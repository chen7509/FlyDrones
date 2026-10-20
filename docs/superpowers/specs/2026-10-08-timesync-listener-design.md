# TIMESYNC listener byte boundary and bootstrap design

## Purpose and authorization

Connect pinned listener output to the existing serial reply/status validator.
This is offline/synthetic preparation only. Do not start PX4, mutate stream rates,
publish ODOMETRY, inject EKF2 or run physical simulation. Routine plans are already
approved; execute inline with targeted tests, independent review and evidence.

## Source findings and approach

Selected installed PX4 d6f12ad source matches upstream byte-for-byte: uORB.cpp,
px4_log.cpp/log.h, daemon client.cpp/client.h/sock_protocol.h/server.cpp. BSD-3.
Prior listener_main/topic_listener/DeviceNode/Subscription/main sources and
generated timesync_status metadata remain the source for listener semantics.

Non-PTY daemon-client path routes PX4_INFO_RAW to the thread's line-buffered
socket FILE; explicit screen-clear dprintf(1) uses daemon stdout, not that FILE.
Client::_listen writes received bytes via fwrite(stdout), without per-read
fflush. The early client branch in main does not set stdout buffering. Test the
unchanged client in a standalone binary with a private temporary AF_UNIX fixture,
no PX4 instance/socket path, before selecting a stdout remedy. A stdbuf -o0
candidate adds installed coreutils9.4 GPL3+ and libstdbuf preload; record versions,
paths, hashes and libc2.39. Do not call this an actual PX4 runtime proof.

Reuse the installed CLI with a strict non-PTY byte parser if supported by that
probe. Alternative custom native uORB observer remains a higher-cost fallback;
PTY auto-translation/color parsing is rejected here because it changes the
source boundary. Do not strip arbitrary ANSI/control bytes into apparently valid
records. This changes no estimator, paper-derived algorithm or sensor model.

## Framing contract

`TimesyncListenerDecoder(instance, expected_records, start_ns)` consumes raw
bytes using feed(data, now_ns), check(now_ns), finish(now_ns, exit_code).
Instance0..255, record count1..4096. Non-PTY canonical LF output only:
leading blank; TOPIC timesync_status instance I #N; inner topic name; six scalar
fields in generated order (timestamp, remote_timestamp, observed_offset,
estimated_offset, round_trip_time, source_protocol); blank padding line.
Timestamp has the pinned six-decimal age annotation when nonzero. Its integer
sample is authoritative; the rendered age is neither an arrival timestamp nor
permission to relabel stale state. Permit only finite nonnegative decimal age;
keep it in raw evidence, do not feed age to the filter. Integer widths match the
message/observer; zero timestamp is invalid for this selected healthy boundary.
Retain ordinal as listener consumption ordinal, never uORB generation.

Decode only complete frames, at most4096-byte chunk and1024-byte incomplete
frame, bounded total4MiB. At2s since start or last complete frame, reject before
accepting new bytes; partial trickles do not refresh deadline. Caller must invoke
check on silent sources. Fail permanently on malformed/unknown/duplicate/missing
fields, wrong instance/ordinal, stdout diagnostics, ANSI/NUL/non-ASCII, clock
regression, excess counts, truncation, nonzero exit, or premature EOF. Record
already emitted before a later error is not retrospectively erased. This parser
has no durable writer, process launcher or independent watchdog thread.

Use existing SerialTimesyncObserver for numerical parity after decoding each
record in integration tests. Parser success alone cannot authorize anything.
All completion authority fields remain false. Persist raw chunks/timestamps in
the eventual harness; bytes returned here do not prove source identity.

## Bootstrap and remaining live boundary

Listener refuses a never-published topic and may return0 for a timeout/diagnostic.
On a separately authorized cold/exclusive PX4 instance, proposed bootstrap is:
reserve/journal first reply, send it once, withhold other replies, start selected
listener after that publication can exist, match the initial latest publication,
then continue one reply/status at a time. DeviceNode initializes subscription at
generation-1 when prior data exists; queue depth1 is not evidence of completeness.
Neither a new companion session nor a matching first offset proves the cold
filter/exclusive producer assumption. Topic instance/channel ownership and actual
stdout forwarding must be demonstrated before live qualification. Never resend
an old frame or reset the observation count to hide missed publications.

Unpublished/bootstrap-race refusal must stop the study, not blindly relaunch it.
100Hz remains candidate only; configured rate does not guarantee500 accepted
updates in8s. Preserve total25s/readiness8s and2s safety limits.

## Verification

Native client fixture compares default piped stdout with explicit unbuffered
stdout before the2s deadline, captures command/trailer/exit, and tests malformed
exit/truncated bytes without a flight process. Parser normal/chunk-split/integer
boundaries, malformed/truncated/diagnostic/control input,2s deadline and EOF tests;
integration into unchanged observer. Independent review and full regression,
changed Ruff/diff, report/seal/publication. No whole-goal completion claim.
