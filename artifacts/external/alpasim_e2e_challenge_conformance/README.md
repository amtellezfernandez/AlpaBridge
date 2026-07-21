# AlpaSim E2E Challenge Conformance Evidence

This directory records a bounded external-stack conformance run against the
NVIDIA AlpaSim E2E challenge development configuration. It is evidence that the
AlpaBridge challenge driver can connect to the challenge runtime over gRPC and
complete a real simulator-backed rollout. It is not a leaderboard benchmark
claim.

Run summary:

- Challenge checkout: `NVlabs/alpasim`, branch `e2e_challenge`.
- Driver image: `alpasim-e2e-wod2sim:latest` (built before this project's
  rename to AlpaBridge; frozen historical record, not the current build tag).
- Challenge config: `+e2e_challenge=dev`.
- Scene: `clipgt-01d503d4-449b-46fc-8d78-9085e70d3554`.
- Rollout status: `pass`.
- Simulated duration: 19.91 seconds.
- Wall-clock rollout duration: 1141.43 seconds.
- Driver RPCs: 197 `Drive` calls.
- Driver latency target: 197/197 calls below 100 ms.
- Driver latency: 2.135 ms mean, 11.966 ms max.
- Images received by driver: 396.

Files:

- `challenge-driver-fixed.jsonl`: AlpaBridge driver telemetry.
- `results-summary.json`: AlpaSim aggregate metrics summary.
- `metrics_results.txt`: AlpaSim text metrics report.

The run also surfaced and fixed a temporal interface mismatch: trajectory
timestamps must include the current ego pose at `time_now_us` so the AlpaSim
controller can interpolate the reference trajectory from the current control
tick.
