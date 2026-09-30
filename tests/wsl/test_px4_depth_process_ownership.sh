#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
run_dir="$(mktemp -d /tmp/flydrones-owned-processes.XXXXXX)"
owned_one=""
owned_two=""
unregistered=""

cleanup() {
  for pid in "$owned_one" "$owned_two" "$unregistered"; do
    [[ -n "$pid" ]] && kill -9 "$pid" 2>/dev/null || true
  done
  rm -rf "$run_dir"
}
trap cleanup EXIT

set +e
invalid_output="$(FLYDRONES_GZ_RENDER_PROFILE=not-a-renderer PX4_ROOT=/definitely/missing \
  bash "$repo_root/tools/launch_px4_depth_swarm_wsl.sh" 2>&1)"
invalid_status=$?
set -e
[[ "$invalid_status" -eq 2 ]]
[[ "$invalid_output" == *"unsupported Gazebo renderer profile"* ]]

sleep 300 & owned_one=$!
sleep 300 & owned_two=$!
sleep 300 & unregistered=$!
sleep 0.1

PYTHONPATH="$repo_root/src" python3 - "$run_dir/owned-processes.json" "$owned_one" "$owned_two" <<'PY'
import sys
from pathlib import Path

from flydrones.process_ownership import append_process_identity

registry = Path(sys.argv[1])
append_process_identity(registry, int(sys.argv[2]), "owned-one")
append_process_identity(registry, int(sys.argv[3]), "owned-two")
PY

set +e
FLYDRONES_PX4_RUN_DIR="$run_dir" bash "$repo_root/tools/stop_px4_swarm_wsl.sh"
stop_status=$?
set -e
if [[ "$stop_status" -ne 0 ]]; then
  cat "$run_dir/cleanup-evidence.json" >&2 || true
  exit "$stop_status"
fi
wait "$owned_one" 2>/dev/null || true
wait "$owned_two" 2>/dev/null || true
if kill -0 "$owned_one" 2>/dev/null; then
  echo "registered process $owned_one survived cleanup" >&2
  exit 1
fi
if kill -0 "$owned_two" 2>/dev/null; then
  echo "registered process $owned_two survived cleanup" >&2
  exit 1
fi
kill -0 "$unregistered" 2>/dev/null

PYTHONPATH="$repo_root/src" python3 - "$run_dir/owned-processes.json" "$unregistered" <<'PY'
import json
import sys
from pathlib import Path

from flydrones.process_ownership import read_process_identity

path = Path(sys.argv[1])
record = read_process_identity(int(sys.argv[2]), role="stale-unregistered").to_dict()
record["start_ticks"] -= 1
path.write_text(json.dumps({"schema": "flydrones-owned-processes-v1", "processes": [record]}), encoding="utf-8")
PY

set +e
PYTHONPATH="$repo_root/src" python3 "$repo_root/tools/stop_owned_processes_wsl.py" \
  --registry "$run_dir/owned-processes.json" --timeout-s 0.1
status=$?
set -e
[[ "$status" -ne 0 ]]
kill -0 "$unregistered" 2>/dev/null
python3 - "$run_dir/cleanup-evidence.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert len(payload["ownership_mismatch"]) == 1
assert payload["stopped"] == []
PY
