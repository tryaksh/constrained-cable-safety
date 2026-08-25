# Robotic Compute-Module Serviceability Lab

A simulation testbed that asks whether a six-axis robot can service a modular
compute unit, and reports which module and rack dimensions decide the answer.

Built on NVIDIA Isaac Lab. Everything here is simulated; nothing has been run on
hardware.

---

## The problem this is about

Compute modules — server blades, spacecraft ORUs — are designed to be swapped by
a person. A human hand tolerates a rack that is loose, a module that is slightly
crooked, and a grip point that was never really designed. A robot does not.

When a robot has to do the swap instead, the things that stop it are usually not
the obvious ones. Reach and payload are rarely the limit. What stops it is the
interface:

- **How the robot holds the module.** A parallel-jaw gripper on a passive
  feature cannot resist a moment about its own closing axis. If the module has no
  feature designed for a robot, the robot drops it under load.
- **How much the rack lets the module move.** A module inside its own channel is
  only as steady as the clearance around it. Loosen the rack and the module can
  go places the gripper cannot follow.
- **How square the module has to be to go back in.** A rigid part of length *L*
  entering a channel with *c* of clearance per side fits only while its tilt
  stays under `2c/L`. That is a hard geometric limit, and it is usually much
  tighter than the tolerance the assembly's own acceptance test uses.

These are design decisions made long before anyone tries to automate the swap,
and they are expensive to discover on hardware. This repository is where they get
discovered cheaply.

## What it does today

One continuous episode, no cuts: a UR10e locates a compute module in a rack bay
using RGB-D, grips it, pulls it clear, carries it to the neighbouring bay, drives
it home, and opens its hand only after the seating has been re-checked over a
0.70 second settle. The robot holds the module the whole way — no world
constraint, no teleport, no direct pose write, no hidden carrier.

| | |
| --- | ---: |
| Pooled success | **97.92%** |
| Episodes / seeds | 96 / three held out |
| Wilson 95% interval | [92.7%, 99.4%] |
| Seating conditions met and re-checked after settling | 7 of 7 |
| Tool-to-module drift through the carry | 0.9 mm and 2.5 mrad median, 2.3 mm and 6.3 mrad worst |

The project's own promotion gate is 95% pooled and 95% worst-case. The chain
passes it. The individual learned skills do not — see
[Where it falls short](#where-it-falls-short).

Rate: `evidence/workflow_robot_carried_m130pin_guarded_certification.json`.
Single run: `evidence/robot_carried_full_chain_pin.json`.

## Approach

### Hybrid control, split on a stated rule

Reinforcement learning owns the phases where contact decides the outcome and no
model predicts it. Deterministic control owns the phases where the geometry is
known and the requirement is repeatability.

| Phase | Runs on | Why |
| --- | --- | --- |
| Grasp | RL policy | The grip point is a tapered pin. A closing pad on a taper in zero gravity pushes the free module away before it grips, and whether the grip takes depends on contact transients over about 0.1 s. |
| Extract | RL policy | The same contact under load, with the rack still partly constraining the module. |
| Transit (5 legs) | Solved inverse kinematics | Pose-to-pose moves through a workcell whose kinematics are solved in closed form and agree with the simulator to 0.006 mm. There is no uncertainty here for a policy to be robust to. |
| Insert | Guarded advance on the RGB-D estimate | The axial target moves only while perception says the module is inside the bay's envelope, so a lost marker stops the insertion instead of continuing blind. |
| Release | Scripted, after the settled re-check | The hand opens only once every seating condition has held for 0.70 s. |

The rule is written down as a requirement in
[`docs/service_interface_spec.md`](docs/service_interface_spec.md) §10, together
with the gates it has to satisfy, so a phase cannot quietly change sides. A phase
may not be labelled "learned" unless a policy produced the actions that ran, and
the report keys that label on the controller that stepped rather than on a
configuration flag.

`--insert_controller policy` swaps the learned insert checkpoint in for the
guarded advance, so "the policy is not used because it loses" stays a measurement
on this chain rather than an assumption.

### Geometry gets derived, not tuned

Most of the numbers that decide whether this works are geometric, and they are
computed from the parts rather than chosen and remembered.
[`scripts/check_workcell_geometry.py`](scripts/check_workcell_geometry.py) runs
in about a second on a CPU, with no simulator, and answers:

- where the arm can stand and how much control authority it has there;
- what attitude the destination channel admits at each depth;
- how much freedom the rack leaves the module while it is being pulled;
- the window the channel's lateral clearance has to lie in;
- which module cross-sections this rack accepts at all.

It validates its own kinematics against configurations the simulator recorded
before it reports anything. A requirement only a GPU can check is a requirement
that stops being checked.

### Every claim carries its counterfactual

Design decisions here are made by measurement, and the losing arm is kept. The
clearest example is why the module is carried on a robot-side form lock instead
of in the fingers:

| Carried by | Kept the planned transform | Tool-to-module drift | Module travel vs tool travel |
| --- | ---: | ---: | --- |
| Finger pads alone, 16 environments | 0 of 16 | 808 mm | 913 mm vs 168 mm |
| Robot-side form lock | every environment | 0.9 mm | matched |

Read the last column of the first row. On the passive grip the tool travels
168 mm while the module travels 913 mm and turns end-for-end. The module is not
being carried, it is being released, about ten seconds into the flight. No
controller change fixes that, so the interface changed instead.

Superseded results are kept and labelled, and claims that turned out to be wrong
are written down in [`evidence/RETRACTED.md`](evidence/RETRACTED.md) rather than
quietly removed.

## Where it falls short

**The learned skills miss their own gate.** Grasp certifies at 85.69% pooled and
extract at 87.75%, against a 95% target, over roughly 4,500 episodes each on
three held-out seeds. The chain exceeds both because it is not their product:
each phase hands over on the *next* phase's precondition rather than on its own
success criterion, and the guarded seating recovers deliveries a skill
certification would score as failures. Both numbers are reported and neither is
quoted without the other.

**Extract's ceiling is not training budget.** Two separate retraining runs — 900
epochs, then 2,000 more — moved the pooled rate by 1.4 points and then by zero.
What moved it was fixing the task: the criterion that judged the grip, the rack
clearance it ran in, and a reset that was starting 39% of its hardest cases with
the gripper closed on nothing. Those three are worth about 13 points pooled on an
unchanged policy. The mechanism and the ladder that separates the contributions
are in [`docs/STATUS.md`](docs/STATUS.md).

**Two setup variables dominate everything else.** A one-variable-at-a-time sweep
around the certified configuration ranks them: a 120 × 16 mm module takes the
chain from 93.75% to 0.00%, and a 10 mm error in where the robot parks across the
bay takes it to 6.25%. By comparison, doubling the module's mass costs nothing
and a rack 16 mm wider per side than the derived bound costs 18.75 points. The
closed-form envelope predicted every cross-section result before the simulator
was started, which is the point of having it.

**The seating is scripted, and a learned policy has not beaten it.** The insert
task was rebuilt this session — its reset now spans the whole 529 mm stroke
instead of starting at one fixed pose, its action scale is sized for that stroke,
both bays seat at the depth the release interlock actually permits, and its
reward no longer charges the gripper's own load path. The last of those was worth
62 points of reward on the step it took effect, and the policy now holds the
module in 128 of 128 held-out episodes where it used to drop it. It still does
not finish the stroke inside the time budget, and a further 977 epochs made the
reward worse rather than better. Both rates are published beside each other and
the chain keeps the scripted advance; `--insert_checkpoint` is optional so a
chain that does not use a policy does not load one.

**The margin on delivered angle is thin.** Modules seat at about 46 mrad off
square against a channel that admits 56 mrad with the shipped relief. That is the
one place in the certification that operates against a limit rather than inside
one.

## Simplifications, stated

- No hardware, no real camera, no hardware-in-the-loop, no connector mating,
  cabling, cooling, or flight qualification.
- The form lock's load path in simulation is a break-rated fixed joint while
  rigid and a bounded, damped joint drive while compliant, both between the wrist
  and the module. Its hardware is authored on the wrist and its clearances are
  derived, but the jaws carry no collider, so contact between them and the pin is
  not simulated.
- The satellite base compliance is authored and **not in the load path**. The
  robot spawns with a fixed root, so the declared spring has nothing to deflect
  and the measured deflection is 0.000000 on every step. The report says exactly
  that, because a zero is also what a working compliant mount would produce.
- The lateral rail carries the *robot*, and it indexes a base that is already
  fixed to the world. Its motor, screw, bearings and brake are not modelled. What
  is not simplified is the claim it supports: the module is never written, never
  constrained to the world, and never held by anything but the robot, and the
  transit trace records the base's own position, so a carriage that was commanded
  and did not move cannot be reported as one that crossed.
- Contact forces are a relative damage proxy for comparing designs, not an
  absolute force budget.

## Where this is going

The end product is a design-for-robotic-serviceability tool: given a module and a
rack, say whether a robot can service them, and if not, name the dimension to
change and by how much. The pieces already exist — the closed-form geometry
checks, the module cross-section envelope, and an interface specification written
as requirements with evidence attached. The swap chain is what validates them.

## Getting started

- **Install:** [`docs/INSTALL.md`](docs/INSTALL.md)
- **Current state, and how to reproduce it:** [`docs/STATUS.md`](docs/STATUS.md)
- **Interface requirements and the evidence behind them:**
  [`docs/service_interface_spec.md`](docs/service_interface_spec.md)
- **Running the local service and dashboard:**
  [`docs/compute_service_demo.md`](docs/compute_service_demo.md)

## Repository map

| Path | Contents |
| --- | --- |
| `src/zero_g_blade_swap/` | Tasks, MDP terms, kinematics, perception, and the local compute service |
| `scripts/` | Training, evaluation, geometry checks, and the workflow driver |
| `tests/` | Contract tests; most run without a simulator |
| `evidence/` | Every published measurement as JSON, including superseded and failed runs |
| `docs/` | Specification, status, installation; `docs/archive/` holds session history |

License: BSD-3-Clause.
