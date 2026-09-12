# Assembly Recovery Lab

**When a robot's connector insertion fails and it has to back off and try again, how much does a safety check need to *see* to know the move is safe — and does the answer depend on what "safe" means?**

Two pre-registered simulation studies, on a UR5e with pinned [Intrinsic AIC](https://github.com/intrinsic-ai/assembly-industrial-benchmark) SC connector assets through a project-owned native MuJoCo adapter.

The first study answered a narrower question and answered it cleanly: given the socket's exact pose and the cable's exact shape, one fitted number — a 409.4 mm threshold — decides a repair as well as a neural network that watches the whole cable. The second study exists because that result is a corner case, and says so: *every arm was handed the truth.*

## Study 2 — how much must a safety check see?

Every arm now reads an **estimate**. The socket's pose carries a per-episode systematic bias with temporally correlated jitter; the cable's centreline carries node error structured by occlusion derived geometrically from the fixture and a declared camera, plus whole-node dropout; and a stochastic disturbance moves the cable for reasons no estimator can attribute. Ground truth is scoring-only, behind a fail-closed guard with a positive control that fires.

Three constraints are scored **on the same rollout**, chosen so their shapes differ as much as the task allows:

| | Constraint | Shape | Why it is here |
| --- | --- | --- | --- |
| **C1** | the required clip is still held | a **global length budget** | the v3 constraint, unchanged, so the zero-error level is comparable request for request |
| **C2** | minimum bend radius above spec | a **local curvature limit** | no pose determines it; it is a property of the whole shape, and the published industrial spec is what actually destroys harnesses |
| **C3** | peak anchor load under limit | a **rate-dependent dynamic limit** | it depends on how the cable got where it is, not only on where it is |

Six arms read the identical estimate and rank the identical actions: the v3 scalar (**B0**); that scalar carrying a margin sized from the *declared* estimator covariance (**B0+**, which is measurement-robust control-barrier-function thinking applied to this predicate, credited not claimed); force only, with no vision channel at all (**B2**); a feature model (**B1**); a network over the whole estimated centreline (**M**); and that network plus a short observation history (**Mh**).

**16,080 requests, 1.49 billion integration steps, 9.05 hours, zero guard violations.** The contract — the error ladder, the metrics, the margin, the group split, the full request list and a falsifiable prediction for each constraint — was frozen and committed at `0842900` before the first request launched.

| Safety check | Carries | C1 false-safe, no error → 2 mm | C3 false-safe |
| --- | --- | --- | --- |
| **B0+** scalar + declared margin | **1 parameter** | **0.133 → 0.220** | 0.034 → 0.044 |
| **B2** force only, no vision | 10 | 0.116 → 0.203 | **0.008 → 0.031** |
| **B1** feature model | 19 | 0.145 → 0.190 | 0.012 → 0.044 |
| **M** learned over the whole shape | ~30,000 | 0.208 → 0.288 | 0.013 → 0.033 |
| **Mh** + short history | ~30,000 | 0.226 → 0.309 | 0.027 → 0.055 |

**No crossover, on any of the three constraints, anywhere in the range.** Nothing beats one number by more than the registered margin at any error level — and on the clip budget the network watching the whole cable is *significantly worse*, by 0.074 with a bootstrap interval excluding zero, with a per-seed spread too tight for that to be noise.

**Two of the three pre-registered predictions were wrong, which is the useful part.** The length budget behaved as predicted. The curvature limit did not need the richer representation. And force-only — the fallback the cable-manipulation literature proposes for exactly this situation — is the best arm on all three constraints at every level, but never by more than the 0.05 margin the contract declared, so it cannot be certified as a win. Three of fifteen cells were refused outright by the resolution check, and are reported as refused.

![How much must a safety check see](evidence/cable_perception_v4.png)

## What you can actually use

A predicate that answers *yes or no about one motion* is not much use to a cell. Nothing in harness work is one motion: you seat a connector, dress the cable, clip it, move to the next fixture — and the cable's remaining slack, its tightest bend and the load on its anchor are all carried from one step into the next. So the study ships a **safety layer**, not a number, and then asks whether that layer survives being used the way a real task would use it.

[`SafetyFilter`](src/assembly_recovery/cable_safety_filter_v4.py) loads its thresholds straight out of the evidence record, so a shipped filter and a published number cannot drift apart. It does three things a per-action verdict cannot:

- **`verdict`** scores all three constraints and names which one a motion would break, reporting a constraint it has no rule for as *unscored* rather than silently approving it.
- **`envelope`** maps the whole continuous action space in one call — retreat × bearing × excursion — so a planner sees the shape of what is allowed instead of probing it action by action.
- **`budget`** reports how much of each constraint's headroom a motion spends, because a step that is individually safe can still leave the next one nothing.

It runs off *the estimator's own account of itself* — a systematic bias, a jitter standard deviation and a worst-case error on a node it cannot see — so any pose estimator that reports those three numbers can drive it without the study's registered ladder.

## Study 3 — does the check chain?

A predicate that judges one motion is not usable by a cell; nothing in harness work is one motion. [A second pre-registered study](configs/cable_sequence_v5.json) issues **three** filtered decisions in one sequence, on held-out contexts the filter was never fitted on, against three supervisors: the filter taking the largest safe motion, the same filter taking the most cautious one, and no filter at all.

**720 sequences, 2,160 decisions, 72.9 million steps, zero guard violations.**

| Over a three-step sequence | Clip lost, no error / 1 mm / 2 mm | Route completed |
| --- | --- | --- |
| no filter, largest motion every time | **80 / 80 / 80 of 80** | 0 / 0 / 0 |
| filter, take the largest safe motion | 32 / 33 / 36 of 80 | 48 / 25 / 0 |
| filter, take the motion with most headroom | **8 / 10 / 37 of 80** | **72 / 41 / 3** |

**The filter earns its place, and it is not close.** Every single unfiltered sequence pulled the cable out of the clip — a rate of 1.000 at all three error levels, against 0.40 to 0.57 filtered.

**But the check does not chain for free.** The per-step violation rate for the clip budget *rises* by 0.089 between the first decision and the last once estimation error reaches 2 mm — more than the registered 0.05 margin, so **the clip budget does not compose**. Curvature and anchor load do. That is the reverse of what was predicted, and it is the more useful answer: the constraint the filter measures directly is the one that degrades along a chain, because each accepted step spends slack the next step is then judged against.

**And how greedily you spend what the filter allows dominates the result.** Same filter, same estimate, different appetite: taking the motion with the most headroom rather than the largest safe one cuts clip loss from 0.40 to 0.10 *and* raises completion from 0.60 to 0.90. That comparison was not pre-registered and carries no verdict — it is reported as exploratory — but it says something a score would hide: the safety check tells you what is permitted, and how much of that you take is a separate engineering decision that this study did not optimise.



## Study 1 — the 409 mm rule

**1,440 physical repair attempts** across 60 registered cable layouts and mounting conditions — 101.7 million simulation steps and 9.1 worker-hours in 46 minutes of wall time, every request kept in the denominator.

| Predictor | What it sees | False-safe rate | Wrong repair issued |
| --- | --- | --- | --- |
| **no filter** | nothing; every repair allowed | 0.296 | **18 of 20 contexts** |
| **B0** analytic budget | one number: straight-line plug-boot to strain-relief distance at the commanded endpoint | 0.162 | 5 of 20 |
| **B1** feature model | 14 hand-designed features | 0.156 | 5 of 20 |
| **M** learned model | the whole 24-vertex cable centreline, pose and action | 0.148 | 3 of 20 |

**Having a safety filter is worth a great deal. Which filter you use is worth almost nothing.** One fitted scalar cuts wrong repairs by 72%. The 14-feature model made *the identical decision in all 20 held-out contexts*. The learned model differed in 2 of 20 — smaller than its own spread across three training seeds (0.15 / 0.25 / 0.50, mean 0.30, worse than B0) and inside a bootstrap interval containing zero.

**The pre-registered verdict was `inconclusive`, and that is reported as the result.** B0 fell inside the declared margin on one metric and outside it on the other. The reason is a flaw in our own pre-registration, recorded rather than quietly fixed: the margin was 0.05 and the ranking metric's resolution is one context in twenty, which is also 0.05. A margin equal to the smallest difference a metric can express cannot decide anything. Study 2 fixes this in code — the runner refuses a margin below twice the coarsest metric resolution — and the full record is in [evidence/cable_repair_boundary_v3.json](evidence/cable_repair_boundary_v3.json).

![Safe-repair boundary, block v3 r01](evidence/cable_repair_boundary_v3.png)

## In plain English

A robot has to plug a connector into a socket. The connector has a cable, and that cable is clipped into a bracket partway along its run, the way a real wiring loom is dressed. If the first attempt fails, the robot backs off and tries again — but the cable is only so long. Back off too far, or in the wrong direction, and the cable lifts out of its clip. The robot has undone work it had already finished, and a person has to re-dress the loom by hand.

So before the robot makes a recovery move it should ask: *will this move pull the cable out?* Study 1 measured whether answering that needs a learned model of the cable, or whether simple geometry is enough, and found simple geometry is enough — while handing the robot a perfect measurement of where everything was. Study 2 takes that perfect measurement away, because no real robot has one, and asks the same question three times over: about a cable that is too short, a cable bent too tightly, and a cable pulled too hard.

## Why you can believe the numbers

The measurement apparatus is the part that took the longest, and it is the part worth interrogating.

| Property | How it is enforced |
| --- | --- |
| **Separated clocks** | 50 Hz policy, 500 Hz servo, 4 kHz physics. Doubling the physics rate leaves job duration, servo tick count, dwell and outcome unchanged (clip margins agree to 2e-8 m). |
| **One authoritative force stream** | A single post-step native solve. No maximum over two sampling points. The strain-relief reaction is read from the constraint rows, cross-checked against a sensor whose 0.0496 N static offset is measured by an unloaded control. |
| **Fail-closed mutation guard** | Wraps every controller call. A deliberate 1e-4 rad pose write fails the job. **0 forbidden events across all 1,440 v3 requests.** |
| **Fail-closed privilege guard** | New in study 2. Any control-side read of a scoring-only channel fails the request. A **positive control fires**: the same request with a deliberate truth read fails with `privilege_violation`, and without it runs clean. ([controls](evidence/cable_perception_controls_v4.json)) |
| **The zero-error anchor is exact** | At the bottom of the error ladder the estimate a controller reads *is* the truth, bit for bit, asserted in the compiled scene. The anchor reproduces the earlier interface rather than approximating it. |
| **Exact replay** | 34 of 34 replayable v2 requests reproduce status, reason, witness, dwell and elapsed time from the stored ledgers alone. Study 2 re-derives its clip and anchor labels from the servo ledgers for every request, not a sample. |
| **Honest denominator** | Every registered request counts — load aborts, settling rejections, infeasible constructions. A request cut short by an abort is **censored**, never counted as having respected a constraint it never got to test. |
| **Frozen before launch** | Support, action design, group split, predictor budgets, metric resolutions, the margin and the crossover prediction are committed before the first request. The run's own manifest records a clean tree at the pre-registration commit. |
| **Measured, not declared** | The compliant mount reproduces its declared stiffness to a relative error of 1.9e-13 with off-axis coupling at 1.3e-16 m — under a known load, not by assertion. |

## What the earlier block measured

**The physical envelope is a geometric constant, to 1.4%.** The open clip releases after 84.40 mm of plug travel at 4 mm/s, 84.88 mm at 20 mm/s and 85.59 mm at 40 mm/s — a 1.41% spread over a tenfold change in speed, with the strain-relief reaction under 0.2 N throughout. It is slack exhaustion, not a tension failure. ([controls](evidence/cable_boundary_controls_v3.json))

**State decides an action's consequence, at population scale.** The same repair library issued near the home pose releases the clip in **28.1%** of requests against **16.7%** from the engaged pose.

**Mount compliance halves force aborts and changes nothing else.** A finite-stiffness bracket cuts load aborts from 36.8% to 15.8% and raises completion from 42.8% to 59.9%.

**Layout dominates.** Clip loss ranges from 10.8% to 37.2% across the five v3 layouts — which is exactly why held-out groups are whole layout families and never neighbouring actions. Study 2 widens that support from 5 layouts and 15 groups to **12 layouts and 29 groups**, screened per cell, with 13 of 42 candidate cells rejected and recorded. ([screen](evidence/cable_layout_screen_v4.json))

**Competence with live state was not defeated by mechanical perturbation.** [18 of 18](evidence/cable_recovery_block_v2.json) on mounting offsets, then [15 of 15](evidence/cable_support_probes_v3.json) across an eightfold range of mount stiffness. Every v2/v3 arm was handed the port's live pose at 500 Hz, so a port that moves under contact is simply tracked. Manufacturing a failure by hiding that information from one arm would have produced a better-looking study and a worse one — so study 2 degrades the information for *every* arm equally instead.

## What we got wrong, and found

Six defects surfaced during this work. They are listed because finding them was most of the value.

- **A recorded provenance hash that no committed file reproduces.** The v2 block records `8d9082…` for its config; the committed blob is `34d08b3b…`. Identical content: the archived copy had 1,569 CRLF line endings and git stores LF. A raw byte hash of a text file hashes the checkout, not the content. Hashes are now taken on normalised bytes with the raw hash recorded beside them.
- **A declared parameter that did nothing.** `RepairMacro.speed_m_per_s` was carried through the controller and never applied — every repair ran at the slow insertion approach speed. It was invisible because every macro in the library happened to declare exactly that speed. No recorded result changed; verified by re-running the v2 repair controls, which reproduce their dwell, clip margin and step count exactly.
- **A waypoint that could never retire.** A repair waypoint advanced on *tip* arrival, so a waypoint the cable held the tip short of consumed the whole 40 s deadline in silence. A registered settling window now retires it on reference arrival and counts the lag.
- **An undocumented definition behind a headline number.** The published 84.4 mm envelope is the plug tip's *three-dimensional* travel; its axial component is 84.25 mm. The 0.14 mm gap is the lateral excursion the cable pulls the plug through as it comes taut. Both are now reported.
- **A control that failed because of its own arithmetic.** The 46-segment cable refinement did not survive settling at 4, 8 or 16 kHz, and that was recorded as an open failure against the *cable*. It was the control. A discrete bending joint carries the continuum Kelvin–Voigt moment over one segment, which discretises to `γI/L`, so halving the segment length must **double** the per-joint damping — and the control halved it, quartering the damping ratio of the stiffest representable mode at exactly the refinement where it needed to rise. With the correct scaling, not one of nine cells is unstable, and a fourfold refinement settles at three integration rates and reproduces the registered settled boot-to-anchor distance to **5.7 µm**. ([control](evidence/cable_discretisation_v4.json))
- **A label whose boundary is where the cable comes to rest.** Clip retention requires the cable's crossing to satisfy `|lateral| ≤ half-width − radius` — which is *exactly* the coordinate at which the cable's surface touches the clip wall. The routed cable is not at rest at the registered five-second settling deadline: it slides along the channel for another eight seconds and stops against that wall, measured **2.9 µm past the boundary**. The five-second deadline samples the configuration well inside it, which is why every block here has a stable label. The deadline is therefore part of the task definition, not an approximation to rest, and neither it nor the predicate was changed.

## Reproduce it

```powershell
.venv/Scripts/python.exe scripts/setup_cable.py
.venv/Scripts/python.exe -m ruff check src scripts tests
.venv/Scripts/python.exe -m pytest
```

```powershell
.deps/cable-venv/Scripts/python.exe scripts/screen_layouts_v4.py --workers 14
.venv/Scripts/python.exe scripts/run_perception_v4.py --freeze
.deps/cable-venv/Scripts/python.exe scripts/controls_perception_v4.py
.venv/Scripts/python.exe scripts/run_perception_v4.py --run-id my-run-s1 --shard 1 --of 4 --workers 20 --max-minutes 290
.venv/Scripts/python.exe scripts/fit_perception_v4.py --run-dir artifacts/cable/my-run-s1 --out evidence/my-fit.json
.deps/cable-venv/Scripts/python.exe scripts/render_perception_v4.py --fit evidence/my-fit.json --out evidence/my-fig.png
```

Then the layer, and whether it chains:

```powershell
.deps/cable-venv/Scripts/python.exe scripts/demo_safety_layer_v4.py --run-dir artifacts/cable/my-run-s1
.venv/Scripts/python.exe scripts/run_sequence_v5.py --freeze
.venv/Scripts/python.exe scripts/run_sequence_v5.py --run-id my-sequence --workers 20
.venv/Scripts/python.exe scripts/fit_sequence_v5.py --run-dir artifacts/cable/my-sequence
```

Freezing refuses to run if fewer layouts survived the screen than the contract needs, or if the split would leave fewer held-out contexts per error level than the metric resolution requires. The runner refuses to launch if the frozen task it merges onto is not the one the contract declares. The launcher captures commit, dirty state, source archive, asset hashes, environment and command before the worker starts, and reserves an immutable run id.

**Collection is CPU-only, and that is a constraint rather than a preference.** MuJoCo's native step is CPU, and the GPU path (MJX) does not support this scene's cable elasticity plugin, composite bodies or elliptic friction cone — moving collection to the GPU would mean a different cable model and would invalidate every comparison with the earlier blocks. The lever that does exist is worker count: on 24 physical cores this task sustains **28,086 aggregate native steps/s on 12 workers against 44,966 on 20**, a 1.60× speedup for a 6.6% per-worker loss. Model fitting takes `--device cuda` where a CUDA build of torch is installed; those fits are minutes beside hours of collection.

515 tests run without a GPU, a simulator or any ignored artifact.

## Scope

Simulation only. No hardware, no connector transfer, no released or latched connection, no electrical function, no learned pickup, no grasp-robustness result and no force-certified safety claim. The endpoint is **held, clip-preserving seating before gripper release**: the robot still holds the plug, real tip/base engagement and a continuous 0.5 s dwell are reached before the deadline, the required open clip stays captured, and no load limit or state-mutation rule is broken. The preset grasp and the world-fixed shelf, clip, post and strain relief are disclosed construction boundaries. Bracket compliance is translational only. A single clip is modelled, so retention is a single point of failure by construction, and a second clip is declared out of scope rather than approximated.

**The error model is a model of how perception fails.** It is derived from geometry and declared magnitudes; it is not camera perception, it renders nothing, and no estimator is built or evaluated here. Simulator pose plus noise is not perception.

This is one task, one connector, one cable model and one observation interface. Every claim here is a measured statement about that, not about cable manipulation in general.

## Where things are

[ROADMAP.md](ROADMAP.md) has the verified state and the single next action. [AGENTS.md](AGENTS.md) has the operating rules. [evidence/INDEX.json](evidence/INDEX.json) lists every evidence record with its own declared scope, so one can be chosen without reading many. These three Markdown files are the only maintained prose.

Prior art this positions against, checked 2026-09-10 and independently re-fetched 2026-09-11 — [every claim and the two that were overstated](evidence/cable_citation_check_v4.json): [WireCraft](https://arxiv.org/abs/2606.18097) benchmarks constrained-cable connector insertion and clip routing; [joint shape and tension prediction](https://arxiv.org/abs/2505.13889) already enforces safe planned cable motion; [FAR](https://arxiv.org/abs/2607.01111) and the tactile, corrective and predictive connector work already do retry and recovery. Measurement-robust control barrier functions already give worst-case safety certificates under bounded state-estimation error — the B0+ arm is an *application* of that idea, not a contribution, and it may well win. [SoftGym](https://arxiv.org/abs/2011.07215) already uses hand-chosen reduced states for deformable objects — four cloth corners, ten evenly spaced rope keypoints — and *implicitly* assumes they capture what the task needs; that assumption, which the paper does not announce as one, is what study 2 measures. ["Feel the Tension"](https://arxiv.org/abs/2310.06424) already manipulates cables among fixtures on force alone, motivated by how little visual information people need for the same job; it proposes the route without measuring where it becomes necessary, which is why the force-only arm is here. The occlusion framing is ours, not theirs.

The Franka/FORGE peg-insertion study that preceded this cycle is preserved in full in [evidence/readme_peg_history_v1.json](evidence/readme_peg_history_v1.json) with its evidence files unchanged. Peg scores are historical peg evidence and are never cable results.
