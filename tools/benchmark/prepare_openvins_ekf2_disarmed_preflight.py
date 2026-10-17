"""Write one immutable, prepare-only OpenVINS-to-PX4 preflight record."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.benchmark.openvins_ekf2_disarmed_preflight import build_preflight_evidence  # noqa: E402


def load_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected JSON object: " + str(path))
    return value


def implementation_identity(commit: str, paths: list[Path]) -> dict:
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit.lower()):
        raise ValueError("invalid implementation commit")
    if not paths:
        raise ValueError("missing implementation files")
    records = []
    seen = set()
    for raw_path in paths:
        path = raw_path.resolve(strict=True)
        if path in seen or not path.is_file():
            raise ValueError("duplicate or invalid implementation file: " + str(path))
        seen.add(path)
        data = path.read_bytes()
        records.append({"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return {"commit": commit.lower(), "files": records}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-binding", type=Path, required=True)
    parser.add_argument("--parameter-baseline", type=Path, required=True)
    parser.add_argument("--implementation-commit", required=True)
    parser.add_argument("--implementation-file", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError(args.output)
    evidence = build_preflight_evidence(load_object(args.runtime_binding), load_object(args.parameter_baseline))
    evidence["implementation"] = implementation_identity(args.implementation_commit, args.implementation_file)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
