# Generated RX software timestamp contract

User's full swarm objective and blanket plan authorization persist. This architectural transport dependency addresses the failed NS queue-time proof; it is not a substitute for learning, real PX4 provenance, clock mapping or physical flight. Keep the existing worktree/PR65 and push only personal.

## Choice and scope

Official Linux timestamping API separates RX_SOFTWARE generation from SOFTWARE reporting. Adopt a separate SO_TIMESTAMPING_NEW profile with exactly those two flags, three signed64 timespecs, only ts[0] nonzero. Forbid SO_TIMESTAMP_OLD/NEW and SO_TIMESTAMPNS_OLD/NEW before/after enable and before/after receive; never enable them, clear caller options or mix the two profiles. Fixed v6.6 socket.c has current-time substitution under SOCK_RCVTSTAMP; excluding the legacy receive-timestamp options addresses the source-described fallback, without claiming installed-kernel causality or arrival qualification. Reject missing/zero metadata; no callback-time fallback, warm-up sleep or blind retry.

Alternatives: old NS metadata failed its declared loopback queue proof and stays frozen; hardware timestamps require device/clock support and external research. Use installed Python3.12 recvmsg and Linux headers, no daemon/dependency install. Kernel GPL2-family/UAPI syscall exception, Python PSF. Official API documentation is current; support status of fixed v6.6 and installed WSL patch equivalence remain unestablished. No protocol source is claimed as VIO/camera calibration research.

Primary references: https://docs.kernel.org/networking/timestamping.html ; https://github.com/torvalds/linux/blob/v6.6/net/socket.c ; https://github.com/torvalds/linux/blob/v6.6/net/core/sock.c ; https://github.com/torvalds/linux/blob/v6.6/include/uapi/linux/net_tstamp.h ; https://github.com/torvalds/linux/blob/v6.6/include/uapi/linux/errqueue.h ; https://docs.python.org/3.12/library/socket.html#socket.socket.recvmsg .

## Architecture and strict interface

New `KernelRXTimestamping` is an exact internal subclass of KernelTimestampNS solely to reuse bounded ABI/hash validation, one-use pre-bind identity, realtime high-water, failure latch and raw describe logic. Base constructor validates the declared class ABI; base enable/check use overridable internal option hooks. DatagramReceiver accepts only exact NS/RX concrete types, no caller subclass or duck decoder. Existing NS probe/config and its default semantics remain unchanged. Source and clock authority remain false in both types.

RX installed-header probe `kernel_rx_timestamping_abi.c` emits schema `flydrones.kernel_rx_timestamping_new_abi.v1`, x86_64/little/pointer8, SOL_SOCKET, NEW option/cmsg, flags, four forbidden option numbers, 48-byte scm_timestamping64 triple layout, 16-byte element/offset0/16/32, CMSG_SPACE and MSG flags. Expected constants may be compared to a narrow supported profile but are not trusted as an installed observation until the new bounded header probe is compiled and frozen. Unknown schema/type/layout/hash/values refuse. Probe is read-only C stdio, no socket. Freeze compiler/headers/source/output/binary/dependency list; compile10s single job, no install.

Before bind: literal IPv4 UDP/unbound/FD valid; confirm every forbidden option reads exact int0; enable NEW with RX_SOFTWARE|SOFTWARE; confirm exact flags, forbidden int0, unchanged FD/address. Unexpected read/set exceptions latch failure; cannot reuse object. Every check revalidates object/FD/options/forbidden options. Cannot retrofit a bound socket or silently disable conflicting options.

Decode exactly one SOL_SOCKET/NEW/48-byte ancillary, flags0. Require ts[0] sec>0 and 0<=nsec<1e9; require ts[1]/ts[2] all zero; reject zero, old cmsg, duplicates, flags/truncation, malformed ranges/overflow/future, regression. Reuse final sample-vs-observed-realtime validation with identical strict bounds. Raw 48 bytes fit existing describe64; receiver uses installed 64-byte CMSG_SPACE. Preserve original payload/peer/flags/raw fields before failing callbacks, user monotonic return stays separate. Successful decode grants no actual arrival/source freshness permission.

Tests cover forbidden options at initial/after enable/pre/post receive, exact flags, error latch, invalid types/bools/changed schema/layout/digest, triple zero/nonzero hardware, wrong cmsg/size/truncation/future/regression, unsupported subclass, and raw payload/cmsg retention when failure follows actual receive. Legacy adjacent tests and existing NS frozen trial stay unchanged. No activation in CaptureWireOwner/live/physics or MAVLink control.

## Gates and later trial

This stage's gate is software/native ABI capability only. After code/ABI review, a separate prospective profile must freeze a new owned opaque loopback study, send3 and delay40ms, queue diagnostic >=20ms, timeout20s/kill-after2; exact pending/raw/cleanup evidence even on failure. Do not run that trial from an unreviewed CLI or copy the failed NS profile. No PX4/ROS/physics/model process. It must distinguish missing metadata from false arrival and preserve all failures without altering gates. Clock mapping and real PX4/CameraInfo/reset/EKF2 health/private publishers are later dependencies.

Resource observation: Windows about2140MiB available, Docker Linux engine unavailable; no simulator/model/firmware build dispatched. Complete MaleCNS/physics/firmware4GiB and EGO2500MiB gates unchanged; five-camera0.873RTF<0.95 and first2sTIMESYNC failures stay. Keep complete learning/roles/fair baseline/single→5→20 objective active, no PPO/reflex substitution or true-state online input.
