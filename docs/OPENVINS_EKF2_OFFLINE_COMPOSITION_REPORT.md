# OpenVINS to PX4 Offline Composition Report

Date: 2026-10-08

Branch: `codex/estimator-aware-physical-diagnosis`

Review: draft PR 65

## Decision

The qualified OpenVINS health result, estimator session, remote clock session,
publisher session, reset counter, 15x15 covariance transform, and pinned PX4
ODOMETRY fields now compose through one fail-closed offline state machine. Only
authoritative health quality `1` can produce a candidate. A candidate remains
explicitly `fusion_eligible=false`; the implementation contains no sender,
socket endpoint, PX4 parameter access, or simulator control.

## Authority and failure behavior

`OfflineEkf2Composer` owns one `OpenVinsHealthContract`. Its `compose` method has
no quality, reset, reset-counter, covariance-profile, or fusion argument. The
native camera record must have the exact schema, and any extra caller field that
tries to supply one of those values is rejected and latched. Explicit estimator,
clock, and publisher identities must match their frozen sessions.

The state machine records either one candidate or one structured refusal. It
rejects unknown/unqualified quality, public-state absence, stale visual updates,
source or native failure, invalid covariance/state, excess delay, duplicate or
reordered sample time, old estimator sessions, clock/publisher mismatch, and
journal write/close errors. Estimator replacement is the only reset transition:
it creates a new health session, increments the absolute reset total once, and
derives the byte counter by modulo 256. A publisher identity change does not
invent an estimator reset.

The fixed fault matrix retains 15 cases: normal, unqualified covariance profile,
public unavailable, stale visual update, source loss, native loss, invalid
covariance, excessive delay, clock mismatch, publisher mismatch, duplicate,
reorder, estimator replacement/old-session rejection, journal write failure,
and journal close failure. Every record remains fusion-ineligible.

## Packet representation

The candidate uses `MAV_FRAME_LOCAL_FRD` (20), `MAV_FRAME_BODY_FRD` (12), and
`MAV_ESTIMATOR_TYPE_VIO` (3). It preserves the full transformed 9x9 covariance
in evidence. The pose upper triangle contains the complete position/body-tangent
orientation 6x6 marginal. The velocity upper triangle contains the complete
3x3 linear-velocity marginal at indices 0, 1, 2, 6, 7, and 11.

The OpenVINS 15-state output has no independently qualified angular velocity or
angular-rate covariance. These values therefore remain `None` in JSON evidence
and encode as MAVLink NaN. They are not synthesized as zero. The pinned PX4
receiver reads the position, orientation, and linear-velocity variance diagonals
used by the contract and ignores non-finite angular velocity.

`encode_candidate` and `decode_candidate` operate only on bytes in memory and
require pymavlink `2.4.49`. A standalone WSL check monkeypatched socket creation
to fail, completed three nonidentity/identity MAVLink2 ODOMETRY round trips, and
rejected 14 field/covariance corruptions. It verified every scalar field,
quaternion, covariance upper-triangle position, reset, frame, estimator type,
quality, and all NaN unknowns.

## Verification and limits

The focused Windows contract suite passes 24 integration tests, including every failure
class above, journal retention, reset wrap, old-session rejection, and a socket
tripwire. Combined integration, transform, historical odometry, and health
verification passes 100 tests. Pymavlink completed 3 round trips, rejected 14
field/covariance mutations, and rejected multiple or trailing packet bytes.
Changed-file Ruff and `git diff --check` pass. With this worktree's `src` pinned
on `PYTHONPATH`, the repository-wide suite reports 1,922 passed, 3 skipped, and
the same 2 existing warnings in 316.26 seconds.

The sealed archive is `evidence/openvins-ekf2-composition-dev-1701.zip`,
41,541 bytes with 21 members and SHA-256
`35e7c08b42d801171b84fc4d243130da448a1b5514c6991f300a09de1b91a272`.
CRC and every recorded member hash verify. This identity statement postdates
the report member inside the archive; the archive was not rewritten afterward.

This stage did not publish ODOMETRY, open a network endpoint, start PX4, Gazebo,
or OpenVINS, change a PX4 parameter, arm a vehicle, inject EKF2, train a policy,
or run multiple aircraft. The in-memory bytes prove the packet contract only;
they do not prove receiver timing, TIMESYNC, uORB publication, EKF2 innovations,
or fusion.

The next gate is the no-network real-source shadow. It must feed actual
journaled sensor/native acknowledgements through this exact state machine once,
retain real arrival/dispatch/processing times, and separately qualify any unique
30-50 Hz propagated covariance producer. The 10 Hz camera cohort cannot grant
that later rate qualification.
