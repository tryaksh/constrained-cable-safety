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
python scripts/check_criterion_currency.py         # evidence that predates its criterion
python scripts/check_source_provenance.py --depth 200  # can the run still be reproduced
python scripts/build_evidence_manifest.py --check
python scripts/build_script_index.py --check
pytest -m "not isaac and not camera and not benchmark"
```

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
