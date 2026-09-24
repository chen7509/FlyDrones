"""Extract auditable EKF fusion evidence from one PX4 ULog."""

from __future__ import annotations

import argparse
import json

from flydrones.px4_ulog_evidence import extract_ulog_fusion_evidence, newest_vehicle_ulog


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--px4-run-dir", required=True)
    parser.add_argument("--vehicle-id", type=int, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = newest_vehicle_ulog(args.px4_run_dir, args.vehicle_id)
    evidence = extract_ulog_fusion_evidence(
        source,
        output_path=args.output,
        fault_vehicle_id=args.vehicle_id,
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
