#!/usr/bin/env bash
set -euo pipefail

trace_root=/home/yuchen7509/flydrones-upstream/open_vins_feature_trace
repo=/mnt/c/Users/yuche/.codex/worktrees/FlyDrones/track-eligibility
output="$repo/results/openvins-feature-rejection-trace-dev-1701/online_probe_trace"

cd "$trace_root"
g++ -std=c++17 -O2 \
  -I./ov_msckf/src -I./ov_core/src -I./ov_init/src \
  -I/usr/include/eigen3 -I/usr/include/opencv4 \
  "$repo/tools/benchmark/openvins_online_probe.cpp" \
  -L./ov_msckf/build \
  -Wl,-rpath,/home/yuchen7509/flydrones-upstream/open_vins_feature_trace/ov_msckf/build \
  -lov_msckf_lib \
  $(pkg-config --libs opencv4) \
  -lboost_date_time -lboost_filesystem -lboost_system -lboost_thread -pthread \
  -o "$output"

sha256sum ov_msckf/build/libov_msckf_lib.so "$output"
ldd "$output" | grep libov_msckf
