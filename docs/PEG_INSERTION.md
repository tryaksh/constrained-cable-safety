# Retired peg-insertion campaign

This campaign studied recovery after a failed insertion using a Franka Panda
robot in Isaac Lab's FORGE environment. It closed on 2026-09-10 because the test
stopped producing the recoverable failures required by its design. The candidate
training method was **never trained and never evaluated**.

The evidence index identifies 66 `peg` records, separate from the cable studies.
These results must not be presented as cable results.

## Task and comparison

The robot inserts a cylindrical peg into a hole with 57 µm clearance. The
registered question was whether training on physically generated failed
insertions improves recovery compared with uniform-fault training at equal
simulator cost.

Both arms would use the same policy, observations, faults, reward and PPO
training method. The candidate would spend half its fault training on attempts
that follow a scripted four-second failed insertion. That prefix would receive
no learning updates, but its simulator cost would still count.

A valid starting failure had to be a witnessed contact stall: the peg still
held against the hole, with the job active. The force-abort limit was 20 N.
[Registered design](../configs/recovery_teaching_registration_v1.json).

## Why the campaign stopped

At 120 Hz physics, 17 of 28 development cases produced the required stall.
Refining the physics largely replaced those stalls with force aborts:

| Physics rate | Force aborts, 120 Hz servo | Force aborts, 480 Hz servo | 480 Hz servo plus 20 mm/s target limit |
| --- | --- | --- | --- |
| 120 Hz | 1 of 28 | Not run | Not run |
| 240 Hz | 13 of 28 | Not run | Not run |
| 480 Hz | 26 of 28 | 27 of 28 | 25 of 28 |
| 960 Hz | 27 of 28 | 27 of 28 | 26 of 28 |

The two corrections were registered before execution. Neither restored the
cohort. The final pair left only 2 and 1 active cases against a required minimum
of 8, triggering the registered stopping rule.
[Executed decision](../evidence/research_cycle_decision_v1.json) ·
[Final comparison](../evidence/approach_slew_comparison_v1.json) ·
[Verification](../evidence/research_cycle_verification_v1.json).

![Physics refinement and training throughput](../evidence/research_cycle_v1.png)

The result establishes sensitivity to physics resolution. It does not establish
which resolution is correct, or whether the untested training method would work.
The exact contact mechanism remains unresolved.
[Figure record](../evidence/research_cycle_figure_v1.json).

## Other findings

| Finding | Evidence and scope |
| --- | --- |
| A baseline policy could perform the task. | Uniform-fault PPO training completed **81 of 84** development jobs: 12 clean and 69 faulted. It used 10.33 million charged transitions in 111.5 minutes. One training seed and three development seeds; not a final test. [Record](../evidence/uniform_unclipped_v4.json) |
| Learned recovery did not outperform scripted retry on completion. | Both completed 13 of the same 17 stalled jobs; continuing to push completed 0. Two further seeds gave 30 of 37 for the learned policy, 31 of 37 for retry and 1 of 37 for continuing. The learned policy was about a third faster on average. [Record](../evidence/post_stall_confirmation_v2_verified.json) |
| The original recovery gate stayed failed. | It required at least 5 mm withdrawal. The learned policy instead moved laterally, with under 1.1 mm lift, so it scored zero withdrawal recoveries. A separate mechanism-neutral endpoint was registered later; the original definition was not changed. [Campaign record](../evidence/research_cycle_decision_v1.json) |
| More parallel environments improved throughput. | 2,048 environments versus 1,024 delivered 29.1% more useful samples/s and 38.6% more charged transitions/s, using 6,499 MiB GPU memory. [Record](../evidence/training_capacity_v2.json) |
| Removing value clipping improved critic fitting. | At equal optimiser work, fit error fell from 222.58 to 10.43. [Record](../evidence/critic_fit_v1.json) |

One charged transition means eight native physics steps. The campaign spent
about 27.9 million charged transitions in total.
[Cost ledger](../evidence/research_cycle_decision_v1.json).

## Reproduction limits

- About 865 MB of raw artifacts remain untracked at
  `D:/6axis-space-robotics/artifacts/`. The evidence keeps hashes, not backups.
- Ten older reports were produced from uncommitted code and have no recoverable
  exact source binding. They remain marked in the records.
- Training code and probe scripts are preserved in the orbital repository's
  `archive/assembly-recovery-training` tag. See [REPO_MAP.md](REPO_MAP.md).
- The contribution review found related published work and did not support
  algorithmic novelty. [Review](../evidence/contribution_review_v1.json).

The original project descriptions remain in
[readme_peg_history_v1.json](../evidence/readme_peg_history_v1.json) and
[roadmap_history_v1.json](../evidence/roadmap_history_v1.json).
