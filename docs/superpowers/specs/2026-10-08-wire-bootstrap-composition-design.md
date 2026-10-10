# Wire and owned bootstrap composition

## Purpose and authority

Connect the actual pinned TIMESYNC byte adapter to the existing owned listener
bootstrap so neither can report success alone after the other fails. Keep the
full FlyDrones objective and staged PX4 integration gates. Current work is
offline logic and ordinary private process fixtures only: no PX4, simulator,
OpenVINS, UDP, ODOMETRY, parameter changes, stream mutation, arming or training.
User preapproval covers design, implementation, verification and PR65 update.

## Sources and alternatives

Reuse fixed PX4d6f12ad/BSD3 listener/filter contracts, installed pymavlink2.4.49
common hash a7c6b23d908322134d19cb94b937c1ea6b1f5d5ffa9d1b0ad139174bf8d75809
and its retained mixed generator(L)GPLv3/generated-output MIT exception. Prior
metadata/codec evidence in openvins-timesync-wire-dev-1701 remains unchanged;
no repeated codec capability experiment or new algorithm/paper claim is needed.
CPython installed3.12.3/PSF, os.write's byte-count API and Unix selectable pipes
are reused; current3.12 docs are not proof of installed patch equality. Installed
source/harness/API hashes accompany a frozen new fixture. No packages installed.

Adopt a small production coordinator. Reject leaving failure propagation to each
caller, and reject implementing another numerical filter. The sink remains an
injected boundary; no arbitrary real socket or process launch is added. This is
not a substitute for future actual UDP ownership/source/clock validation.

## Production interface

First fix the deferred wire received_ns issue: accept nondecreasing local receive
timestamps, reject any regression even on heartbeat-only input. Equal timestamps
are allowed for clock-resolution ties; requestts1 remains strictly increasing.
Keep independent maximum-age/future checks, no TTL adjustment. Add public
TimesyncWireResponder.check() for serialized idle deadline/session checks.

Add OwnedBootstrap.check() which performs existing clock/owner/pending/frame
checks without opening a command or consuming input. It must use the same
failure/cleanup path as poll/reserve. No new deadline or authority.

OwnedWireBootstrap(process,expected,path,remote_clock,start_ns,journal,send_sink,
backend=None) in tools/benchmark/openvins_wire_bootstrap.py constructs one
OwnedBootstrap and one TimesyncWireResponder with the same start/backend clock.
The reserve callback is the actual OwnedBootstrap.reserve_reply, not a fake
success response. poll() consumes listener progress; receive(raw,peer,
received_ns,observed_sim_ns) handles a request; close() is idempotent.

Before and after each operation check both sides. Immediately before invoking
the external sink recheck the owned process and outer failure latch, including
any reentrant journal failure. Count a completed_reply_attempt only after the
wire receive operation and final owner checks pass. Returned byte counts stay
in wire evidence even if subsequent checks fail. Completion requires all500
modeled accepted statuses, clean owned listener terminal/EOF, exactly500
completed reply attempts, and no wire/coordinator failure. No status/counter is
invented to meet500; replay remains counted once. Finished objects refuse new
operations without rewriting their historical successful evidence.

A failure in either side latches the outer coordinator before error formatting,
closes current owned listener, retains primary and cleanup errors, and masks
all composed completion outputs. Inner evidence is retained as inner evidence,
never renamed actual PX4 success. Nonblocking operation lock rejects concurrent
or callback-reentrant use; check after callbacks before further effects. Shared
journal envelopes identify wire vs owned events and receive independent copies.
No unbounded extra event list: compose the existing bounded inner logs. Original
8s global,2s request/pending/frame and500 sample constraints remain unchanged.

## Ordinary-process integration design

Freeze one new matrix before launch: normal500, wrong-replay, sink-short and
journal-failure. No old matrix is rerun. Reuse the prior ordinary daemon's exact
listener command/output protocol and synthetic status template, with a new
stdin decoder that actually validates received pinned MAVLink response bytes.
The response's echoedts1/remote tc1/header/sequence must match the next synthetic
request. Only then may the fixture release its corresponding simulated status.

Requests are explicit synthetic in-memory packets; their supplied peer and
simulation time are fixture labels, not actual UDP arrivals or PX4 clock data.
Replies travel as actual bytes through the owned child's stdin pipe, using
os.write actual byte count. A separate JSON stop marker is fixture cleanup only.
AF_UNIX listener output passes the existing same-FD SO_PEERCRED/owner checks.
The status template and fixed2ms modeled RTT remain synthetic; measured parent
wall duration cannot be called live TIMESYNC throughput or aircraft latency.

Use retained Linux private scratch files and copy/hash after termination. Check
ready/command/control count,500 successful byte matches in normal case, all
failure results, journal equivalence and direct-owned child cleanup. No unrelated
process termination, no scratch deletion. Sink-short intentionally writes an
incomplete frame; child decode failure/exit2 is preserved as expected fault
evidence, not relabeled clean success. Source hashes and installed codec/Python
are frozen before/after. A failed matrix run is retained; do not silently rerun.

## Validation and remaining gates

TDD: monotonic/tied receives, non-consuming checks, normal composed500 with
realcodec and fake transport, wrong phase, pending reuse, owner/clock/session
change, short send, bad CRC/status, journal/reentrant failure, close and EOF.
Actual-codec unit tests run in WSL stdlibunittest; Windows missing-codec skips
are explicit. Review whole change once and fix Important/Critical findings
with RED→GREEN; full regression after final code. One frozen private matrix.

No actual UDP descriptor/source guarantee, namespace-isolated PX4 cold epoch,
real status/filter acceptance, interval ACK/query/rollback or fusion is proven.
Current physicalVIO simulation-domain results and all historical failures stand.
Five-camera0.873RTF still fails0.95; no load/threshold reduction or Linux install.
