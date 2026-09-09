# Roadmap: learn to recover, then measure whether training pays

**Locked goal:** autonomous recovery from failed industrial assembly attempts, evaluated at equal training cost. Franka + FORGE peg insertion first, gear assembly second. Eight weeks on the current workstation, starting with the first implementation session after the 2026-09-06 audit. Agents execute the work; the owner does not need to supervise technical choices or approve each run.

This file is the only plan and handoff. Update its current-state table in place after each work block. A five-hour block is an execution/checkpointing unit, not a request for five hours of owner attention. No new robot, perception project, VLA, space task or research question during these eight weeks. Negative results change the conclusion, not the project identity.

## Current state

| Item | Verified state |
| --- | --- |
| Audit and source archive | Completed; original commit `1b969f6db01aeac226667db4759b7603b3f663a0`, all original refs in verified local bundle |
| Old active project | Retired; 629 original tracked files removed; all 653 original weights rehashed and verified unchanged |
| Clean repository | Exactly three Markdown documents; historical index excluded from routine searches |
| Simulator | Upstream peg smoke passed: 4 environments, 16 steps; no recovery claim |
| Training | Fresh value-unclipped v4 completed 22 cohorts and 10,326,272 charged transitions in 111.5 minutes. All 22 model/optimizer checkpoints are finite; exact source and artifact hashes verified. Final deterministic development evaluation completed 81/84 jobs: 12/12 nominal and 69/72 fault cases, with two force aborts and one deadline. Prior interrupted v3/v4 attempts remain preserved. |
| Verification | Ruff and 175 CPU tests pass. All 22 v4 model/optimizer checkpoints are finite and budget-consistent; source snapshots and primary evaluation artifacts verified. All three recovery-assay physical prefixes and sensor draws match exactly; unchanged retry reproduces its prior full trajectory bit for bit. Source-only export verification is recorded in the final block evidence. |
| Study implementation | Frozen reward-v3/value-unclipped-v4 PPO now produces a strong development insertion policy. A separate fixed four-second scripted-prefix assay tests actual post-stall completion without resets, pose writes or evaluator-triggered handoff. The existing recovery witness requires a five-millimetre withdrawal and does not count the learned lateral correction; retain both measured endpoints and the original failed gate. |
| Physics and job accounting | Physical held-part gravity; raw 20 N wrist abort at native physics rate, 30 s deadline and 0.5 s seating dwell retained. No within-job reset or pose writes. Initialization, active and absorbing costs are explicit. A noisy-target initial-action overflow was reproduced and corrected without changing physical states/noise; all 5,120 v2 training initializations valid. |
| Remaining validation | Peg pilot protocol v2 frozen after required checks. Sampled support covers lower/interior/upper values; continuous-range guarantees remain unavailable. Four development physics pairs verify 120/240 Hz timing/noise/force conversion but complete 2/4 versus 1/4 (1/4 jointly). Learned-policy robustness, gear and final tests remain open. |
| Scientific evidence | Learned Gaussian mean: 81/84 primary development completions (12/12 nominal, 69/72 fault), two force aborts, one deadline, zero witnessed initial failures. In the separate matched prefix assay, learned/scripted retry/continued insertion complete 22/28, 19/28 and 3/28 whole jobs. Among the same 17 witnessed stalled jobs active at handoff, post-stall completions are 13/17, 13/17 and 0/17. All three share three prefix-script completions and two prefix force aborts. No curriculum advantage or independent-training-seed claim. |
| Resource allocation | Renewed block: 12 serial simulator launches, 11 complete and one interrupted; at least 14,010,969 charged transitions including the failed repeat. Cumulative tracked training/development ledger is at least 24,764,663.25. Completed v4 training: 1,515 end-to-end rollout transitions/s, 5,433 MiB peak GPU, 14,902 MiB minimum available RAM; 17.4 percent of rollout slots supplied active samples. All owned simulator jobs have stopped. |
| Website / manuscript | Not built. Original scripted simulator video retained. New measured learned/retry/continue motion figure is verified at artifacts/assembly/failure_prefix_v4_r01_review/matched_prefix_motion.png and .pdf; it shows post-stall lateral correction without the five-millimetre retraction required by the old witness. |
| Execution authorization | Owner renewed autonomous work and requested a practical handover only after verification. No sleep-guard work. Future 2048/4096-environment probes are authorized if prior work is preserved; benchmark 2048 first and adopt only after measured throughput, RAM and GPU checks under a new shared comparison configuration. Local commits only; GitHub destination remains undecided. |
| Single next action | Endpoint `post_stall_completion_v1` and six-run confirmation preregistered in `configs/failure_prefix_confirmation_v2.json`; 187 CPU tests pass. Run the frozen v4 model with the unchanged four-second prefix on development seeds 10071 and 10072 against unchanged retry and continued insertion (77,007 charged transitions). Verify common prefixes, RNG, native replay and scripted actions before interpreting results. Original withdrawal metric and failed gate remain frozen; no new training or final-test use. |

## The fixed experiment

**Question:** does concentrating practice on recoverable failures improve complete-job reliability per training transition compared with uniform practice and simple retries?

A job begins with a valid grasped part above the fixture and ends in settled insertion, a declared abort or a deadline. A miss or stall must be resolved with robot actions during that same job. Episode initialization between jobs is allowed. Simulator reset, pose writes, changing a joint constraint or regrasping by teleportation during a job counts as an unfinished job. This is autonomous recovery within an assembly job, not reset-free training or a complete factory cell.

Start with lateral fixture-pose bias, approach offset and friction variation. They can generate recoverable misses and stalls without inventing a broken part. All faults are sampled at job initialization and act through the same interface in every arm. Reserve unseen combinations and severity ranges for evaluation. Gear assembly can add a yaw error. Do not add roll/pitch faults while those action axes are disabled upstream. Do not inject arbitrary penetrations or restore incomplete PhysX state snapshots.

**Training arms, with the same architecture, reward, fault support and job horizon:**

| Arm | Purpose |
| --- | --- |
| Standard FORGE training | Reference implementation; it already has force-aware exploration, so never label it incapable of recovery by design |
| Standard policy + bounded retract/retry | Strong practical baseline using the same noisy observations and contact signal; retry time counts toward the same job deadline |
| Uniform fault training | Main compute-matched learning baseline: fixed sampling across the declared fault support |
| Adaptive fault training | Candidate: 25% nominal practice; 75% prioritized toward fault bins with intermediate success and recent learning progress |
| Fixed difficulty curriculum | Established easy-to-hard baseline, same fault support and compute; prevents claiming that any curriculum improvement is new |

Uniform and adaptive arms both retain the same 25% nominal share. Begin the adaptive score with intermediate difficulty `p * (1 - p)`; add a learning-progress term only as a separately registered ablation, not an invisible change after seeing results. Maintain a nonzero sampling floor for every training bin. This is a candidate curriculum, not a proven algorithm. Train from normal episode initializations and sample fault settings; do not reset directly into a supposed recoverable contact state.

**Outcomes:** unfinished jobs per 100 requests is primary. Report nominal success, per-fault success, recoveries after an observed miss/stall, time per request including failures, time per successful job, peak simulated contact force, force-budget violations, aborts and simulator resets. Distinguish preventing a failure from recovering after one: both improve job completion, but only a witnessed stall followed by success supports a recovery claim.

All methods receive the same observation interface and total time. The actor gets noisy target information, robot proprioception and force feedback; simulator truth is reserved for training critics and evaluation. Audit frame transforms and action clamping as well as the observation vector. A supposedly hidden true target can leak through either.

## Weeks 1-2: a trustworthy task and strong baselines

**Week 1 deliverable:** a small project-owned adapter around pinned upstream FORGE, a complete-job evaluator and replayable fault cases. Keep upstream source unchanged. Read only the relevant FORGE/Factory code, not the retired project.

1. Reproduce the short smoke and training commands. Check saved weights by loading them. Measure sustained throughput over at least 20 epochs and memory over the whole run; the existing two-epoch pilot is not a capacity estimate.
2. Held-part gravity decision completed: use physical gravity for the primary industrial study. Matched historical trials and current contact-aware holding checks passed; preserve the gravity-disabled upstream reference. Robot gravity remains disabled as idealized compensation. This resolves the development choice, not hardware fidelity or every future fault.
3. Derive feasible fault ranges from the peg/hole dimensions, controller action limits and scripted withdrawal tests. The pinned peg has roughly 57 micrometres of radial clearance; plausible pose errors are much larger. Validate each generated case for collision-free initialization, retained grasp and an actionable retreat. Do not widen geometry to obtain a score.
4. Implement a job record independent of upstream reward: method/checkpoint, seed, fault, time, contact force, success, stall, retry, abort and reset count. Preserve the upstream success predicate and report it alongside the project outcome. Require 0.5 seconds of continuous seated state for project completion; apply the same rule to every arm.
5. Freeze the job deadline and the simulated force budget from development trials, before held-out evaluation. Start the development protocol at 30 seconds and 20 N, with the force budget explicitly an experimental limit, not a hardware damage threshold. Test sensing, filtering and abort latency. An abort is a failed job; reward penalties are not hard safety enforcement. If revised during development, preserve both settings and the reason.
6. Specify fault bins, training support, held-out combinations, stall detection and retry limits in `configs/study.json`. Test that evaluation seeds and cases cannot enter training. Freeze a versioned protocol with source and config hashes. No later threshold changes to improve a result.

**Three early validity risks (required before the learning comparison):**

- **Stall gaming:** never define progress by velocity magnitude alone. Detector v2 tracks new median-filtered insertion depth and tolerates brief load/action gaps. Oscillation tests must pass. It has no reward penalty; deadline and complete-job failures remain the primary endpoints. Compare its labels against recorded contact and motion before freezing thresholds. A wrist-load proxy cannot establish a contact jam. The original seven development stalls all withdrew clear of the fixture. One recorded actor-only recovery now completes reinsertion; numeric recoverable fault support remains open.
- **Faults must produce recoverable contact failures:** record filtered peg-to-fixture PhysX contact separately from wrist load. Inspect the approach, sustained contact without new depth, retained grasp and a feasible robot-driven withdrawal. Report free-space misses separately. The contact witness is evaluator-only privileged information, unavailable to the actor. Do not call a contact or prevention episode a recovered jam.
- **Reward must permit backing out:** source inspection found proximity/engagement rewards, not a literal signed downward-progress penalty. Withdrawal can still lose immediate reward. Compare full discounted returns for matched, physically successful retract/reinsert trajectories and persistent stalls, including force/action terms and the same deadline. Do not change shaping based only on an isolated upward step; any justified shared reward correction retains the official baseline and reruns both learning arms.

**Week 2 deliverable:** a trained standard reference, scripted retract/retry and one uniform-fault pilot. Run independent seeds, record all outcomes, and inspect unsuccessful episodes. Establish that nominal insertion can work and the fault set contains difficult but solvable cases. A missed insertion that can never be undone under the action limits is a task-design defect, not a learning challenge.

**Next block acceptance:** the tensorized finite-job training adapter matches the CPU evaluator on terminal outcomes, dwell, stalls, force/grasp precedence and reward accounting; a bounded simulator check verifies instantiated actor/critic information paths and finite-job bootstrapping. Measure memory and sustained throughput with one GPU queue before selecting campaign batch size. Resolve the remaining development support and physics checks, then freeze the protocol before long training. Keep the raw 20 N abort and final-test cases closed; the temporal diagnostic and registered physics-refinement test are specified in evidence/physics_and_throughput_design.json and configs/study.json. Do not extend scripted-controller tuning.

**Day 14 decision:** if the environment and evaluator pass, proceed to the learning comparison. If an implementation fault remains, spend at most two work blocks fixing that specific fault, retaining all affected evidence. If learning is still weak on the unchanged upstream task, report the baseline reproduction limitation, finish the benchmark and demo with measured baseline behavior, and keep the research question. Do not start a different project or run another month of unbounded training.

## Weeks 3-4: the first answer and a useful demo

**Week 3:** implement the adaptive fault sampler. Compare uniform and adaptive training with identical seeds, network, reward, nominal share, action bounds and episode budget. Train each of three seeds as one continuing run, saving around 1M, 3M and 10M transitions. Count all pretraining, fault-mining and curriculum-probe transitions. No free auxiliary rollouts for the proposed method. A shared initialization must be identical for both arms, with its cost stated.

**Week 4:** finish the peg comparison against fixed difficulty curriculum and retract/retry. Evaluate a checkpoint fixed by the training budget, never the one that looks best on the test set. Pair initial conditions and report each training seed separately. Produce a first result table, reliability-versus-training plot and recorded failure/recovery comparison.

Predeclared engineering target: halve the unfinished-job rate versus uniform training on held-out faults at equal training cost, with no more than two percentage points of nominal-success loss. This target is a practical ambition, not a promised result. If the baseline has near-zero failures, report saturation; do not make the held-out test harder after looking at it. If the target is missed, the paper reports the measured effect and the limits of recovery training.

At least 200 held-out jobs per training seed and task for the final comparison, stratified by the frozen fault families, plus 100 nominal jobs. Use the same cases across arms. Report paired differences, uncertainty and variation across training seeds; thousands of episodes from one trained network do not replace independent training seeds. Use the development set for tuning. Open the final test set once the method and training budget are frozen.

## Weeks 5-6: generality and the reason for the result

Apply the same protocol to the installed FORGE gear-meshing task. Reuse the method, not a peg-specific success geometry. Verify yaw action range and geometry before training. Train task-specific policies for the main comparison; do not call this zero-shot transfer. A bounded transfer experiment is optional after the main two-task result.

Run the fixed easy-to-hard curriculum on both tasks and one targeted ablation of the winning explanation: remove adaptive prioritization or shuffle bin priorities while preserving the nominal share and total budget. Keep unsuccessful runs. State whether any improvement comes from preventing initial misses, recovering more often after a stall, or simply spending more simulated time.

If the method only works on pegs, that is the result. Do not substitute a friendly task and imply broad generality. If compute is tight, reduce extra ablations before reducing independent seeds or removing the second task; document any final budget reduction equally across arms before their test evaluation.

## Weeks 7-8: evidence, manuscript and website

Freeze code and repeat the final selected evaluations from a clean checkout with reachable, hashed checkpoints. Package commands, environment lock, per-job records and plots. Raw videos and weights can be local during development; any public reproducibility claim must identify a downloadable checkpoint and its license.

Write the manuscript around the actual result: problem, prior art, exact comparison, scaling curves, two tasks, failure analysis and simulation limits. A negative method result can support a useful technical report or workshop submission if it answers the question carefully; it does not automatically justify a research publication. Choose a currently open, relevant venue only after reviewing the result and live submission requirements.

Build a static website replay: choose a held-out fault, compare standard policy / retry / learned recovery, and watch force, time and outcome. The footage must come from saved evaluations. Include complete failures and aggregate results. A hosted live GPU, elaborate dashboard and new perception stack are outside scope.

**Completion:** a person can explain the problem in two sentences, run the baseline, inspect an honest demo, reproduce the main comparison and read a manuscript that says what training improved and what it did not.

## Execution without owner micromanagement

At the start of a work block, read AGENTS.md and this current-state table, take the single next action and finish the smallest verifiable deliverable. Budget at most 30 minutes for an individual incidental tooling issue; use a documented equivalent fallback or record a concrete blocker and continue independent work. Scientific validity issues must be fixed or disclosed, never bypassed to make progress look green.

Reserve the last 30 minutes of each five-hour block for checking artifacts, saving progress and updating this file. Agents make implementation choices within this plan. Ask the owner only if an essential external resource or a change to the high-level goal is required. Routine failures, seed selection, script fixes and scheduled evaluations do not require guidance.

Use one serial supervisor and unique run IDs, not multiple shells sleeping on log files. Default to one GPU job. Do not inherit the old project's concurrency measurements: this model and physics workload differ. Keep enough system RAM and disk for evaluation and checkpoints. Measure progress from elapsed simulation steps, process CPU time and artifacts, not silence in a log or a single GPU-utilization number.

At the pilot's approximate 200 transitions/second, 10M transitions would take about 14 hours before other overhead. This is arithmetic from a short pilot, not a schedule commitment. Twelve 10M runs for the two main arms, three seeds and two tasks imply roughly 167 hours before baselines, evaluation and overhead. Measure sustained speed in week one, then set a total campaign budget; reserve at least 25% for evaluation and reporting. Keep the 1M/3M/10M axis unless that budget requires a documented common reduction. A 30M extension is optional only after the main study and if the curves warrant it.

Start a fresh session after a completed milestone, using this file rather than copying the old conversation. Give each block one acceptance test and a run budget. Manual inspection or CAD is optional and justified only by a concrete obstacle it can resolve faster than automation; no manual step is required now.

After each block update only the table above and the next action; place detailed run data in JSON artifacts. Do not append session diaries, create another roadmap or restore the archived robot project into the active tree.
