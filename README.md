# Robotic Compute-Module Serviceability Lab

This repository uses NVIDIA Isaac Lab to test whether a six-axis robot can see,
capture, remove, carry, align, and replace a modular compute unit. The useful
product direction is a simulation-backed design-for-robotic-serviceability
tool, not a claim of flight-qualified orbital servicing.

## The result this branch produced

**A parallel-jaw grip on a passive pin does not carry this module between bays,
and that is now measured rather than suspected.** Sixteen robot-carried
transits, nothing changed but the interface:

| Carried by | Retained the planned transform | Tool-to-module drift, p50 | Attitude drift, p50 | Module travel vs tool travel |
| --- | ---: | ---: | ---: | --- |
| Finger pads alone, 16 environments | **0 of 16** | **808 mm** | **3.14 rad** | 913 mm against 168 mm |
| Robot-side form lock, 32 environments | **11 of 32** | **2.6 mm** | **6.7 mrad** | 773 mm against 297 mm |
| Robot-side form lock, the demonstration run | 1 of 1 | **2.3 mm** | **6.2 mrad** | 433 mm against 454 mm |

The middle row's travel columns are pooled across the 21 environments that lost
the transform as well as the 11 that kept it, which is why they do not look like
the demonstration run's. The drift medians are the number to read: 2.6 mm against
808 mm is the interface result, and 11 of 32 is how often the lock held it for a
whole flight on this rating.

Read the last column first. On the passive arm the tool travels 168 mm while the
module travels 913 mm and turns end-for-end: the module is not being carried, it
is being released, at the median ten seconds into the flight. No controller
change addresses that.

The fix is on the **robot**, not the module, and an earlier measurement decided
that rather than preference — section 8.4 of
[`docs/service_interface_spec.md`](docs/service_interface_spec.md) sweeps the
gripper's own envelope and concludes a serviceable module cannot carry an axial
stop forward of the pads. Section 9 is the latch that rule demands: two jaws in
the 80 mm of shaft behind the collar that no part of the hand can reach, with
every clearance derived from the measured envelope by
[`scripts/check_service_latch_clearance.py`](scripts/check_service_latch_clearance.py).
The module's pin is unchanged, so every certification taken against it still
describes the part that is built.

## What is working

| Capability | Measured result | Boundary |
| --- | ---: | --- |
| RGB-D fiducial perception | 1.682 mm position-error p95 over 1,024 rendered frames | Simulation camera and calibrated marker |
| Detection at critical rack poses | 99.854% | Rendered holdout |
| Two-bay occupancy | 100% exact match | Rendered holdout |
| Learned capture and extraction | Run from their certified checkpoints, unchanged | Existing certifications |
| Robot-carried transit | 2.6 mm tool-to-module drift over a 450 mm flight, 11 of 32 inside tolerance throughout | 32-environment latched batch against a 16-environment passive control |
| RGB-D end-to-end chain | capture, extract, carry, align — every seating condition met except depth | One seed on the vision task; seed 4070 does not get through capture there |
| Seating in the destination bay | **Not closed** — see below | |
| Local compute service | API, dashboard, queue, events, cancellation, artifacts and hashes | Local machine; no authentication or cloud deployment |

Primary evidence:

- [`evidence/fiducial_rgbd_service_plate.json`](evidence/fiducial_rgbd_service_plate.json)
- [`evidence/service_latch_clearance.json`](evidence/service_latch_clearance.json)
- [`evidence/robot_carried_interface.json`](evidence/robot_carried_interface.json)
- [`evidence/robot_carried_rgbd_seed6070.json`](evidence/robot_carried_rgbd_seed6070.json) — one full RGB-D chain, randomization on, 2.95 mm carried drift, every seating condition met except axial depth
- [`evidence/robot_carried_seating_sweep.json`](evidence/robot_carried_seating_sweep.json) — why the axial depth is the one that is not met

Retained as a **labelled historical baseline**, not as a robot-carried result:
[`evidence/full_chain_state_16_report.json`](evidence/full_chain_state_16_report.json)
and
[`evidence/full_chain_rgbd_service_seed4070.json`](evidence/full_chain_rgbd_service_seed4070.json)
describe a chain in which a hidden world-mounted payload stage took the module
off the arm after extraction and moved it independently. That mechanism is still
in the driver behind `--base_rail_on_relocation`, because superseding a
measurement is not the same as deleting it, and it is kept out of the live
preset by
[`tests/test_robot_carried_contract.py`](tests/test_robot_carried_contract.py)
rather than by anyone remembering.

## What is not closed

The robot carries the module to the destination bay and drives it 362 mm into
the channel. It stops **163 mm short of seated**, and the reason is upstream of
the mating interface.

Four faults in the chain were found and fixed while measuring this, and three
conclusions this project had already published from them were wrong. The largest
was a guarded advance whose axial target was rebuilt each step from the module it
was pushing — a bounded lead that is a deadlock, and which held every stiffness,
force cap and clearance sweep at one standing 10 mm command error. See section 4
of [`docs/robot_carried_handoff.md`](docs/robot_carried_handoff.md).

What the corrected chain measures: the guarded advance is never blocked by its
own guard, and spends 875 of 900 steps holding a commanded depth a **full mating
stroke** in front of a module that will not follow. The compliance is at its hard
stop and the module still does not move.

The blocker is the delivered attitude, and it is not about one axis. The module
arrives 47–67 mrad off square — the arm's own accuracy inside the reach boundary
this project already measured — split **13.8 mrad of pitch and 15.1 mrad of
yaw**. A 450 mm module tilted in two planes has to be walked square by two
lead-ins at once.

Widening the bay was then swept properly, and the sweep is the result worth
reading — [`evidence/robot_carried_seating_sweep.json`](evidence/robot_carried_seating_sweep.json):

| Channel relief, per side | Module advanced, of 163 mm | Attitude it stopped at |
| ---: | ---: | ---: |
| 4 mm | 0.7 mm | 20.5 mrad |
| 8 mm | 10.1 mm | 35.2 mrad |
| 12 mm | 14.6 mm | 49.8 mrad |
| 16 mm | 20.6 mm | **63.5 mrad** |

Both curves are monotone and they run in opposite directions, because **the
channel is what squares the module**. Every millimetre of relief buys about
1.2 mm of travel and costs about 3.5 mrad of squareness, so the seating check's
52.4 mrad limit is crossed near 12.5 mm — with the module 15 mm into a 163 mm
travel. By 16 mm the module settles at the attitude the arm delivers with
nothing touching it at all. There is no channel width for this workcell, and
force is not a lever anywhere on the sweep: four times the push moves it 0.1 mm.

## Start the local service

On the validated Windows/Isaac installation:

```powershell
C:\isaac-sim\python.bat scripts\run_service_api.py --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

`replay_full_chain` tests the service and dashboard without physics.
`isaac_full_chain_perception` runs the robot-carried workflow: calibrated RGB-D
fiducial perception, visual occupancy planning, learned capture and extraction,
the form-locked transit, guarded robot-driven insertion, and release after
settling.

See [`docs/compute_service_demo.md`](docs/compute_service_demo.md) for the short
API and artifact reference.

## Reproducing it

```bash
scripts/run_robot_carried.sh passive    # the control: pads alone, expected to fail
scripts/run_robot_carried.sh latched    # the same chain with the form lock
scripts/run_robot_carried.sh sweep      # what the lock has to be rated at
scripts/run_robot_carried.sh mating     # what compliance the seating needs
scripts/run_robot_carried.sh certify    # three seeds, pooled with a Wilson interval
scripts/run_robot_carried.sh rgbd       # one RGB-D end-to-end run, with video
```

## Validation

Fast non-Isaac suite:

```powershell
C:\isaac-sim\python.bat -m pytest tests -m "not isaac and not camera and not benchmark" `
  --ignore=tests/test_service_api.py --ignore=tests/test_service_core.py -q
```

Service suite:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_service_api.py tests\test_service_core.py -q
```

Static checks:

```powershell
C:\isaac-sim\python.bat -m ruff check scripts src tests
node --check src\zero_g_blade_swap\service\static\app.js
C:\isaac-sim\python.bat scripts\check_evidence_links.py
C:\isaac-sim\python.bat scripts\check_service_latch_clearance.py
```

## Honest limits

- No real robot, real camera, hardware-in-the-loop, connector mating, cabling,
  cooling, or flight qualification has been demonstrated.
- The form lock's **load path in simulation is a break-rated fixed joint** while
  rigid and a limited, damped D6 joint drive while compliant, both between the
  wrist and the module. Its
  hardware is authored on the wrist and its clearances are derived, but the jaws
  carry no collider, so contact between them and the pin is not simulated. Every
  report says so.
- The wrist reaction to that lock is carried by the joint; the arm's joint
  torques under it are not separately measured.
- The robot-carried transit numbers come from one 32-environment batch on a
  single seed. There is no multi-seed success rate for it yet.
- The seating does not complete, so no end-to-end relocation has succeeded. The
  chain reaches the destination bay and stops; that failure is reported, not
  worked around.
- The two-bay insert policy certifies at 10.5% on this workcell — 0.00% in the
  first bay — from a previous session. The insertion here is scripted and
  guarded, and is labelled as such in every report.

License: BSD-3-Clause.
