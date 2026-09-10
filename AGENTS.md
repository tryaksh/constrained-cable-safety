# Agent instructions

Read this file, then the current-state table and next action in [ROADMAP.md](ROADMAP.md). Read [README.md](README.md) for the project explanation and prior-art boundaries. These are the only maintained Markdown documents. Do not read the archive, old logs or checkpoint inventories unless a specific question requires them. Search src, scripts, tests and configs by default; .rgignore excludes the large historical index from routine searches.

The fixed eight-week objective is **learned recovery from failed industrial assembly attempts at equal training cost**, using Franka and pinned Isaac Lab FORGE: peg insertion, then gear meshing. The owner explicitly authorized replacing the old project and wants agents to execute without technical micromanagement. The old zero-gravity robot, service, claims and campaigns are retired. No routine session may reopen robot choice or the research question.

## Work autonomously

Take the single next action in ROADMAP.md, implement it, verify the artifact and update the state in that same file. Work in bounded blocks of up to five hours and reserve the final 30 minutes for verification and handoff. The owner is not a technical supervisor for those blocks. Ask only for essential missing external resources or a genuine high-level scope decision. Resolve normal implementation choices yourself.

The owner does not need to learn CAD, inspect the simulator manually, or guide routine runs for work to continue. Suggest a manual action only after identifying a concrete obstacle that it would resolve faster or more reliably than the available tools. Supply a prepared case and an exact short instruction; never make manual participation an artificial gate. Keep CAD and connector setup conditional on a measured geometry need.

Do not start long training before the week-one physics, observation, fault-validity and evaluation gates pass. The existing launcher runs upstream FORGE only; it does not implement the proposed study. The two-epoch pilot proves training can save weights, not that a competent policy or recovery method exists.

## Scientific and engineering rules

1. Report the controller that produced the actions. Scripted retries, upstream policies and the proposed policy must have different labels. No inherited historical success rates.
2. Keep the task, observations, geometry, force budget, reward and success criteria identical across a comparison. A task correction invalidates affected comparisons; keep the previous result and rerun both arms.
3. Derive feasible fault ranges from geometry and actions before spending the GPU. Upstream FORGE disables roll/pitch actions and held-part gravity; audit both. Actor access includes action transforms and clamps, not just observation tensors. Contact filters must use actual USD rigid-body paths and pass positive controls; displayed names and collision mesh paths can silently produce zero readings.
4. Initialization between jobs may write simulator state. Recovery within a job may not reset, teleport, write part poses, or change attachment constraints. Count any such event as a failed job. A dropped part is outside the retained-grasp scope and ends the job.
5. Preserve the upstream task predicate and report it separately from project completion. Success requires the declared dwell. Include failures, force violations, aborts and timeouts in denominators. Force reward shaping alone is not a hard force ceiling.
6. Match total simulator transitions, nominal practice, architecture and tuning budget. Include fault-mining and probe rollouts. Keep training/development/test seeds and fault combinations separate. Select checkpoints by declared training budget, not final-test performance.
7. Keep failed experiments as immutable JSON records with scope and limitations. Correct an interpretation in place with an explicit superseded field, never delete a losing arm to tell a cleaner story. The 2026 audit archived old failed evidence with the entire old project; it does not authorize erasing new negative results.
8. Capture commit, dirty state, actual source hashes, upstream revision, config, seeds, command, environment and checkpoint hashes **before** launch. Preserve source snapshots for dirty development runs. Changes committed at the end of a run are not its source provenance. Primary results require a clean source tree or an exact archived source snapshot.
9. Use unique run IDs and reject collisions. Check artifact contents, not only log exit lines. Timeouts and process failures remain failures even if partial weights exist. Record partial checkpoints without calling a run complete.
10. Use one GPU job and one serial queue by default. Measure sustained throughput and memory for this task. Leave RAM and time for evaluation; never recreate the old sleeping-shell supervisors. Avoid editing executing scripts.
11. Simulator pose with added noise is not camera perception. A simulation result is not hardware transfer. Preset grasping is not learned pickup. No claim of force-certified hardware safety or fully autonomous factory operation.
12. Read the scope of an evidence file before quoting its result. Distinguish recovery after a witnessed failure from prevention. A high isolated-skill rate does not establish reliable complete jobs.

## Files and commands

| Need | Read or run |
| --- | --- |
| Goal, explanation and current literature | README.md |
| Plan, verified state and one next action | ROADMAP.md |
| Study settings and gate status | configs/study.json |
| Upstream baseline launcher | scripts/run_experiment.py |
| Simulator smoke check | scripts/assembly_smoke.py |
| Bounded peg validation | scripts/run_validation.py; scripts/validate_peg.py |
| Current validation findings | evidence/peg_validation.json; evidence/reward_audit.json |
| Frozen learned/retry physics validation | configs/learned_physics_validation_v3.json; scripts/run_learned_physics_v3.py; evidence/learned_physics_validation_v3.json |
| Cheap run-planning and artifact checks | src/assembly_recovery/ |
| Machine versions | environment-lock.example.json; local environment-lock.local.json if present |
| Compact lessons from the retired project | maintenance/lessons.json |
| Recover an old file or branch | maintenance/archive_index.json, on demand only |

```powershell
ruff check src scripts tests
pytest
python scripts/run_experiment.py plan --task peg --epochs 2 --num-envs 64
```

CI uses bare pytest. On this Windows workstation App Control blocks pytest.exe; use `.venv/Scripts/python.exe -m pytest`. Tests must run without ignored local artifacts, Isaac Sim or a GPU. Simulator verification is a separate bounded job. Do not replace these cheap checks with hours of training.

Do not modify `.deps/IsaacLab` to implement this study. Put adapters in `src/assembly_recovery/`, retain the upstream baseline, and pin the installed version. `TORCHDYNAMO_DISABLE=1` is the verified local workaround for the optional compiler import failure; the launcher records it. New machine setup is not verified merely because this workstation runs.

Read only `summary`, `key_findings`, `next_action` and `scope_and_limitations` from `evidence/peg_validation.json` at handoff; the per-run and historical arrays are for specific investigations.

Keep raw runs, videos and weights in ignored output directories. Keep concise verified evidence in `evidence/`. Exactly three maintained Markdown documents: no HANDOFF, NOW, NEXT_WORK, new paper-plan or extra agent file. Future manuscript source can be LaTeX. References and detailed machine records belong in JSON or BibTeX.

When a block finishes, state what changed, what actually ran and the next action. Do not promise a positive result, publication acceptance or hiring. Stop proposing new pivots and build the experiment in ROADMAP.md.
