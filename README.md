# Adapting WOD-Style Driving Policies to Closed-Loop Simulation

This directory is a clean standalone repo for the paper:

```text
Adapting WOD-Style Driving Policies to Closed-Loop Simulation
```

It vendors the minimal LaTeX source set needed to build the submission locally:

- `paper.tex`
- `paper.bib`
- `wod_alpasim_2026.sty`
- `wodalpasimabbrvnat.bst`
- `Makefile`

Build from this directory with:

```bash
make
```

The paper's contribution is framed as a reusable contract adaptation for running
WOD-style driving policies inside AlpaSim's closed-loop external-driver runtime.
