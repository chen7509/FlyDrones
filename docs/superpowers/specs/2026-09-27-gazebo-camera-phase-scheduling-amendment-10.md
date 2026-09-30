# Gazebo Camera Phase Scheduling — Amendment 10

Date: 2026-09-27

## Trigger

The preserved run `results/camera-phase/dev-phased-five-20260927-8` proved that
Amendment 9 removed stream disruption: all five cameras produced continuous
10 Hz evidence, every p95 phase error was 8 ms, and no trigger or image was
unmatched. The mission gate still failed because the unchanged 12 s climb
window contained only about 5.35 s of simulation time (RTF 0.445–0.448).

Inspection found one remaining synchronous Windows-mounted-file write path.
The phase scheduler flushes its JSONL file after every published trigger. A
five-vehicle schedule publishes 50 triggers per simulation second, so this
hot path continues to block the scheduler/Python/Gazebo process set even though
the observer was already changed to bounded flushing.

## Correction

The scheduler JSONL writer will use the same bounded buffering contract as the
observer: flush every 250 ms wall time and at topology, readiness, failure and
shutdown boundaries. Completed logs are flushed before scoring; queue and
lifecycle integrity rules are unchanged. Production command construction pins
the 250 ms interval and tests reject invalid values.

## Frozen boundaries

The camera streams, scheduler state machine, trigger times, 4 ms dispatch
correction, 100 ms period, phase targets, 10 Hz frequency, 8 ms phase/spacing
limits, 12 s climb deadline, flight safety behavior, policy, mission, RTF gate
and evidence acceptance remain unchanged. The failed run is preserved and all
three development scenarios must be repeated with new identifiers.
