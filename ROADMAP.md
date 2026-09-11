# Roadmap: constrained-cable connector recovery

**Status: the V1 question is closed; a V2 question is open.** The question this repository was built to answer has been answered with a pre-registered, held-out measurement, and re-running it would only invalidate it. The answer is a corner case, though, and the corner is named: every arm was handed the socket's exact pose and the cable's exact shape. V2 removes that and asks where the answer flips. The next-session prompt is `artifacts/prompts/cable_v2_perception_handover_20260911.txt` (ignored artifacts); this file stays the maintained plan.

**Active scope:** industrial cable handling and connector insertion. Establish a credible physical task, measure where competent methods actually fail, and test the smallest justified improvement.

**Endpoint:** held, clip-preserving seating before gripper release. The robot still holds the plug, real tip/base engagement and a continuous 0.5 s dwell are reached before the deadline, the required open clip stays captured, and no load limit or state-mutation rule is broken. Not a released or latched connection, electrical function, learned pickup, grasp-robustness result or hardware transfer.

**The question, as pre-registered:** when a supervisor must choose a clearance repair, is the boundary between a repair that keeps the required clip and one that overdraws the cable a simple analytic function of the observable state, or does it need a learned action-outcome model?

## Verified state (block v3 r01, 2026-09-11)

| Item | Verified state |
| --- | --- |
| Block | 1,440 registered requests over 60 contexts: 5 layouts x 3 installed service loops x 2 port mounts x 2 decision poses, 24 clearance actions each. Launched from a clean tree at `01d87b4`, the pre-registration commit. [Contract](configs/cable_repair_boundary_v3.json), [record](evidence/cable_repair_boundary_v3.json), [figure](evidence/cable_repair_boundary_v3.png). |
| Denominator | 1,440 requested, 1,440 executed, 1,440 scored. 739 reached held clip-preserving seating, 322 released the clip, 379 aborted on load. No deadlines, no settling rejections, no infeasible constructions. |
| Guards | 0 forbidden mutation events across the whole block. |
| Cost | 72,874,693 job steps plus 28,800,000 settling steps; 32,620 s summed worker time in 2,737 s of wall time on 12 workers; median request 22.6 s; 3,117 native steps/s per worker and 37,147 aggregate. No training ran during collection. |
| Held-out design | Whole (layout, installed loop) families. Train 7 groups, dev 3, test 5, frozen before launch. Test: 480 requests, 142 clip losses, 20 contexts. |
| **B0** analytic budget | One fitted scalar: reject a repair whose straight-line plug-boot to strain-relief distance at the commanded endpoint exceeds **409.4 mm**. Held-out false-safe rate **0.162**, ranking regret **0.25**. |
| **B1** feature model | L2-regularised logistic regression over 14 named features; linear variant chosen on dev. False-safe **0.156**, ranking regret **0.25**. Makes the **identical decision to B0 in all 20 held-out contexts**. |
| **M** learned model | Action-conditioned MLP over the 24-vertex centreline, pose and action; three seeds, checkpoints by dev loss inside a frozen budget. False-safe **0.148**, ranking regret **0.15**. |
| No filter | Reference, not a predictor: allowing every repair gives a 0.296 clip-loss rate and issues the wrong repair in **18 of 20** contexts. |
| Is M's advantage real? | It is two contexts out of twenty, paired sign-test p = 0.5. Its three seeds give 0.15 / 0.25 / 0.50, mean 0.30 — **worse than B0**; one seed of three is worse than B0. Cluster bootstrap on the false-safe gap: B0 - M = +0.016, 95% interval **[-0.017, +0.050]**, spanning zero. |
| **Pre-registered verdict** | **`inconclusive_neither_branch_triggered`.** B0 sits inside the declared margin on the false-safe metric (gap 0.014) and outside it on ranking regret (gap 0.10), so neither the wrap-up branch nor the publication branch fired. |
| Pre-registration defect | The margin was 0.05 and the ranking metric's resolution is one context in twenty, which is also 0.05. That branch was unresolvable by construction. Recorded, not corrected after the fact. |
| Envelope is geometry | Release travel 84.40 / 84.88 / 85.59 mm at 4 / 20 / 40 mm/s: **1.41% over a tenfold speed range**. The 4 mm/s run reproduces the v2 ledger sample for sample. |
| Mount control | The compliant bracket reproduces its declared stiffness to a relative error of 1.9e-13 with off-axis coupling at 1.3e-16 m, under a known load. With no compliance declared the compiled scene is unchanged from v2. |
| Compliance is not a fault | 15 of 15 completed with the clip retained across lateral stiffness {rigid, 8000, 4000, 2000, 1000} N/m crossed with offsets {0, 2, 4} mm. Every arm sees the port's live pose, so a moving target is tracked. Preserved with the layout screen and the action shakedown in [evidence/cable_support_probes_v3.json](evidence/cable_support_probes_v3.json). |
| Factor effects | Clip loss 28.1% from the home pose against 16.7% from the engaged pose. Load aborts 36.8% on a rigid mount against 15.8% on a compliant one. Clip loss 10.8% to 37.2% across the five layouts. |
| **Open failure** | The 46-segment spatial refinement does not survive settling at 4, 8 **or** 16 kHz. Not an integration-step artefact. Discretisation insensitivity is **not** established and every result is scoped to the 23-segment cable model. |

## What this settles, and what it does not

It settles that on this task a repair supervisor needs a safety filter and that one number is a sufficient one. Nothing that saw more of the state — fourteen engineered features, or the entire cable centreline — changed the decision by more than its own training noise. Learning does not earn its data cost here.

It does not settle that the safe-repair boundary is simple in general. It is one task, one connector, one cable model, and one observation interface in which the port's true pose is handed to the controller at 500 Hz. The honest reading is narrower than the headline: **when the constraint that a repair can violate is a length budget, and that budget's endpoint is computable in closed form from the observed pose, a scalar is the right representation.** Where a repair's consequence is not a budget, none of this transfers.

## The single next action

**Make the 46-segment cable model survive its settling transient, or revise the cable model, and re-run the controls.** Until that passes, every number here is a property of a 23-segment discretisation rather than of a cable, and a reviewer is entitled to ask whether the 409 mm threshold describes the cable or its polyline. It also gates any transfer statement: a simulation result whose mesh refinement crashes cannot claim anything about hardware.

It is the first task in the V2 handover for exactly that reason. The two items behind it, in order of value: the observation interface must consume an *estimate* of the socket pose and cable shape rather than ground truth, since handing every arm the truth is why nothing in V1 ever failed; and the load-abort class (26% of requests) is censored with respect to clip loss, because an action that aborts never gets to test the clip, so scoring it as "clip kept" is not quite true.

## Why the earlier plan changed

The v2 block ended with a plan to widen the support until the competent first attempt failed, then measure whether a learned selector could repair those failures better than rules. That plan was executed as far as the physics allowed and then abandoned on evidence.

Mounting compliance was built, verified against a known load, and defeated nothing. Combined with the 18 of 18 already on record for mounting offsets, the reason became clear and is a property of the interface rather than the mechanics: the observation hands every arm the port's live pose, so a port that moves under contact is tracked rather than missed. The available routes to a residual failure were then to hide information from the comparison arms — which the operating rules forbid, and which would have manufactured the cohort — or to measure something the data genuinely supports.

The safe-repair boundary is well posed whether or not the first attempt fails: given a decision state and a candidate repair, does that repair release the clip? That question was pre-registered, executed and answered. It is also the only framing the 2026-09-10 literature check left open — prior work plans safe cable motions and retries after failure, but does not treat a repair as spending a physical budget it can overdraw and undo a completed step.

## History

Closed cycles, the preserved peg study, the first free-cable cycle and the earlier adaptive-sampling design are kept verbatim in [evidence/roadmap_history_v1.json](evidence/roadmap_history_v1.json) with their original evidence files unchanged. The v2 task and gate block are in [evidence/cable_recovery_block_v2.json](evidence/cable_recovery_block_v2.json) and its [independent replay](evidence/cable_recovery_replay_v2.json). [evidence/INDEX.json](evidence/INDEX.json) lists every record with its declared id, status and scope.
