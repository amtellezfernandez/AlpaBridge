# Waymax Policy-Dependency Contract Study

This directory retains the public-safe outputs of the WOD2Sim `2 x 2`
attribution-correctness experiment:

| Policy | Full WOMD route | `KEEP_HEADING` command proxy |
| --- | --- | --- |
| Route following | Valid control | `semantic.command_only` |
| Constant velocity | Negative control A | Negative control B |

The same pure-pursuit controller is used in both route-following arms. The
proxy arm removes the original WOMD route geometry and reconstructs a straight
geometric proxy from an intervention-defined command. Constant velocity
traverses the same adapter conversion but does not consume route.

## Retained Result

- Fixture scenarios: `20`
- Paired scenarios with valid `sdc_paths.on_route`: `19`
- Closed-loop steps: `3,800` (`19 x 4 x 50`)
- Route-following endpoint divergence: `1.017 m` median, `1.973 m` mean,
  `14.211 m` maximum
- Route-following changes above `0.1 m`: `13/19`
- Constant-velocity invariant scenarios: `19/19`; maximum divergence `0.000 m`
- Audit decisions: RF/full `19/19` clean, RF/proxy `19/19` semantic fault,
  CV/full `19/19` clean, CV/proxy `19/19` clean

`scenario-results.jsonl` contains one public-safe result per TFExample.
`results-summary.json` is recomputed from those rows. `manifest.json` pins the
upstream commit, fixture hash, implementation hashes, and result hashes.

## Reproduce

```bash
./scripts/run_waymax_contract_study.sh
make cvm-aggregate
make paper-verify
```

The runner clones Waymax at
`a64dfec9be8576b60d9cecc94f406d9812d4a7d0`, verifies the bundled fixture SHA-256
`aba63d14b00d133803db04f49a3263447beafd8ca3010ea535ca7dfff0635ba5`,
and creates an isolated environment under `workspace/waymax-contract-study`.

## Evidence Boundary

The upstream fixture and Waymax source remain governed by the Waymax License
Agreement for Non-Commercial Use and are not redistributed here. The fixture
is upstream-selected test data, not a random or representative WOMD sample.
The study uses deterministic, dependency-light policies and log playback for
non-SDC agents. It supports selective behavior consequence and semantic
attribution on this fixture. It does not support learned-policy quality,
counterfactual safety, fault prevalence, comparative runtime overhead, or
framework superiority.
