# Gazebo Camera Phase Scheduling — Amendment 4

Date: 2026-09-27

## Trigger

The preserved post-compensation single-vehicle development run
`results/camera-phase/dev-phased-single-20260927-4` completed its PX4 mission,
proved the takeoff chain, landed, restored shared files and released owned
resources. Its image-header phase p50 and p95 were both 8 ms, at the frozen
limit, with 491 images at 10 Hz and no scheduler miss or callback overflow.

The observer nevertheless rejected the run for one unmatched final trigger.
The scheduler published that trigger immediately before the worker wrote the
trial completion marker. The observer drained the trigger callback, saw an empty
callback queue plus the completion marker, and stopped before the triggered
camera's final image callback arrived. This is an observer shutdown race; it is
not a frequency, phase, renderer, controller or cleanup failure.

## Correction

After observing the completion marker, the phase observer will remain alive for
a fixed one-second wall-time drain window. The window restarts whenever a new
callback event arrives. The observer may finish only when the queue is empty and
the full quiet window has elapsed. Its existing overall duration timeout remains
authoritative and all late callbacks continue to be scored normally.

The drain duration is recorded in the observer start event and exposed as a CLI
option for deterministic tests. Production trials use the fixed one-second
value. The complete development suite must again use new identifiers.

## Frozen boundaries

The 4 ms physics step, one-step dispatch correction, 100 ms period,
`0/20/40/60/80 ms` image targets, 10 Hz frequency, 8 ms phase and spacing
limits, pairing rules and all failure-preservation rules remain unchanged. The
failed run remains preserved and cannot be reused as smoke or formal evidence.
