# Constrained-cable safety

**How much does a robot's safety check need to *see* before it moves a cable — and does the answer change with what "unsafe" means?**

A robot plugs a connector into a socket. The connector's cable is clipped into a bracket partway along its run, the way a real wiring loom is dressed. When the first attempt fails, the robot backs off to try again — but the cable is only so long. Back off too far and it lifts out of the clip, undoing work that was already finished. Bend it too tightly and the jacket is damaged. Pull too hard and the strain relief takes the load.

So before a recovery move, something should ask: *will this break anything?* This repository measures how much that check has to see.

Everything here is simulation, on a UR5e with pinned [Intrinsic AIC](https://github.com/intrinsic-ai/assembly-industrial-benchmark) connector assets through a purpose-built native MuJoCo adapter. Three pre-registered studies, each frozen and committed before a single run launched.

---

## The answer

**One number is enough.** A scalar — the straight-line distance from where the cable leaves the connector to where it is clamped, computed for the endpoint the move would reach — is not beaten by anything richer, at any level of measurement error, on any of three different failure modes.

**16,080 simulated repair attempts. 1.49 billion integration steps. 9 hours. Zero guard violations.**

| Safety check | Parameters | Clip-loss rate, perfect info → 2 mm error |
| --- | --- | --- |
| **one number + a margin** | **1** | **0.133 → 0.220** |
| force sensing only, no vision | 10 | 0.116 → 0.203 |
| 18 hand-designed features | 19 | 0.145 → 0.190 |
| network over the whole cable shape | ~30,000 | 0.208 → 0.288 |
| …plus a short history | ~30,000 | 0.226 → 0.309 |

The network that watches all 24 points of the cable is not merely tied — on the constraint that matters most it is **significantly worse**, by 0.074 with a bootstrap interval excluding zero, and the spread across three training seeds is too tight for that to be chance.

The first study established this when the robot was handed the simulator's *exact* truth. The obvious objection was that no real cell has that. So the second study took it away: every method now reads an estimate with a systematic bias that does not average out, error concentrated exactly where the fixture hides the cable, whole points dropping out, and a disturbance nothing could attribute. The answer did not change.

---

## Does the check survive being chained?

A predicate that judges one motion is not usable by a cell; nothing in harness work is one motion. So a third study issues **three** decisions in one sequence, on held-out layouts the check was never fitted on.

**720 sequences. 2,160 decisions. 72.9 million steps.**

| Over a three-step sequence | Clip lost, no error / 1 mm / 2 mm | Route completed |
| --- | --- | --- |
| no check, largest motion every time | **80 / 80 / 80 of 80** | 0 / 0 / 0 |
| check, take the largest safe motion | 32 / 33 / 36 of 80 | 48 / 25 / 0 |
| check, take the motion with most headroom | **8 / 10 / 37 of 80** | **72 / 41 / 3** |

**Without the check the cable comes out every single time** — 240 of 240 sequences, at every error level. That is what the safety layer is worth.

**But it does not chain for free.** The clip budget — the one quantity the check measures directly — is the one that degrades: its per-step failure rate *rises* 0.089 by the third decision once error reaches 2 mm, past the margin declared in advance. Curvature and anchor load, which the check only judges indirectly, both hold. That is the reverse of the prediction, and the more useful direction: every accepted step spends slack that the next step is then judged against.

---

## What was surprising

**Force sensing quietly won.** With no vision channel at all, it had the lowest false-safe rate on all three failure modes at every error level. It never beat the baseline by more than the margin declared in advance, so it cannot be certified as a win — but the direction is unambiguous and consistent, and it is the single most interesting thing left open here.

**Appetite mattered more than representation.** Same check, same estimate — but a supervisor that takes the motion with the most *headroom* instead of the largest *permitted* one loses 8 clips instead of 32 and completes 72 routes instead of 48. That comparison was not pre-registered and carries no verdict. It is reported as exploratory, because the honest reading is that the safety check tells you what is allowed, and how much of that you take is a separate decision nobody optimised here.

**Four of six predictions were wrong**, each written down before collection. The length budget would need nothing more (correct). The curvature limit would need the whole shape (wrong — nothing separated). Force would beat everything on the load limit by a certifiable margin (wrong — it won, but not by enough). The clip budget would compose over a chain (wrong — it is the one that does not). Curvature and load would not compose (wrong — they do). The check would be worth having in a sequence (correct, overwhelmingly).

**A bug in a test, not in the model.** A refined cable model had been failing for months and the cable was blamed. The test was scaling the cable's internal damping backwards when halving segment length — a discretised bending joint carries damping proportional to `1/L`, so halving the segment must *double* it. Corrected, the refinement is stable at three timestep settings and reproduces the coarse model's settled geometry to 5.7 micrometres.

**A label whose boundary is where the cable rests.** Clip retention is decided by whether the cable's crossing sits within `half-width − radius` of the channel centre — exactly the position at which the cable touches the clip wall. Left to settle, the cable slides along the channel and stops 2.9 micrometres past that line. The registered settling deadline samples it well before then, which is why every result here is stable — so that deadline is part of the task's definition, not an approximation, and is now written down as one.

---

## Why you can believe the numbers

- **Truth is scoring-only, and proved so.** A fail-closed guard fails any run whose control code reads a scoring channel, verified by a positive control that *fires*.
- **The labels survive independent re-derivation.** All 16,080 runs re-scored from the raw per-tick logs alone: 26,652 comparisons, zero disagreements, peak anchor load reconstructed to exactly 0.0 N.
- **The margin can resolve the difference.** An earlier block set a decision margin exactly equal to its own metric's resolution, making it undecidable. The runner now *refuses* a margin below twice the coarsest resolution — and refused three of fifteen cells here, which are reported as refused.
- **Aborted runs are censored, not successes.** A move cut short never got to test the constraints it hadn't already broken.
- **Frozen, committed, then launched.** Every contract's hash is recorded in the run manifests.

---

## What you can use

[`SafetyFilter`](src/assembly_recovery/cable_safety_filter_v4.py) loads its thresholds straight from the evidence record, so the published number and the running check cannot drift apart. It scores all three constraints and names which one binds, maps the whole continuous action space in one call so a planner sees the shape of what is allowed, and reports how much of each constraint's headroom a move spends. It runs off whatever a real estimator reports about its own error — a bias, a jitter, a worst-case error on a point it cannot see.

The transfer sweep says which cable property matters: a ±30% uncertainty in **friction** implies 12.5 mm of extra margin, against 4.3 mm for bending stiffness.

```powershell
.venv/Scripts/python.exe -m pytest                          # 216 tests, CPU-only
.venv/Scripts/python.exe scripts/summarize_perception_v4.py
.venv/Scripts/python.exe scripts/probe_cell_toolchain_v6.py # checks the CAD toolchain
```

`AGENTS.md` has the operating rules and the full command sequence. `evidence/INDEX.json` lists every record with its own declared scope.

---

## What is next

The measurement questions are closed. What is missing is a cell worth showing: a multi-clip harness jig authored in CAD, a cable routed through it under this check, and a tool an engineer can actually open. That work is planned in two parts and both are written down — [the routing cell](docs/handover/v6_routing_cell.txt) and [the workbench](docs/handover/v7_workbench.txt) — with the CAD toolchain already checked on real hardware and recorded in [evidence/cell_toolchain_v6.json](evidence/cell_toolchain_v6.json).

---

## Scope

Simulation only. No hardware, no released or latched connection, no electrical function, no learned grasping, no force-certified safety claim. The endpoint is *held, clip-preserving seating before gripper release*.

The error model is a model of **how perception fails** — derived from geometry and declared magnitudes. It is not camera perception, it renders nothing, and no estimator is built or evaluated here.

One task, one connector, one cable model, one observation interface. "One number is enough" is a measured statement about that, not about cable manipulation in general.
