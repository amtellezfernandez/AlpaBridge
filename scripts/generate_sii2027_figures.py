from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate SII 2027 vector figures.")
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--runs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    figures = args.output / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    data_hash = str(summary.get("data_hash", "missing-data-hash"))
    _figure_pdf(
        figures / "system_architecture.pdf",
        _architecture_tikz(),
        data_hash=data_hash,
    )
    _figure_pdf(
        figures / "evaluation_pipeline.pdf",
        _pipeline_tikz(),
        data_hash=data_hash,
    )
    _figure_pdf(
        figures / "main_results.pdf",
        _results_tikz(summary),
        data_hash=data_hash,
    )
    return 0


def _figure_pdf(output: Path, tikz_body: str, *, data_hash: str) -> None:
    tex = (
        "\\documentclass[tikz,border=2pt]{standalone}\n"
        "\\usepackage{tikz}\n"
        "\\usetikzlibrary{arrows.meta,positioning}\n"
        f"\\pdfinfo{{/Subject (SII 2027 figure data_hash={data_hash})}}\n"
        "\\begin{document}\n"
        + tikz_body
        + "\n\\end{document}\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        tex_path = tmpdir / "figure.tex"
        tex_path.write_text(tex, encoding="utf-8")
        env = os.environ.copy()
        env.setdefault("SOURCE_DATE_EPOCH", "0")
        env.setdefault("FORCE_SOURCE_DATE", "1")
        result = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
            cwd=tmpdir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise SystemExit(f"pdflatex failed for {output}:\n{result.stdout}")
        output.write_bytes((tmpdir / "figure.pdf").read_bytes())


def _architecture_tikz() -> str:
    return r"""
\begin{tikzpicture}[
  node distance=8mm and 10mm,
  box/.style={draw, rounded corners, align=center, minimum width=24mm, minimum height=9mm, font=\small},
  contract/.style={box, fill=blue!8},
  runtime/.style={box, fill=orange!12},
  arr/.style={-Stealth, thick}
]
\node[box, fill=green!10] (policy) {Dataset-trained\\trajectory policy};
\node[contract, right=of policy] (semantic) {Semantic\\contract};
\node[contract, right=of semantic] (temporal) {Temporal\\contract};
\node[contract, below=of semantic] (life) {Lifecycle\\contract};
\node[contract, below=of temporal] (deploy) {Deployment\\contract};
\node[contract, right=of temporal] (evidence) {Evidence\\contract};
\node[runtime, right=of evidence] (sim) {Distributed\\AlpaSim runtime};
\node[runtime, below=of sim] (audit) {Audit and\\aggregation};
\draw[arr] (policy) -- (semantic);
\draw[arr] (semantic) -- (temporal);
\draw[arr] (temporal) -- (evidence);
\draw[arr] (evidence) -- (sim);
\draw[arr] (life) -- (deploy);
\draw[arr] (deploy) -- (evidence);
\draw[arr] (sim) -- (audit);
\draw[arr] (audit) -- (evidence);
\end{tikzpicture}
"""


def _pipeline_tikz() -> str:
    return r"""
\begin{tikzpicture}[
  node distance=7mm,
  box/.style={draw, rounded corners, align=center, minimum width=27mm, minimum height=8mm, font=\small},
  arr/.style={-Stealth, thick}
]
\node[box] (setup) {setup/check};
\node[box, right=of setup] (ready) {readiness};
\node[box, right=of ready] (manifest) {launch\\manifest};
\node[box, right=of manifest] (rollout) {rollout};
\node[box, below=of rollout] (audit) {audit/evidence};
\node[box, left=of audit] (aggregate) {aggregate};
\node[box, left=of aggregate] (paper) {paper assets};
\draw[arr] (setup) -- (ready);
\draw[arr] (ready) -- (manifest);
\draw[arr] (manifest) -- (rollout);
\draw[arr] (rollout) -- (audit);
\draw[arr] (audit) -- (aggregate);
\draw[arr] (aggregate) -- (paper);
\end{tikzpicture}
"""


def _results_tikz(summary: dict[str, object]) -> str:
    total = int(summary.get("total_rows", 0))
    completed = int(summary.get("completed_runs", 0))
    blocked = int(summary.get("blocked_runs", 0))
    total_bar = max(total, 1)
    completed_w = 70 * completed / total_bar
    blocked_w = 70 * blocked / total_bar
    return rf"""
\begin{{tikzpicture}}[
  label/.style={{font=\small, anchor=east}},
  bar/.style={{draw, minimum height=7mm, anchor=west}},
]
\node[label] at (0,0) {{Completed}};
\node[bar, fill=green!25, minimum width={completed_w:.1f}mm] at (2mm,0) {{}};
\node[anchor=west, font=\small] at ({completed_w/10 + 0.4:.2f},0) {{{completed}/{total}}};
\node[label] at (0,-0.9) {{Blocked}};
\node[bar, fill=red!20, minimum width={blocked_w:.1f}mm] at (2mm,-0.9) {{}};
\node[anchor=west, font=\small] at ({blocked_w/10 + 0.4:.2f},-0.9) {{{blocked}/{total}}};
\node[font=\small, align=center] at (3.8,-1.8) {{Configured SII matrix status; no blocked row is claim-valid.}};
\end{{tikzpicture}}
"""


if __name__ == "__main__":
    raise SystemExit(main())
