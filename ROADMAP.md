# Roadmap

**Every measurement question this repository registered is closed.** Four
pre-registered studies are run and fitted. What remains is not a measurement: a
tool an engineer can open and a page that makes the result legible. Both are
specified in [docs/handover/v7_final_session.txt](docs/handover/v7_final_session.txt),
which is the last planned session.

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

## The single next action

Build the tool and the public page, to
[docs/handover/v7_final_session.txt](docs/handover/v7_final_session.txt), then
close the project. No further measurement is planned.

## History

Earlier closed cycles — the retired peg study, the first free-cable cycle and the
earlier adaptive-sampling design — stayed behind in the space-robotics repository
this work was cut from, with their evidence unchanged.
[evidence/INDEX.json](evidence/INDEX.json) lists every record here with its
declared scope.
