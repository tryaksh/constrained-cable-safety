# Roadmap: cable recovery, from physical baseline to a controlled result

**Active scope:** industrial cable handling and connector insertion. Establish a credible physical baseline, measure remaining failures and test the smallest justified recovery improvement. The preserved Franka/FORGE peg study is historical evidence, not a restriction on this cable cycle.

The owner's 2026-09-10 mandate supersedes the fixed five-hour/single-action limits and the mandatory adaptive-sampling question. Agents own scientific and engineering choices and execute a complete, bounded research cycle. Scientific validity, preservation of negative evidence, source provenance, fair cost and closed final tests remain required. Earlier plans below are historical designs until explicitly replaced by a versioned registration.

## Closed cable cycle (2026-09-10)

**Decision: revise the physical connection-retention model.** The authorized cycle produced runnable native AIC code, a controlled scripted seating comparison and a matched retention experiment. The current rigid SC asset releases under 0.5/2 N net extraction at both tested resolutions, so it cannot support claims of completed retained connections. Learning the proposed joint connector/cable recovery mechanism is not yet justified.

| Item | Verified state |
| --- | --- |
| Starting source | Research branch at `4040de31c903ea085c992cada566f9e18ed562a2`; exact dirty run-time sources and meshes archived before each simulator launch |
| Public toolkit | Intrinsic AIC `e9145480c945f2afc3741f355233f44082cc3b06`; seven UR5e collision STLs match public source at `ef93882e17d8aa628837915da4b83208fe5e519a`; BSD/Apache license scope recorded |
| Native environment | Isolated MuJoCo 3.3.7/Python 3.11.15; setup/check command verifies source, assets and package pins; Gazebo/ROS official evaluation not executed |
| Asset/contact controls | Current SC SDF retains all 15 collision primitives per plug/port. Force-actuated fixture controls pass; source MuJoCo contact exclusion and older embedded plug geometry are not used as insertion truth. |
| Native robot | Finite-torque UR5e seats/retracts with a deforming free cable at 0.5/0.25 ms. Three earlier cable initializations abort; all preserved. Cable contact remains timestep-sensitive. Use 0.25 ms only for bounded engineering, not a convergence claim. |
| Scripted comparison | Same six deterministic development cases: force-guided/precontact-compensated baseline seats 6/6; continuation seats 3/6, with three witnessed contact-stall timeouts. Strong baseline used zero retries and had no witnessed recoveries. |
| Retention | All six axial fixtures first seat/dwell. Zero net pull holds for 2 s; 0.5/2 N unseat in about 12/6 ms with zero opposing extraction contact at both 0.25/0.125 ms. This is a rigid-model limit, not a hardware specification. |
| Accounting | 12 launcher attempts, 10 processes with physical trials, one worker compile failure and one pre-worker encoding failure. 37 physical trials; 1,185,841 explicit native steps, including 222,637 initialization steps; 595.203 s summed launcher wall time. |
| Learning / proposed extension | No ordinary, recovery-focused, recurrent or candidate learning. No prior-clip/connection, distal-snag or unseen-connector comparison. Conditional extension registration and CPU geometry/accounting helpers remain unexecuted. |
| Observation / hardware scope | Full simulated poses and exact-model bias feedforward; ideal fixed robot grasp. No camera perception, pickup, released physical connection, electrical/optical functionality or hardware transfer. |
| Contribution | Reproducible native integration, a competent local scripted baseline, and a specific physical-retention limit. No learned benefit or algorithmic novelty. |
| Release | Three maintained documents, pinned setup/commands, immutable negative evidence, plots and CPU/source-only verification in `evidence/cable_cycle_verification_v1.json` |
| Single next action | Specify and validate a physically justified passive connection-retention/load model (or select an asset that already supports it), with seated/unseated/release controls. Then validate required-clip and clearable-post support before any learned recovery comparison. |

The [decision](evidence/cable_cycle_decision_v1.json), [baseline](evidence/cable_baseline_v2.json), [retention control](evidence/cable_retention_v1.json), and [native validation](evidence/cable_robot_validation_v1.json) contain denominators, costs, source hashes and limitations. The candidate effect remains unknown. Do not turn held seating or a touch-triggered freeze into a retained-connection claim. Preserve the original asset/model results when revising the task. The peg campaign below remains closed independently.

## Preserved peg state

| Item | Verified state |
| --- | --- |
| Audit and source archive | Completed; original commit `1b969f6db01aeac226667db4759b7603b3f663a0`, all original refs in verified local bundle |
| Old active project | Retired; 629 original tracked files removed; all 653 original weights rehashed and verified unchanged |
| Clean repository | Exactly three Markdown documents; historical index excluded from routine searches |
| Simulator | Upstream peg smoke passed: 4 environments, 16 steps; no recovery claim |
| Training | Fresh value-unclipped v4 completed 22 cohorts and 10,326,272 charged transitions in 111.5 minutes. All 22 model/optimizer checkpoints are finite; exact source and artifact hashes verified. Final deterministic 120 Hz development evaluation completed 81/84 jobs: 12/12 nominal and 69/72 fault cases, with two force aborts and one deadline. Prior interrupted v3/v4 attempts remain preserved. |
| Verification | Ruff and 299 CPU tests pass, including 299 tests in an isolated source checkout without ignored runs, weights or Isaac Lab. Corrected per-run and paired source/action/timing/RNG/native-replay checks pass. Three CPU checker failures remain preserved with versioned corrections and zero simulator reruns. |
| Study implementation | Separate mechanism-neutral `post_stall_completion_v1` preregistered and confirmed on development seeds 10071/10072. It requires actual contact stall before the fixed four-second handoff, later completed dwell, retained grasp and no forbidden events. Whole-job and conditional denominators remain separate. Original five-millimetre withdrawal metric and failed competence gate remain frozen. |
| Physics and job accounting | Physical held-part gravity; native raw 20 N wrist abort, retained grasp, 30 s deadline and 0.5 s seating dwell retained. The v3 worker initializes both resolutions at 120 Hz, then passes explicit 120/240 Hz dt to the installed PhysX simulate/fetch calls with 15 Hz policy and 120 Hz servo/sensors. Native dt, contact impulse conversion and torque holds pass; no within-job reset, pose write or attachment change. Native fine work, absorbing slots and every failed probe are charged. |
| Learned physics result | On all 28 seed-10071 development cases, direct learned / learned after the fixed prefix / unchanged retry complete 27/28, 25/28, 24/28 at 120 Hz versus 20/28, 11/28, 12/28 at 240 Hz. Prefix force aborts rise from 1 to 13 before controller handoff. The stalled active cohort shrinks from 17 to five: learned/retry complete 16/17 and 16/17 at 120 Hz versus 3/5 and 2/5 at 240 Hz; on the same five cases, coarse arms each complete 5/5. Learned withdrawal remains zero; the original competence gate remains failed. Two timesteps establish sensitivity, not convergence. |
| Remaining validation | The registered fixed-prefix recovery-teaching comparison is rejected under the current task. No tested480/960 Hz condition leaves an active witnessed contact stall at handoff. The final common-reference condition also fails its censored-impulse and active-request support gates. No candidate campaign, new full-job comparison, final test or gear run is justified by this cycle. |
| Research contribution | Chosen question: does explicit physical failure exposure improve recovery at equal simulator cost? Candidate worker/masks are CPU-tested but untrained. Current contribution is bounded engineering evidence that this fixed-prefix assay loses its target cohort under refinement, plus measured training capacity. Algorithmic novelty and a candidate benefit remain unestablished. |
| Scientific evidence | Primary learned development insertion remains 81/84 with no witnessed stalls. On the two additional fixed-prefix seeds, learned/retry/continue complete 47/56, 47/56 and 11/56 whole jobs; among the same 37 stalled jobs active at handoff they complete 30/37, 31/37 and 1/37. Each arm includes six prefix-script completions and one prefix force abort. Learned withdrawal recoveries remain zero; no reliability advantage over retry or curriculum effect is established. Prior seed 10070 stays separate (13/17, 13/17, 0/17 conditional). |
| Resource allocation | Ten simulator processes completed: two PPO capacity runs and eight scripted prefixes. New charge 2,883,652 reference transitions; cumulative tracked lower bound 27,878,867.25. All initialization and absorbing work counted; corrected CPU reviews add zero. Peak GPU 6,499 MiB; all owned simulator processes stopped. No candidate training or final-test use. |
| Website / manuscript | A standalone verified comparison figure and technical result are released through README and evidence/research_cycle_v1.png/.pdf. No website or algorithmic-superiority manuscript. Earlier learned motion/withdrawal evidence remains unchanged. |
| Execution authorization | The owner authorizes complete autonomous research cycles, method revision within Franka/FORGE assembly recovery, parallel independent agents and safe non-force pushes to this existing research branch. Main stays unchanged. 2,048 was tested and earns adoption on the measured runtime; 4,096 was not needed. |
| Prior physics handoff | Completed: original native120/240/480/960 Hz prefixes, matched 480 Hz-feedback pair and final common 20 mm/s-reference pair. All cases and raw 20 N aborts retained. The final pair leaves 2/1 active requests and zero active witnessed contact stalls. |
| Current autonomous cycle | Closed with reject_premise in evidence/research_cycle_decision_v1.json. The final correction did not earn full-job validation or a learning campaign. The candidate effect remains unknown; ordinary/adaptive/retry labels stay distinct. |
| Single next action | Independently specify a new physical/load model and retained-stall generation protocol before reopening learned comparisons. Preserve this rejected assay, its raw 20 N endpoints and all results. Do not queue more prefix tuning, candidate training or final tests under the current definition. |

## Closed research cycle (2026-09-10)

**Registered question:** at equal total charged simulator work, does explicit exposure to physically generated failed insertion attempts improve whole-job and witnessed post-stall reliability over ordinary uniform-fault training?

**Decision: reject the present comparison premise.** The original 120 Hz prefix has 17 active witnessed stalls; at 240 Hz it has five; every480/960 Hz condition has zero. The common 20 mm/s reference produces 25/26 force aborts among 28 requests and leaves only 2/1 active requests. It fails the registered support floor and terminal-censored impulse margin. The final pair does pass its outcome-count and wrist-peak margins, so the impulse statistic must not be presented as an uncensored convergence proof.

The candidate implementation keeps the same policy, observations, fault support and reward, excluding scripted actions/rewards from PPO while charging their physical work. It was not trained. The prior adaptive sampler remains an unexecuted design. The learned ordinary model's prior120Hz development results remain valid only within their stated scope.

**Executed efficiency result:** two full PPO cohorts at each of 1,024 and 2,048. The 2,048 setting improves startup-inclusive active throughput by 29.1% and charged throughput by 38.6%, with 6,499 MiB peak GPU use. Adopt it for the measured runtime; reprofile after a material task change. No simple all-terminal tail can be removed from these cohorts.

The [decision record](evidence/research_cycle_decision_v1.json) preserves controller labels, source archives, all costs, saved models, checker corrections and limitations. The [comparison figure](evidence/research_cycle_v1.pdf) is the concise technical result. No additional GPU work is queued for this rejected assay.

## Earlier adaptive experiment (preserved design, no longer mandatory)

**Question:** under a fixed physical task and equal total charged simulator cost, does selecting fault practice from recent job outcomes reduce unfinished jobs compared with uniform and calibrated fixed easy-to-hard training, and does it improve prevention, completion after a witnessed contact stall, or both? Compare reliability and time with unchanged scripted retry. This is an unanswered engineering question for this benchmark, not a claim that adaptive assembly recovery is new.

A job begins with a valid grasped part above the fixture and ends in settled insertion, a declared abort or a deadline. A miss or stall must be resolved with robot actions during that same job. Episode initialization between jobs is allowed. Simulator reset, pose writes, changing a joint constraint or regrasping by teleportation during a job counts as an unfinished job. This is autonomous recovery within an assembly job, not reset-free training or a complete factory cell.

Start with lateral fixture-pose bias, approach offset and friction variation. They can generate recoverable misses and stalls without inventing a broken part. All faults are sampled at job initialization and act through the same interface in every arm. Reserve unseen combinations and severity ranges for evaluation. Gear assembly can add a yaw error. Do not add roll/pitch faults while those action axes are disabled upstream. Do not inject arbitrary penetrations or restore incomplete PhysX state snapshots.

**Comparison arms:** learning arms share architecture, reward, fault support, nominal share and job horizon. Scripted retry is a zero-training practical comparator with its development and evaluation costs reported; do not pad it with fictitious training.

| Arm | Purpose |
| --- | --- |
| Standard FORGE training | Reference implementation; it already has force-aware exploration, so never label it incapable of recovery by design |
| Standard policy + bounded retract/retry | Strong practical baseline using the same noisy observations and contact signal; retry time counts toward the same job deadline |
| Uniform fault training | Main compute-matched learning baseline: fixed sampling across the declared fault support |
| Adaptive fault training | Candidate: 25% nominal practice; 75% prioritized toward fault bins with intermediate success and recent learning progress |
| Fixed difficulty curriculum | Established easy-to-hard baseline, same fault support and compute; prevents claiming that any curriculum improvement is new |

All three learning arms retain 25% nominal practice. The adaptive arm uses the established intermediate-success heuristic `p * (1 - p)` with a nonzero sampling floor, updated only from its own finalized training jobs. It does not estimate physical recoverability. The fixed arm follows a predeclared schedule calibrated from existing scripted development evidence; it does not react to new policy outcomes. Within-bin fault support and reward stay identical. Learning progress and alternative adaptive methods are separate, attributed comparisons, never invisible additions after seeing results.

The closest direct overlap is [Yu and Lee (2026)](https://scholarx.skku.edu/item/822cdd01-3c7c-4237-afdd-43cc4e05bbb6). Its institutional abstract describes adaptive difficulty selection for recovery-oriented peg insertion against static/no-curriculum baselines; exact evaluation details require the unavailable full text. [Beltran-Hernandez et al. (2022)](https://arxiv.org/html/2204.12844v2) already evaluate fixed/adaptive curricula and sampling strategies for industrial insertion, including force-triggered termination. IndustReal, AutoMate, reverse curricula and learning-progress/level-selection methods further limit novelty claims. Changing the simulator, optimizer or score is insufficient.

The proposed contribution is an executable engineering decision: when does adaptive practice earn its cost under complete-job accounting, a witnessed-failure assay and physics refinement? Existing evidence does not yet establish that benefit. A useful negative result must identify a reproducible operating boundary; otherwise finish a transparent technical report without asserting a novel paper contribution. The detailed comparison and evidence limits are in `evidence/contribution_review_v1.json`.

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

**Next block acceptance:** a versioned learned/retry refinement path has a documented 120 Hz compatibility result and a bounded, source-captured 120/240 Hz comparison with matched external timing, noise and physical parameters. Native force/grasp/dwell replay and all-request denominators must pass; report initialization differences and any material outcome sensitivity. Two resolutions do not prove convergence. Preserve the original failed withdrawal gate and separate post-stall endpoint. No additional controller tuning or training campaign is permitted merely because the primary insertion policy is competent.

**Day 14 decision:** if the environment and evaluator pass, proceed to the learning comparison. If an implementation fault remains, spend at most two work blocks fixing that specific fault, retaining all affected evidence. If learning is still weak on the unchanged upstream task, report the baseline reproduction limitation, finish the benchmark and demo with measured baseline behavior, and keep the research question. Do not start a different project or run another month of unbounded training.

## Weeks 3-4: the first answer and a useful demo

**Week 3:** complete learned-policy physics validation and the common sampler/worker contract before further substantial training. The initial fair screen in `configs/contribution_screen_v1.json` is peg only: uniform, calibrated fixed easy-to-hard and adaptive selection, each with training seeds 170/271/372 and six 1024-environment cohorts (2,816,256 expected charged transitions per run). All nine runs start fresh under one new registration. Preserve the existing 10M policy as development evidence. Run paired direct-job and fixed-prefix evaluations and unchanged scripted retry/continued-insertion controls. The design is not launch authorization; required source, physics, cost and evaluation checks remain.

**Week 4:** use the registered development spending rule to decide whether a full comparison is worth funding. The initial screen costs 25,346,304 training plus 770,070 expected evaluation transitions, with physics/integration probes separately charged. It is not a final-test result or a statistical guarantee. If there is no useful signal, retain the negative result and stop routine sampler tuning. If all policies are weak, report insufficient budget rather than superiority. If direct insertion saturates, use the predeclared earlier budget or report saturation; do not make test faults harder.

Only a justified continuation receives a new common registration for the 1M/3M/10M curve. Verify complete optimizer/RNG/sampler continuation or account for fresh matched runs; never substitute old partial weights. The full study retains three training seeds, the fixed curriculum and retry, a competent upstream FORGE reference, gear, and a mechanism ablation. A claim of algorithmic superiority would also require a strong established adaptive comparator and adequate primary implementation details; the three-arm screen cannot establish it.

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

Read AGENTS.md and the current-state table, then carry a registered research cycle through its acceptance or rejection decision. The owner superseded single-artifact, fresh-session and five-hour execution limits. Revise the method or precise research question when evidence warrants, keeping Franka/FORGE assembly recovery as the project scope.

Use measured throughput to set a bounded campaign budget and reserve time for evaluation, artifact verification and handoff. The current original-runtime measurement is 2,306 charged reference transitions/s and 595 active samples/s at 2,048 environments, including startup. This is a capacity profile, not a throughput promise for a changed physical task or a mature policy.

Use one serial GPU queue and unique run IDs. Capture source, configuration, environment, seeds, commands and checkpoint hashes before launch; preserve exact archives for development sources. Do not edit executing scripts or use sleeping-shell supervisors. Keep enough RAM and time for evaluation, and preserve failed jobs, processes and checks.

Agents make ordinary scientific and implementation choices. Ask only for an essential missing external resource or an unavoidable high-level scope decision. Manual inspection or CAD is conditional on a concrete measured obstacle; it is not a gate for routine progress.

Update the current table and next action when the cycle closes. Put detailed evidence and decisions in versioned JSON, retaining previous failed records. Report actual controllers, work, costs, failures, saved models and the pushed commit. Maintain only these three Markdown documents.
