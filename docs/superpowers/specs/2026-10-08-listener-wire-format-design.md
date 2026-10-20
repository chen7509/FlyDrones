# Pinned multi-record listener framing correction

Purpose: unblock the actual PX4 first-status/serial-observer integration, under
the existing no-network/no-physical authorization. This is a bounded prerequisite
correction discovered during cold bootstrap research, not a replacement goal.
User preapproved routine plans and inline execution; no new approval is needed.

## Evidence and choice

Pinned PX4 d6f12ad listener_main.cpp emits `ESC[2J LF ESC[H` before every explicit
instance record when num_msgs > 1, irrespective of terminal type. The existing
decoder rejects ESC. The old hand-authored two-record test did not model this
source branch. A native probe compiled the unchanged installed/pinned listener
against explicit fake uORB/pollable-pipe/field-printer services. Its two-record
stdout is 484 bytes, SHA256 e3b3453862a2a4e219f3c5b96c717a82e5de37e9bd0df7f452764ac64cc854f9.
The probe selects unbuffered stdout; it does not prove actual PX4 buffering,
uORB delivery, fields, clock, namespace or throughput. No PX4 daemon is used.

Keep the existing plain profile for historical fixed data. Add keyword-only
output_profile='plain-v1' to TimesyncListenerDecoder. The opt-in
'px4-d6f12ad-multi-v1' profile requires expected_records >= 2 and exactly the
eight-byte prefix before each complete record, including #1. Prefix bytes count
against raw frame/chunk/total limits and cannot refresh the two-second deadline.
Reject partial/missing/duplicated/misplaced/unknown prefixes, arbitrary controls,
extra trailing data, diagnostic output, wrong instance/ordinal and bad exit.
The existing field parser, numerical observer and authority-false flags remain.
Neither autodetect nor general ANSI stripping is acceptable: both can hide
corrupt output. Changing upstream listener code is unnecessary and rejected.

Per-byte fragmentation is allowed. A complete prefix is necessary but never
sufficient to release a record. Preserve raw bytes outside this pure parser;
report chosen output_profile and raw byte count. No background watchdog is
created: the future harness must poll check() even during silence. The implicit
single-record listener header remains unsupported (no explicit instance identity).

## Validation and remaining dependencies

Use the recorded native stdout plus analytical mutation cases, all split
boundaries, byte-by-byte delivery, strict two-second deadline, field/escape
corruption, partial prefixes, overflow and post-completion data. Feed valid
records to the existing serial observer with actual fixture request identities.
Synthetic 500-record parsing does not qualify live accepted throughput.
Keep all prior format failures and identify the probe's stubbed surfaces.

Cold PX4 lifecycle/exclusive responder, all-instance discovery, first-reply
association, actual listener/transport, cwd/resource binding, reversible stream
transaction and 500 accepted/8s readiness/25s study/2s watchdog gates remain.
No ODOMETRY, PX4 parameter/stream change, EKF2, arming or training in this task.
