# Gazebo Camera Phase Scheduling — Amendment 9

Date: 2026-09-27

## Trigger

The preserved five-vehicle run
`results/camera-phase/dev-phased-five-20260927-7` kept every measured stream at
the frozen 8 ms p95 phase limit, but it failed both the stream-integrity and
mission-readiness gates. Vehicle 2 emitted no scored images for the first
8.592 s of the observation window, leaving 87 unmatched triggers. The renderer
attester was still creating and destroying two temporary `gz topic`
subscriptions per camera after the permanent observer subscriptions existed.

The same run showed that every vehicle received only 4.91–4.96 s of simulation
time during the unchanged 12 s wall-clock climb window (RTF 0.408–0.413). The
observer synchronously flushed every image and trigger JSON line onto the
Windows-mounted result tree. At five cameras this creates about one hundred
cross-filesystem flushes per simulation second and competes directly with the
Gazebo/PX4 loop. All five vehicles physically climbed 0.77–0.86 m but correctly
failed while PX4 still reported a transitional landed state.

## Correction

The permanent phase observer becomes the sole depth-stream subscriber used for
renderer evidence. Production readiness will require at least 11 actual images
from every expected stream and will record per-topic width, height, count and
simulation-time frequency in its atomic ready marker. The launcher will pass
that marker to the renderer attester, which will validate the recorded streams
instead of running temporary `gz topic -e` and `gz topic -f` subscribers.

The JSONL writer will use bounded buffering and flush at a fixed 250 ms wall
interval, plus readiness, failure and shutdown boundaries. A crash can lose at
most the current interval; completed evidence is always flushed before scoring.
Callback queues, overflow rejection and final malformed-tail checks remain in
force.

## Frozen boundaries

No camera, vehicle, policy, controller, mission or sensor setting changes. The
12 s climb deadline, 0.5 m gain, three fresh samples, landed-state requirement,
4 ms physics step, 100 ms trigger period, `0/20/40/60/80 ms` targets, 10 Hz
frequency, 8 ms phase/spacing limits, RTF threshold and all cleanup/evidence
gates remain unchanged. The failed run is preserved and cannot be reused as
smoke or formal evidence. All three development scenarios must again use new
identifiers.
