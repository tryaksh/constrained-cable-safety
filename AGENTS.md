# Agent instructions

Read this file explicitly at handover; do not assume your client loads it. Then read [ROADMAP.md](ROADMAP.md) for the verified state and the single next action, and [README.md](README.md) for the explanation and prior-art boundaries. These three files are the only maintained Markdown. Use the tools your client actually has; tool names and agent ids from a previous assistant are history, not requirements.

## Current mandate

**The research line is closed.** On 2026-09-11 the owner ended the publication track: no workshop paper, no venue. The deliverable is this repository, finished to a standard worth linking from a personal site — readable by a non-specialist in minutes, with every number traceable to an evidence record. Keep it that way.

The pre-registered safe-repair boundary question was executed and answered: see [ROADMAP.md](ROADMAP.md) for the verified state and [evidence/cable_repair_boundary_v3.json](evidence/cable_repair_boundary_v3.json) for the block. Do not reopen it without clearing the one open failure named in the roadmap. Do not re-run the block under a changed rule to get a cleaner verdict; the `inconclusive` verdict and the pre-registration defect behind it are the result and stay recorded.

The task is **held, clip-preserving seating before gripper release**. Do not relabel prior seating as recovery, or claim latching, grasp reliability or hardware transfer. A tempting and wrong move, already tried: widening the support with another mechanical perturbation in the hope of a residual failure. Every arm is handed the port's live pose at 500 Hz, so mounting offsets and mount compliance are tracked rather than missed (18 of 18, then 15 of 15). Either the perturbation must be genuinely unobservable, or the honest move is to measure something else.

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
| The answered question, its verdict and its caveats | evidence/cable_repair_boundary_v3.json; evidence/cable_boundary_controls_v3.json |
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

Torch lives in `.venv` and MuJoCo, SciPy and Matplotlib in `.deps/cable-venv`; fitting runs in the former and physics and figures in the latter. Hash text provenance with `cable_study_v3.content_sha256`, never raw bytes: a CRLF working tree and the LF blob git stores hash differently, which is how the v2 block came to record a config hash no committed file reproduces.

CI uses bare pytest. App Control on this workstation blocks `pytest.exe`; use `python -m pytest`. Tests must run without ignored artifacts, Isaac Sim or a GPU. Native dynamics use `.deps/cable-venv/Scripts/python.exe` (Python 3.11.15, MuJoCo 3.3.7); CPU checks use `.venv/Scripts/python.exe`. Do not modify `.deps/IsaacLab` or `.deps/aic`; put adapters in `src/assembly_recovery/`. `TORCHDYNAMO_DISABLE=1` is the verified workaround for the optional compiler import failure.

Keep raw runs, videos and weights in ignored output directories and concise verified results in `evidence/`. Regenerate `evidence/INDEX.json` with `scripts/index_evidence.py` after adding a record. Exactly three maintained Markdown documents: no HANDOFF, NOW, NEXT_WORK or extra agent file. Manuscript source, if any, is LaTeX; references and machine records are JSON or BibTeX.

When a block finishes, state what changed, what actually ran and the next action. Do not promise a positive result, publication or hiring. Safe non-force pushes to `research/assembly-recovery-training` are authorized; `main` stays unchanged.

**Publication status:** there is no paper and no venue; the owner closed that track on 2026-09-11. An automatic approval review previously blocked the push to `https://github.com/tryaksh/orbital-robotic-servicing-lab.git` because explicit destination authorization was missing, and the owner has not answered that question. Continue local work and commits on `research/assembly-recovery-training`. This pending approval takes precedence over the general branch-push authorization above; changing assistant or client is not a workaround, and neither is creating a new remote.
