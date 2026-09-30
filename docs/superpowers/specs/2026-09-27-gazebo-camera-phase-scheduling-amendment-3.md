# Gazebo Camera Phase Scheduling — Amendment 3

Date: 2026-09-27

## Trigger

After retaining observer callbacks, the preserved D3D12 five-vehicle phased
development run `results/camera-phase/dev-phased-five-20260927-2` produced every
stream continuously and passed renderer attestation. Each vehicle emitted about
575 images at 10 Hz; trigger/image counts matched, and missed, duplicate,
unmatched, cross-model and queue-overflow counts were all zero. All five vehicles
landed and owned resources were released.

The run still failed the frozen output-phase gate. Vehicles 0–3 had 12 ms p95
image-header phase error and vehicle 4 had 8 ms. Scheduler evidence rules out
input lateness as the cause: over 97% of trigger publications were exactly on
the planned simulation timestamp, all remaining publications were one 4 ms
physics step late, and scheduler p95 lateness was 0 ms for every vehicle. The
outliers were image headers stamped 12–16 ms before their target while the
message was received after its trigger. This identifies a loaded D3D12 render
pipeline timestamp offset, not a missed trigger or observer loss.

## Correction

The phased trial launcher will apply a fixed one-physics-step (4 ms) trigger
dispatch delay while preserving the preregistered image targets at
`0/20/40/60/80 ms`. Scheduler state will distinguish the desired image timestamp
(`planned_sim_ns`) from the dispatch deadline and will publish only when
`sim_ns >= planned_sim_ns + 4 ms`. Scheduler readiness and trigger evidence will
record the dispatch delay explicitly.

The one-step correction is fixed from the development evidence before smoke or
formal trials. It is not estimated per run, per vehicle or from future images,
and it is not available to the flight policy or safety path. The complete three
scenario development suite must be rerun with new identifiers after the change.

## Frozen boundaries

The 4 ms physics step, 100 ms image period, `0/20/40/60/80 ms` image targets,
10 Hz output frequency, 8 ms p95 phase limit, 8 ms spacing limit, paired order,
performance gates and all failure-preservation rules remain unchanged. The
failed run remains preserved and cannot be reused as smoke or formal evidence.
The correction does not change image timestamps during scoring and does not
substitute receipt time for the required image-header time.
