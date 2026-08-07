# Autonomous Server Blade Swap in Zero-G

An NVIDIA Isaac Lab `ManagerBasedRLEnv` project for training a UR10e with a
Robotiq 2F-85 gripper to remove a failed compute blade, stow it, acquire a
replacement, and insert the replacement in a microgravity data-center rack.

The active milestone is a learned, state-based insertion policy for a blade
that is already secured by the gripper. A privileged teacher, camera student,
and full-swap task are later-stage scaffolds—not completed Sim2Real claims.

## What is implemented

- Zero gravity, GPU PhysX, Fabric cloning, and collision-only manipulation
  without contact-report sensors.
- A promoted Level-0 secured-grasp insertion policy plus a vectorized
  eight-phase full-swap research scaffold.
- Random blade mass, guide friction/stiction, compliant mount disturbance,
  orbital sun lighting, rack materials, and camera radiation noise.
- A measured 1024-environment state profile and a conservative 128-environment
  64x64 RGB training default (256 camera environments also passed the sustained
  environment-only benchmark on the development laptop).
- RL-Games PPO hooks, teacher demonstration collection, behavioral cloning,
  play, and repeatable VRAM/FPS benchmarks.

## Supported stack

| Component | Pinned value |
| --- | --- |
| OS | Native Windows 11 x64 |
| Isaac Sim | 5.1.0 standalone |
| Isaac Lab | v2.3.2 (`37ddf626871758333d6ed89cf64ad702aef127d0`) |
| Python | Isaac Sim bundled Python 3.11 |
| Learning library | Isaac Sim fork of RL-Games (`python3.11` branch, resolved SHA recorded locally) |

Isaac Sim 5.1 publishes a 16 GB minimum VRAM requirement. The development
machine has 12 GB. On this machine, the sustained environment benchmark passed
at 1024 state environments and 256 camera environments under the project's
10.5 GiB budget. Those are environment-step results, not guarantees that a full
PPO optimizer or another laptop workload will fit; the benchmark script falls
back through safe counts.

## Installation

This repository deliberately pins Isaac Sim 5.1.0 and Isaac Lab v2.3.2. That
pair matches the recorded development environment; it is a reproducibility pin,
not a claim that 5.1.0 is NVIDIA's newest supported simulator release. As of
August 2026 NVIDIA marks the 5.1 documentation as unsupported; use this branch
to reproduce the recorded stack and evaluate a Sim/Lab upgrade on a separate
branch. The
[Isaac Sim 5.1 workstation guide](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/install_workstation.html)
and the [Isaac Lab v2.3.2 binary-install guide](https://isaac-sim.github.io/IsaacLab/v2.3.2/source/setup/installation/binaries_installation.html)
are the upstream references for this exact stack.

### 1. Install Isaac Sim manually

The Isaac Sim archive is a large NVIDIA download with an interactive license
flow, so downloading and extracting it manually is faster and more reliable
than hiding that step in a project script:

1. Download `isaac-sim-standalone-5.1.0-windows-x86_64.zip` from NVIDIA.
2. Extract it so `C:\isaac-sim\python.bat` exists.
3. Run `C:\isaac-sim\post_install.bat` once.
4. Run `C:\isaac-sim\isaac-sim.compatibility_check.bat` and resolve any red
   checks before installing Isaac Lab.
5. If this machine previously ran another Isaac Sim version, launch
   `C:\isaac-sim\isaac-sim.bat --reset-user` once. Do not clear working caches
   merely to reclaim disk space.

The UR10e USD is an NVIDIA-hosted asset. Keep the machine online for the first
environment launch so it can populate the asset cache; subsequent launches can
reuse the cache.

### 2. Inspect obsolete installations

The cleanup script is dry-run by default and reports the exact paths and sizes
it would remove:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\cleanup_old_isaac.ps1
```

After reviewing the list, `-Execute` first validates the retained simulator and
CUDA, writes `artifacts\sim_validation.json`, and only then deletes those exact
obsolete targets:

```powershell
.\scripts\cleanup_old_isaac.ps1 -Execute
```

The script preserves `C:\isaac-sim`, NVIDIA/Omniverse caches, generic package
caches, Docker data, and `D:\Isaac_Robots`. Deletion is permanent. Its old Lab
and Conda locations can be overridden with `-OldIsaacLabRoot` and `-CondaRoot`;
downloaded archive/PDF locations are development-machine-specific, so users
with a different Windows profile should remove their own copies manually after
the validation gate.

### 3. Install the pinned Lab and project

The setup reuses `C:\isaac-sim`, clones the pinned Isaac Lab source into the
ignored `.deps` directory, creates the `_isaac_sim` junction, installs the four
essential Lab packages, the pinned RL-Games fork, this project, and writes
`environment-lock.local.json`.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup_windows.ps1
```

UAC is optional. A normal PowerShell session is the fastest path because the
script enables repository-local `core.longpaths`. Only if Windows still reports
a long-path error, open one elevated PowerShell and enable the OS setting:

```powershell
Set-ItemProperty HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem `
  -Name LongPathsEnabled -Type DWord -Value 1
```

Re-running setup is safe when `.deps\IsaacLab` is the expected checkout. Use
`-SkipInstall` only to re-check paths and regenerate the local environment lock.

### 4. Validate before training

```powershell
C:\isaac-sim\python.bat scripts\validate_sim.py
C:\isaac-sim\python.bat scripts\smoke_env.py --profile teacher --teacher_steps 100
C:\isaac-sim\python.bat scripts\smoke_env.py --profile vision --vision_steps 32
```

## Train and evaluate

All commands use Isaac Sim's Python so `isaaclab` is imported only after the
simulation application starts.

```powershell
# Active six-axis policy: blade already secured; Level 0 is collision-free
C:\isaac-sim\python.bat scripts\train.py --task Isaac-ZeroG-Blade-Insertion-RigidGrasp-v0 --robustness_level 0 --num_envs 512 --max_iterations 800 --headless

# Vision student; the script enables cameras automatically
C:\isaac-sim\python.bat scripts\train.py --task Isaac-ZeroG-BladeSwap-Vision-v0 --num_envs 128 --headless

# Hardware selection
C:\isaac-sim\python.bat scripts\benchmark.py --profile all

# Learned secured-grasp insertion playback; selects the newest matching checkpoint
C:\isaac-sim\python.bat scripts\play.py --task Isaac-ZeroG-Blade-Insertion-RigidGrasp-Play-v0 --robustness_level 0 --num_envs 1 --steps 900 --real_time
```

For continuation, begin with [CLAUDE.md](CLAUDE.md). It contains the verified
checkpoint, exact evidence, blockers, and ordered roadmap without requiring a
new agent to read the entire repository.

Teacher-to-student transfer:

```powershell
C:\isaac-sim\python.bat scripts\collect_teacher.py --checkpoint <teacher.pth> --samples 250000
C:\isaac-sim\python.bat scripts\pretrain_student.py --dataset datasets\teacher_250k.h5
```

## Task interface

| Gym ID | Actor input | Default environments | Rendering |
| --- | --- | ---: | --- |
| `Isaac-ZeroG-Blade-Insertion-v0` | state; three learned translation increments | 512 | off |
| `Isaac-ZeroG-Blade-Insertion-Play-v0` | same as insertion training | 1 | on |
| `Isaac-ZeroG-Blade-Insertion-Robust-v0` | state; six Cartesian corrections | 512 | off |
| `Isaac-ZeroG-Blade-Insertion-Robust-Play-v0` | same as robust insertion training | 1 | on |
| `Isaac-ZeroG-Blade-Insertion-RigidGrasp-v0` | state; six corrections; fixed secured grasp | 512 | off |
| `Isaac-ZeroG-Blade-Insertion-RigidGrasp-Play-v0` | same as rigid-grasp training | 1 | on |
| `Isaac-ZeroG-BladeSwap-Teacher-v0` | privileged state | 1024 | off |
| `Isaac-ZeroG-BladeSwap-Vision-v0` | proprioception + RGB | 128 | 64x64 tiled RGB at 15 Hz |
| `Isaac-ZeroG-BladeSwap-Play-v0` | vision/play profile | 8 | on |

See the [handover](CLAUDE.md), [architecture](docs/architecture.md), and the
[Sim2Real randomization matrix](docs/sim2real_matrix.md) for design details.

## Validation status

The repository contains real local smoke and sustained capacity evidence. A
local nominal-insertion policy converged, but checkpoints are intentionally not
stored in Git and no real-hardware transfer result exists. The current measured
snapshot is:

| Check | Actual completed result | Scope |
| --- | --- | --- |
| Isaac Sim/CUDA launch | Passed | RTX 5070 Ti Laptop GPU, CUDA available |
| Teacher sustained benchmark | Passed | 1024 environments; 200 warm-up + 500 measured steps; 7,378.90 environment-steps/s; 1,037 MiB observed total GPU use |
| Vision sustained benchmark | Passed | 256 environments; 200 warm-up + 500 measured steps; 1,597.65 environment-steps/s; 2,266 MiB observed total GPU use |
| Vision sensor smoke | Passed | 8 environments, 64x64 RGB; finite observations, black background, material variation, and noise delta std 0.02469 |
| RL-Games integration | Passed | Teacher and vision two-epoch PPO checkpoints saved and each reloaded for 16 deterministic play steps; this is not convergence evidence |
| Phase-1 three-axis insertion | Promoted locally | 6,051/6,051 full-distance held-out episodes across seeds 1042/2042/3042, plus 100% near/medium checks on seed 1042; nominal wide rails and virtual grasp fixture only |
| Phase-2 robust task | Integration passed | CUDA smoke checkpoints saved at level 0 and level 4; six actions, zero gravity, no sensors, mass/friction/stiction ranges and compliant mount constructed; this is not convergence evidence |
| Secured-grasp Phase 2.6 | Level 0 promoted on one held-out seed | Epoch 700 achieved 3,028/3,028 deterministic successes across near/medium/full starts on seed 1060, with zero timeout, failure, instability, or non-finite termination. Levels 1--2 passed physics smoke but remain untrained; Level 3 stiction settling and Level 4 remain blocked. |
| Nominal insertion baseline | Diagnosed, not promoted | Superseded 300-iteration curriculum: 56.35% full-distance and 22.57% near-distance deterministic success on unseen seed 1042; all failures were timeouts and the 90% gate was not met |
| Mixed-curriculum axial baseline | Diagnosed, not promoted | Fresh 300-iteration run stayed correctly at Level 0 and achieved 1,292/2,000 (64.6%) near-distance deterministic success; lateral error remained above tolerance, motivating three-axis translation control |

See [CLAUDE.md](CLAUDE.md) for artifact provenance, exact limitations, and the
distinction between smoke, training success, and Sim2Real validation.
The compact machine-readable result is committed at
[`evidence/rigid_grasp_l0_seed1060.json`](evidence/rigid_grasp_l0_seed1060.json).

To reproduce and extend the checks:

```powershell
C:\isaac-sim\python.bat -m pytest -m "not isaac"
C:\isaac-sim\python.bat scripts\smoke_env.py --profile all
C:\isaac-sim\python.bat scripts\benchmark.py --profile all --quick
C:\isaac-sim\python.bat -m ruff check src scripts tests
```

Raw hardware JSON, checkpoints, datasets, and videos are intentionally untracked.
This keeps clones lean; publish selected checkpoints and demo media through a
GitHub Release and record the commit, seed, environment lock, and benchmark JSON
with each release.

## Research basis

The staged design follows NVIDIA's
[Isaac Lab gear-insertion workflow](https://isaac-sim.github.io/IsaacLab/develop/source/policy_deployment/02_gear_assembly/gear_assembly_policy.html),
which begins with an already-grasped part and progressively addresses transfer.
The Sim2Real roadmap follows OpenAI Dactyl's
[dynamics/appearance randomization and perception-control separation](https://openai.com/index/learning-dexterity/).
These references motivate the method; they do not make this project physically
validated.

## Current limitations

- Full teacher/student convergence is not part of the initial smoke-tested
  delivery and remains workload- and seed-dependent.
- Sustained environment stepping passed at 1024 teacher and 256 vision
  environments on this specific laptop. Full PPO adds network, optimizer, and
  rollout memory, so 1024/128 remain the recommended training starting points
  and should be re-benchmarked when other GPU applications are open.
- No real UR10e, flight-like rack, hardware-in-the-loop, or orbital dataset has
  been used yet. The current result demonstrates simulation infrastructure, not
  physical Sim2Real transfer.
- The rack and blades use inexpensive collision proxies rather than proprietary
  server CAD.
- Vision training is intentionally run at a lower parallel count than the
  state teacher on a 12 GB laptop GPU.
- The orbital sun is global to a vision scene, so lighting is correlated across
  environments during a reset. Rack materials remain per-environment.
- Gaussian image noise is an uncalibrated radiation proxy; hot pixels, temporal
  persistence, rolling shutter, lens effects, and radiation dose response are
  future work.
- A cold asset cache requires network access to NVIDIA's hosted UR10e USD. A
  missing/blocked asset endpoint prevents environment construction even when
  local Python packages are healthy.
- Contact forces are solved by PhysX but are not exposed as observations; this
  avoids costly contact-report processing across every environment.
- The promoted insertion uses a fixed joint representing an already-secured
  blade. Physical grasp acquisition is not solved.
- Tight bottom-shelf collision is disabled after it caused non-physical
  lateral ejection; side-rail contact remains enabled in later levels.
- Level 3 high-stiction insertion reaches valid geometry but does not reliably
  settle below velocity limits, so Levels 3--4 are blocked.
- The 3,028/3,028 result uses one held-out seed; two additional seeds and
  terminal-metric capture are required for release-grade evidence.

## License

BSD-3-Clause.
