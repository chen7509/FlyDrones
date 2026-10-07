# Same-connection owned daemon identity

The future TIMESYNC command path can now check the connected Linux peer against
an explicitly owned process before handing over the same socket. This closes an
ownership gap in pathname-only selection. The module sends no application bytes;
it is not yet a PX4 command reader, bootstrap runner or fusion authorization.

Implementation3ac54b1; ordinary-process harness producer c5846ea; review hardening
17b15fe. Written spec/plan: `superpowers/specs/2026-10-08-owned-daemon-connection-design.md`
and `superpowers/plans/2026-10-08-owned-daemon-connection.md`.

## Why this dependency exists

Fixed PX4 d6f12ad1c4f70ad3230afd7d86e971421e02fef4 uses
`/tmp/px4-sock-<instance>` in
[sock_protocol.cpp](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/platforms/posix/src/px4/common/px4_daemon/sock_protocol.cpp).
The fixed client connects and sends its command without checking peer identity;
the server creates/listens in its daemon process. Network namespace separation
does not isolate a filesystem socket pathname. Checking a different connection
before reconnecting would not establish ownership of the command connection.
All three retained client/server/protocol files match installed source exactly.
PX4 license is BSD-3-Clause. Maintenance metadata is reused, not newly queried:
nonarchived, last push observed2026-10-07T16:06:37Z.

The implementation uses installed Python3.12.3 (PSF) and Linux
[SO_PEERCRED](https://man7.org/linux/man-pages/man7/unix.7.html), which reports
credentials associated with the peer's connect/listen operation. The
[Python socket API](https://docs.python.org/3.12/library/socket.html) supplies the
same-descriptor getsockopt call. This is an OS/protocol dependency, not a new
estimation algorithm or VIO paper claim. No packages were installed. The fixture
ran on WSL2 kernel6.6.87.2-microsoft-standard-WSL2. Rolling documentation pages
were read; only the fixed PX4 files are claimed as retained pinned source.

Reuse the existing proc-stat parser, and bracket bounded proc observations with
unchanged PID/start ticks/group/session, executable path/device/inode, cwd
path/device/inode, effective UID/GID and user/network namespace links. Require
the original process handle to remain live. The connection checks these fields,
then SO_PEERCRED on the connected descriptor, journals the observation, and checks
identity/credentials/deadline again before handover. Wrong peer, exit, drift,
clock error, journal error or expired deadline closes the socket and refuses.
There is no socket unlink, process kill, automatic discovery or reconnect.

## Verification and failures

The prospective kernel-v1 harness uses private `/tmp/fly-peer-*` paths and ordinary
Python children, never the real PX4 socket. It freezes its own/module/parser/
Python-executable hashes before execution and verifies them afterward. This
selected-file inventory is not whole-runtime dependency closure.
The3 producer source files were subsequently exported from Git and matched to
the recorded before/after hashes; these are post-run exports, not claims of
contemporaneous source copies. All original run files remain unchanged.

|Case|Observed result|
|---|---|
|Matching child-created socket|Same connection handed over, then closed by harness; server received zero application bytes.|
|Wrong owned process|Connected server rejected against the separately owned sentinel; zero bytes.|
|Listener created by parent, inherited by child|Rejected: listener credential PID does not match the child owner; zero bytes.|
|Owned process exited|Refused before connect after recorded TERM/exit-15; no server receive observation was possible after exit.|
|Journal failure after peer observation|Refused and connection closed; zero bytes.|

Four live servers recorded empty application input and exited0. The exited case
retains exit-15; the independent sentinel was terminated by the fixture and
reaped. This harness creates no descendants and claims only those direct owned
children, not global process cleanup. No PX4/Gazebo/OpenVINS/ODOMETRY or new
training experiment ran. The existing full suite includes temporary CLI smoke
fixtures separately.

Initial RED was a missing-module import error. The first114 focused tests passed.
Independent review found one Important: if connect failed and closing that
socket also failed, the close error hid the primary exception; KeyboardInterrupt
could become an ordinary refusal. The first proposed regression encountered
Windows' missing AF_UNIX constant, a test precondition failure. After explicitly
supplying the Linux constant to the socket substitute, both intended assertions
failed, then passed with independent primary/cleanup error retention and original
interrupt propagation. Final focused adjacent suite116 passed. Independent
read-only re-review found no remaining Critical/Important/Minor finding.

Full regression with explicit current-worktree PYTHONPATH completed with exit0:
3125 passed,3 skipped,2 existing warnings in345.22s. This is the final hardening
tree; the separate kernel fixture remains on its original producer.

The harness initially had five Ruff findings (lambda assignment and loop closure
bindings); their output is retained and they were corrected. These were lint
findings, not failed kernel cases. Changed-file Ruff/diff passed afterward; no
whole-repository lint pass is claimed. The final hardening also retains raw peer
observations, including mismatches. That field was absent from kernel-v1 and is
not backfilled: the old run proves its recorded accept/refuse behavior; new
raw-value and double-failure paths have synthetic test evidence only. No second
five-case kernel run was performed to relabel the original producer.

## Scope and remaining integration

`connection_peer_matched` is moment-in-time connection evidence. A passed or
inherited descriptor may later have a different writer; peer credentials do not
solve malicious same-UID races, hostile ABA, namespace translations or launch
provenance. Caller-owned runtime binding must still establish the actual selected
binary/configuration. The module checks exe/cwd identity, not the complete loaded
runtime. `runtime_closure_qualified`, `network_authorized` and `fusion_qualified`
stay false. Synchronous file/journal stalls require external supervision; deadline
checks cannot asynchronously interrupt them. The caller owns the handed-over
descriptor and must use exactly it, not reopen the pathname.

Next compose bounded read-only listener command/response handling on this socket
with the fixed upstream command wire format, empty/first/multi bootstrap and
interval restoration. Preserve original8s readiness/2s frame/500 accepted gates.
Command framing and exit trailer must be independently checked; matching a peer
does not prove uORB filter freshness, source exclusivity or500 accepted live
updates. Do not execute actual PX4 parameter/stream changes or ODOMETRY based on
this result. Overall single-aircraft closed loop, full fruit-fly learning/division,
fair baseline and5/20-aircraft qualification remain downstream. The five-camera
0.873RTF<0.95 limitation and all historical physical failures remain unchanged.

Evidence is sealed in `evidence/owned-daemon-connection-dev-1701.zip`; the sibling
manifest records archive SHA256 and member hash/CRC verification. The previous
cold-bootstrap archive remains unchanged. Publication marks follow sealing.
