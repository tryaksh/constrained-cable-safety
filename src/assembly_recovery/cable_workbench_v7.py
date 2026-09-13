"""The workbench session: load the measured cell, change it, and run it again.

Everything the routing study measured is a statement about one jig. The obvious
next question an engineer has is "what about mine?", and the honest answer is
that nobody knows until it is run. This is the object that lets them run it:
load the registered cell, move a clip or change the service loop, pick an error
level and a supervisor, ask the shipped safety layer what it would allow, and
route through it.

Nothing here is a study result. A session that has been mutated is a DIFFERENT
CELL from the one the block measured, and it says so in every report it writes.

Two rules the class exists to enforce:

**A cell that compiles is not a cell that installs.** Moving a clip invalidates
the screen, and the session refuses to route until the screen has been re-run and
passed. The registered screen rejected 19 of the 28 cells it was given; a cell
that fails it is not a harder cell, it is one the cable never gets into.

**One place expands a contract into a request.** The session does not build its
own request dictionaries: it calls the launcher's own expansion, with the cell it
is actually holding, so a request run here is byte-for-byte the request the block
would have run. That is what makes reproducing a committed result meaningful.

The viewer is deliberately not in here. This class is headless and testable; the
window is a thin shell over it in scripts/workbench.py.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

#: Where the session reads its inputs. All committed, all named by the contract.
PATHS = {
    "contract": "configs/cable_routing_v6.json",
    "candidates": "configs/cable_cell_v6_candidates.json",
    "screen": "evidence/cable_cell_screen_v6.json",
    "cad": "evidence/cable_cell_cad_v6.json",
    "perception": "configs/cable_perception_v4.json",
}

#: What a clip may be moved by. Bearing is in radians, the rest in metres, and
#: they are the same names the candidate file uses, because moving a clip in the
#: workbench and moving one in the config have to mean the same thing.
MOVABLE = ("along_m", "across_m", "up_m", "bearing_rad")

SUPERVISORS = ("filtered", "conservative", "unfiltered")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


@dataclass
class WorkbenchSession:
    """One loaded cell, its settings, and everything that can be asked of it."""

    root: Path
    contract: dict
    candidates: dict
    screen: dict
    cad: dict
    perception: dict
    base: dict
    layout: dict
    loop_m: float
    error_level: str = "E2"
    supervisor: str = "conservative"
    port_mount: str = "compliant4000"
    mount_offset_index: int = 0
    repeat: int = 0
    mutations: list = field(default_factory=list)
    screen_result: dict | None = None

    # ---------------------------------------------------------------- loading

    @classmethod
    def open(cls, root: Path, cell: str | None = None, loop_m: float | None = None,
             error_level: str = "E2", supervisor: str = "conservative") -> WorkbenchSession:
        """Load the registered cell, or a named candidate, at an accepted loop."""
        root = Path(root)
        contract = read_json(root / PATHS["contract"])
        candidates = read_json(root / PATHS["candidates"])
        screen = read_json(root / PATHS["screen"])
        cad = read_json(root / PATHS["cad"])
        perception = read_json(root / PATHS["perception"])
        base = read_json(root / contract["base_config"]["path"])
        cell = cell or contract["cell"]["registered_cell"]
        layout = next((e for e in candidates["layouts"] if e["id"] == cell), None)
        if layout is None:
            raise ValueError(f"{cell!r} is not a declared cell in {PATHS['candidates']}")
        loops = cls._accepted_loops(screen, cell)
        if loop_m is None:
            if not loops:
                raise ValueError(f"The screen accepted no service loop for {cell!r}")
            loop_m = loops[len(loops)//2]
        session = cls(root=root, contract=contract, candidates=copy.deepcopy(candidates),
                      screen=screen, cad=cad, perception=perception, base=base,
                      layout=copy.deepcopy(layout), loop_m=float(loop_m))
        session.set_level(error_level)
        session.set_supervisor(supervisor)
        if float(loop_m) not in loops:
            # Not refused: an unaccepted loop is a legitimate thing to explore.
            # It is recorded as a mutation so no report can call it registered.
            session.mutations.append({"what": "service loop", "loop_m": float(loop_m),
                                      "note": "not one of the loops the screen accepted"})
        else:
            session.screen_result = cls._accepted_entry(screen, cell, float(loop_m))
        return session

    @staticmethod
    def _accepted_loops(screen: dict, cell: str) -> list[float]:
        return sorted(float(e["installed_loop_m"]) for e in screen["accepted_cell_detail"]
                      if e["layout"] == cell)

    @staticmethod
    def _accepted_entry(screen: dict, cell: str, loop_m: float) -> dict | None:
        for entry in screen["accepted_cell_detail"]:
            if entry["layout"] == cell and float(entry["installed_loop_m"]) == loop_m:
                return {**entry, "source": PATHS["screen"], "rerun_here": False,
                        "passes": True}
        return None

    # --------------------------------------------------------------- settings

    @property
    def cell_id(self) -> str:
        return self.layout["id"]

    @property
    def mutated(self) -> bool:
        return bool(self.mutations)

    @property
    def needs_screening(self) -> bool:
        """True when nothing on disk or in this session says this cell installs."""
        return not (self.screen_result and self.screen_result.get("passes"))

    def set_level(self, level: str) -> str:
        declared = [entry["id"] for entry in self.perception["error_model"]["levels"]]
        if level not in declared:
            raise ValueError(f"{level!r} is not a declared error level; choose from {declared}")
        self.error_level = level
        return level

    def set_supervisor(self, supervisor: str) -> str:
        if supervisor not in SUPERVISORS:
            raise ValueError(f"{supervisor!r} is not a registered supervisor; "
                             f"choose from {list(SUPERVISORS)}")
        self.supervisor = supervisor
        return supervisor

    def set_loop(self, loop_m: float) -> dict:
        """Change the installed service loop. Invalidates the screen."""
        loop_m = float(loop_m)
        before = self.loop_m
        self.loop_m = loop_m
        self.screen_result = None
        change = {"what": "service loop", "from_m": before, "to_m": loop_m}
        self.mutations.append(change)
        return change

    def move_clip(self, clip_id: str, **deltas) -> dict:
        """Move one clip. Absolute values, in the candidate file's own units.

        The screen is invalidated, because a clip that has moved is a cell nobody
        has settled a cable into yet. Whether it compiles says nothing about it.
        """
        unknown = sorted(set(deltas)-set(MOVABLE))
        if unknown:
            raise ValueError(f"A clip has no {unknown}; movable fields are {list(MOVABLE)}")
        clip = next((c for c in self.layout["clips"] if c["id"] == clip_id), None)
        if clip is None:
            raise ValueError(f"{clip_id!r} is not a clip of {self.cell_id}; this cell has "
                             f"{[c['id'] for c in self.layout['clips']]}")
        before = {key: clip[key] for key in deltas}
        for key, value in deltas.items():
            clip[key] = float(value)
        self.layout["clips"].sort(key=lambda c: c["along_m"])
        self._rebuild_waypoints()
        self._sync_candidates()
        self.screen_result = None
        change = {"what": "clip", "clip": clip_id, "from": before,
                  "to": {key: clip[key] for key in deltas}}
        self.mutations.append(change)
        return change

    def add_clip(self, clip_id: str, along_m: float, across_m: float = 0.0,
                 up_m: float = 0.0, bearing_rad: float = 0.0, **shape) -> dict:
        """Put another clip in the route, with the waypoint that threads it.

        A clip with no waypoint is a clip the cable never goes through, so the
        install waypoint is added with it, at the clearance the registered route
        uses above every clip floor. Clips and waypoints are kept in order along
        the board, because that order is the order the cable is threaded in.
        """
        if any(c["id"] == clip_id for c in self.layout["clips"]):
            raise ValueError(f"{clip_id!r} is already a clip of {self.cell_id}")
        template = {k: v for k, v in self.layout["clips"][0].items()
                    if k not in ("id", *MOVABLE)}
        unknown = sorted(set(shape)-set(template))
        if unknown:
            raise ValueError(f"A clip has no {unknown}; its shape fields are "
                             f"{sorted(template)}")
        clip = {"id": clip_id, "along_m": float(along_m), "across_m": float(across_m),
                "up_m": float(up_m), "bearing_rad": float(bearing_rad),
                **template, **{k: float(v) for k, v in shape.items()}}
        self.layout["clips"].append(clip)
        self.layout["clips"].sort(key=lambda c: c["along_m"])
        self._rebuild_waypoints()
        self._sync_candidates()
        self.screen_result = None
        change = {"what": "clip added", "clip": clip_id,
                  "at": {key: clip[key] for key in MOVABLE}}
        self.mutations.append(change)
        return change

    def remove_clip(self, clip_id: str) -> dict:
        """Take a clip out of the route, and its waypoint with it."""
        clips = self.layout["clips"]
        if len(clips) <= 1:
            raise ValueError("A route needs at least one clip")
        clip = next((c for c in clips if c["id"] == clip_id), None)
        if clip is None:
            raise ValueError(f"{clip_id!r} is not a clip of {self.cell_id}; this cell has "
                             f"{[c['id'] for c in clips]}")
        clips.remove(clip)
        self._rebuild_waypoints()
        self._sync_candidates()
        self.screen_result = None
        change = {"what": "clip removed", "clip": clip_id,
                  "was_at": {key: clip[key] for key in MOVABLE}}
        self.mutations.append(change)
        return change

    def _rebuild_waypoints(self) -> None:
        """One install waypoint per clip, at the registered clearance above its floor."""
        from assembly_recovery.cable_cell_v6 import ROUTE_CLEARANCE_M

        self.layout["route_waypoints_along_across_m"] = [
            [clip["along_m"], clip["across_m"], clip["up_m"]+ROUTE_CLEARANCE_M]
            for clip in sorted(self.layout["clips"], key=lambda c: c["along_m"])]

    def _sync_candidates(self) -> None:
        """Keep the candidate file this session expands from in step with the layout."""
        for index, entry in enumerate(self.candidates["layouts"]):
            if entry["id"] == self.cell_id:
                self.candidates["layouts"][index] = copy.deepcopy(self.layout)
                return
        self.candidates["layouts"].append(copy.deepcopy(self.layout))

    # ----------------------------------------------------------------- screen

    def run_screen(self) -> dict:
        """Settle a cable into this cell and decide whether it installs at all.

        The registered screen, applied to whatever this session is now holding.
        Takes about six seconds and needs the simulator.
        """
        from scripts.screen_cell_v6 import cell_fails, screen_one

        record = screen_one(self.layout, self.loop_m, self.base, self.candidates)
        reason = cell_fails(record, float(self.candidates["c2_spec_m"]))
        self.screen_result = {
            **{key: record[key] for key in record if key not in ("per_clip", "lateral_wall_gaps")},
            "per_clip": record.get("per_clip"),
            "passes": reason is None, "reason_rejected": reason,
            "source": "re-run in this session", "rerun_here": True,
        }
        return self.screen_result

    # ---------------------------------------------------------------- request

    def case(self) -> dict:
        """The one registered request these settings name.

        Expanded by the launcher's own code, from the cell this session holds, so
        an unmutated session produces the request the block actually ran - same
        id, same seeds, same overrides.
        """
        # Imported here rather than at module scope: this module is imported by
        # tests that have no simulator, and one expansion is better than two.
        from scripts.run_routing_v6 import build_cases

        screen = self._screen_for_expansion()
        cases = build_cases(self.contract, self.candidates, self.base, screen, self.cad,
                            self.perception)
        wanted = (f"{self._group_id()}_{self.port_mount}_m{self.mount_offset_index}"
                  f"_{self.error_level}_{self.supervisor}_r{self.repeat}")
        case = next((c for c in cases if c["id"] == wanted), None)
        if case is None:
            raise ValueError(f"No request {wanted!r}; the expansion produced "
                             f"{len(cases)} requests for this cell")
        return case

    def runtime(self) -> dict:
        """The merged runtime the worker reads, carrying exactly this one request."""
        from scripts.run_routing_v6 import merge_runtime

        runtime = merge_runtime(self.base, self.contract, self.candidates,
                                self._screen_for_expansion(), self.cad, self.perception)
        runtime["cases"] = [self.case()]
        runtime["workbench"] = self.provenance()
        return runtime

    def _group_id(self) -> str:
        from assembly_recovery.cable_cell_v6 import group_id

        return group_id(self.cell_id, self.loop_m)

    def _screen_for_expansion(self) -> dict:
        """The screen record the launcher's expansion reads.

        An UNMUTATED session hands over the committed screen whole. That matters
        more than it looks: the expansion walks the accepted groups in order and
        increments one seed counter as it goes, so narrowing the list would give
        every group but the first different seeds, and the request would stop
        being the request the block ran.

        A MUTATED cell is not in the committed screen at all, so there the record
        is narrowed to the one group this session is holding. Its seeds are then
        its own, which costs nothing, because a moved clip has no committed
        result to be compared against.
        """
        if self.needs_screening:
            raise RuntimeError(
                "This cell has not passed a screen. A cell that compiles is not a cell that "
                "installs - the registered screen rejected 19 of 28 declared cells. "
                "Call run_screen() first.")
        group = self._group_id()
        registered = any(entry["group"] == group and entry["layout"] == self.cell_id
                         for entry in self.screen["accepted_cell_detail"])
        if registered and not self.mutated:
            return self.screen
        entry = {"group": group, "layout": self.cell_id,
                 "installed_loop_m": self.loop_m, "clips": len(self.layout["clips"])}
        return {**self.screen, "accepted_cell_detail": [entry],
                "accepted_groups": [entry["group"]]}

    # -------------------------------------------------------------- the layer

    def allowed(self, resolution: int = 16) -> dict:
        """What the shipped safety layer permits here, over the whole action space.

        Settles the cell, takes one perception draw at the declared level, and
        asks the filter about every registered candidate motion and about a grid
        over retreat, bearing and excursion. Geometry only: this is what the
        fitted rule allows, not what the physics permits, and the study's
        false-safe rate is the measure of how often those differ.
        """
        import numpy as np

        from assembly_recovery.cable_constrained_v2 import (
            cable_centerline,
            clip_state,
            measure_loads,
        )
        from assembly_recovery.cable_perception_v4 import EpisodePerception
        from assembly_recovery.cable_recovery_control_v2 import RecoveryObservation
        from assembly_recovery.cable_safety_filter_v4 import SafetyFilter
        from scripts.evaluate_cable_perception_v4 import (
            effective_level,
            estimated_observation,
            observed_decision_state,
        )
        from scripts.evaluate_cable_recovery_v2 import clip_margin, wrist_world

        scene, runtime, case = self._settled()
        level = effective_level(runtime, case)
        servo_dt = 1.0/runtime["clocks"]["servo_hz"]
        centreline = cable_centerline(scene)
        perception = EpisodePerception(level, scene.fixture, runtime["perception"]["camera"],
                                       int(case["perception_seed"]), servo_dt, len(centreline))
        state = clip_state(scene, centreline)
        loads = measure_loads(scene)
        reaction = np.asarray(loads["anchor_constraint_world_n"])
        data = scene.data
        truth = RecoveryObservation(
            0.0, data.site_xpos[scene.tip_site].copy(),
            data.site_xmat[scene.tip_site].reshape(3, 3).copy(),
            data.site_xpos[scene.port_site].copy(), scene.insertion_axis,
            wrist_world(scene).copy(), wrist_world(scene).copy(),
            loads["plug_port_contact_n"], loads["cable_clip_contact_n"],
            loads["cable_post_contact_n"], reaction, centreline,
            state["summary"]["all_required_retained"], clip_margin(scene, state, centreline),
            False)
        perception.advance()
        estimate, weights = estimated_observation(scene, perception, truth, None)
        decision = observed_decision_state(scene, estimate, loads, perception, weights, [])

        filter_ = SafetyFilter.from_evidence(self.root / runtime["safety_filter"]["fit"],
                                             self.root / runtime["safety_filter"]["contract"],
                                             self.root / runtime["safety_filter"]["base"])
        run_direction = case["run_direction_xy"]
        declared = dict(level.__dict__)
        candidates = []
        for index, action in enumerate(runtime["route"]["candidate_actions"]):
            verdict = filter_.verdict(decision, action, run_direction, declared)
            budget = filter_.budget(decision, action, run_direction, declared)
            candidates.append({
                "index": index, "action": action,
                "safe": bool(verdict["safe"]),
                "binding_constraint": verdict.get("binding"),
                "headroom_m": min((v["headroom_m"] for v in verdict["constraints"].values()
                                   if v["state"] != "unscored"), default=None),
                "spent_fraction": {name: entry["spent_fraction"]
                                   for name, entry in budget.items()},
            })
        retreats = [action["retreat_m"] for action in runtime["route"]["candidate_actions"]]
        envelope = filter_.envelope(
            decision, run_direction, declared,
            {"retreat_m": [0.0, max(retreats)], "excursion_m": [0.0, 0.06]},
            resolution=resolution)
        return {
            "cell": self.cell_id, "installed_loop_m": self.loop_m,
            "error_level": self.error_level,
            "mutated": self.mutated,
            "boot_to_anchor_m": decision["boot_to_anchor_m"],
            "candidates": candidates,
            "permitted_of_registered": sum(1 for c in candidates if c["safe"]),
            "registered_candidates": len(candidates),
            "envelope": {key: envelope[key] for key in
                         ("constraint", "effective_threshold_m", "safe_fraction",
                          "largest_safe_retreat_m", "largest_safe_excursion_m", "note")},
            "filter": filter_.report(),
            "scope": "What the FITTED RULE allows, from geometry. Not what the physics permits, "
                     "and not a safety guarantee.",
        }

    def _settled(self, directory: Path | None = None):
        """A compiled, settled scene for the current settings."""
        from assembly_recovery.cable_constrained_v2 import build_scene
        from scripts.evaluate_cable_recovery_v2 import settle

        runtime = self.runtime()
        case = runtime["cases"][0]
        merged = {**runtime,
                  "clocks": {**runtime["clocks"], **case.get("clocks_override", {})},
                  "cable": {**runtime["cable"], **case.get("cable_overrides", {})}}
        directory = Path(directory or (self.root / "artifacts/workbench" / case["id"]))
        directory.mkdir(parents=True, exist_ok=True)
        scene = build_scene(self.root, merged, case, directory)
        steps, settled, reason = settle(scene, merged)
        if not settled:
            raise RuntimeError(f"This cell did not settle: {reason}")
        del steps
        return scene, runtime, case

    # -------------------------------------------------------------------- run

    def run(self, directory: Path | None = None, observer=None) -> dict:
        """Route through this cell once and report what it cost.

        Runs the block's worker, unchanged, on the one request these settings
        name. On an unmutated session that request is the registered one, so the
        outcome can be - and in the self-check is - compared against the result
        the block committed.
        """
        from scripts.evaluate_cable_routing_v6 import run_case

        runtime = self.runtime()
        case = runtime["cases"][0]
        directory = Path(directory or (self.root / "artifacts/workbench" / case["id"]))
        outcome = run_case(runtime, case, directory, observer)
        return self.summarise(outcome, directory)

    def summarise(self, outcome: dict, directory: Path) -> dict:
        """The report: what happened, and what each constraint's budget paid for it."""
        steps = []
        for record in outcome["issued"]:
            budget = record.get("budget") or {}
            steps.append({
                "step": record["step"], "time_s": record["time_s"],
                "abstained": record["abstained"],
                "action_index": record["action_index"],
                "commanded_m": record["magnitude_m"],
                "headroom_m": record["headroom_m"],
                "motion_completed": record["motion_completed"],
                "clips_before": record["state_before"]["clips"]["required_retained"],
                "spent": {name: {"headroom_at_decision_m": entry["headroom_at_decision_m"],
                                 "spent_m": entry["spent_by_this_motion_m"],
                                 "spent_fraction": entry["spent_fraction"],
                                 "headroom_left_m": entry["headroom_left_m"],
                                 "units": entry["units"]}
                          for name, entry in budget.items()},
            })
        totals = {}
        for name in ("C1_clip", "C2_bend", "C3_anchor"):
            spends = [s["spent"][name]["spent_m"] for s in steps if name in s["spent"]]
            fractions = [s["spent"][name]["spent_fraction"] for s in steps if name in s["spent"]]
            totals[name] = {
                "motions_scored": len(spends),
                "total_spent_m": sum(spends),
                "largest_single_spend_fraction": max(fractions) if fractions else None,
                "final_headroom_left_m": (steps[-1]["spent"][name]["headroom_left_m"]
                                          if steps and name in steps[-1]["spent"] else None),
                "outcome": outcome["constraints"][name]["state"],
            }
        return {
            "request": outcome["case"]["id"],
            "cell": self.cell_id, "installed_loop_m": self.loop_m,
            "error_level": self.error_level, "supervisor": self.supervisor,
            "mutated": self.mutated, "mutations": list(self.mutations),
            "outcome": outcome["job"]["failure_reason"] or "completed",
            "route_completed": outcome["route_completed"],
            "seated": outcome["seated"],
            "elapsed_s": outcome["job"]["elapsed_s"],
            "installed_clips": outcome["installed_clips"],
            "terminal_clips": outcome["terminal_clips"],
            "clip_loss_attribution": outcome["clip_loss_attribution"],
            "steps_offered": outcome["steps_offered"],
            "steps_issued": outcome["steps_issued"],
            "abstentions": outcome["abstentions"],
            "per_step": steps,
            "per_constraint": totals,
            # The two guards name their counters differently in the records they
            # already write, and those names are load-bearing elsewhere.
            "guards": {"privilege": outcome["privilege_guard"]["events"],
                       "mutation": outcome["mutation_guard"]["forbidden_events"]},
            "directory": str(directory),
            "scope": self.scope_line(),
        }

    # ------------------------------------------------------------- provenance

    def scope_line(self) -> str:
        if self.mutated:
            return ("A MUTATED cell. This is not the geometry the routing study measured, so no "
                    "number from it belongs beside a published one. Simulation only.")
        return ("The registered cell at a registered service loop, so this request is the one "
                "the block ran. Simulation only; not a hardware claim.")

    def provenance(self) -> dict:
        """What this session is holding, in enough detail to check it later."""
        return {
            "cell": self.cell_id,
            "registered_cell": self.contract["cell"]["registered_cell"],
            "installed_loop_m": self.loop_m,
            "accepted_loops_m": self._accepted_loops(self.screen, self.cell_id),
            "error_level": self.error_level,
            "supervisor": self.supervisor,
            "port_mount": self.port_mount,
            "mount_offset_index": self.mount_offset_index,
            "repeat": self.repeat,
            "mutated": self.mutated,
            "mutations": list(self.mutations),
            "needs_screening": self.needs_screening,
            "asset_sha256": self.contract["cell"].get("asset_sha256"),
            "contract": PATHS["contract"],
        }

    def describe(self) -> dict:
        """Everything a caller needs to see before it changes anything."""
        return {
            **self.provenance(),
            "clips": [{key: clip[key] for key in ("id", *MOVABLE)}
                      | {"required": bool(clip.get("required", True))}
                      for clip in self.layout["clips"]],
            "route_waypoints_along_across_m": self.layout["route_waypoints_along_across_m"],
            "screen": self.screen_result,
            "candidate_actions": len(self.contract["route"]["candidate_actions"]),
            "decision_times_s": list(self.contract["route"]["decision_times_s"]),
            "error_levels": [entry["id"] for entry in self.perception["error_model"]["levels"]],
            "supervisors": list(SUPERVISORS),
            "scope": self.scope_line(),
        }
