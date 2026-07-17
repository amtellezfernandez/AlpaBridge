# Ungated Demo

`make demo` generates a public synthetic run directory:

```bash
make demo
```

Default output is `demo/wod2sim-contract-demo`. The directory contains:

| Artifact | Purpose |
| --- | --- |
| `launch-metadata.json` | Synthetic launch metadata with `valid_claim_evidence=false`. |
| `driver/baseline-log.jsonl` | Driver-frame records with `route_source=alpasim_waypoints`. |
| `controller/synthetic-controller.csv` | Minimal controller trace used by audit export. |
| `run-audit.json` | Output from the same public audit path used for executed runs. |
| `aggregate/synthetic-contract-metrics.json` | Format metrics plus synthetic route-loss and lane-offset diagnostics. |
| `support-bundle.tar.gz` | Portable support bundle built by `wod2sim-support-bundle`. |
| `synthetic-rollout.svg` | Lightweight visual overview of the synthetic route and audited frames. |

## Synthetic Diagnostics

The metrics JSON includes two deterministic geometry diagnostics:

| Diagnostic | Meaning |
| --- | --- |
| `route_command_information_loss.same_x_lateral_rmse_m` | Lateral RMSE between preserved route waypoints and a straight command-proxy route at the same x-samples. |
| `road_center_vs_ego_route.mean_abs_lateral_offset_m` | Mean absolute offset between the ego route and a synthetic visual road centerline. |

These numbers make the contract failure inspectable on public synthetic
geometry. They are not closed-loop policy metrics and should not be compared as
benchmark results.

## Claim Boundary

The demo is intentionally not a benchmark. It does not launch AlpaSim, load a
checkpoint, use gated scenes, replay Waymo data, or report policy quality. It
exists so a public user can inspect the evidence schema, support-bundle layout,
route-contract audit, and generated visual without private assets.

Use it to verify that the release surface is runnable on an ordinary machine.
Do not cite it as closed-loop performance evidence.
