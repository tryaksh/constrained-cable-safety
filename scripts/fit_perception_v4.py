"""Fit the six registered arms and apply the pre-registered crossover rule.

Reads one or more executed perception-study shards, assembles the (estimated
decision state, action, three constraint outcomes) dataset, fits every arm under
its declared budget on the pooled training split, scores each arm per constraint
and per error level on held-out groups, and emits the verdict the contract's rule
dictates. It does not choose the verdict; the contract does.

One predictor is fitted once and evaluated at every error level, because that is
the question a practitioner faces: a safety check is deployed across conditions,
not refitted for each one. B0 cannot adapt - it is one number. B0+ adapts through
the declared estimator covariance, which is the measurement-robust answer. B1, M
and Mh are told the declared sigma as a feature and may adapt through it. Nothing
is refitted on a test group, and the test split is read once, after every budget
is frozen.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from assembly_recovery.cable_constraints_v4 import CENSORED, CONSTRAINTS, VIOLATED  # noqa: E402
from assembly_recovery.cable_study_v4 import (  # noqa: E402
    ARM_COST,
    FEATURE_NAMES,
    FORCE_FEATURE_NAMES,
    action_displacement,
    b0plus_margin_m,
    balanced_accuracy,
    build_contexts,
    check_margin_resolution,
    cluster_bootstrap_difference,
    constraint_truth,
    content_sha256,
    effective_level,
    false_safe_at_coverage,
    feature_row,
    finite,
    fit_threshold,
    isolation_contexts,
    kaplan_meier,
    ranking_regret,
)


def collect(run_dirs, contract: dict, retract_distance_m: float) -> dict:
    """Assemble the dataset, keeping every request in the denominator."""
    contexts = {c["id"]: c for c in build_contexts(contract)+isolation_contexts(contract)}
    levels = {level["id"]: level for level in contract["error_model"]["levels"]}
    rows, denominator = [], []
    for run_dir in run_dirs:
        for directory in sorted(p for p in Path(run_dir).iterdir() if p.is_dir()):
            result_path = directory / "result.json"
            if not result_path.exists():
                continue
            result = json.loads(result_path.read_text(encoding="utf-8"))
            case = result["case"]
            if "study_context" not in case:
                continue
            context = contexts[case["study_context"]]
            decision = result.get("decision_state")
            labels = result["constraints"]
            denominator.append({
                "case": case["id"], "context": case["study_context"], "group": case["study_group"],
                "split": case["study_split"], "level": case["error_level"],
                "isolation": case.get("error_isolation", "all"),
                "job_status": result["job"]["status"], "reason": result["job"]["failure_reason"],
                "move_completed": bool(result.get("move_completed", False)),
                "usable": decision is not None,
                "privilege_events": result.get("privilege_guard", {}).get("events", 0),
                "mutation_events": result.get("mutation_guard", {}).get("forbidden_events", 0),
                **{name: labels[name]["state"] for name in CONSTRAINTS},
            })
            if decision is None:
                continue
            level = levels[case["error_level"]]
            rows.append({
                "case": case["id"], "context": case["study_context"], "group": case["study_group"],
                "split": case["study_split"], "level": case["error_level"],
                "isolation": case.get("error_isolation", "all"),
                "action_kind": case["action_kind"], "action_index": case["action_index"],
                "action": case["repair_action"], "mount_id": context["mount_id"],
                "decision_pose_id": context["decision_pose_id"],
                "features": feature_row(decision, case["repair_action"], context,
                                        retract_distance_m, level),
                "decision": decision, "constraints": labels,
                "move_completed": bool(result.get("move_completed", False)),
                "completed": int(result["job"]["status"] == "completed"),
                "run_direction_xy": context["run_direction_xy"],
            })
    return {"rows": rows, "denominator": denominator}


def canonical_frame(run_direction_xy):
    run = np.array([*run_direction_xy, 0.0], dtype=float)
    run = run/np.linalg.norm(run)
    return np.column_stack([run, np.cross([0.0, 0.0, 1.0], run), [0.0, 0.0, 1.0]])


def shape_inputs(rows, retract_distance_m: float, with_history: bool,
                 history_length: int = 0) -> np.ndarray:
    """Learned-model input: the estimated shape, the pose and the action.

    Everything is expressed in the fixture frame with the strain relief at the
    origin, so one model transfers across layouts without being told which layout
    it is looking at. ``with_history`` appends the short window of earlier
    estimated snapshots that the Mh arm is allowed and the M arm is not.

    ``history_length`` is the contract's declared window and is passed in rather
    than inferred, so a train split and a test split cannot end up with different
    input widths because one of them happened to carry a shorter window.
    """
    out = []
    for row in rows:
        decision, action = row["decision"], row["action"]
        basis = canonical_frame(row["run_direction_xy"])
        anchor = np.asarray(decision["anchor_site_m"], dtype=float)
        centreline = (np.asarray(decision["centerline_m"], dtype=float)-anchor) @ basis
        tip = (np.asarray(decision["tip_position_m"], dtype=float)-anchor) @ basis
        boot = (np.asarray(decision["boot_position_m"], dtype=float)-anchor) @ basis
        axis = np.asarray(decision["insertion_axis"], dtype=float)
        displacement = action_displacement(action, axis, np.array([*row["run_direction_xy"], 0.0]),
                                           retract_distance_m) @ basis
        bearing = float(action["bearing_rad"])
        parts = [centreline.ravel(), tip, boot, axis @ basis, displacement,
                 [float(action["retreat_m"]), float(action["excursion_m"]),
                  np.sin(bearing), np.cos(bearing)]]
        if with_history:
            recent = list(decision.get("history") or [])[-history_length:]
            padded = ([recent[0]]*(history_length-len(recent))+recent) if recent else []
            block = []
            for snapshot in padded:
                block.extend([
                    *((np.asarray(snapshot["tip_position_m"], dtype=float)-anchor) @ basis),
                    *((np.asarray(snapshot["seated_position_m"], dtype=float)-anchor) @ basis),
                    *((np.asarray(snapshot["boot_position_m"], dtype=float)-anchor) @ basis),
                    snapshot["min_bend_radius_m"], snapshot["anchor_reaction_n"],
                    snapshot["wrist_force_n"], snapshot["routed_length_m"],
                ])
            parts.append(np.asarray(block, dtype=float) if block
                         else np.zeros(13*history_length, dtype=float))
        out.append(np.concatenate([np.asarray(p, dtype=float).ravel() for p in parts]))
    width = max(len(o) for o in out)
    return np.asarray([np.pad(o, (0, width-len(o))) for o in out], dtype=np.float64)


def feature_matrix(rows, names) -> np.ndarray:
    return np.asarray([[row["features"][name] for name in names] for row in rows], dtype=np.float64)


def quadratic(matrix: np.ndarray) -> np.ndarray:
    columns = [matrix]
    for i in range(matrix.shape[1]):
        for j in range(i, matrix.shape[1]):
            columns.append((matrix[:, i]*matrix[:, j])[:, None])
    return np.hstack(columns)


def standardise(train: np.ndarray, *others: np.ndarray):
    mean, scale = train.mean(0), train.std(0)
    scale[scale < 1e-12] = 1.0
    return [(m-mean)/scale for m in (train, *others)]


def resolve_device(requested: str) -> torch.device:
    """Pick the fitting device. CUDA when it is genuinely present, else CPU.

    The simulator is CPU-only: MuJoCo's native step is, and the GPU path (MJX)
    does not support this scene's cable elasticity plugin, composite bodies or
    elliptic friction cone, so collection cannot move to the GPU without becoming
    a different cable. Fitting can, and this is where that choice is made. The
    fits here are small beside collection, so a CPU run is not a degraded result -
    it is the same result, a few minutes slower.
    """
    if requested == "cpu":
        return torch.device("cpu")
    if torch.cuda.is_available():
        return torch.device("cuda")
    if requested == "cuda":
        raise SystemExit("--device cuda was asked for but this torch build has no CUDA. "
                         "torch " + torch.__version__ + " is installed.")
    return torch.device("cpu")


def train_torch(inputs, labels, dev_inputs, dev_labels, budget: dict, seed: int, hidden=None,
                device=None) -> dict:
    """One fit to a declared budget, selecting the checkpoint by dev loss only."""
    device = device or torch.device("cpu")
    torch.manual_seed(seed)
    x = torch.tensor(inputs, dtype=torch.float32, device=device)
    y = torch.tensor(labels, dtype=torch.float32, device=device)[:, None]
    xd = torch.tensor(dev_inputs, dtype=torch.float32, device=device)
    yd = torch.tensor(dev_labels, dtype=torch.float32, device=device)[:, None]
    if hidden:
        layers, width = [], inputs.shape[1]
        for size in hidden:
            layers += [torch.nn.Linear(width, size), torch.nn.ReLU()]
            width = size
        layers.append(torch.nn.Linear(width, 1))
        model = torch.nn.Sequential(*layers).to(device)
    else:
        model = torch.nn.Linear(inputs.shape[1], 1).to(device)
    positives = max(float(y.sum()), 1.0)
    weight = torch.tensor([(len(y)-positives)/positives], dtype=torch.float32, device=device)
    loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=weight)
    optimiser = torch.optim.Adam(model.parameters(), lr=budget["learning_rate"],
                                 weight_decay=budget["weight_decay"])
    best_state, best_dev, best_epoch = None, float("inf"), -1
    batch = budget["batch_size"]
    generator = torch.Generator().manual_seed(seed)
    for epoch in range(budget["epochs"]):
        model.train()
        order = torch.randperm(len(x), generator=generator).to(device)
        for start in range(0, len(x), batch):
            index = order[start:start+batch]
            optimiser.zero_grad()
            loss_fn(model(x[index]), y[index]).backward()
            optimiser.step()
        model.eval()
        with torch.no_grad():
            dev_loss = float(loss_fn(model(xd), yd))
        if dev_loss < best_dev:
            best_dev, best_epoch = dev_loss, epoch
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    model.eval()
    return {"model": model, "dev_loss": best_dev, "selected_epoch": best_epoch, "seed": seed,
            "device": str(device)}


def probabilities(model, inputs) -> np.ndarray:
    device = next(model.parameters()).device
    with torch.no_grad():
        tensor = torch.tensor(inputs, dtype=torch.float32, device=device)
        return torch.sigmoid(model(tensor)).detach().cpu().numpy().ravel()


def fit_arms(rows, contract: dict, constraint: str, retract: float, device=None) -> dict:
    """Every arm, fitted once on the pooled training split for one constraint.

    Censored rows carry no label for this constraint and are excluded from
    fitting. They stay in the denominator and in every evaluation coverage.
    """
    ladder = [row for row in rows if row["isolation"] == "all"]
    train = [row for row in ladder if row["split"] == "train"]
    dev = [row for row in ladder if row["split"] == "dev"]
    train = [row for row in train if row["constraints"][constraint]["state"] != CENSORED]
    dev = [row for row in dev if row["constraints"][constraint]["state"] != CENSORED]
    if not train or not dev:
        return {"status": "no_labelled_training_data", "constraint": constraint}
    y_train = np.asarray([row["constraints"][constraint]["state"] == VIOLATED for row in train], dtype=float)
    y_dev = np.asarray([row["constraints"][constraint]["state"] == VIOLATED for row in dev], dtype=float)

    fitted: dict = {"constraint": constraint,
                    "train_rows": len(train), "dev_rows": len(dev),
                    "train_violation_rate": float(y_train.mean()),
                    "dev_violation_rate": float(y_dev.mean())}

    budget_b1 = contract["predictors"]["B1"]["budget"]
    budget_m = contract["predictors"]["M"]["budget"]

    # B0: one scalar threshold on the estimated endpoint distance, fitted on
    # train plus dev and given every advantage on purpose.
    pooled = train+dev
    values = np.asarray([row["features"]["endpoint_boot_to_anchor_m"] for row in pooled])
    labels = np.concatenate([y_train, y_dev])
    fitted["B0"] = fit_threshold(values, labels)

    for name, names in (("B1", FEATURE_NAMES), ("B2", FORCE_FEATURE_NAMES)):
        matrix_train = feature_matrix(train, names)
        matrix_dev = feature_matrix(dev, names)
        best = None
        for variant in contract["predictors"][name]["variants"]:
            xt, xd = (quadratic(matrix_train), quadratic(matrix_dev)) if variant["expansion"] == "quadratic" \
                else (matrix_train, matrix_dev)
            xt, xd = standardise(xt, xd)
            budget = {**budget_b1, "weight_decay": variant["weight_decay"]}
            fit = train_torch(xt, y_train, xd, y_dev, budget, seed=variant["seed"],
                              device=device)
            fit["variant"] = variant
            if best is None or fit["dev_loss"] < best["dev_loss"]:
                best = fit
        fitted[name] = best

    window = int(contract["error_model"]["history"]["length"])
    for name, history in (("M", False), ("Mh", True)):
        xt = shape_inputs(train, retract, history, window)
        xd = shape_inputs(dev, retract, history, window)
        xt, xd = standardise(xt, xd)
        seeds = []
        for seed in budget_m["seeds"]:
            seeds.append(train_torch(xt, y_train, xd, y_dev, budget_m, seed=seed,
                                     hidden=budget_m["hidden"], device=device))
        fitted[name] = {"seeds": seeds, "inputs": int(xt.shape[1])}
    return fitted


def arm_scores(name, fitted, rows, retract, contract, level_id=None) -> np.ndarray:
    """Risk score for one arm on one set of rows. Lower is safer."""
    if name == "B0":
        return np.asarray([row["features"]["endpoint_boot_to_anchor_m"] for row in rows])
    if name == "B0plus":
        coverage = contract["predictors"]["B0plus"]["coverage_sigma"]
        # An isolation cell has one error channel on, so the declared covariance
        # B0+ carries its margin from is that cell's, not the full level's.
        return np.asarray([row["features"]["endpoint_boot_to_anchor_m"]
                           + b0plus_margin_m(effective_level(contract, row["level"],
                                                             row.get("isolation", "all")),
                                             coverage)
                           for row in rows])
    if name in ("B1", "B2"):
        names = FEATURE_NAMES if name == "B1" else FORCE_FEATURE_NAMES
        variant = fitted[name]["variant"]
        matrix = feature_matrix(rows, names)
        if variant["expansion"] == "quadratic":
            matrix = quadratic(matrix)
        reference = fitted[f"_{name}_reference"]
        matrix = (matrix-reference[0])/reference[1]
        return probabilities(fitted[name]["model"], matrix)
    if name in ("M", "Mh"):
        matrix = shape_inputs(rows, retract, name == "Mh",
                              int(contract["error_model"]["history"]["length"]))
        reference = fitted[f"_{name}_reference"]
        matrix = (matrix-reference[0])/reference[1]
        return np.mean([probabilities(seed["model"], matrix) for seed in fitted[name]["seeds"]], axis=0)
    raise ValueError(f"Unregistered arm {name!r}")


def safe_set(name, scores, fitted, contract, rows) -> np.ndarray:
    """The actions this arm calls safe, under the contract's declared rule."""
    if name == "B0":
        return scores <= fitted["B0"]["threshold_m"]
    if name == "B0plus":
        return scores <= fitted["B0"]["threshold_m"]
    return scores < contract["predictors"]["probability_safe_below"]


def evaluate_arm(name, rows, scores, safe, coverage, constraint, retract) -> dict:
    violated, observed = constraint_truth(rows, constraint)
    own = violated[safe & observed]
    return {
        "arm": name,
        "predicted_safe": int(safe.sum()),
        "false_safe_rate_own_operating_point": float(own.mean()) if own.size else None,
        "false_safe_matched_coverage": false_safe_at_coverage(scores, violated, observed, coverage),
        "balanced_accuracy": balanced_accuracy(violated[observed].astype(int), (~safe)[observed]),
        "ranking_regret": ranking_regret(rows, safe, constraint, retract),
        "cost": ARM_COST[name],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, action="append", required=True,
                        help="One executed shard. Repeat for every shard of the block.")
    parser.add_argument("--contract", type=Path, default=Path("configs/cable_perception_v4.json"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dataset-out", type=Path, default=None)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto",
                        help="Fitting device. Collection is CPU-only; see resolve_device.")
    args = parser.parse_args()

    device = resolve_device(args.device)
    contract = json.loads((ROOT / args.contract).read_text(encoding="utf-8-sig"))
    base = json.loads((ROOT / contract["base_config"]["path"]).read_text(encoding="utf-8-sig"))
    retract = base["force_guided_controller"]["retract_distance_m"]
    data = collect([ROOT / d for d in args.run_dir], contract, retract)
    rows, denominator = data["rows"], data["denominator"]
    if not rows:
        parser.error("No usable requests found")

    levels = [level["id"] for level in contract["error_model"]["levels"]]
    margin = float(contract["decision_rule"]["margin"])
    results: dict = {}
    crossover: dict = {}
    guard_checks: dict = {}

    for constraint in CONSTRAINTS:
        fitted = fit_arms(rows, contract, constraint, retract, device=device)
        if fitted.get("status"):
            results[constraint] = fitted
            continue
        # Standardisation references, frozen on the training split only.
        ladder = [row for row in rows if row["isolation"] == "all"]
        train = [row for row in ladder
                 if row["split"] == "train" and row["constraints"][constraint]["state"] != CENSORED]
        for name, names in (("B1", FEATURE_NAMES), ("B2", FORCE_FEATURE_NAMES)):
            matrix = feature_matrix(train, names)
            if fitted[name]["variant"]["expansion"] == "quadratic":
                matrix = quadratic(matrix)
            scale = matrix.std(0)
            scale[scale < 1e-12] = 1.0
            fitted[f"_{name}_reference"] = (matrix.mean(0), scale)
        window = int(contract["error_model"]["history"]["length"])
        for name in ("M", "Mh"):
            matrix = shape_inputs(train, retract, name == "Mh", window)
            scale = matrix.std(0)
            scale[scale < 1e-12] = 1.0
            fitted[f"_{name}_reference"] = (matrix.mean(0), scale)

        per_level = {}
        for level_id in levels:
            test = [row for row in ladder if row["split"] == "test" and row["level"] == level_id]
            if not test:
                continue
            scores = {name: arm_scores(name, fitted, test, retract, contract) for name in ARM_COST}
            safes = {name: safe_set(name, scores[name], fitted, contract, test) for name in ARM_COST}
            coverage = int(safes["B0"].sum())
            evaluated = {name: evaluate_arm(name, test, scores[name], safes[name], coverage,
                                            constraint, retract)
                         for name in ARM_COST}
            violated, observed = constraint_truth(test, constraint)
            reference = evaluated["B0plus"]
            best_rich = min(("M", "Mh"),
                            key=lambda n: (evaluated[n]["false_safe_matched_coverage"]["rate"]
                                           if evaluated[n]["false_safe_matched_coverage"]["rate"]
                                           is not None else float("inf")))
            gaps = {}
            for name in ARM_COST:
                a = reference["false_safe_matched_coverage"]["rate"]
                b = evaluated[name]["false_safe_matched_coverage"]["rate"]
                gaps[name] = {
                    "false_safe_gap_vs_B0plus": (None if a is None or b is None else float(a-b)),
                    "ranking_regret_gap_vs_B0plus": float(reference["ranking_regret"]["regret"]
                                                          - evaluated[name]["ranking_regret"]["regret"]),
                }
            resolutions = [evaluated[name]["ranking_regret"]["resolution"] for name in ARM_COST]
            guard_checks[f"{constraint}:{level_id}"] = check_margin_resolution(margin, resolutions)
            per_level[level_id] = {
                "b0plus_note": (
                    "Within one error level the B0+ margin is a constant added to every B0 score, "
                    "so the two arms RANK actions identically and their false-safe rate at matched "
                    "coverage is identical by construction. The margin acts on the operating "
                    "point, not on the ordering: read predicted_safe and "
                    "false_safe_rate_own_operating_point to see what it buys. The crossover rule "
                    "compares a learned arm against B0+ on the matched-coverage metric, which is "
                    "therefore a question about the REPRESENTATION rather than about the margin."),
                "test_requests": len(test),
                "test_contexts": len({row["context"] for row in test}),
                "violation_rate_observed": (float(violated[observed].mean()) if observed.any() else None),
                "censored_rate": float((~observed).mean()),
                "coverage_matched_to_B0": coverage,
                "arms": evaluated, "gaps_vs_B0plus": gaps,
                "best_rich_arm": best_rich,
                "bootstrap_B0plus_minus_best_rich": cluster_bootstrap_difference(
                    test, scores["B0plus"], scores[best_rich], safes["B0plus"], constraint,
                    draws=contract["decision_rule"]["bootstrap_draws"]),
                "survival": kaplan_meier(
                    [(row["constraints"][constraint]["violation_progress_m"]
                      or row["constraints"][constraint]["censoring_progress_m"] or 0.0) for row in test],
                    violated, observed),
            }

        # The registered crossover: the smallest level at which a rich arm beats
        # the measurement-robust baseline by more than the margin on BOTH metrics.
        crossing = None
        for level_id in levels:
            block = per_level.get(level_id)
            if not block or guard_checks[f"{constraint}:{level_id}"]["verdict"] != "usable":
                continue
            for name in ("M", "Mh"):
                gap = block["gaps_vs_B0plus"][name]
                if (gap["false_safe_gap_vs_B0plus"] is not None
                        and gap["false_safe_gap_vs_B0plus"] > margin
                        and gap["ranking_regret_gap_vs_B0plus"] > margin):
                    crossing = {"level": level_id, "arm": name, **gap}
                    break
            if crossing:
                break
        force_beats = {}
        for level_id, block in per_level.items():
            gap_b2 = block["gaps_vs_B0plus"]["B2"]
            force_beats[level_id] = bool(
                gap_b2["false_safe_gap_vs_B0plus"] is not None
                and gap_b2["false_safe_gap_vs_B0plus"] > margin)
        crossover[constraint] = {
            "crossover": crossing,
            "crossover_found": crossing is not None,
            "force_only_beats_B0plus_by_level": force_beats,
            "note": ("No crossover inside the registered range is a result, not a missing result. "
                     "It means a scalar over an estimated pose, carrying a margin sized from the "
                     "declared estimator covariance, stayed sufficient at every error level tested."),
        }
        selection = {
            "B0": fitted["B0"],
            "B1": {"variant": fitted["B1"]["variant"], "dev_loss": fitted["B1"]["dev_loss"]},
            "B2": {"variant": fitted["B2"]["variant"], "dev_loss": fitted["B2"]["dev_loss"]},
            "M": [{"seed": s["seed"], "dev_loss": s["dev_loss"], "selected_epoch": s["selected_epoch"]}
                  for s in fitted["M"]["seeds"]],
            "Mh": [{"seed": s["seed"], "dev_loss": s["dev_loss"], "selected_epoch": s["selected_epoch"]}
                   for s in fitted["Mh"]["seeds"]],
        }
        # Per-seed spread on the held-out split, so a mean over seeds cannot hide
        # a seed that is worse than the baseline. This is what v3 had to report
        # post hoc; here it is part of the record.
        seed_spread = {}
        for name in ("M", "Mh"):
            spread = {}
            for level_id in levels:
                test = [row for row in ladder if row["split"] == "test" and row["level"] == level_id]
                if not test:
                    continue
                matrix = shape_inputs(test, retract, name == "Mh", window)
                reference = fitted[f"_{name}_reference"]
                matrix = (matrix-reference[0])/reference[1]
                violated, observed = constraint_truth(test, constraint)
                coverage = int(safe_set("B0", arm_scores("B0", fitted, test, retract, contract),
                                        fitted, contract, test).sum())
                spread[level_id] = [
                    false_safe_at_coverage(probabilities(seed["model"], matrix), violated, observed,
                                           coverage)["rate"]
                    for seed in fitted[name]["seeds"]]
            seed_spread[name] = spread

        isolation_rows = [row for row in rows if row["isolation"] != "all" and row["split"] == "test"]
        isolation_report = {}
        for channel in sorted({row["isolation"] for row in isolation_rows}):
            subset = [row for row in isolation_rows if row["isolation"] == channel]
            scores = {name: arm_scores(name, fitted, subset, retract, contract) for name in ARM_COST}
            safes = {name: safe_set(name, scores[name], fitted, contract, subset) for name in ARM_COST}
            coverage = int(safes["B0"].sum())
            isolation_report[channel] = {
                "requests": len(subset),
                "arms": {name: evaluate_arm(name, subset, scores[name], safes[name], coverage,
                                            constraint, retract) for name in ARM_COST},
            }

        results[constraint] = {"selection": selection, "per_level": per_level,
                               "seed_spread_false_safe_matched_coverage": seed_spread,
                               "isolation": isolation_report,
                               "train_rows": fitted["train_rows"], "dev_rows": fitted["dev_rows"],
                               "train_violation_rate": fitted["train_violation_rate"]}

    outcome_counts: dict = {}
    for record in denominator:
        for name in CONSTRAINTS:
            outcome_counts.setdefault(name, {}).setdefault(record[name], 0)
            outcome_counts[name][record[name]] += 1
    privilege_events = sum(r["privilege_events"] for r in denominator)
    mutation_events = sum(r["mutation_events"] for r in denominator)

    report = {
        "schema": 1, "id": contract["id"]+"_fit", "created_on": contract["created_on"],
        "status": "fitted_perception_study",
        "scope": contract["scope"],
        "question": contract["question"],
        "contract": {"path": args.contract.as_posix(),
                     "content_sha256": content_sha256(ROOT / args.contract)},
        "run_dirs": [Path(d).as_posix() for d in args.run_dir],
        "denominator": {
            "requests": len(denominator),
            "usable_for_fitting": sum(1 for r in denominator if r["usable"]),
            "by_constraint": outcome_counts,
            "by_job_reason": {reason: sum(1 for r in denominator
                                          if (r["reason"] or "completed") == reason)
                              for reason in sorted({r["reason"] or "completed"
                                                    for r in denominator}, key=str)},
            "note": "Every registered request counts, including settling rejections, infeasible "
                    "constructions and load aborts. A load abort censors the constraints it had "
                    "not already violated; it is never scored as a success.",
        },
        "fitting_device": str(device),
        "guards": {"privilege_guard_events": privilege_events,
                   "mutation_guard_events": mutation_events,
                   "verdict": "clean" if not (privilege_events or mutation_events)
                              else "guard_fired_see_denominator"},
        "margin_resolution_checks": guard_checks,
        "margin_resolution_verdict": ("usable" if all(v["verdict"] == "usable"
                                                      for v in guard_checks.values())
                                      else "refused_margin_below_resolution"),
        "prediction": contract["decision_rule"]["crossover_prediction"],
        "crossover": crossover,
        "results": results,
        "cost_axis": ARM_COST,
        "scope_and_limitations": contract["scope_and_limitations"],
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(finite(report), indent=2, allow_nan=False, default=float),
                   encoding="utf-8")
    if args.dataset_out:
        dataset = ROOT / args.dataset_out
        dataset.parent.mkdir(parents=True, exist_ok=True)
        dataset.write_text(json.dumps(finite({"rows": rows, "denominator": denominator}),
                                      allow_nan=False, default=float), encoding="utf-8")
    print(json.dumps({"out": args.out.as_posix(),
                      "requests": len(denominator),
                      "margin_resolution": report["margin_resolution_verdict"],
                      "crossover": {k: v["crossover_found"] for k, v in crossover.items()}}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
