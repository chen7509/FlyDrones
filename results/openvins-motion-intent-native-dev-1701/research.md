# Native motion-intent integration research

## Fixed upstream and license

- OpenVINS is fixed at `69488123ed9362dd44b6f28e7f4680abbff1442b`.
  Its repository and source headers identify GPL-3.0-or-later.  The previously
  recorded repository metadata says non-archived and last pushed on
  2025-11-30; that observation is reused and does not establish current
  maintenance cadence.
- Official source inspected at the exact commit:
  `https://github.com/rpng/open_vins/blob/69488123ed9362dd44b6f28e7f4680abbff1442b/ov_msckf/src/core/VioManager.h`
  and `VioManager.cpp`.  The header makes `params`, `is_initialized_vio`,
  `did_zupt_update` and `has_moved_since_zupt` protected.  The implementation
  feeds and attempts ZUPT only while beginning-only mode has not observed
  movement.
- Official API and derivation pages inspected:
  `https://docs.openvins.com/classov__msckf_1_1VioManager.html` and
  `https://docs.openvins.com/update-zerovelocity.html`.  They support the
  manager ownership and stationary-measurement interpretation; they do not
  validate this adapter or its flight safety.

## Installed source and binary identity

- Installed `VioManager.h` SHA-256:
  `7afa93033a85656f16a32bba9324887bfdc4a1272c3fe53567d16bd28da4c1e2`.
- Installed `VioManager.cpp` SHA-256:
  `13d0c40710f2d267e8b5967c9a91d026c12a79fec174b63154942ae97b896182`.
- Installed `VioManagerOptions.h` SHA-256:
  `68ceb7fbf67d52e24eab4552ac202ab0299e6dad9cfbcc497a5d4752e13e4aac`.
- Linked `libov_msckf_lib.so` SHA-256:
  `532ae57a6a952a0137cc1de291bc47ad556d419c7524fbb23b7a90c00addab5b`.
- The upstream worktree has two pre-existing, already disclosed modifications:
  `ov_init/src/init/InertialInitializer.cpp` and
  `ov_msckf/src/core/VioManagerHelper.cpp`.  Neither `VioManager.h`,
  `VioManager.cpp` nor `VioManagerOptions.h` is modified.  The linked library
  is the same frozen library used by the sealed run; installed-patch
  equivalence to a pristine upstream build is not claimed.
- Compiler: Ubuntu g++ 13.3.0.  The final adapter binary is
  `online_probe-v2`, SHA-256
  `d7252cdb97b4b73baa64f6950e3a03299fd4e0c6bb8252a568fcbc118218719e`.
  No package was installed.

## Selection

Adopted: add a narrow method only in the existing GPL-linked research
executable subclass.  It verifies internal initialization and the frozen
`try_zupt=true`, `zupt_only_at_beginning=true` options, then sets the existing
movement flag before the externally scheduled actuation time.  The MIT Python
side contains only a bounded `M` message, identity hashes, strict
acknowledgement projection and evidence gate.

Rejected:

- Globally disabling ZUPT: changes the static initialization path and is not
  equivalent to suppressing an invalid update after a command.
- Changing disparity, speed or noise thresholds from the sealed failure:
  would tune on the test evidence and would not prove the command handoff.
- Gazebo pose/velocity detection or true-motion feedback: violates the
  truth-free estimator input boundary.
- A new ROS, DDS or network service: adds clocks, dependencies, resource use
  and another worker without solving the single-owner state transition.
- Editing or rebuilding the OpenVINS library: unnecessary for the protected
  subclass interface and would invalidate the pinned binary baseline.

## Resource and evidence limits

The adapter reuses the single existing native process, pipe, OpenCV and
OpenVINS library.  The fixed replay ran without PX4, Gazebo, network output,
ODOMETRY or EKF2.  Historical source arrival clocks were replaced by a new
monotonic replay clock and are not latency evidence.  The replay stops after
the 3.0 s camera state, so it proves the handoff and early ZUPT suppression on
sealed input, not full-trajectory accuracy or physical behavior.
