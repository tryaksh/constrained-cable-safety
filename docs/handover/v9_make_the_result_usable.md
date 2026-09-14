# V9 — Make the finished result usable by someone who is not you

**The measuring is over and it stays over.** Four studies are registered, run and
fitted. This session does not start a fifth, does not refit the safety layer, and
does not re-run a block for nicer numbers. It takes a repository that is *correct*
and makes it *usable*, which is a different job and is the one that is left.

**EXECUTED 2026-09-14.** All six stages ran. `scripts/verify_findings.py`
re-derives the four verdicts from `evidence/` and
`scripts/try_the_safety_check.py` runs the shipped filter with no simulator, both
on `.venv` alone and both in the README's first screenful.
`tests/test_documented_numbers.py` pins every headline number to the record it
came from. Six committed figures are now shown with captions and record links;
findings 2 and 3 had none drawn, which is recorded as an open item with a price
rather than fixed by rendering. The five maintained documents were rewritten for
a reader: no session, no agent, no writing standard, nothing explained twice. No
study was run, no block refitted, no figure rendered and nothing for a website
produced. The suite is 501 tests. **This file is now history. Do not run it
again.**

Prepared 2026-09-13, after the two-repository reorganisation
([v8](v8_two_repo_reorganisation.md)) left this repository with one branch, 441
tests and both campaigns indexed.

---

## What this session must NOT produce

- **Nothing for a website.** No HTML, no hosted page, no published artifact, no
  demo site, no slide deck, no marketing copy. The owner is writing a Robotics
  Lab page on their own portfolio themselves, later, from what is in this
  repository. If you find yourself writing anything whose audience is a web
  visitor rather than an engineer reading the repository, stop.
- **No new study, no refit, no re-run of a fitted block.**
- **No new figures or videos.** Twenty figures are already committed in
  `evidence/`. Regenerate one only if it disagrees with the record it was drawn
  from, and say so when you do.
- **No renaming of packages, modules or evidence files.** Records hash each other
  by path.

---

## Why this session exists

Someone lands on this repository from a one-line link. They have five minutes and
no simulator installed. Right now they can read an accurate README, and that is
about all they can do: the shipped safety layer is the genuinely reusable thing
here and there is no way to run it without MuJoCo in a separate environment; the
headline numbers are correct but nothing checks that they still match the records
they came from; and nineteen of the twenty committed figures are never shown.

The goal is that a stranger with a checkout, a plain Python environment and five
minutes can **run the check, see what it decides, and verify the headline claim
themselves.**

---

## What to do, in order

Commit at every stage boundary and push. If a stage turns out to be a bad idea
once you are inside it, write down why and move on rather than forcing it.

### Stage 1 — Make the headline numbers testable, not just true

The sister repository has `tests/test_documented_numbers.py`: it reads figures out
of `evidence/` and asserts the documents still quote them. This repository has no
equivalent, so every number in `README.md` and `ROADMAP.md` is a hand-typed copy
that can drift silently. That is this project's most expensive failure mode and it
is the one thing here that is not yet mechanically defended.

Port the idea, deliberately narrowly — only the claims a reader takes away and a
reviewer would check. A test that pinned every number in the prose would fail
constantly and be switched off.

Done when: changing a number in a record makes the test fail and name the document.

### Stage 2 — One command that reproduces the headline claim, on CPU, in under a minute

There is no single entry point that says "here is what the four studies found, and
here is that conclusion re-derived from the committed records rather than retyped."
Write one. It reads `evidence/`, prints a short table of the four verdicts with the
record each came from, and exits non-zero if a verdict cannot be reconstructed.

No simulator, no GPU, no network. Put the command in the README's first screenful,
above everything that needs `.deps/cable-venv`.

### Stage 3 — Make the safety layer obviously reusable

`SafetyFilter` is the piece of this project someone else could actually pick up,
and it imports nothing heavier than numpy — the simulator is only needed to
*generate* data, never to *use* the check. Nothing in the repository demonstrates
that.

Build the smallest honest demonstration: load the measured five-clip rig from
config, hand the filter an estimate at each of the three eyesight levels, and print
what it allows, which of the three constraints binds, and how much of each budget a
move spends. It must run with `.venv` alone. Ten to twenty lines of output, not a
framework.

Then say in the README, in one line, what a reader would have to supply to use the
check on their own rig.

### Stage 4 — Show the pictures that are already committed

Twenty figures are in `evidence/` and the README shows one. Each of the three
findings should carry the figure that was drawn for it, with a caption saying what
the reader is looking at and which record it came from. Nothing new is rendered.

If a committed figure disagrees with its record, that is a finding: either
regenerate that one figure and say you did, or leave it and say it is stale.

### Stage 5 — Check the whole thing against a cold reader

Read `README.md`, `ROADMAP.md`, `AGENTS.md`, `docs/REPO_MAP.md` and
`docs/PEG_INSERTION.md` end to end as though you had never seen the project.

- Every abbreviation explained where it first appears.
- Every claim linked to the record behind it.
- No number that a test does not defend, unless it is obviously illustrative.
- **No trace of how the work was done.** Rule 2 below: no "session", no "a
  previous session", no addressing an agent, no naming the writing standard, and
  nothing explained twice. This is the pass where you hunt those down.
- The **first 150 words of the README stand completely alone** — someone should be
  able to lift them verbatim as a summary of the project without adding anything
  or checking anything.
- The peg campaign reads as an honest closed negative result, not as an apology.

### Stage 6 — Price what is left

`ROADMAP.md` already lists what stayed open and why none of it was bought. Check it
is still accurate after this session, and that each open item still carries what it
would cost. Do not buy any of it.

---

## Rules

1. **Plain English.** `~/.claude/CLAUDE.md` carries the owner's writing
   preference and it applies to every document you touch: natural English,
   explain unfamiliar terms where they first appear, concrete over abstract,
   focused but not cryptic. The current `README.md` is the standard being asked
   for — read it before writing anything.
2. **Write for the reader, not about the work.** These documents still read in
   places as though they were produced by and for a working session, and a reader
   has no idea what a session is: *"Done in this session"*, *"a previous session
   deleted a helper"*, *"an unmodified session now hands over the whole record"*,
   *"past session handovers"*, and a repository map that opens by addressing an
   agent. Delete that frame. State what is true now and what was found; git
   history already records who changed what and when. Three more, while you are
   there:
   - **Do not name the writing standard inside the document.** "Plain English" is
     an instruction to whoever is writing, not content for whoever is reading.
   - **Say each thing once, in the document that owns it.** The README owns what
     the project is, `ROADMAP.md` owns what is open, `docs/REPO_MAP.md` owns where
     things went, `docs/PEG_INSERTION.md` owns the peg campaign. Every one of them
     currently re-explains the project from scratch. Cross-link instead.
   - **Cut the paragraph that restates the paragraph above it.** If a passage
     survives being deleted, it was not carrying anything.

   Two exemptions, and they are real: `AGENTS.md` and everything under
   `docs/handover/` are addressed to whoever picks the work up next, so process
   words belong there. And keep genuine domain vocabulary — do not sweep a word
   away because it looks like jargon without checking what it means.
3. **Never delete a result.** Failed runs, rejected candidates and losing arms
   stay with their scope. Stale code, dead scripts and superseded prose are what
   get deleted. If you are unsure which a file is, it is a result.
4. **Every claim keeps its evidence link.** A number that loses its record is a
   number you have to delete.
5. **A peg number is never a cable number.** Both campaigns live in `evidence/`
   and are told apart by the `campaign` field in `evidence/INDEX.json`.
6. Run `scripts/index_evidence.py` after adding any record, and the full test
   suite before every commit.

## Traps already paid for

- **Windows Application Control blocks `.deps/cable-venv/Scripts/python.exe` and
  `pytest.exe`.** Use `pythonw.exe` from the same environment, and
  `python -m pytest`. Never copy or rename a blocked binary.
- **Multi-line edits:** write a small Python patch script with `assert old in s`
  before each replace. Bash heredocs fail on this machine on apostrophes and
  triple quotes.
- **There is no display on this machine.** Anything that opens a window cannot be
  run here. Render to a file and inspect the file.
- `.gitattributes` turns off end-of-line conversion for the whole repository on
  purpose: records hash each other over the bytes on disk. Leave it alone.

## Done conditions

1. A stranger with a checkout and `.venv` can run one command and see the four
   findings re-derived from the records.
2. A stranger can run the safety check itself, with no simulator, and see what it
   decides and why.
3. Every headline number in the maintained documents is defended by a test against
   the record it came from.
4. Each finding carries a figure that was already committed.
5. **No maintained document mentions a session, addresses an agent, names the
   writing standard, or explains the project a second time.** `AGENTS.md` and
   `docs/handover/` are exempt.
6. Nothing is uncommitted and nothing is unpushed.
7. No website material of any kind was produced.

Finish by telling the owner, in plain English: what a newcomer can now do in five
minutes that they could not before, what you changed, what you found wrong, and
what is still open with its price.
