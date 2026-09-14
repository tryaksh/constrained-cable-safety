# Constrained-cable safety

A robot recovering from a failed connector insertion can pull its cable out of
clips that already hold it in place. This repository studies how to choose a
recovery move while preserving that earlier assembly work.

The result is a lightweight decision inspector backed by four simulation studies.
It compares candidate moves, explains their predicted constraint budgets, and
selects the move with the most remaining headroom. On the tested five-clip rig,
this ranking completed jobs where choosing the largest allowed move completed
none. The fitted safety threshold itself did not transfer reliably from the
single-clip rig.

Cable measurements use MuJoCo with a UR5e and connector models from
[Intrinsic's Assembly Industrial Benchmark](https://github.com/intrinsic-ai/assembly-industrial-benchmark).
The results concern simulation and held seating before gripper release; they do
not establish hardware safety or a latched connection.

![The five-clip test rig](evidence/cable_cell_v6_clips_cad.png)

The fixture is generated in FreeCAD from the simulator's configuration. Visual
meshes and physical contact geometry are checked separately.
[CAD record](evidence/cable_cell_cad_v6.json)

## Try the decision inspector

From a checkout, use Python 3.11. The inspector needs only NumPy; MuJoCo and Torch
are unnecessary for these commands. Installation may download dependencies.
On Linux or macOS, use `.venv/bin/python` in place of `.venv/Scripts/python.exe`.

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install .
.venv/Scripts/python.exe scripts/inspect_recovery.py --demo
.venv/Scripts/python.exe scripts/inspect_recovery.py --demo --level E4 --json
```

The default example is an estimate recorded at the first repair decision, 2 s
into a registered five-clip job. Both policies below read that same E0 estimate
and the same fitted rules:

| Policy | Selected candidate | Endpoint displacement | C1 budget spent |
| --- | --- | --- | --- |
| Most remaining headroom (`conservative`) | 0 | 6.0 mm | 6.1% |
| Largest allowed move (`filtered`) | 9 | 100.6 mm | 81.9% |

Candidate 0 still performs the controller's mandatory 6 mm retract. At this
decision the rule allows 8 of 12 candidates. Budget percentages describe the
fitted distance rule, not the cable's physical slack or a probability of failure.
[Recorded estimates](artifacts/showcase/demo.json)

To inspect your own estimate, generate a complete request and edit it:

```powershell
.venv/Scripts/python.exe scripts/inspect_recovery.py --write-example decision.json
.venv/Scripts/python.exe scripts/inspect_recovery.py --input decision.json
.venv/Scripts/python.exe scripts/inspect_recovery.py --input decision.json --json
```

`--write-example` refuses to overwrite an existing file. `--input -` reads JSON
from stdin. The installed `cable-inspect` command offers the same interface;
run it from the checkout or pass `--repository <checkout>`.
After updating source files, reinstall with `python -m pip install .` in the
same environment. The installed API verifies its runtime code against the
checkout and reports an error if they differ.

Requests include positions, unit direction vectors, candidate actions, geometry
context and three explicit uncertainty values. Units are metres, radians and
seconds (`m_rad_s`). Missing uncertainty, nonfinite numbers, inconsistent
distances, malformed vectors and unknown fields are rejected. The cable-run
direction must not be parallel to the insertion axis. If no candidate
passes, or any constraint lacks a fitted rule, the inspector abstains.

JSON reports contain every candidate's constraint scores, all three policy
choices, the normalized request, source hashes and model scope. Exit status is
`0` for a ranked advisory result, `2` for invalid input or an I/O error, and `3`
for abstention or an unscored model. An allowed move is a fitted-rule pass, not a
physical safety guarantee. The inspector does not execute motion.

The Python API accepts the same request:

```python
import json
from pathlib import Path
from assembly_recovery.recovery_inspector import RecoveryInspector

request = json.loads(Path("decision.json").read_text(encoding="utf-8"))
report = RecoveryInspector.from_repository(Path.cwd()).inspect(request)
print(report["selected"], report["scope"])
```

The application uses the existing B0plus filter and registered policies without
refitting them. Its tests compare all candidate scores and policy choices against
the original filter at E0, E2 and E4, including refusal and abstention cases.
A fixed replay reproduced all 9 original outcomes and matched all 21 recorded
actions, verdicts and budgets within 1e-12. It retains the E4 conservative
failure and all six largest-move clip losses. This verifies software parity;
it is not a new controller-performance result.
[Verification record](artifacts/showcase/recovery_inspector.json) ·
[Portable replay](artifacts/showcase/recovery_replay.json)

## What the studies found

The filter predicts the endpoint distance from the connector's cable exit to the
anchor. Each constraint has a fitted threshold; declared estimator error reduces
that threshold through a margin. Headroom is the distance remaining below it.
All three reported budgets use metres of endpoint-distance headroom, including
the bend and anchor-load proxies.

The physical scoring checks clip retention (C1), a minimum bend radius of 40 mm
(C2), and an anchor load limit of 0.30 N (C3). The cable is 4 mm across. Success
requires 0.5 s of continuous held seating with every required clip retained,
within the deadline and force limits.
[Frozen constraints](configs/cable_perception_v4.json)

E0 supplies an exact simulator estimate. E2 models small error: 0.5 mm socket
bias, 1 mm hidden-node error and 5% dropout. E4 uses 2 mm, 4 mm and 20% respectively.
These are declared error models, not tested camera perception.

**v3 — An unresolved boundary.** The first study could not distinguish its
registered alternatives at its own metric resolution. It remains inconclusive;
the data was not rescored under a more favorable rule.
[Record](evidence/cable_repair_boundary_v3.json)

**v4 — More complex sensing did not clear the registered improvement margin.**
The table shows clip loss among approved moves on held-out layouts, with each
model evaluated at matched approval coverage. The shape network reads all 24
estimated points of the cable:

| Model | Parameters | E0 false approval | E4 false approval |
| --- | --- | --- | --- |
| One distance plus uncertainty margin | 1 | 13% | 22% |
| Force only | 10 | 12% | 20% |
| Hand-designed features | 19 | 14% | 19% |
| Whole cable shape | 28,033 | 21% | 29% |
| Cable shape plus history | 34,689 | 23% | 31% |

The study ran 16,080 requests; 15,476 reached a decision that could be scored.
The E0 table column uses 960 held-out decisions and E4 uses 865, before matching
approval coverage. No richer model cleared the registered margin on any
constraint or error level. A post-hoc E0 comparison found the shape network
worse by about 7 percentage points (95% interval: 1 to 15); this carries no
registered verdict. [Record](evidence/cable_perception_v4.json)

**v5 — Action selection matters over a sequence.** Across 720 runs and 2,160
decisions, the unfiltered policy lost the clip in all 240 runs assigned to it. The table
reports clip losses over observed outcomes; censored outcomes are not counted
as safe:

| Policy | E0 | E2 | E4 |
| --- | --- | --- | --- |
| No filter, largest move | 80 of 80 | 80 of 80 | 80 of 80 |
| Filter, largest allowed move | 32 of 80 | 33 of 58 | 36 of 66 |
| Filter, most remaining headroom | 8 of 80 | 10 of 63 | 37 of 79 |

These are clip-retention outcomes on held-out single-clip layouts, not completed
five-clip jobs. [Record](evidence/cable_sequence_v5.json)

**v6 — The threshold failed to transfer; conservative selection helped on the
tested rig.** The unchanged single-clip filter was evaluated on a five-clip
route. Before the block, the rig tolerated about 18 mm of retreat while the
filter reported 58 mm of endpoint-distance headroom. Those quantities describe
the geometry mismatch; 58 mm is not an allowed retreat distance.
[Pre-block record](artifacts/cell/block.json)

Each policy had 780 jobs: 60 at E0, 360 at E2 and 360 at E4.

| Policy | Clip-loss share, E0 / E2 / E4 | Held seating completed, E0 / E2 / E4 |
| --- | --- | --- |
| No filter, largest move | 0.667 / 0.636 / 0.489 | 0 of 60 / 0 of 360 / 0 of 360 |
| Filter, largest allowed move | 0.667 / 0.611 / 0.497 | 0 of 60 / 0 of 360 / 0 of 360 |
| Filter, most remaining headroom | 0.333 / 0.314 / 0.353 | 20 of 60 / 76 of 360 / 9 of 360 |

The filter's reductions in clip-loss share were +0.000, +0.025 and −0.008,
all below the registered 0.05 margin. The two largest-move policies completed
0 of 1,560 jobs combined. Selecting the most remaining headroom improved
completion at E0 and E2, with much less benefit at E4. This is evidence for one
rig and its registered action set, not general transfer.

The raised clip c3 accounted for 1,017 of 1,144 clip losses; c1 accounted for 127.
The block ran 2,340 jobs, 11,700 decisions and 266.8 million simulation steps in
87 minutes on 20 CPU workers. [Record](evidence/cable_routing_v6.json)

## Verification and limits

Study configs, seeds and decision rules were committed before collection.
At each decision the inspector compares policies using the same estimate.
Study arms use the same estimate interface; their later trajectories can
diverge. Ground truth is reserved for scoring.
Privilege and simulator-mutation guards recorded zero events in v4–v6, and a
deliberate cheating control confirmed that the privilege guard fires.
[Controls](evidence/cable_perception_controls_v4.json)

Independent replay of 16,080 v4 requests made 26,652 comparisons with zero
disagreements. The resolution check refused 3 of 15 v4 comparisons whose margin
was too small. Failed runs, rejected designs, censored outcomes and unsuccessful
predictions remain in the records.
[Replay](evidence/cable_perception_replay_v4.json) ·
[Resolution checks](evidence/cable_perception_v4.json)

Two simulation limits affect interpretation: bend-radius findings apply only to
the 23-segment cable at 4 kHz, and the cable is still moving at the task's 5 s
settling deadline. Neither the deadline nor the retention predicate was changed.
There is no hardware transfer, grasp-reliability, released-connection or
force-certified safety claim. The connector model has no demonstrated latch.
[Instrument checks](evidence/cable_discretisation_v4.json) ·
[Retention test](evidence/cable_retention_v1.json)

```powershell
.venv/Scripts/python.exe scripts/verify_findings.py
.venv/Scripts/python.exe scripts/verify_recovery_replay.py
.venv/Scripts/python.exe scripts/try_the_safety_check.py
.venv/Scripts/python.exe -m pip install ".[dev]"
.venv/Scripts/python.exe -m pytest  # 611 tests, CPU only
.venv/Scripts/python.exe -m ruff check src scripts tests
```

The verifiers re-derive all four study verdicts and check all 21 portable replay
decisions without a simulator. `try_the_safety_check.py` checks the filter's
arithmetic against a recorded job. The development install
adds Torch for the full test suite; it is separate from using the inspector.

## Repository guide

The [workbench](scripts/workbench.py) edits fixture configurations and checks that
a cable can be installed before running a job. Its screen rejected 19 of 28
candidate configurations. Physics and rendering require separate environments;
the full commands and Windows constraints are in [AGENTS.md](AGENTS.md).
The workbench's interactive window has never been tested because this machine
has no display. Its headless self-check reproduces the registered job.
[Workbench verification](artifacts/showcase/tool.json)

| Need | Location |
| --- | --- |
| Closed studies, artifact verification and remaining limitations | [ROADMAP.md](ROADMAP.md) |
| Inspector API and underlying filter | [recovery_inspector.py](src/assembly_recovery/recovery_inspector.py), [cable_safety_filter_v4.py](src/assembly_recovery/cable_safety_filter_v4.py) |
| Fixture configuration | [cable_cell_v6_candidates.json](configs/cable_cell_v6_candidates.json) |
| Evidence by campaign and scope | [evidence/INDEX.json](evidence/INDEX.json) |
| Branches and repository history | [docs/REPO_MAP.md](docs/REPO_MAP.md) |
| Retired peg-insertion campaign | [docs/PEG_INSERTION.md](docs/PEG_INSERTION.md) |

The evidence index distinguishes cable and peg campaigns. Read a record's scope
before quoting its numbers. Historical handovers are retained unchanged.
