#!/usr/bin/env bash
# One offline synthetic ROS callback plus bounded journal I/O fault cases.
source /opt/ros/humble/setup.bash
source /workspace/install/setup.bash
set -u
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=229
export ROS_HOME=/case/ros-home
export HOME=/case/home
mkdir -p "$ROS_HOME" "$HOME"
gcc -O2 -shared -fPIC -o /case/libstatus_journal_fault.so \
  /tools/status_journal_fault.c -ldl
sha256sum /case/libstatus_journal_fault.so > /case/shim.sha256
binary=/workspace/install/flydrones_px4_status_ros2_source/lib/flydrones_px4_status_ros2_source/px4_estimator_status_source
sha256sum "$binary" > /case/subscriber.sha256
for mode in normal fsync_eio close_eio partial_then_eio; do
  mkdir -p "/case/$mode" "/case/roslog-$mode"
  export ROS_LOG_DIR="/case/roslog-$mode"
  if [[ "$mode" == normal ]]; then
    timeout 15s "$binary" "/case/$mode/source.jsonl" "status-synthetic-$mode" 8 3 \
      > "/case/$mode/subscriber.log" 2>&1 &
  else
    timeout 15s env FAULT_MODE="$mode" FAULT_TARGET="/case/$mode/source.jsonl" \
      LD_PRELOAD=/case/libstatus_journal_fault.so "$binary" \
      "/case/$mode/source.jsonl" "status-synthetic-$mode" 8 3 \
      > "/case/$mode/subscriber.log" 2>&1 &
  fi
  subscriber=$!
  sleep 0.4
  timeout 12s python3 /tools/status_synthetic_pub.py --count 3 \
    > "/case/$mode/publisher.log" 2>&1
  printf '%s\n' "$?" > "/case/$mode/publisher.exit"
  wait "$subscriber"
  printf '%s\n' "$?" > "/case/$mode/subscriber.exit"
done
python3 /tools/status_synthetic_cdr_check.py /case/normal/source.jsonl \
  > /case/normal/cdr-parity.json
