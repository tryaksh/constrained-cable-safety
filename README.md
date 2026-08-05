# Autonomous Server Blade Swap in Zero-G

An NVIDIA Isaac Lab `ManagerBasedRLEnv` project for training a UR10e with a
Robotiq 2F-85 gripper to remove a failed compute blade, stow it, acquire a
replacement, and insert the replacement in a microgravity data-center rack.

The project is still in state of stabilization and is being actively worked upon. 
It separates a high-throughput privileged-state teacher from a
camera-based student so the final policy has a defensible Sim2Real story rather
than relying on simulator-only object poses at deployment.

## What is implemented

- Zero gravity, GPU PhysX, Fabric cloning, and collision-only manipulation
  without contact-report sensors.
- A vectorized eight-phase full-swap task with insertion-first curriculum.
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
# State teacher
C:\isaac-sim\python.bat scripts\train.py --task Isaac-ZeroG-BladeSwap-Teacher-v0 --num_envs 1024 --headless

# Vision student; the script enables cameras automatically
C:\isaac-sim\python.bat scripts\train.py --task Isaac-ZeroG-BladeSwap-Vision-v0 --num_envs 128 --headless

# Hardware selection
C:\isaac-sim\python.bat scripts\benchmark.py --profile all

# Policy playback; omit --checkpoint to select the newest teacher checkpoint
C:\isaac-sim\python.bat scripts\play.py --policy teacher --steps 600
```

For a guided, plain-English tour and exact commands that open the live Isaac
Sim GUI, start with the [PM and live-simulation guide](docs/pm_guide.md).

Teacher-to-student transfer:

```powershell
C:\isaac-sim\python.bat scripts\collect_teacher.py --checkpoint <teacher.pth> --samples 250000
C:\isaac-sim\python.bat scripts\pretrain_student.py --dataset datasets\teacher_250k.h5
```

## Task interface

| Gym ID | Actor input | Default environments | Rendering |
| --- | --- | ---: | --- |
| `Isaac-ZeroG-BladeSwap-Teacher-v0` | privileged state | 1024 | off |
| `Isaac-ZeroG-BladeSwap-Vision-v0` | proprioception + RGB | 128 | 64x64 tiled RGB at 15 Hz |
| `Isaac-ZeroG-BladeSwap-Play-v0` | vision/play profile | 8 | on |

See the [PM and live-simulation guide](docs/pm_guide.md),
[architecture](docs/architecture.md), and the
[Sim2Real randomization matrix](docs/sim2real_matrix.md) for design details.

## Validation status

The repository contains real local smoke and sustained capacity evidence. It
does not yet contain a converged policy or real-hardware transfer result. The
current measured snapshot is:

| Check | Actual completed result | Scope |
| --- | --- | --- |
| Isaac Sim/CUDA launch | Passed | RTX 5070 Ti Laptop GPU, CUDA available |
| Teacher sustained benchmark | Passed | 1024 environments; 200 warm-up + 500 measured steps; 7,378.90 environment-steps/s; 1,037 MiB observed total GPU use |
| Vision sustained benchmark | Passed | 256 environments; 200 warm-up + 500 measured steps; 1,597.65 environment-steps/s; 2,266 MiB observed total GPU use |
| Vision sensor smoke | Passed | 8 environments, 64x64 RGB; finite observations, black background, material variation, and noise delta std 0.02469 |
| RL-Games integration | Passed | Teacher and vision two-epoch PPO checkpoints saved and each reloaded for 16 deterministic play steps; this is not convergence evidence |

See the [validation ledger](docs/validation.md) for artifact provenance,
observation shapes, exact commands, and the distinction between smoke, scale,
training, and Sim2Real validation.

To reproduce and extend the checks:

```powershell
C:\isaac-sim\python.bat -m pytest -m "not isaac"
C:\isaac-sim\python.bat scripts\smoke_env.py --profile all
C:\isaac-sim\python.bat scripts\benchmark.py --profile all --quick
C:\isaac-sim\python.bat -m ruff check src scripts tests
```

Hardware JSON, checkpoints, datasets, and videos are intentionally untracked.
This keeps clones lean; publish selected checkpoints and demo media through a
GitHub Release and record the commit, seed, environment lock, and benchmark JSON
with each release.

## Publish to GitHub

GitHub authentication is intentionally a manual publication step. Run the
status check first; if it reports an invalid stored token (the current state on
the development workstation), re-authenticate in the browser:

```powershell
gh auth status
gh auth login -h github.com --web --git-protocol https
gh auth status
```

After authentication, inspect before publishing. If the remote repository
already exists, add it and push the current branch; otherwise create it:

```powershell
git status --short
git remote -v
git add .
git status --short
git commit -m "Initial zero-g blade-swap environment"
gh repo create autonomous-zero-g-blade-swap --public --source . --remote origin
git push -u origin HEAD
```

If `origin` already exists, skip `gh repo create` and verify its URL before the
push. Create a release only after the acceptance gates in the validation ledger
pass; attach a short full-swap video, selected checkpoint, environment lock,
and benchmark JSON rather than committing large binaries to the repository.

Do not commit `environment-lock.local.json`, `.deps`, datasets, logs, or raw
checkpoints. The included GitHub Actions workflow runs lightweight lint and
unit/contract tests on Linux; Isaac/RTX smoke and hardware benchmarks remain
manual Windows GPU gates.

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

## License

BSD-3-Clause.
