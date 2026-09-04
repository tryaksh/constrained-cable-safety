# Agent instructions

Read [`docs/NOW.md`](docs/NOW.md) first. It is the canonical state: what runs,
what the numbers are, which checkpoints the chain uses, what is settled, and how
to reproduce any of it. Its current gates determine priority. Bounded task
detail is in [`docs/NEXT_WORK.md`](docs/NEXT_WORK.md).

Everything below is the working rules, not the state.

## Route by question

| You need | Read | Cost |
| --- | --- | --- |
| Current state, numbers, checkpoints | `docs/NOW.md` | one file |
| What to work on next | `docs/NEXT_WORK.md` | one file |
| Is this evidence file current? | `evidence/MANIFEST.json` → `counts`, `canonical` | head of one file |
| Why a requirement is what it is | `docs/service_interface_spec.md` (large — search it, do not read it) | grep |
| How a past conclusion was reached | `docs/archive/` + `evidence/RETRACTED.md` | on demand |
| Which script does X | `scripts/README.md` | one file |
| What the videos actually show | `docs/DEMOS.md` | one file |
| What is idealised, and what would falsify it | `docs/sim_to_real.md` | one file |
| Why the seating phase is scripted | `docs/seating_controller.md` | one file |
| What the paper may claim, and what is prior art | `docs/paper_position.md` | one file |
| How to start the manuscript, and the prompt for it | `docs/manuscript_prompt.md` | one file |
| Install | `docs/INSTALL.md` | on demand |

**Do not read `evidence/*.json` in bulk.** Most are superseded.
`evidence/MANIFEST.json` mechanically records the current counts and groups every
report as `canonical`, `retracted`, or `historical`. Quote canonical. Never quote
retracted.

## What is built

**The problem:** swapping a failed compute module in a rack on an orbiting
platform, autonomously. The simulation runs at `gravity=(0.0, 0.0, 0.0)`
throughout, and that is load-bearing — a free-floating mass does not settle, and
closing pads on a taper in zero gravity eject the module before they grip, which
is why capture and extraction are learned and the free-space motion is not. The
project's output is the design specification, not the demo.

An industrial hybrid, and the split is a stated requirement rather than a habit:

1. trained capture and extraction;
2. deterministic collision-checked robot motion while retaining the module, on a
   visible robot-side form lock;
3. guarded robot-driven alignment and insertion, advancing only while the
   deployed estimator says the module is inside its envelope;
4. release of the lock's rigidity where the rack takes over, and of the hand only
   after settled seating is verified.

Do not use a world constraint, teleport, direct module pose write, or hidden
carrier. The form lock is a break-rated PhysX fixed joint between `wrist_3_link`
and the module while rigid, and a bounded spring-damper on the same pair while
compliant. That simplification is disclosed in every report and in the
specification.

## Rules

1. **Label on the controller that ran.** A phase may not be called learned unless
   a policy produced the actions. Never key that label on a configuration flag.
2. **Derive geometry, do not tune it.** Every geometric requirement is computed by
   a check that runs without a simulator, and that check validates itself against
   the simulator's own recorded configurations before it reports.
3. **Change one thing at a time and keep the losing arm.** A criterion change and
   a policy change must never be quoted as one number. `play.py` carries
   `--legacy_grip_ball_m` and `--legacy_unbounded_reset` for exactly this.
4. **Never widen a tolerance to pass a gate.** If a criterion is wrong, replace it
   with one derived from the parts, and re-run the old checkpoint under both.
5. **Check the geometry before spending the GPU.** A policy cannot make a 3 mm
   swing fit through a 0.5 mm gap. Extract gained 13 points from task corrections
   and 0 from 2,000 epochs; that ordering is the norm here, not the exception.
6. **Keep failed results.** Superseded and failed runs stay in `evidence/`,
   labelled. Claims that turn out to be wrong go in `evidence/RETRACTED.md`.
7. **Batch long GPU runs and time-box them** so certification always has clock
   left. A 1024-environment PPO run fits in 12 GB alongside a small evaluation
   process; two full training runs do not.

   **Parallel trainings cost per-job throughput and still win on aggregate, and
   the earlier reading of this was wrong.** This rule used to say one
   512-environment run alone reports about 6,000 fps and four report about 5,000
   aggregate, so concurrency lost. That compared a *peak* against *sustained*
   figures. Medians over whole runs, same task and same configuration at two
   seeds, measured 2026-09-03 later the same day:

   | what was running | per-job `fps total`, median |
   | --- | ---: |
   | capture, seed 70 | 2,213 (p90 2,808, one sample at 8,215) |
   | capture, seed 71, beside two other trainings | 1,812 |
   | extraction, beside two other trainings | 1,558 |
   | seating, beside two other trainings | 1,133 |

   Three concurrent trainings aggregate about 4,278 fps against a best sustained
   single-run median of 2,213. Concurrency costs each job roughly 18% and nearly
   doubles the total, so **run three**. The 8,215 sample is what the old rule was
   built on: `fps total` is inflated for the first reporting intervals of a run,
   and reading it once, early, is how a peak becomes a ceiling.

   Memory is the real limit, not the GPU. A 1024-environment run fits in 12 GB
   beside a small evaluation process; free system memory falling under about
   3 GB of 32 is when the machine starts paging and hours get lost to an
   out-of-memory kill. Watch that, and report per-job `fps total` medians rather
   than GPU utilization or a single line: a saturated GPU time-slicing four jobs
   looks identical to a busy one.

   Not yet measured: whether a fourth concurrent training still adds. The cheap
   way to find out is to median the period when the campaign naturally drops to
   one run, rather than stopping work to stage it.
8. **Never claim a capability whose checkpoint is not reachable.** `logs/` and
   `checkpoints/` are gitignored, so a clone has the reports and none of the
   weights. Say where a checkpoint lives when quoting what it scored.

## Before you change anything

A refactor that could move a published number must either re-run the affected
certification or become a task in `docs/NEXT_WORK.md`. These files define
criteria, so editing them invalidates evidence:

```
src/zero_g_blade_swap/tasks/blade_swap/mdp/grapple.py
src/zero_g_blade_swap/tasks/blade_swap/mdp/insertion.py
src/zero_g_blade_swap/evaluation.py
src/zero_g_blade_swap/tasks/blade_swap/grapple_pin_env_cfg.py
src/zero_g_blade_swap/tasks/blade_swap/two_slot_env_cfg.py
scripts/run_workflow_demo.py
```

```bash
ruff check src scripts tests                       # CI runs this and nothing else here did
pytest -m "not isaac and not camera and not benchmark"   # bare pytest, the way CI invokes it
python scripts/check_criterion_currency.py         # evidence that predates its criterion
python scripts/check_source_provenance.py --depth 200  # can the run still be reproduced
python scripts/build_evidence_manifest.py --check
python scripts/build_script_index.py --check
pytest -m "not isaac and not camera and not benchmark"
```

**Run `ruff` before pushing.** `.github/workflows/ci.yml` lints `src scripts
tests` and fails the build on any finding, and this list omitted it until
2026-09-03 -- by which time the branch had been red for long enough that every
push emailed a failure. `ruff --fix` is not automatically safe either: it deleted
a re-export that `tests/test_rack_retention.py` reads off the module, so run the
suite after fixing.

**Run it as a bare `pytest`, not as `python -m pytest`.** The two differ: the
module form puts the working directory on `sys.path` and the bare form does not,
and `tests/test_project_insertion_checkpoint.py` imports `scripts.…`. That test
passed locally and failed collection in CI, invisibly, because the lint step
failed first and the suite never ran. `pythonpath = ["."]` in `pyproject.toml`
now makes the two agree; the habit is still worth keeping.

**When you quote a report, read its `scope_and_limitations` and carry the
qualifying ones into the sentence you write.** Three claims were corrected on
2026-09-03 for the same reason: the evidence file said the limit, and the prose
that cited it did not.

| what the report said | what the prose said |
| --- | --- |
| "the arithmetic brackets the observed travel rather than predicting it to a millimetre" | "the closed-form bound predicts the achieved depth to within a millimetre" |
| visibility "is line of sight only... does not predict decoding, exposure or motion blur" | "no depth of the stroke where both plates are unreadable" |
| per-seed **medians** of estimator error | quoted as "mean estimator error", hiding 154 mm and 355 mm excursions |

None was a wrong number. Each was a true number that grew a stronger meaning on
the way from the file to the paragraph, and each survived every mechanical check
this repository runs, because none of them checks what a sentence claims. The
only defence is reading the scope block before writing the sentence.

**Do not believe an `exit=` line in a campaign log written before
2026-09-03.** Every one of them reports the clock, not the job. Expansion runs
left to right, so in `echo "[$(date +%H:%M:%S)] thing exit=$?"` the `date`
substitution executes first and overwrites the status, and the line prints
`exit=0` whether the run finished or died in its first second. Forty-five lines
across twenty-two shipped scripts did this, including every certification script
here, and twenty-eight more across the campaign queues. Nothing branched on the
value so no published number is affected, but a job that crashed was logged as a
success. Capture it first:

```bash
rc=$?
echo "[$(date +%H:%M:%S)] thing exit=$rc"
```

The mirror image is fine for the same reason -- `say "exit=$? -> $(ckpt)"` reads
the status before anything can disturb it. `tests/test_shell_status_reporting.py`
enforces the rule and carries a short exemption list for scripts that were
mid-run when it was written; bash reads a script incrementally, so editing one
while it executes can make it run garbage.

**Verify a run by its artifact, never by its log line.** The screening bug that
threw away three completed RGB-D arms and this one are the same mistake in two
places: trusting a summary rather than the thing it summarises.

The suite must stay green, including `tests/test_skill_chain_agreement.py`, which
holds each learned skill to the problem the full chain actually hands it — the
failure mode that has cost this project the most. It is source-level and needs no
GPU. Rebuild the manifest after adding evidence.

## Completion rule

The robot must visibly carry the module from source to destination, the report
must show bounded tool-to-module pose throughout transit, RGB-D perception must
remain active, the module must settle in the destination for 0.70 s, and the
compute service must save a clear video and hashed artifacts. If part of this
cannot be completed, report the measured blocker; never fall back to the hidden
payload stage and call it success.

This is met at the pooled rate. The same rule applied to the individual *skills*
is not — see `docs/NOW.md` §2 and §5.

## Main files

| Path | What it is |
| --- | --- |
| `scripts/run_workflow_demo.py` | The chain driver: phases, controllers, reports |
| `scripts/run_robot_carried.sh` | Every way of running the chain, one stage per question |
| `scripts/check_workcell_geometry.py` | Where the arm stands, what the channel admits, the module-section envelope. No simulator |
| `src/zero_g_blade_swap/servicing_design.py` | The same derivation as a library: three measured manipulator numbers in, the rack requirement out. `scripts/derive_rack_requirement.py` is its CLI |
| `scripts/report_boundary_failure_modes.py` | Scores each closed-form criterion against the failure it predicts, rather than against the pooled rate |
| `scripts/check_service_latch_clearance.py` | The form lock's clearances, from the measured gripper envelope |
| `scripts/solve_insert_reset_bank.py` | Paired arm and module poses along the seating stroke, solved in closed form |
| `scripts/certify_grapple_skills.sh` | One skill, three stages, three held-out seeds, pooled with a gate |
| `scripts/sweep_chain_robustness.sh` | One variable at a time around the certified point |
| `scripts/build_evidence_manifest.py` | Regenerates `evidence/MANIFEST.json` |
| `src/zero_g_blade_swap/arm_kinematics.py` | One UR10e chain: NumPy for checks, batched Torch for transit |
| `src/zero_g_blade_swap/grapple_geometry.py` | The pin, and what counts as holding it |
| `src/zero_g_blade_swap/service_latch.py` | The form lock's geometry and release interlock |
| `src/zero_g_blade_swap/tasks/blade_swap/grapple_pin_env_cfg.py` | The three skill tasks |
| `src/zero_g_blade_swap/tasks/blade_swap/assets.py` | Rack, module, pin, rails, lead-ins |
| `src/zero_g_blade_swap/tasks/blade_swap/mdp/grapple.py` | Every predicate and reward the skills use |
| `src/zero_g_blade_swap/tasks/blade_swap/insert_reset_bank.py` | Generated; do not hand-edit |
| `src/zero_g_blade_swap/service/presets.py` | What the live service runs (currently a superseded set — `NEXT_WORK.md` T7) |

**Before adding a test that reads a path, check the path is in git.**
`artifacts/` is gitignored, so a clean checkout -- which is exactly what CI has
-- contains none of the campaign queues, none of the episode archives and none
of the logs. A test that reads one passes locally and fails in CI, and the lint
that catches shell status bugs did precisely that on every push until it was
found. Reproduce CI before pushing a test that touches the filesystem:

```bash
git clone --depth 1 file://$(pwd) /tmp/cisim && cd /tmp/cisim && pytest -q -m "not isaac and not camera and not benchmark"
```

That takes twenty seconds and is the only way to see what CI sees.
