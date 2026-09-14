# Agent instructions

Read this file, [ROADMAP.md](ROADMAP.md), then [README.md](README.md).
The four measurement studies are closed. The completed application is the
Recovery Decision Inspector, which exposes the existing policies without a
simulator. No further study or application is queued.

## Maintained documents

Maintain exactly these five documents:

| File | Purpose |
| --- | --- |
| [README.md](README.md) | Project, findings, setup and use |
| [ROADMAP.md](ROADMAP.md) | Verified state, limitations and deferred work |
| [AGENTS.md](AGENTS.md) | Operating rules and commands |
| [docs/REPO_MAP.md](docs/REPO_MAP.md) | Repository history and archive locations |
| [docs/PEG_INSERTION.md](docs/PEG_INSERTION.md) | Retired peg-insertion campaign |

Everything under `docs/handover/` is immutable history. Do not update a handover
to describe today's repository. Stage records and existing `PROGRESS.md` logs
under `artifacts/cell/` and `artifacts/showcase/` are committed exceptions; do not
create another handoff document.

## Scope

- There is no publication track: no paper or venue. The repository is the deliverable.
- Do not start a fifth study, refit the safety layer or rerun a fitted block for
  better numbers. A fixed replay used to verify software is not a new result.
- The task is held, clip-preserving seating before gripper release. The v6
  routing task requires all five clips to remain held. It is a separate task
  version; earlier blocks are never rescored under it.
- Do not claim latching, grasp reliability, real perception, hardware transfer
  or force-certified safety. The estimator uses simulator pose plus declared error.
- The inspector's recommendations are advisory. Its default is the existing
  conservative policy. It does not execute actions or repair the known failure
  of the single-clip fitted threshold on the five-clip rig.
- The portfolio package is outside this repository at
  `D:/constrained-cable-portfolio/`. Do not add it here or build a website.
- The existing generated page is private. Do not publish a new page or make it public.
- Cable and peg evidence share a directory but have separate `campaign` labels
  in `evidence/INDEX.json`. Never present a peg result as a cable result.

## Result integrity

1. Name the controller that generated the actions. Do not inherit another controller's success rate.
2. Comparisons must share task, observations, geometry, force budget and success
   criteria. Preserve invalidated comparisons and rerun both arms after a task correction.
3. No reset, pose write, teleport or attachment change inside a job. Any such event fails it.
4. Success requires the declared dwell. Include failures, force violations,
   aborts, infeasible constructions and timeouts in denominators.
5. Freeze support, action design, error model, split, metric resolutions, margin
   and predictions in a config; commit before launch. Code must check that the
   margin is at least twice the coarsest metric resolution. Never lower it to pass.
6. Every arm reads the same estimate interface. Ground truth is scoring-only.
   Keep the privilege guard armed and its deliberate-cheating positive control passing.
7. A cut-short request is censored, not evidence that an untested constraint was respected.
8. Preserve failed experiments, rejections and losing arms as scoped JSON.
   Correct an interpretation with an explicit `superseded` field; never delete a result.
9. Label post-hoc findings and give them no registered verdict.
10. Capture commit, dirty state, source hashes, config, seeds and environment
    before launch. Primary results require a clean tree.
11. Read a record's scope before quoting it. Simulation is not hardware transfer.
12. Hash text provenance with `cable_study_v3.content_sha256`, which strips BOMs
    and normalises line endings. Raw-byte text hashes differ across CRLF/LF checkouts.

Two instrument limits in [cable_discretisation_v4.json](evidence/cable_discretisation_v4.json)
apply to every claim. Minimum bend radius does not agree across refinements, so
C2 remains scoped to the 23-segment model at 4 kHz. The cable is still moving at
the 5 s settling deadline and eventually rests 2.9 µm beyond the retention
predicate's lateral boundary. Keep the deadline and predicate unchanged.

## Workflow

Work autonomously on bounded jobs with one serial simulator queue. Ask only for
a missing external resource or a real scope decision. Keep done conditions on
disk, verify each stage and commit at stage boundaries. Do not poll long runs.
Never edit modules imported by a running block: workers may respawn and reimport.

For multiline edits, write a Python patch script with `assert old in s` before
each replacement. Write UTF-8 with `newline="\n"` to preserve LF. Do not modify
`.deps/aic`; put adapters in `src/assembly_recovery/`.

## Main entry points

| Need | File |
| --- | --- |
| Offline decision inspector | `scripts/inspect_recovery.py`; `src/assembly_recovery/recovery_inspector.py` |
| Portable replay verification | `scripts/verify_recovery_replay.py`; `artifacts/showcase/recovery_replay.json` |
| Fixed replay export | `scripts/export_recovery_replay.py`; `configs/recovery_inspector_demo.json` |
| Original safety layer | `src/assembly_recovery/cable_safety_filter_v4.py` |
| Scene, clips, cable and guards | `src/assembly_recovery/cable_constrained_v2.py` |
| Routing cell | `src/assembly_recovery/cable_cell_v6.py`; `configs/cable_cell_v6_candidates.json` |
| Constraint scoring and censoring | `src/assembly_recovery/cable_constraints_v4.py` |
| Estimate interface and privilege guard | `src/assembly_recovery/cable_perception_v4.py` |
| Editable simulator workbench | `scripts/workbench.py`; `src/assembly_recovery/cable_workbench_v7.py` |
| Four findings, re-derived | `scripts/verify_findings.py` |
| Original filter demonstration | `scripts/try_the_safety_check.py`; `artifacts/showcase/demo.json` |
| Documented-number checks | `tests/test_documented_numbers.py` |
| Evidence lookup | `evidence/INDEX.json` |
| Machine versions | `environment-lock.example.json`; local `environment-lock.local.json` |

## Verification commands

```powershell
.venv/Scripts/python.exe -m pytest                    # 611 tests
.venv/Scripts/python.exe -m ruff check src scripts tests
.venv/Scripts/python.exe scripts/verify_findings.py
.venv/Scripts/python.exe scripts/try_the_safety_check.py
.venv/Scripts/python.exe scripts/inspect_recovery.py --demo
.venv/Scripts/python.exe scripts/verify_recovery_replay.py
.venv/Scripts/python.exe scripts/index_evidence.py    # after adding an evidence record
```

If the client cannot write to the default pytest temporary directory, use a
fresh `--basetemp artifacts/test_tmp_<name> -p no:cacheprovider`. The launcher
timeout test needs permission to terminate its own child process. The inspector,
findings verifier and portable replay verifier need only Python and NumPy.

## Simulator and rendering environments

- Collection uses CPU MuJoCo. MJX does not support this scene's cable elasticity
  plugin, composite bodies or elliptic friction cone. Changing that path changes
  the model and invalidates comparisons. The measured throughput is 44,966
  aggregate steps/s on 20 workers, versus 28,086 on 12; this machine has 24 physical cores.
- Windows Application Control blocks `.deps/cable-venv/Scripts/python.exe`.
  Use that environment's `pythonw.exe`, including `--python` on launchers.
  Never copy or rename the blocked executable. Use `python -m pytest` rather than `pytest.exe`.
- `.venv` holds Torch for fitting; `.deps/cable-venv` holds MuJoCo, SciPy and
  Matplotlib for physics and figures. `TORCHDYNAMO_DISABLE=1` avoids the known
  optional compiler import failure. Do not change the simulation environment's
  recorded package set to install an unrelated tool.
- `.deps/usd-venv` holds only `usd-core` and Pillow for export. Isaac Sim 5.1 at
  `C:/isaac-sim` supplies its own `python.bat` and is used only for rendering.
- There is no display. Keep work headless, render to a file and inspect it. The
  workbench's interactive window has never been executed here.
- MuJoCo's offscreen framebuffer is 1280×960. The 1920-wide comparison combines
  three smaller renders; a single larger `mujoco.Renderer` fails.
- In Isaac Sim, let `rep.orchestrator.step` advance the timeline. Manually setting
  time with a paused timeline can lose the scene from view. Use distant lights;
  sphere lights appear as visible balls. Export sanitised geom names for legal USD paths.

## CAD

Use `C:/Users/tryak/AppData/Local/Programs/FreeCAD 1.1/bin/freecadcmd.exe`.
The FreeCAD MCP server requires an RPC server started from a GUI, unavailable here.

- Fused solids must interpenetrate; use about 0.01 mm overlap for a watertight tessellation.
- Every clip needs a floor.
- CAD meshes are visual only: `contype="0" conaffinity="0" group="2"`,
  `scale="0.001 0.001 0.001"`. Primitive collision shapes and the contact defaults
  in `cable_constrained_v2.py` define the measured contact manifold. Keep them unchanged.
- FreeCAD runs scripts under its own module name with no `__file__`.
  Call `main()` directly; an `if __name__ == "__main__"` guard silently does nothing.

See [cell_toolchain_v6.json](evidence/cell_toolchain_v6.json) for the checks.

## Reproduction commands

These reproduce closed work; they are not a queue of new runs.

```powershell
& "C:/Users/tryak/AppData/Local/Programs/FreeCAD 1.1/bin/freecadcmd.exe" scripts/build_cell_cad.py
.deps/cable-venv/Scripts/pythonw.exe scripts/screen_cell_v6.py --workers 20
.venv/Scripts/python.exe scripts/run_routing_v6.py --freeze
# Commit the frozen config before any launch.
.venv/Scripts/python.exe scripts/run_routing_v6.py --run-id <id> --workers 20 --max-minutes 290 --python .deps/cable-venv/Scripts/pythonw.exe
.venv/Scripts/python.exe scripts/fit_routing_v6.py --run-dir artifacts/cable/<id>
```

Perception uses `run_perception_v4.py --freeze`, then `--run-id <id> --shard N
--of M`, then `fit_perception_v4.py`. Composition uses `run_sequence_v5.py
--freeze`, then `--run-id <id>`, then `fit_sequence_v5.py`. The launch limit is
300 minutes. Shard longer blocks on whole contexts and fit every shard together.

The fixed inspector export needs retained local runtime/results and clean git state:

```powershell
.deps/cable-venv/Scripts/pythonw.exe scripts/export_recovery_replay.py
.venv/Scripts/python.exe scripts/verify_recovery_replay.py
```

Rendering commands, in dependency order:

```powershell
.deps/cable-venv/Scripts/pythonw.exe scripts/render_routing_video_v6.py --layout triptych --view clips `
  --case RC1_l15_compliant4000_m0_E0_unfiltered_r0 `
  --case RC1_l15_compliant4000_m0_E0_filtered_r0 `
  --case RC1_l15_compliant4000_m0_E0_conservative_r0
.deps/cable-venv/Scripts/pythonw.exe scripts/render_routing_video_v6.py --layout estimate --view wide `
  --case RC1_l30_compliant4000_m0_E4_conservative_r2 --name estimate
.deps/cable-venv/Scripts/pythonw.exe scripts/render_routing_video_v6.py --layout budget --view clips `
  --case RC1_l15_compliant4000_m0_E0_conservative_r0 --name budget
.deps/cable-venv/Scripts/pythonw.exe scripts/verify_showcase_video.py
.deps/cable-venv/Scripts/pythonw.exe scripts/workbench.py --self-check
.deps/usd-venv/Scripts/python.exe scripts/export_usd_v7.py
C:/isaac-sim/python.bat scripts/render_isaac_v7.py --view wide --frames 200 --width 1920 --height 1080
.deps/cable-venv/Scripts/pythonw.exe scripts/encode_isaac_v7.py --scale 1.0 --quality 8
```

The historical private page was built with `scripts/build_showcase.py
--published-at <artifact url>` after the clips. Its URL is
<https://claude.ai/code/artifact/71352222-82b3-4676-901c-c2c4852eea3c>.
Republishing the same file path updates it; omitting that path creates a second
page. Do not rebuild, republish or change its visibility without an explicit request.

## Outputs and remotes

Keep raw runs, weights, renders and videos in ignored output directories. Keep
concise verified records in `evidence/`, and regenerate `evidence/INDEX.json`
when adding one. The small JSON stage records and existing decision logs in
`artifacts/cell/` and `artifacts/showcase/` are tracked; their media are not.

Push this repository's commits to
`https://github.com/tryaksh/constrained-cable-safety.git`.
Pushing to `https://github.com/tryaksh/orbital-robotic-servicing-lab.git` remains
blocked by an earlier automatic approval review for missing destination
authorization. The owner has not approved it. Do not bypass that pending approval
with another remote or client.

At completion, state what changed, what actually ran and anything still blocked.
Do not promise a positive result, publication or hiring.
