# Gazebo Camera Phase Scheduling — Amendment 8

Date: 2026-09-27

## Trigger

The preserved five-vehicle development run
`results/camera-phase/dev-phased-five-20260927-6` passed the complete camera
phase contract: all five streams ran at 10 Hz, every p95 phase error was 8 ms,
adjacent median spacing error was zero, and no trigger or image was unmatched.
It nevertheless failed the existing mission-readiness gate before any autonomous
policy call.

Vehicles 0–2 accepted arm and takeoff and physically climbed 1.17–1.25 m, but
the 12 s wall-clock climb window ended while PX4 still reported a transitional
landed state. Vehicles 3–4 received `MAV_RESULT_TEMPORARILY_REJECTED` for their
first arm command while their PX4 console still reported preflight health
failures. Their takeoff events also showed that the controller had labeled
`preflight-ready` before either a known disarmed or known landed state existed.

## Correction

Before the first arm command, the MAVLink takeoff transaction will wait for
fresh PX4 status that explicitly reports both disarmed and landed. An arm ACK
with `MAV_RESULT_TEMPORARILY_REJECTED` may be retried exactly once, and only
after a newer status sample again proves disarmed and landed. The first rejected
ACK and the retry decision remain in the takeoff event evidence. All other arm
rejections fail immediately, and a missing or ambiguous safe state prevents the
retry.

This implements the already specified bounded retry rule at the transaction
boundary and prevents workers from arming during incomplete PX4 cold-start
health initialization. Tests will prove the success, persistent-rejection,
permanent-rejection and unsafe-state cases.

## Frozen boundaries

The 12 s climb deadline, 0.5 m gain, three fresh samples, PX4 landed-state
requirement, command timeouts, recovery behavior, policy, mission, vehicle,
camera, 4 ms physics step, 100 ms trigger period, phase targets and all formal
RTF and evidence gates remain unchanged. The failed run remains preserved and
cannot be reused as smoke or formal evidence. All three development scenarios
must be repeated with new identifiers after this correction.
