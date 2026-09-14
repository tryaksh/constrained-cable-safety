# Project status

The four cable studies are closed. The deliverable is this repository; there is
no paper or publication track and no new study queued. The recovery inspector
applies the existing filter and action-selection policies without changing their
fitted thresholds or historical results.

[README.md](README.md) explains the problem, results and quick start.
[AGENTS.md](AGENTS.md) contains operating rules and reproduction commands.
The retired peg-insertion campaign is tracked separately in
[docs/PEG_INSERTION.md](docs/PEG_INSERTION.md).

## Closed measurements

| Study | Result | Evidence |
| --- | --- | --- |
| **v3** | Inconclusive. The registered alternatives could not be resolved at the metric's granularity. The original result is retained. | [Boundary study](evidence/cable_repair_boundary_v3.json) |
| **v4** | No richer representation cleared the registered improvement margin over the one-distance baseline, across the tested constraints and error levels. 16,080 requests. | [Perception study](evidence/cable_perception_v4.json) |
| **v5** | The unfiltered arm lost the clip in all 240 runs. Conservative action selection reduced observed clip losses at E0 and E2. At E4, the filtered arm's per-step clip violation rate rose by 0.089 across the sequence. | [Composition study](evidence/cable_sequence_v5.json) |
| **v6** | On one five-clip rig, the unchanged filter's clip-loss improvements were +0.000, +0.025 and −0.008, below the registered margin. Most-headroom selection completed 20/60, 76/360 and 9/360 jobs at E0/E2/E4; both largest-move arms completed none. | [Routing study](evidence/cable_routing_v6.json) |

The v6 block ran 2,340 jobs, 11,700 decisions and 266.8 million native steps in
87 minutes on 20 workers. Its contract was committed before launch. Zero
privilege-guard events, simulator mutations or settling failures occurred.
[Block record](artifacts/cell/block.json)

Before the block, physical clip loss appeared between 18 mm and 25 mm of
commanded retreat. The filter reported 58 mm of endpoint-distance headroom on
the cell. These use different quantities; the old threshold was not a measured
five-clip retreat limit. The live inspector uses a later, recorded repair
decision and reports that decision's candidate set and budgets.

## Instrument and fixture checks

| Check | Verified result |
| --- | --- |
| Cable refinement | Fourfold refinement agrees on settled boot-to-anchor distance within 5.7 µm. Minimum bend radius fails the agreement test, so C2 remains scoped to 23 segments at 4 kHz. [Record](evidence/cable_discretisation_v4.json) |
| Settling | The cable is still moving at the 5 s deadline. Its eventual position is 2.9 µm beyond the retention predicate's lateral boundary. The deadline and predicate remain fixed. [Record](evidence/cable_discretisation_v4.json) |
| Contact and controller | A misaligned plug is blocked by contact; aligned insertion seats. Force-guided alignment seated 6/6 validation cases, while continued pushing timed out on all three offset cases. [Contact](evidence/cable_contact_validation_v1.json), [controller](evidence/cable_baseline_v2.json) |
| Independent scoring | Replayed 16,080 requests from raw logs: 26,652 comparisons, zero disagreements. [Record](evidence/cable_perception_replay_v4.json) |
| Guard and resolution controls | A deliberate privileged read triggers the guard. The margin check refused 3 of 15 v4 comparisons; it requires at least twice the coarsest metric resolution. [Guard](evidence/cable_perception_controls_v4.json), [resolution](evidence/cable_perception_v4.json) |
| Throughput | 44,966 aggregate steps/s on 20 CPU workers, versus 28,086 on 12. The GPU is used for rendering; this cable model cannot be moved unchanged to MJX. [Pilot](evidence/cable_perception_pilot_v4.json) |
| Model sensitivity | At a nominal 399.7 mm threshold, ±30% sliding-friction uncertainty implies 12.5 mm extra margin; bending stiffness implies 4.3 mm. This is simulation sensitivity, not hardware calibration. [Record](evidence/cable_transfer_protocol_v4.json) |
| CAD | 8 parts, 3,704 facets; all watertight and single-solid. Meshes are visual only. Settling with and without them agrees to 0.0 m. [Record](evidence/cable_cell_cad_v6.json) |
| Fixture screen | 28 candidates: 9 accepted, 19 rejected with reasons. The selected layout survives 6 of 7 slack settings. [Record](evidence/cable_cell_screen_v6.json) |
| Earlier-task compatibility | Two registered single-clip contexts compile to byte-identical scene XML after adding multi-clip support. [Record](artifacts/cell/scene.json) |

## Applications and rendered artifacts

| Artifact | Verification and scope |
| --- | --- |
| **Recovery inspector** | NumPy-only API and CLI for external estimates. Compares all three existing policies, reports per-constraint budgets and source hashes, validates inputs and abstains on missing rules. A fixed nine-case replay reproduced 9 original outcomes and all 21 decisions within 1e-12, including failures. Zero guard events. These are software checks, not new performance measurements. [Application](artifacts/showcase/recovery_inspector.json), [replay](artifacts/showcase/recovery_replay.json) |
| **Workbench** | Loads or edits fixture configurations, runs the install check, then evaluates a job. 17 headless tests and a self-check reproduce the registered install result and job, including its headroom series. The interactive window has never been opened. [Record](artifacts/showcase/tool.json) |
| **Three replay clips** | Study control-loop replays checked against committed job results. Decoding verified 329, 352 and 329 frames, with no blank images in 27 samples. [Record](artifacts/showcase/video.json) |
| **USD export** | 200 frames of recorded motion, read back as 286 prims, 72 animated. Export does not step the physics. [Record](artifacts/showcase/usd.json) |
| **Isaac Sim render** | The exported motion rendered as 198 frames at 1920×1080. Rendering only; measured physics is unchanged. [Record](artifacts/showcase/isaac.json) |
| **Existing private page** | Previously generated from ten committed records and published privately. Its record retains the existing link. The existing private publication remains unchanged. [Record](artifacts/showcase/page.json) |

Stage records are committed; large videos, image sequences and USD files are
generated output. Reproduction commands are in [AGENTS.md](AGENTS.md). The
portfolio demo and description are delivered outside this repository.

## Remaining limitations and the cost of extending the work

Possible extensions; none are scheduled. Cost estimates use the original
machine's measured v6 cost: about 44 summed worker-seconds per route and
87 minutes for 2,340 routes on 20 workers. A new study would require explicit
scope, a new frozen contract and its own validation.

| Open question or limitation | Work required |
| --- | --- |
| Force-only sensing may merit a larger study | To resolve a margin near 0.01, target at least 200 held-out contexts per rig rather than v4's 60. More than three times the original 16,080-run block, with the same arms and scoring. |
| A supervisor could cap the fraction of headroom spent | The registered candidates leave a gap between spent fractions 0.061 and 0.819. A cap would need a new candidate set before evaluation, then about 780 routes, roughly half an hour. It is not implemented or claimed here. |
| Five-clip findings cover one rig | Screen a second geometry and run a full comparison: approximately 2,340 routes and 87 minutes after screening. No threshold-transfer claim follows from the existing rig. |
| v3 remains inconclusive | A different resolution or margin would require a new registered block. Refitting or rescoring the old block would not answer its original question. v4 already addressed the representation question. |
| The workbench window is untested | Run `scripts/workbench.py --run --view` on a machine with a display. Headless behavior is verified. |
| v5/v6 lack standalone study figures | Draw two figures from committed evidence in the plotting environment. No new physics runs are needed. |
| One old figure has damaged text encoding | Re-render `evidence/cable_baseline_v2.png` from its JSON record. The recorded numbers are intact. |

Camera perception, hardware transfer, reliable grasping, latching and released
connections have not been demonstrated. Bend-radius scope and the 5 s settling
deadline are instrument constraints, not tuning options.

## Repository continuity

The repository includes restored evidence links, 41 frozen contracts and ten
early cable scripts. Tests now check that maintained-document links are
tracked and that imports of repository modules resolve. Historical handovers
under `docs/handover/` remain unchanged.

Four scripts named by old records could not be recovered from the parent
repository's archive: `add_cable_plugin.py`, `load_aic_world.py`,
`sim_comparison_test.py` and `view_scene.py`. Their records remain available, but
their exact reproduction code is missing. The retired peg campaign's code and
raw runs are also elsewhere; [docs/PEG_INSERTION.md](docs/PEG_INSERTION.md)
states where.

[docs/REPO_MAP.md](docs/REPO_MAP.md) records branch history.
[evidence/INDEX.json](evidence/INDEX.json) distinguishes cable, peg and shared
records; campaign numbers must not be combined.
