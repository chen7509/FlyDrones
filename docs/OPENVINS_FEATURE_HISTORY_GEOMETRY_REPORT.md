# OpenVINS feature-history and geometry diagnosis

## Scope and evidence boundary

This stage diagnoses the two dominant fixed-input mechanisms exposed by the
preceding feature-rejection trace. It does not rerun the physical simulator or
modify the immutable `study-v21/capture-v1` evidence. It uses OpenVINS commit
`69488123ed9362dd44b6f28e7f4680abbff1442b`, the same fixed estimator
configuration and sealed request stream, and a new isolated GPL diagnostic
build. No state, threshold, feature order, input, or branch decision is
changed.

The strict audit is
`results/openvins-feature-history-geometry-dev-1701/audit-v3.json`. It reports
`qualified=true`, `physical_replay=false`, `truth_used=false`, and
`fusion_eligible=false`. All 250 non-timing camera-state rows equal the
uninstrumented control within `1e-12`.

## Findings

The 1,202 MSCKF insufficient-history rejections are all **raw-short**. Every
one entered the updater with only one observation; zero candidates had two or
more raw observations and then fell below two because old clone measurements
were removed. Across all 1,235 MSCKF candidates, the raw and valid observation
count medians and 95th percentiles are both one, and the clone cleaner removed
zero observations. Candidate origins are 1,230 lost tracks and five marginal
tracks. This rules out the 11-clone window as the cause of the dominant MSCKF
insufficient-history count in this fixed replay. It points to features being
lost after a single camera frame; it does not yet distinguish image content,
motion blur, viewpoint, or tracker policy as the upstream cause.

Of the 33 MSCKF candidates with sufficient history, 27 passed linear
triangulation and six failed the unchanged condition-number threshold. The
failed six have median maximum pair baseline 0.00929 m and median maximum
parallax 0.00162 rad, versus 0.19093 m and 0.05978 rad for the 27 accepted
candidates. Four later failed nonlinear refinement and 23 completed the MSCKF
update, matching the prior aggregate trace exactly.

All 160 delayed-SLAM candidates came from max-length tracks and retained at
least six valid observations; none was raw-short or clone-pruned. Forty-six
passed linear triangulation. All 114 rejected candidates exceeded the fixed
condition-number limit; 12 of those also produced depth below the fixed
minimum. The rejected set has median condition number 68.1 million, median
maximum pair baseline 0.00165 m, and median maximum parallax 0.000400 rad. The
accepted set has median condition number 634, median maximum pair baseline
0.340 m, and median maximum parallax 0.118 rad. The fixed-input delayed-SLAM
failure is therefore directly associated with degenerate low-baseline,
low-parallax geometry, rather than insufficient history.

These observations explain the exact rejection mechanisms in this replay.
They do not establish that changing motion, tracker parameters, clone count,
or triangulation thresholds would improve the physical estimator, and no such
change was tested. They also do not close the full cause of the earlier
47.7-metre physical trajectory error.

## Validation and retained failures

The final negative protocols qualify: native motion intent before internal
initialization is rejected, and a duplicate intent is rejected after the first
acknowledged handoff. The complete fixed replay consumes 6,477 sealed source
records and the native adapter accepts 6,478 packets including the one motion
intent. The aggregate totals remain 1,202 MSCKF insufficient, six MSCKF
triangulation, four MSCKF refinement, 114 delayed-SLAM triangulation, 46
delayed-SLAM accepted, and two existing-SLAM chi-square rejections.

Focused parser/auditor tests pass. The complete repository suite passes with
1,780 tests, three existing skips, and two existing warnings in 211.24 s after
pinning `PYTHONPATH` to this worktree. The first full-suite attempt is retained:
it failed during collection because the process inherited a different
`curriculum-training` worktree on Python's import path. That was an environment
selection failure, not an algorithm or test assertion failure.

## Status matrix

| Item | Status | Evidence |
|---|---|---|
| Candidate origin and raw history | Verified on fixed replay | 1,395 selection/history pairs reconcile exactly |
| Clone-pruning hypothesis for MSCKF | Rejected for this replay | 1,202 raw-short, 0 clone-pruned |
| Delayed-SLAM linear geometry | Verified on fixed replay | 114 condition-number failures; 12 also minimum-depth failures |
| Diagnostic state neutrality | Verified | 250 camera states, tolerance `1e-12` |
| Physical VIO accuracy | Failed previously; not rerun | Earlier physical evidence remains authoritative |
| Online latency | Not tested | Offline replay clocks are not online latency |
| Quality/reset/covariance calibration | Not verified | Values remain unknown or uncalibrated |
| ODOMETRY / EKF2 / arming / flight | Not eligible | Explicit false gates in the audit |
| Fruit-fly policy learning or training | Not involved | No training process or weights changed |

The next safe experiment is a separately specified development-only
sensitivity study that increases real camera parallax through a bounded,
physically consistent motion profile while preserving the estimator and
thresholds, plus an image/tracker diagnosis for the single-frame lost tracks.
It must not tune against a frozen evaluation set or be presented as physical
VIO qualification.

The sealed evidence archive is
`evidence/openvins-feature-history-geometry-dev-1701.zip`. It contains 76
members, is 39,974,828 bytes, and has SHA-256
`6d2ba2cc104ffe6e9ead72437ca2fab44a4ded6707ae85ed671c50e405df3f31`.
ZIP CRC, unique member names, manifest count, and all 75 manifest-listed
member sizes and hashes verify. The archive contains this report as it stood
before this paragraph; the archive itself is unchanged by this statement.
