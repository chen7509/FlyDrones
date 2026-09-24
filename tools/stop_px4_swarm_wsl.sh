#!/usr/bin/env bash
set -euo pipefail

run_dir="${FLYDRONES_PX4_RUN_DIR:-/tmp/flydrones-px4-five}"
px4_root="${PX4_ROOT:-$HOME/PX4-Autopilot}"
build="$px4_root/build/px4_sitl_default"
if [[ -d "$run_dir" ]]; then
  if [[ -f "$run_dir/vio-relay.pid" ]]; then
    kill "$(cat "$run_dir/vio-relay.pid")" 2>/dev/null || true
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
echo "FlyDrones five-vehicle PX4/Gazebo processes stopped."
