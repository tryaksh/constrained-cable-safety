# Agent instructions

Read this file at handover. Then [ROADMAP.md](ROADMAP.md) for the verified state
and what stays open, and [README.md](README.md) for what the project is. The
project is closed; there is no next action waiting. Use the tools your client
actually has; tool names from a previous assistant are history, not requirements.

Five documents are maintained, and no others:

| File | What it is for |
| --- | --- |
| [README.md](README.md) | What the project is and what it found, for a stranger |
| [ROADMAP.md](ROADMAP.md) | What is closed, what is open, and what each open item costs |
| [AGENTS.md](AGENTS.md) | This file: the rules and the command sequence |
| [docs/REPO_MAP.md](docs/REPO_MAP.md) | Branches, and what arrived here from where |
| [docs/PEG_INSERTION.md](docs/PEG_INSERTION.md) | The retired peg-insertion campaign |

Everything under [docs/handover/](docs/handover/) is history: each file describes
the repository as it was on the day it was written and is deliberately not
updated afterwards. Do not correct one.

## Mandate

**There is no publication track.** The owner closed it on 2026-09-11: no paper,
no venue. The deliverable is this repository, finished to a standard worth
linking from a personal site. Measuring did not stop; submitting did.

**All four measurement questions are closed, and so is the project.** Do not
start a fifth study, do not refit the safety layer, and do not re-run a fitted
block for nicer numbers. The last planned session
([docs/handover/v7_final_session.txt](docs/handover/v7_final_session.txt)) ran on
2026-09-12 and built what it was asked for: three replay clips, a generated page,
the workbench and a USD export. All four are verified and their records are
committed under `artifacts/showcase/`. **The page is a local file and is not
published anywhere** — do not publish it, and do not build a new one. Nothing is
queued. [ROADMAP.md](ROADMAP.md) is now a record rather than a plan; read it for
what stays open and why none of it was bought.

The 2026-09-13 session ([docs/handover/v8_two_repo_reorganisation.md](docs/handover/v8_two_repo_reorganisation.md))
brought the retired peg-insertion campaign here from the repository this one was
cut out of, because peg insertion is recovery work. Its evidence sits in
`evidence/` beside the cable records and is told apart by the `campaign` field in
`evidence/INDEX.json`. **A peg number is never a cable number.**

The task is **held, clip-preserving seating before gripper release** — extended in
the routing study so that *every* required clip of a five-clip route must still be
held. That is a new task version, not a relabelling, and no earlier block is
rescored under it. Do not claim latching, grasp reliability or hardware transfer.

## How to work

Work autonomously with bounded jobs and one serial simulator queue. Ask only for a
genuinely missing external resource or a real scope decision; resolve ordinary
implementation choices yourself. Keep done-conditions on disk, commit at every
stage boundary, verify per stage rather than at the end, and do not poll long runs.

## Rules that decide results

1. Report the controller that produced the actions. No inherited historical
   success rates.
2. Keep task, observations, geometry, force budget and success criteria identical
   across a comparison. A task correction invalidates affected comparisons: keep
   the previous result and rerun both arms.
3. Inside a job there is no reset, pose write, teleport or attachment change.
   Count any such event as a failed job.
4. Success requires the declared dwell. Include failures, force violations,
   aborts, infeasible constructions and timeouts in denominators.
5. Freeze support, action design, error model, split, metric resolutions, margin
   and predictions in a config, and **commit before launch**. The margin must be
   at least twice the coarsest metric resolution, checked in code. Never lower a
   margin to pass.
6. Every arm reads the same estimate. Ground truth is scoring-only and the
   privilege guard stays armed with its positive control passing.
7. A request cut short is **censored**, never counted as respecting a constraint
   it never got to test.
8. Keep failed experiments, rejections and losing arms as immutable JSON with
   their scope. Correct an interpretation in place with an explicit `superseded`
   field; never delete one.
9. Post-hoc findings are labelled post-hoc and carry no verdict.
10. Capture commit, dirty state, source hashes, config, seeds and environment
    **before** launch. Primary results need a clean tree.
11. Simulator pose plus noise is not perception. Simulation is not hardware
    transfer. No force-certified safety claim.
12. Read an evidence record's scope before quoting its result.

Two instrument findings constrain every claim, both in
[evidence/cable_discretisation_v4.json](evidence/cable_discretisation_v4.json).
The cable model *does* refine, but minimum bend radius does not agree across
refinements, so **C2 stays scoped to the 23-segment model at 4 kHz**. And the
routed cable is **not at rest** at the 5 s settling deadline — it comes to rest
2.9 µm past the retention predicate's own lateral test. The deadline is part of
the task definition. Do not lengthen it and do not change the predicate.

## Where things are

| Need | Read or run |
| --- | --- |
| What this is, and the four results | README.md |
| Verified state, what is open, next action | ROADMAP.md |
| Which record answers a question | evidence/INDEX.json |
| **The shipped safety layer** | src/assembly_recovery/cable_safety_filter_v4.py |
| **The scene: fixture, clips, cable, guards** | src/assembly_recovery/cable_constrained_v2.py |
| **The routing cell, config to scene** | src/assembly_recovery/cable_cell_v6.py; configs/cable_cell_v6_candidates.json |
| **The three constraints and censoring** | src/assembly_recovery/cable_constraints_v4.py |
| **Estimate interface, occlusion, privilege guard** | src/assembly_recovery/cable_perception_v4.py |
| v4 perception study | configs/cable_perception_v4.json; evidence/cable_perception_v4.json; scripts/{screen_layouts,run_perception,fit_perception,controls_perception,replay_perception,summarize_perception}_v4.py |
| v5 composition study | configs/cable_sequence_v5.json; evidence/cable_sequence_v5.json; scripts/{run,evaluate,fit}_sequence_v5.py |
| v6 routing study | configs/cable_routing_v6.json; evidence/cable_routing_v6.json; scripts/{build_cell_cad,screen_cell,render_cell}_v6.py; scripts/{run,evaluate,fit}_routing_v6.py |
| v6 stage records and decision log | artifacts/cell/ |
| **The workbench** | scripts/workbench.py over src/assembly_recovery/cable_workbench_v7.py |
| **The four findings, re-derived from evidence/** | scripts/verify_findings.py |
| **The safety layer run with no simulator** | scripts/try_the_safety_check.py over artifacts/showcase/demo.json |
| **Every headline number, pinned to its record** | tests/test_documented_numbers.py |
| **The replay clips** | scripts/render_routing_video_v6.py; scripts/verify_showcase_video.py |
| **The generated page** | scripts/build_showcase.py; artifacts/showcase/page.json |
| **The USD export** | scripts/export_usd_v7.py |
| **The Isaac Sim re-render** | scripts/render_isaac_v7.py; scripts/encode_isaac_v7.py |
| v7 stage records and decision log | artifacts/showcase/ |
| v3 boundary study, closed inconclusive | configs/cable_repair_boundary_v3.json; evidence/cable_repair_boundary_v3.json |
| v2 task and gate block | configs/cable_recovery_task_v2.json; evidence/cable_recovery_block_v2.json |
| v1 and v2 probes and reviews, restored 2026-09-13 so the early records have a reproduction path | scripts/{probe,review}_cable_{retention,robot,task,baseline,contact}.py; scripts/evaluate_cable_insertion.py |
| The retired peg-insertion campaign | docs/PEG_INSERTION.md; the `campaign: peg` entries in evidence/INDEX.json |
| Branches, and what came here from where | docs/REPO_MAP.md |
| Machine versions | environment-lock.example.json; local environment-lock.local.json |

## Commands

```powershell
.venv/Scripts/python.exe -m pytest                    # 501 tests, CPU-only, ~5 s
.venv/Scripts/python.exe -m ruff check src scripts tests
.venv/Scripts/python.exe scripts/index_evidence.py    # after adding a record
```

The two the README offers a stranger. Both need `.venv` and nothing else, both
exit non-zero when what they check stops holding, and both are run by
`tests/test_entry_points.py`:

```powershell
.venv/Scripts/python.exe scripts/verify_findings.py     # four verdicts, re-derived
.venv/Scripts/python.exe scripts/try_the_safety_check.py  # the filter deciding a real move
```

The four rendered artefacts, in the order they depend on each other. The clips
must exist before the page, because the page embeds them and reads their
verification record.

```powershell
.deps/cable-venv/Scripts/pythonw.exe scripts/render_routing_video_v6.py --layout triptych --view clips `
  --case RC1_l15_compliant4000_m0_E0_unfiltered_r0 `
  --case RC1_l15_compliant4000_m0_E0_filtered_r0 `
  --case RC1_l15_compliant4000_m0_E0_conservative_r0
.deps/cable-venv/Scripts/pythonw.exe scripts/render_routing_video_v6.py --layout estimate --view wide `
  --case RC1_l30_compliant4000_m0_E4_conservative_r2 --name estimate
.deps/cable-venv/Scripts/pythonw.exe scripts/render_routing_video_v6.py --layout budget --view clips `
  --case RC1_l15_compliant4000_m0_E0_conservative_r0 --name budget
.deps/cable-venv/Scripts/pythonw.exe scripts/verify_showcase_video.py   # writes artifacts/showcase/video.json
.venv/Scripts/python.exe scripts/build_showcase.py --published-at <artifact url>
.deps/cable-venv/Scripts/pythonw.exe scripts/workbench.py --self-check  # writes artifacts/showcase/tool.json
.deps/usd-venv/Scripts/python.exe scripts/export_usd_v7.py              # writes artifacts/showcase/usd.json
C:/isaac-sim/python.bat scripts/render_isaac_v7.py --view wide --frames 200 --width 1920 --height 1080
.deps/cable-venv/Scripts/pythonw.exe scripts/encode_isaac_v7.py --scale 1.0 --quality 8
```

The page is published with the Artifact tool, with `index.html` plus `cell.png`
and the three clips and their posters under `video/`. It lives at
<https://claude.ai/code/artifact/71352222-82b3-4676-901c-c2c4852eea3c>.
Republishing the same file path updates that URL; publishing without it creates
a second page.

The routing block, in the order it must run. The cell is authored from the
candidate file, the screen decides which cells are registered, the freeze reads
the screen and is **committed before anything launches**, and the fitter reads one
or more shards together.

```powershell
"C:/Users/tryak/AppData/Local/Programs/FreeCAD 1.1/bin/freecadcmd.exe" scripts/build_cell_cad.py
.deps/cable-venv/Scripts/pythonw.exe scripts/screen_cell_v6.py --workers 20
.venv/Scripts/python.exe scripts/run_routing_v6.py --freeze
.venv/Scripts/python.exe scripts/run_routing_v6.py --run-id <id> --workers 20 --max-minutes 290
.venv/Scripts/python.exe scripts/fit_routing_v6.py --run-dir artifacts/cable/<id>
```

The perception and composition blocks follow the same shape:
`run_perception_v4.py --freeze` then `--run-id <id> --shard N --of M`, then
`fit_perception_v4.py`; `run_sequence_v5.py --freeze` then `--run-id <id>`, then
`fit_sequence_v5.py`. The launcher caps a run at 300 minutes, so longer blocks are
sharded on whole contexts and the fitter reads every shard together.

## This machine

- **Collection is CPU-only and that is a constraint.** MuJoCo's native step is
  CPU, and MJX does not support this scene's cable elasticity plugin, composite
  bodies or elliptic friction cone — moving collection to the GPU would mean a
  different cable model and would invalidate every comparison. The lever is worker
  count: 24 physical cores, **44,966 aggregate steps/s on 20 workers** against
  28,086 on 12. The GPU is for rendering.
- **Windows Application Control blocks `.deps/cable-venv/Scripts/python.exe`.**
  The same environment's `pythonw.exe` is the identical interpreter with identical
  packages and is what every native step uses. Pass
  `--python .deps/cable-venv/Scripts/pythonw.exe` to any launcher. Never copy or
  rename the blocked binary. App Control also blocks `pytest.exe`; use
  `python -m pytest`.
- **Four interpreters.** Torch lives in `.venv` and MuJoCo, SciPy and Matplotlib
  in `.deps/cable-venv`. Fitting runs in the former, physics and figures in the
  latter. `TORCHDYNAMO_DISABLE=1` is the verified workaround for the optional
  compiler import failure. `.deps/usd-venv` is a third, holding `usd-core` and
  `pillow` for the USD export **and nothing else** — the cable environment's
  exact package set is recorded in every run manifest and the provenance depends
  on it not drifting. Isaac Sim 5.1 at `C:/isaac-sim` brings its own interpreter
  (`python.bat`) and is used for rendering only; nothing measured runs in it.
- **The offscreen framebuffer is 1280x960.** A render wider or taller than that
  raises from `mujoco.Renderer`. The 1920-wide replay clip is three separate
  renders composited, not one.
- **There is no display.** Anything that opens a window cannot be run here. Build
  it so that everything except the window is headless and tested, render to a
  file and inspect the file, and say in the handover what was never executed.
- **Isaac Sim renders need the timeline to drive the stage.** Setting the stage
  time by hand with the timeline paused looks correct and silently drops the
  scene out of frame partway through. Let `rep.orchestrator.step` advance the
  timeline. Sphere lights render as visible balls; use distant lights. Geom names
  containing dots, slashes or minus signs are not legal USD paths, so the export
  runs off a sanitised copy of the scene written beside the original.
- **Hash text provenance with `cable_study_v3.content_sha256`, never raw bytes.**
  A CRLF working tree and the LF blob git stores hash differently, which is how the
  v2 block came to record a config hash no committed file reproduces.
- **Multi-line edits: write a Python patch script with `assert old in s` before
  each replace.** Bash heredocs fail here on apostrophes and triple quotes; this
  has cost time in five separate sessions.
- **Do not edit a module a running block imports.** Workers respawn and re-import.
- Do not modify `.deps/aic` (the pinned upstream connector assets); put adapters in
  `src/assembly_recovery/`.

## CAD

Geometry is authored by `freecadcmd.exe` at
`%LOCALAPPDATA%\Programs\FreeCAD 1.1in\`, **not** through the FreeCAD MCP
server — that server needs an RPC server started from a GUI toolbar button, and
there is no GUI here.

Three rules from [the toolchain check](evidence/cell_toolchain_v6.json) are
load-bearing:

- A fuse only welds solids that **interpenetrate**. Overlap adjoining parts by
  about 0.01 mm, or the tessellation is not watertight.
- A clip needs a **floor**, or the cable falls out of the bottom.
- CAD meshes are **visual geoms only** (`contype="0" conaffinity="0" group="2"`,
  `scale="0.001 0.001 0.001"`). Collision stays on the primitives `build_fixture`
  writes: mesh collision does hold the cable, but on a different contact manifold,
  and the retention predicate is decided within about 4 mm. Any new scene must
  also inherit the contact defaults in `cable_constrained_v2.py`, without which a
  0.23 g capsule sinks through a 3 mm plate.

And one that cost twenty minutes: `freecadcmd script.py` runs the file under a
module name of its own, so `if __name__ == "__main__":` never fires and the script
exits 0 having done nothing. Call `main()` directly; `__file__` is not bound
either.

## Outputs and remotes

Keep raw runs, videos and weights in ignored output directories, and concise
verified results in `evidence/`. `artifacts/cell/` and `artifacts/showcase/` are
the exceptions and are committed: their JSON stage records and `PROGRESS.md`
decision logs are small and are what a later session reads. The videos, renders
and USD stages under them are not.
Regenerate `evidence/INDEX.json` after adding a record. Exactly five maintained
Markdown documents, the ones listed at the top of this file — no HANDOFF, NOW or
extra agent file.

When a block finishes, state what changed, what actually ran and the next action.
Do not promise a positive result, publication or hiring.

**Push status.** Pushing to this repository's own remote,
`https://github.com/tryaksh/constrained-cable-safety.git`, is fine and is what
every commit here goes to. A push to the orbital repository,
`https://github.com/tryaksh/orbital-robotic-servicing-lab.git`, was blocked by an
automatic approval review for missing destination authorization and the owner has
not answered. That approval is still pending and takes precedence over any
general branch-push authorization; changing assistant or client is not a
workaround, and neither is creating a new remote.
