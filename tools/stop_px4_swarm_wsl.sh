#!/usr/bin/env bash
set -euo pipefail

run_dir="${FLYDRONES_PX4_RUN_DIR:-/tmp/flydrones-px4-five}"
px4_root="${PX4_ROOT:-$HOME/PX4-Autopilot}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cleanup_status=0
if [[ -d "$run_dir" ]]; then
  if [[ -f "$run_dir/owned-processes.json" ]]; then
    PYTHONPATH="$repo_root/src" python3 "$repo_root/tools/stop_owned_processes_wsl.py" \
      --registry "$run_dir/owned-processes.json" --timeout-s 2 \
      --output "$run_dir/cleanup-evidence.json" || cleanup_status=$?
  fi
fi
if [[ -f "$run_dir/fault-mode" ]]; then
  world_target="$px4_root/Tools/simulation/gz/worlds/flydrones_forest.sdf"
  model_root="$px4_root/Tools/simulation/gz/models"
  if [[ -f "$run_dir/backups/world.sdf" ]]; then
    cp -a "$run_dir/backups/world.sdf" "$world_target"
  else
    rm -f "$world_target"
  fi
  for model in OakD-Lite-Fly x500_depth_fly; do
    rm -rf "${model_root:?}/$model"
    if [[ -d "$run_dir/backups/$model" ]]; then
      cp -a "$run_dir/backups/$model" "$model_root/$model"
    fi
  done
  python3 - "$run_dir" "$world_target" "$model_root" <<'PY'
import hashlib
import json
import sys
import tempfile
from pathlib import Path

run_dir = Path(sys.argv[1])
world_target = Path(sys.argv[2])
model_root = Path(sys.argv[3])
backup_root = run_dir / "backups"

def digest(path: Path):
    if not path.exists():
        return None
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()

pairs = {
    "world": (backup_root / "world.sdf", world_target),
    "OakD-Lite-Fly": (backup_root / "OakD-Lite-Fly", model_root / "OakD-Lite-Fly"),
    "x500_depth_fly": (backup_root / "x500_depth_fly", model_root / "x500_depth_fly"),
}
items = {
    name: {
        "backup_sha256": digest(before),
        "restored_sha256": digest(after),
        "matched": digest(before) == digest(after),
    }
    for name, (before, after) in pairs.items()
}
payload = {
    "schema": "flydrones-px4-shared-restoration-v1",
    "restored": all(item["matched"] for item in items.values()),
    "items": items,
}
target = run_dir / "restoration-evidence.json"
with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=run_dir, delete=False) as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
    temporary = Path(handle.name)
temporary.replace(target)
PY
  rm -f "$run_dir/fault-mode"
fi
echo "FlyDrones five-vehicle PX4/Gazebo processes stopped."
exit "$cleanup_status"
