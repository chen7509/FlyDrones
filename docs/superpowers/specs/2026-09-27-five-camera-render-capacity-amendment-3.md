# Five-camera render-capacity amendment 3

## Triggering evidence

Corrected development run `results/camera-render-capacity/dev-native-single-20260927-203546/` reached the temporary five-topic renderer probe, then the runner timed out at 45 seconds while that probe was still active. The probe is intentionally sequential and allows up to 15 seconds for message capture plus 10 seconds for frequency evidence per topic, so its defined worst-case setup time exceeds the runner deadline. The timeout also left the launcher process group alive after its registered PX4/Gazebo children were cleaned. Artifact copying stopped at the first unavailable renderer file and therefore omitted otherwise available failure evidence.

## Binding correction

1. Increase only the pre-score readiness deadline to 180 wall seconds. The scored window remains exactly 30 simulation seconds with a 120 wall-second timeout.
2. Collection must close a still-running launcher process group, then record its exit code, before the ownership-safe stopper runs.
3. Artifact preservation must copy every available required artifact and ULog, report each missing item, and never discard available evidence because another artifact is absent.
4. Restart all Task 6 development checks with new identifiers after tests and frozen hashes are updated.

No scoring threshold, camera rate, phase schedule, vehicle state, native implementation, or PX4 revision changes.
