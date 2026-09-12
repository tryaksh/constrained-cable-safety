# Roadmap

**This is a record, not a plan.** Every measurement question this repository
registered is closed, and so is the work that made the results usable. Four
pre-registered studies are run and fitted; a public page, three replay clips, a
local workbench and a USD export are built and verified. No further work is
planned. What is below is what was found, what was built, and what stays open —
written down so that someone picking this up later, including a later version of
me, does not have to guess which of those three a line belongs to.

**Scope.** Industrial cable handling and connector insertion, in simulation.
**Endpoint:** held, clip-preserving seating before gripper release — the robot
still holds the plug, real tip/base engagement and a continuous 0.5 s dwell are
reached before the deadline, every required clip stays captured, and no load
limit or state-mutation rule is broken. In the routing study "every required
clip" means all five of a route, not one. Not a released or latched connection,
electrical function, learned pickup, grasp-robustness result or hardware transfer.

---

## The four studies

| | Question | Verdict | Record |
| --- | --- | --- | --- |
| **v3** | Where is the safe-repair boundary? | `inconclusive_neither_branch_triggered`. The margin equalled the metric's own resolution, so the question was undecidable by construction. Kept, with the pre-registration defect, rather than re-run. | [record](evidence/cable_repair_boundary_v3.json) |
| **v4** | How much must a safety check *see*, as perception degrades, across three constraint shapes? | **No crossover anywhere.** Nothing beats a one-parameter scalar by more than the registered margin at any error level on any constraint. The ~30k-parameter network is significantly *worse* on clip retention (gap 0.074, interval excluding zero). 1 of 3 predictions correct. | [record](evidence/cable_perception_v4.json) |
| **v5** | Does that check survive being chained? | **Yes, decisively — but it does not compose.** Unfiltered lost the clip in 80 of 80 sequences at every error level. The clip budget's per-step rate *rises* 0.089 by the third decision at E4, past the margin; curvature and load hold. 1 of 3 correct, wrong in the informative direction. | [record](evidence/cable_sequence_v5.json) |
| **v6** | Does it still earn its place over a five-clip route in a cell it was never fitted on? | **No.** Filtered and unfiltered are the same supervisor there (gaps 0.000 / +0.025 / −0.008, all inside the margin), both issuing one motion and losing a clip on it. Per-step risk *falls* rather than compounding. What holds is appetite, registered here and certified. 1 of 3 correct. | [record](evidence/cable_routing_v6.json) |

**What this adds up to.** A scalar check carrying a margin sized from the
estimator's declared error is sufficient for a single move and worth having over a
short chain — and its *threshold* is a fitted property of the jig it was fitted
on, not of the cable. Move to a jig with five clips and the threshold permits
58 mm where the route tolerates 18 mm, and the check stops buying anything. Its
*ranking* still transfers: reading the same check for which move has the most
headroom completes routes where taking the largest permitted one completes none.

---

## Verified state: the instrument

| Item | State |
| --- | --- |
| Does the cable model refine? | Yes, on the quantity the threshold is built on. A fourfold refinement settles at 4, 8 and 16 kHz and reproduces the registered settled boot-to-anchor distance to **5.7 µm**. Minimum bend radius does **not** agree across refinements, so C2 stays scoped to the 23-segment model at 4 kHz. [record](evidence/cable_discretisation_v4.json) |
| Is the initial state at rest? | **No, and that is part of the task.** The routed cable slides along the clip channel for another eight seconds and comes to rest **2.9 µm past** the retention predicate's own lateral test. The 5 s settling deadline is a task definition, not an approximation. Neither it nor the predicate was changed. |
| Privilege guard | Fail-closed, with a positive control that **fires**. Zero events across v4, v5 and v6. [controls](evidence/cable_perception_controls_v4.json) |
| Mutation guard | Armed on every request. Zero events across v4, v5 and v6. |
| Ledger replay | Every v4 clip and anchor label re-derived from the stored servo ledgers alone: **13,408 and 13,244 comparisons, 0 disagreements**. [record](evidence/cable_perception_replay_v4.json) |
| Margin resolution | Checked in code before any freeze, and in v6 level by level so a well-sized cell cannot hide an unresolvable one. v4 refused 3 of 15 comparisons and reports them as refused. |
| Throughput | 24 physical cores, CPU-only. **44,966 aggregate native steps/s on 20 workers** against 28,086 on 12. MJX does not support this scene's cable plugin, composite bodies or elliptic friction cone, so the GPU is for rendering only. |
| Transfer | Nominal threshold **399.7 mm**. A ±30% uncertainty in sliding friction implies **12.5 mm** of extra margin, against 4.3 mm for bending stiffness. [record](evidence/cable_transfer_protocol_v4.json) |

## Verified state: the routing cell

| Item | State |
| --- | --- |
| The cell | Five clips at three heights and four bearings, a ridge, a corner, a strain-relief clamp, a socket surround. Authored in FreeCAD **from config**: 8 parts, all watertight, all one solid after the fuse, 3,704 facets. [record](evidence/cable_cell_cad_v6.json), assets in `assets/cell_v6/`. |
| The CAD cannot move a number | Meshes are visual only (`contype=0 conaffinity=0 group=2 mass=0`); the cable collides with the primitives every published number was measured against. Settling with and without them agrees to **0.0 m** at three service loops. |
| The refactor did not change the task | `build_fixture` carries N clips; the registered `clip` key reads as a one-element list. Two registered v4 contexts recompile to **byte-identical scene XML** with settled centreline agreement of **0.0 m**. [check](artifacts/cell/scene.json) |
| The screen | 28 cells declared before it ran, **9 accepted, 19 rejected** with reasons. RC1 wins the selection rule written down first — surviving at 6 of 7 service loops against 2, 1 and 0. [record](evidence/cable_cell_screen_v6.json) |
| The block | **2,340 routes, 11,700 decisions, 266.8M integration steps, 87 minutes**, zero guard events, zero settling rejections. Frozen and committed before launch. [contract](configs/cable_routing_v6.json) |
| Which clip lets go | The raised one at the top of the ridge: **1,017 of 1,144 losses**, against 127 for the clip nearest the plug and none for the other three. |

---

## What was built on top of the measurements

The last session turned the finished result into things a person can use. Each
has a record on disk, and each record says what was checked rather than what was
intended.

| Item | State |
| --- | --- |
| **The public page** | <https://claude.ai/code/artifact/71352222-82b3-4676-901c-c2c4852eea3c>. Generated by `scripts/build_showcase.py` from ten committed records — not hand-written, so it cannot drift from them. Published as a private Artifact; nothing was pushed to any git remote. [Record](artifacts/showcase/page.json) |
| **Three replay clips** | Registered routes re-run through the study's own worker loop, via a per-tick observer, so the replay cannot land on a different random stream. Every capture is compared against the committed `result.json` and refused if it differs. Verified by decoding the written files: **329, 352 and 329 frames, 0 blank of 27 sampled**. [Record](artifacts/showcase/video.json) |
| **The workbench** | `scripts/workbench.py` over `WorkbenchSession`. Loads the measured cell, moves a clip, re-runs the screen, reports what the safety layer permits, routes through it. **13 headless tests**, and a self-check that reproduces the committed screen numbers and the committed route including its whole headroom series. The interactive window was **never executed** — no display on this machine. [Record](artifacts/showcase/tool.json) |
| **USD export** | One route written to a 5.4 MB USD stage from the recorded rollout, in a separate virtual environment so the cable environment's package set cannot drift. A rendering export only. [Record](artifacts/showcase/usd.json) |

Two things that were nearly wrong and were caught by checking rather than by
reasoning, both worth knowing if any of this is extended:

- The workbench first narrowed the screen record to one cell group before
  expanding the contract. That restarts the launcher's seed counter, so every
  group but the first would have been handed **different seeds** — the tool would
  have shown a different request under a registered name. An unmodified session
  now hands over the committed screen whole.
- The USD export first **stepped** the compiled scene instead of replaying it.
  With no controller the arm collapses under gravity in 4.3 ms, and the export
  wrote 200 frames of that and exited zero.

---

## Open, and honestly so

- **Force-only sensing.** Lowest false-safe rate on all three constraints at
  every error level, never by more than the declared 0.05 margin, so nothing
  could be certified. Closing it needs a margin near 0.01 and therefore at least
  200 held-out contexts per cell. The most interesting measurement this project
  did not buy.
- **A budget-capped supervisor.** The obvious fix for the v6 result, using only
  what the shipped layer already reports. Not registered in v6 because the
  registered action set produces spent fractions of 0.061 and 0.819 with nothing
  between them, so any cap that separates the arms would have to be tuned. It
  needs its own action set and its own sizing.
- **v6's support is thin.** One cell at six service loops crossed with two mounts
  and five mounting offsets — 60 physical contexts, against v5's ten held-out
  layouts. A v6 finding is a statement about that cell.
- **v3 stays inconclusive.** Re-running it under a changed rule would not fix the
  pre-registration defect; it would hide it.
- **The workbench's window was never opened.** Everything behind it is headless
  and unit tested, and one call to `launch_passive` is not. Someone with a
  display should run `scripts/workbench.py --run --view` once before relying on
  it.

## History

Earlier closed cycles — the retired peg study, the first free-cable cycle and the
earlier adaptive-sampling design — stayed behind in the space-robotics repository
this work was cut from, with their evidence unchanged.
[evidence/INDEX.json](evidence/INDEX.json) lists every record here with its
declared scope.
