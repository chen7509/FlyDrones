# OpenVINS feature-rejection trace research

## Frozen upstream and license

- OpenVINS commit: `69488123ed9362dd44b6f28e7f4680abbff1442b`.
- License: GPL-3.0-or-later. The diagnostic patch is stored separately under
  `tools/benchmark/gpl/` and is not loaded by the normal FlyDrones runtime.
- Recorded repository state: non-archived, last recorded push 2025-11-30;
  2026 maintenance cadence is uncertain.
- Official sources inspected: `TrackKLT.cpp`, `FeatureDatabase.cpp/.h`,
  `VioManager.cpp/.h`, `UpdaterMSCKF.cpp`, `UpdaterSLAM.cpp`,
  `FeatureInitializer.cpp/.h`, and the upstream class documentation for those
  components. The Geneva et al. OpenVINS ICRA 2020 paper remains the algorithm
  reference.

## Adopted approach

The public database and tracker APIs expose current features but not the exact
rejection reason after an updater erases or consumes a feature. A read-only
post-hoc database snapshot therefore cannot distinguish insufficient history,
triangulation/refinement failure, initialization failure, or chi-square
rejection. The adopted method builds an isolated GPL diagnostic library with
structured counter logging only. It replays the sealed `study-v21/capture-v1`
requests through the same native adapter and compares every non-timing state
field with an uninstrumented control.

The final diagnostic patch SHA-256 is
`def348ff3f007e86fdba83ad9fe22cd612101acf6af7b5947034145fc851925a`.
The dynamically loaded diagnostic library SHA-256 is
`fc8af64f7417917c2f5f70f493adcf53d842d5439314784550c9ce0d73b38c4f`;
it is 292,684,400 bytes and is reproducible from the patch and frozen build,
so the repository retains its identity and build log rather than duplicating
the library. The native probe SHA-256 is
`945e5279ef4286ef85dda65a9bf0f1dc6532536cad951c00aee8ad0be3ac49b6`.

## Rejected approaches

- A proxy corner detector: it is not OpenVINS KLT, database, updater, or
  triangulation evidence.
- Reconstructing updater outcomes from the final feature database: rejected
  candidates have already been erased and accepted candidates may be moved to
  the SLAM state.
- Changing thresholds, feature limits, scene, texture, noise, motion, or
  configuration: that would tune the sealed input and invalidate diagnosis.
- Adding truth, Gazebo pose, or physical reference values to the estimator:
  truth remains confined to earlier offline accuracy scoring.
- Treating trace runtime as online latency: the replay uses newly generated
  monotonic clocks and is not a physical timing measurement.

## Resource and adaptation cost

The isolated worktree reuses the installed compiler and dependencies and adds
five structured record types. It requires rebuilding the 292.7 MB OpenVINS
shared library and a 406,232-byte native probe; no PX4, Gazebo, package install,
training, ODOMETRY, or EKF2 process is needed. The code cost is an isolated GPL
patch plus an MIT-side strict parser/auditor. Logging is not qualified for a
production flight build.
