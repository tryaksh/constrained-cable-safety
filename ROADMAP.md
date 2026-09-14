# Roadmap

**This is a record, not a plan.** Every question the cable studies set out to
answer has been answered, and the work that turned those answers into something
usable is finished too. Nothing is queued.

Four separate things follow, kept separate on purpose: what was found, what the
instrument is known to do, what was built on top, and what is still open.

[README.md](README.md) is where the project itself is explained. The short
version for reading the tables below: a robot plugs a connector into a socket,
the cable behind the plug is clipped to a board along the way, and backing off
to retry can pull it out of a clip. A job succeeds only if the plug holds a
continuous 0.5 s seating before the deadline with every required clip still
holding, no force limit exceeded, and nothing editing the simulator's state
mid-job.

Nothing below is a peg number. The retired peg-insertion campaign is closed and
is not summarised here beyond its entry under *History*;
[docs/PEG_INSERTION.md](docs/PEG_INSERTION.md) is its record.

---

## What was found

Each study wrote its question and its pass/fail rule into a config file that was
committed to git before the runs started.

| | The question | The answer | Record |
| --- | --- | --- | --- |
| **v3** | Where exactly is the boundary between a safe repair move and an unsafe one? | **Undecidable as asked.** The study required differences smaller than its own measuring resolution, so neither branch could ever trigger. Kept as-is, with the design flaw visible, rather than quietly re-run. | [record](evidence/cable_repair_boundary_v3.json) |
| **v4** | How much does a safety check need to *see*, as the robot's eyesight gets worse? | **A single number is enough.** Nothing richer — up to a 28,000-parameter network reading the whole cable shape — beat a one-number check by enough to count, at any eyesight level, on any of the three failure modes. The network was in fact *worse* at protecting the clips. 1 of 3 predictions right. | [record](evidence/cable_perception_v4.json) |
| **v5** | Does that check still work when you use it several times in a row? | **Yes, decisively.** Without it the cable came out of its clip in all 240 runs. But it does not chain for free: the clip budget is the quantity that decays, its per-step failure rate rising 0.089 by the third move at the worst eyesight. 1 of 3 right, wrong in a useful direction. | [record](evidence/cable_sequence_v5.json) |
| **v6** | Does it still earn its keep on a five-clip rig it was never tuned for? | **No.** With the check and without it the robot behaves identically: one big move, cable out. The gaps (+0.000, +0.025, −0.008) are all inside the margin fixed in advance. Risk turns out to sit in the *first* move rather than building up. What does survive is how greedily the robot spends what the check allows. 1 of 3 right. | [record](evidence/cable_routing_v6.json) |

**What it adds up to.** A one-number check carrying a margin sized from the
estimator's own reported error is enough for a single move, and clearly worth
having over a short sequence. Its *threshold*, though, is a property of the rig
it was fitted on, not of the cable. Move to a rig with five clips and the
threshold allows 58 mm of pull-back where the rig only tolerates 18 mm, and the
check stops buying anything. Its *ranking* of candidate moves still transfers:
taking the move with the most room left finishes jobs where taking the biggest
allowed move finishes none.

---

## What the instrument is known to do

These are properties of the simulation itself, established separately from any
result, because a result is only as good as the thing that produced it.

| Question | Answer |
| --- | --- |
| Can the arm do the task at all, and does the timestep decide? | Yes, and yes. At a 1 ms step the job aborts on contact 28 steps in; at 0.5 ms and 0.25 ms the plug seats, dwells and retracts. 0.25 ms is what everything since has used. [figure](evidence/cable_robot_validation_v1.png) · [record](evidence/cable_robot_validation_v1.json) |
| Is the plug really touching the socket, or passing through it? | Touching, and misalignment blocks it as it should: a 3 mm offset drives plug-to-socket contact to 20.4 N and stops the plug 13.8 mm short, while an aligned approach seats at 1.6 N. [figure](evidence/cable_contact_validation_v1.png) · [record](evidence/cable_contact_validation_v1.json) |
| Does the insertion controller need its force guidance? | Yes. Force-guided alignment seated **6 of 6** cases; simply continuing to push seated the three nominal cases and timed out on all three 2 mm offsets. Its effect is prevention, not recovery: it never stalled, so it never retried. [figure](evidence/cable_baseline_v2.png) · [the same pair, rendered](evidence/cable_video_v1.jpg) · [record](evidence/cable_baseline_v2.json) |
| Does the cable model converge as you refine it? | Yes, for the quantity the threshold is built on. A four-fold refinement reproduces the settled plug-to-clamp distance to **5.7 µm**. Minimum bend radius does *not* agree across refinements, so any claim about bending stays scoped to the 23-segment model at 4 kHz. [record](evidence/cable_discretisation_v4.json) |
| Is the cable actually at rest when a job starts? | **No, and that is part of the task definition.** It keeps creeping along the clip channel for another eight seconds and settles **2.9 µm past** the retention test's own threshold. The 5 s settling deadline is a definition, not an approximation, and was not changed to make anything look better. |
| Can the code being tested read the answer key? | No. A guard fails any run whose control code touches ground truth. A deliberately cheating run is included to prove the guard fires; it does, and it never fired on a real run across v4, v5 and v6. [controls](evidence/cable_perception_controls_v4.json) |
| Can a job secretly edit the simulator mid-run? | No. Checked around every control step. Zero events across v4, v5 and v6. |
| Were the labels graded twice? | Yes. All 16,080 runs of v4 were re-scored from the raw per-tick logs alone by separate code: **26,652 comparisons, 0 disagreements**. [record](evidence/cable_perception_replay_v4.json) |
| Can a study ask a question it is too coarse to answer? | No. The difference a result must beat has to be at least twice the measurement's own resolution, checked in code before anything is frozen. v4 refused 3 of 15 comparisons outright and reports them as refused. |
| How fast does it run? | 24 physical cores, CPU only: **44,966 simulation steps per second on 20 workers**, against 28,086 on 12. MuJoCo's GPU path does not support this scene's cable plugin, composite bodies or friction model, so moving collection to the GPU would mean a different cable and would invalidate every comparison. The GPU is for rendering. |
| How much would real-world friction uncertainty move the threshold? | The nominal threshold is **399.7 mm**. A ±30% uncertainty in sliding friction implies **12.5 mm** of extra margin; bending stiffness implies 4.3 mm. [record](evidence/cable_transfer_protocol_v4.json) |

## What the five-clip rig is known to be

| Item | State |
| --- | --- |
| The rig | Five clips at three heights and four angles, a ridge the cable climbs, a corner it turns, a clamp at the end, and a socket surround. Drawn in FreeCAD **from the config file**, not by hand: 8 parts, all watertight, all one solid after the fuse, 3,704 facets. [record](evidence/cable_cell_cad_v6.json), meshes in `assets/cell_v6/`. |
| The drawn geometry cannot move a number | The CAD meshes are visual only — the cable physically touches the same primitive shapes every earlier result was measured against. Settling with and without the meshes agrees to **0.0 m** at three different slack settings. |
| Supporting five clips did not change the old task | The scene builder now takes a list of clips; the old single-clip config reads as a one-element list. Two registered single-clip contexts recompile to **byte-identical scene XML**. [check](artifacts/cell/scene.json) |
| How the rig was chosen | 28 candidate rigs were drawn before the check ran. **9 accepted, 19 rejected** with reasons — mostly because a cable cannot actually be installed in them. The winner survived at 6 of 7 slack settings against 2, 1 and 0 for the others. [record](evidence/cable_cell_screen_v6.json) |
| The block itself | **2,340 jobs, 11,700 decisions, 266.8M simulation steps, 87 minutes**, no guard events, no settling failures. Frozen and committed before launch. [contract](configs/cable_routing_v6.json) |
| Which clip lets go | Almost always the raised one at the top of the ridge: **1,017 of 1,144 losses**, against 127 for the clip nearest the plug and none at all for the other three. |

---

## What was built on top of the measurements

Five things turn the results into something a person can use. Each has a record
on disk, and each record says what was actually checked rather than what was
intended.

| Item | State |
| --- | --- |
| **The page** | Generated by `scripts/build_showcase.py` from ten committed records, so it cannot drift from them — change a number in a record, rebuild, and the page changes. It is a local file: `artifacts/showcase/index.html` is generated output and is not in the repository, not published, and not served anywhere. The record of what was built is. [record](artifacts/showcase/page.json) |
| **Three replay clips** | Real jobs re-run through the study's own control loop, via a per-tick callback, so the replay cannot land on a different random stream than the original. Each capture is compared against the committed result and refused if it differs. Checked by decoding the written files: **329, 352 and 329 frames, 0 blank of 27 sampled**. [record](artifacts/showcase/video.json) |
| **The workbench** | `scripts/workbench.py`. Loads the measured rig, moves, adds or removes a clip, re-runs the install check, reports what the safety layer allows, and runs the job. **17 headless tests**, plus a self-check that reproduces the committed install-check numbers and the committed job result including its whole slack series. The interactive window has **never been run** — no display on this machine. [record](artifacts/showcase/tool.json) |
| **USD export** | One job written out as a USD stage — Universal Scene Description, the scene format other renderers read — from the recorded motion rather than by re-stepping it: **200 frames**, read back as 286 prims of which 72 move over time. Built in its own virtual environment so the simulation environment's package list cannot drift. A rendering export and nothing more. [record](artifacts/showcase/usd.json) |
| **Isaac Sim re-render** | The same stage rendered again with ray-traced lighting: 198 frames at 1920×1080. MuJoCo's built-in renderer exists to check a scene is built right, not to look at. The physics, and every number anywhere in this repository, are unchanged. [record](artifacts/showcase/isaac.json) |

Four things were nearly wrong and were caught by checking rather than by
reasoning. They are worth knowing if any of this gets extended:

- The workbench first narrowed the rig record to a single group before turning
  the study contract into a job. That restarts the seed counter, so every group
  but the first would have been handed **different random seeds** — the tool
  would have shown a different job under a registered name. It now expands the
  whole record and picks the request out afterwards.
- The USD export first **stepped** the scene instead of replaying it. With no
  controller the arm collapses under gravity in 4.3 ms, and the export wrote 200
  frames of exactly that and still exited zero.
- The Isaac render looked right and dropped the scene out of frame after about
  40% of every run, because the stage time was being set by hand with the
  timeline held still. Letting the renderer advance the timeline itself fixed it.
- The working tree arrived broken: an earlier commit deleted a helper module that
  two live scripts still imported, so every simulator entry point failed at
  import. None of the unit tests noticed, because none of them import those
  scripts.

---

## Open, and honestly so

Nothing here was bought. Each one carries what it would cost, in the units the
executed blocks actually measured: a v6 route cost 44 summed worker-seconds, and
the whole three-arm block was 2,340 routes in 87 minutes of wall clock on 20 of
this machine's 24 cores.

- **Force-only sensing.** It had the lowest false-approval rate on all three
  failure modes at every eyesight level — but never by more than the margin, so
  nothing could be certified. **Price:** a margin near 0.01 needs a metric
  resolution near 0.005, which needs at least **200 held-out contexts per rig**
  against v4's 60 — so a block more than three times v4's 16,080 runs. No new
  code: same arms, same error ladder, same scoring. This is the most interesting
  measurement the project did not buy.
- **A supervisor that caps its appetite.** The obvious fix for the v6 result:
  cap the *fraction* of the reported room a single move may spend. It uses only
  what the shipped layer already reports. It was deliberately not registered in
  v6 because the twelve candidate moves produce spent fractions of 0.061 and
  0.819 with nothing in between, so any cap that separated the arms would have
  had to be tuned to do so. **Price:** a candidate-move set that fills the gap
  between those two fractions, then one more arm on a v6-shaped block — **about
  780 routes and half an hour**, since v6 ran three arms in 2,340 routes and 87
  minutes.
- **The five-clip result rests on one rig.** One geometry at six slack settings
  crossed with two mounts and five mounting offsets: 60 physical contexts,
  against v5's ten held-out layouts. A v6 finding is a statement about that rig.
  **Price:** a second cell needs its own screen — the first drew 28 candidates
  and registered 9 — and then **a whole second block**, 2,340 routes and 87
  minutes, because nothing from the first one transfers.
- **Neither v5 nor v6 has a figure.** Findings 2 and 3 reach a reader as tables
  only; every other finding here has a picture drawn from its record. **Price:**
  two figures from records already committed, in the plotting environment that
  drew the others. No simulator time, no new measurement.
- **`evidence/cable_baseline_v2.png` has mis-decoded characters in its titles** —
  `â€¢` where a bullet belongs and `Ã—` where a multiplication sign does, from
  UTF-8 text written through a Latin-1 path when it was drawn. Every number on it
  is right and agrees with its record; only the labels are damaged. **Price:** one
  re-render of that figure alone, from `evidence/cable_baseline_v2.json`.
- **v3 stays undecided.** Its own record names the only honest fix: more held-out
  contexts, or a margin of at least two of them, set before collection.
  Re-running the same data under a changed rule would hide the design flaw rather
  than fix it. **Price:** a whole new block with a differently written decision
  rule — not a re-fit — and v4 already answered the question it was reaching for.
- **The workbench window has never been opened.** Everything behind it is
  headless and unit tested; one call to MuJoCo's `launch_passive` is not.
  **Price:** one run of `scripts/workbench.py --run --view` on a machine that has
  a display.

---

## Where the documents had drifted from the repository

Found by checking rather than by measuring. Each of these was a gap between what
a document claimed and what a clone would actually have.

- **Five records the README linked to were not in the repository.** They were on
  disk and git-ignored, so a clone got five dead links and the only copy lived on
  one workstation. The cause was a `.gitignore` line reading `artifacts/` rather
  than `artifacts/*`: git cannot re-include anything inside an excluded
  directory, so every exception under it had been silently dead. Fixed, the
  records are committed, and a test now asks git — not the filesystem — whether a
  linked file is actually in the repository.
- **Forty-one frozen contracts that records named were never carried across**
  when this repository was cut out of the one it came from. Several v1 and v2
  cable records pointed at configs that did not exist here. They do now.
- **Ten scripts that produced the v1 and v2 cable records were missing too**, so
  those records had no reproduction path. Restored from the archive tag, byte for
  byte; they need only modules this repository already has.
- **A test now reads every Python file and checks that each import of this
  repository's own code names a module that exists and a name it defines.** A
  helper that two live entry points imported had been deleted: every unit test
  passed and every simulator entry point failed at import. That cannot happen
  silently again.

## What is still missing, honestly

- **The raw run artifacts behind the peg records are in no repository.** About
  865 MB of trajectories and per-tick samples sit untracked in
  `D:/6axis-space-robotics/artifacts/` on the workstation that produced them.
  Every record carries the sha256 of what it was derived from, so they can be
  checked against the records but not replaced. See
  [docs/PEG_INSERTION.md](docs/PEG_INSERTION.md).
- **Four scripts that v2-era records name no longer exist anywhere** —
  `add_cable_plugin.py`, `load_aic_world.py`, `sim_comparison_test.py` and
  `view_scene.py`. They were deleted in the parent repository's own history
  before this one was cut, so the archive tag does not have them either. The
  records that name them still stand; their exact code does not.
- **The peg campaign's code is not here.** The reinforcement-learning training
  stack stayed in the repository it ran in, preserved under the tag
  `archive/assembly-recovery-training`. [docs/REPO_MAP.md](docs/REPO_MAP.md) says
  how to check it out.

## History

This repository was cut out of the orbital repository's
`research/assembly-recovery-training` branch, which no longer exists: it was
tagged `archive/assembly-recovery-training` and deleted on 2026-09-13, and its
peg-insertion evidence moved here. [docs/REPO_MAP.md](docs/REPO_MAP.md) records
every branch and where it went; [docs/PEG_INSERTION.md](docs/PEG_INSERTION.md)
explains the peg campaign and why a study that rejected its own premise is worth
keeping.

[evidence/INDEX.json](evidence/INDEX.json) lists every record kept here — 30
cable, 66 peg, 3 describing both — each with its own declared scope.
