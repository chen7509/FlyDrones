"""Score a frozen ten-run Gazebo renderer campaign from preserved artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from flydrones.renderer_stability import campaign_schedule, score_campaign


def load_campaign(campaign_dir: Path) -> list[tuple[dict, dict]]:
    trials = []
    for scheduled in campaign_schedule():
        trial_dir = campaign_dir / scheduled.name
        manifest_path = trial_dir / "trial-manifest.json"
        summary_path = trial_dir / "stress-summary.json"
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.is_file() else {}
        )
        summary = (
            json.loads(summary_path.read_text(encoding="utf-8"))
            if summary_path.is_file() else {}
        )
        trials.append((manifest, summary))
    return trials


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = score_campaign(load_campaign(args.campaign_dir))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({
        "formal_artifacts_complete": result["formal_artifacts_complete"],
        "d3d12_stability_gate_pass": result["d3d12_stability_gate_pass"],
        "validation_failures": result["validation_failures"],
        "campaign_failures": result["campaign_failures"],
    }, ensure_ascii=False))
    return 0 if result["formal_artifacts_complete"] and result["d3d12_stability_gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
