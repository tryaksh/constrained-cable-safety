# Repository map

This repository contains the constrained-cable studies, their reusable tools,
and the records of a retired peg-insertion campaign. The related
[orbital-robotic-servicing-lab](https://github.com/tryaksh/orbital-robotic-servicing-lab)
repository covers spacecraft rack servicing in zero gravity.

## Current structure

`main` is the maintained branch. It contains the four cable studies (v3–v6),
the safety filter, Recovery Decision Inspector, simulator workbench, five-clip
cell and peg evidence. The remote is
`https://github.com/tryaksh/constrained-cable-safety.git`.

| Location | Contents |
| --- | --- |
| `src/assembly_recovery/` | Simulation, control, scoring and inspector API |
| `scripts/` | Study runners, verification tools, inspector CLI and renderers |
| `configs/` | Frozen study contracts and scene definitions |
| `evidence/` | Scoped results, including failed and inconclusive studies |
| `artifacts/cell/`, `artifacts/showcase/` | Committed stage records; generated media stay ignored |
| `tests/` | CPU tests for software, provenance and documented findings |
| `docs/handover/` | Historical handovers, unchanged after their dates |

The portfolio video and description are delivered separately at
`D:/constrained-cable-portfolio/` and are not repository content. There is no
portfolio website in this project.

## History and archive

The cable repository was extracted from the orbital repository's
`research/assembly-recovery-training` branch. Its history was filtered, so commit
hashes differ; the repositories share only the empty initial commit. Treat them
as separate projects rather than branches to merge.

The original recovery branch was preserved as
`archive/assembly-recovery-training` before deletion. Its 623 commits include
the peg training code and probe scripts:

```text
git clone https://github.com/tryaksh/orbital-robotic-servicing-lab.git
git checkout archive/assembly-recovery-training
```

On 2026-09-13, the cable repository received 65 peg evidence records, 41 missing
configs, 19 existing figures and two documentation archives. Paths were kept
because records refer to them and often hash their contents.

[`evidence/INDEX.json`](../evidence/INDEX.json) lists 99 records: 30 `cable`,
66 `peg` and 3 `shared`. The 65 imported peg records supplement one already
present. Campaign labels are assigned by
[`scripts/index_evidence.py`](../scripts/index_evidence.py). A peg result is
never a cable result.

The final approach-slew comparison was recovered from a local raw-output
directory as [approach_slew_comparison_v1.json](../evidence/approach_slew_comparison_v1.json).
Its bytes match the hash in the executed decision record. This closes the
question left open in the earlier design record: the comparison ran and failed
its registered support floor.

## What remains elsewhere

About 865 MB of peg trajectories, physics samples and checkpoints remain
untracked at `D:/6axis-space-robotics/artifacts/`. Evidence records retain their
hashes, but a clone does not include those files. The peg implementation is in
the archive tag, not this repository.

Ten early cable probe/review scripts were restored from that archive. Four older
scripts named in v2-era records could not be recovered: `add_cable_plugin.py`,
`load_aic_world.py`, `sim_comparison_test.py` and `view_scene.py`. The records
remain available; their exact source does not.

Read [README.md](../README.md) for the project,
[ROADMAP.md](../ROADMAP.md) for verified limits and deferred work, and
[PEG_INSERTION.md](PEG_INSERTION.md) for the retired campaign.
