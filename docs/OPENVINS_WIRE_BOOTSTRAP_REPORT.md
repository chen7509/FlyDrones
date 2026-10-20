# Wire responder and owned startup composition

This stage verifies an offline/ordinary-process interface between the pinned MAVLink TIMESYNC byte responder and the owned read-only listener bootstrap. It does not launch PX4, transmit UDP, publish ODOMETRY, inject EKF2, arm, train, or establish live clock convergence. The broader FlyDrones objective remains incomplete.

## Changes and rationale

- Reject regressed supplied receive timestamps while allowing ties. Non-consuming checks retain the existing 8-second global and 2-second progress gates without reading/opening commands.
- `OwnedWireBootstrap` couples actual `OwnedBootstrap.reserve_reply` to the actual pinned codec. Either side's refusal masks composed completion; a sink return is retained even when later ownership/journal checks fail. It cannot create live/fusion authority.
- Final reply counts and completion commit after health checks and before operation unlock. A state lock serializes close/refusal against commit. Explicit terminal checking retains process identity and final-frame timeout checks after the inner bootstrap completes.
- The private fixture receives actual serialized reply bytes through the direct-owned stdin pipe and decodes/checks their fields and sequence before generating each modeled status. Requests, their peer metadata and simulated timestamps remain supplied synthetic inputs. This is not an actual UDP receive or PX4 TIMESYNC filter.

## Review and tests

Independent read-only review of `25f3c63..d22e706` found three Important findings, no Critical/Minor: unlocked final commits, skipped terminal identity/deadline checks, and a harness summary that could claim completion after last-case post-cleanup audit failure. Fix `f44be5b` addresses these. Two lock interleavings, terminal timeout, and close interleaving have assertion RED→GREEN evidence. The harness hash-drift false-complete case also has assertion RED→GREEN; journal/copy/copy-hash error coverage was added GREEN (not mislabeled as previously observed failures).

The first actual fixture study exposed a separate JSON tuple/array comparison error and insufficient raw-artifact retention. Two further assertion RED→GREEN cases cover those paths; fix `2239100` copies raw artifacts before audit and uses `/var/tmp` as secondary scratch. The final WSL suite has **67 passing tests** (46 pinned wire + 21 composition/harness). Changed-file Ruff and diff-check pass. Full Windows regression: **3195 passed, 5 skipped, 2 existing warnings in 344.74s**, exit0. Windows lacks pymavlink, so that platform skips both real-codec modules; the WSL runs cover them. Existing whole-suite training CLI fixtures run as regression tests, not a new drone training study. No relevant processes remained in the post-run check.

## Actual ordinary-process studies

`kernel-v1`, producer `f44be5be01bb522a918af344dc3bf0980840eab0`, failed after normal500 during log comparison. Parent summary records 500 sends/composed completion, 3.987450994 seconds and child exit0. Matrix completion is correctly false. Its raw child receipt/server/journal files were left under `/tmp`, then became unavailable before the next read. Subsequent `/tmp` inventory is consistent with WSL lifecycle cleanup, but the deletion cause was not recorded. These missing artifacts cannot be reconstructed; parent summary does not replace them. Three fault cases were not reached. Retained prospective, console, summary and post hashes remain unchanged.

`kernel-v2`, producer `2239100fad7f3a04ec005ac6dadc1aaebeef2936`, was separately declared in `kernel-v2-prospective.md` after diagnosis. It repeats normal500 specifically to collect complete raw evidence and runs the previously unreached fault cases. Same gates, synthetic sample schedule, protocol and expected outcomes; no tuning or automatic retry loop.

| Case | Coordinator elapsed seconds | Child decoded replies | Child exit | Result |
|---|---:|---:|---:|---|
| normal500 | 4.028957860 | 500 | 0 | Composed modeled completion |
| wrong-replay | 0.040422983 | 1 | 0 | Ordinal gap refused |
| sink-short | 0.052139877 | 2 | 2 | Third reply short write refused; child incomplete-frame EOF retained |
| journal-failure | 0.019873420 | 0 | 0 | Reservation journal failure refused before sink |

All four direct children were reaped without parent cleanup signals. Child exit2 is expected evidence in the short-write case, not a successful child execution. Actual disk journals match JSON-normalized in-memory events; copied file hashes match original artifacts. Fourteen selected source/dependency files are unchanged before/after. This is a declared subset, not complete runtime closure. Source provenance, prospective cases, actual command bytes, parent writes, child reads, owner identities, clocks, cleanup and all failures are retained.

Elapsed time is ordinary fixture coordinator wall time starting after child readiness. Fixed status RTT/offset values are synthetic. It is neither PX4 cold-start latency, live synchronization convergence nor complete fruit-fly inference latency.

## Verified / implemented / untested / failed

- **Verified:** pinned byte conversion combined with owned reservation/listener handling; synthetic normal500 and the three named private-process faults; final gates, reentry and review counterexamples; v2 selected-file stability and raw evidence copying.
- **Implemented:** reusable coordinator and explicit idle/terminal checks. No production transport or launch integration was added.
- **Untested:** actual PX4 receiving replies, UDP provenance, cold-session synchronization, real TIMESYNC status/filter convergence, ODOMETRY delivery, VIO→EKF2 and closed-loop flight.
- **Failed / retained:** kernel-v1 audit and missing raw child artifacts, all original development/review counterexamples, historical VIO failures and five-camera 0.873 RTF below 0.95. Do not relabel these as fruit-fly training failures.

## Next dependency and scope

The next design must bind a genuine received request's peer/time/session to the selected owned PX4 process and verify the real response/status path under the existing fixed limits. Current synthetic namespace values and fixture RTT are insufficient. Continue fixed upstream research and offline contract tests first; any actual SITL injection remains outside this stage's authority. No inference of live convergence from modeled 500 samples. The overall work still requires real VIO/EKF2 safety integration, complete fruit-fly learning/decision/division verification, fair upstream comparison, and staged swarm evidence.

## Evidence

Exclusive archive: `evidence/openvins-wire-bootstrap-dev-1701.zip`; external seal metadata supplies SHA256/member count/CRC. Raw v2 artifacts, retained v1 parent artifacts, both prospective declarations, original counterexamples, final test output, research and source snapshots are included. Source snapshots are the sealing worktree files; the kernel prospective/post manifests identify the actual 14 selected runtime inputs. Historical archives remain unchanged. Final publication checklist can be newer than the immutable pre-publication plan snapshot in the archive.
