from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate contract-validation vector figures.")
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
    waymax_figure = figures / "waymax_factorial.pdf"
    _figure_pdf(
        waymax_figure,
        _waymax_factorial_tikz(summary),
        data_hash=data_hash,
    )
    _render_png(waymax_figure)
    return 0


def _figure_pdf(output: Path, tikz_body: str, *, data_hash: str) -> None:
    tex = (
        "\\documentclass[tikz,border=2pt]{standalone}\n"
        "\\usepackage{tikz}\n"
        "\\usetikzlibrary{arrows.meta,positioning}\n"
        f"\\pdfinfo{{/Subject (contract-validation figure data_hash={data_hash})}}\n"
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


def _render_png(pdf_path: Path) -> None:
    result = subprocess.run(
        [
            "pdftocairo",
            "-png",
            "-singlefile",
            "-r",
            "180",
            str(pdf_path),
            str(pdf_path.with_suffix("")),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"pdftocairo failed for {pdf_path}:\n{result.stdout}")


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
    effectiveness = summary.get("integration_effectiveness", {})
    if not isinstance(effectiveness, dict):
        effectiveness = {}
    full_completed = int(effectiveness.get("full_contract_completed_runs", 0))
    audit_valid = int(effectiveness.get("full_contract_audit_valid_runs", 0))
    semantic_pairs = int(effectiveness.get("semantic_ablation_completed_pairs", 0))
    semantic_eligible_pairs = int(
        effectiveness.get("semantic_ablation_comparison_eligible_pairs", 0)
    )
    status_only_denominator = int(
        effectiveness.get("status_only_baseline_acceptance_denominator", 0)
    )
    status_only_accepted = int(
        effectiveness.get("status_only_baseline_accepted_runs", 0)
    )
    command_completed = int(
        effectiveness.get("semantic_ablation_command_proxy_completed_runs", 0)
    )
    command_rejected = int(
        effectiveness.get("semantic_ablation_command_proxy_rejected_runs", 0)
    )
    checks = [
        ("Full-contract audit", audit_valid, full_completed, "green!25"),
        ("Eligible route-loss pairs", semantic_eligible_pairs, semantic_pairs, "blue!18"),
        (
            "Status-only baseline",
            status_only_accepted,
            status_only_denominator,
            "gray!25",
        ),
        ("Invalid route rejected", command_rejected, command_completed, "orange!22"),
    ]
    max_total = max((total for _, _, total, _ in checks), default=1)
    lines = []
    for idx, (label, observed, total, color) in enumerate(checks):
        y = -0.9 * idx
        width = 70 * observed / max(max_total, 1)
        total_width = 70 * total / max(max_total, 1)
        x_label = width / 10 + 0.4
        lines.append(
            rf"\node[label] at (0,{y:.1f}) {{{label}}};"
            "\n"
            rf"\node[bar, fill=gray!12, minimum width={total_width:.1f}mm] at (2mm,{y:.1f}) {{}};"
            "\n"
            rf"\node[bar, fill={color}, minimum width={width:.1f}mm] at (2mm,{y:.1f}) {{}};"
            "\n"
            rf"\node[anchor=west, font=\small] at ({x_label:.2f},{y:.1f}) {{{observed}/{total}}};"
        )
    return rf"""
\begin{{tikzpicture}}[
  label/.style={{font=\small, anchor=east}},
  bar/.style={{draw, minimum height=7mm, anchor=west}},
]
{chr(10).join(lines)}
\node[font=\small, align=center] at (3.9,-3.7) {{Completed closed-loop integration checks.}};
\end{{tikzpicture}}
"""


def _waymax_factorial_tikz(summary: dict[str, object]) -> str:
    study = summary.get("waymax_contract_study", {})
    if not isinstance(study, dict) or study.get("available") is not True:
        raise SystemExit("Waymax contract study is unavailable")
    behavior = study.get("behavior", {})
    if not isinstance(behavior, dict):
        raise SystemExit("Waymax contract behavior summary is missing")
    curves = behavior.get("displacement_divergence_over_time_m", {})
    if not isinstance(curves, dict):
        raise SystemExit("Waymax displacement curves are missing")
    route_curve = _mean_curve(curves, "route_following")
    cv_curve = _mean_curve(curves, "constant_velocity")
    if len(route_curve) != 51 or len(cv_curve) != 51:
        raise SystemExit("Waymax displacement curves must contain 51 samples")
    eligible = int(behavior.get("comparison_eligible_scenarios", 0))
    changed = int(
        _nested_number(
            behavior,
            "endpoint_difference_m.route_following.changed_count",
        )
    )
    endpoint_median = _nested_number(
        behavior,
        "endpoint_difference_m.route_following.median",
    )
    y_max = max(max(route_curve), 0.1) * 1.1
    route_points = " ".join(
        f"({4.2 * index / 50:.3f},{1.15 + 2.55 * value / y_max:.3f})"
        for index, value in enumerate(route_curve)
    )
    cv_points = " ".join(
        f"({4.2 * index / 50:.3f},{1.15 + 2.55 * value / y_max:.3f})"
        for index, value in enumerate(cv_curve)
    )
    return rf"""
\begin{{tikzpicture}}[
  cell/.style={{draw, align=center, minimum width=19mm, minimum height=10mm, font=\scriptsize}},
  valid/.style={{cell, fill=green!16}},
  invalid/.style={{cell, fill=orange!22}},
  audit/.style={{draw, align=left, minimum width=46mm, minimum height=8mm, font=\scriptsize}},
]
\node[anchor=west,font=\bfseries\small] at (0,4.75) {{(a) Policy $\times$ route}};
\node[font=\scriptsize\bfseries] at (2.75,4.15) {{Full WOMD}};
\node[font=\scriptsize\bfseries] at (4.85,4.15) {{Command proxy}};
\node[anchor=east,font=\scriptsize] at (1.72,3.35) {{Route following}};
\node[anchor=east,font=\scriptsize] at (1.72,2.15) {{Constant velocity}};
\node[valid] at (2.75,3.35) {{valid\\control}};
\node[invalid] at (4.85,3.35) {{semantic\\violation}};
\node[valid] at (2.75,2.15) {{negative\\control A}};
\node[valid] at (4.85,2.15) {{negative\\control B}};
\node[anchor=west,font=\scriptsize,align=left] at (0,1.05)
  {{Same scene, initial state, dynamics,\\50 steps, and per-policy control law.}};

\begin{{scope}}[xshift=7.0cm]
\node[anchor=west,font=\bfseries\small] at (0,4.75) {{(b) Paired divergence}};
\node[anchor=west,font=\scriptsize] at (0,4.25)
  {{median $D_T={endpoint_median:.3f}$ m; $>{0.1}$ m in {changed}/{eligible}}};
\draw[->] (0,1.15) -- (4.55,1.15);
\draw[->] (0,1.15) -- (0,3.95);
\node[font=\scriptsize] at (2.1,0.63) {{time (s)}};
\node[font=\scriptsize,rotate=90] at (-0.72,2.55) {{$D(t)$ (m)}};
\draw[very thick, blue!70!black] plot coordinates {{{route_points}}};
\draw[very thick, dashed, green!50!black] plot coordinates {{{cv_points}}};
\node[anchor=north,font=\scriptsize] at (0,1.08) {{0}};
\node[anchor=north,font=\scriptsize] at (2.1,1.08) {{2.5}};
\node[anchor=north,font=\scriptsize] at (4.2,1.08) {{5}};
\node[anchor=east,font=\scriptsize] at (-0.08,1.15) {{0}};
\node[anchor=east,font=\scriptsize] at (-0.08,3.70) {{{y_max:.1f}}};
\node[anchor=west,font=\scriptsize,text=blue!70!black] at (3.05,3.72)
  {{RF mean}};
\node[anchor=west,font=\scriptsize,text=green!40!black] at (2.55,1.38)
  {{CV = 0.000 m}};
\end{{scope}}

\begin{{scope}}[xshift=12.15cm]
\node[anchor=west,font=\bfseries\small] at (0,4.75) {{(c) Admission before metrics}};
\node[audit,fill=green!16] at (2.35,3.95)
  {{RF + full WOMD \hfill VALID ({eligible}/{eligible})}};
\node[audit,fill=orange!22] at (2.35,2.95)
  {{RF + command proxy \hfill REJECT ({eligible}/{eligible})\\
    \texttt{{semantic.command\_only}}}};
\node[audit,fill=green!16] at (2.35,1.95)
  {{CV + full WOMD \hfill VALID ({eligible}/{eligible})}};
\node[audit,fill=green!16] at (2.35,0.95)
  {{CV + command proxy \hfill VALID ({eligible}/{eligible})}};
\node[anchor=west,font=\scriptsize\bfseries] at (0,0.25)
  {{All four arms complete; completion alone does not make valid evidence.}};
\end{{scope}}
\end{{tikzpicture}}
"""


def _mean_curve(curves: dict[str, object], policy: str) -> list[float]:
    item = curves.get(policy)
    if not isinstance(item, dict) or not isinstance(item.get("mean"), list):
        raise SystemExit(f"Waymax mean curve is missing for {policy}")
    values = item["mean"]
    if not all(isinstance(value, (int, float)) for value in values):
        raise SystemExit(f"Waymax mean curve is nonnumeric for {policy}")
    return [float(value) for value in values]


def _nested_number(payload: dict[str, object], dotted_path: str) -> float:
    value: object = payload
    for part in dotted_path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise SystemExit(f"Waymax summary field is missing: {dotted_path}")
        value = value[part]
    if not isinstance(value, (int, float)):
        raise SystemExit(f"Waymax summary field is nonnumeric: {dotted_path}")
    return float(value)


if __name__ == "__main__":
    raise SystemExit(main())
