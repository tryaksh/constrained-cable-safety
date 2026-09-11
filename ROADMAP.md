# Roadmap: constrained-cable connector recovery

**Status: the v3 question is closed; the v4 question is executing.** The first question this repository asked has been answered with a pre-registered, held-out measurement, and re-running it would only invalidate it. The answer is a corner case, though, and the corner was named: every arm was handed the socket's exact pose at 500 Hz and the cable's exact shape. v4 removes that and asks how much a safety check actually needs to see, as perception degrades and across three constraint shapes. Its contract is [configs/cable_perception_v4.json](configs/cable_perception_v4.json), frozen and committed before launch.

**Active scope:** industrial cable handling and connector insertion. Establish a credible physical task, measure where competent methods actually fail, and test the smallest justified improvement.

**Endpoint:** held, clip-preserving seating before gripper release. The robot still holds the plug, real tip/base engagement and a continuous 0.5 s dwell are reached before the deadline, the required open clip stays captured, and no load limit or state-mutation rule is broken. Not a released or latched connection, electrical function, learned pickup, grasp-robustness result or hardware transfer.

## The v4 question, as pre-registered

**How much must a safety check see?** As the state estimate degrades the way real perception degrades, where does a predicate over richer observations start to beat a scalar over estimated state — and does that crossover move with the *shape* of the constraint?

Three constraints are scored on the same rollout, chosen so their shapes differ as much as the task allows: **C1** clip retention, a global length budget; **C2** minimum bend radius, a local curvature limit; **C3** peak anchor load, a rate-dependent dynamic limit. Six arms read the identical estimate: the v3 scalar, that scalar carrying a margin sized from the declared estimator covariance, a force-only arm, a feature model, a network over the whole estimated centreline, and that network plus a short observation history. The crossover prediction, the margin, the metrics, the group split and the full request list were frozen in the contract and committed at `0842900` before the first request launched.

## Verified state: the instrument

| Item | Verified state |
| --- | --- |
| **The v3 open failure** | **Cleared, and relocated.** The 46-segment refinement did not fail because of discretisation. The control that tested it scaled per-joint bending damping as `c ∝ L`; a continuum Kelvin–Voigt bending moment discretises to `γI/L`, so halving the segment length must *double* it. [The control](evidence/cable_discretisation_v4.json) reproduces the original instability at 4, 8 and 16 kHz at the registered damping, and with the corrected scaling **not one of nine cells is unstable**. |
| Does the cable model refine? | Yes, on the quantity the safety threshold is built on. A fourfold refinement (92 segments at 5 mm) settles at 4, 8 and 16 kHz, retains the clip at all three, and reproduces the registered 23-segment settled boot-to-anchor distance to **5.7 µm** at the matched rate and **0.18 mm** across every settled cell. Minimum bend radius does **not** agree within its declared 2 mm tolerance, so C2 stays scoped to the 23-segment model at 4 kHz. |
| **The new open item** | The routed cable is **not at rest** at the registered 5 s settling deadline. It slides laterally along the clip channel for another eight seconds and comes to rest against the clip wall — which is exactly where the retention predicate's lateral test sits. The measured resting crossing is **2.9 µm past it** at 4 kHz and 5.3 µm past it at 16 kHz. The deadline is part of the task definition, not an approximation to rest. Neither it nor the predicate was changed. |
| Support, widened | 12 layouts × up to 3 installed loops, screened per cell: **29 of 42 candidate cells registered, 13 rejected** with their reasons in [the screen](evidence/cable_layout_screen_v4.json). v3 had 5 layouts and 15 groups. Clip positions from 130 to 195 mm, doglegs to 35 mm, two shelf heights, and a corner route. The distal catch route that never survived settling is retired rather than carried forward. |
| A criterion withdrawn, not tuned | The candidate file declared a 1 mm floor on the installed clearance between the cable and the retention predicate's own wall. The screen measures that this floor rejects **L1, the validated v2/v3 layout the whole repository is built on** — its cells install at 0.14, 1.87 and 1.05 mm. A criterion that rejects the reference cannot be the right criterion, so it is withdrawn and reported as a diagnostic. Both verdicts are kept. |
| Privilege guard | Fail-closed, with a **positive control that fires**: a request that deliberately reads a scoring-only channel inside the control window fails with `privilege_violation`, and the same request without the probe runs clean. [Controls](evidence/cable_perception_controls_v4.json). |
| The zero-error anchor | At E0 the estimate a controller reads **is** the truth, exactly — asserted in the compiled scene, not in prose — so the anchor reproduces the v3 interface rather than approximating it. |
| Occlusion is geometry | Derived from a declared camera eye against the clip channel and the mount assembly. It hides **5 to 6 of the 24 centreline nodes**: the run descending behind the mount and the node inside the clip. The occluded nodes carry about five times the visible nodes' error. Not uniform noise. |
| Two choices made from the pilot | The C2 spec moved from the static band (4–6× OD) to the dynamic one (10–15× OD), because the static band fires on 0.5% of requests and cannot be measured, while a repair is a commanded *motion* and every registered cell installs above 40 mm. The error ladder was compressed to 0–2 mm of socket bias, because above that almost nothing reaches seating and every arm abstains. Both are recorded with the measurement that forced them in [the pilot](evidence/cable_perception_pilot_v4.json). |
| Metric resolution, in code | 60 test contexts per error level, so the ranking metric's resolution is 1/60 and the registered margin of 0.05 is three times it. The runner **refuses** a margin below twice the coarsest resolution. v3 registered a margin exactly equal to its resolution and returned a verdict that was unresolvable by construction; that cannot happen again. |
| Censoring, declared before collection | A request cut short by the force abort is **censored** on every constraint it had not already violated, never scored as respecting one. Censored actions count in a predictor's coverage — so it cannot hide behind them — but not in its numerator, and the censored share is reported beside every rate. |
| Throughput | 28,086 aggregate native steps/s on 12 workers against **44,966 on 20** — a 1.60× speedup for a 6.6% per-worker loss, on 24 physical cores. Collection is CPU-only: MJX does not support this scene's cable elasticity plugin, composite bodies or elliptic friction cone. |

## Verified state: the block

**Executing.** 16,080 registered requests across 870 ladder contexts and 180 single-factor isolation cells, in four shards on 20 workers. The block's verified state, the crossover verdict and the release figure land here when it completes and is fitted.

## What v3 settled, and what it did not

It settles that on this task a repair supervisor needs a safety filter and that one number is a sufficient one. Nothing that saw more of the state — fourteen engineered features, or the entire cable centreline — changed the decision by more than its own training noise. Learning does not earn its data cost there.

It does not settle that the safe-repair boundary is simple in general. It is one task, one connector, one cable model, and one observation interface in which the port's true pose is handed to the controller at 500 Hz. The honest reading is narrower than the headline: **when the constraint that a repair can violate is a length budget, and that budget's endpoint is computable in closed form from the observed pose, a scalar is the right representation.** Where a repair's consequence is not a budget, none of that transfers — which is why v4 scores three constraint shapes rather than one.

The v3 block itself: 1,440 requests over 60 contexts, 739 reaching held clip-preserving seating, 322 releasing the clip, 379 aborting on load; B0 a single 409.4 mm threshold at a held-out false-safe rate of 0.162; B1 making the identical decision in all 20 held-out contexts; M better in two contexts out of twenty, inside a bootstrap interval spanning zero and worse than B0 on one of its three seeds. Verdict `inconclusive_neither_branch_triggered`, with the pre-registration defect behind it recorded rather than corrected. [Contract](configs/cable_repair_boundary_v3.json), [record](evidence/cable_repair_boundary_v3.json), [controls](evidence/cable_boundary_controls_v3.json), [figure](evidence/cable_repair_boundary_v3.png).

## The single next action

**Fit the executed perception block and apply the registered crossover rule.** Every downstream tool is written, committed and smoke-tested against the pilot: the fitter, the ledger replay, the release figure, the video renderer and the summariser. Nothing in the analysis may be changed after the test split is read.

## History

Closed cycles, the preserved peg study, the first free-cable cycle and the earlier adaptive-sampling design are kept verbatim in [evidence/roadmap_history_v1.json](evidence/roadmap_history_v1.json) with their original evidence files unchanged. The v2 task and gate block are in [evidence/cable_recovery_block_v2.json](evidence/cable_recovery_block_v2.json) and its [independent replay](evidence/cable_recovery_replay_v2.json). [evidence/INDEX.json](evidence/INDEX.json) lists every record with its declared id, status and scope.
