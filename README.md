# Orbital Robotic Servicing Lab

**A zero-gravity simulation testbed for robotic servicing of modular spacecraft
compute hardware — and for the design question underneath it: can a robot swap
this module in this rack, and if not, which dimension has to change and by how
much?**

Built on NVIDIA Isaac Lab. Everything here is simulated at zero gravity. Nothing
has been run on hardware, and nothing here is a flight-readiness claim.

---

## Executive summary

**The goal.** Hardware that fails in orbit is usually abandoned. Servicing it
means either an astronaut EVA — rare, expensive, dangerous — or a robot, and
robots are not yet trusted to do contact-rich work on hardware nobody designed
for them. As satellites, stations and orbital compute platforms get more modular,
the ability to pull a failed compute module out of a rack and slide a new one in,
autonomously and in microgravity, is the difference between a serviceable asset
and a disposable one.

**What I am trying to achieve.** Not a better controller. The useful output is a
**design-for-robotic-serviceability specification**: given a module and a rack,
say whether a robot can service them in orbit, and if not, name the dimension to
change and by how much. Those decisions get made years before anyone tries to
automate the swap, and they are ruinously expensive to discover on hardware. This
repository is where they get discovered cheaply, in simulation, with the evidence
kept — including the evidence that went against me.

**What this repository proves.**

1. **The full swap works in zero gravity, end to end, with the robot holding the
   module the whole way** — locate, grip, extract, carry to the next bay, align,
   insert, and release only after settled seating. **97.92% pooled** over 96
   episodes on three held-out seeds. No world constraint, no teleport, no direct
   pose write, no hidden carrier.
2. **The binding constraint is the mechanical interface, not the control.**
   Measured here, a parallel-jaw gripper on a smooth raised post holds about
   **6 N** against extraction where the task's own worst-case contact reaction
   demands **66.4 N** — a factor of eleven, structural rather than a tuning
   failure. Tightening the grip made it *worse*. That is the measured argument for
   purpose-built grapple fixtures on serviceable spacecraft hardware, reached from
   data rather than from precedent.
3. **Which dimensions actually decide the outcome, ranked.** A 120 × 16 mm module
   cross-section takes the chain from 93.75% to **0.00%**; a **10 mm** error in
   where the robot parks across the bay takes it to **6.25%**. Doubling the
   module's mass costs nothing. A closed-form geometry check called every
   cross-section result before the simulator was started.
4. **A hybrid architecture that stays honest about which parts are learned.**
   Reinforcement learning where contact decides the outcome, solved kinematics
   where geometry already answers, guarded control for insertion — with the split
   written down as a requirement and every phase labelled by the controller that
   actually stepped, never by a configuration flag.

**Status.** The chain passes its 95% gate. The individual learned skills do not
(85.69% grasp, 87.75% extract). Perception is certified separately and has never
been combined with the chain at scale. The seating is scripted; a learned insert
policy has not beaten it. Every policy is a single training seed.

**The biggest caveat, first, because it qualifies everything above.** No
certification in this repository is reproducible from committed code: all nine
reports that record source hashes were produced on uncommitted working-tree
state. The runs happened and the episodes are real, but the committed bytes are
not the measured bytes. This is the top open task
([`docs/NEXT_WORK.md`](docs/NEXT_WORK.md) T0), reported rather than quietly fixed.

---

## Why zero gravity changes the problem

This is not a ground robotics demo with gravity switched off. Weightlessness is
what makes the manipulation hard, and it is in the physics —
`gravity=(0.0, 0.0, 0.0)`, and the module's own gravity disabled:

- **Nothing settles.** On the ground, gravity and friction do half the fixturing
  for free; a part resting in a channel stays there. In orbit the module is a
  free-floating mass and the only thing holding it is the robot.
- **Squeezing a free mass ejects it.** A closing pad on a tapered feature pushes
  the module away before it grips. Capture is a contact transient over about
  0.1 s, which is exactly why that phase is learned rather than scripted.
- **Reaction goes into the servicer.** There is no floor to push against, so
  insertion forces feed back into the spacecraft the arm is mounted on. The rig
  models a spring-damped satellite mounting interface for this — though it is
  authored and *not* currently in the load path, which is stated plainly below.
- **The light is brutal.** One hard directional sun, no atmospheric fill, extreme
  contrast. Perception trains against a randomized orbital sun (intensity, angle,
  pitch, yaw, colour temperature) plus Gaussian sensor radiation noise.

## The bottleneck this is really about

Compute modules — server blades, spacecraft orbital replacement units — are
designed to be swapped by a person. A human hand tolerates a rack that is loose, a
module that is slightly crooked, and a grip point nobody designed. A robot does
not, and in microgravity it has even less to work with.

What stops it is almost never reach or payload. It is the interface:

- **How the robot holds the module.** A parallel-jaw gripper on a passive feature
  cannot resist a moment about its own closing axis. Give it nothing designed for
  a robot and it drops the module under load — the 6 N against 66.4 N above.
- **How much the rack lets the module move.** A module in its channel is only as
  steady as the clearance around it. Loosen the rack and the module goes places
  the gripper cannot follow.
- **How square the module has to be to go back in.** A rigid part of length *L*
  entering a channel with *c* of clearance per side fits only while its tilt stays
  under `2c/L` — a hard geometric limit, and usually far tighter than the tolerance
  the assembly's own acceptance test uses.

## What works today

One continuous episode, no cuts: a UR10e locates a compute module in a rack bay,
grips it, pulls it clear, carries it to the neighbouring bay, drives it home, and
opens its hand only after the seating has been re-checked over a 0.70 second
settle.

| | |
| --- | ---: |
| Pooled success | **97.92%** |
| Episodes / seeds | 96 / three held out |
| Wilson 95% interval | [92.7%, 99.4%] |
| Seating conditions met and re-checked after settling | 7 of 7 |
| Tool-to-module drift through the carry | 0.9 mm / 2.5 mrad median, 2.3 mm / 6.3 mrad worst |

Gate: 95% pooled and 95% worst-case. The chain passes; the learned skills do not
— see [Limits](#limits). Evidence:
`evidence/workflow_robot_carried_m130pin_guarded_certification.json`.

## Approach

### Learn what contact decides; solve what geometry already answers

| Phase | Runs on | Why |
| --- | --- | --- |
| Grasp | RL policy (PPO) | The grip point is a tapered pin, and a closing pad on a taper in zero gravity pushes the free module away before it grips. Whether the grip takes depends on contact transients over ~0.1 s. |
| Extract | RL policy (PPO) | The same contact under load, with the rack still partly constraining the module. |
| Transit (5 legs) | Solved inverse kinematics | Closed-form kinematics agreeing with the simulator to 0.006 mm. No uncertainty here for a policy to be robust to. |
| Insert | Guarded advance on the RGB-D estimate | The axial target advances only while perception says the module is inside the bay's envelope, so a lost marker stops the insertion instead of continuing blind. |
| Release | Scripted, after the settled re-check | The hand opens only once every seating condition has held for 0.70 s. |

`--insert_controller policy` swaps the learned insert checkpoint in for the
guarded advance, so "the policy is not used because it loses" stays a measurement
on this chain rather than an assumption.

### Geometry gets derived, not tuned

[`scripts/check_workcell_geometry.py`](scripts/check_workcell_geometry.py) runs in
about a second on a CPU with no simulator, and answers where the arm can stand,
what attitude the channel admits at each depth, how much freedom the rack leaves
the module, and which module cross-sections this rack accepts at all. It validates
its own kinematics against configurations the simulator recorded before it reports
anything. **A requirement only a GPU can check is a requirement that stops being
checked** — which is also why the test holding each learned skill to the problem
the chain actually hands it is source-level and runs on every commit.

### Every claim carries its counterfactual

Why the module rides a robot-side form lock instead of the fingers:

| Carried by | Kept the planned transform | Tool-to-module drift | Module travel vs tool travel |
| --- | ---: | ---: | --- |
| Finger pads alone, 16 environments | 0 of 16 | 808 mm | 913 mm vs 168 mm |
| Robot-side form lock | every environment | 0.9 mm | matched |

Read the last column of the first row. On the passive grip the tool travels
168 mm while the module travels 913 mm and turns end-for-end — in zero gravity the
module is not being carried, it is being released, about ten seconds into the
flight. No controller change fixes that, so the interface changed instead.

Superseded results are kept and labelled; claims that turned out to be wrong are
written down in [`evidence/RETRACTED.md`](evidence/RETRACTED.md).

## Limits

**No certification is reproducible from committed code.** All nine reports
recording source hashes were produced on uncommitted state. The numbers are real;
their provenance is broken. `NEXT_WORK.md` T0.

**The learned skills miss their own gate.** Grasp 85.69% pooled, extract 87.75%,
against 95%, over roughly 4,500 episodes each. The chain exceeds both because it
is not their product: each phase hands over on the *next* phase's precondition,
and the guarded seating recovers deliveries a skill certification scores as
failures. Both are published; neither is quoted alone.

**The chain's number and the perception number have never been combined.** The
97.92% runs on the state task, where module pose comes from the simulator.
Perception is certified separately on 1,024 rendered frames. Combining them is the
highest-value missing measurement (T1).

**The seating is scripted, and a learned policy has not yet beaten it.** The
insert skill has certified at 0.00% throughout this project, stopping a median of
204 mm short. It was read for a long time as *creeping* — still moving at
3.65 mm/s when the clock stopped — and the fix that followed was a time cost.
**That reading is now measured and refuted.** Trained to convergence, the time
cost changes the shortfall by 1.4 mm and every episode still spends its whole
clock: it is being paid, not avoided.

The episodes say something else. The module ends at a median of **84.6 mrad** off
square against a channel that geometrically admits **20.5 mrad** (`2c/L` for the
shipped relief), with a 5th percentile of 56.1 — so not one episode in 512 ends
inside the angle at which it could enter at all. It is not creeping toward a seat
it might reach; it is **wedged**. The cause was in the objective: it normalised
orientation error by the *seated* tolerance, 0.15 rad, which only applies once the
channel is already holding the module square, so a fatal attitude cost less per
step than a survivable lateral offset. That scale is now derived from the rack's
own admittance. `evidence/insert_attitude_diagnosis.json`.

**The 97.92% is a point, not a tolerance band.** Training randomizes none of the
variables the robustness sweep shows the chain is sensitive to, and every policy is
a single PPO training seed, so no number carries a spread.

**The margin on delivered angle is thin.** Modules seat at about 46 mrad off square
against a channel admitting 56 mrad — the one quantity in the certification
operating against a limit rather than inside one.

**No video here shows the certified chain.** Every recording predates the fixes
that produced the current rate. See [`docs/DEMOS.md`](docs/DEMOS.md).

### Simplifications, stated

- No hardware, no real camera, no hardware-in-the-loop, no connector mating,
  cabling, thermal, or flight qualification. No orbital mechanics, attitude
  control or communication constraints — this is the manipulation problem in
  microgravity, not a mission simulator.
- The form lock is a break-rated fixed joint while rigid and a bounded, damped
  joint drive while compliant, both between the wrist and the module. Its hardware
  is authored on the wrist and its clearances derived, but the jaws carry no
  collider, so contact between them and the pin is not simulated.
- **The satellite base compliance is authored and not in the load path.** The
  robot spawns with a fixed root, so the declared spring has nothing to deflect and
  the measured deflection is 0.000000 on every step. The report says exactly that,
  because a zero is also what a working compliant mount would produce.
- The lateral rail carries the *robot* and indexes a base already fixed to the
  world; its motor, screw, bearings and brake are not modelled. What is not
  simplified is the claim it supports: the module is never written, never
  constrained to the world, and never held by anything but the robot.
- Contact forces are a relative damage proxy for comparing designs, not an absolute
  force budget.

## Where this is going

The end product is the specification, not the demo.
[`docs/service_interface_spec.md`](docs/service_interface_spec.md) states what a
modular compute unit must present to be robotically serviceable, with every number
derived from a measurement in `evidence/` rather than chosen. The swap chain is
what validates it. The ambition is that a module designer can read that document
without reading the simulation — and that "can a robot service this in orbit?"
becomes a check that runs in a second on a CPU, years before any hardware exists.

That is the ambition. What is *demonstrated* today is the chain above, in
simulation, at the rate stated, with the limits stated.

## Reproducing, and what a clone does not contain

Trained weights live in `logs/` and `checkpoints/`, which are **gitignored**. A
clone carries every report and none of the weights, so the learned numbers here are
readable and not reproducible without them. [`docs/NOW.md`](docs/NOW.md) §3 names
the exact checkpoints the certified chain loads.

```bash
scripts/run_robot_carried.sh rail         # the whole job, one environment, ~8 min
python scripts/check_workcell_geometry.py # geometry, no simulator, ~1 s
pytest -m "not isaac and not camera and not benchmark"
```

## Getting started

- **Install:** [`docs/INSTALL.md`](docs/INSTALL.md)
- **Current state and how to reproduce it:** [`docs/NOW.md`](docs/NOW.md)
- **What to work on next:** [`docs/NEXT_WORK.md`](docs/NEXT_WORK.md)
- **The specification this project exists to produce:**
  [`docs/service_interface_spec.md`](docs/service_interface_spec.md)
- **Running the local service and dashboard:**
  [`docs/compute_service_demo.md`](docs/compute_service_demo.md)
- **Demonstration videos, and what each one really shows:**
  [`docs/DEMOS.md`](docs/DEMOS.md)
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
