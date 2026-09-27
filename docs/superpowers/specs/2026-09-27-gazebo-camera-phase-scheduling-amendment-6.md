# Gazebo Camera Phase Scheduling — Amendment 6

Date: 2026-09-27

## Trigger

The preserved five-vehicle development run
`results/camera-phase/dev-phased-five-20260927-4` met the frozen phase limit for
every stream (8 ms p95), had zero spacing error, landed all vehicles and released
resources. It still rejected 342 unmatched startup triggers: vehicles 1 and 2
did not emit to the observer until simulation times 22.024 s and 30.044 s,
respectively. Their missing cycles were almost entirely contiguous startup
ranges (`0–129` and `0–209`). Once each stream began, it continued at about
10 Hz through the end of the trial.

The onset times align with the launcher's sequential renderer-attestation
subscriptions. The observer currently declares readiness from topic names,
clock and scheduler metadata alone, before proving that every image subscription
has delivered data. The worker can therefore start with an inactive evidence
stream, and startup triggers are later scored as trial losses even though the
measurement window was never ready.

## Correction

The observer will require at least one actual image callback from every expected
vehicle before writing its readiness marker. Callbacks received while renderer
attestation establishes the five transport paths are retained as explicit
warm-up counts but excluded from scored trigger/image events. Once all streams
are proven, the observer chooses the next strict 100 ms epoch as
`observation_start_sim_ns`; only triggers and images mapped to targets at or
after that boundary enter the scored evidence window.

The ready marker and JSONL ready event will record the observation boundary and
per-vehicle warm-up counts. Missing streams fail closed with
`stream_readiness_timeout`; the worker cannot start. No mid-trial loss is
discarded, and all callbacks after the boundary retain the existing integrity
and phase gates.

## Frozen boundaries

The camera model, 4 ms physics step, one-step dispatch correction, 100 ms
period, `0/20/40/60/80 ms` targets, 10 Hz frequency, 8 ms phase and spacing
limits, controller, mission and failure-preservation rules remain unchanged.
The failed run remains preserved and cannot be reused as smoke or formal
evidence. All development scenarios must again use new identifiers.
