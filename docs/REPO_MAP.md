# Repository map

What this repository holds, what its branches are, and where the work that is
*not* here went. If you are an agent or a person picking this up cold, read this
before anything except [README.md](../README.md).

Measured on 2026-09-13 with `git ls-remote`, `git merge-base` and `git rev-list`.
Nothing below is assumed.

---

## The two repositories, and which is which

There are two, and they used to be tangled together. They are not any more.

| Repository | Question it answers |
| --- | --- |
| **constrained-cable-safety** (this one) | An assembly attempt has failed and the robot must back off and try again. What does a safety check need to know before it makes that retreat, and does the check survive being used repeatedly and on hardware it was not tuned for? |
| [**orbital-robotic-servicing-lab**](https://github.com/tryaksh/orbital-robotic-servicing-lab) | Can a robot service a modular spacecraft rack in zero gravity, which constraint stops it, and do skills that pass on their own survive being chained together? |

Neither repository now contains the other's subject matter. If you find cable or
peg-insertion work in the orbital repository, or spacecraft racks here, it is a
mistake and should be reported.

---

## Branches here

| Branch | State | What is on it |
| --- | --- | --- |
| `main` | **alive — the only branch** | Everything. Four pre-registered studies (v3–v6), the safety layer, the workbench, the five-clip rig, and the retired peg-insertion campaign's records. |

One branch is deliberate. There is no work in progress, no parallel line, and
nothing half-merged. If a branch appears here later it should be short-lived and
its name should say what it is for.

The remote is `https://github.com/tryaksh/constrained-cable-safety.git`.

---

## Where this repository came from

This repository was cut out of the orbital repository's
`research/assembly-recovery-training` branch. The two share exactly one commit —
the empty initial commit — and nothing else: the history here was rewritten to
keep only the cable work, so commit hashes do not match between them and no merge
between the two is possible or wanted.

The branch it came from no longer exists. It was tagged
`archive/assembly-recovery-training` in the orbital repository before it was
deleted, so its 588 commits and every file on it stay reachable there:

```
git clone https://github.com/tryaksh/orbital-robotic-servicing-lab.git
git checkout archive/assembly-recovery-training
```

---

## What arrived from that branch on 2026-09-13

The recovery branch carried 116 files under `evidence/` and 49 under `configs/`;
this repository had 35 and 10. Every file it had and this one did not was looked
at, and all of it came across.

| What came over | Count | Why |
| --- | --- | --- |
| **The peg-insertion campaign's records** | 65 records | This is recovery work — an insertion attempt fails and the robot has to try again — so it belongs in the recovery repository. The campaign was closed by rejecting its own premise, which is a real result and is kept as one. [docs/PEG_INSERTION.md](PEG_INSERTION.md) explains it in plain English. |
| **Frozen contracts the records name** | 41 configs | Several records already here named configs that were never carried over, so their evidence links were broken. They are not broken now. |
| **Figures** | 19 files | `.png`, `.pdf`, `.svg` and `.jpg` renderings that records link to by path. Copied so the links resolve rather than regenerated. |
| **Two records that describe both campaigns** | 2 records | Archives of retired README and ROADMAP prose. |

**The paths were kept exactly as they were.** Records reference each other and
their configs by path — `evidence/peg_fault_matrix_v1.json`,
`configs/protocol_v4.json` — and many carry a sha256 hash of the file at that
path. Filing the peg work under a subdirectory would have broken every one of
those references, so peg and cable records sit side by side in `evidence/` and
are told apart by the `campaign` field that
[`evidence/INDEX.json`](../evidence/INDEX.json) gives every entry. The rule that
assigns it is mechanical and is written out in
[`scripts/index_evidence.py`](../scripts/index_evidence.py).

| Campaign | Records | What it is |
| --- | --- | --- |
| `cable` | 31 | The four constrained-cable studies. What this repository is about. |
| `peg` | 65 | The retired peg-insertion campaign. |
| `shared` | 2 | Documentation archives describing both. |

Nothing was deleted from the recovery branch to make this tidy. The branch was
archived whole, under a tag, before anything moved.

### One result was rescued rather than copied

`evidence/approach_slew_design_v1.json` registered a comparison and was recorded
*before* its results existed, which left it reading as an open question. The
results do exist. They were written to
`artifacts/assembly/research_cycle_20260910_r01/approach_slew_comparison_v1.json`
in the orbital working tree — untracked, on one workstation, one disk failure
from gone. That file is now
[`evidence/approach_slew_comparison_v1.json`](../evidence/approach_slew_comparison_v1.json),
byte for byte, and its sha256 matches the hash
[`research_cycle_decision_v1.json`](../evidence/research_cycle_decision_v1.json)
recorded for it. The question that record left open is closed: the comparison ran,
and it failed its registered support floor.

### What did not come over

About **865 MB** of raw run artifacts — trajectories, per-tick physics samples,
checkpoints — that the peg records were derived from. They are too large for a
git repository and they are not results; the records are. They remain untracked
in `D:/6axis-space-robotics/artifacts/` on the workstation that produced them,
and every record carries the sha256 of the artifacts behind it, so they can be
checked but not replaced.

---

## Where to look next

| Need | Read |
| --- | --- |
| What this project is and what it found | [README.md](../README.md) |
| What is closed and what is still open, with prices | [ROADMAP.md](../ROADMAP.md) |
| How to run things, and the rules an agent works under | [AGENTS.md](../AGENTS.md) |
| Which record answers which question | [evidence/INDEX.json](../evidence/INDEX.json) |
| The retired peg campaign | [docs/PEG_INSERTION.md](PEG_INSERTION.md) |
| Past session handovers, kept as history | [docs/handover/](handover/) |
