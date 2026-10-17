# Owned listener/bootstrap composition

Architectural integration of existing ColdTimesyncBootstrap and ReadOnlyListener.
User's continuous inline approval covers design and implementation; existing
worktree/branch retained. No actual PX4/MAVLink/parameter/flight authorization.

The missing result is a single coordinator enforcing the same8s startup window
across empty snapshot, first reserved reply/first snapshot, and a persistent
500..4096-record stream. Reuse existing strict parsers, modeled filter and Linux
owner/peer checks. Do not implement a second filter or send arbitrary commands.
Alternatives rejected: independent per-command readiness windows would reset the
global deadline; offline file-only composition would not cover real socket EOF
and owner association. An actual MAVLink responder remains a separate dependency.

OwnedBootstrap(process, expected, path, session_id, start_ns, journal,
stream_records=500, backend=None) keeps immutable owner/path/session and derives
comparison tags from the owner identity. These tags are not a cold-epoch proof.
Backend defaults to the existing LinuxBackend; test substitutes are labeled.
Constructor validates inputs without connecting. poll() lazily creates at most
three sequential owned connections: empty snapshot, first snapshot, stream.
Each uses the original start and start+8s deadline. The owned process is checked
between connections as well as inside every actual transport; no reconnect retry.

poll() opens first snapshot only after reserve_reply(request_ns,response_ns),
which records an intent through the existing bootstrap but performs no send.
It cannot prove an actual reply or exclusive source. An external fixture driver
may produce synthetic status afterward; a live driver needs separate design.
After clean first snapshot, open one stream. Its initial latest replay must equal
the first status and count as no new sample; exactly one pending reply at a time.
Raw stdout feeds the existing state machine, not rows repackaged as raw evidence.
Use each transport's zero status/trailer/EOF as the condition for snapshot
confirmation or final stream completion. Intermediate rows remain provisional.
Return progress without deep-copying growing logs on every poll.

One lock guards poll/reserve. Reentry/concurrent calls latch refusal and close
owned connections; an already executing I/O may finish and remains recorded.
Every public operation checks strict monotonic uint64 time, original8s total,
existing2s progress/frame/pending limits and unchanged owner. Journal delays are
checked after callback return, including after modeled completion. No callback
or log can turn failure into success. Polling/filesystem/process observations
remain synchronous, requiring outer supervision; no asynchronous cancellation.

Journal envelope identifies coordinator/bootstrap/transport source and command
index; copies isolate mutation. Retain transport construction refusals, actual
partial I/O, failed transitions, primary/cleanup/journal errors. Bounds:65536
regular outer events plus one terminal refusal; underlying transport/decoder
bounds unchanged. Snapshots remain bounded by the existing parser. A failed
outer coordinator masks modeled-ready in public progress and cannot resume.
Evidence contains underlying modeled progress, bootstrap events and all created
transport evidence separately. It never grants network/live/fusion qualification.
Explicit close aborts unfinished work and is idempotent. No process kill/launch,
socket unlink or stream/parameter write exists in production.

First test same-owner3connections, exact commands, empty/first/replay/500 sequence,
global clock not reset,2s missing progress, clock regression, identity change
between commands, wrong replay, unsolicited rows, premature EOF, construction
failure, journal failure/delay/reentry, nonzero final status and explicit abort.
Then freeze one ordinary Linux private-server matrix. Server uses a separate
fixture-only pipe to synthesize status after intent; no MAVLink is represented.
Use selected source/input/runtime hashes before/after, raw socket and fixture
control logs, all failures, direct-owned cleanup and one global monotonic clock.
One successful500-sample case proves modeled/socket composition only; synthetic
timestamps and fixture cadence cannot establish live accepted PX4 throughput.

No normal physics is rerun. Existing VIO/covariance domains,25s/1ms/250Hz/10Hz
physical workload,8s/2s gates and five-camera0.873RTF failure remain unchanged.
