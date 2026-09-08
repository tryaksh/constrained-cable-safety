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

The audit on 2026-09-06 ran the upstream Franka peg task on this workstation: four parallel environments, 16 control steps, finite observations, rewards and force signals. A separate two-epoch PPO pilot with 64 environments completed and saved checkpoints. Its reported training throughput was 205 and 192 transitions/second; two samples establish feasibility, not sustained campaign capacity.

These are infrastructure checks. The peg adapter now runs with direct part/fixture and finger-contact sensing, complete-job scoring and blocked resets/pose writes. A predeclared matrix of 84 development cases across seven numeric fault bins gives 60/84 scripted retry completions versus 14/84 matched continued insertions, including 39 fully witnessed contact-stall -> withdrawal -> reinsertion recoveries. All 168 initializations pass; force aborts are 5 versus 11. This establishes recovery support at sampled development values, not learned recovery or complete validation of the severity ranges. The earlier unresolved case 1 also recovers at 25.075 s under a second bounded script, which loses the earlier case 2 recovery. Every failure is preserved and controller tuning is capped. **The learned method, trained baseline, tensorized training integration and website remain unfinished.** See [evidence/peg_fault_matrix_v1.json](evidence/peg_fault_matrix_v1.json), [evidence/fault_validation_block.json](evidence/fault_validation_block.json), and ROADMAP.md.

Physical gravity on the held part is selected for the study. The upstream reference preserves its gravity-disabled default; the robot still uses idealized gravity compensation. Observations are simulator-derived pose with synthetic noise. The scope remains insertion and recovery while holding a part: no pickup, dropped-part recovery, camera perception or hardware-transfer claim. Under the unchanged resolved FORGE reward, the recorded recovery earns discounted job return 75.797 versus 37.543 for continued insertion (gamma 0.995), excluding post-termination rewards. [evidence/reward_audit.json](evidence/reward_audit.json) contains all terms, terminal-sampling limitations and an explicit correction of the earlier action-change coefficient. Broader fault support and training terminal handling remain open.

## What the audit changed

The old repository combined several research questions, competing handoffs and hundreds of reports. Some improvements came from changing geometry or retention, while isolated skill scores did not establish complete-job reliability. More GPU time could not resolve those confounds. The surviving value is the infrastructure knowledge and the discipline to compare the same task under the same criteria.

The audit retired 629 of the original 638 tracked files, including the zero-gravity runtime, its tests, old demo service, campaign queues and historical result files. The original code, results, retractions and branch tips are recoverable from a verified Git bundle. All 653 original weight files remain at their local paths; they are legacy assets, not Franka policies. The bundle is local and is not included in a fresh clone.

Archive: `artifacts/audit_2026-09-06/pre_cleanup.bundle`. Exact inventory and restoration details: `maintenance/archive_index.json`. That file is for recovery of history, not routine agent context. Condensed lessons: `maintenance/lessons.json`. Main and remote branches have not been rewritten or pushed.

## Run and inspect

CPU checks need Python 3.11:

```powershell
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

The experiment launcher runs the **upstream baseline only**. The separate validation launcher runs scripted peg probes, not learned policies. It refuses reused run IDs and unpinned or modified upstream source, records source and configuration hashes before launch, sets a wall-clock deadline and checks saved artifacts. `TORCHDYNAMO_DISABLE=1` avoids an optional compilation import failure in the current simulator environment. A timeout remains a timeout even if a partial checkpoint exists. Long study campaigns must wait for the week-one validity gates.

## The website and paper deliverables

The website will show the same held-out fault under standard training, retract-and-retry and learned recovery. A visitor can choose a recorded fault and see the robot, force trace, elapsed time and complete-job outcome. Every replay links to the run and checkpoint behind it. Show a failure alongside successes and label the scene as simulation. A static replay page is sufficient; no hosted GPU is required.

By week four: a credible peg-task result and recorded comparison. By week eight: two-task evidence, scaling curves, released experiment specifications and a manuscript suitable for a focused robotics workshop or technical preprint. A stronger result may support a larger submission. Acceptance and a positive experimental result cannot be promised.

A clear interview description, once the work is completed: "I studied how robots can learn to recover from assembly failures. I compared training strategies at equal compute and measured how often the robot finished the whole job, how long it took, and what happened to contact forces."
