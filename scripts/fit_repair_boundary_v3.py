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
    build_contexts,
    content_sha256,
    feature_row,
    outcome_label,
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


def fit_b0(values: np.ndarray, labels: np.ndarray) -> dict:
    """One scalar threshold on the analytic endpoint distance, by balanced accuracy."""
    order = np.unique(values)
    midpoints = np.concatenate([[order[0]-1e-6], (order[:-1]+order[1:])/2, [order[-1]+1e-6]])
    positive, negative = labels == 1, labels == 0
    best = None
    for threshold in midpoints:
        predicted = values > threshold
        if not positive.any() or not negative.any():
            continue
        score = 0.5*(predicted[positive].mean()+(~predicted[negative]).mean())
        if best is None or score > best[1]:
            best = (float(threshold), float(score))
    return {"threshold_m": best[0], "train_balanced_accuracy": best[1]}


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


def false_safe_at_coverage(scores: np.ndarray, truth: np.ndarray, coverage: int) -> float:
    """Of the `coverage` actions a predictor is most confident are safe, how many lost the clip."""
    if coverage <= 0:
        return float("nan")
    order = np.argsort(scores, kind="stable")[:coverage]
    return float(truth[order].mean())


def ranking_regret(rows, scores: np.ndarray, safe: np.ndarray, key: str) -> dict:
    """The registered supervisor procedure, scored per test context."""
    core = [i for i, row in enumerate(rows) if row["action_kind"] == "core"]
    contexts: dict[str, list[int]] = {}
    for i in core:
        contexts.setdefault(rows[i]["context"], []).append(i)
    regret = abstain = scored = 0
    for indices in contexts.values():
        allowed = [i for i in indices if safe[i]]
        if not allowed:
            abstain += 1
            continue
        chosen = max(allowed, key=lambda i: (np.linalg.norm([rows[i]["action"]["retreat_m"],
                                                             rows[i]["action"]["excursion_m"]]),
                                             -rows[i]["action_index"]))
        scored += 1
        bad = rows[chosen]["clip_lost"] if key == "clip_lost" else 1-rows[chosen]["completed"]
        regret += int(bad)
    return {"contexts": len(contexts), "scored": scored, "abstentions": abstain,
            "regret": regret/scored if scored else float("nan"),
            "mean_predicted_risk": float(np.mean(scores[core])) if core else float("nan")}


def evaluate(name, rows, scores, safe, coverage) -> dict:
    truth = np.asarray([row["clip_lost"] for row in rows])
    return {
        "predictor": name,
        "predicted_safe": int(safe.sum()),
        "false_safe_rate_own_operating_point": float(truth[safe].mean()) if safe.any() else float("nan"),
        "false_safe_rate_matched_coverage": false_safe_at_coverage(scores, truth, coverage),
        "balanced_accuracy": balanced_accuracy(truth, ~safe),
        "ranking_regret_clip": ranking_regret(rows, scores, safe, "clip_lost"),
        "ranking_regret_completion": ranking_regret(rows, scores, safe, "completed"),
    }


def balanced_accuracy(truth: np.ndarray, predicted: np.ndarray) -> float:
    positive, negative = truth == 1, truth == 0
    if not positive.any() or not negative.any():
        return float("nan")
    return float(0.5*(predicted[positive].mean()+(~predicted[negative]).mean()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=Path("configs/cable_repair_boundary_v3.json"))
    parser.add_argument("--out", type=Path, required=True)
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

    results = {
        "B0": evaluate("B0", test, b0_scores_test, b0_safe_test, coverage),
        "B1": evaluate("B1", test, b1_scores_test, b1_scores_test < 0.5, coverage),
        "M": evaluate("M", test, m_scores_test, m_scores_test < 0.5, coverage),
    }
    for seed_index, fit in enumerate(m_fits):
        results[f"M_seed{fit['seed']}"] = evaluate(
            f"M_seed{fit['seed']}", test, m_scores[seed_index], m_scores[seed_index] < 0.5, coverage)

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
        "schema": 1, "id": "cable_repair_boundary_v3_fit", "created_on": "2026-09-11",
        "contract": {"path": args.contract.as_posix(), "content_sha256": content_sha256(ROOT / args.contract)},
        "run_dir": args.run_dir.as_posix(),
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
            "rule": contract["decision_rule"],
        },
        "scope": contract["scope_and_limitations"],
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, allow_nan=True, default=float), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "requests": len(denominator), "usable": len(rows),
                      "b0_threshold_m": b0["threshold_m"], "out": args.out.as_posix()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
