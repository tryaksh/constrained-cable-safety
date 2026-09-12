"""Routing worker: does the safety layer still earn its place over a five-clip route?

Everything this repository has measured so far is one connector and one clip. Real
harness work is routing: a cable dressed into a sequence of clips along a board,
then a connector seated at the far end, with every clip expected to still hold
when the job is finished. That is a LONGER chain than the three-decision sequence
the composition study measured, and it is the chain the composition study said
would be the hard one - the clip budget was the constraint that decayed along a
chain, because every accepted step spends slack the next step is judged against.

One request here is one ROUTE. The cable is installed through all five clips of
the CAD-authored cell, settled, and then the supervisor is offered a decision at
each of five registered decision points: the same twelve candidate motions, its
own rule, one motion issued or an abstention. Success is EVERY required clip
still retained AND the connector seated for the declared dwell. All three
constraints are scored continuously across the whole route, and the step and the
clip at which each first went are recorded, so a loss can be attributed.

Three supervisors, all reading the same estimate, all reading the same filter:

``filtered``      the shipped safety layer, issuing the largest motion it calls
                  safe. The composition study's registered supervisor.
``conservative``  the same filter issuing the motion with the most HEADROOM.
                  Same information, different appetite. The composition study
                  found this dominated, post hoc and with no verdict; it is
                  registered here, which is the right way to promote it.
``unfiltered``    issues the largest motion regardless. The reference that says
                  what the filter is worth over a route.

Not official AIC scoring, not a released or latched connection, not learned
pickup, not camera perception and not a hardware claim.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from assembly_recovery.cable_constrained_v2 import (  # noqa: E402
    LOAD_KEYS,
    MutationGuard,
    apply_cartesian_impedance,
    build_scene,
    cable_centerline,
    clip_state,
    measure_loads,
    raw_loads,
)
from assembly_recovery.cable_constraints_v4 import CONSTRAINTS, ConstraintScorer  # noqa: E402
from assembly_recovery.cable_jobs import CableJob, CableJobLimits, CableSample  # noqa: E402
from assembly_recovery.cable_perception_v4 import EpisodePerception, PrivilegeGuard  # noqa: E402
from assembly_recovery.cable_recovery_control_v2 import (  # noqa: E402
    PHASE_CODE,
    ForceGuidedInsertion,
    RecoveryObservation,
    parametric_macro,
    repair_library,
)
from assembly_recovery.cable_safety_filter_v4 import SafetyFilter  # noqa: E402
from assembly_recovery.cable_study_v4 import action_displacement  # noqa: E402
from scripts.evaluate_cable_perception_v4 import (  # noqa: E402
    SERVO_CHANNELS,
    effective_level,
    estimated_observation,
    observed_decision_state,
)
from scripts.evaluate_cable_recovery_v2 import clip_margin, settle, wrist_world, write  # noqa: E402

SUPERVISORS = ("filtered", "conservative", "unfiltered")


def choose(supervisor: str, filter_: SafetyFilter, decision: dict, actions, run_direction_xy,
           level: dict) -> dict:
    """One supervisor's choice at one decision point, with its reasoning kept."""
    if supervisor == "unfiltered":
        axis = np.asarray(decision["insertion_axis"], dtype=float)
        run = np.array([*run_direction_xy, 0.0], dtype=float)
        magnitudes = [float(np.linalg.norm(
            action_displacement(a, axis, run, filter_.retract_distance_m))) for a in actions]
        index = int(np.argmax(magnitudes))
        return {"abstained": False, "action_index": index, "action": actions[index],
                "magnitude_m": magnitudes[index], "headroom_m": None,
                "verdict": {"safe": None, "note": "no filter was consulted"}}
    prefer = "largest" if supervisor == "filtered" else "safest"
    chosen = filter_.best_action(decision, actions, run_direction_xy, level, prefer=prefer)
    if chosen is None:
        return {"abstained": True, "action_index": None, "action": None,
                "magnitude_m": None, "headroom_m": None,
                "verdict": {"safe": False, "note": "the filter called no candidate safe"}}
    return {"abstained": False, "action_index": chosen["index"], "action": chosen["action"],
            "magnitude_m": chosen["magnitude_m"], "headroom_m": chosen["headroom_m"],
            "verdict": chosen["verdict"]}


def clip_snapshot(state: dict) -> dict:
    """The per-clip retention picture, small enough to store at every step."""
    return {"retained": [c["id"] for c in state["per_clip"] if c["has_retained_passage"]],
            "lost": state["summary"]["lost_required_ids"],
            "required_retained": state["summary"]["required_retained"],
            "required_count": state["summary"]["required_count"]}


def run_case(cfg, case, directory: Path, observer=None) -> dict:
    """Run one registered route.

    ``observer``, when given, is called once per servo tick with a read-only view
    of the tick. It exists so a replay can record dense state from THIS loop
    rather than from a copy of it: a copy that drew one extra random number would
    silently be showing a different rollout. It is called after the control step,
    outside the mutation guard, and it draws nothing from the perception stream.
    """
    directory.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    cfg = {**cfg, "clocks": {**cfg["clocks"], **case.get("clocks_override", {})},
           "cable": {**cfg["cable"], **case.get("cable_overrides", {})}}
    scene = build_scene(ROOT, cfg, case, directory)
    build_seconds = time.monotonic()-started
    data = scene.data
    physics = cfg["clocks"]["physics_hz"]
    dt = 1.0/physics
    servo_every = round(physics/cfg["clocks"]["servo_hz"])
    policy_every = round(physics/cfg["clocks"]["policy_hz"])
    limits = CableJobLimits(**{**cfg["job_limits"], **case.get("job_limits_override", {})})
    job = CableJob(limits)
    settle_steps, settled, settle_reason = settle(scene, cfg)
    guard = MutationGuard(scene)
    privilege = PrivilegeGuard()
    bias = wrist_world(scene).copy()
    if not settled:
        job.fail(settle_reason)

    level = effective_level(cfg, case)
    perception = EpisodePerception(level, scene.fixture, cfg["perception"]["camera"],
                                   int(case["perception_seed"]), servo_every*dt,
                                   len(cable_centerline(scene)))
    constraints = cfg["constraints"]
    scorer = ConstraintScorer(
        bend_radius_spec_m=float(constraints["C2_bend"]["spec_m"]),
        anchor_limit_n=float(constraints["C3_anchor"]["limit_n"]),
        bend_radius_secondary_m=float(constraints["C2_bend"]["secondary_m"]),
        anchor_secondary_n=float(constraints["C3_anchor"]["secondary_n"]),
        segment_length_m=float(cfg["cable"]["segment_length_m"]),
        max_turn_deg=float(cfg["cable"]["max_initial_turn_deg"]))

    filter_ = SafetyFilter.from_evidence(ROOT / cfg["safety_filter"]["fit"],
                                         ROOT / cfg["safety_filter"]["contract"],
                                         ROOT / cfg["safety_filter"]["base"])
    candidates = cfg["route"]["candidate_actions"]
    step_times = list(cfg["route"]["decision_times_s"])
    supervisor = case["supervisor"]
    run_direction = np.array([*case["run_direction_xy"], 0.0])
    estimated_axis = perception.insertion_axis(scene.insertion_axis)
    controller = ForceGuidedInsertion(cfg["force_guided_controller"], scene.initial_tip,
                                      estimated_axis)
    macros = repair_library(cfg["repair_library"])

    native = np.zeros((round(limits.deadline_s*physics)+2, 4))
    servo = np.zeros((round(limits.deadline_s*cfg["clocks"]["servo_hz"])+2, SERVO_CHANNELS))
    native_rows = servo_rows = steps = 0
    target = scene.initial_tip.copy()
    peaks = dict.fromkeys(LOAD_KEYS, 0.0)
    axis, initial_tip = scene.insertion_axis, scene.initial_tip
    cable_bodies = np.asarray(scene.cable_bodies)
    history: list[dict] = []
    history_cfg = cfg["perception"]["history"]
    history_stride = max(1, round(history_cfg["stride_s"]*cfg["clocks"]["servo_hz"]))
    issued: list[dict] = []
    pending_step: int | None = None
    first_violation: dict = {}
    #: When each required clip first went, and which step was running at the time.
    #: A five-clip route can lose a clip the supervisor never touched, so a clip
    #: loss has to be attributed to a clip as well as to a step.
    clip_loss: dict = {}
    step_index = 0
    repair_start_tip = None
    servo_tick = 0
    phase = "align"
    installed = None
    total = round(limits.deadline_s*physics) if settled else 0

    for i in range(total):
        job_time = i*dt
        if i % servo_every == 0:
            centreline = cable_centerline(scene)
            state = clip_state(scene, centreline)
            summary = state["summary"]
            if installed is None:
                installed = clip_snapshot(state)
            loads = measure_loads(scene)
            reaction = np.asarray(loads["anchor_constraint_world_n"])
            truth = RecoveryObservation(
                job_time, data.site_xpos[scene.tip_site].copy(),
                data.site_xmat[scene.tip_site].reshape(3, 3).copy(),
                data.site_xpos[scene.port_site].copy(), axis, wrist_world(scene).copy(), bias,
                loads["plug_port_contact_n"], loads["cable_clip_contact_n"],
                loads["cable_post_contact_n"], reaction, centreline,
                summary["all_required_retained"], clip_margin(scene, state, centreline),
                job.first_witness_s is not None)
            perception.advance()
            estimate, weights = estimated_observation(scene, perception, truth, privilege)
            progress = (0.0 if repair_start_tip is None
                        else float(np.linalg.norm(truth.tip_position-repair_start_tip)))
            scorer.update(centreline, float(np.linalg.norm(reaction)),
                          bool(summary["all_required_retained"]), progress)
            for entry in state["per_clip"]:
                if entry["required"] and not entry["has_retained_passage"] \
                        and entry["id"] not in clip_loss:
                    clip_loss[entry["id"]] = {"time_s": job_time,
                                              "during_step": max(step_index-1, -1),
                                              "steps_issued_so_far":
                                                  sum(1 for r in issued if r.get("requested"))}
            went = {
                "C1_clip": not summary["all_required_retained"],
                "C2_bend": scorer.min_bend_radius_m < scorer.bend_radius_spec_m,
                "C3_anchor": scorer.peak_anchor_n > scorer.anchor_limit_n,
            }
            for name, broken in went.items():
                if broken and name not in first_violation:
                    first_violation[name] = {"time_s": job_time,
                                             "during_step": max(step_index-1, -1),
                                             "steps_issued_so_far":
                                                 sum(1 for r in issued if r.get("requested"))}
            if level.process_force_n:
                data.xfrc_applied[cable_bodies, :3] = (perception.process_force_world_n
                                                       / len(cable_bodies))
            if servo_tick % history_stride == 0:
                history.append({"time_s": job_time})
                del history[:-int(history_cfg["length"])]
            guard.before_control()
            privilege.arm()
            if i % policy_every == 0:
                idle = controller.phase not in ("retract", "repair")
                due = step_index < len(step_times) and job_time >= step_times[step_index]
                if due and idle and not controller.terminal:
                    decision = observed_decision_state(scene, estimate, loads, perception,
                                                       weights, list(history))
                    pick = choose(supervisor, filter_, decision, candidates,
                                  case["run_direction_xy"], dict(level.__dict__))
                    record = {"step": step_index, "time_s": job_time, **pick,
                              "state_before": {
                                  "clips": clip_snapshot(state),
                                  "min_bend_radius_m": (None
                                                        if not np.isfinite(scorer.min_bend_radius_m)
                                                        else scorer.min_bend_radius_m),
                                  "peak_anchor_n": scorer.peak_anchor_n,
                                  "already_violated": sorted(first_violation)},
                              "decision_boot_to_anchor_m": decision["boot_to_anchor_m"]}
                    if pick["action"] is not None:
                        # What the shipped layer says this motion SPENDS. A route
                        # is exactly the case where an individually safe step can
                        # leave the next one nothing, so the spend is the number
                        # the workbench has to be able to draw.
                        record["budget"] = filter_.budget(decision, pick["action"],
                                                          case["run_direction_xy"],
                                                          dict(level.__dict__))
                        record["endpoint_boot_to_anchor_m"] = filter_.endpoint_distance_m(
                            decision, pick["action"], case["run_direction_xy"])
                    else:
                        record["budget"] = None
                        record["endpoint_boot_to_anchor_m"] = None
                    record["motion_completed"] = False
                    if pick["action"] is not None:
                        macro = parametric_macro(pick["action"])
                        macros[f"route{step_index}"] = macro
                        record["requested"] = bool(controller.request_repair(
                            macro, estimate.tip_position, run_direction, job_time))
                        if record["requested"]:
                            repair_start_tip = np.asarray(truth.tip_position, dtype=float).copy()
                    else:
                        record["requested"] = False
                    issued.append(record)
                    if record["requested"]:
                        pending_step = step_index
                    step_index += 1
                target, phase, _ = controller.step(estimate, policy_every*dt)
                if pending_step is not None and phase not in ("retract", "repair"):
                    issued[pending_step]["motion_completed"] = True
                    issued[pending_step]["state_after"] = {
                        "clips": clip_snapshot(state),
                        "min_bend_radius_m": (None if not np.isfinite(scorer.min_bend_radius_m)
                                              else scorer.min_bend_radius_m),
                        "peak_anchor_n": scorer.peak_anchor_n,
                        "time_s": job_time}
                    pending_step = None
            privilege.disarm()
            apply_cartesian_impedance(scene, target, scene.target_rotation, cfg["controller"])
            guard.after_control()
            angle = float(np.arccos(np.clip(
                (np.trace(truth.tip_rotation.T @ scene.target_rotation)-1)/2, -1, 1)))
            sample = CableSample(
                job_time+servo_every*dt, servo_every*dt,
                float(np.linalg.norm(truth.tip_position-truth.seated_position)), angle,
                float((truth.tip_position-initial_tip) @ axis),
                float((target-initial_tip) @ axis),
                loads["raw_wrist_load_n"], loads["raw_plug_load_n"],
                float(np.linalg.norm(reaction)), loads["plug_port_contact_n"],
                loads["cable_post_contact_n"], bool(summary["all_required_retained"]), True,
                loads["port_detector_contact_n"] > limits.contact_witness_n, guard.events)
            job.update(sample)
            for key in peaks:
                peaks[key] = max(peaks[key], loads[key])
            servo[servo_rows] = [job_time, *truth.tip_position, *target,
                                 sample.seating_error_m, angle, sample.insertion_depth_m,
                                 sample.commanded_depth_m, *[loads[k] for k in LOAD_KEYS],
                                 *reaction, float(sample.clip_retained),
                                 float(summary["required_retained"]), guard.events,
                                 PHASE_CODE.get(phase, len(PHASE_CODE))]
            servo_rows += 1
            servo_tick += 1
            if observer is not None:
                observer({"tick": servo_tick-1, "native_step": i, "time_s": job_time,
                          "scene": scene, "state": state, "centreline": centreline,
                          "estimate": estimate, "weights": weights, "truth": truth,
                          "scorer": scorer, "loads": loads, "phase": phase,
                          "target": target, "step_index": step_index, "issued": issued,
                          "progress": progress, "job": job})
            if not summary["all_required_retained"] and job.status == "active":
                job.fail("lost_required_clip")
            elif getattr(controller, "terminal", False) and job.status == "active":
                job.fail("controller_"+phase)
        mujoco.mj_step(scene.model, data)
        steps += 1
        wrist, plug, anchor = raw_loads(scene)
        native[native_rows] = [job_time, wrist, plug, anchor]
        native_rows += 1
        if wrist > limits.wrist_force_n or plug > limits.plug_force_n:
            job.fail("force_abort")
        elif anchor > limits.anchor_force_n:
            job.fail("prior_connection_load_abort")
        if job.status != "active":
            break
    data.xfrc_applied[:] = 0.0
    if job.status == "active" and settled:
        job.fail("deadline")
    mujoco.mj_forward(scene.model, data)
    terminal = clip_state(scene)
    completed_steps = sum(1 for r in issued if r.get("requested"))
    finished_steps = sum(1 for r in issued if r.get("motion_completed"))
    move_completed = bool(settled and job.failure_reason not in (
        "force_abort", "prior_connection_load_abort", "nonfinite_dynamics", "deadline"))
    labels = scorer.labels(move_completed, terminal["summary"]["all_required_retained"])
    attribution = {name: {"state": labels[name]["state"], **first_violation.get(name, {})}
                   for name in CONSTRAINTS}
    seated = job.status == "completed"
    route_completed = bool(seated and terminal["summary"]["all_required_retained"])
    np.savez_compressed(
        directory / "ledger.npz", native=native[:native_rows], servo=servo[:servo_rows],
        native_channels=np.asarray(cfg["ledger"]["native_channels"]),
        servo_channels=np.asarray(cfg["ledger"]["servo_channels"]),
        terminal_centerline=cable_centerline(scene))
    wall = time.monotonic()-started
    outcome = {
        "case": case, "controller": "route_supervisor", "supervisor": supervisor,
        "status": "completed", "job": job.report(), "settled": settled,
        "settle_reason": settle_reason,
        "seated": seated,
        "route_completed": route_completed,
        "installed_clips": installed,
        "terminal_clips": clip_snapshot(terminal),
        "terminal_clip_retained": terminal["summary"]["all_required_retained"],
        "clip_loss_attribution": clip_loss,
        "error_level": case["error_level"], "error_isolation": "all",
        "steps_offered": len(step_times), "steps_issued": completed_steps,
        "steps_completed": finished_steps,
        "abstentions": sum(1 for r in issued if r["abstained"]),
        "issued": issued, "constraints": labels, "constraint_report": scorer.report(),
        "attribution": attribution, "move_completed": move_completed,
        "peak_loads": peaks, "mutation_guard": guard.report(),
        "privilege_guard": privilege.report(),
        "filter": filter_.report(),
        "cell": {"id": case.get("cell"), "clips": [c["id"] for c in scene.clips],
                 "required": [c["id"] for c in scene.clips if c["required"]],
                 "cad_visuals": scene.fixture.get("cad_visuals", []),
                 "solved_anchor_along_m": scene.fixture["solved_anchor_along_m"]},
        "accounting": {"native_steps": steps, "settle_native_steps": settle_steps,
                       "servo_ticks": servo_rows, "model_compilations": 2,
                       "build_seconds": build_seconds, "wall_seconds": wall,
                       "native_steps_per_second": (steps+settle_steps)/max(wall-build_seconds, 1e-9)},
        "scope": [
            "One request is one ROUTE through a five-clip cell, not one motion and not a "
            "three-motion sequence. It is a genuine EXTENSION of held, clip-preserving seating: "
            "the endpoint now requires EVERY required clip of the route to still be held, not "
            "one. It is not a relabelling of an earlier block and no earlier block is rescored "
            "under it.",
            "Every supervisor reads the declared ESTIMATE; ground truth is scoring-only.",
            "The filter is loaded from the perception study's evidence record and is NOT refitted "
            "here. It was fitted on single-clip layouts, so this cell is new geometry to it, and "
            "that is part of what is being measured.",
            "The CAD cell is visual geometry. The cable collides with the primitives every "
            "earlier block was measured against.",
            "Simulation only. No hardware claim.",
        ],
    }
    if privilege.events:
        outcome["job"]["status"] = "failed"
        outcome["job"]["failure_reason"] = "privilege_violation"
    write(directory / "result.json", outcome)
    print(json.dumps({"case": case["id"], "supervisor": supervisor,
                      "status": outcome["job"]["status"], "reason": outcome["job"]["failure_reason"],
                      "issued": completed_steps, "finished": finished_steps,
                      "abstained": outcome["abstentions"],
                      "kept": outcome["terminal_clips"]["required_retained"],
                      "route": route_completed,
                      **{k: labels[k]["state"] for k in CONSTRAINTS}}), flush=True)
    return outcome


def guarded_case(cfg, case, directory: Path, observer=None) -> dict:
    try:
        return run_case(cfg, case, directory, observer)
    except (ValueError, KeyError) as exc:
        directory.mkdir(parents=True, exist_ok=True)
        censored = {name: {"state": "censored", "violation_progress_m": None,
                           "censoring_progress_m": 0.0} for name in CONSTRAINTS}
        outcome = {"case": case, "supervisor": case.get("supervisor"), "status": "completed",
                   "job": {"status": "failed", "failure_reason": "construction_infeasible",
                           "elapsed_s": 0.0, "dwell_s": 0.0, "first_witness_s": None,
                           "witness_type": None, "samples": 0},
                   "settled": False, "settle_reason": "construction_infeasible",
                   "construction_error": f"{type(exc).__name__}: {exc}",
                   "seated": False, "route_completed": False,
                   "terminal_clip_retained": False, "terminal_clips": None,
                   "installed_clips": None, "clip_loss_attribution": {},
                   "error_level": case.get("error_level"),
                   "steps_offered": 0, "steps_issued": 0, "steps_completed": 0,
                   "abstentions": 0, "issued": [],
                   "constraints": censored, "attribution": {}, "move_completed": False,
                   "mutation_guard": {"events": 0},
                   "privilege_guard": {"events": 0, "reasons": [], "verdict": "clean"},
                   "accounting": {"native_steps": 0, "settle_native_steps": 0, "servo_ticks": 0,
                                  "model_compilations": 0, "build_seconds": 0.0,
                                  "wall_seconds": 0.0, "native_steps_per_second": 0.0},
                   "scope": ["Infeasible construction retained in the all-request denominator."]}
        write(directory / "result.json", outcome)
        print(json.dumps({"case": case["id"], "status": "failed",
                          "reason": "construction_infeasible"}), flush=True)
        return outcome


def _worker(item):
    return guarded_case(*item)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--case")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8-sig"))
    cases = [c for c in cfg["cases"] if not args.case or c["id"] == args.case]
    if not cases:
        parser.error("No selected cases")
    args.run_dir.mkdir(parents=True, exist_ok=True)
    if args.workers > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            outcomes = list(pool.map(_worker, [(cfg, c, args.run_dir / c["id"]) for c in cases]))
    else:
        outcomes = [guarded_case(cfg, c, args.run_dir / c["id"]) for c in cases]
    write(args.run_dir / "result.json", {
        "status": "completed", "scope": cfg["scope"], "config_id": cfg["id"], "cases": outcomes,
        "expected_requests": len(cases),
        "accounting": {
            "native_steps": sum(o["accounting"]["native_steps"] for o in outcomes),
            "settle_native_steps": sum(o["accounting"]["settle_native_steps"] for o in outcomes),
            "wall_seconds": sum(o["accounting"]["wall_seconds"] for o in outcomes),
            "training_runs": 0,
        },
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
