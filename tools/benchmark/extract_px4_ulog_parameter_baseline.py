"""Extract the frozen PX4 parameter baseline and topic inventory from one ULog."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.benchmark.openvins_ekf2_disarmed_preflight import required_parameter_names  # noqa: E402


def extract_baseline(ulog, source: Path) -> dict:
    source = Path(source).resolve(strict=True)
    names = ("MAV_SYS_ID", *required_parameter_names())
    parameters = {}
    for name in names:
        if name not in ulog.initial_parameters:
            raise ValueError("missing parameter " + name)
        value = ulog.initial_parameters[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError("invalid parameter " + name)
        parameters[name] = value
    data = source.read_bytes()
    return {
        "schema": "px4-ulog-parameter-baseline-v1",
        "parameters": parameters,
        "topics": sorted({item.name for item in ulog.data_list}),
        "source_ulog": {
            "path": str(source),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        "parameter_access": "retained_ulog_initial_parameters",
        "live_px4_parameter_access": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ulog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError(args.output)
    from pyulog import ULog

    result = extract_baseline(ULog(str(args.ulog)), args.ulog)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
