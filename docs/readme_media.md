# README Media

The README should use real media from the dataset, AlpaSim, and integration
workflow. Do not commit synthetic diagrams as a substitute for screenshots or
rollout video.

## Approved Media Slots

| Slot | README path | Source requirement |
| --- | --- | --- |
| Dataset frame | `docs/assets/readme/dataset-frame.jpg` | A frame you are allowed to redistribute from a WOD/AlpaSim scene. |
| AlpaSim rollout | `docs/assets/readme/alpasim-rollout.mp4` | A short local closed-loop rollout video with explicit redistribution rights. |
| Integration screenshot | `docs/assets/readme/integration-terminal.png` | A screenshot of `wod2sim-reproduce`, `wod2sim-audit-run`, or `wod2sim-benchmark-summary` output. |
| Evidence plot | `docs/assets/readme/evidence-metrics.png` | A metrics image generated from a local run, with no gated scene pixels. |

## Local Candidates Found

The working tree currently has useful local media, but it is intentionally
ignored by git:

```text
runs/closed_loop_spotlight_reflex_one_scene/aggregate/metrics_results.png
runs/closed_loop_spotlight_reflex_one_scene/rollouts/...camera_front_wide_120fov_default.mp4
workspace/alpasim/docs/assets/images/alpasim-architecture.png
```

Do not copy these into tracked docs until the redistribution rights are clear.
`runs/` can contain AlpaSim/WOD-derived media, and `workspace/` contains a
third-party AlpaSim checkout.

## How To Add Real Media

When rights are confirmed, put the approved files under:

```text
docs/assets/readme/
```

Then uncomment or add the matching `<img>` / video link in `README.md`.
