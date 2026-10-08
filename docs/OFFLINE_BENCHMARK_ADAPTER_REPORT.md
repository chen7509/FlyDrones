# Offline benchmark observation adapter and contract stat guard

Date: 2026-10-09. Base 2889693; stat guard 6eb290c; adapter cfd3e8e.
This stage remains offline and does not complete the FlyDrones goal.

## Results and scope

The learned rate core now has an `OfflineBenchmarkController` implementing the
existing reset/step(Observation)/close boundary. It copies RGB, depth, position,
velocity and goal arrays without changing their dtype, axes or units; carries
simulation/image timestamps, yaw and yaw rate unchanged; and reuses the existing
`SequenceFrame` feature mapping and recurrent inference implementation. The core
does not use camera_pose. A caller must own an observation during conversion;
copying is not synchronization against concurrent mutation.

The adapter requires explicitly supplied limits and either `synthetic` or
`gazebo-model-truth` input labeling. These are declarations, not verified sensor
sources. `input_source_verified`, training success and flight eligibility remain
false. PX4/EKF2/VIO source labels are refused rather than certified from a string.
Output commands remain ENU velocity and yaw-rate intent. Outer elapsed time covers
conversion and the inner call; inner inference timing is separately recorded.
Conversion or inference failure latches until an explicit successful reset;
close remains terminal. One caller owns the controller and loaded core.

This adapter is **not registered with the physical run_episode.py entry point**.
It neither replaces its old LIF controller nor changes frozen comparison evidence.
No simulation, native estimator, training job, ODOMETRY or flight was started.
Full learned-core construction/inference remains unmeasured after the earlier resource refusal. The
actual small core used in unit tests validates the boundary, not learning,
navigation, division, full timing or superiority over EGO.

## Existing regression investigation

The prior full suite failed once in the unchanged execution-contract recorder's
`before != after` stat comparison. A focused rerun passed, and 200 independent
stat/read/stat trials did not reproduce it. The original field values were not
logged, so its precise cause remains unproven; the old failed log is retained in
`evidence/connectome-inference-probe-dev-1701.zip` (SHA256
04f196671982358f4dfeb0030641112592aed546213b1b82faf6b886d6f9cc02).

Inspection identified independently reproducible defects: stat tuple equality
includes access time, which a read may change, but does not compare the nanosecond
mtime/ctime attributes. Deterministic OS-boundary injections reproduced one false
refusal and two missed mutations (3 failed, 7 passed). The recorder now explicitly
checks mode, inode, device, link count, uid, gid, size, mtime_ns and ctime_ns;
access time is excluded. A rejection reports each changed field with before/after
values. File hashes and the remaining execution/environment checks are unchanged.
This is ordinary drift detection, not an atomic snapshot or hostile ABA defense.

The 10 injected cases use real file I/O and actual os.stat_result objects with
controlled OS metadata, not a claim that the original Windows failure was
reproduced. Nanosecond precision is used where supplied; filesystem precision can
be coarser. No timestamp was changed in historical evidence or execution inputs.

## Research and reuse decisions

- CPython installed 3.12.10, PSF license: reuse pathlib/os.stat and existing
  hashlib instead of adding a filesystem watcher or platform service. The
  [official 3.12 API documentation](https://docs.python.org/3.12/library/os.html#os.stat_result)
  distinguishes access, modification and change time, and recommends nanosecond
  fields to retain available precision. Retrieved docs render 3.12.15; this does
  not assert installed patch equivalence or a maintenance SLA.
- [Microsoft File Times](https://learn.microsoft.com/en-us/windows/win32/sysinfo/file-times)
  documents filesystem-dependent access updates, including delayed NTFS updates.
  Its semantics support excluding access time from content mutation detection;
  they do not prove the original failing field. This is documentation, not a
  new redistributable dependency.
- Existing project Observation, SequenceFrame, inference loader/controller and
  shared command shaping are reused at the commits above. Existing Torch
  2.14.0+cpu/NumPy 2.3.4 remain unchanged; no library installation or alternative
  algorithm is introduced. Prior loader/probe research records their versions
  and adoption. A new flight controller, PPO substitute or duplicated feature
  formula was rejected: none is necessary for this interface conversion.

The new work adds only bounded copying, metadata comparison and Python adapter
overhead; full-model resource and latency cost have not been measured.

## Verification

- Stat guard: 3 behavioral RED failures and 7 already-passing cases; then 73
  contract/preflight tests passed in 11.49 seconds.
- Adapter: initial 12 failures asserted a missing API, not 12 discovered behavior
  bugs. Following implementation, 131 combined related tests passed in 11.79
  seconds with one known sparse-checkpoint warning. Real tiny-core commands and
  recurrent behavior match direct calls; timestamps, copied fields, explicit
  limits, source refusal and failure/reset/close are exercised.
- Changed-file Ruff and diff checks passed. The full suite on production commit
  cfd3e8e finished **3920 passed, 33 skipped, 3 warnings in 655.43 seconds**.
  The warnings are the deliberate duplicate ZIP member, sparse checkpoint check,
  and existing missing-neuron-group warning. Skipped tests are not validated.
- Independent read-only review found no Critical or Important issue and one
  Minor coverage gap: uniform RGB and absent dtype assertions. Distinct pixels
  and channels plus float32/float64 depth were added afterward. The final changed
  test file passed **13 tests in 1.08 seconds**, after the full suite finished.
  This coverage addition is GREEN, not a claimed production defect or RED fix.
  The full suite had collected the earlier 12 adapter cases; it was not rerun
  merely for this test-only addition. Production code did not change after it.

Post-test host observation at 05:26:55 +08:00 found no matching Python/PX4/Gazebo/
online_probe process and 1,282,977,792 available bytes, still below the fixed
4,294,967,296-byte full inference preflight. No full-model retry was launched.
Docker service remained Stopped; the pinned EGO image was not inspected or run.
These are current observations, not permanent machine infeasibility claims.

## Remaining requirements

The historical stat failure's exact field remains unknown. The new rejection
diagnostic supports future investigation without loosening mutation checks.
Full learned-core timing needs the predeclared resource gate. A trustworthy
deployment-visible observation producer and corpus/teacher integration remain
missing; the current physical benchmark declares truth-derived observations.
Library protocol compatibility is not evidence that a real benchmark or an
EKF2-controlled aircraft used the adapter. Full learning/division, held-out fair
comparison, the failed five-camera 0.873 RTF gate, and hardware/HITL/flight remain
open. Changes stay local under the existing publication limitation.
