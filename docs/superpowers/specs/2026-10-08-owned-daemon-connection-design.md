# Same-connection daemon ownership gate

Purpose: make the next TIMESYNC command transport bind to the owned process,
instead of treating an instance-number pathname as ownership. This implements
only the connection/identity prerequisite. No command or MAVLink bytes, PX4,
Gazebo, estimator, stream/parameter mutation or flight authority in this stage.
User preapproval covers written design and inline implementation in this worktree.

Pinned PX4 d6f12ad Client::process_args connects a pathname then calls _send_cmds
without a peer credential check. Server::start creates/listens in the daemon
process. Existing user/network namespace isolation does not isolate pathname
UNIX sockets. A separate preflight connection cannot qualify a later reconnected
command socket. SO_PEERCRED reports credentials associated with listen/connect;
it does not prove who later writes through an inherited/transferred descriptor.

Choose Linux SO_PEERCRED on the exact returned connected SOCK_STREAM descriptor,
with before/after registered Popen process observations. Reject the alternatives
of pathname existence, socket file ownership, a separate probe then reconnect,
or PID alone. Do not introduce a private mount namespace or modify fixed PX4.
Reuse owned_group_evidence.parse_stat. Registry/capture runtime binding remains
responsible for launch provenance and dependency hashes; this is not a replacement.

`observe_owner(process)` reads bounded proc stat/status and exe/cwd/ns links,
brackets the observation with pid/start/group/session checks and requires poll()
still None. Result: literal pid/pgrp/session/start_ticks, effective uid/gid,
resolved exe/cwd path plus device/inode, net/user namespace IDs. Dead/zombie,
malformed/unreadable or changing process refuses. It does not guess from a scan.

`connect_owned_daemon(process, expected, path, *, deadline_ns, journal,
backend=None)` consumes a previously captured expected owner, explicit absolute
pathname (nonabstract, <=107 encoded bytes), and one absolute monotonic deadline
within2s of entry. Snapshot and return objects use copies. Backend supplies
observe, monotonic_ns, connect, peer credentials and close for deterministic tests;
default Linux backend uses the installed Python socket/proc interfaces.

Validate schemas and expected Popen PID, compare identity before connect; record
attempt with original pathname/deadline, check elapsed time/identity again; connect
with remaining socket timeout; query SO_PEERCRED (pid/effective uid/gid) on that
same descriptor; compare process again; record success evidence; finally repeat
peer/owner/clock checks after journaling before returning. All failed paths close
the connected descriptor, retain memory error and attempt/refusal journal where
possible, and never send application data. A journal error cannot authorize
handover; close errors remain distinguishable, not swallowed as successful cleanup.

Return `connection` and evidence only after successful journal and final checks.
The caller must use exactly this descriptor and close it; no CLI/default path,
automatic discovery/retry or reconnect. The gate neither kills the process nor
unlinks any socket. It sets network_authorized/fusion_qualified false, and only
connection_peer_matched true. It is a moment-in-time check, not an anti-malicious
same-UID/ABA/FD-passing proof. General launch provenance and runtime closure remain
unqualified. Parent timeouts/supervision must bound filesystem/journal stalls;
post-call deadline checks are not asynchronous cancellation. The existing8s
bootstrap and2s frame limits remain independent and unchanged.

Tests: schema/PID/exe/cwd/namespace/start/credentials drift, exited process,
connect/peer error, journal failure/late journal, clock regression and close error.
One prospectively frozen ordinary AF_UNIX process harness covers matching peer,
wrong owned PID, socket created by a parent then inherited by child, short-lived
peer, and journal refusal. Server records received application bytes (must zero).
Use exclusive private temp paths; no real /tmp/px4 socket. Preserve failure/cleanup
logs. This harness validates kernel identity behavior, not PX4 protocol behavior.
