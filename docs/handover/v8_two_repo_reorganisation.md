# V8 — Reorganise two repositories into two clear projects

**This session does not measure anything new and does not build anything for an
audience.** It reorganises, refactors, finishes what is already finishable,
commits what is uncommitted, and rewrites the documentation. If you find yourself
designing a study or making a web page, you have gone off task.

### What this session must NOT produce

- **No artifacts, no published page, no website, no demo site.** Not as a draft,
  not as a nice-to-have.
- **No new study, no refit, no re-run of a block that is already fitted.**
- **No new figures or videos**, beyond regenerating one that already exists and
  is broken or out of date.

### The end goal this serves, which is somebody else's job

The owner will later write **one page on their portfolio site, a Robotics Lab
page, listing these experiments with their results and demos, concisely, each
with a GitHub link.** They will write it themselves.

Your job is to leave each repository in a state where writing that page is
trivial: one clear objective per repository, branches whose names mean something,
results that are either finished or honestly marked unfinished, and a README
whose first few sentences can be read by someone who has never seen the project.
Nothing that goes on the portfolio page is built here.

Prepared 2026-09-13 from a direct reading of both remotes. Every branch fact
below was measured with `git ls-remote`, `git merge-base` and `git rev-list`, not
assumed.

---

## 1. Why this session exists

Two GitHub repositories currently hold three different research projects between
them, spread over six branches, and there is no way for a newcomer — human or
agent — to tell which branch is what. The owner wants a portfolio page listing
each project with a GitHub link, and right now you cannot write that page
honestly because the links would not point at anything self-describing.

The goal is **two repositories, each with one stated goal, each with branches
whose names mean something.**

---

## 2. What is actually on disk and on the remotes

### `constrained-cable-safety` — clean, finished, one branch

- Remote: `https://github.com/tryaksh/constrained-cable-safety.git`
- Local: `D:/constrained-cable-safety`
- `main` only, at `1c002ae`, local and remote identical, working tree clean.
- Four pre-registered studies (v3–v6), a safety layer, a workbench, a generated
  results page, an Isaac Sim re-render, 267 tests passing in about two seconds.
- **This repo is in good shape. Do not restructure it.** It is the model for what
  the other one should look like.

### `orbital-robotic-servicing-lab` — five branches, three projects, two of them stale

- Remote: `https://github.com/tryaksh/orbital-robotic-servicing-lab.git`
- Local: `D:/6axis-space-robotics`, currently checked out on
  `research/assembly-recovery-training`, **35 commits ahead of its remote**.

| Branch | Commits | Last commit | Relationship to `main` | What it is |
| --- | --- | --- | --- | --- |
| `main` | 301 | 2026-08-25 | — | Orbital Robotic Servicing Lab: zero-g testbed for servicing modular spacecraft. 172 evidence records. Ends on "the skill certifies at 36.77% and scores 0.00% in the chain. The gap is the result." |
| `paper/serviceability-qualification` | 489 | 2026-09-04 | 188 ahead, 0 behind | The current orbital work. 244 evidence records, 536 files. Full chain scores 91.67% (22/24), Wilson [74.2%, 97.7%], and **fails** its unchanged 95% gate. Carries `docs/NEXT_WORK.md`. |
| `research/assembly-recovery-training` | 588 | 2026-09-10 | 287 ahead, 0 behind | The recovery work: peg insertion, the training stack, and the cable studies. Only 72 evidence records — the orbital evidence was already pruned here. This is the parent of `constrained-cable-safety`. |
| `industrial-relocation` | 286 | 2026-08-25 | **0 ahead, 15 behind** | A fully merged ancestor of `main`. Nothing is on it that is not on `main`. |
| `agent/zero-g-blade-swap` | 14 | 2026-08-08 | 6 ahead of a shared base, 293 behind | An early Isaac Lab `ManagerBasedRLEnv` experiment — "Autonomous Server Blade Swap in Zero-G" on a UR10e. Abandoned. |

Local-only branch `research/assembly-recovery` at `5f551d1` is an ancestor of the
training branch (0 ahead, 19 behind). It is a stale pointer.

### `D:/orbital-servicing-paper` - out of scope

A 1,669-line manuscript draft with no git remote. **Leave it alone this
session.** Do not move it, publish it, or regenerate its numbers. Give it one
sentence in the orbital repository's `docs/REPO_MAP.md` as a related document
that lives elsewhere, and go no further.

---

## 3. The target state

Two repositories. Each one states its goal in the first two sentences of its
README, and a stranger can tell within thirty seconds whether it is the one they
want.

**Repository A — space robotics.** Keep the name
`orbital-robotic-servicing-lab`. Its goal: *can a robot service a modular
spacecraft rack in zero gravity, which constraint stops it, and do isolated
skills survive being chained together?* It keeps `main` and the
serviceability qualification work.

**Repository B — recovery.** The `constrained-cable-safety` repository, possibly
renamed, or a new repository if a rename loses too much. Its goal: *when an
assembly attempt fails and the robot has to back off and try again, what does a
safety check need to know, and does it survive being used repeatedly?* The peg
insertion study belongs here, not in the space repository: it is a recovery
study, and the owner is right about that.

The peg work is currently mixed into `research/assembly-recovery-training` along
with the training stack. Decide deliberately whether it moves into repository B
or is retired with a record saying why. Its own evidence already says the
campaign was **closed by rejecting its own premise** —
`research_cycle_decision_v1.json`, `executed_cycle_closed_reject_premise`: the
final correction failed its stability gate and no policy evaluation ever ran.
That is a real, honest, negative result and it is worth keeping. It is not worth
pretending it was a success.

---

## 4. Rules

1. **Plain English everywhere.** `~/.claude/CLAUDE.md` carries the owner's
   writing preference and it applies to every document you touch: natural
   English, explain unfamiliar terms where they first appear, concrete over
   abstract, focused but not cryptic. `constrained-cable-safety/README.md` and
   `ROADMAP.md` are worked examples of the standard being asked for — read them
   before writing anything.
2. **No new measurements.** Do not design a study, refit a safety layer, or
   re-run a block that has already been fitted for nicer numbers.
3. **Never delete a result to tidy up.** Failed runs, rejected candidates and
   losing arms stay, with their scope. Stale *code*, dead *scripts*, orphaned
   *artifacts* and superseded *prose* are what get deleted. If you are unsure
   which a file is, it is a result.
4. **Every claim keeps its evidence link.** A number that loses its record is a
   number you have to delete.
5. **Commit at every stage boundary**, even an ugly one, and push branch by
   branch rather than in one large push at the end.
6. **Do not force-push a shared branch or rewrite published history.** Delete a
   remote branch only after its content is provably reachable from somewhere
   else, and say in the commit where it went.

---

## 5. What to do, in order

### Stage 0 — read and write down what is there

Before touching anything, produce `docs/REPO_MAP.md` in each repository: every
branch, what is on it, its relationship to the others, and one sentence on
whether it is alive, merged or abandoned. This is the artefact that makes the
rest of the session checkable, and it is what a future agent will read first.

Done when: both maps exist and every branch listed in section 2 above appears
with a decision beside it.

### Stage 1 — retire the two dead branches

- `industrial-relocation` is an ancestor of `main`. Confirm with
  `git merge-base --is-ancestor origin/industrial-relocation origin/main`, then
  delete the remote branch and note it in the repo map.
- `agent/zero-g-blade-swap` is 14 commits of an abandoned Isaac Lab experiment.
  Decide: tag it as `archive/zero-g-blade-swap` so it survives, then delete the
  branch. Tagging costs nothing and makes the branch list honest.
- The local-only `research/assembly-recovery` pointer can just go.

Done when: `git ls-remote --heads` on the orbital repo lists three branches, and
every removed one is either an ancestor of a kept branch or reachable by tag.

### Stage 2 — push the 35 unpushed commits

`research/assembly-recovery-training` is 35 commits ahead locally. Those commits
are the cable studies v2–v5 — the same work that was later cut into
`constrained-cable-safety`. Push them so the remote stops lying about what was
done, **before** any reorganisation moves them.

### Stage 3 — separate the two projects

Move the recovery work out of the orbital repository, or confirm that
`constrained-cable-safety` already carries everything worth keeping and retire
the recovery branch with a record pointing at the new home. **Check before you
assume:** the recovery branch has 72 evidence records; `constrained-cable-safety`
has 31. Find out what the other 41 are and decide each one. Some will be peg and
training records that belong in repository B, some will be superseded, and some
may be orbital records that were never pruned.

Done when: no branch in the orbital repository contains cable or peg work, and
nothing worth keeping was dropped on the floor.

### Stage 4 — finish what is already finishable

The owner asked for incomplete results to be completed. Sort every open item
into one of three buckets and act accordingly:

- **Finishable from data already on disk** — an analysis that was never run, a
  figure never regenerated, a record never written. Do these.
- **Needs a short, cheap run to close** — a verification, a control, a reproduction
  check. Do these if they fit in the session, and say what they cost.
- **Needs new collection** — a study that was never sized or launched. **Do not
  start it.** Write down what it would take and leave it in the roadmap as an open
  item with a price.

Known open items to triage:

- The orbital chain scores 91.67% against an unchanged 95% gate. The gate was not
  moved, which is correct. Say so plainly in the README rather than burying it.
- The analytical-versus-simulation validator returns **not qualified**: rack
  clearance and module-section arms mismatch, a +10 mm rail-stop error is
  kinematically feasible but fails in simulation, and capture clearance is
  analytical only.
- `approach_slew_design_v1.json` is a design registered *before* its servo
  results. Either the results exist somewhere and the record should be closed, or
  they do not and it should say so.
- `docs/NEXT_WORK.md` on the paper branch lists what a final claim still needs.
- The robot-side latch geometry is visual only, with an idealised load path.

### Stage 5 — refactor and reorganise

Standard layout, the same in both repositories, because it is the one this work
already half-uses and the one an agent will expect:

```
README.md            what it is and why, in plain English, for a stranger
ROADMAP.md           what is closed, what is open, honestly
AGENTS.md            operating rules and the command sequence
docs/REPO_MAP.md     the branch map from stage 0
docs/handover/       session handovers, kept as history
src/<package>/       importable code
scripts/             entry points, one job each
configs/             frozen contracts
evidence/            immutable records, plus a generated INDEX.json
tests/               fast CPU tests, no simulator
artifacts/           generated output, git-ignored except small stage records
```

While you are in there:

- Delete scripts nothing calls. Check with a repository-wide grep before each
  deletion, not after — `constrained-cable-safety` arrived this session with a
  deleted module that two live scripts still imported, and every simulator entry
  point failed at import while all 250 unit tests passed, because no test
  imported those scripts. **Add a test that imports every script's module** so
  that cannot recur.
- Regenerate `evidence/INDEX.json` in each repository.
- Make sure the test suite runs in seconds on CPU with no simulator, and says how
  many tests there are in the README.

### Stage 6 — rewrite the documentation

For each repository, in this order: what the problem is, why it matters, what was
tried, one comparison table, what was found, what to do about it, how to run it,
what it is not.

Every abbreviation gets explained where it first appears. If a document says
`C1`, `E0`, `B0+` or `Mh` without saying what it means within a line or two, it
is not finished. The orbital branch has the same problem with its own vocabulary.

Finish with a two-to-three sentence description of each project, written so it
can be pasted straight onto a portfolio page, and put it at the top of each
README.

---

## 6. Traps already paid for

- **`git branch -vv` "ahead 35" is about one branch pair, not the repository.**
  Check every branch against every other before claiming anything is unpushed. I
  got this wrong once already this week and told the owner the orbital work was
  322 commits behind, when it was simply on a different branch.
- **Windows Application Control blocks `.deps/cable-venv/Scripts/python.exe`.**
  Use `pythonw.exe` from the same environment — identical interpreter, identical
  packages. Never copy or rename the blocked binary.
- **Multi-line edits:** write a small Python patch script with
  `assert old in s` before each replace. Bash heredocs fail on this machine on
  apostrophes and triple quotes, and this has now cost time in six separate
  sessions.
- **`freecadcmd script.py`** runs the file under its own module name, so an
  `if __name__ == "__main__"` guard never fires; the process prints its banner,
  exits 0 and writes nothing. Call `main()` directly.
- **Isaac Sim's shutdown takes the process with it.** Anything after
  `app.close()` does not run. Write records before closing the app.
- There is **no display on this machine.** Anything that opens a window cannot be
  run here. Render to a file and inspect the file, and say in the handover what
  was never executed.

---

## 7. Done conditions

1. `docs/REPO_MAP.md` exists in both repositories and describes every branch.
2. The orbital repository has three branches, each with a clear purpose, and no
   deleted branch lost anything.
3. Neither repository contains the other's subject matter.
4. Every open item is either closed, or written down with what it would cost.
5. Nothing is left uncommitted in either working tree, and nothing is left
   unpushed on any branch.
6. No script is imported that does not exist, and a test enforces it.
7. Both READMEs open with a two-to-three sentence description a stranger
   understands, and neither uses an unexplained abbreviation.
8. No artifact, page or website was produced.

Finish by telling the owner, in plain English: what each repository is now for,
which branches exist and why, what was deleted and where it went, what was
finished, and what is still open with its price.
