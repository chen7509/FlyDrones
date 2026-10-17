# Observed clock and owned wire session composition

The independent clock, supplied datagram receiver and existing owned wire bootstrap now share one composition path. This is an **offline implementation and validation result**. There was no actual UDP socket, PX4/Gazebo/OpenVINS instance, ODOMETRY publication, EKF2 injection, arming or training in this stage. The complete FlyDrones goal remains unfinished.

## Implemented behavior

`ObservedWireSession` uses one caller-owned socket for both recvmsg and sendto, the existing real pinned pymavlink codec, one `OwnedWireBootstrap`, and actual `JournaledSimulationClock` / `RemoteMonotonicClock` classes. It freezes session and clock origins, checks the expected process identity through the supplied backend, and invokes the supplied descriptor guard. It creates no socket or process and does not claim kernel ownership authentication.

Every reply selects a journaled simulation-clock observation independently of the request timestamp. A newer source observation cannot refresh an older selected sample. Selection and receive/core evidence are separate. No-data returns without inventing a clock sample. The original 8-second bootstrap limit, 2-second source/packet limits, 500 modeled exchanges, 4096-byte limit, loopback endpoints and 25-second/1-ms clock profile remain unchanged.

Socket profile access can itself take time. The final boundary now collects source state after those calls and any state-lock wait, then samples time and checks latest/pending source ages and selected sample/receipt ages before send or completion. It also rejects the shared remote clock's latched failure without consuming another sample. These are point-in-time observations, not atomic guarantees against an external process/source changing after the last check. Supplied callbacks still require outer bounded supervision.

The send return is immediately handed back to the existing wire code before any post-send validation. Short writes and failures after send preserve the actual returned count; refusal cannot undo an already attempted send. A failure closes existing owned listener connections but leaves the supplied socket's lifetime with its caller.

## Research and reuse

Reuse fixed PX4 d6f12ad (BSD3), Python 3.12.3 (PSF), Gazebo 8.15 (Apache2), and pymavlink 2.4.49. The latter's generator license is (L)GPLv3 with a generated-output MIT exception; the distribution metadata says LGPLv3. Retained upstream metadata and installed-code hashes are referenced in the stage research manifest, not presented as freshly measured maintenance or installed-source equivalence.

The [Python socket API](https://docs.python.org/3.12/library/socket.html#socket.socket.sendto) and [Linux send(2)](https://man7.org/linux/man-pages/man2/send.2.html) support per-call nonblocking flags and distinguish a return count from delivery. Existing fixed Python socket documentation and fixed PX4 clock/receiver research are reused. No numerical algorithm, learning method or new paper result changed. Composition avoids another codec, process supervisor or dependency. Costs are bounded selection/event logs and existing journal/guard calls; no online throughput or real-time latency claim is made.

Real WSL composition exposed that `socket.MSG_DONTWAIT` is a `socket.MsgFlag`, whereas earlier fake Windows tests supplied an int. The receiver now accepts the actual stdlib enum or an exact int and normalizes to int. This corrects a limitation in the previous receiver-stage validation; its sealed evidence is not rewritten.

## Verification and review

- Supporting APIs initially produced 9 failures / 85 passes; implementation reached 94 passes.
- Initial composition collection failed because the new module was absent. The next actual-class run failed all 16 cases on the enum flag check. A dedicated enum counterexample then failed (1 failure / 43 passes) and passed after correction. These are separate failures, not all behavioral assertion REDs.
- A later preexisting-source-fault counterexample showed an open listener was not closed: 1 failure / 20 tests, then 20 OK after moving the health refusal inside the cleanup path.
- Independent review by `/root/review_observed_wire_session` found two Important issues, no other confirmed Critical/Minor: source/packet freshness could expire during socket profile calls, and a shared remote-clock fault was ignored. Three deterministic assertions failed before repair and passed afterward: no send after profile-check expiry; no final completion after expiry; no send after a shared-clock failure. Final production fix is **a0345624a31a1257faadb80382d1e087a45fd006**.
- Current related Windows regression: **115 passed, 2 skipped** (the codec suites require the existing WSL installation). Current WSL real pinned-codec wire/bootstrap/composition regression: **90 tests, OK**, including **23 composition tests**. Changed-file Ruff and diff-check pass. The extra public health-accessor test is added GREEN coverage, not another claimed RED repair.
- The entire repository was not rerun for this local composition change. Prior whole-repository successes and its retained intermittent timeout remain historical, not a fresh full-suite claim. No deferred review minors.

Five separately exported synthetic cases preserve full selection/core/receiver evidence, forwarded journals and fake send bytes: normal 500; profile expiry (zero sends); shared clock fault (zero sends); short write (one attempted send); failure during send (one attempted send with returned count retained). Case names and selected source/codec hashes were written before those cases ran; hashes match afterward. This uses real classes and a real codec, but all owner/listener/status/clock/socket observations are synthetic. The export is not a replay of PX4 packets and establishes no actual RTT, filter convergence or transport delivery.

## Status and remaining dependency

- **Verified offline:** one-socket composition; independently selected clock; exact sample membership; final source/packet ages; remote failure/session refusal; same supplied owner/descriptor checks; no-data handling; nonblocking send flags; partial send accounting; reentry/close refusal; final 500-exchange modeled completion; owned listener cleanup on prior source failure.
- **Implemented, not exercised live:** this composition and the PostUpdate lane remain unregistered in a live capture lifecycle. The injected descriptor guard is an interface, not proof of actual socket/process identity.
- **Untested / unqualified:** actual lifecycle binding, timing against PX4's separate clock subscription, actual UDP exchange/convergence, VIO-to-EKF2 integration and flight. All network/delivery/runtime-source/live-convergence/fusion qualification flags stay false.
- **Failures retained:** all collection, enum, cleanup and review counterexamples, plus historical simulation failures. Five-camera 0.873 RTF still fails 0.95; hardware calibration, HITL, real flight, full fruit-fly task validation and fair baseline comparison are not completed here.

Next work should bind the existing composition to a narrowly defined capture lifecycle, with real descriptor/session ownership evidence, callback registration and exit behavior. First inspect the current capture/socket owners and design/test the adapter offline. Do not add another generic process-governance subsystem. A later actual network/physical study requires its own frozen conditions and authority; this stage grants none.

Evidence: `evidence/openvins-observed-wire-session-dev-1701.zip`, with an external SHA-256/member manifest. The preapproved draft PR65 is updated without merging, deleting evidence or changing prior archives.
