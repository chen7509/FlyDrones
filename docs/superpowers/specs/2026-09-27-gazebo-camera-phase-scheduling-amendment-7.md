# Gazebo Camera Phase Scheduling — Amendment 7

Date: 2026-09-27

## Trigger

The preserved five-vehicle run
`results/camera-phase/dev-phased-five-20260927-5` required an actual first image
from every stream before readiness. Four streams then remained continuous, but
vehicle 2 produced one warm-up image and later had a 21.696 s scored gap. It
finished with 129 images versus 543–544 for the other vehicles, causing 415
unmatched triggers and an out-of-range mean frequency. All measured stream
phases remained at or below the frozen 8 ms p95 limit.

The affected stream's activity follows temporary external renderer-attestation
subscriptions. A single Python Gazebo Transport `Node` currently owns the clock,
five image and five trigger subscriptions. The evidence shows that a successful
`subscribe` return and one callback do not guarantee every publisher continues
to see that multiplexed node as a live image connection after another subscriber
disconnects.

## Correction

The observer will retain one primary node for topology and `/clock`, plus one
dedicated Transport node per vehicle for that vehicle's image and trigger
subscriptions. Every node, callback and `(node, topic)` ownership pair remains
strongly referenced through cleanup. Each subscription is explicitly removed
from its owning node before references are released.

This isolates transport connection state per camera while leaving event format,
warm-up/readiness, scoring, camera configuration, scheduler, controller and
safety behavior unchanged. A test will require distinct per-vehicle subscription
nodes. The complete development suite must again use new identifiers.

## Frozen boundaries

The 4 ms physics step, dispatch correction, observation boundary, 100 ms period,
`0/20/40/60/80 ms` targets, 10 Hz frequency, 8 ms phase and spacing limits and
all mission and failure gates remain unchanged. The failed run remains preserved
and cannot be reused as smoke or formal evidence.
