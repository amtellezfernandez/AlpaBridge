# Documentation

This directory is the documentation entry point. The root `README.md` stays
short; use these pages for the detailed operational and paper-facing material.

| Page | Use It For |
| --- | --- |
| [`integration_guide.md`](integration_guide.md) | Day-0 setup, first AlpaSim launch, expected outputs, and common failures. |
| [`closed_loop_reproduction.md`](closed_loop_reproduction.md) | Public dry-run plans versus executed closed-loop evidence. |
| [`benchmark_evidence_workflow.md`](benchmark_evidence_workflow.md) | Batch runs, USDZ cache workflow, tracked public evidence, audits, and promotion order. |
| [`benchmark_regeneration_handoff.md`](benchmark_regeneration_handoff.md) | Current 10/50/100 regeneration state, blocker IDs, role boundaries, and next command groups. |
| [`evaluation_protocol.md`](evaluation_protocol.md) | Claim boundary, baselines, metrics, scene coverage, and current scale readiness. |
| [`waymo_motion_and_alpasim.md`](waymo_motion_and_alpasim.md) | Dataset/simulator positioning and Waymax comparison. |
| [`cli_reference.md`](cli_reference.md) | Installed command surface and model presets. |
| [`readme_media.md`](readme_media.md) | Policy for redistributable README screenshots, plots, and media. |

Generated or compact public evidence lives under [`evidence/`](evidence/).
LaTeX paper source lives under [`../paper/`](../paper/); `make paper` builds
`paper/paper.pdf` and copies the arXiv-ready PDF to [`../arxiv.pdf`](../arxiv.pdf).
