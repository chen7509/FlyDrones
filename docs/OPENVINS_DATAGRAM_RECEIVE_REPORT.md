# Datagram receive boundary

This stage implements the missing receive-envelope boundary for the existing TIMESYNC wire/bootstrap adapter. It reads one supplied socket using recvmsg and retains returned bytes, flags, source endpoint and userspace monotonic observation. **The new adapter's tests use only synthetic injected sockets.** No actual PX4/Gazebo/OpenVINS process, network ODOMETRY, parameter change, arming or new training study was used. The separately requested full repository regression includes existing localhost UDP tests (`test_peer_udp.py`/`test_task_udp.py`) and small training CLI fixtures. Thus “no actual UDP” describes the new adapter study, not every test in the full suite; the legacy tests do not validate this new adapter's kernel behavior.

## Implemented behavior

`DatagramReceiver` never creates, closes, binds, connects or sends a socket. The caller owns lifecycle and supplies an independent session/descriptor guard. Each poll verifies the declared IPv4 datagram/nonblocking/local127.0.0.1:14548 profile and accepts only source127.0.0.1:14588,1..4096byte payload, no ancillary controls and zero message flags. Empty data is a refused packet; BlockingIOError is no packet. There is no retry, synthetic packet or implicit EOF success.

The immutable envelope contains data/peer/received_ns. Return bytes are saved before external clock/guard/journal callbacks; failures retain those partial effects and latch future refusal. Event storage is bounded8192ordinary entries plus a separate refusal slot. Nonblocking operation locking prevents a callback from performing a second read. Existing8s global/2s observed syscall limits are not extended.

Single-call MSG_DONTWAIT is required even when Python gettimeout reports0. Descriptor aliases can share kernel mode without updating another Python object's timeout cache. The flag prevents relying solely on that cache. Unsupported platforms refuse before reading. External guard/journal callbacks still need bounded execution/supervision; the adapter cannot preempt an arbitrary stuck callback.

## Sources, choices and review

Fixed PX4d6f12ad BSD3 UDP source was reused from the sealed prior channel research. It binds a configured port and learns the initial address; that inspected path is not per-packet sender PID authentication. Python3.12.3 fixed socket API/license source and current upstream metadata were retained. GitHub observed nonarchived CPython, pushed2026-10-08T01:26:20Z; this does not imply the installed3.12.3 is the latest package. Linux UDP and UNIX-socket manual pages clarify truncation and the difference from AF_UNIX peer credentials. References and hashes are in the stage research manifest.

Adopt stdlib recvmsg because it exposes flags; reject recvfrom for this boundary and avoid replacing the existing pinned pymavlink codec with a connection factory. No VIO/learning algorithm changed; existing numerical/paper basis remains. Cost is one bounded datagram read, bounded event storage and synchronous callbacks, no background thread or new dependency.

Independent review found1Important, no confirmed Critical/Minor: the timeout-cache/kernel-mode distinction above. Two synthetic counterexamples failed before f90f0c5 and pass afterward. Earlier self-check found four assertion failures in event-capacity/reentry and floating metadata handling, repaired before review. Initial module-missing collection error is reported separately. Review did not claim a real kernel/socket reproduction.

## Validation

Final targeted offline suite: **41passed in0.10s**. Windows explicitly injects Linux MSG_DONTWAIT64 into fake sockets; this is not Windows UDP support or a Linux kernel test. Read-only WSL capability observation confirms installed Python3.12.3, recvmsg availability, MSG_DONTWAIT64/MSG_TRUNC32/MSG_CTRUNC8 without constructing a socket. Changed-file Ruff and diff-check pass.

First full regression: **1failed,3235passed,5skipped,2existing warnings in226.98s**. An unchanged resource-graph test's one-byte Python child reached its original5s timeout. The exact failed test passed once in isolation in1.57s without source/threshold changes. A separately retained full confirmation then passed: **3236passed,5skipped,2existing warnings in213.16s**, exit0. The initial delay's cause is unresolved, not a proven code fix; both full logs and isolated diagnostic remain. No relevant Python test processes remained after completion.

## Verified / implemented / untested / failed

- **Verified offline:** receive method/argument contract, payload/source/flag/schema refusals, empty/EAGAIN distinction, callback failure and reentry, evidence retention at capacity, strict clocks, per-call nonblocking flag and unsupported-platform refusal.
- **Implemented only:** adapter for a caller-supplied real socket and guard. No integration with a live endpoint was executed.
- **Untested:** actual kernel datagram behavior, socket/namespace/process provenance, independently observed simulation time, physical message delivery and actual PX4 filter convergence. These remain false; endpoint agreement is not PID authentication.
- **Failed and retained:** initial collection error, four self-check and two review counterexamples, first full-suite subprocess timeout with unresolved cause. Prior wire/bootstrap v1 raw-artifact gap and all physical/algorithm failures remain unchanged. Five-camera0.873RTF still fails0.95.

Do not automatically forward a packet into the wire responder using request ts1 as observed simulation time. The next integration requires a separately recorded, fresh simulation-clock observation and actual descriptor/namespace/session evidence; this module supplies neither. The userspace receive timestamp is not kernel arrival or end-to-end latency. This small boundary does not complete the full fruit-fly policy, training/division, fair comparison or swarm objective.

## Evidence

Stage directory: results/openvins-datagram-receive-dev-1701. Exclusive evidence archive and external seal metadata retain sources, counterexamples, final tests and code/spec/plan snapshots. Old archives are not edited. No physical study, new process fixture or actual receive-adapter UDP retry is needed. This same distinction between feature-specific validation and pre-existing full-suite socket fixtures clarifies earlier wire/bootstrap reports; it does not turn their modeled fields into real PX4 evidence.
