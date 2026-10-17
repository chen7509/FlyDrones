# Datagram receive boundary for the staged PX4 bootstrap

## Intent and authority

The goal remains credible VIO/PX4 safety integration and eventually complete fruit-fly learning/division and fair comparison. Existing wire/bootstrap composition consumes caller-supplied peer and receive time; it does not read a datagram. Add the missing single-datagram receive boundary, not another estimator/filter or process supervisor. Current execution is offline synthetic tests only: no socket creation/bind/connect/send, actual UDP, PX4/Gazebo/OpenVINS, ODOMETRY, parameter/stream change, arming or new training study. Routine design/implementation/tests/publication are already approved.

## Research and decision

Pinned PX4 d6f12ad/BSD3 init_udp binds INADDR_ANY and the configured port. Its receiver learns the client address on initial reception; the inspected initialized path is not a per-datagram sender-PID authentication check. Existing isolated-launch and original-owner listener gates therefore remain necessary for future actual operation. Neither an IP/port match nor a successful UDP connect proves process identity.

Reuse installed CPython3.12.3/PSF recvmsg. Official Python3.12 documentation (rolling3.12.15) defines a data/ancillary/flags/address tuple; Linux udp(7) documents one packet per receive and truncation flags. Use the API directly on a supplied socket; reject ancillary data and all nonzero flags in this narrowly declared profile. This does not support kernel timestamps or GRO. The observed time is monotonic userspace syscall-return time, not kernel arrival or end-to-end latency. Fixed pymavlink2.4.49 and all numerical contracts remain unchanged.

Choose a small read-only adapter with a supplied socket and existing ownership guard. Reject adding a UDP factory/sender or arbitrary socket CLI at this stage. Reject recvfrom because it hides the message flags needed to detect truncation. No package installation; resource cost is one <=4096-byte read per poll, bounded event storage, no polling thread. Current upstream metadata/pins are reused with their earlier observation dates, not presented as fresh maintenance checks. This is protocol/API work, not a new VIO/learning algorithm or paper claim.

## Interface and scope

`DatagramReceiver(sock, guard, now, start_ns, journal)` in tools/benchmark/openvins_datagram_receive.py. The caller retains socket lifecycle ownership; this adapter never closes, creates, binds, connects or sends. `guard()` must return None after checking the owning session/descriptor; use a caller-supplied callback so the future real integration can use the existing owned/namespace gate. Passing a fake guard proves nothing about a process. The adapter enforces no network/live/fusion authority and explicitly reports sender_process_proven=false.

`poll()` calls guard before reading, records the local monotonic start, performs one `recvmsg(4096, 0, MSG_DONTWAIT)`, observes local monotonic return time, records raw returned data/peer/flags, checks guard again, then returns an immutable `ReceivedDatagram(data, peer, received_ns)` only if qualified. A BlockingIOError means no datagram; still check clock/guard and return None. An empty UDP payload is a received packet and is refused, not an EOF/no-data success. No receive retry or blocking wait is added.

Require supplied socket AF_INET/SOCK_DGRAM/IPPROTO_UDP-or0, nonblocking timeout0 and exact local127.0.0.1:14548 each time. Received source must be exact127.0.0.1:14588 with strict tuple/string/int shape (bool is not port). This is endpoint agreement only. A later integration must prove namespace/descriptor ownership and producer/session separately. recvmsg may be unconnected; no getpeername requirement or implicit connect.

Strict integer monotonic clock, original8s global deadline and2s per-call bound, equal clocks allowed. Data must be bytes length1..4096, ancillary list must be empty, flags strict int0. Preserve return bytes in internal evidence before a clock/guard/journal failure; actual flags/source retained even if refused. Unexpected tuple shape/types are refused with bounded diagnostic metadata, never fed to decoder. No arbitrary repr/str callbacks for returned objects. All external journal values are deep copies; journal must return None. Retain failure before formatting and refuse subsequent polls. Nonblocking lock rejects concurrent/reentrant use before a second recvmsg. Event limit8192 with a separate refusal slot; reserve attempt/return capacity before the syscall. Idle calls need not append repeated empty observations, but never renew the global start/deadline.

No automatic raw-to-wire forwarding: caller needs a separately verified simulation-clock observation. This avoids substituting request ts1 as observed simulation time. Future integration will pass returned raw/peer/received_ns plus that independent clock input to existing OwnedWireBootstrap.receive. This boundary can be independently tested without manufacturing simulation-clock evidence.

## Verification and remaining work

Offline injected sockets only. Test exact recvmsg arguments, normal packet, empty/not-ready distinction, cap/truncation/ancillary/unknown flags/wrong peer, socket mode/local drift, guard failure before/after consume, monotonic/regressed/exact deadline clocks, journal failure before/after consume, return evidence retained despite clock failure, reentry, input mutation and event capacity. Callback guards are synthetic and all source/kernel/process proof stays false.

Independent final review, one Critical/Important fix pass with counterexamples, full regression plus changed Ruff/diff. No ordinary-process or UDP fixture is needed or allowed in this stage. Freeze final source, test output and researched source references into an exclusive archive; preserve prior studies. Actual datagram reception, descriptor/namespace/producer binding, simulation clock source and actual PX4 filter convergence remain untested; this stage does not authorize them.

Review ruling: the per-call MSG_DONTWAIT is mandatory because gettimeout() is a Python-object setting and descriptor aliases share kernel mode. Unsupported platforms refuse at construction; Windows tests explicitly inject the observed Linux flag into fake sockets only. Timeout checks do not preempt arbitrary external guard/journal code; a future caller must bound or supervise callbacks. No actual alias/socket experiment was performed.
