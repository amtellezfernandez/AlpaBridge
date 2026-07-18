# WOD2Sim Documentation

| Guide | Purpose |
| --- | --- |
| [Design](design.md) | Five-contract WOD2Sim integration boundary, architecture, and scope. |
| [Getting started](getting-started.md) | Installation, AlpaSim setup, and command materialization. |
| [Reproduction](reproduction.md) | Executed-run workflow and evidence artifacts. |
| [Evaluation](evaluation.md) | Metrics, baselines, and claim requirements. |
| [Conformance](conformance.md) | Dependency-light core contract checks. |
| [Demo](demo.md) | Ungated synthetic evidence demo and claim boundary. |
| [AlpaSim E2E Challenge compatibility](challenge-compatibility.md) | External-driver compatibility path; not a benchmark claim. |
| [CLI](cli.md) | Supported public commands. |
| [Changelog](changelog.md) | Public release history. |

The canonical [paper PDF](../wod2sim.pdf), [paper source](../paper/cvm/),
and [generated evidence package](../artifacts/cvm/) describe the contract-based
integration boundary in detail. The contract-validation matrix (CVM) material is
the WOD2Sim reproducibility package, not a separate project.
For release traceability, see the generated-report surface under
[`artifacts/cvm/reports`](../artifacts/cvm/reports/), especially the
[`contract_test_audit.md`](../artifacts/cvm/reports/contract_test_audit.md)
mapping from contract requirements to tests and explicit gaps.
