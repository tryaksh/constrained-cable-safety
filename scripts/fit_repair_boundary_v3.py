"""Fit the three registered predictors and apply the pre-registered decision rule.

Reads one executed safe-repair boundary run, assembles the (decision state,
action, outcome) dataset, fits the analytic budget baseline, the calibrated
feature model and the learned outcome model under their declared budgets, scores
them on held-out groups, and emits the verdict the contract's decision rule
dictates. It does not choose the verdict; the contract does.

Test groups are read exactly once, after every method and budget is frozen. The
analytic baseline is deliberately given every advantage: it is the thing that
must be beaten.
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

from assembly_recovery.cable_study_v3 import (  # noqa: E402
    FEATURE_NAMES,
    action_displacement,
    balanced_accuracy,
    build_contexts,
    cluster_bootstrap_difference,
    commanded_magnitude,
    content_sha256,
    false_safe_at_coverage,
    feature_row,
    finite,
    fit_b0,
    lowest_risk_choice,
    outcome_label,
    paired_context_comparison,
    ranking_regret,
)

CLIP_LOST_LABELS = {"clip_lost", "completed_clip_lost"}


def collect(run_dir: Path, contract: dict, retract_distance_m: float) -> dict:
    """Assemble the dataset, keeping every request in the denominator."""
    contexts = {c["id"]: c for c in build_contexts(contract)}
    rows, denominator = [], []
    for directory in sorted(p for p in run_dir.iterdir() if p.is_dir()):
        result_path = directory / "result.json"
        if not result_path.exists():
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        case = result["case"]
        if "study_context" not in case:
            continue
        label = outcome_label(result)
        context = contexts[case["study_context"]]
        denominator.append({"case": case["id"], "context": case["study_context"],
                            "group": case["study_group"], "split": case["study_split"],
                            "outcome": label, "usable": result.get("decision_state") is not None})
        decision = result.get("decision_state")
        if decision is None:
            continue
        features = feature_row(decision, case["repair_action"], context, retract_distance_m)
        rows.append({
            "case": case["id"], "context": case["study_context"], "group": case["study_group"],
            "split": case["study_split"], "action_kind": case["action_kind"],
            "action_index": case["action_index"], "action": case["repair_action"],
            "mount_id": context["mount_id"], "decision_pose_id": context["decision_pose_id"],
            "outcome": label, "clip_lost": int(label in CLIP_LOST_LABELS),
            "completed": int(label == "completed_clip_retained"),
            "features": features, "decision": decision,
            "run_direction_xy": context["run_direction_xy"],
        })
    return {"rows": rows, "denominator": denominator}


def canonical_frame(run_direction_xy):
    """Fixture frame used to express the cable shape independently of layout."""
    run = np.array([*run_direction_xy, 0.0], dtype=float)
    run = run/np.linalg.norm(run)
    return np.column_stack([run, np.cross([0.0, 0.0, 1.0], run), [0.0, 0.0, 1.0]])


def shape_inputs(rows, retract_distance_m: float) -> np.ndarray:
    """Learned-model input: the whole cable shape, the pose and the action.

    Everything is expressed in the fixture frame with the strain relief at the
    origin, so one model transfers across layouts without being told which
    layout it is looking at.
    """
    out = []
    for row in rows:
        decision, action = row["decision"], row["action"]
        basis = canonical_frame(row["run_direction_xy"])
        anchor = np.asarray(decision["anchor_site_m"], dtype=float)
        centerline = (np.asarray(decision["centerline_m"], dtype=float)-anchor) @ basis
        tip = (np.asarray(decision["tip_position_m"], dtype=float)-anchor) @ basis
        boot = (np.asarray(decision["boot_position_m"], dtype=float)-anchor) @ basis
        axis = np.asarray(decision["insertion_axis"], dtype=float)
        displacement = action_displacement(action, axis, np.array([*row["run_direction_xy"], 0.0]),
                                           retract_distance_m) @ basis
        bearing = float(action["bearing_rad"])
        out.append(np.concatenate([
            centerline.ravel(), tip, boot, axis @ basis, displacement,
            [float(action["retreat_m"]), float(action["excursion_m"]),
             np.sin(bearing), np.cos(bearing)],
        ]))
    return np.asarray(out, dtype=np.float64)


def feature_matrix(rows) -> np.ndarray:
    return np.asarray([[row["features"][name] for name in FEATURE_NAMES] for row in rows], dtype=np.float64)


def quadratic(matrix: np.ndarray) -> np.ndarray:
    """Declared nonlinear variant: the features, their squares and their products."""
    columns = [matrix]
    count = matrix.shape[1]
    for i in range(count):
        for j in range(i, count):
            columns.append((matrix[:, i]*matrix[:, j])[:, None])
    return np.hstack(columns)


def standardise(train: np.ndarray, *others: np.ndarray):
    mean, scale = train.mean(0), train.std(0)
    scale[scale < 1e-12] = 1.0
    return [(m-mean)/scale for m in (train, *others)]


def train_torch(inputs, labels, dev_inputs, dev_labels, budget: dict, seed: int, hidden=None) -> dict:
    """One fit to a declared budget, selecting the checkpoint by dev loss only."""
    torch.manual_seed(seed)
    x = torch.tensor(inputs, dtype=torch.float32)
    y = torch.tensor(labels, dtype=torch.float32)[:, None]
    xd = torch.tensor(dev_inputs, dtype=torch.float32)
    yd = torch.tensor(dev_labels, dtype=torch.float32)[:, None]
    if hidden:
        layers, width = [], inputs.shape[1]
        for size in hidden:
            layers += [torch.nn.Linear(width, size), torch.nn.ReLU()]
            width = size
        layers.append(torch.nn.Linear(width, 1))
        model = torch.nn.Sequential(*layers)
    else:
        model = torch.nn.Linear(inputs.shape[1], 1)
    # Positive weighting so a rare clip loss is not optimised away as noise.
    positives = max(float(y.sum()), 1.0)
    weight = torch.tensor([(len(y)-positives)/positives], dtype=torch.float32)
    loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=weight)
    optimiser = torch.optim.Adam(model.parameters(), lr=budget["learning_rate"],
                                 weight_decay=budget["weight_decay"])
    best_state, best_dev, best_epoch = None, float("inf"), -1
    batch = budget["batch_size"]
    generator = torch.Generator().manual_seed(seed)
    for epoch in range(budget["epochs"]):
        model.train()
        order = torch.randperm(len(x), generator=generator)
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
    return {"model": model, "dev_loss": best_dev, "selected_epoch": best_epoch, "seed": seed}


def probabilities(model, inputs) -> np.ndarray:
    with torch.no_grad():
        return torch.sigmoid(model(torch.tensor(inputs, dtype=torch.float32))).numpy().ravel()


def evaluate(name, rows, scores, safe, coverage, retract_distance_m, score_units) -> dict:
    truth = np.asarray([row["clip_lost"] for row in rows])
    return {
        "predictor": name,
        "score_units": score_units,
        "predicted_safe": int(safe.sum()),
        "false_safe_rate_own_operating_point": float(truth[safe].mean()) if safe.any() else float("nan"),
        "false_safe_rate_matched_coverage": false_safe_at_coverage(scores, truth, coverage),
        "balanced_accuracy": balanced_accuracy(truth, ~safe),
        "ranking_regret_clip": ranking_regret(rows, safe, "clip_lost", retract_distance_m),
        "ranking_regret_completion": ranking_regret(rows, safe, "completed", retract_distance_m),
        "lowest_risk_choice": lowest_risk_choice(rows, scores, retract_distance_m),
    }


def provenance(run_dir: Path) -> dict:
    """The launcher's prelaunch record, reduced to what the evidence file needs."""
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    return {"commit_at_start": manifest["source_commit_at_start"],
            "dirty_at_start": manifest["source_dirty_at_start"],
            "config": manifest["config"],
            "source_archive": manifest["source_archive"],
            "run_id": manifest["run_id"],
            "launcher_status": manifest.get("status"),
            "native_environment": manifest.get("native_environment"),
            "upstream_commit": manifest.get("upstream", {}).get("aic", {}).get("commit")}


def accounting(run_dir: Path) -> dict:
    """Measured cost of the block, read from the worker's own totals."""
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    cases = result["cases"]
    wall = [c["accounting"]["wall_seconds"] for c in cases]
    steps = result["accounting"]["native_steps"]+result["accounting"]["settle_native_steps"]
    launcher = float(manifest.get("elapsed_seconds") or 0.0)
    return {"launcher_wall_seconds": round(launcher, 1),
            "total_native_steps": steps,
            "aggregate_native_steps_per_second": round(steps/launcher, 1) if launcher else None,
            "per_worker_native_steps_per_second": round(steps/sum(wall), 1) if sum(wall) else None,
            "throughput_note": "Aggregate is total steps over launcher wall time on twelve workers, the "
                               "same convention the v2 block used, where it measured 25,244.7. This block "
                               "runs faster because visual mesh export is off for study requests.",
            "requests": len(cases),
            "expected_requests": result.get("expected_requests"),
            "native_steps": result["accounting"]["native_steps"],
            "settle_native_steps": result["accounting"]["settle_native_steps"],
            "summed_worker_wall_seconds": round(sum(wall), 1),
            "median_request_wall_seconds": round(float(np.median(wall)), 2),
            "training_runs_during_collection": result["accounting"]["training_runs"],
            "repairs_issued": sum(int(c.get("repairs_started", 0) > 0) for c in cases),
            "mutation_guard_events": sum(c.get("mutation_guard", {}).get("forbidden_events", 0) for c in cases)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=Path("configs/cable_repair_boundary_v3.json"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dataset-out", type=Path, default=None)
    args = parser.parse_args()

    contract = json.loads((ROOT / args.contract).read_text(encoding="utf-8-sig"))
    base = json.loads((ROOT / contract["base_config"]["path"]).read_text(encoding="utf-8-sig"))
    retract = base["force_guided_controller"]["retract_distance_m"]
    data = collect(ROOT / args.run_dir, contract, retract)
    rows, denominator = data["rows"], data["denominator"]
    split_of = {"train": [], "dev": [], "test": []}
    for row in rows:
        split_of[row["split"]].append(row)
    train, dev, test = split_of["train"], split_of["dev"], split_of["test"]
    if not (train and dev and test):
        parser.error("Every split needs usable requests before any model is fitted")

    y_train = np.asarray([r["clip_lost"] for r in train])
    y_dev = np.asarray([r["clip_lost"] for r in dev])

    # B0: one scalar, fitted on train plus dev, given every advantage.
    column = FEATURE_NAMES.index("endpoint_boot_to_anchor_m")
    v_train = feature_matrix(train)[:, column]
    v_dev = feature_matrix(dev)[:, column]
    v_test = feature_matrix(test)[:, column]
    b0 = fit_b0(np.concatenate([v_train, v_dev]), np.concatenate([y_train, y_dev]))
    b0_safe_test = v_test <= b0["threshold_m"]
    coverage = int(b0_safe_test.sum())
    b0_scores_test = v_test

    # B1: regularised logistic regression, linear or quadratic chosen on dev only.
    budget = dict(contract["predictors"]["M"]["budget"])
    variants = {}
    for label, transform in (("linear", lambda m: m), ("quadratic", quadratic)):
        xt, xd, xs = standardise(transform(feature_matrix(train)), transform(feature_matrix(dev)),
                                 transform(feature_matrix(test)))
        for decay in (1e-4, 1e-3, 1e-2):
            fit = train_torch(xt, y_train, xd, y_dev,
                              {**budget, "weight_decay": decay, "epochs": 300}, seed=0)
            variants[f"{label}_wd{decay:g}"] = {**fit, "test_inputs": xs, "dev_loss": fit["dev_loss"]}
    b1_key = min(variants, key=lambda k: variants[k]["dev_loss"])
    b1 = variants[b1_key]
    b1_scores_test = probabilities(b1["model"], b1["test_inputs"])

    # M: the learned outcome model over the whole cable shape, three seeds.
    st, sd, ss = standardise(shape_inputs(train, retract), shape_inputs(dev, retract),
                             shape_inputs(test, retract))
    m_fits = [train_torch(st, y_train, sd, y_dev, budget, seed=s, hidden=budget["hidden"])
              for s in budget["seeds"]]
    m_scores = np.stack([probabilities(f["model"], ss) for f in m_fits])
    m_scores_test = m_scores.mean(0)

    distance = "metres: the analytic endpoint boot-to-anchor distance, a monotone risk score"
    probability = "probability of clip loss"
    results = {
        "B0": evaluate("B0", test, b0_scores_test, b0_safe_test, coverage, retract, distance),
        "B1": evaluate("B1", test, b1_scores_test, b1_scores_test < 0.5, coverage, retract, probability),
        "M": evaluate("M", test, m_scores_test, m_scores_test < 0.5, coverage, retract, probability),
    }
    for seed_index, fit in enumerate(m_fits):
        results[f"M_seed{fit['seed']}"] = evaluate(
            f"M_seed{fit['seed']}", test, m_scores[seed_index], m_scores[seed_index] < 0.5,
            coverage, retract, probability)

    # Reference, not a predictor: a supervisor with no safety filter at all, which
    # is what the repair library does today. It says what the filter is worth.
    truth_test = np.asarray([r["clip_lost"] for r in test])
    unfiltered = np.ones(len(test), dtype=bool)
    results["no_filter_reference"] = {
        "predictor": "no filter", "score_units": "none; every action is allowed",
        "status": "reference, not one of the three registered predictors",
        "predicted_safe": int(len(test)),
        "clip_loss_base_rate": float(truth_test.mean()),
        "ranking_regret_clip": ranking_regret(test, unfiltered, "clip_lost", retract),
        "ranking_regret_completion": ranking_regret(test, unfiltered, "completed", retract),
    }

    # Post-hoc and labelled as such: the registered margin is 0.05 and the
    # ranking metric's own resolution is one context in twenty, which is also
    # 0.05. A gap of one or two contexts therefore cannot be read as a win, so
    # the pairing and the seed spread are reported beside the registered numbers.
    safe_sets = {"B0": b0_safe_test, "B1": b1_scores_test < 0.5, "M": m_scores_test < 0.5}
    results["exploratory_paired_comparisons"] = {
        f"{a}_vs_{b}": paired_context_comparison(test, safe_sets[a], safe_sets[b], "clip_lost", retract)
        for a, b in (("B0", "M"), ("B0", "B1"), ("B1", "M"))}
    results["exploratory_false_safe_bootstrap"] = {
        "B0_minus_M": cluster_bootstrap_difference(test, b0_scores_test, m_scores_test, b0_safe_test),
        "B0_minus_B1": cluster_bootstrap_difference(test, b0_scores_test, b1_scores_test, b0_safe_test),
        "note": "Positive means B0 lets through more clip losses than the comparison predictor at the "
                "same coverage. An interval spanning zero means the metric cannot tell them apart."}
    seed_regrets = [results[f"M_seed{f['seed']}"]["ranking_regret_clip"]["regret"] for f in m_fits]
    seed_false_safe = [results[f"M_seed{f['seed']}"]["false_safe_rate_matched_coverage"] for f in m_fits]
    results["exploratory_seed_spread"] = {
        "M_per_seed_ranking_regret": seed_regrets,
        "M_per_seed_ranking_regret_mean": float(np.mean(seed_regrets)),
        "M_per_seed_false_safe_matched_coverage": seed_false_safe,
        "B0_ranking_regret": results["B0"]["ranking_regret_clip"]["regret"],
        "seeds_worse_than_B0_on_ranking_regret": int(sum(
            r > results["B0"]["ranking_regret_clip"]["regret"] for r in seed_regrets)),
        "status": "exploratory_post_hoc_not_part_of_the_decision_rule"}

    margin = contract["decision_rule"]["margin"]
    best_other_a = min(results["B1"]["false_safe_rate_matched_coverage"],
                       results["M"]["false_safe_rate_matched_coverage"])
    best_other_b = min(results["B1"]["ranking_regret_clip"]["regret"],
                       results["M"]["ranking_regret_clip"]["regret"])
    gap_a = results["B0"]["false_safe_rate_matched_coverage"]-best_other_a
    gap_b = results["B0"]["ranking_regret_clip"]["regret"]-best_other_b
    m_beats = (results["B0"]["false_safe_rate_matched_coverage"]-results["M"]["false_safe_rate_matched_coverage"] > margin
               and results["B1"]["false_safe_rate_matched_coverage"]-results["M"]["false_safe_rate_matched_coverage"] > margin
               and results["B0"]["ranking_regret_clip"]["regret"]-results["M"]["ranking_regret_clip"]["regret"] > margin
               and results["B1"]["ranking_regret_clip"]["regret"]-results["M"]["ranking_regret_clip"]["regret"] > margin)
    verdict = ("publication_track_learned_model_wins" if m_beats
               else "wrap_up_analytic_budget_is_sufficient" if (gap_a <= margin and gap_b <= margin)
               else "inconclusive_neither_branch_triggered")

    outcome_counts: dict[str, int] = {}
    for entry in denominator:
        outcome_counts[entry["outcome"]] = outcome_counts.get(entry["outcome"], 0)+1
    report = {
        "schema": 1, "id": "cable_repair_boundary_v3_r01", "created_on": "2026-09-11",
        "status": "executed_pre_registered_decision_block",
        "scope": contract["scope"],
        "question": contract["question"],
        "contract": {"path": args.contract.as_posix(), "content_sha256": content_sha256(ROOT / args.contract)},
        "run_dir": args.run_dir.as_posix(),
        "source": provenance(ROOT / args.run_dir),
        "execution": accounting(ROOT / args.run_dir),
        "denominator": {"requests": len(denominator), "usable_for_fitting": len(rows),
                        "outcome_counts": outcome_counts,
                        "note": "Unusable requests are those whose repair was never issued, so no decision "
                                "state exists. They stay in the denominator and are reported by outcome."},
        "splits": {k: {"requests": len(v), "clip_lost": int(sum(r["clip_lost"] for r in v)),
                       "completed": int(sum(r["completed"] for r in v)),
                       "groups": sorted({r["group"] for r in v})}
                   for k, v in split_of.items()},
        "B0_fit": b0,
        "B1_selected_variant": b1_key,
        "B1_dev_losses": {k: v["dev_loss"] for k, v in variants.items()},
        "M_fits": [{"seed": f["seed"], "dev_loss": f["dev_loss"], "selected_epoch": f["selected_epoch"]}
                   for f in m_fits],
        "M_budget": budget,
        "held_out_results": results,
        "decision": {
            "margin": margin,
            "b0_minus_best_other_false_safe": gap_a,
            "b0_minus_best_other_ranking_regret": gap_b,
            "verdict": verdict,
            "metric_b_resolution": results["B0"]["ranking_regret_clip"]["resolution"],
            "margin_cannot_resolve_one_context": bool(
                margin <= results["B0"]["ranking_regret_clip"]["resolution"]),
            "pre_registration_defect": (
                "The registered margin and the ranking metric's own resolution are both one context in "
                "twenty. A margin equal to the smallest difference the metric can express cannot "
                "separate signal from a single context changing hands, so the metric-B branch of the "
                "rule was unresolvable by construction. This is a flaw in the pre-registration, not in "
                "the data; it is recorded rather than corrected after the fact. A future block wanting "
                "to decide on this metric needs either more held-out contexts or a margin of at least "
                "two contexts, set before collection."),
            "rule": contract["decision_rule"],
        },
        "scope_and_limitations": contract["scope_and_limitations"],
    }
    # A compact, centreline-free copy of the dataset so the figure and any later
    # check can be rebuilt without torch and without re-reading every ledger.
    dataset = ROOT / (args.dataset_out or (args.run_dir / "study_dataset.json"))
    scores = {"B0": dict(zip([r["case"] for r in test], b0_scores_test.tolist(), strict=True)),
              "B1": dict(zip([r["case"] for r in test], b1_scores_test.tolist(), strict=True)),
              "M": dict(zip([r["case"] for r in test], m_scores_test.tolist(), strict=True))}
    dataset.write_text(json.dumps({
        "contract_content_sha256": report["contract"]["content_sha256"],
        "b0_threshold_m": b0["threshold_m"],
        "denominator": data["denominator"],
        "rows": [{k: row[k] for k in ("case", "context", "group", "split", "action_kind",
                                      "action_index", "action", "features", "outcome",
                                      "clip_lost", "completed", "mount_id", "decision_pose_id")}
                 | {"commanded_magnitude_m": commanded_magnitude(row, retract)} for row in rows],
        "test_scores": scores,
    }, indent=1, default=float), encoding="utf-8")

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    report["dataset"] = dataset.relative_to(ROOT).as_posix()
    out.write_text(json.dumps(finite(report), indent=2, allow_nan=False, default=float), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "requests": len(denominator), "usable": len(rows),
                      "b0_threshold_m": b0["threshold_m"], "out": args.out.as_posix()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
