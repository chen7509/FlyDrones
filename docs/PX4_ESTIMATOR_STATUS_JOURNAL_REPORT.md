# Read-only PX4 EstimatorStatus journal: offline result

## Scope and result

This stage adds a separate, read-only ROS 2 `EstimatorStatus` collector and a
strict Python journal auditor. It does not change PX4 firmware, publish
`ODOMETRY`, inject EKF2 measurements, unlock a vehicle or authorize training.
The fixed PX4 `d6f12ad` DDS topic list still omits
`/fmu/out/estimator_status`; a matching ROS message type and synthetic
publisher cannot establish a live PX4 source.

The collector compiled in one bounded offline Docker run. Its installed
`EstimatorStatus.msg` SHA-256 was
`44cba4424c224753b8249729e9bf7e530d0b34e04d5299fcf94f2677c8f50bd5`,
and the collector binary SHA-256 was
`12731be948f3293943fc9baa814eb3f4c64a8b6c502f7c0a5a3f8d477a15c0a6`.
The source verifier rehashed all 263 files and returned profile
`9b09019edaba29bee1364e67f3d2f7d31820936a1a12e6b7bc470b19c5cc3572`
before and after the build. Docker exited 0 after 2,382.344 seconds; the
daemon identity was stable and the owned container was absent. The offline
build used one CPU, 768 MiB/no swap, no network and a 900,000 KiB host-free
minimum. This is separate from the unchanged 4 GiB PX4/Gazebo physical-trial
gate.

One synthetic ROS 2 trial ran the exact built binary in a 512 MiB/no-network
container. The normal callback received three typed samples; an independent
CDR decoder matched all three, including float32 precision and the unavailable
`vel_test_ratio` represented as `null` plus `available=false`. The journal
preserved PX4 publication and sample times separately from RMW and callback
times. In this RMW run the source timestamp was observed, while the received
timestamp was unavailable and recorded as `null`, never as zero. The normal
journal SHA-256 is
`c51acb744e31e3d4f210f2b3f48253e9b47e52019421327415da22913c1e2ad1`.

Three independent I/O faults were retained. `fsync` and `close` EIO each
caused subscriber exit 2. Their journals contained a `complete` terminal
claim, but the auditor rejected completion because the observed owned writer
exit was nonzero. A partial-write EIO caused exit 1; its malformed JSONL was
rejected. Each fault has its injection marker, publisher exit 0, raw journal
and subscriber log. The Docker runner exited 0, no owned container remained,
and `training_eligible` stayed false in every case. The post-run qualification
predicate now requires these exact fault exits and terminal/error evidence;
the preserved v2 result still qualifies under that stricter predicate. The
runner was hardened after the physical execution through unit tests and a
read-only re-audit; the collector and Docker experiment were **not** rerun.
The evidence sealer independently re-audits all four raw journals, observed
process exits and fault-injection markers before publication, and checks fixed
journal and CDR-parity hashes. Its output-path check rejects linked parent
directories. Review found no remaining Critical or Important issue; ancillary
publisher and container logs have archive member hashes but were not separately
pre-pinned to fixed bytes.

## Preserved failures and verification

The first direct-script invocation failed before `main()` because the repo
root was missing from its import path. That failure is preserved separately.
The next declared v1 attempt stopped at preflight because an unrelated pytest
process occupied the host; it did not start Docker. Only the documented
prelaunch refusal permitted a distinct v2 result directory. No result was
overwritten. A later full-regression run found two existing inference-probe
child failures caused by the same script-path import assumption. Those tests
were reproduced and fixed by adding the fixed repo root to that child script's
import path. The original failed full-suite log is retained.

The targeted status checks initially recorded 141 passed and two Windows
symlink-permission skips. Four focused failing assertions exposed the two
review issues plus the inference-probe import failure; after the fixes, the
status runner and inference-probe suite recorded 32 passed. Changed-file Ruff
and `git diff --check` passed. The final whole-repository rerun passed with
4,763 passed, 44 skipped and four warnings in 983.60 seconds. Its raw output
is retained in the sealed evidence. The final targeted status, transport,
inference-probe and sealer checks passed 45 cases; the last sealer-only run
passed three cases.

An independent code review found no Critical or Important issue with the
offline result. It identified two Minor future-runner weaknesses: opaque
sensitive Windows process metadata could pass preflight, and any nonzero
fault exit could be mistaken for the intended injected fault. Both received
failing tests, fixes and passing focused tests. Existing v2 raw evidence was
read again without modification and passed the hardened rules.

A second whole-repository run reached 4,759 passed/44 skipped but had one
10-second subprocess timeout in the already existing source-only PX4 status
transport test. That test's complete 10-case file passed in an isolated
40.53-second rerun without any code or threshold change. Both raw test logs
are retained; the isolated result does not erase the whole-suite failure.

## Evidence boundaries and next gate

The one-shot local archive
[`evidence/px4-estimator-status-journal-dev-1701.zip`](../evidence/px4-estimator-status-journal-dev-1701.zip)
contains the selected build profile, compiler log, source seals, binary and
generated type hashes, normal/fault journals, launch and cleanup records,
historical prelaunch refusals, tests, report and a per-member SHA-256/size
manifest. Its ZIP SHA-256 is recorded separately after publication; member
CRC and extracted bytes are independently checked. Historical source and
test files outside this archive remain at their original paths and are not
rewritten or discarded.

**Verified:** matching offline type and collector build, three synthetic ROS
callbacks with independent CDR parity, fail-closed journal handling of three
specific I/O faults, source/result identity and bounded owned-container
cleanup. **Implemented only:** the read-only collector, auditor, run and seal
scripts. **Untested:** live PX4 publication, owned PX4/Agent/GID/ULog identity,
real EKF2 fault visibility, VIO→EKF2 status correlation and physical
closed-loop safety. **Historical failures retained:** the first-TIMESYNC
two-second miss and five-camera 0.873 RTF below the 0.95 gate. Neither is
evidence of a fruit-fly learning failure.

The next dependent work is a separately frozen firmware candidate that adds
exactly the status DDS topic, followed by unarmed live receipt when the
unchanged 4 GiB host-memory and no-contention gates pass. Publication/sample
clocks, Agent and PX4 process identity, GID, ULog and message loss must be
cross-checked before the journal can inform student capture eligibility.
There is still no authorization from this stage to publish `ODOMETRY`, inject
EKF2, arm, train or extend to five or twenty vehicles.
