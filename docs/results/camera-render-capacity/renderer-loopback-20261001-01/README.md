# Gazebo Transport loopback evidence — 2026-10-01

This compact snapshot records the audited `GZ_IP=127.0.0.1` experiment on the
frozen five-PX4, Ogre2, D3D12/NVIDIA WSL zero-trigger configuration. The
run-scoped server configuration also retained the preceding removal of the
unused GStreamer camera plugin. Camera resolution, 10 Hz attestation rate,
vehicle count, physics, PX4 build, 30 simulation-second window, and thresholds
were unchanged.

The trial runner clears inherited `GZ_IP`, accepts only an explicit IPv4
loopback address, passes it to Gazebo, and the renderer attester reads
`/proc/<gazebo-pid>/environ` to prove the live server used the exact value. All
three repetitions proved `expected_gz_ip == process_gz_ip == 127.0.0.1`, five
healthy/disarmed/landed PX4 vehicles, matching frozen hashes, five ULogs, clean
owned-process teardown, and shared-file restoration.

The three RTF values were 0.8769211765, 0.8473785794, and 0.8225722368. Their
mean was 0.8489573309 and range was 0.0543489397. The 0.95 performance gate and
0.03 repeatability gate both failed, so one-camera, five-camera, and the formal
12-slot campaign were not started. An earlier exploratory loopback trial
reached 0.9122179464 RTF but predates runtime `GZ_IP` attestation and is not one
of the formal repetitions.

A loopback profiler trial reached 0.8875003265 RTF with about 11,000 samples and
zero lost samples. The sampled hotspot mix remained dominated by Gazebo
Transport discovery and DART physics. This supports retaining explicit
loopback isolation for local WSL tests, but does not establish real-time
capacity.

Files:

- `repetitions.json`: all three formal scores, health, hash, ULog, and cleanup
  results.
- `renderer-attestation-summary.json`: per-run renderer, depth, server-config,
  GStreamer absence, and live `GZ_IP` proof.
- `profile-summary.json`: loopback profiler result and hotspot percentages.
- `raw-artifact-index.json`: hashes of this compact snapshot.
