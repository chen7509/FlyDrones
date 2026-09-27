# Five-camera render-capacity amendment 8

## Triggering evidence

Restarted development run
`results/camera-render-capacity/dev-native-single-20260927-211551/` completed and
accepted the five-stream renderer witness. The launcher then failed while
reading the selected observer PID with `ValueError: invalid literal for int()
with base 10: ''`. The PID path was written with `Path.write_text`, which makes
an empty/truncated file briefly visible, and the trial wrapper wrote the same
file a second time.

## Binding correction

1. Publish observer PID files by writing a sibling temporary file and atomically
   replacing the destination.
2. Use the same atomic helper for both native handoff and the generic trial
   wrapper. Repeated publication of the same PID remains harmless and never
   exposes an empty file.
3. Keep the launcher's liveness and exact subscriber checks unchanged.
4. Restart all Task 6 development checks with new identifiers and retain the
   failed run.

No process identity, readiness, camera, PX4, scheduler, or scoring changes.
