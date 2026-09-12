# Constrained-cable safety

A robot pushes a connector into a socket. The connector's cable is clipped into
brackets along the way, the way a wiring loom is dressed inside a machine. When
the insertion fails and the robot backs off to try again, it can pull the cable
out of a clip — undoing work that was already done.

Something should check each move before it happens. This repository measures what
that check needs to know, and what it is worth.

Everything is simulation: MuJoCo, a UR5e arm, connector models from the
[Intrinsic Assembly Industrial Benchmark](https://github.com/intrinsic-ai/assembly-industrial-benchmark).
Four studies, each with its question, its method and its success criteria written
down and committed to git before any of it ran.

![The five-clip routing cell](evidence/cable_cell_v6_clips_cad.png)

---

## The setup

The robot holds a plug. A cable leaves the back of the plug, runs down to a
board, passes through one or more clips, and is clamped at the far end. Three
things can go wrong when the robot retreats to retry:

- **the cable comes out of a clip** — there is only so much slack
- **the cable is bent too tightly** — below a declared minimum bend radius
- **the clamp takes too much load** — a declared force limit

A "safety check" here is a function that looks at the robot's estimate of the
world, looks at a candidate move, and says whether that move would break any of
the three. The studies ask what that function has to see, and whether it keeps
working when you use it repeatedly.

---

## What the four studies found

### 1. One number is enough — for a single move

Five candidate checks were compared, from a single scalar to a ~30,000-parameter
neural network reading the cable's full 24-point shape. The scalar wins: the
straight-line distance from where the cable leaves the plug to where it is
clamped, computed for the position the move would end at, plus a safety margin
sized from what the estimator reports about its own error.

| Check | Parameters | Clip-loss rate, perfect info → 2 mm error |
| --- | --- | --- |
| **one distance + a margin** | **1** | **0.133 → 0.220** |
| force sensing only, no vision | 10 | 0.116 → 0.203 |
| 18 hand-designed features | 19 | 0.145 → 0.190 |
| network over the whole cable shape | ~30,000 | 0.208 → 0.288 |
| …plus a short history | ~30,000 | 0.226 → 0.309 |

Nothing beat the scalar by more than the margin declared in advance. The network
was *worse* on clip retention — by 0.074, with a bootstrap interval excluding
zero and a spread across training seeds too tight to be chance.

16,080 runs, 1.49 billion simulation steps, 9 hours.
[Record](evidence/cable_perception_v4.json) ·
[contract](configs/cable_perception_v4.json)

This held whether the check was handed the simulator's exact truth or a degraded
estimate — a systematic bias that does not average out, extra error exactly where
the fixture hides the cable, points dropping out entirely, and an unattributable
disturbance force.

### 2. Chaining moves is where the check earns its keep

A check that judges one move is not much use; real work is a sequence. Three
decisions per run, on cable layouts the check had never been fitted on:

| Over a three-step sequence | Clip lost (no error / 1 mm / 2 mm) | Route completed |
| --- | --- | --- |
| no check, largest move every time | **80 / 80 / 80 of 80** | 0 / 0 / 0 |
| check, take the largest allowed move | 32 / 33 / 36 of 80 | 48 / 25 / 0 |
| check, take the move with most headroom | **8 / 10 / 37 of 80** | **72 / 41 / 3** |

Without the check the cable came out **every single time** — 240 of 240 runs.
That is what the safety layer was worth on this layout.

But it did not chain for free. The clip budget — the one quantity the check
measures directly — is the one that degraded, its per-step failure rate rising
0.089 by the third decision at 2 mm error. Each accepted step spends slack that
the next step is then judged against.

720 sequences, 2,160 decisions.
[Record](evidence/cable_sequence_v5.json) ·
[contract](configs/cable_sequence_v5.json)

### 3. On a different cell, the check stops working

The first three studies used one clip. Real harness work is a route. So: a
CAD-authored jig with five clips at three heights and four bearings, a ridge the
cable climbs over, a corner it turns, and a clamp at the end — the picture at the
top of this page. Success now means **all five clips still held and the connector
seated**, across five decisions instead of three.

Two numbers, measured before anything was scored, explain the result:

| | |
| --- | --- |
| what the five-clip route physically tolerates | about **18 mm** of pull-back |
| what the shipped check permits on that route | **58 mm**, and 11 of its 12 candidate moves |

The check's threshold is a fitted property of *the jig it was fitted on* — how
much cable lies between the plug and the clamp, and how much of that can
straighten out. It is not a property of the cable. Five clips pin the cable, so
almost none of it can straighten, and the check does not know that.

The result, over 2,340 routes and 11,700 decisions:

| Over a five-clip route | Lost a clip | Route completed |
| --- | --- | --- |
| no check, largest move every time | 0.667 / 0.636 / 0.489 | **0 of 780** |
| check, take the largest allowed move | 0.667 / 0.611 / 0.497 | **0 of 780** |
| check, take the move with most headroom | 0.333 / 0.314 / 0.353 | 20 / 76 / 9 |

**The check bought nothing.** With it and without it are the same supervisor
here: both issue one move, both lose a clip on it, and the gaps between them
(0.000, +0.025, −0.008) are all inside the declared 0.05 margin. What did work is
*taking less* — the same check, read for which move has the most room to spare
rather than which is the largest one allowed.

One further thing worth knowing: the clip that lets go is almost always the one
at the top of the ridge — 1,017 of 1,144 losses, against 127 for the clip nearest
the plug and none at all for the other three.

266.8 million simulation steps, 87 minutes, zero guard violations.
[Record](evidence/cable_routing_v6.json) ·
[contract](configs/cable_routing_v6.json)

### 4. What was predicted, and what actually happened

Nine predictions were written down before collection. **Three were right:** that
the length budget would need nothing richer than a scalar, that the check would be
worth having over a sequence, and the one below.

The six that were wrong, and what they taught: the curvature limit was predicted to need the whole cable
shape (nothing separated); force sensing was predicted to win the load limit by a
certifiable margin (it won everywhere, but never by enough to certify); the clip
budget was predicted to chain cleanly (it is the one that degrades); curvature and
load were predicted not to chain (they do); the check was predicted to still be
worth having over a five-clip route (it is not); and the per-step risk was
predicted to keep compounding (it does the opposite — on the route, risk is
concentrated in the *first* move, and a route that survives that is mostly safe).

The one prediction that landed squarely: **how greedily the supervisor spends what
the check permits matters more than what the check is.** That started as an
unplanned observation in study 2, was registered as a formal prediction in study
3, and held — completing 33% and 21% of routes where the greedy version completed
none, and collapsing inside the margin at the highest error level, exactly as
predicted.

---

## Why the numbers are trustworthy

- **The answer key is never readable by the code being tested.** A guard fails
  any run whose control code touches a scoring-only channel, and a deliberate
  positive control confirms the guard actually fires.
- **Labels were re-derived independently.** All 16,080 runs of study 1 re-scored
  from the raw per-tick logs alone: 26,652 comparisons, zero disagreements.
- **The margin can resolve the difference it claims to measure.** An earlier
  study set a decision margin equal to its own measurement resolution, making the
  question unanswerable. The launcher now refuses to start a study whose margin is
  smaller than twice its resolution — and refused three of fifteen comparisons.
- **Runs cut short are excluded, not counted as successes.** A move that aborted
  never got the chance to break the constraints it had not already broken.
- **Frozen, committed, then launched**, with every contract's hash recorded in
  the run manifest.
- **Rejections are kept.** The screen that chose the five-clip jig rejected 19 of
  the 28 candidates it was given, and all 19 are in the record with reasons.

---

## What you can actually use

[`SafetyFilter`](src/assembly_recovery/cable_safety_filter_v4.py) is the check
itself, packaged. It reads its thresholds straight out of the evidence file, so
the published number and the running code cannot drift apart. It scores all three
constraints, names which one binds, maps the whole space of allowed moves in one
call, and reports how much of each constraint's headroom a move spends. It runs
off whatever a real pose estimator reports about its own error.

Study 3 says how to read it: **use its ranking, not its threshold.** The
threshold does not transfer to a jig it was not fitted on. Ranking candidate moves
by remaining headroom and taking a conservative one does.

The jig itself is defined in config, not code — move a clip in
[`configs/cable_cell_v6_candidates.json`](configs/cable_cell_v6_candidates.json)
and the CAD, the screen and the study all follow.

```powershell
.venv/Scripts/python.exe -m pytest                          # 250 tests, no GPU, no simulator
.venv/Scripts/python.exe scripts/summarize_perception_v4.py # study 1, in a paragraph
.deps/cable-venv/Scripts/pythonw.exe scripts/render_cell_v6.py
```

`AGENTS.md` has the operating rules and the full command sequence.
`evidence/INDEX.json` lists every record with its own declared scope.

---

## Limits of these claims

Simulation only. No hardware, no released or latched connection, no electrical
function, no learned grasping, no force-certified safety claim. The endpoint is
*held, clip-preserving seating before the gripper opens*.

The degraded-perception model is a model of **how perception fails** — built from
geometry and declared error magnitudes. It renders nothing, and no camera or
estimator is built or evaluated here.

One task, one connector, one cable model, two jigs. "One number is enough" is a
measured statement about a single move on the first jig — and study 3 is the
measurement of where that stops being true.

---

## What is left

The measurements are done. What is missing is a tool an engineer can open, move a
clip in, and re-run, plus a page that makes the result legible to someone who will
not read this far. Both are specified in
[docs/handover/v7_final_session.txt](docs/handover/v7_final_session.txt).
