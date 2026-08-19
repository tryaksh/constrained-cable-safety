# Design-for-serviceability: robotic replacement of a modular compute unit

An NVIDIA Isaac Lab project asking a specific engineering question:

> **What service interface does a 6-axis manipulator need in order to capture,
> extract, and insert a modular compute unit in microgravity, and what loads
> does that impose?**

The bottleneck in robotic servicing of modular hardware is usually assumed to be
the controller. Measured here, it is not. It is that modules are not designed to
be grabbed:

| Interface | Axial holding capacity |
| --- | ---: |
| Parallel-jaw grip on a smooth post | about **6 N** |
| Requirement, from the insertion task's own contact reaction | **66.4 N** |
| Head-on tapered capture interface on the module | **69 N** |

The 6 N result is structural, not a tuning failure: the gripper closes along one
axis while the module leaves along another, the rails must leave that axis free,
and flat pads can then oppose it only by friction. Closing harder makes it
worse. No controller fixes that, so the interface moves onto the module and the
approach aligns with the pull axis.

The design output is **[the service interface specification](docs/service_interface_spec.md)**,
which states what a module must present to be serviceable by a 2F-85-class
gripper, with every dimension traced to a measurement. It is written to be
usable without reading the simulation. It also specifies the *rack*, because one
of the strongest results here is that a 16.6 mm lead-in flare on the rack is
load-bearing: remove it and two fully trained insertion policies both score 0%,
even with no pose uncertainty at all.

## The one finding, in one sentence

**Attitude, not position, is the binding constraint on every operation that
moves a payload through free space** — and it binds in two independent places
that took most of the project to tell apart, because each one masks the other.

*On the grip.* A parallel-jaw grip on a passive feature cannot resist a moment
about its closing axis: the pads' contact normals lie along that axis, and a
normal force cannot oppose a moment about its own direction. Only friction can,
and friction loses. The clearest single piece of evidence is a module being
carried between bays that swung **end-for-end** about its grip — the
tool-to-module offset changed sign, −0.335 m to +0.305 m — while the grip error
itself read a healthy 24 mm, because the pads were still exactly where they had
been.

*On the arm.* Near the folded configuration servicing requires, reach and
attitude **trade**, and steeply — about 7.5 metres per radian. Drive the
orientation at full authority and the tool stops **88.7 mm** short of the pose
extraction has to finish in; allow 0.0114 rad of attitude error and the same
solver reaches it to 3.6 mm. Remove the orientation command entirely and every
depth is reachable to 0.00 mm, including 64 mm beyond the furthest the task
needs. **The arm can go where the task needs it; it cannot go there pointing the
right way.** ([`relocation_reach_boundary.json`](evidence/relocation_reach_boundary.json))

Three other findings are non-obvious and are the reason this repository is worth
reading rather than skimming.

**1. Chained success has repeatedly landed below the product of its parts, and
the cause was never policy capacity.** Every time it was a hand-off, a phase
clock, or a controller state. Installation went 89.41% → **96.35%** with no
retraining at all: a truncating clock, and a settling window that kept squeezing
a module that was already seated.

**2. A skill's own success rate and what a chain needs from it are different
questions.** Capture scores 88.78% alone and *fails* its gate, while the same
checkpoint overruns its capture phase once in 192 chained installations — because
the skill task ends an episode when its failure predicate fires and the chain
simply lets the capture finish.

**3. A single run is not a measurement, and this repository learned that twice
in opposite directions.** A one-seed vision sweep once reported a gate *pass*
that three seeds overturned. Three seeds then reported a gate *failure* that a
re-run overturns — one of the three scored 25.00% and re-runs at 80.73% with
every input identical. Both are in
[`evidence/RETRACTED.md`](evidence/RETRACTED.md).

## In plain terms, before the numbers

The module has a stub sticking out of its front face, like a short door handle.
It is wedge-shaped — fatter at the free end, narrowing where it meets the module
— with a wide flat plate behind it, and the robot's two-finger hand closes on the
wedge like a clothes peg. The fat-end-out shape is the whole trick: when the robot
pulls, the fat part is dragged into the fingers and they bite harder instead of
slipping. The plate behind stops the hand sliding in too far.

That holds the module's *position* well — 69 N of pull against the 66.4 N the job
needs. What it cannot hold is the module's *orientation*. A two-finger clamp
squeezes along one line, and squeezing along a line cannot stop a part twisting
about that same line; only friction can, and friction loses. On Earth this rarely
shows, because a part rests on something and its own weight helps. In freefall the
moment the rack lets go, the module is a free-floating body held at one spot.

So the obvious fix was tried: replace the wedge with a flat-sided block and a lip
in front of it — a cotton reel — so the fingers drop into the groove and are
trapped by shape rather than by squeezing. It grips far better on every
measurement. **It cannot be fitted, for a dull reason: there is no room for the
lip.** The hand's own palm and knuckles occupy the space directly in front of
where the fingertips close. About 8 mm of clearance exists there; the lip needs
about 44 mm, or the fingers simply spread and pop over it. Making the block
smaller is worse, not better, because a smaller block lets the hand close further
and brings the knuckles in.

> **The engineering conclusion, and the most useful thing here:** keep the module
> dumb and put the locking geometry in the **end-effector**, not on the part.
> V-grooved fingers, or a powered latch that engages after the grip closes. That
> is what flight hardware already does — the station's arm snares a fixture and
> then rigidises it; the ISS manipulator grips a square boss and then drives a
> bolt. Grip first, lock second. None of them makes friction load-bearing.
>
> This is a claim about *where* the geometry goes, not a claim that microgravity
> gripping is infeasible. The gripping works. It is the twisting that does not,
> and the part is the wrong place to fix it.

## What works, what does not, and what was refuted

Every number names the file in [`evidence/`](evidence/) it came from.

### Works

| | Rate | Evidence |
| --- | ---: | --- |
| **Removal chain** — capture, break free, pull 495 mm clear, still settled 0.7 s later | **98.78%** | `workflow_remove_retain_certification.json` |
| **Installation chain** — capture at the mouth, seat, still seated 0.7 s later | **96.35%** | `workflow_install_clock30retain_certification.json` |
| Extraction skill | 99.02% | `grapple_extract_v14reset_certification.json` |
| Insertion skill, one bay | 98.27% | `grapple_insert_v6clock30_certification.json` |
| Insertion skill, **either bay of two**, one policy, gated on the worse bay | 98.34% | `grapple_insert_two_slot_certification.json` |
| Interface axial hold | 69.0 N against 66.4 N required | `grapple_pin_axial_pull_gate.json` |
| Module pose from 64×64 RGB on a two-bay rack, plus which bay holds it | 2.81 mm mean, occupancy 100% | `module_pose_head_two_slot.json` |
| Onboard inference | 0.73 ms CPU, 2.2% of the control period | `inference_budget.json` |

Both chains are 576 workflows on three held-out seeds, zero instability and zero
non-finite terminations, with the module held by real pad-against-pin contact
throughout and no fixed joint anywhere.

### Does not work, with the measurement that says why

| | State | Why |
| --- | --- | --- |
| Capture as a standalone skill | **88.78%, fails its 95% gate** | 1,008 of 1,011 failures are refusals rather than timeouts, and the chain that uses the same checkpoint overruns capture once in 192. Two different questions; neither may be quoted as the other |
| **Relocation, bay 1 → bay 2** | **Does not complete** | A kinematic wall, mapped rather than inferred. Extraction ends 88.7 mm past it and the transit's retreat needs 167 mm past it. Attitude free, every depth is reachable to 0.00 mm. No leg order fixes it; lifting over the rack's flares does not move it either |
| The keyed interface redesign | **Cannot be built on this gripper** | Its nose flange overlaps the palm by 45.0 mm at *every* closure, including fully open. No forward axial stop fits at any key height: 7.9 mm of room against the 43.5 mm a splay-proof stop needs |

### Built, measured, refuted

| | Result |
| --- | --- |
| Anti-yaw yoke | Cost insertion 67 points to buy extraction 0.13. **Code deleted** |
| Modelled latch | Jams the module in the rails; extraction travel 458 mm → 25 mm |
| Raising the gripper drive to its rated 24.96 N·m | Capacity *fell* — a wedge turns closing force into thrust along the pull axis |
| Force sensing for pose robustness | Worse beyond the trained range. Force has to be actionable, not merely observable |
| Fine-tuning insert on the chain's own distribution | 300 epochs took the install chain 89.41% → 88.37% |
| Reproducing the insert hand-off as a reset | Four attempts: 0.00%, 26.32%, 47.17%. Running the real capture reproduces it at 93.06% |

The full list, each with its evidence file, is in
[docs/claim_vs_evidence.md](docs/claim_vs_evidence.md) and
[docs/status.md](docs/status.md). Negative and retracted results are kept
deliberately: [`evidence/RETRACTED.md`](evidence/RETRACTED.md) lists every figure
that has been withdrawn and what replaced it.

**[Claim versus evidence](docs/claim_vs_evidence.md)** states precisely what this
repository has and has not shown. This is a research demonstration of
contact-rich field servicing, not a flight-readiness claim and not an orbital
data-centre digital twin.

## What is implemented

- Zero gravity, GPU PhysX, Fabric cloning, and collision-only manipulation
  without contact-report sensors.
- Promoted Level-0, Level-1, and Level-2 secured-grasp insertion policies.
- A reset-safe evaluator that snapshots each episode's terminal pose, velocity,
  and cycle time before Isaac Lab's automatic reset, and pools runs into a
  single gated report with Wilson 95% confidence intervals.
- Random blade mass, guide friction/stiction, compliant mount disturbance,
  orbital sun lighting, rack materials, and camera radiation noise.
- A measured 1024-environment state profile and a conservative 128-environment
  64x64 RGB training default (256 camera environments also passed the sustained
  environment-only benchmark on the development laptop).
- RL-Games PPO hooks, state-teacher demonstration collection, behavioral
  cloning, play, and repeatable VRAM/FPS benchmarks.

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
C:\isaac-sim\python.bat scripts\smoke_env.py --profile state --state_steps 100
C:\isaac-sim\python.bat scripts\smoke_env.py --profile vision --vision_steps 32
```

## Train and evaluate

All commands use Isaac Sim's Python so `isaaclab` is imported only after the
simulation application starts.

```powershell
# Active six-axis policy: blade already secured; Level 0 is collision-free
C:\isaac-sim\python.bat scripts\train.py --task Isaac-ZeroG-Blade-Insertion-RigidGrasp-v0 --robustness_level 0 --num_envs 512 --max_iterations 800 --headless

# Vision insertion scaffold; the script enables cameras automatically
C:\isaac-sim\python.bat scripts\train.py --task Isaac-ZeroG-Blade-Insertion-Vision-v0 --num_envs 128 --headless

# Hardware selection
C:\isaac-sim\python.bat scripts\benchmark.py --profile all

# Learned secured-grasp insertion playback; selects the newest matching checkpoint
C:\isaac-sim\python.bat scripts\play.py --task Isaac-ZeroG-Blade-Insertion-RigidGrasp-Play-v0 --robustness_level 0 --num_envs 1 --steps 900 --real_time
```

Recording the demonstration. `--inspection_view array` frames whatever parallel
grid the cloner produced, so one clip shows several workcells running the same
learned policy at once. Recording runs disable Fabric cloning because
Fabric-cloned prims do not all reach the RTX renderer; physics is unchanged.

```powershell
C:\isaac-sim\python.bat scripts\play.py --task Isaac-ZeroG-Blade-Insertion-RigidGrasp-Play-v0 --checkpoint <l2.pth> --robustness_level 2 --curriculum_stage 2 --num_envs 9 --seed 9162 --headless --video --video_length 300 --video_dir artifacts\demo\array --inspection_view array
```

For continuation, begin with [CLAUDE.md](CLAUDE.md). It is a short routing file
that states the mission, the operating rules, and which document to open for a
given task, so a new agent does not have to read the whole repository. Measured
results and limitations live in [docs/status.md](docs/status.md); ordered next
work and prior art live in [docs/roadmap.md](docs/roadmap.md).

State-teacher to vision-student transfer. The dataset records each image
alongside the teacher's action *and* the true blade-to-goal error, which is the
supervision a pose-regression head needs:

```powershell
C:\isaac-sim\python.bat scripts\collect_teacher.py --checkpoint <force_feedback.pth> --samples 250000
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
| `Isaac-ZeroG-Blade-Insertion-ForceLimited-v0` | rigid grasp plus a contact-force penalty and 60 N abort | 512 | off |
| `Isaac-ZeroG-Blade-Insertion-StrictForceLimited-v0` | the same at 1.5 N free allowance and a 30 N abort | 512 | off |
| `Isaac-ZeroG-Blade-Insertion-ForceFeedback-v0` | strict force task plus 7 contact-force observations; must be trained from scratch | 512 | off |
| `Isaac-ZeroG-Blade-Insertion-ForceFeedback-Play-v0` | force feedback judged at the shared 60 N limit | 1 | on |
| `Isaac-ZeroG-Blade-Insertion-Uncertain-v0` | the slot physically moves; the actor is told the wrong place and must feel for it | 512 | off |
| `Isaac-ZeroG-Blade-Insertion-UncertainBlind-v0` | the same, with the contact wrench removed: the matched ablation | 512 | off |
| `Isaac-ZeroG-Blade-Insertion-GuidedSlot-v0` | rigid grasp into a channel with lips and a funnelled mouth | 512 | off |
| `Isaac-ZeroG-Blade-GrapplePin-Capture-v0` | head-on capture on the grapple pin; the interface spec's scene | 512 | off |
| `Isaac-ZeroG-Blade-GrapplePin-Grasp-v0` | learned head-on capture; the only skill that commands the gripper | 512 | off |
| `Isaac-ZeroG-Blade-GrapplePin-Extract-v0` | pull a captured module 495 mm clear of the rack | 512 | off |
| `Isaac-ZeroG-Blade-GrapplePin-Insert-v0` | insert a module held by pad-against-pin contact, no fixed joint | 512 | off |
| `Isaac-ZeroG-Blade-GrapplePin-Workflow-v0` | the three skills chained in one episode; **never train on this** | 1 | on |
| `Isaac-ZeroG-Blade-Insertion-Vision-v0` | proprioception + contact wrench + RGB; **untrained P3 scaffold** | 128 | 64x64 tiled RGB at 15 Hz |
| `Isaac-ZeroG-Blade-Insertion-Vision-Play-v0` | same, plus the state teacher's own group for demonstration capture | 8 | on |

The eight-phase full-swap task (`Isaac-ZeroG-BladeSwap-Teacher/-Vision/-Play-v0`)
was **deleted on 2026-08-10** and must not come back: four of its five servicing
stages had no physics content, and `tests/test_configuration_contract.py` fails
if the swap state machine returns.

The three head-on grapple-pin skills were deleted with it and **restored on
2026-08-11**. Deleting them was defensible on the evidence at the time — all
three had failed — but each had failed for a cause identified and corrected in
the same session and then never retested. Retested, they chain into two
servicing workflows. See [docs/status.md](docs/status.md) and
[CLAUDE.md](CLAUDE.md).

See the [handover](CLAUDE.md), [architecture](docs/architecture.md), the
[perception plan](docs/perception_plan.md), and the
[Sim2Real randomization matrix](docs/sim2real_matrix.md) for design details.
The [status page](docs/status.md) carries every measured number.

## The question the current work answers

Every result above was produced on a task that **told the policy its exact pose
error**. With a rigid known object on a constrained axis and full observability
that is a motion-planning and force-control problem, and a scripted controller
solves it; reinforcement learning cannot demonstrate its value there.

The active experiment moves the learning to where uncertainty actually lives.
The rack's guide rails now shift laterally by an amount the policy is never
told, and contact against a rail is the only channel that carries it. Two
policies are trained from scratch on one configuration, one seed, and one
schedule, differing in exactly one thing: whether the actor can feel contact.

The deliverable is one falsifiable plot — success rate against pose-belief
error, force-aware against force-blind — which is the axis
[IndustReal](https://arxiv.org/abs/2305.17110) and
[FORGE](https://arxiv.org/abs/2408.04587) are evaluated on.

**It came out negative, and that is the finding.** Over 33,500 held-out episodes
the two policies are indistinguishable at and below the displacement they trained
on, and the force-aware one is *worse* beyond it while using about twice the
contact force. The cause is identified rather than guessed: the slot's lead-in
already handles a 4 mm offset mechanically, and a position-controlled arm gives a
policy no way to turn a force reading into compliance — so the only thing it can
do with force is push harder, which hurts. That makes an admittance action space
the precondition for force sensing to pay here, not an optimisation of it.

`docs/status.md` carries the curve, the contact-force measurement that explains
its direction, the limitations, and the two faults found while building the task
— one of which was that the obvious construction of the uncertainty is
recoverable from an observation the policy already has.

## Validation status

The repository contains real local smoke and sustained capacity evidence. A
local nominal-insertion policy converged, but checkpoints are intentionally not
stored in Git and no real-hardware transfer result exists. The current measured
snapshot is:

| Check | Actual completed result | Scope |
| --- | --- | --- |
| Isaac Sim/CUDA launch | Passed | RTX 5070 Ti Laptop GPU, CUDA available |
| State sustained benchmark | Passed | 1024 environments; 200 warm-up + 500 measured steps; 7,378.90 environment-steps/s; 1,037 MiB observed total GPU use |
| Vision sustained benchmark | Passed | 256 environments; 200 warm-up + 500 measured steps; 1,597.65 environment-steps/s; 2,266 MiB observed total GPU use |
| Vision sensor smoke | Passed | 8 environments, 64x64 RGB; finite observations, black background, material variation, and noise delta std 0.02469 |
| RL-Games integration | Passed | Two-epoch PPO checkpoints saved and each reloaded for 16 deterministic play steps; this is not convergence evidence |
| Phase-1 three-axis insertion | Promoted locally | 6,051/6,051 full-distance held-out episodes across seeds 1042/2042/3042, plus 100% near/medium checks on seed 1042; nominal wide rails and virtual grasp fixture only |
| Phase-2 robust task | Integration passed | CUDA smoke checkpoints saved at level 0 and level 4; six actions, zero gravity, no sensors, mass/friction/stiction ranges and compliant mount constructed; this is not convergence evidence |
| Secured-grasp Level 0 (collision-free) | Promoted on three held-out seeds | Epoch 700 achieved 9,086/9,086 deterministic successes across near/medium/full starts on seeds 1060/2060/3060 (Wilson 95% lower bound 0.9996), with zero timeout, failure, mount-instability, or non-finite termination. Terminal pose, velocity, and cycle-time metrics are captured before Isaac Lab's automatic reset. |
| Secured-grasp Level 1 (physical side rails) | Promoted on three held-out seeds | Fine-tuning the epoch-700 policy for 500 more PPO epochs achieved 9,014/9,014 deterministic successes on seeds 1061/2061/3061 with real wide side-rail collision and doubled reset joint noise (Wilson 95% lower bound 0.9996), zero instability. Stage-0 terminal axial error improved from 4.15 mm to 1.65 mm. |
| Secured-grasp Level 2 (tight rails + 5–15 kg mass) | Promoted on three held-out seeds | Fine-tuning the Level-1 policy for 600 more PPO epochs achieved 9,021/9,021 deterministic successes on seeds 1062/2062/3062 with 1.5 mm side clearance and blade mass randomized over an observed 5.00–14.97 kg. Full-distance cycle time improved to 7.20 s median. Level 3 stiction settling and Level 4 remain blocked. |
| Force-limited insertion | Tried, negative result | A force budget and abort hold 100% success with zero aborts, but two penalty strengths — the stronger charging the same order as the success reward — changed mean contact by 2.6% and impulse not at all. Only the worst case moved, and that is the abort clipping the tail. The evidence points at the policy having no force feedback and at a geometric contact floor, so the next step is force in the observation space or an admittance action space, not a bigger penalty. |
| Force feedback in the observation space | Measured against a matched control | Adding seven contact-force values to the observation and retraining from scratch cut contact impulse 59% at the mean, 89% at the median, and 40% at p95, with mean cycle time unchanged and peak contact force unchanged. A control policy trained from scratch on the identical schedule with the observation left alone isolates the effect to sensing. Cost: three force-limit aborts in 4,518 held-out episodes, so 99.93% rather than 100%. |
| Learned grasping | Blocked by a measured geometry bug | The handle is configured 0.179 m from the wrist flange while the fingers only obstruct on the blade between about 0.06 and 0.15 m, so they close past it. PhysX reports 0.0 N of finger/blade contact across the whole finger range, drive torque stays at 0.39 N·m of a 10 N·m limit, and the grasp transmits 0 N of the 66.4 N the insertion contact reaction demands. Grasping is a geometry fix first, not a training problem. |
| Insertion contact load | Measured, not constrained | Peak contact force over 4,513 successful Level-2 episodes: mean 6.73 N, p95 16.56 N, max 66.36 N. It rises about sevenfold from the near start to the full start while success stays 100%, so success rate hides contact load entirely. Nothing bounds it yet. |
| Capability envelope | Measured, not certified | Pushing the Level-2 policy past its training range: success degrades gracefully with initial pose error (100% at 1–2×, 97.0% at 3×, 62.4% at 6×, 21.2% at 12×), failing by lateral divergence with **zero** instability at every point. Blade mass is flat at 100% out to 1–50 kg, which shows the task is nearly mass-insensitive in this regime and that the Level-2 mass claim is weak. |
| Insertion under a wrong pose belief | Measured, hypothesis refuted | Force-aware against a matched force-blind control over 33,500 held-out episodes and seven slot displacements. Identical at and below the trained 4 mm (99.87% against 99.77%); the force-aware arm is **worse** beyond it (96.94/87.50/74.07% against 99.56/94.90/82.31% at 6/8/10 mm) and uses about twice the peak contact force throughout. Diagnosis and limitations in `docs/status.md` |
| Insertion under a wrong pose belief, mechanism | Built and verified | The slot physically moves by up to 4 mm and the actor is told the nominal position. Fourteen simulator checks confirm the rails and lead-in move with the goal, the blade starts clear of the channel, nothing resets interpenetrating, and environments whose tool poses agree to 1.5 mm disagree about the true lateral error by 5.2 mm. Force-aware actor 58 values, force-blind 51, identical 71-value critic. No success number is claimed yet |
| Head-on grapple pin, three skills | Certified on three held-out seeds each; capture fails its gate | Extraction 99.02% (9,005 episodes) and insertion 98.27% (3,000) pass the 95% gate. **Capture is 88.78%** over 9,011 episodes — 100% / 87.12% / 79.22% by reset distance — and fails it. The module is held by pad-against-pin contact throughout, with no fixed joint. Extraction reached its number from 0.00% through three fixes, none of them mechanical: a reward for arriving settled, an attitude penalty whose clamp saturated at exactly the angle the policy parked at, and a reset that had been scoring a quarter of its episodes with the grip already lost. |
| Capture: the skill number and the chain number are different questions | Both measured | Capture's 88.78% is measured with a `capture_failed` termination that ends the episode the moment its predicate declares failure. The chains carry no such term: they hand over on a 10 mm grip held 0.30 s and otherwise let the capture keep closing for its full 10 s, which it does — chained installation overruns its capture phase **once in 192 episodes**. Adding such a termination to the chained-insert task was separately measured at 95.31% → 69.27%. So capture reliably produces the grip the chain requires *and* fails a fixed-episode predicate at the two widest resets. Neither number may be quoted as the other. |
| Insert into either bay of a two-bay rack | Certified on three held-out seeds, gated on the worse bay | One policy, both bays, trained 50/50 from the single-bay insert: **98.87% in bay 1 and 98.34% in bay 2**, pooled 98.60% over 3,004 episodes, zero instability and zero non-finite. The gate is the worse bay rather than the pool, because a policy that scores 99% in one and 90% in the other has not done the job. The second bay is the certified one displaced part for part, and the skill transferred almost immediately — 0 to 83% within 40 epochs of the curriculum unlocking it — which is evidence for that construction rather than for the policy. |
| Perception on a two-bay rack | Occupancy solved; **the camera arm passes its gate**, after the 2026-08-17 result was retracted | The pose head gains a bay-occupancy output and reads *which* bay holds the module at **100% exact-match** on 12,000 held-out frames against a 66.6% majority-class baseline. Re-certified 2026-08-18 over 576 workflows per arm on three held-out seeds: oracle **88.72%**, camera **84.90%**, blind **34.03%**. Camera is **3.82 points** behind oracle against a 10-point allowance and **50.9 points** above blind, so both halves of the gate pass. The superseded run reported 65.10% and a 23.6-point gap, and all of that difference was one seed that scored 25.00% and re-runs at 84.90%. **The caveat that replaces it:** the camera arm is not deterministic — six runs span 80.73–86.46% with a 2.13-point standard deviation, while the oracle arm reproduces exactly — so a single camera run is one draw, and the retracted outlier sits 28 standard deviations outside even that spread, which is a second mechanism rather than a bad draw of the first, and it is unidentified. |
| Relocation: bay 1 to bay 2 in one episode | Built, instrumented, **does not complete**, and the blocker is measured | The ORU changeout this roadmap is for, and it is not working. Capture, extraction and both insertions are certified and the chain still times out inside the lateral transit. The cause is a reach-versus-attitude trade the workcell cannot pay. Driving position and the head-on capture attitude at full authority, the tool parks at local x = −0.0258; extraction must finish 88.7 mm past that and the transit's retreat 167 mm past it. Two controls pin it down: with the orientation command removed **every** depth converges to 0.00 mm, so the arm can go there but not pointing the right way; and lifting the module over the rack's 50 mm lead-in flares — the one crossing that avoids the retreat — does not move the parking point at any lift from 0 to 200 mm. Surrendering attitude buys reach at about 7.5 m/rad, which is why the transit reached its waypoints at all and why the module swung end-for-end when it did. `evidence/relocation_reach_boundary.json`. |
| Chained servicing workflows | Certified on three held-out seeds, 576 workflows each | **Removal 98.78%** (Wilson 95% [97.51, 99.41]) and **installation 96.35%** ([94.49, 97.60]), both gates passed with zero instability. Each phase is given the episode length its own skill was certified on, derived automatically, so "it completes in the chain" cannot disagree with "it scores X alone". Installation reached its gate without retraining anything: the insert phase's clock was truncating successful insertions, and the settling window was still squeezing a seated module in breach of this project's own operating rule. Earlier figures of 14.06%, 84.38% and 89.41% are superseded; see `evidence/RETRACTED.md`. |
| Anti-yaw yoke | Built, trained against, refuted, **code deleted 2026-08-18** | Two walls dimensioned entirely from the measured gripper envelope, and a net negative: capture 95.55% → 88.81%, insertion 95.57% → 28.70%, extraction 0.00% → 0.13%. Re-tested later against a policy whose attitude error had concentrated onto the exact axis the walls oppose — removing the original excuse — it moved that axis by 0.0015 rad. The compliance is the pads camming open under load, not the gap between the walls, so no passive geometry reaches it. The measurements are kept in `docs/status.md` and `evidence/`; the code is not, and a contract test keeps it out. |
| Keyed interface redesign | Built on a branch, measured, **refuted by geometry** | Flat keyed faces between two axial stops, replacing the taper. It fixes rotation decisively — seated grip offset 0.0194 → 0.0007 m, seated attitude 0.0637 → 0.0013 rad, 120 N held at a 0.34 m arm without slip — and takes extraction to 0.00%, and five parameter corrections did not move that. The reason is structural: the nose flange sits **45.0 mm inside the gripper's palm at every closure**, including fully open, so the pads were never in the pocket. Nor can any version of it fit — a stop forward of the pads must exceed the aperture's own 43.5 mm half-opening to be proof against the pads splaying, and the room there is 7.9 mm. The corollary is the useful half: the 2F-85's throat is cone-shaped and the taper's profile matches it, so the taper doing double duty as funnel and clamp is the only shape this hand admits. `evidence/grapple_pin_keyed_interference.json`. |
| Modelled capture latch | Built, swept, refuted | A rated restoring torque engaged by a qualifying capture, which is what flight servicing hardware does instead of relying on friction. Swept 10–160 N·m against an unchanged policy so nothing is a training artefact: it moves the targeted rotation by 0.006 rad and collapses extraction travel from 458 mm to about 25 mm, because a torque on a module the rails still hold jams it in the rails. Off by default. |
| Extraction end pose reachability | Measured twice, and the two answers are a trade rather than a contradiction | A 2,000-step converged servo reaches the folded extraction end pose to 3.6 mm while holding the head-on attitude to 0.0114 rad. A later 3,000-step sweep driving orientation at full authority holds 0.0002 rad and gives up 88.7 mm at the same pose. Both are correct: near this configuration the Jacobian is ill-conditioned and attitude exchanges for reach at about 7.5 m/rad. The earlier reading that the workcell is "not the problem" was drawn from one side of that trade; the honest statement is that the workcell is marginal and the objective decides which way it fails. The `--robot_base_x` sweep published alongside it was inert — the flag edited a config that `configure_robustness` then overwrote — and is retracted. |
| Perception readiness | Blocking finding, before any training | The authored 64x64 camera resolves a 4 mm slot displacement as 0.13 pixels, so it cannot support the perception stage as configured. `docs/perception_plan.md` derives the fix — a narrower field of view rather than more pixels — and requires a rendered frame before images are collected |
| Nominal insertion baseline | Diagnosed, not promoted | Superseded 300-iteration curriculum: 56.35% full-distance and 22.57% near-distance deterministic success on unseen seed 1042; all failures were timeouts and the 90% gate was not met |
| Mixed-curriculum axial baseline | Diagnosed, not promoted | Fresh 300-iteration run stayed correctly at Level 0 and achieved 1,292/2,000 (64.6%) near-distance deterministic success; lateral error remained above tolerance, motivating three-axis translation control |

See [docs/status.md](docs/status.md) for artifact provenance, exact limitations,
and the distinction between smoke, training success, and Sim2Real validation.
The compact machine-readable result is committed at
[`evidence/rigid_grasp_l0_ep700_certification.json`](evidence/rigid_grasp_l0_ep700_certification.json).

To reproduce and extend the checks:

```powershell
C:\isaac-sim\python.bat -m pytest -m "not isaac"
C:\isaac-sim\python.bat scripts\smoke_env.py --profile all
C:\isaac-sim\python.bat scripts\benchmark.py --profile all --quick
C:\isaac-sim\python.bat -m ruff check src scripts tests
```

Held-out certification runs one `play.py` per curriculum stage and seed, then
pools the raw per-episode rows into a single report:

```powershell
C:\isaac-sim\python.bat scripts\play.py --task Isaac-ZeroG-Blade-Insertion-RigidGrasp-Play-v0 --checkpoint <ep700.pth> --robustness_level 0 --curriculum_stage 0 --num_envs 128 --episodes 1000 --seed 1060 --headless --report artifacts\stage0_seed1060.json --episode_metrics artifacts\episodes\stage0_seed1060.npz
C:\isaac-sim\python.bat scripts\aggregate_evaluation.py --episodes artifacts\episodes --output evidence\rigid_grasp_l0_ep700_certification.json --title "Level-0 held-out certification" --minimum_stage_success_rate 0.95
```

Physics characterization runs on their own, with no policy involved. The grasp
diagnostic sweeps a closure-by-pull-force grid in parallel and reports whether
the finger pads can reach the handle at all before reporting any capacity:

```powershell
C:\isaac-sim\python.bat scripts\grasp_diagnostics.py --headless --report evidence\grasp_axial_pull_gate.json
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

> **Read this list with one distinction in mind.** The repository contains two
> lineages. The **rigid-grasp** one holds the module with a PhysX fixed joint
> standing in for an already-secured grasp — that is where the 27,121-episode
> insertion certifications come from, and most of the caveats below are about it.
> The **grapple-pin** one holds the module by real pad-against-pin contact with no
> fixed joint anywhere, and that is where the chains, the interface result and the
> vision arms come from. A limitation of one is not automatically a limitation of
> the other, and this list used to read as though it were.

- **No policy consumes images directly.** A supervised pose head regresses the
  module's position and which bay holds it from 64×64 RGB, and the trained
  state policies then consume that estimate in place of the simulator's answer.
  That is enough to measure what perception *costs* — camera against oracle
  against blind — but it is not end-to-end visual control, and no policy has
  been trained on pixels.
- Sustained environment stepping passed at 1024 state and 256 camera
  environments on this specific laptop. Full PPO adds network, optimizer, and
  rollout memory, so 1024/128 remain the recommended training starting points
  and should be re-benchmarked when other GPU applications are open.
- No real UR10e, flight-like rack, hardware-in-the-loop, or orbital dataset has
  been used yet. The current result demonstrates simulation infrastructure, not
  physical Sim2Real transfer.
- The rack and blades use inexpensive collision proxies rather than proprietary
  server CAD.
- Vision runs at a lower parallel count than the state profile on a 12 GB laptop
  GPU. Whether the camera frames the rack well enough to regress a
  millimetre-scale pose is no longer unmeasured: 1.75 mm mean on one bay and
  2.81 mm on two, with bay occupancy exact at 100% against a 66.6% majority-class
  baseline (`evidence/module_pose_head.json`, `module_pose_head_two_slot.json`).
- **The camera arm is not deterministic and the state pipeline is.** Two runs
  with identical seed, task and checkpoints diverge at the first episode, while
  the oracle arm re-run a day later reproduces its per-seed rates exactly. Any
  camera measurement therefore needs replicating; a single run of it is one draw,
  and one such draw was published as a gate failure before being re-run.
- The orbital sun is global to a vision scene, so lighting is correlated across
  environments during a reset. Rack materials remain per-environment.
- Gaussian image noise is an uncalibrated radiation proxy; hot pixels, temporal
  persistence, rolling shutter, lens effects, and radiation dose response are
  future work.
- A cold asset cache requires network access to NVIDIA's hosted UR10e USD. A
  missing/blocked asset endpoint prevents environment construction even when
  local Python packages are healthy.
- Contact forces are solved by PhysX and are exposed as observations only on the
  force-feedback task, which pays for contact reporting and disables Fabric
  cloning. Every promoted policy runs without them.
- **The rigid-grasp insertion lineage** uses a fixed joint representing an
  already-secured blade, and on it `tool_to_handle_error_m` is a tautology rather
  than a grip audit. Its old contact-grasp variant never gripped anything: the
  handle sat 0.179 m from the wrist flange, outside the 0.06–0.15 m band the
  fingers reach. **The grapple-pin lineage solved that** and is what the chains
  run on — real pad-against-pin contact, no fixed joint, 69 N of measured axial
  hold — so "physical grasp acquisition is not solved" is true of the older
  lineage only.
- Peak contact force has resisted every intervention tried: two reward-penalty
  strengths and full force feedback with a matched control. Only accumulated
  impulse responded.
- Tight bottom-shelf collision is disabled after it caused non-physical
  lateral ejection; side-rail contact remains enabled in later levels.
- Level 3 high-stiction insertion reaches valid geometry but does not reliably
  settle below velocity limits, so Levels 3--4 are blocked.
- Because every certification episode succeeded, the reported terminal error
  distribution is bounded by the success criterion itself. It shows where
  inside the tolerance box the policy lands, not accuracy independent of it.
  The capability-envelope sweeps exist to cover that gap.
- Blade-mass robustness is close to vacuous for this task: in zero gravity with
  a fixed-joint grasp and millimetre-scale quasi-static motion, mass barely
  enters the dynamics, and a sweep to 1–50 kg is still 100%.
- Contact force is measured but not limited. There is no force budget, no
  abort-and-retry, and no connector model, so nothing here demonstrates the
  insertion would not damage a real pin.
- Level-0 margin is thin on two axes: terminal axial error reaches 11.96 mm of
  the 12 mm limit and orientation error reaches 0.0484 of the 0.0524 rad limit.
  Lateral error and blade velocities keep comfortable margin.
- Only one PPO training seed (60) produced the promoted policy. The three
  certification seeds are held-out *evaluation* seeds; training repeatability
  across seeds is untested.
- `train.py --smoke`'s scripted axial feasibility probe is now scoped to the
  contact-grasp family it was written for. On a rigid grasp the blade is welded
  to the tool, so axial feasibility holds by construction and the probe tested
  nothing while failing on its own 300-step budget.

## License

BSD-3-Clause.
