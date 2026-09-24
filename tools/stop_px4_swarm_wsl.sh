#!/usr/bin/env bash
set -euo pipefail

run_dir="${FLYDRONES_PX4_RUN_DIR:-/tmp/flydrones-px4-five}"
px4_root="${PX4_ROOT:-$HOME/PX4-Autopilot}"
build="$px4_root/build/px4_sitl_default"
if [[ -d "$run_dir" ]]; then
  if [[ -f "$run_dir/vio-relay.pid" ]]; then
    relay_pid="$(cat "$run_dir/vio-relay.pid")"
    kill "$relay_pid" 2>/dev/null || true
    for _ in $(seq 1 50); do
      if ! kill -0 "$relay_pid" 2>/dev/null; then break; fi
      if [[ "$(ps -o stat= -p "$relay_pid" 2>/dev/null || true)" == Z* ]]; then break; fi
      sleep 0.1
    done
    if kill -0 "$relay_pid" 2>/dev/null; then
      kill -9 "$relay_pid" 2>/dev/null || true
    fi
  fi
  for pid_file in "$run_dir"/instance_*/pid; do
    [[ -f "$pid_file" ]] || continue
    pid="$(cat "$pid_file")"
    kill "$pid" 2>/dev/null || true
  done
fi
pkill -f "^$build/bin/px4 -i [0-4] -d $build/etc$" 2>/dev/null || true
pkill -f '^px4-gz_bridge --instance [0-4] start -w flydrones_forest' 2>/dev/null || true
pkill -f '^gz sim .*flydrones_forest.sdf$' 2>/dev/null || true
for _ in $(seq 1 20); do
  if ! pgrep -f "^$build/bin/px4 -i [0-4] -d $build/etc$" >/dev/null \
      && ! pgrep -f '^px4-gz_bridge --instance [0-4] start -w flydrones_forest' >/dev/null \
      && ! pgrep -f '^gz sim .*flydrones_forest.sdf$' >/dev/null; then
    break
  fi
  sleep 0.1
done
pkill -9 -f "^$build/bin/px4 -i [0-4] -d $build/etc$" 2>/dev/null || true
pkill -9 -f '^px4-gz_bridge --instance [0-4] start -w flydrones_forest' 2>/dev/null || true
pkill -9 -f '^gz sim .*flydrones_forest.sdf$' 2>/dev/null || true
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
