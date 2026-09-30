"""Stop only processes whose Linux identity was recorded by this run."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from flydrones.process_ownership import load_process_registry, stop_owned_processes


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--timeout-s", type=float, default=2.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    output = args.output or args.registry.parent / "cleanup-evidence.json"
    records = load_process_registry(args.registry)
    evidence = stop_owned_processes(records, timeout_s=args.timeout_s)
    payload: dict[str, object] = {
        "schema": "flydrones-owned-process-cleanup-v1",
        "registry": str(args.registry),
        "recorded_processes": len(records),
        **evidence,
    }
    _atomic_json(output, payload)
    return 2 if evidence["ownership_mismatch"] or evidence["failed_to_stop"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
