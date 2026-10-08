# Capture startup-preflight boundary

## Purpose and bounded design

Continue the VIO-to-PX4 dependency chain by making the existing startup preflight
usable before any network or estimator activation. This is a bounded correction
to the existing worker entry, not a new runtime subsystem or permission to run a
physical study. The user's standing approval covers this implementation and its
offline tests. The existing wire-lifecycle publication remains a separate open
item; its historical archive is not modified.

The existing `main()` created and bound a local UDP socket before its preflight
return, and initialized `result.estimator_run` from configuration presence. Those
two behaviors made a files-only preflight touch a network endpoint and report an
estimator run that never happened. The correction skips only the port check in
startup-preflight mode and makes its result's estimator flag false. Ordinary
capture retains its original port check. That check is point-in-time only; the
socket is closed and does not reserve the port until the real receiver starts.

## Research and reuse

Reused CPython's installed standard-library socket and mock interfaces; no
dependency installation or replacement framework. The official Python 3.12
[socket API](https://docs.python.org/3.12/library/socket.html) describes socket
creation, bind and OS error behavior; the [mock API](https://docs.python.org/3.12/library/unittest.mock.html)
supports patching at the lookup boundary. The maintained documentation currently
identifies 3.12.15, which is not a claim that the installed interpreter was upgraded.
CPython upstream is [python/cpython](https://github.com/python/cpython), PSF license;
this stage makes no new assertion about upstream release cadence or equivalence
of installed patches. Existing fixed Python 3.12.3 research remains in the prior
supervisor evidence. No algorithm or estimator was replaced, so no new algorithm
paper is used to justify this entry-point correction.

Alternatives rejected: bypassing `main()` would miss the offending branch;
running an actual PX4/Gazebo capture would introduce unnecessary runtime effects
before the offline prerequisite was verified. Test cost is temporary small files,
file snapshots and Python calls. Production cost is a conditional branch only.

## Verification

`results/capture-preflight-boundary-dev-1701/red-v2.txt` records three expected
failures: legacy and wire preflight both attempted socket creation, and the
estimator flag was incorrectly true. Two existing behaviors already passed:
wire declaration drift refused before output, and ordinary capture still checked
its port. The earlier `red-v1.txt` also contains a fixture-only PATH mismatch;
that is preserved and is not counted as a production defect.

After correction the five focused cases passed. Four further GREEN coverage cases
exercise calibration drift, generated-copy mismatch, native-resource query
failure and parent-to-worker argument forwarding. The affected regression run
passed **140 tests**, including capture declaration, resource binding/graph,
startup auditing and the production capture runner. Changed-file Ruff and
`git diff --check` passed. This is not a new whole-repository regression claim.

Independent read-only review of `11cb88a..ebe7c03` found no Critical/Important
issues and two Minor coverage weaknesses. Both were addressed: the ordinary
capture fixture now fails from `bind()` after checking the intended address/port,
and preparation failures must match their expected reason and show zero forbidden
factory/import calls (a swallowed guard assertion cannot satisfy them). These are
additional GREEN assertions, not production RED/GREEN repairs. Final affected
regression `regression-v2.txt` again passed **140 tests**; changed Ruff passed.
The reviewer did not rerun tests or re-review the strengthened assertions.

The new tests call the real parent/worker `main()`, parser, declaration validation,
file extraction, generated-file copying, frozen configuration validation,
`RuntimeBinding`, graph scanner, snapshots and `CaptureJournal`. Test pins map
tiny fixture binary/archive bytes to the two installed pin constants only in the
capture module; all other file hashes are real. Process environment and self maps
are injected, and the resource SDK supplies only a fixed context for an empty SDF.
The parent supervisor is an in-process test adapter. Network/process creation,
runtime native imports and `run_capture_runtime` are guarded against escape.

Therefore these tests establish entry orchestration and refusal behavior, **not**
installed resource resolution, real process environment, real supervisor cleanup,
actual port ownership or a complete installed CLI startup-preflight run. The old
physical scenes and their failures have not been rerun or changed.

## Status and next dependency

- Verified offline: socket-free startup-preflight branch, accurate preflight
  estimator flag, strict wire declaration and normal/failure entry paths.
- Still pending: publication of this correction and its sealed evidence; the
  previous 25 MB archive also remains pending upload.
- Not run: actual installed startup-preflight with the new wire declaration,
  live wire synchronization, new physical VIO, ODOMETRY, EKF2 injection, arming,
  learning or multi-aircraft expansion.
- Next dependency: prepare a prospective installed startup package with the
  current wire/config/runtime hashes, then verify its files-only startup boundary.
  Passing this test suite alone cannot authorize a live study.

All previous simulation/hardware limits remain: fusion false, raw noise uncalibrated,
five-camera 0.873 RTF below 0.95, no HITL/flight qualification, and no completed
fair full-fruit-fly versus upstream baseline comparison.

## Sealed evidence

`evidence/capture-preflight-boundary-dev-1701.zip`: 23 members, 75,418 bytes,
SHA256 `d6e112fe1214a852af23752583235a8b8aeae3a77d523a12279100341b8d455f`.
Every member and ZIP CRC verified. Producer: `47b3fd1af2e1c3f741adf759615a2a120c6e0f6f`.
Source copies were recorded after `regression-v2`, not claimed as a runtime
pre/post freeze. The included report precedes this seal paragraph. Prior stage
archives, failed physical studies and pending-upload records remain unchanged.

## Publication limitation

The Git remote still reports `e4312ed`; this correction and both local archive
commits have not reached PR65. The previous Git push ended with HTTP 408. A
GitHub Git-database API trial recreated the existing `e4312ed` object with the
identical hash, establishing an exact-object alternative without rewriting
history. Two small blobs uploaded, but the 25 MB archive blob request exceeded
its 300-second bound. A subsequent HEAD request for that exact blob returned
404 and the branch still pointed to `e4312ed`. No reference was moved. Requests,
responses and the timeout are retained under the results directory; no TLS check
was disabled. This is a publication blocker, not a VIO or learning failure.
