#!/usr/bin/env python3
# ruff: noqa: E402 - script inserts repository src before importing FlyDrones
"""Summarize PX4 ULog estimator and control evidence without replaying flight."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from flydrones.benchmark.ulog_health import summarize_ulog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ulog", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from pyulog import ULog

    with args.ulog.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    summary = summarize_ulog(ULog(str(args.ulog)))
    summary.update({"ulog_sha256": digest, "ulog_bytes": args.ulog.stat().st_size,
                    "pyulog_version": version("pyulog")})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["basic_topic_gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
