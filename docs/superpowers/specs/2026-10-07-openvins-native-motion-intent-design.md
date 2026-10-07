# OpenVINS native motion-intent adapter design

## Scope

This stage connects the already tested truth-free `MotionIntentGate` to the
existing single-owner GPL-linked OpenVINS research adapter.  It does not alter
the pinned OpenVINS library, estimator thresholds, initialization policy,
noise model, camera stream, physical scene or flight controller, and it does
not authorize PX4/Gazebo execution, ODOMETRY, arming or EKF2 injection.

OpenVINS remains commit `69488123ed9362dd44b6f28e7f4680abbff1442b`,
GPL-3.0.  The pinned `VioManager` exposes `params`, `is_initialized_vio`,
`did_zupt_update` and `has_moved_since_zupt` as protected members.  Its
camera/IMU paths skip beginning-only ZUPT once the movement flag is true.  The
adapter therefore uses a narrow subclass method in the GPL-linked executable;
the MIT Python layer carries only a bounded protocol and does not copy the
upstream implementation.

## Protocol

Add one transport kind, `M`, to the existing one-request-in-flight native
pipe.  Its exact payload is the transport sequence, effective simulation
timestamp, source arrival and dispatch clocks, command sequence, intent
SHA-256, estimator-session SHA-256 and clock-domain SHA-256.  No pose,
measured velocity, acceleration, Gazebo state or other truth is permitted.
Python rejects extra/missing fields, booleans masquerading as integers,
invalid hashes, pixels, zero/late identity and a mutated acknowledgement.

The native subclass accepts exactly one command sequence zero after internal
initialization.  It verifies the frozen runtime options have
`try_zupt=true` and `zupt_only_at_beginning=true`, verifies the effective
timestamp does not precede the initialized state, and refuses a duplicate or
already-moved estimator.  It then sets the existing movement flag and clears
the stale per-frame ZUPT latch.  Its acknowledgement includes the exact intent
and session identities, option values, initialized state and resulting flag.
The Python gate still decides whether the later actuation step is authorized.

Any parse, timing, configuration, session, reset, process, pipe, log or
shutdown failure remains terminal.  The transport stays single-worker and the
existing two-second bound remains unchanged.

## Verification

TDD first covers exact packet bytes, strict action schema, hash/session
binding, acknowledgement projection, configuration booleans, duplicate and
pre-initialization refusal, and the existing gate's reset/clock/safety cases.
Then compile a new binary in WSL against the unchanged pinned library and
freeze compiler, source, binary and dynamic-library identities.

A new read-only fixed-input replay consumes the sealed `study-v21/capture-v1`
native requests and RGB bytes only through the first initialized state and a
short post-intent window.  It uses a new monotonic replay clock, not historical
arrival latency, sends one motion intent before its prospective effective
time, and verifies the same native session acknowledges the flag before the
gate authorizes that time.  A separate bounded negative run proves native
pre-initialization refusal.  No simulator, PX4, truth initialization, physical
motion, network publication or performance claim is allowed.

Success qualifies only the native protocol and fixed-input handoff.  It does
not establish that the full 47.7 m drift is corrected, that visual updates are
healthy, or that a future physical run will pass.
