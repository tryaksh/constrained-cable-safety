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
| Finger pads alone | **0 of 16** | **808 mm** | **3.14 rad** | 913 mm against 168 mm |
| Robot-side form lock | 1 of 1 | **2.3 mm** | **6.2 mrad** | 433 mm against 454 mm |

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
| Robot-carried transit | 2.3 mm / 6.2 mrad tool-to-module drift over a 450 mm flight | Single-environment runs plus one 16-environment passive control |
| Seating in the destination bay | **Not closed** — see below | |
| Local compute service | API, dashboard, queue, events, cancellation, artifacts and hashes | Local machine; no authentication or cloud deployment |

Primary evidence:

- [`evidence/fiducial_rgbd_service_plate.json`](evidence/fiducial_rgbd_service_plate.json)
- [`evidence/service_latch_clearance.json`](evidence/service_latch_clearance.json)

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

The robot carries the module to the destination bay and drives it at the
channel. The seating does not complete, and the reason is a real conflict rather
than a tuning gap: **carrying needs rigidity and mating needs compliance.**
Measured three ways, on the same seed and policies:

| Lock state during mating | What the seating did |
| --- | --- |
| rigid throughout | module advanced **0.3 mm** in a 30-second budget |
| released at the phase boundary | advanced **15.6 mm**, then wedged inside the channel |
| released before the mouth | slid **laterally out of the bay** — the pads do not resist lateral load |

The current design gives the lock three states — rigid to carry, a bounded
compliance to mate, released once seated — which is what assembly compliance
devices and the SSRMS latching end effector both do. The compliant state is a
solver-side joint drive rather than an applied wrench, because an explicit
spring at the 30 Hz command rate cannot be made stiff, and it has to be stiff in
rotation while staying soft in translation: the rack aligns a module by pushing
it, and no lead-in can straighten a 450 mm module inside a 1 mm channel.

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
- The robot-carried transit numbers come from single-environment runs. There is
  no multi-seed success rate for it yet.
- The two-bay insert policy certifies at 10.5% on this workcell — 0.00% in the
  first bay — from a previous session. The insertion here is scripted and
  guarded, and is labelled as such in every report.

License: BSD-3-Clause.
