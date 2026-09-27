# Gazebo Camera Phase Scheduling — Amendment 2

Date: 2026-09-27

## Trigger

The preserved D3D12 five-vehicle phased development run
`results/camera-phase/dev-phased-five-20260927-1` stopped before the PX4 worker
started because renderer attestation received no depth images from vehicle 1.
The independent phase observer saw the same missing stream and delayed onsets:
vehicles 3 and 4 produced immediately, vehicle 0 began later, vehicle 2 began
much later, and vehicle 1 never produced. The scheduler still recorded trigger
publication for every vehicle, with no scheduler misses, duplicate slots or
queue overflow.

The observer passed freshly-created bound methods and closure functions directly
to the Gazebo Transport Python subscription API, then retained only topic names.
Those callable objects had no Python-owned strong reference after each
`subscribe` call. A binding that retains callbacks weakly can therefore lose the
clock, image or trigger callback during garbage collection. The staggered stream
onsets also correlated with later external `gz topic` subscriptions, which is
consistent with an observer callback-lifetime failure rather than a valid camera
phase result.

## Correction

The phase observer will retain every clock, image and trigger callback object for
the complete subscription lifetime. Subscription remains fail-closed: a rejected
subscription is removed from the retained set and produces the existing failure.
The observer will release the retained references only after all topics have been
unsubscribed.

This correction changes evidence collection only. It does not change the camera
model, scheduler, controller, PX4 worker, renderer attestation or safety gates.

## Frozen boundaries

The preregistered 4 ms physics step, 100 ms period, `0/20/40/60/80 ms` targets,
10 Hz frequency, 8 ms p95 phase limit, 8 ms spacing limit, paired schedule and
performance thresholds remain unchanged. The failed five-vehicle run remains
preserved and cannot be reused as smoke or formal evidence. All three development
scenarios must be repeated with new identifiers after this correction before
input hashes are frozen.
