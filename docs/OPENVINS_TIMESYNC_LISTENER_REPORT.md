# TIMESYNC listener byte boundary and buffering evidence

Date: 2026-10-08

## Decision

Implemented a strict incremental decoder for the pinned non-PTY listener output
and connected its decoded records to the existing serial TIMESYNC observer in
offline tests. A separately compiled, unchanged PX4 command-client source exposed
a real stdout-buffering obstacle in a private synthetic fixture: default pipe
output withheld the first status for more than two seconds. Installed `stdbuf -o0`
forwarded it promptly in that fixture. This is a candidate launch dependency, not
proof that an actual PX4 listener now meets the startup gate.

No PX4, Gazebo, estimator, network ODOMETRY, parameter/stream change or flight was
started. All live-listener/network/fusion authority remains false.

## Source and reuse

Seven selected installed files match fixed PX4
`d6f12ad1c4f70ad3230afd7d86e971421e02fef4` byte-for-byte: generic uORB printing,
raw logging/header, daemon client/header/socket declarations and server. They are
BSD-3-Clause. Copies, URLs and comparisons are retained. Earlier selected
listener/DeviceNode/Subscription/main sources are reused without repeating the
old source inventory; this is not whole-checkout/build equivalence.

The [generic printer](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/platforms/common/uORB/uORB.cpp)
prints ordered integer fields, a timestamp age annotation and a blank line for
padding. The annotation is display text, not a receive clock. The existing
generated structure fixes six fields and their widths; the installed generated
field-format header also explicitly includes the three-byte padding field.
Explicit-instance
listener headers include instance and consumption ordinal, not uORB generation.

The [daemon client](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/platforms/posix/src/px4/common/px4_daemon/client.cpp)
writes socket input to stdout through stdio without flushing each read. The
server's thread-specific FILE is line buffered; client stdout is a separate
buffer. In the selected non-PTY path, screen-clearing dprintf goes to daemon
stdout, whereas raw topic text uses thread-specific output. The decoder therefore
does not indiscriminately strip ANSI sequences or merge daemon stdout into status.

Installed coreutils is9.4-3ubuntu6.3, libc6 is2.39-0ubuntu8.9. Package copyright
and [stdbuf v9.4 source](https://github.com/coreutils/coreutils/blob/v9.4/src/stdbuf.c)
confirm GPL-3-or-later. `-o0` uses a preload library to disable stdout buffering;
programs that reset buffering can override it. Fixed source, installed executable
and libstdbuf hashes are retained; installation-patch equivalence and actual
runtime mapping closure are not proven. The GNU manual fetch timed out; fixed
official-project source was used instead. Repository maintenance metadata is
recorded with observation time, not inferred from package version. PX4 maintenance
observations are reused from the preceding source study.

Choose reuse of CLI/client plus explicitly frozen buffering for future design.
A new native uORB observer costs more build/provenance work and remains fallback;
PTY translation/color handling is excluded from this profile. No package install,
estimation algorithm or paper-derived noise model changes were needed. Resource
cost of real high-rate output is still unmeasured; no capacity benefit is claimed.

## Native experiment: actual client, synthetic server

`results/openvins-timesync-listener-dev-1701` retains the exact compiler command,
selected before/after hashes, binary, private-path/log-only substitutions and
four outputs. Unchanged pinned client.cpp/client.h/socket declaration are used;
`get_socket_path` is deliberately replaced by a unique private temporary AF_UNIX
path. There is no PX4 server. The status text is a handwritten source-derived
fixture, not a real uORB printer result. These distinctions are necessary.

|Case|Bytes before synthetic server completion|Client exit|Finding|
|---|---:|---:|---|
|Default pipe|0 during2.053209510s|0|Full valid-looking text only arrives at exit.|
|Explicit unbuffered pipe|234|0|First byte at0.145822ms in this one fixture.|
|Missing return trailer|234|255|Output presence does not prove clean completion.|
|Truncated frame with success trailer|214|0|Exit0 does not prove a complete record.|

These latencies are a single local IPC observation, not VIO/flight/TIMESYNC
performance measurements. The fixture sent a command asking for two records but
supplied only one frame intentionally. Fixed-byte adaptation used the actual
expected count2: all four complete-stream qualifications were correctly false.
The unbuffered first complete frame independently matched the existing numerical
observer, followed by premature-EOF refusal. The missing-trailer case refused
on nonzero exit; truncated text never produced a complete status; delayed default
text failed the two-second decoder deadline. No missing second frame was invented.

## Decoder and verification

`tools/benchmark/openvins_timesync_listener.py` requires exact non-PTY LF framing,
ordered fields, integer widths, selected instance and consecutive consumption
ordinal. It rejects diagnostics, ANSI/NUL/non-ASCII, duplicates, missing fields,
malformed age, unexpected trailing bytes, clock regression, premature EOF and
nonzero/unknown exit. Chunk4096B, frame1024B, total4MiB and record4096 limits bound
input. At the inclusive two-second deadline, no complete-frame output means
failure; partial trickles do not refresh it. The caller must call check on silence.

Completion flags are always false for live/network/fusion authority. Raw chunk
journaling, process identity, independent watchdog and durable I/O are future
harness responsibilities. Previously emitted records are not retroactively
erased on a later refusal. No parser output proves cold filter state or ownership.

Initial module-missing collection failure is retained separately from behavior
regressions. Initial284 cases passed, including every two-chunk split of the
234-byte fixture. Independent review found one Important issue: non-newline
garbage after the final expected record was held until EOF rather than refusing
immediately. Two behavioral counterexamples failed, were fixed, and were rerun
by the reviewer (2 passed,284 deselected), with no remaining actionable finding.
Final decoder286 cases and combined decoder/observer/interval/preflight409 cases
passed; changed Ruff passed. Full current-worktree regression with explicit
PYTHONPATH passed2440 tests,3 skips and2 existing warnings in329.64s. No whole-repo
lint pass is claimed.

The native client probe did not invoke the decoder. The four subsequent fixed-byte
adaptations used the pre-review decoder. The guard correction is separately
tested; the unchanged normal fixture was not replayed or described as a new
native run. The adaptation helper's exact hash/source is retained.

## Bootstrap, status and remaining work

Pinned listener returns a diagnostic for an unpublished topic, and timeout does
not necessarily mean nonzero exit. A proposed bootstrap must journal/reserve one
reply, send it once on an exclusive cold instance, withhold others while attaching
the explicit-instance listener, then match that latest first publication before
continuing. DeviceNode permits the subscriber to read a prior publication, but
queue depth1 and a correct offset cannot prove an exclusive producer or cold
filter. A bootstrap race is a study refusal, not grounds for blind restarts.

|Status|Scope|
|---|---|
|Verified offline|Strict parser, failure matrix, native-client buffering behavior in private fixture, first-frame observer parity.|
|Implemented|Bounded byte decoder with permanent refusal and strict EOF/count.|
|Unverified|Actual listener/uORB rendering, stdout runtime mapping, process/channel ownership, cold epoch,500 accepted updates within8s.|
|Preserved failures|Default buffering miss, missing trailer, truncated successful exit, missing-module RED and two review counterexamples.|

Next is a concrete cold/exclusive-channel and bootstrap lifecycle contract,
composed with the offline observer and interval-restoration component. Do not
send ODOMETRY or run another normal physical VIO capture to bypass this gap.
The25s physical duration,8s readiness,2s watchdogs and all sensor/physics loads
remain unchanged.100Hz remains a candidate setting, not demonstrated accepted
frequency. Overall fruit-fly learning, division of work, fair baseline and swarm
qualification remain pending; this is not a conclusion about their performance.

## Evidence seal

`evidence/openvins-timesync-listener-dev-1701.zip` contains the member manifest,
source comparisons, native fixture inputs/outputs, parser source/tests, review
RED/GREEN and full regression. The external manifest records SHA-256 and verified
CRC/member hashes. Existing startup/observer/interval archives are checked
unchanged. The pre-review decoder is reconstructed after execution and matched
to the adaptation's recorded hash, not described as a contemporaneous file copy.
Publication completion marks are added to the plan after sealing; the archive
retains its pre-publication snapshot.
