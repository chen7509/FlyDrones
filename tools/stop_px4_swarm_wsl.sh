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
    rm -rf "$model_root/$model"
    if [[ -d "$run_dir/backups/$model" ]]; then
      cp -a "$run_dir/backups/$model" "$model_root/$model"
    fi
  done
  rm -f "$run_dir/fault-mode"
fi
echo "FlyDrones five-vehicle PX4/Gazebo processes stopped."
exit "$cleanup_status"
