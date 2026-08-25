# Robotic Compute-Module Serviceability Lab

**A simulation testbed that answers one question: can a robot service this
module in this rack — and if not, which dimension has to change, and by how
much?**

Built on NVIDIA Isaac Lab. Everything here is simulated. Nothing has been run on
hardware, and nothing here is a flight-readiness claim.

---

## The bottleneck

Compute modules — server blades, spacecraft orbital replacement units — are
designed to be swapped by a person. A human hand tolerates a rack that is loose,
a module that is slightly crooked, and a grip point nobody designed. A robot does
not.

When a robot has to do the swap instead, the thing that stops it is almost never
reach or payload. It is the interface:

- **How the robot holds the module.** A parallel-jaw gripper on a passive feature
  cannot resist a moment about its own closing axis. Give it nothing designed for
  a robot and it drops the module under load.
- **How much the rack lets the module move.** A module in its channel is only as
  steady as the clearance around it. Loosen the rack and the module goes places
  the gripper cannot follow.
- **How square the module has to be to go back in.** A rigid part of length *L*
  entering a channel with *c* of clearance per side fits only while its tilt stays
  under `2c/L`. That is a hard geometric limit, and it is usually far tighter than
  the tolerance the assembly's own acceptance test uses.

These are decided long before anyone tries to automate the swap, and they are
expensive to discover on hardware. This repository is where they get discovered
cheaply.

## What works today

One continuous episode, no cuts: a UR10e locates a compute module in a rack bay,
grips it, pulls it clear, carries it to the neighbouring bay, drives it home, and
opens its hand only after the seating has been re-checked over a 0.70 second
settle. The robot holds the module the whole way — no world constraint, no
teleport, no direct pose write, no hidden carrier.

| | |
| --- | ---: |
| Pooled success | **97.92%** |
| Episodes / seeds | 96 / three held out |
| Wilson 95% interval | [92.7%, 99.4%] |
| Seating conditions met and re-checked after settling | 7 of 7 |
| Tool-to-module drift through the carry | 0.9 mm / 2.5 mrad median, 2.3 mm / 6.3 mrad worst |

The project's promotion gate is 95% pooled and 95% worst-case. The chain passes
it. **The individual learned skills do not** — see [Limits](#limits).

Evidence: `evidence/workflow_robot_carried_m130pin_guarded_certification.json`.
One run, end to end: `evidence/robot_carried_full_chain_pin.json`.

## Approach

### Learn what contact decides; solve what geometry already answers

Reinforcement learning owns the phases where contact decides the outcome and no
model predicts it. Deterministic control owns the phases where the geometry is
known and the requirement is repeatability.

| Phase | Runs on | Why |
| --- | --- | --- |
| Grasp | RL policy (PPO) | The grip point is a tapered pin. A closing pad on a taper in zero gravity pushes the free module away before it grips, and whether the grip takes depends on contact transients over ~0.1 s. |
| Extract | RL policy (PPO) | The same contact under load, with the rack still partly constraining the module. |
| Transit (5 legs) | Solved inverse kinematics | Closed-form kinematics that agree with the simulator to 0.006 mm. There is no uncertainty here for a policy to be robust to. |
| Insert | Guarded advance on the RGB-D estimate | The axial target advances only while perception says the module is inside the bay's envelope, so a lost marker stops the insertion instead of continuing blind. |
| Release | Scripted, after the settled re-check | The hand opens only once every seating condition has held for 0.70 s. |

That split is written down as a requirement, not left as a habit, and a phase may
not be labelled "learned" unless a policy produced the actions that ran — the
report keys the label on the controller that stepped, never on a configuration
flag. `--insert_controller policy` swaps the learned insert checkpoint in for the
guarded advance, so "the policy is not used because it loses" stays a measurement
on this chain rather than an assumption.

### Geometry gets derived, not tuned

Most of the numbers that decide whether this works are geometric, and they are
computed from the parts rather than chosen and remembered.
[`scripts/check_workcell_geometry.py`](scripts/check_workcell_geometry.py) runs in
about a second on a CPU with no simulator, and answers where the arm can stand,
what attitude the channel admits at each depth, how much freedom the rack leaves
the module, and which module cross-sections this rack accepts at all. It validates
its own kinematics against configurations the simulator recorded before it reports
anything.

**A requirement only a GPU can check is a requirement that stops being checked.**
The same principle governs the tests: the check that holds each learned skill to
the problem the chain actually hands it is source-level, so it runs on every
commit without a simulator.

### Every claim carries its counterfactual

Design decisions here are made by measurement, and the losing arm is kept. The
clearest example is why the module rides a robot-side form lock instead of the
fingers:

| Carried by | Kept the planned transform | Tool-to-module drift | Module travel vs tool travel |
| --- | ---: | ---: | --- |
| Finger pads alone, 16 environments | 0 of 16 | 808 mm | 913 mm vs 168 mm |
| Robot-side form lock | every environment | 0.9 mm | matched |

Read the last column of the first row. On the passive grip the tool travels
168 mm while the module travels 913 mm and turns end-for-end. The module is not
being carried, it is being released, about ten seconds into the flight. No
controller change fixes that, so the interface changed instead.

Superseded results are kept and labelled; claims that turned out to be wrong are
written down in [`evidence/RETRACTED.md`](evidence/RETRACTED.md) rather than
quietly removed.

## Limits

**The learned skills miss their own gate.** Grasp certifies at 85.69% pooled and
extract at 87.75%, against a 95% target, over roughly 4,500 episodes each on three
held-out seeds. The chain exceeds both because it is not their product: each phase
hands over on the *next* phase's precondition rather than on its own success
criterion, and the guarded seating recovers deliveries a skill certification scores
as failures. Both numbers are published and neither is quoted without the other.

**The chain's number and the perception number have never been combined.** The
97.92% runs on the state task, where the module pose comes from the simulator.
Perception is certified separately on 1,024 rendered frames. The RGB-D chain has
been run end to end at one seed. Certifying the chain on the vision task is the
highest-value missing measurement in the project, and it is task T1.

**The seating is scripted, and a learned policy has not beaten it.** The insert
policy holds the module in 128 of 128 held-out episodes where it used to drop it,
and its mean reward went positive for the first time in this project — but it
still stops a median of 204 mm short of the seated plane, at 0.00% over 1,536
episodes. It is creeping, not jamming: still moving at 3.65 mm/s when the clock
stops, against 120 mm/s of available authority. Published as a negative result
beside the scripted advance that does work.

**Two setup variables dominate everything else.** A one-variable-at-a-time sweep
ranks them: a 120 × 16 mm module takes the chain from 93.75% to 0.00%, and a
10 mm error in where the robot parks across the bay takes it to 6.25%. By
comparison, doubling the module's mass costs nothing. The closed-form envelope
predicted every cross-section result before the simulator was started, which is
the point of having it. **Training randomizes none of these**, so the 97.92% is a
point certification rather than a tolerance band.

**Every policy is a single PPO training seed.** The evaluation seeds are held out,
so the rates are honest, but training repeatability is untested and no number
carries a spread.

**The margin on delivered angle is thin.** Modules seat at about 46 mrad off
square against a channel admitting 56 mrad — the one place in the certification
operating against a limit rather than inside one.

### Simplifications, stated

- No hardware, no real camera, no hardware-in-the-loop, no connector mating,
  cabling, cooling, or flight qualification.
- The form lock is a break-rated fixed joint while rigid and a bounded, damped
  joint drive while compliant, both between the wrist and the module. Its hardware
  is authored on the wrist and its clearances are derived, but the jaws carry no
  collider, so contact between them and the pin is not simulated.
- The satellite base compliance is authored and **not in the load path**. The robot
  spawns with a fixed root, so the declared spring has nothing to deflect and the
  measured deflection is 0.000000 on every step. The report says exactly that,
  because a zero is also what a working compliant mount would produce.
- The lateral rail carries the *robot* and indexes a base already fixed to the
  world. Its motor, screw, bearings and brake are not modelled. What is *not*
  simplified is the claim it supports: the module is never written, never
  constrained to the world, and never held by anything but the robot, and the
  transit trace records the base's own position — so a carriage that was commanded
  and did not move cannot be reported as one that crossed.
- Contact forces are a relative damage proxy for comparing designs, not an
  absolute force budget.

## Where this is going

The end product is a **design-for-robotic-serviceability tool**: given a module
and a rack, say whether a robot can service them, and if not, name the dimension
to change and by how much. The pieces already exist — the closed-form geometry
checks, the module cross-section envelope, and an interface specification written
as requirements with evidence attached. The swap chain is what validates them.

That is the ambition. What is *demonstrated* today is the chain above, in
simulation, at the rate stated, with the limits stated.

## Reproducing, and what a clone does not contain

Trained weights live in `logs/` and `checkpoints/`, which are **gitignored**. A
clone carries every report and none of the weights, so the learned numbers here
are readable and not reproducible without them. `docs/NOW.md` §3 names the exact
checkpoints the certified chain loads and the reports that depend on each.

```bash
scripts/run_robot_carried.sh rail        # the whole job, one environment, ~8 min
python scripts/check_workcell_geometry.py # geometry, no simulator, ~1 s
pytest -m "not isaac and not camera and not benchmark"
```

## Getting started

- **Install:** [`docs/INSTALL.md`](docs/INSTALL.md)
- **Current state and how to reproduce it:** [`docs/NOW.md`](docs/NOW.md)
- **What to work on next:** [`docs/NEXT_WORK.md`](docs/NEXT_WORK.md)
- **Interface requirements and the evidence behind them:**
  [`docs/service_interface_spec.md`](docs/service_interface_spec.md)
- **Running the local service and dashboard:**
  [`docs/compute_service_demo.md`](docs/compute_service_demo.md)
- **For coding agents:** [`AGENTS.md`](AGENTS.md)

## Repository map

| Path | Contents |
| --- | --- |
| `src/zero_g_blade_swap/` | Tasks, MDP terms, kinematics, perception, and the local compute service |
| `scripts/` | Training, evaluation, geometry checks, and the workflow driver |
| `tests/` | Contract tests; most run without a simulator |
| `evidence/` | Every published measurement as JSON, including superseded and failed runs. Indexed by `evidence/MANIFEST.json` |
| `docs/` | Specification, state, installation; `docs/archive/` holds session history |

License: BSD-3-Clause.
