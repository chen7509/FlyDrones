# Serial TIMESYNC observation: offline validation

Date: 2026-10-08

## Decision

Implemented a pure one-reply/one-status observation contract. It matches the
pending reply to PX4's reported remote timestamp, RTT, offsets and topic identity
before advancing its filter model. It does not run a listener or send packets.
`live_convergence_qualified`, `network_authorized` and `fusion_qualified` remain
false even after 500 matched accepted statuses.

Task 4 launch readiness remains reopened. Installed listener framing, bootstrap,
exclusive producer/channel proof, cold PX4 epoch, actual timing and reversible
stream-rate changes remain unverified. No new physical run is justified by this
offline result. The broader learning, closed-loop and swarm goals remain pending.

## Installed-source findings and selection

The evidence directory is `results/openvins-timesync-observer-dev-1701`.
Eleven installed source/generated files were saved. Nine source files were then
fetched at PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4` and matched byte-for-byte:
listener main/header, DeviceNode, Subscription, MAVLink timesync header/source,
Timesync header/source and POSIX main. Generated metadata and wire headers are
installed evidence only. This is not a full checkout/build reproducibility claim.

The fixed code is BSD-3-Clause. Current PX4/pymavlink maintenance observations
and installed pymavlink 2.4.49 license provenance are reused from the immediately
preceding startup study; they were not fetched again or represented as new
observations. No package, daemon or ROS/DDS stack was installed.

- [Listener source](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/systemcmds/topic_listener/listener_main.cpp)
  increments a consumption count. It does not export the generation value
  available to a native uORB subscription. The installed topic queue depth is
  one. Therefore ordinary line counting cannot prove complete publication.
- The pinned [MAVLink wrapper](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/modules/mavlink/mavlink_timesync.h)
  initializes `Timesync _timesync{}`. Its status source protocol is the default
  UNKNOWN (0), even though the schema defines MAVLINK (1). This field cannot
  serve as channel identity proof.
- Installed generated TIMESYNC has target-system/component extensions; the
  fixed handler does not use those fields to correlate accepted replies.
- POSIX client dispatch uses `px4-listener --instance 8 ...`; listener topic
  selection uses a separate `-i`. Neither client nor PX4 was invoked here.

Reuse the existing tool as a candidate with one outstanding reply. A matching
status must arrive before the next reply reservation. This can prevent our own
controlled updates overwriting one another, but only if exclusive ownership and
no hidden reset are demonstrated in the eventual runtime. No such assumption is
upgraded to a passing qualification by this class. Modifying PX4 to expose new
native diagnostics remains a fallback with extra build/provenance cost.

## Implementation

`SerialTimesyncObserver` in `tools/benchmark/openvins_timesync_observer.py` has no
socket, subprocess or file interface. A reservation records intent only. It
requires exact status keys, strict integer ranges, increasing reply identities,
the selected instance and consecutive observation ordinals. The ordinal checks
record continuity, not uORB publication generations.

PX4 receive time is reconstructed from request time plus reported RTT. Status
publication time is checked independently and never substituted for receive
time. Prediction occurs on a cloned existing verifier; offset mismatch does not
advance the stored filter. Failure latches permanently. A pending status expires
at the inclusive two-second local deadline; a second pending reply, missing or
unsolicited status, malformed data, clock regression or filter reset is refused.

New `estimated_offset_us` exposes the same integer-microsecond cast as the pinned
status output. The existing filter's division was corrected to signed integer
truncation: `int(numerator / 2)` previously rounded through a float. Review
reproduced both refusing a correct offset and accepting a wrong offset for
large, valid positive/negative odd numerators. Four behavioral RED cases became
GREEN after the fix. Future runtime declarations must bind this updated helper;
older preflights and archives are not retroactively updated.

## Executed validation and retained failures

Initial RED was a missing-module collection error, not a behavior assertion.
The next run found pytest's reserved `request` parameter name in a test; it was
renamed. The following two assertion failures came from fixtures assuming a
constant -1000 us integer estimate during floating-point filtering. Those
fixtures now use exactly representable zero-offset convergence cases, and an
independent native-source experiment below checks nonzero behavior. These
failures were retained rather than claimed as production fixes.

Focused observer and preflight validation: **71 passed**, including the four
review regression cases. Independent review confirmed the correction with four
passing cases and no remaining actionable finding. Changed-file Ruff passed.

The unchanged pinned `Timesync.cpp` and header were compiled with GCC and explicit
synthetic clock/uORB publication stubs. This is not the PX4 binary, actual uORB
or a live listener. The native probe produced 520 statuses, including one
RTT-rejected exchange; the final observer matched every status and convergence
flag, with 519 modeled acceptances. Of the first 500 constant-offset inputs, 179
native integer estimates differed from the ideal -1000 us constant, explaining
the discarded fixture assumption. A separate native boundary probe confirmed
the correct offsets `4503599627370497` and `-4503599627370497` us used by the
review regression cases. Source hashes, compiler command/version, stubs, binaries
and output hashes are retained. Compiler version was recorded, not a prospective
compiler-binary freeze; this is an analytic build, not a physical-study build.

The first whole-repository pytest attempt failed with 70 import-collection errors:
the default interpreter loaded a FlyDrones installation outside this worktree.
`import-path-before.txt` and `import-path-after.txt` preserve the paths. The retry
explicitly sets `PYTHONPATH` to this worktree's `src` and root, preserving the
same tests and interpreter without installing or modifying dependencies.
The corrected full run completed with **2102 passed, 3 skipped, 2 existing
warnings in 325.12 s**. Final combined observer/preflight/receiver checks passed
**142 tests**. Ruff for the changed Python files and Git whitespace checks passed.

The sealed bundle is `evidence/openvins-timesync-observer-dev-1701.zip`; its
companion manifest records SHA-256, member count and CRC/member verification.
It includes failed attempts, source comparisons, explicit native stubs/binaries,
native outputs, final production source and test logs. It does not replace or
modify previous physical evidence or preflight archives.

## Remaining integration gates

1. Prove listener output framing/instance bootstrap and cold filter identity.
   Listener refuses an unpublished topic; its bootstrap/re-subscription must
   neither lose nor double-count the first controlled status.
2. Establish exclusive controlled replies and detect any foreign update or hidden
   reset. Matching numeric output alone cannot prove these premises.
3. Implement and test reversible stream-interval apply/readback/restore. Preserve
   25 s total load, 8 s readiness, 200 ms future anchor and 2 s watchdogs; do not
   silently add warmup or equate requested 100 Hz with achieved throughput.
4. Bind the complete replacement preflight, then obtain the separately scoped
   authorization before any actual ODOMETRY or PX4/stream mutation. Receiver-only
   execution must retain `EKF2_EV_CTRL=0`, unarmed state and all failure evidence.

The serial contract adds model-matching work per exchange and any eventual
listener adds runtime load; neither is a capacity optimization. No result here
changes the failed five-camera 0.873 RTF gate or proves fruit-fly learning speed.
