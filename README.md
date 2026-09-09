# Assembly Recovery Lab

**Train a robot to recover from a failed assembly attempt and finish the job without a person resetting it.**

The industrial problem is interrupted work: an insertion misses, binds or stalls, and the robot needs another chance without damaging the part. This project studies how a robot can learn that second chance efficiently from its own experience.

The setup is a Franka arm performing peg insertion, followed by gear assembly, in NVIDIA Isaac Lab. It uses force feedback and robot state. Everything is simulated on the current workstation. The old space-rack project has been retired.

[ROADMAP.md](ROADMAP.md) contains the eight-week execution plan, progress and single next action. [AGENTS.md](AGENTS.md) contains the operating rules. These are the only three maintained Markdown files.

## The research question

**At equal training cost, does automatically concentrating practice on recoverable failures reduce unfinished assembly jobs more effectively than uniform training and a simple retract-and-retry controller?**

The proposed method keeps some ordinary successful practice, then allocates the remaining training to fault conditions where the current policy still has something to learn. It learns continuous robot actions, including backing out and approaching again. It does not ask an LLM to choose a move. Training starts from physically valid episode initializations; a recovery must happen through robot actions in the same job.

The study measures complete jobs, time, simulated contact loads and failures as training grows. Checkpoints at roughly 1, 3 and 10 million environment transitions make the scaling question testable. More training is useful only if the held-out curves justify it. Peg insertion establishes the result; gear assembly tests whether it survives a second contact task.

The manuscript will emphasize empirical recovery reliability and training cost. A registered physics-timestep refinement test will evaluate frozen learned policies under finer simulation while preserving control and observation timing; it has not run and is not an algorithmic novelty claim.

The candidate paper contribution is **a reproducible study of how to allocate training for autonomous assembly recovery**, including when the method fails. Neither recovery nor curricula are new inventions. The benefit of this particular allocation is an untested hypothesis.

## Why this direction

Physical Intelligence describes reliability, throughput and learning from a robot's own mistakes as central problems in its work on [learning from experience](https://www.pi.website/blog/pistar06). This project addresses a small, measurable version of that problem.

NVIDIA's [FORGE](https://arxiv.org/abs/2408.04587) already provides force-aware assembly learning, and [AutoMate](https://developer.nvidia.com/blog/?p=85056) studies assembly across geometries. We use the installed FORGE infrastructure instead of rebuilding a simulator and gripper. [ARCH](https://long-horizon-assembly.github.io/) already demonstrates hybrid assembly and recovery. The July 2026 [FORGE-plus preprint](https://arxiv.org/abs/2607.21227) also studies force-budgeted recovery with a frozen LLM supervisor. Our question is training allocation and reliability scaling, not whether assembly recovery can exist.

[Reverse Curriculum Generation](https://arxiv.org/abs/1707.05300) established adaptive start-state training years ago. The paper must compare against a competent curriculum baseline and explain what the new evidence adds. A literature check is required before any novelty claim.

The skills this project can demonstrate include reinforcement learning, force-aware control, fault diagnosis, reproducible GPU experiments and reliable evaluation. These overlap directly with the training, evaluation, scalability and failure-analysis responsibilities in [World Labs' robot-learning role](https://job-boards.greenhouse.io/worldlabs/jobs/4333272009). This is preparation for that work; a simulation project does not establish hardware deployment experience.

## What is actually working

The project now has a verified tensorized finite-job training path around pinned FORGE: complete-job scoring, actor/critic separation, terminal rewards and returns, contact sensing, mutation guards and transition accounting. Lint and 144 CPU tests pass in source-only and staged-Git exports. Protocol v2 is frozen in `configs/protocol_v2.json`; upstream source remains unchanged.

A fresh uniform-fault PPO pilot completed 2,346,880 charged transitions at 1,024 environments in 23.4 minutes. Its saved checkpoint reloads correctly. **The deterministic policy completed 0/84 development jobs: 80 timeouts and 4 force aborts, including 0/12 nominal completions and zero witnessed recoveries.** A functioning training pipeline has not yet produced a competent learned assembly policy. See [evidence/uniform_pilot_v2.json](evidence/uniform_pilot_v2.json). An earlier pilot stopped on a rare initial action-bound failure; its partial checkpoints and the verified correction remain preserved in [evidence/initial_action_projection_v2.json](evidence/initial_action_projection_v2.json).

Physical recovery is demonstrated by the fixed scripted controller. The original 84-case matrix records 60/84 completions versus 14/84 continued insertions and 39 scripted-phase witnessed recoveries. A separate lower/interior/upper support grid gives 73/96 versus 18/96 completions, with all 192 initializations valid. These establish sampled recovery support, not a learned-method advantage or proof of every continuous case. Controller tuning remains capped. See [evidence/peg_fault_matrix_v1.json](evidence/peg_fault_matrix_v1.json) and [evidence/training_support_v1.json](evidence/training_support_v1.json).

The study retains physical held-part gravity, the 30-second deadline, raw 20 N wrist-load abort and 0.5-second seating dwell. Robot gravity compensation is idealized; observations are simulator poses with synthetic noise. Four scripted development pairs complete 2/4 at 120 Hz physics and 1/4 at 240 Hz despite matched external timing/noise, demonstrating sensitivity rather than convergence. No pickup, dropped-part recovery, camera perception, hardware transfer or force-certified safety is established. Final tests and gear learning remain unopened. ROADMAP.md contains the single next action: diagnose the learned policy's incomplete insertions before spending more training compute.

## What the audit changed

The old repository combined several research questions, competing handoffs and hundreds of reports. Some improvements came from changing geometry or retention, while isolated skill scores did not establish complete-job reliability. More GPU time could not resolve those confounds. The surviving value is the infrastructure knowledge and the discipline to compare the same task under the same criteria.

The audit retired 629 of the original 638 tracked files, including the zero-gravity runtime, its tests, old demo service, campaign queues and historical result files. The original code, results, retractions and branch tips are recoverable from a verified Git bundle. All 653 original weight files remain at their local paths; they are legacy assets, not Franka policies. The bundle is local and is not included in a fresh clone.

Archive: `artifacts/audit_2026-09-06/pre_cleanup.bundle`. Exact inventory and restoration details: `maintenance/archive_index.json`. That file is for recovery of history, not routine agent context. Condensed lessons: `maintenance/lessons.json`. Main and remote branches have not been rewritten or pushed.

## Run and inspect

CPU checks need Python 3.11:

```powershell
python -m pip install torch==2.7.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -e ".[dev]"
ruff check src scripts tests
pytest
python scripts/run_experiment.py plan --task peg --epochs 2 --num-envs 64
```

Simulator runs use the pinned Isaac Sim 5.1 / Isaac Lab 2.3.2 stack in `environment-lock.example.json`. On this workstation it is already installed. `scripts/setup_windows.ps1` is the bootstrap for a compatible Windows machine with Isaac Sim installed; it is not a claim that any fresh machine has been tested.

```powershell
.\.venv\Scripts\python.exe scripts/run_validation.py --run-id peg-validation-001 --controller insert_withdraw --seconds 8
.\.venv\Scripts\python.exe scripts/run_experiment.py smoke --run-id peg-smoke-001
.\.venv\Scripts\python.exe scripts/run_experiment.py train --run-id peg-pilot-001 --task peg --epochs 2 --num-envs 64 --max-minutes 15
```

The experiment launcher runs the **upstream baseline only**. The separate validation launcher runs scripted peg probes. `scripts/run_uniform.py` launches the project feedforward PPO pilot and development checkpoint evaluations under the source/config hashes in `configs/protocol_v2.json`; this architecture is distinct from the upstream recurrent reference. It refuses reused run IDs and unpinned or modified upstream source, records source and configuration hashes before launch, sets a wall-clock deadline and checks saved artifacts. `TORCHDYNAMO_DISABLE=1` avoids an optional compilation import failure in the current simulator environment. A timeout remains a timeout even if a partial checkpoint exists. The peg pilot gates now pass. Primary campaigns, gear validation and final tests remain separate milestones. The completed pilot measured 1,638 rollout transitions/s end to end and 5,573 MiB peak GPU memory. This counts absorbing slots: only 851,578 of its 2,304,000 rollout slots supplied active learning samples. Full resource and failure accounting is in [evidence/tensorized_training_block_v2.json](evidence/tensorized_training_block_v2.json).

## The website and paper deliverables

The website will show the same held-out fault under standard training, retract-and-retry and learned recovery. A visitor can choose a recorded fault and see the robot, force trace, elapsed time and complete-job outcome. Every replay links to the run and checkpoint behind it. Show a failure alongside successes and label the scene as simulation. A static replay page is sufficient; no hosted GPU is required.

By week four: a credible peg-task result and recorded comparison. By week eight: two-task evidence, scaling curves, released experiment specifications and a manuscript suitable for a focused robotics workshop or technical preprint. A stronger result may support a larger submission. Acceptance and a positive experimental result cannot be promised.

A clear interview description, once the work is completed: "I studied how robots can learn to recover from assembly failures. I compared training strategies at equal compute and measured how often the robot finished the whole job, how long it took, and what happened to contact forces."
