# Pinned TIMESYNC byte contract and sink accounting

The new adapter decodes real installed pymavlink requests, derives a reply from
the existing independent remote clock, reserves it through the existing serial
callback contract, and records the injected sink's result. It opens no socket
and does not transmit to PX4. Sink acceptance, delivery and actual PX4 filter
convergence remain separate; every live/fusion authorization flag stays false.

Spec/plan: `superpowers/specs/2026-10-08-timesync-wire-design.md` and
`superpowers/plans/2026-10-08-timesync-wire.md`. Design789b78e, initial
implementation3c77a74, reviewed-fault fixesdacad9e. This follows the owned
bootstrap composition; it does not replace its observed-status association.

## Source-backed choice

Reused installed pymavlink2.4.49 commonv20 SHA
a7c6b23d908322134d19cb94b937c1ea6b1f5d5ffa9d1b0ad139174bf8d75809.
Tagv2.4.49 resolves to2a500b8acfb507255d02ed8257b6eb132e5b86d7.
The retained [COPYING](https://github.com/ArduPilot/pymavlink/blob/2a500b8acfb507255d02ed8257b6eb132e5b86d7/COPYING)
distinguishes the(L)GPLv3 generator and MIT exception for generated output;
distribution metadata saysLGPLv3 and GitHub's detected license saysOther.
Fresh repository metadata is nonarchived and last-pushed2026-10-06; no claim
that the installed generated module equals every file at the tag.

Current [TIMESYNC documentation](https://mavlink.io/en/services/timesync.html)
describes target-address extensions absent in this installed constructor.
This is TIMESYNC servicev1 in MAVLink1/2 framing. Fixed PX4d6f12ad(BSD3)
handler/filter findings are reused, not revalidated by a running PX4 instance.
Full source/interface/resource/adoption notes are retained in research.md.
No package was installed and no VIO algorithm was changed.

The earlier14-case installed-codec experiment established variable-length
trimmed frames, partial parser buffering, CRC behavior, sequence behavior and
missing target fields. With no signingkey the codec accepts signed/tampered
frames without marking the signature verified. The new unsigned study profile
therefore refuses flagged frames. Endpoint/header equality is not authentication.
The experiment is retained unchanged; it is not final responder execution.

## Implemented boundaries

`PinnedCodec` binds the installed version/source/schema and checks CRC bypass.
It uses upstream decode/pack with a4096-byte/64-frame complete-datagram profile.
Truncated, unknown, flagged, badCRC and extended-TIMESYNC-schema inputs refuse.
Multiple known telemetry frames are retained; at most one request is allowed,
and the entire datagram is validated before any reservation or sink call.

`TimesyncWireResponder` checks the declared peer and sysid9/component1, tracks
strict request/response identities and uses sender254/component191 with its
own wrapping sequence. It never invents target fields or timestamps from ts1.
The supplied reserve callback must return the exact existing false-authority
intent; the actual SerialTimesyncObserver is used in tests to enforce one
pending reply and matching modeled status. Actual OwnedBootstrap/UDP combined
execution has not been performed by this stage.

Request8s-global/2s-local budgets and session checks occur around callbacks.
They are synchronous deadline checks, not preemptive cancellation. Raw bytes,
peer, supplied receive time, reservation, encoded reply, send attempt, returned
count and post-sink clock are separated. A returned clock failure retains the
count; a send or post-send journal failure cannot undo effects. A separate
refusal slot and pre-send return capacity preserve bounded evidence. Malformed
exception formatting cannot prevent the failure latch. Callbacks receive copies.

The profile does not claim observed real-PX4 datagram compatibility. Real UDP
ownership, clocks and packet arrival still require a future bounded transport.
The adapter has no permission to publish ODOMETRY, inject EKF2 or change streams.

## Verification and independent review

Initial36-case RED was missing-module import errors, not behavioral assertions.
First implementation exposed four exception-type errors. A normalization edit
then hid the word latched on repeated refusals;28 tests caught it. Both outputs
remain. After correction36 tests passed. Two additional send-clock assertions
failed, then passed with explicit returned timestamps, bringing the suite to38.

Independent read-only review found3Important issues: lost send-return evidence
at capacity/reentry, masked primary clock interruption, and exception-string
failure bypassing latch. Four new counterexamples produced3 assertion failures
and1 wrong-exception error; all passed after the fixes. Final suite has42 cases.
The hostile-error test was tightened to require the exact refusal class/reason
after Ruff rejected its broad Exception assertion. No automatic re-review was
substituted for these tests. Review and all earlier outputs are retained.

Windows targeted adjacent tests passed141 with1 explicit missing-pymavlink skip.
The actual codec runs under existing WSL Python3.12.3 using stdlibunittest,
because WSL lackspytest and Windows lackspymavlink. A Windows skip is not proof
of codec behavior. Final selected-hash WSL run at producerdacad9e passed42 in
0.265s, exit0, with all8 selected source/runtime file hashes unchanged. The
single full Windows regression passed3193 with4 skips and2 existing warnings
in296.89s, exit0. The additional skip is this real-codec module, not a passed
codec test. Changed-file Ruff and Git whitespace checks passed; no claim of
whole-repository lint success. All test processes exited; no new simulator or
estimator was launched. Existing CLI smoke fixtures in the full suite are not
a new training study.

## Status and remaining limits

- Verified offline: real codec behavior; valid/failed reply attempts against
  injected sinks; actual serial observer pending and synthetic status association.
- Implemented, not live tested: packet adapter compatible with reservation API.
- Unverified: actual UDP send/receive, original-owned-PX4 cold epoch, exclusive
  responder, actual500 accepted samples within8s, interval ACK/query/rollback.
- Deferred Minor: received_ns is fresh and not future but not monotonic across
  datagrams. The host clock and request identities are monotonic; this gap does
  not increase the2s window. Resolve before claiming receive-clock qualification.
- Earlier VIO simulation qualification stays limited to its domain; no new
  estimator, covariance, full fruit-fly, multi-aircraft or physical result here.
- Five-camera0.873RTF remains below0.95. No workload reduction, Linux install,
  hardware calibration, HITL or real-flight claim.

Next work is concrete bounded receive/send ownership plus correlated interval
ACK/query transport, with offline refusal testing first. The overall FlyDrones
goal remains open; this report is one dependency, not final drone readiness.

Sealed archive: `evidence/openvins-timesync-wire-dev-1701.zip`,54members,
94248bytes, SHA256
`52dc2f8e459f08d208f5d605c6d3de4b38514562160ab82cef0a9417651c3944`.
Every member hash and CRC verified; preceding owned-bootstrap archive unchanged.
Archive includes the pre-publication report and post-test selected source copies;
the eight files checked by the WSL wrapper stayed stable. It is not a complete
OS/runtime closure snapshot or an actual flight capture.
