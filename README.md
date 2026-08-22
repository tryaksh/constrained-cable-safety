# Robotic Compute-Module Serviceability Lab

This repository uses NVIDIA Isaac Lab to test whether a six-axis robot can see,
capture, remove, carry, align, and replace a modular compute unit. The useful
product direction is a simulation-backed design-for-robotic-serviceability
tool, not a claim of flight-qualified orbital servicing.

## Important current status

The perception pipeline and compute service work. The latest complete physics
run does **not** yet satisfy the intended final demonstration: after extraction,
an invisible world-mounted D6 payload stage takes the module from the robot and
moves it between bays. This is retained as a measured experimental baseline,
not as proof that the robot carries the module.

The next task is defined precisely in
[`docs/claude_opus_5_handoff.md`](docs/claude_opus_5_handoff.md): remove the
hidden carrier from the showcase and complete the swap using learned capture /
extraction plus deterministic robot-carried transit and guarded insertion. If
the present gripper interface cannot retain the module, measure that limitation
and implement a visible, physically justified form-locking service interface.

## What is working

| Capability | Measured result | Boundary |
| --- | ---: | --- |
| RGB-D fiducial perception | 1.682 mm position-error p95 over 1,024 rendered frames | Simulation camera and calibrated marker |
| Detection at critical rack poses | 99.854% | Rendered holdout |
| Two-bay occupancy | 100% exact match | Rendered holdout |
| Shuttle-based state workflow | 16/16 settled outcomes | Module is not robot-carried after extraction |
| Shuttle-based RGB-D workflow | One settled complete run | Demonstration outcome, not a reliability rate |
| Local compute service | API, dashboard, queue, events, cancellation, artifacts and hashes | Local machine; no authentication or cloud deployment |

Primary evidence:

- [`evidence/fiducial_rgbd_service_plate.json`](evidence/fiducial_rgbd_service_plate.json)
- [`evidence/full_chain_state_16_report.json`](evidence/full_chain_state_16_report.json)
- [`evidence/full_chain_rgbd_service_seed4070.json`](evidence/full_chain_rgbd_service_seed4070.json)

The last two files explicitly describe the payload-stage baseline and must not
be presented as robot-carried results.

## Start the local service

On the validated Windows/Isaac installation:

```powershell
C:\isaac-sim\python.bat scripts\run_service_api.py --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

`replay_full_chain` tests the service and dashboard without physics.
`isaac_full_chain_perception` currently executes the payload-stage baseline and
must be changed before it is used as the final portfolio demo.

See [`docs/compute_service_demo.md`](docs/compute_service_demo.md) for the short
API and artifact reference.

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
```

The last completed validation recorded 141 non-Isaac tests and 31 service
tests passing. Re-run them after changing the robot-carried workflow.

## Files that matter for the next session

| Purpose | Path |
| --- | --- |
| One-session execution prompt | `docs/claude_opus_5_handoff.md` |
| Measured interface constraints | `docs/service_interface_spec.md` |
| Full workflow driver | `scripts/run_workflow_demo.py` |
| Candidate relocation path tooling | `scripts/plan_relocation_joint_path.py`, `configs/ur10e_relocation_rrt.yaml` |
| Gripper/workcell configuration | `src/zero_g_blade_swap/tasks/blade_swap/grapple_pin_env_cfg.py` |
| Perception estimator | `src/zero_g_blade_swap/fiducial.py`, `src/zero_g_blade_swap/tasks/blade_swap/mdp/perception.py` |
| Compute service live preset | `src/zero_g_blade_swap/service/presets.py` |
| Tests defending the chain | `tests/test_workflow_handoff_contract.py`, `tests/test_perception_deployment_contract.py` |

## Honest limits

- No real robot, real camera, hardware-in-the-loop, connector mating, cabling,
  cooling, or flight qualification has been demonstrated.
- The current final-looking video uses the rejected payload-stage baseline.
- The oversized upright fiducial and heavy presentation noise should be replaced
  with a realistic flush marker and clean showcase render.
- A physical or simulated latch is acceptable only when it represents visible
  hardware between the robot tool and module, carries the load through the
  robot, and is reported honestly. A hidden world constraint is not acceptable.

License: BSD-3-Clause.
