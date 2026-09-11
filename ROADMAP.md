# Roadmap: constrained-cable connector recovery

**Active scope:** industrial cable handling and connector insertion. Establish a credible physical task, measure where competent methods actually fail, and test the smallest justified improvement. The preserved Franka/FORGE peg study and the first free-cable cycle are historical evidence, not restrictions.

**Endpoint:** held, clip-preserving seating before gripper release. The robot still holds the plug, real tip/base engagement and a continuous 0.5 s dwell are reached before the deadline, the required open clip stays captured, and no load limit or state-mutation rule is broken. This is not a released or latched connection, electrical function, learned pickup, grasp-robustness result or hardware transfer.

**Question:** on unfamiliar cable layouts and mechanical combinations, when does a learned action-outcome selector improve clip-preserving recovery over competent cable-aware rules and planning at matched experience and inference cost?

## Verified state (block v2 r01, 2026-09-10)

| Item | Verified state |
| --- | --- |
| Task | Built and executed. World-fixed mount plate on standoffs, riser, shelf, support column, one escapable open clip, one shallow post, an instrumented strain relief, and a 0.46 m cable clamped at the boot and the strain relief. [Runtime config](configs/cable_recovery_task_v2.json). |
| Clocks | Separated. 50 Hz policy, 500 Hz servo, 4 kHz physics. Doubling to 8 kHz leaves job duration, servo tick count, dwell, outcome and clip margin unchanged (margins agree to 2e-8 m). |
| Forces | One authoritative post-step stream replaces the v1 two-sample maximum. Strain-relief reaction read from the connect constraint, cross-checked against a sensor whose 0.0496 N static offset is measured by an unloaded control. |
| Mass | Compiled cable mass equals the declared 0.05 kg exactly; v1 compiled 6.67% heavy. |
| Guards | Fail-closed mutation guard on every controller call; a deliberate 1e-4 rad pose write fails the job. |
| Replay | 34 of 34 replayable requests reproduce status, reason, witness, dwell and elapsed time exactly from the stored ledgers. One request was rejected before the job clock and has no samples. [Replay record](evidence/cable_recovery_replay_v2.json). |
| Physical envelope | The open clip releases after **84.4 mm** of plug retreat from the port. Release is kinematic slack exhaustion: the strain-relief reaction stays under 0.2 N throughout. |
| Recovery witness | A blind existing routine jams on a mounting offset and produces a witnessed contact stall on two layouts; with no repair the request runs out its deadline with the stall active; with a robot-driven repair every request reaches held clip-preserving seating. |
| Constraint matters | The same `over_travel_clear` macro releases the required clip when issued near home (84.4 mm retreat) and preserves it when issued from the inserted pose (about 79 mm). Identical action, opposite consequence, decided by state. |
| Screen | 18 of 18 requests across installed service loop 2/4/6 mm by mounting offset 0/2/4 mm completed with the clip retained under both arms. No witness fired, so the cable-aware repair layer never ran. |
| Failed control | The 46-segment spatial refinement does not survive its own settling transient. Discretisation insensitivity is **not** established. Preserved, not retried under a changed rule. |
| Learning | None. No predictor, recurrent baseline or policy has been trained on any cable task. |
| Cost | 35 requests, 1,447,106 job steps plus 720,000 settling steps, 708 s summed worker time in 87 s of wall time on 12 workers. Measured aggregate 25.0k native steps/s against the v1 serial 1.78k. |
| Release | [Block record](evidence/cable_recovery_block_v2.json), [labelled figure](evidence/cable_recovery_v2.png), [replay record](evidence/cable_recovery_replay_v2.json). |
| **Single next action** | Broaden the registered support to conditions the competent first attempt cannot prevent, then re-screen before any acquisition or training. |

## Why learning is not yet earned

Gate G4 requires competent rules or planning to leave a reproducible feasible residual failure, or a predeclared material cost deficit. On the registered G3 support they leave neither: exact target knowledge plus bounded force-guided retries prevents every cell outright, and a prevented visible offset is prevention, not recovery. That is a result about this support, not a claim that learning is unnecessary in general. Do not open acquisition or training until a re-screen produces a measured residual.

## Next block

1. **Widen the support to what competence cannot prevent.** Candidates, in order of expected yield: unmodelled mounting compliance so the true port pose moves under contact; installed service loop taken close to the measured 84.4 mm envelope so ordinary repairs approach clip release; distal catch routes that survive settling. Each needs its own G1 controls before it enters a screen.
2. **Fix the two open measurement gaps.** The 46-segment spatial control must pass or the model must be revised; cable tension is still not a named measured channel; peak contact sums differ about 70% between the two physics resolutions and must never be quoted as resolution-independent.
3. **Re-screen with the same arms** on the widened support, 64-128 registered development contexts across layout and mechanical families, whole-request and common-cohort accounting kept separate.
4. **Only on a measured residual**, start with a compact action-conditioned outcome ranker over the shared repair library, include bad repairs in held-out prediction, and compare separate local/distal predictors and a direct history-based selector before claiming anything a joint model adds.

Budget the next block from the measured throughput above, not from the v1 extrapolation: 12 workers sustain roughly 25k native steps/s on the corrected task, so a 128-request screen costs a few minutes of wall time and a 3,000-request acquisition is hours, not days. Keep one serial queue for any GPU work. Time exhaustion is an incomplete handoff, not a result.

## Distal catch: a specific unresolved construction

Routing the cable around the shallow post is registered in the task but does not yet survive settling: the detour route either folds at construction or the cable migrates out of the clip channel during relaxation. Diagnosed cause is that surplus service-loop cable has no stable resting place near a 20 mm clip channel. The gravity ramp fixed the free route; the catch route needs either a longer shelf run past the clip, a second clip, or a catch expressed as a post the cable is pressed against rather than routed around. Every failed attempt is preserved in the run artifacts.

## History

Closed cycles, the preserved peg study, the first free-cable cycle and the earlier adaptive-sampling design are kept verbatim in [evidence/roadmap_history_v1.json](evidence/roadmap_history_v1.json) with their original evidence files unchanged. [evidence/INDEX.json](evidence/INDEX.json) lists every evidence record with its own declared id, status and scope so one file can be chosen without reading many.
