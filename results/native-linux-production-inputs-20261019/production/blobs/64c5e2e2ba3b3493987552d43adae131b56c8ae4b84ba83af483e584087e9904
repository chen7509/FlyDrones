"""Read-only check of a prospective PX4 v1.17 odometry logger file."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src/flydrones/connectome_training/px4_logger_diagnostic_profile.py"
SPEC = importlib.util.spec_from_file_location("px4_logger_diagnostic_profile", MODULE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("PX4 logger diagnostic profile module unavailable")
profile = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = profile
SPEC.loader.exec_module(profile)


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _read_stable(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise OSError("input is missing, symlinked, or not a regular file")
    before = path.stat()
    if before.st_size > limit:
        raise OSError("input exceeds audit size limit")
    raw = path.read_bytes()
    after = path.stat()
    def identity(stat):
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns
    if identity(before) != identity(after) or len(raw) != before.st_size:
        raise OSError("input changed during audit")
    return raw


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate declaration key")
        value[key] = item
    return value


def main(argv: list[str] | None = None) -> int:
    parser = _ArgumentParser(description=__doc__)
    parser.add_argument("--topics", type=Path, required=True)
    parser.add_argument("--declaration", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
    except ValueError:
        print(json.dumps({
            "schema": "flydrones.px4_logger_diagnostic_audit.v1",
            "topics_path": None,
            "declaration_path": None,
            "topics_sha256": None,
            "declaration_sha256": None,
            "audit": asdict(profile.LoggerProfileAudit("cli_arguments_invalid")),
            "eligible_for_live_capture": False,
        }, indent=2, sort_keys=True))
        return 1
    topics, declaration = None, None
    try:
        topics = _read_stable(args.topics, 1000)
        declaration = _read_stable(args.declaration, 4096)
    except OSError:
        audit = profile.LoggerProfileAudit("input_unavailable")
    else:
        try:
            value = json.loads(declaration.decode("utf-8"), object_pairs_hook=_unique_object)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            audit = profile.LoggerProfileAudit("declaration_json_invalid")
        else:
            audit = profile.audit_profile(topics, value)
    result = {
        "schema": "flydrones.px4_logger_diagnostic_audit.v1",
        "topics_path": str(args.topics),
        "declaration_path": str(args.declaration),
        "topics_sha256": hashlib.sha256(topics).hexdigest() if topics is not None else None,
        "declaration_sha256": (hashlib.sha256(declaration).hexdigest()
                               if declaration is not None else None),
        "audit": asdict(audit),
        "eligible_for_live_capture": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if audit.logger_file_candidate else 1


if __name__ == "__main__":
    raise SystemExit(main())
