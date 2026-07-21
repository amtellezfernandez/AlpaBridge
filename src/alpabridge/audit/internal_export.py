from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import build_audit_frames, load_rollout_payload


def export_internal_audit_log(rollout_json: Path, output_dir: Path) -> dict[str, Any]:
    payload = load_rollout_payload(rollout_json)
    frames = build_audit_frames(payload)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "format_version": 1,
        "source": "internal",
        "scenario_cluster": payload["scenario"]["cluster"],
        "seed": payload["scenario"]["seed"],
        "policy": payload["architecture"]["policy"],
        "rollout_preset": payload["architecture"].get("rollout_preset", "default"),
        "frame_count": len(frames),
        "files": {
            "manifest": "manifest.json",
            "frames": "frames.jsonl",
            "scenario": "scenario.json",
            "rollout": "rollout.json",
        },
    }

    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (output_dir / "scenario.json").write_text(json.dumps(payload["scenario"], indent=2))
    (output_dir / "rollout.json").write_text(json.dumps(payload, indent=2))
    with (output_dir / "frames.jsonl").open("w", encoding="utf-8") as handle:
        for frame in frames:
            handle.write(json.dumps(frame) + "\n")
    return manifest
