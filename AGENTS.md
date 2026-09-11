# Agent instructions

Read this file explicitly at handover; do not assume your client loads it. Then read [ROADMAP.md](ROADMAP.md) for the verified state and the single next action, and [README.md](README.md) for the explanation and prior-art boundaries. These three files are the only maintained Markdown. Use the tools your client actually has; tool names and agent ids from a previous assistant are history, not requirements.

## Current mandate

**There is no publication track.** On 2026-09-11 the owner ended it: no workshop paper, no venue. The deliverable is this repository, finished to a standard worth linking from a personal site — readable by a non-specialist in minutes, with every number traceable to an evidence record. Keep it that way. Measuring did not stop; submitting did.

Two questions have been pre-registered and executed. The **safe-repair boundary** (v3) is answered and closed: see [evidence/cable_repair_boundary_v3.json](evidence/cable_repair_boundary_v3.json). Do not re-run it under a changed rule to get a cleaner verdict; the `inconclusive` verdict and the pre-registration defect behind it are the result and stay recorded. The **perception** question (v4) asks how much a safety check must see as the state estimate degrades, and across three constraint shapes; its contract is [configs/cable_perception_v4.json](configs/cable_perception_v4.json) and [ROADMAP.md](ROADMAP.md) carries its verified state.

The task is **held, clip-preserving seating before gripper release**. Do not relabel prior seating as recovery, or claim latching, grasp reliability or hardware transfer. A tempting and wrong move, already tried and recorded: widening the support with another mechanical perturbation in the hope of a residual failure. In v2 and v3 every arm was handed the port's live pose at 500 Hz, so mounting offsets and mount compliance were tracked rather than missed (18 of 18, then 15 of 15). v4 removes that: every arm reads a declared *estimate*, ground truth is scoring-only, and a fail-closed privilege guard fails any request whose control-side code touches a truth channel. If you add an arm, it reads the same estimate as every other one. Manufacturing a failure by withholding information from one arm is forbidden and would make the cohort, not measure it.

**Two instrument findings constrain what may be claimed**, both in [evidence/cable_discretisation_v4.json](evidence/cable_discretisation_v4.json). The cable model *does* refine: the v3 refinement failure was a bending-damping scaling error in the control that tested it, and a fourfold refinement now settles at three integration rates. But the routed cable is **not at rest** at the registered five-second settling deadline — it slides along the clip channel and comes to rest against the clip wall, which is exactly where the retention predicate's lateral test sits. The deadline is therefore part of the task definition, not an approximation to rest. Do not lengthen it, and do not change the retention predicate; either would change the task and invalidate every comparison with v2 and v3.

## Work autonomously

ROADMAP is the plan; update its verified state. Work through the whole experiment cycle with bounded jobs, one serial GPU queue, and time reserved for verification and handoff. Ask only for a genuinely missing external resource or a real high-level scope decision; resolve ordinary implementation choices yourself. Suggest a manual action only after identifying a concrete obstacle it would clear faster, and then give a prepared case and an exact short instruction.

## Scientific and engineering rules

1. Report the controller that produced the actions. Scripted, retrofitted, upstream and proposed controllers get different labels. No inherited historical success rates.
2. Keep task, observations, geometry, force budget, reward and success criteria identical across a comparison. A task correction invalidates affected comparisons: keep the previous result and rerun both arms.
3. Derive feasible fault ranges from geometry and actions before spending compute. Audit action transforms and clamps, not only observation tensors. Contact filters must use real geometry ids and pass positive controls.
4. Initialization between jobs may write state. Inside a job there is no reset, pose write, teleport or attachment change; count any such event as a failed job. A dropped part ends the job.
5. Success requires the declared dwell. Include failures, force violations, aborts, infeasible constructions and timeouts in denominators. Reward shaping is not a hard force ceiling.
6. Match total simulator transitions, nominal practice, architecture and tuning budget, including fault mining and probes. Keep training, development and test seeds and combinations separate. Select checkpoints by declared budget, never by final-test performance.
7. Keep failed experiments as immutable JSON with scope and limitations. Correct an interpretation in place with an explicit superseded field; never delete a losing arm.
8. Capture commit, dirty state, source hashes, upstream revision, config, seeds, command, environment and checkpoint hashes **before** launch. Primary results need a clean tree or an exact archived snapshot.
9. Use unique run ids and reject collisions. Check artifact contents, not log exit lines. Timeouts and process failures stay failures even if partial weights exist.
10. Measure sustained throughput and memory for the actual task. Leave RAM and time for evaluation. Avoid editing executing scripts.
11. Simulator pose plus noise is not perception. Simulation is not hardware transfer. Preset grasping is not learned pickup. No force-certified safety or autonomous-factory claim.
12. Read an evidence file's scope before quoting its result. Distinguish recovery after a witnessed failure from prevention. A high isolated-skill rate does not establish reliable complete jobs.

## Files and commands

| Need | Read or run |
| --- | --- |
| Goal, executed evidence, prior art | README.md |
| Plan, verified state, one next action | ROADMAP.md |
| Which evidence record answers a question | evidence/INDEX.json |
| **The perception question, its verdict and its caveats** | evidence/cable_perception_v4.json; evidence/cable_perception_controls_v4.json |
| **What was frozen before the perception block launched** | configs/cable_perception_v4.json; configs/cable_perception_v4_candidates.json |
| **Does the cable model refine, and is the initial state at rest** | evidence/cable_discretisation_v4.json |
| **Which candidate layouts survived, and why the others did not** | evidence/cable_layout_screen_v4.json |
| **Why the C2 spec and the error ladder are what they are** | evidence/cable_perception_pilot_v4.json |
| **The labels re-derived from the ledgers alone** | evidence/cable_perception_replay_v4.json |
| **How the threshold moves with the cable's own properties** | evidence/cable_transfer_protocol_v4.json |
| **Estimate interface, occlusion model and privilege guard** | src/assembly_recovery/cable_perception_v4.py |
| **The three constraints and the censoring rule** | src/assembly_recovery/cable_constraints_v4.py |
| **Perception support, error ladder, arms, metrics** | src/assembly_recovery/cable_study_v4.py |
| **Freeze, run, fit, control, replay, render, film that block** | scripts/run_perception_v4.py; scripts/evaluate_cable_perception_v4.py; scripts/fit_perception_v4.py; scripts/controls_perception_v4.py; scripts/replay_perception_v4.py; scripts/render_perception_v4.py; scripts/render_perception_video_v4.py; scripts/summarize_perception_v4.py |
| The earlier answered question, its verdict and its caveats | evidence/cable_repair_boundary_v3.json; evidence/cable_boundary_controls_v3.json |
| What was frozen before that block launched | configs/cable_repair_boundary_v3.json |
| Probes that chose the registered support | evidence/cable_support_probes_v3.json |
| Support, action design, features, metrics | src/assembly_recovery/cable_study_v3.py |
| Run, fit, control, render that block | scripts/run_repair_boundary_v3.py; scripts/fit_repair_boundary_v3.py; scripts/controls_repair_boundary_v3.py; scripts/render_repair_boundary_v3.py |
| Executed cable task and gate results | evidence/cable_recovery_block_v2.json; evidence/cable_recovery_replay_v2.json |
| Runnable cable task configuration | configs/cable_recovery_task_v2.json |
| Cable scene, loads, clip geometry, mutation guard | src/assembly_recovery/cable_constrained_v2.py |
| Controllers and the shared repair library | src/assembly_recovery/cable_recovery_control_v2.py |
| Run, review, render a block | scripts/run_cable.py; scripts/evaluate_cable_recovery_v2.py; scripts/review_cable_recovery_v2.py; scripts/render_cable_recovery_v2.py |
| Design intent and open critiques | evidence/cable_direction_audit_v2.json; evidence/cable_technical_audit_v2.json; evidence/cable_research_critique_v2.json |
| Retired plan and README history | evidence/roadmap_history_v1.json; evidence/readme_peg_history_v1.json |
| Machine versions | environment-lock.example.json; local environment-lock.local.json |
| Compact lessons from the retired project | maintenance/lessons.json |
| Recover an old file or branch | maintenance/archive_index.json, on demand only |

```powershell
.venv/Scripts/python.exe scripts/setup_cable.py
.venv/Scripts/python.exe -m ruff check src scripts tests
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe scripts/run_cable.py --run-id <id> --worker scripts/evaluate_cable_recovery_v2.py --config configs/cable_recovery_task_v2.json --max-minutes 45 -- --workers 12
.venv/Scripts/python.exe scripts/run_repair_boundary_v3.py --run-id <id> --workers 12 --max-minutes 150
.venv/Scripts/python.exe scripts/fit_repair_boundary_v3.py --run-dir artifacts/cable/<id> --out evidence/<name>.json
```

The perception block, in the order it must be run. Freeze reads the executed screen and writes the surviving support, the split and the request count into the contract; the contract is then **committed before anything launches**. The launcher caps a run at 300 minutes, so the block is sharded on whole contexts and the fitter reads every shard together.

```powershell
.deps/cable-venv/Scripts/python.exe scripts/screen_layouts_v4.py --workers 14
.venv/Scripts/python.exe scripts/run_perception_v4.py --freeze
.deps/cable-venv/Scripts/python.exe scripts/controls_perception_v4.py
.venv/Scripts/python.exe scripts/run_perception_v4.py --run-id <id>-s1 --shard 1 --of 4 --workers 20 --max-minutes 290
.venv/Scripts/python.exe scripts/fit_perception_v4.py --run-dir artifacts/cable/<id>-s1 --run-dir artifacts/cable/<id>-s2 --out evidence/cable_perception_v4.json --dataset-out artifacts/cable/<id>-s1/study_dataset.json
.venv/Scripts/python.exe scripts/summarize_perception_v4.py
.venv/Scripts/python.exe scripts/replay_perception_v4.py --run-dir artifacts/cable/<id>-s1
.deps/cable-venv/Scripts/python.exe scripts/render_perception_v4.py
.deps/cable-venv/Scripts/python.exe scripts/render_perception_video_v4.py --case <request id> --run-dir artifacts/cable/<id>-s1
```

Torch lives in `.venv` and MuJoCo, SciPy and Matplotlib in `.deps/cable-venv`; fitting runs in the former and physics and figures in the latter. Hash text provenance with `cable_study_v3.content_sha256`, never raw bytes: a CRLF working tree and the LF blob git stores hash differently, which is how the v2 block came to record a config hash no committed file reproduces.

**Collection is CPU-only and that is a constraint, not a preference.** MuJoCo's native step is CPU, and the GPU path (MJX) does not support this scene's cable elasticity plugin, composite bodies or elliptic friction cone, so moving collection to the GPU would mean a different cable model and would invalidate every comparison with v2 and v3. The lever that does exist is worker count: this machine has 24 physical cores, and the perception pilot measured 28,086 aggregate native steps per second on 12 workers against 44,966 on 20, a 1.60x speedup for a 6.6 per cent per-worker loss. Model fitting accepts `--device cuda` where a CUDA build of torch is installed; the fits are minutes beside hours of collection.

CI uses bare pytest. App Control on this workstation blocks `pytest.exe`; use `python -m pytest`. Tests must run without ignored artifacts, Isaac Sim or a GPU. Native dynamics use `.deps/cable-venv/Scripts/python.exe` (Python 3.11.15, MuJoCo 3.3.7); CPU checks use `.venv/Scripts/python.exe`. Do not modify `.deps/IsaacLab` or `.deps/aic`; put adapters in `src/assembly_recovery/`. `TORCHDYNAMO_DISABLE=1` is the verified workaround for the optional compiler import failure.

Keep raw runs, videos and weights in ignored output directories and concise verified results in `evidence/`. Regenerate `evidence/INDEX.json` with `scripts/index_evidence.py` after adding a record. Exactly three maintained Markdown documents: no HANDOFF, NOW, NEXT_WORK or extra agent file. Manuscript source, if any, is LaTeX; references and machine records are JSON or BibTeX.

When a block finishes, state what changed, what actually ran and the next action. Do not promise a positive result, publication or hiring. Safe non-force pushes to `research/assembly-recovery-training` are authorized; `main` stays unchanged.

**Publication status:** there is no paper and no venue; the owner closed that track on 2026-09-11. An automatic approval review previously blocked the push to `https://github.com/tryaksh/orbital-robotic-servicing-lab.git` because explicit destination authorization was missing, and the owner has not answered that question. Continue local work and commits on `research/assembly-recovery-training`. This pending approval takes precedence over the general branch-push authorization above; changing assistant or client is not a workaround, and neither is creating a new remote.
