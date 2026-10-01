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

The first three RTF values were 0.8769211765, 0.8473785794, and 0.8225722368.
Their mean was 0.8489573309 and range was 0.0543489397. They used identical
working-tree input hashes, but Git line-ending normalization changed the runner
hash on commit. They remain historical development evidence. The three runs
using the committed runner bytes measured 0.8694998992, 0.8772845673, and
0.8716535042 RTF. Their mean was 0.8728126569 and range was 0.0077846681.
The 0.03 scored-RTF repeatability gate passed, but the 0.95 performance gate
failed. An additional committed-byte attempt timed out waiting for camera
trigger connections before scoring; its failure is retained separately.
One-camera, five-camera, and the formal 12-slot campaign were not started. An
earlier exploratory loopback trial reached 0.9122179464 RTF but predates runtime
`GZ_IP` attestation.

A loopback profiler trial reached 0.8875003265 RTF with about 11,000 samples and
zero lost samples. The sampled hotspot mix remained dominated by Gazebo
Transport discovery and DART physics. This supports retaining explicit
loopback isolation for local WSL tests, but does not establish real-time
capacity.

Files:

- `repetitions.json`: all three formal scores, health, hash, ULog, and cleanup
  results from the pre-commit working tree.
- `committed-repetitions.json`: three scored runs from the committed runner.
- `committed-renderer-attestation.json`: renderer and live transport proof for
  those three runs.
- `committed-startup-failure.json`: retained unscored camera trigger connection
  timeout from the same committed inputs.
- `committed-trial-config.json`: exact trial configuration used for the
  committed-byte repetitions.
- `raw-clock-crosscheck.json`: independent RTF calculation from each run's
  raw clock CSV, with source hashes.
- `renderer-attestation-summary.json`: per-run renderer, depth, server-config,
  GStreamer absence, and live `GZ_IP` proof.
- `profile-summary.json`: loopback profiler result and hotspot percentages.
- `thread-profile-summary.json`: scored-window, per-thread samples linked to
  the raw `perf script` and epoch hashes.
- `rejected-server-systems.json`: valid screening evidence for the rejected
  Contact/OpticalFlow system-removal experiment.
- `raw-artifact-index.json`: hashes of this compact snapshot.
