"""Read-only check for the exact vehicle_odometry topic in existing PX4 ULogs."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src/flydrones/connectome_training/px4_ulog_odometry_preflight.py"
SPEC = importlib.util.spec_from_file_location("px4_ulog_odometry_preflight", MODULE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("ULog preflight module unavailable")
preflight = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = preflight
SPEC.loader.exec_module(preflight)
audit_topic = preflight.audit_topic


def main(paths: list[str]) -> int:
    if not paths:
        raise SystemExit("usage: audit_px4_ulog_odometry.py ULOG [ULOG ...]")
    from pyulog import ULog

    results = []
    for value in paths:
        path = Path(value)
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"ULog must be a regular file: {path}")
        before = path.stat()
        if before.st_size > 100_000_000:
            raise ValueError(f"ULog exceeds bounded audit size: {path}")
        raw = path.read_bytes()
        ulog = ULog(str(path))
        after = path.stat()
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
            raise ValueError(f"ULog changed during audit: {path}")
        audit = audit_topic(ulog.data_list)
        selected = {name: sum(len(item.data["timestamp"]) for item in ulog.data_list
                              if item.name == name)
                    for name in ("vehicle_odometry", "vehicle_local_position",
                                 "vehicle_attitude", "estimator_status", "vehicle_status")}
        results.append({
            "path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw), "topic_count": len(ulog.data_list),
            "selected_topic_samples": selected,
            "vehicle_odometry_audit": audit.__dict__,
        })
    passed = all(item["vehicle_odometry_audit"]["usable_for_exact_crosscheck"]
                 for item in results)
    print(json.dumps({"schema": "flydrones.px4_ulog_odometry_preflight.v1",
                      "pyulog_version": version("pyulog"),
                      "preflight_passed": passed,
                      "source_authentication_qualified": False,
                      "results": results}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
