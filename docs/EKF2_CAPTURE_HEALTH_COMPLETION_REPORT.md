# EKF2 capture-health evidence completion

## Result

The checked EGO teacher recorder now rejects a supplied PX4 estimate unless
horizontal and vertical velocity are valid, dead reckoning is false, filter
fault flags are exactly zero, and a separate estimator-status sample is causal
and no more than 100 ms old. It still requires the earlier position, heading,
calibration, teacher identity and non-truth gates. Rejection happens before a
frame, target or reference is appended. These fields are caller-supplied
evidence; this change **does not authenticate a live PX4 producer** or enable
training, fusion or flight.

Pinned PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4` defines the relevant
fields in
[`VehicleLocalPosition.msg`](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/msg/versioned/VehicleLocalPosition.msg)
and
[`EstimatorStatus.msg`](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/msg/EstimatorStatus.msg).
The pinned PX4 source is BSD-3-Clause. The existing `pyulog` 1.2.4 parser is
BSD-3-Clause; no new runtime dependency, simulator load or model load was
introduced. Upstream maintenance, interface and resource/adaptation choices
are already recorded in `docs/PX4_ODOMETRY_CAUSAL_ADAPTER_REPORT.md` and
`docs/PX4_ULOG_ODOMETRY_PREFLIGHT_REPORT.md`.

## Retrospective physical evidence

The read-only auditor verified each ULog, its capture manifest and its
OpenVINS health journal against the historical
`evidence/openvins-health-contract-dev-1701.zip` (SHA-256
`88c11d16ec19b52d590cd07622def74262d33837abf611cbf97bfe84f8d99347`)
and that archive's per-member hashes. It parsed every public OpenVINS camera
row from a single verified byte read and retained every per-frame reason from
the existing `ekf2_shadow` auditors.
It made no change to the frozen OpenVINS covariance cohort or held-out seeds.
The first retrospective audit was preserved: independent review identified
that it had read the health journal twice without binding its hash to parsed
bytes. The corrected `v2` audit binds both reads. A further review found that
`pyulog` still reopened the ULog path, so `v3` parses the already verified
ULog bytes through its readable-file API. All three versions produce the same
four sets of per-frame results, and the earlier outputs remain preserved.

| Original run | ULog SHA-256 | Public VIO frames | PX4 healthy at those frames | Sample-time usable | Heading invalid |
| --- | --- | ---: | ---: | ---: | ---: |
| development 27201 | `55428c6d37e75d7fa2d53ab67a6527b4350fa020dca4a761a44fa7aec68d1028` | 222 | 1 | 220 | 221 |
| held-out 27211 | `42f10230c9ff24c8a9f401c6d41118c0b43acbed99a1c16797969750ebcce85d` | 222 | 0 | 220 | 222 |
| held-out 27212 | `00fa3c1d660000447a0638e575407a7d1aefe0b1f911af751cdd4c269c7848a7` | 222 | 1 | 220 | 221 |
| held-out 27213 | `aaabc5cb89cfd03b1c3d0fa49a0a6ea745ce12ff3091134a7d7fc7c4da9b3efa` | 222 | 1 | 220 | 221 |

Thus the existing publication-time PX4 health audit accepts only 3 of 888
public VIO camera frames; 885 have invalid heading at the selected PX4 sample.
Each ULog lacks `vehicle_odometry`. This is consistent with, but cannot by
itself prove, the absence of VIO→EKF2 fusion. The four OpenVINS runs' previous
simulation-domain covariance result remains valid within its original scope;
it is not PX4 heading, velocity or closed-loop qualification. No VIO training
or EGO teacher collection was done here.

The alignment assumes a common simulation epoch between health journals and
ULog timestamps. It has not independently authenticated that clock relation.
`time_epoch_qualified`, `source_authenticated`,
`camera_calibration_qualified`, `fusion_qualified` and `training_eligible`
remain false in the audit. Missing `vehicle_odometry` also prevents the
exact-field crosscheck from qualifying these runs.

## Validation and status

- Initial field-shape RED and subsequent behavioral RED were retained; after
  implementation, the final focused suite passed 54 tests, including malformed
  types, stale/future status and recorder no-mutation cases.
- Full `tests/connectome_training` regression passed: 570 passed, 2 skipped,
  2 existing PyTorch warnings. Changed-file Ruff and diff checks passed after
  fixing the audit script's import order.
- Verified: synthetic fail-closed checked-recorder gate and read-only ULog
  alignment on four original physical captures.
- Implemented but unverified against a producer: binding these fields to
  authenticated live PX4 messages and calibrated camera extrinsics.
- Failed/unqualified: PX4 heading-health availability in the four old runs,
  source identity, fusion evidence and student capture eligibility. The
  pre-existing five-camera 0.873 RTF result remains below its 0.95 threshold.
- Not tested: a new physical run, hardware calibration, HITL or flight.

The next dependency is an authenticated, causal producer for PX4 local
position/status and calibrated camera evidence. Resource constraints still
prevent treating a Docker-ready host as ready for the frozen physical study.
