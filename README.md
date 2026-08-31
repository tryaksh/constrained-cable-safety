# Orbital Robotic Servicing Lab

A zero-gravity simulation testbed for deciding whether a robot can service a
module-rack configuration, which constraint prevents service, and whether
isolated manipulation skills survive real chain handoffs.

Everything here is simulated. Nothing has run on hardware, and nothing is a
flight-readiness claim.

## Executive status

The continuous state-task chain captures, extracts, carries, inserts and releases
a compute module with the robot holding it throughout. Under the strict current
rule -- release both robot-side supports and recheck rack-only seating for 0.70 s
-- it scores **70.83%** (17/24) over three held-out seeds, Wilson 95%
**[50.8%, 85.1%]**. It fails the 95% gate. There is no world constraint,
teleport, direct module pose write or hidden carrier.

The prior **97.92%** (94/96) result is a legacy supported-settle baseline. It did
not include the independent rack-only recheck and is not the current completion
rate. A paired hand-first release arm loses at 12/24, so release sequencing is
not the repair; rack-side retention/contact is the current physical blocker.

That point result is not yet a serviceability envelope. The current analytical
versus simulation validator returns **not qualified**:

- entry attitude is supported in simulation;
- rack-clearance and module-section arms contain mismatches;
- a +10 mm rail-stop error is kinematically feasible but fails in simulation;
- capture clearance is analytical-only; and
- load-path and base-compliance evidence is idealized or absent.

The learned skills also do not support an “end-to-end RL” claim. On the current
rack, unchanged-checkpoint grasp scores **86.90%** and extraction **87.64%**;
both miss their 95% gates and overlap their earlier **85.69%** and **87.75%**
results. Learned v24
insertion scores 36.77% in isolation and **0.00%** in the chain, so the guarded
controller remains selected. The older insert baseline is **0.00% over 1,536
episodes**. Its three reward arms ended at 84.26, 84.61 and 84.58 mrad against a
**52.4 mrad** tolerance: the objective did not move the interface-limited angle.

The paired handoff audit makes the insertion gap concrete. With the real
fixed-to-compliant load path, v24 is **0/768** from reset stations 0–3, rises to
**786/960** over stations 4–8, and returns to **0/96** on real predecessor
handoffs. Guarded insertion is **94/96** on those handoffs. The skill certificate
therefore describes the late stroke, not the state its caller supplies.

The old passing RGB-D certificate is retracted because its tag floated 90 mm
above the current module. With the physically flush tag, critical-rack detection
is **43.27%** against a 99% gate. Pose precision is acceptable when detected;
visibility is not. Dropout propagation is now enabled only after verified
physical capture, and the live service stays unavailable until current evidence
passes.

## Method

The intended output is a simulation-guided qualification method:

1. derive constraints from module, rack, capture interface, robot and load path;
2. intersect them into a candidate serviceability envelope;
3. test points inside, outside and near every boundary without changing the
   tolerances;
4. preserve every losing or contradictory arm; and
5. replay learned and guarded controllers at every reset station and at recorded
   predecessor handoffs on identical states and seeds.

The control split follows the physics: PPO for capture and extraction contact,
collision-checked IK for free-space carry, guarded insertion while the estimate
remains inside the entry envelope, and release only after 0.70 s of settled
seating.

## Trust and scope

[`docs/NOW.md`](docs/NOW.md) is the concise verified state and
[`evidence/MANIFEST.json`](evidence/MANIFEST.json) is the mechanical evidence
index: 32 canonical, 11 retracted and 140 historical reports. Quote canonical;
never quote retracted.

Twelve reports contain runtime source bindings. One is mechanically `RECOVERED`,
two new reports record clean source revisions, and nine older reports produced
from **uncommitted** source are `LOST`.
The runs happened, but their exact code cannot be reproduced. T0 in
[`docs/NEXT_WORK.md`](docs/NEXT_WORK.md) therefore remains for any lost result a
final claim needs.

The current robot-side latch geometry is visual. Its load path is an idealized
fixed joint while rigid and a spring-damper while compliant. The robot root is
fixed to the world, so the authored base spring does not deflect. A historical
simulation probe compared about 6 N of idealized retention with a derived
**66.4 N** axial requirement; that is a diagnostic, not a hardware load rating.
No real camera, connector, cable, thermal path, orbital dynamics or compliant
spacecraft base is qualified.

## Run

Install instructions and Isaac Lab version requirements are in
[`docs/INSTALL.md`](docs/INSTALL.md). A clone does not include the learned
checkpoints under `logs/` or `checkpoints/`; evidence records their hashes.

```powershell
# CPU-only trust gate
.\.venv\Scripts\python.exe -m pytest -m "not isaac and not camera and not benchmark"
.\.venv\Scripts\python.exe scripts/build_evidence_manifest.py --check
.\.venv\Scripts\python.exe scripts/check_source_provenance.py --depth 200

# One end-to-end simulator run, with reachable checkpoints
scripts\run_robot_carried.sh rail

# Paired v24/guarded insertion at all stations and real handoffs
& .\scripts\run_conditioned_insertion.ps1 -IncludeChainHandoffs
```

The frozen question, variables, baselines, metrics, experiment matrix and
evidence gates are in [`docs/PAPER_PLAN.md`](docs/PAPER_PLAN.md). Do not draft a
manuscript until those gates close.
