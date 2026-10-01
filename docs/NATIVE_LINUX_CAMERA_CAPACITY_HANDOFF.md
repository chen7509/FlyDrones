# Native Linux camera capacity comparison

## Boot handoff (2026-10-01)

The published baseline is commit `20a6b77ee672dbcbbf2239a13696332eb5b82c2c`
on `https://github.com/chen7509/FlyDrones.git`, branch
`codex/px4-sensor-readiness`. The Windows host's internal NVMe currently shows
only EFI, Microsoft reserved, NTFS, and recovery partitions. The attached LaCie
USB-C disk shows EFI plus an exFAT data partition. These observations do not
establish a bootable native Linux installation; Ubuntu available from Windows is
WSL2. Identify and boot the native Linux medium without repartitioning either
disk as part of this trial.

After booting Linux, run this read-only preflight before installing packages,
building, or launching a simulation:

```bash
uname -a
lsblk -o NAME,TRAN,SIZE,FSTYPE,MOUNTPOINTS
command -v nvidia-smi && nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
command -v eglinfo && eglinfo -B
command -v gz && gz sim --version
pkg-config --modversion gz-transport13 gz-msgs10
```

`uname` must not identify WSL or Microsoft. Preserve the output and boot medium
description. If the NVIDIA device, Gazebo dependencies, or persistent storage
are unavailable (for example in an unprepared live USB session), stop before
the scored trial and prepare the host. Do not use the Windows/WSL PX4 binary.

On a persistent native Linux installation, fetch the frozen source with:

```bash
git clone --branch codex/px4-sensor-readiness https://github.com/chen7509/FlyDrones.git
cd FlyDrones
git rev-parse HEAD
```

Check that `HEAD` includes the baseline commit above. Subsequent native-host
adaptations must be recorded as a separate revision; compare frozen model,
world, profile, policy, and physics inputs against the baseline and explicitly
list any runner or renderer changes. Reopen the Codex task on Linux with this
handoff document and the captured preflight output before running the gates.

Status on 2026-10-01: this workstation provides Ubuntu under WSL2 only. A
native Linux trial has not been run. The current WSL baseline is the three
committed-byte, five-PX4, renderer-initialized, zero-steady-trigger trials in
[`committed-repetitions.json`](results/camera-render-capacity/renderer-loopback-20261001-01/committed-repetitions.json):
0.8694998992, 0.8772845673, and 0.8716535042 RTF. Mean 0.8728126569;
range 0.0077846681. One additional attempt timed out before scoring because
camera trigger connections never became ready. It remains in
[`committed-startup-failure.json`](results/camera-render-capacity/renderer-loopback-20261001-01/committed-startup-failure.json).

## Comparison contract

Use the same physical machine booted into Linux if available. A different
machine measures a hardware-and-platform difference, so it cannot isolate
WSL overhead. Clone the same Git commit and compare source, model, world,
sensor, scheduling, threshold, and PX4 revision hashes. Build PX4 and the
native camera observer on the Linux host. Their executable hashes can differ
because the compiler, linker, and driver stack differ; record both hashes and
do not claim bit-identical binaries. Record CPU, GPU, kernel, Gazebo Sim,
Gazebo Transport, Gazebo Messages, DART, and PX4 versions.

The WSL renderer profile forces Mesa D3D12 on NVIDIA. A native Linux run must
use a separately attested NVIDIA OpenGL/EGL renderer profile. The current
`default` profile does not require NVIDIA and may accept a software renderer;
it is insufficient for a formal comparison by itself. Keep Ogre2, five PX4
vehicles, the same SDF world, 160 × 120 `R_FLOAT32` depth cameras, 10 Hz
attestation rate, phased schedule, 30 simulation-second score window, and the
same 0.95 RTF and 0.03 range limits. Keep `GZ_IP=127.0.0.1` and the audited
depth-only GStreamer removal. The exact WSL configuration is preserved in
[`committed-trial-config.json`](results/camera-render-capacity/renderer-loopback-20261001-01/committed-trial-config.json).

Do not reuse the WSL `px4_build_identity`, `readiness_gate_inputs`, or
`expected_hashes` on Linux. Rebuild and rerun the native host's PX4 sensor
readiness gate, then freeze that host's binary, patch, config, and source
hashes. The trial runner deliberately rejects stale frozen hashes. Record a
host-specific configuration and the exact Git commit before any scored run.

## Execution order on the native host

1. Confirm `uname` does not contain `Microsoft` or `WSL`. Confirm the actual
   EGL renderer is NVIDIA hardware, and `gz sim`, PX4, `eglinfo`, and the
   required `gz-transport13` and `gz-msgs10` development packages are present.
2. Build and verify the no-lockstep PX4 binary with the frozen first-IMU-sample
   patch. Run its ten-slot sensor readiness gate and preserve all five ULogs
   per slot. Build the native camera observer with
   `tools/build_camera_phase_native_wsl.sh --test`.
3. Freeze the Linux-specific config and hashes. Verify the live Gazebo process
   uses the selected NVIDIA renderer, the exact private server config,
   `GZ_IP=127.0.0.1`, and five healthy depth streams during attestation.
4. Run the three zero-steady-trigger slots `capacity-01-idle-0-r1`,
   `capacity-08-idle-0-r2`, and `capacity-10-idle-0-r3` sequentially in fresh
   output directories. Retain every invalid startup and all scored failures.
   Verify owned-process cleanup and shared-file restoration before each next
   run.
5. Advance only if all three runs have valid evidence, each RTF is at least
   0.95, and their range is no more than 0.03. Then run the one-camera and
   five-camera cells, followed by the frozen 12-slot campaign under its own
   gate. Do not change the camera, vehicle, physics, or thresholds to pass a
   stage.

The current WSL profile separates the main simulation thread from a busy
Gazebo Transport discovery thread. In the scored window, 2,072 of 2,976 main
simulation-thread samples (69.6%) contain DART calls, while 3,889 of 3,897
samples on another thread contain Transport discovery. These are overlapping
CPU stack counts, not predicted speedups. The native comparison must report
per-thread CPU, wall-clock RTF, and any startup failures separately.
