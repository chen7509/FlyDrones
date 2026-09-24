#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
px4_root="${PX4_ROOT:-$HOME/PX4-Autopilot}"
build="$px4_root/build/px4_sitl_default"
run_dir="${FLYDRONES_PX4_RUN_DIR:-/tmp/flydrones-px4-five-depth}"
world_source="$repo_root/results/px4-sitl-five-depth/flydrones_forest.sdf"
world_target="$px4_root/Tools/simulation/gz/worlds/flydrones_forest.sdf"
model_root="$px4_root/Tools/simulation/gz/models"

if [[ ! -x "$build/bin/px4" ]]; then
  echo "PX4 SITL binary is missing: $build/bin/px4" >&2
  exit 2
fi

PYTHONPATH="$repo_root/src" python3 "$repo_root/tools/generate_px4_forest_world.py" --output "$world_source" --lane-spacing 2.0
cp "$world_source" "$world_target"
rm -rf "$model_root/OakD-Lite-Fly" "$model_root/x500_depth_fly"
cp -r "$repo_root/assets/gazebo/models/OakD-Lite-Fly" "$model_root/OakD-Lite-Fly"
cp -r "$repo_root/assets/gazebo/models/x500_depth_fly" "$model_root/x500_depth_fly"

for port in 14580 14581 14582 14583 14584; do
  pids="$(ss -H -lunp "sport = :$port" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | sort -u)"
  if [[ -n "$pids" ]]; then kill $pids 2>/dev/null || true; fi
done
pkill -9 -f "^$build/bin/px4 -i [0-4] -d $build/etc$" 2>/dev/null || true
pkill -9 -f '^px4-gz_bridge --instance [0-4] start -w flydrones_forest' 2>/dev/null || true
pkill -9 -f '^gz sim .*Tools/simulation/gz/worlds/flydrones_forest.sdf$' 2>/dev/null || true
sleep 2

rm -rf "$run_dir"
mkdir -p "$run_dir"
poses=(-4.0 -2.0 0.0 2.0 4.0)
for instance_id in 0 1 2 3 4; do
  instance_dir="$run_dir/instance_$instance_id"
  mkdir -p "$instance_dir"
  ln -sf "$build/rootfs/gz_env.sh" "$instance_dir/gz_env.sh"
  extra_env=()
  if [[ "$instance_id" -gt 0 ]]; then extra_env+=(PX4_GZ_STANDALONE=1); fi
  (
    cd "$instance_dir"
    nohup env HEADLESS=1 "${extra_env[@]}" PX4_SYS_AUTOSTART=4001 PX4_GZ_WORLD=flydrones_forest \
      PX4_SIM_MODEL=gz_x500_depth_fly PX4_GZ_MODEL_POSE="0,${poses[$instance_id]},0,0,0,0" \
      "$build/bin/px4" -i "$instance_id" -d "$build/etc" \
      >"$instance_dir/out.log" 2>"$instance_dir/err.log" </dev/null &
    echo $! >"$instance_dir/pid"
  )
  if [[ "$instance_id" -eq 0 ]]; then sleep 7; else sleep 2; fi
done

for _ in $(seq 1 40); do
  running=0
  for pid_file in "$run_dir"/instance_*/pid; do
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then running=$((running + 1)); fi
  done
  depth_topics="$(gz topic -l 2>/dev/null | grep -c '/sensor/StereoOV7251/depth_image$' || true)"
  if [[ "$running" -eq 5 ]] && [[ "$depth_topics" -eq 5 ]]; then
    echo "Five PX4 x500_depth_fly instances and five isolated depth topics are ready."
    echo "MAVLink ports: 14540 14541 14542 14543 14544"
    echo "Logs: $run_dir"
    exit 0
  fi
  sleep 1
done

echo "PX4/Gazebo depth-camera startup timed out" >&2
gz topic -l 2>/dev/null | grep -E 'depth|x500_depth_fly' >&2 || true
for instance_id in 0 1 2 3 4; do
  tail -30 "$run_dir/instance_$instance_id/out.log" >&2 || true
  tail -30 "$run_dir/instance_$instance_id/err.log" >&2 || true
done
exit 3
