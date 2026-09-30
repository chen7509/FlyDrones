# Gazebo Camera Phase Scheduling — Amendment 1

Date: 2026-09-27

## Trigger

The preserved D3D12 single-vehicle development run
`results/camera-phase/dev-phased-single-20260927-1` completed the PX4 mission,
landing, renderer attestation, ULog chain and cleanup, but the independent camera
observer rejected phase fidelity with `phase_error_p95_exceeded`.

The run recorded 492 matched triggers and images at exactly 10 Hz, with zero
missed, duplicate, unmatched, cross-model or queue-overflow events. Image phase
error was 8 ms at p50 and 12 ms at p95. Scheduler evidence showed trigger
publication commonly 8 ms late; the depth image header then followed one 4 ms
physics step later. This is a scheduler polling-resolution failure, not a camera
compatibility, topology, controller-safety or cleanup failure.

## Correction

The trial runner will launch the phased scheduler with a 1 ms wall polling
interval instead of its generic 10 ms default. The scheduler remains driven by
Gazebo `/clock`; wall time only controls how quickly the process notices a new
clock sample. It still publishes at most the latest due slot, never catches up
with a burst, and retains all clock-reversal, topology and connection fail-closed
checks.

## Frozen boundaries

The preregistered 4 ms physics step, 100 ms period, `0/20/40/60/80 ms` targets,
10 Hz frequency, 8 ms p95 phase limit, 8 ms spacing limit, paired schedule and
performance thresholds remain unchanged. The failed run remains preserved and
cannot be reused as smoke or formal evidence. After this correction, all
automated gates and all three development scenarios must be repeated with new
identifiers before hashes are frozen.
