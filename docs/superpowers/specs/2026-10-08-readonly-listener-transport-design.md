# Read-only listener command transport

Purpose: implement the missing real byte-I/O adapter on the same owned AF_UNIX
connection, without authorizing a live PX4 study. User-approved continuous inline
execution applies. Ordinary private fixture servers only in this stage.

Fixed PX4 d6f12ad client.cpp/server.cpp encode argv joined by spaces, then one
isatty byte (0 for this non-PTY profile). Server waits for that byte, not a client
half-close. Response is stdout followed by0/one-byte return value and EOF. The
client header's half-close prose does not describe the inspected implementation.
Reuse those wire semantics, not a shell or general command interface. This is a
Python adapter derived from inspected protocol, not unchanged upstream client.
Existing peer gate, strict snapshot/multi decoders and raw fixtures are reused.
No new dependency/estimation algorithm; installed Python3.12 nonblocking socket
API provides bounded send/recv calls. Filesystem/journal stalls still need outer
supervision; this is not asynchronous cancellation or proof of live throughput.

`listener_command(mode,count)` accepts only snapshot/count1 or stream/count2..4096.
Output is exactly `listener timesync_status -n 1\0` or
`listener timesync_status -i 0 -n COUNT\0`. No arbitrary args, paths, writes,
shutdown command, interval or parameter command.

`ReplyEnvelope.feed(bytes)` returns stdout bytes before the first NUL. The next
byte is the unsigned exit status; any subsequent byte refuses. Only a0 status
plus actual EOF can finish successfully. Chunk<=4096, total<=4MiB+2; malformed,
truncated, duplicate/trailing bytes and nonzero status latch failure. This narrow
listener output profile has no embedded NUL. Partial trailers never become stdout.

`ReadOnlyListener(process,expected,path,mode,count,start_ns,deadline_ns,journal,
backend=None)` uses connect_owned_daemon and exactly its returned socket. Require
absolute uint64 monotonic start/deadline, window<=8s and current time in window.
Connect deadline is min(global deadline,current+2s). Decoder2s first/complete-frame
timer starts at entry; connect/send time does not buy extra frame time. Native
socket becomes nonblocking; no reconnect, private stdout buffer or extra process.

`poll()` is single-owner and nonblocking after construction. It validates clock,
global/frame deadlines and unchanged owner/peer, journals the exact send attempt,
rechecks after journal, sends once (retaining partial offset), and reads at most
one4096-byte chunk only after all command bytes have been sent. Would-block makes
no progress and does not refresh deadlines. Returned raw stdout and parsed rows
are provisional until valid EOF/trailer/decoder completion. Snapshot stores at
most1024bytes until EOF and uses parse_snapshot. Stream feeds the existing pinned
multi decoder. Check at every poll, including silence; caller must poll/arrange
outer supervision. Caller can interleave a future responder, but no responder is
implemented or authorized here.

Journal callbacks returnNone. Input/events are copied; failure closes and latches,
including errors after partial sending. No rollback fiction. Reentrant/concurrent
poll refuses and latches, with no additional writes once observed; an already
running OS operation may finish. Keep bounded events and raw bytes. Record
connect evidence, send attempted/returned, recv raw/EOF, parse failure, close
failure separately. Preserve KeyboardInterrupt after cleanup. Explicit close is
idempotent, aborts unfinished transport and does not turn it into success.
Successful EOF closes connection, requires journal+final clock/identity checks,
and returns terminal result; all network/fusion/live-listener flags remain false.

Testing: exact fixed commands and every split of native response/trailer; wrong
shape/limit/status/trailing bytes; partial send, would-block, send0/exception,
incomplete payload/EOF, deadline during journal, clock/owner/peer drift, reentry,
callback mutation, cleanup error. Named private-server harness uses sealed220-byte
implicit and484-byte multi fixtures, fragmented output, missing/nonzero trailer,
silent peer, journal failure. Match exact received command bytes, same peer,
consumer result and owned cleanup. Freeze sources/input/runtime before execution.
No real PX4/MAVLink/ODOMETRY/parameters/physics/training/scaling. Existing500/8s/2s
bootstrap gates,25s physical study, all failure evidence and five-camera0.873RTF
limitation remain unchanged.
