# EKF2 development state-time diagnostic

Date: 2026-10-09. Production code and frozen method: `3eda64c`.

## Result and effect on the next step

The retained **development seed 27201** has no publication-versus-sample age
discrepancy in the selected position/attitude rows. Timing alone does not explain
why its PX4 state cannot yet supply the student corpus. Of all 251 original
camera times, 221 have timing-usable state under the explicitly **uncalibrated
shared simulation-epoch assumption**. The separate existing health auditor
returns 1 valid, 220 invalid and 30 missing. Its only healthy frame is 4.0 s,
classified as GNSS, not external vision. No training sequence was produced.

The immediate dependency is therefore a trustworthy EKF2 output producer with
explicit heading health, reset coherence, source and camera/clock calibration.
Do not treat the already successful standalone VIO trajectory as proof that
PX4 is receiving it, or remove the heading gate to obtain training data. This
study did not publish ODOMETRY, inject EKF2, change parameters, arm, train, start
WSL, inspect/start Docker, construct a full neural model, or run a simulator.

## What changed

`audit_state_sample_times()` is a pure companion to the unchanged v1 shadow
auditor in `src/flydrones/benchmark/ekf2_shadow.py`. It selects messages by
publication time at or before each frame, then independently checks raw sample
time. A future publication with an old sample cannot enter an earlier frame.
It records both ages, their difference, selected row identity and cross-topic
sample skew. Zero/future/nonincreasing sample times remain visible; timing
faults invalidate the subsequent topic history rather than silently restoring
it. Malformed types/shapes/ranges and nonincreasing publication times refuse
the input. Empty topics preserve all frames as missing.

The 100 ms age boundary is unchanged. A 50 ms state-skew diagnostic selector
uses the existing camera-pose alignment bound, not a newly qualified flight
criterion. The companion always returns `clock_epoch_qualified=false` and
`eligible_for_live_capture=false`. It does not construct Observation,
CaptureInputEvidence or camera poses, certify a teacher, check complete reset
coherence, or claim state accuracy. It does not change any capture gate.

## Exact evidence

The source is the original development capture under
`results/openvins-health-physical-dev-1701-v2/development-seed-27201/capture-v1`.
ULog SHA256:
`55428c6d37e75d7fa2d53ab67a6527b4350fa020dca4a761a44fa7aec68d1028`.
Its bytes were checked against the unchanged health-contract archive SHA256
`88c11d16ec19b52d590cd07622def74262d33837abf611cbf97bfe84f8d99347`
and the original ULog manifest. All 251 original RGB payload hashes were checked
against their manifest; pixel decoding/calibration is not part of this timing
diagnostic. Only four non-truth ULog topics were parsed, at instance 0. The
filtered ULog contains only instance 0 for those topics and no logged dropouts.
No held-out run was parsed or scored.

The current selected inputs were hashed before analysis and rechecked afterward.
These diagnostic snapshots do not backfill historical capture runtime freeze.
ULog `ver_sw` matches the fixed PX4 commit, but this does not establish that all
historically installed files or local patches matched upstream. The diagnostic
harness is retained; it is not a newly qualified capture executable.

| Observation | Result |
|---|---:|
| Original RGB timestamps retained | 251 |
| Local-position / attitude samples | 3038 / 5511 |
| Timing-usable camera instants | 221 |
| Publication-only false-fresh instants | 0 |
| Selected position sample age: P95 / max | 4 / 16 ms |
| Selected attitude sample age: P95 / max | 0 / 12 ms |
| Selected publication-minus-sample, both topics | 0 throughout |
| Maximum selected position/attitude sample skew | 4 ms |
| Existing health audit: valid / invalid / missing | 1 / 220 / 30 |
| Heading-invalid camera instants | 243 |

Both timing and health output retain every frame and all reasons. Counts of
different reasons overlap. The health output still uses its original publication
time semantics; the timing companion does not upgrade its other evidence.
The approximately 2.85 s diagnostic duration includes parsing, hashing and
analysis; it is neither flight transport latency nor fruit-fly inference time.

## Heading and resets

Only 9 of 3038 local-position messages have `heading_good_for_control=true`,
at 3.992–4.056 s. Among 34 sparse estimator status-flag samples, 24 have magnetic
heading enabled, none has `mag_aligned_in_flight`, none has EV position or EV yaw
enabled, and 25 have GNSS position enabled. The one healthy camera instant is
GNSS-classified. A single `in_air` flag in the sparse record is not arming or
real-flight evidence. The original study's separate unarmed evidence remains
in its original report.

The pinned `EKF2.cpp` derives the control-heading flag from
`isYawFinalAlignComplete()`. In the magnetometer-enabled path, `ekf.h` requires
the relevant magnetic in-flight alignment condition to persist over one second
when magnetic aiding is used. This is consistent with the observed rejection;
sparse flags and source inspection alone do not prove the entire runtime cause
or justify disabling magnetometer checks, changing thresholds, or flying higher.

Observed counter transitions include 3 horizontal position resets, 1 vertical
position reset, 2 horizontal velocity resets and a heading/quaternion reset.
Heading reset publication is 3.992 s; attitude reset publication is 3.996 s.
The future producer must not splice a pre-reset attitude with post-reset
position/heading or carry an unchanged global goal through a coordinate reset
without an explicitly validated policy. This diagnostic counts observed
transitions; it cannot reconstruct unlogged transitions, prove reset coherence
or authorize automatic coordinate correction.

## Research and dependency selection

The [frozen method](superpowers/specs/2026-10-09-ekf2-sample-time-diagnostic.md)
links the fixed BSD-3-Clause PX4 message, publisher and selector source. The
selector preserves sample time while updating publication time, so conflating
them is unsafe in general even though they coincide here. Source snapshots,
URLs and hashes are retained. The initial raw GitHub message URLs outside
`msg/versioned` returned 404; corrected versioned paths succeeded, and no
unversioned message definition was substituted.

Official BSD-3-Clause pyulog 0.9.0 is imported directly from its hash-verified
pure-Python wheel; Windows site packages are unchanged. Existing NumPy 2.3.4 is
reused. This avoids a new ULog parser or starting WSL just to parse a log.
The dependency/source/maintenance/resource and alternative decisions are in the
frozen method. No new estimator algorithm or hardware-calibration claim is made.

## Verification and review

Initial 26 new tests failed because the API was absent, not because 26 existing
production defects were found. After implementation, 62 timing/shadow/capture
gate tests passed, with the deliberate duplicate ZIP member warning.
Changed-file Ruff and `git diff --check` passed.

Independent read-only review found no Critical/Important issue and one optional
Minor boundary-coverage improvement. Added exact 50 ms and the next representable
microsecond cases; sample timestamps are integer microseconds, so 50 ms + 1 ns
is not representable. These are GREEN coverage additions, not a production fix.
The reviewer independently checked saved arrays and reproduced the principal
timing/health counts. Clock calibration, host arrival latency, historical full
runtime identity, reset coherence, state accuracy, teacher provenance, held-out
generalization and flight qualification remain outside the proven scope.

Full regression on unchanged production commit `3eda64c` terminated with exit 0:
**3948 passed, 33 skipped, 3 warnings in 611.90 s**. The warnings are the deliberate
duplicate ZIP member, sparse-checkpoint invariant check and existing unmatched
neuron-group warning; skips are not validated. It had collected the original
27 new timing cases before the review's two boundary cases were added. The final
29-case timing file was therefore run separately after the full suite and passed
in 0.47 s, exit 0. Production code did not change between these verifications.
Final changed-file Ruff and diff checks passed; no full-repository lint claim is
made. Both pytest process handles terminated, and the subsequent Windows scan
found no matching Python/PX4/Gazebo/online_probe process. Observed free physical
memory was 1,322,636 KiB, still below the 4 GiB full-inference preflight; no model
retry was launched. This is a current resource observation, not permanent
machine infeasibility.

## Remaining work

- Verified here: offline timing separation, invalid-time refusal, original
  development input identities, all-frame diagnostic and health/reset findings.
- Implemented only: a reusable timing companion; no live source producer.
- Not verified: camera calibration/pose, common epoch, actual receipt freshness,
  primary-estimator association across topics, reset-coherent Observation,
  inspected EGO teacher and usable deployment-visible corpus.
- Still open: full-model resource/timing gate, complete learning/division,
  frozen fair comparison, five-camera 0.873 RTF < 0.95, hardware/HITL/real flight.

Next producer work must explicitly carry sample/publication/receipt times,
source health and estimator/session/reset identity; derive calibrated camera
pose from the correct body origin; and keep unknown qualification false. The
current archived unarmed study is not a replacement training corpus. Actual
VIO-to-EKF2/live activation remains outside this stage's authorization.

## Sealed evidence

`evidence/ekf2-sample-time-dev-1701.zip`: 39 members, 480,110 bytes, SHA256
`4a34ff156b71dd1b20433a62b7b34aa53bcd6bde1ec5dd28d99a543f62550230`.
All member bytes/hashes and CRC were checked. It retains the selected input
manifests, consumed non-truth topic arrays, all-frame reports, parser wheel and
research sources, RED/GREEN/full-suite output, final boundary tests, review and
next requirements. The original ULog is referenced by its sealed archive/hash
rather than duplicated. Source/document copies are post-verification at
`320a09c`; this seal paragraph was appended afterward. Work remains local under
the existing publication limitation; no remote push or merge was attempted.
