# Five-Camera Render Capacity Amendment 37: Observer Handoff Deadline

## Trigger

The settled warmup correction passed renderer attestation, including D3D12,
NVIDIA, five depth streams, dimensions, and frequency. The selected native
single-camera observer then remained alive but had not accumulated its readiness
images before the launcher failed with `capacity observer PID file is missing
after handoff`.

The observer command correctly permits 150 seconds for slow-simulation readiness,
but the launcher still uses its 45-second default camera-auxiliary timeout. The
backend writes the observer PID only after the observer's ready marker, so the
launcher can expire 105 seconds before the observer's own valid deadline.

## Correction

For capacity trials, export `FLYDRONES_CAMERA_AUX_TIMEOUT_S` as the larger of the
frozen trial readiness timeout and 150 seconds. Allow the backend's selected
observer marker wait up to the same 150-second observer limit. Keep PID publication
after the observer readiness marker so the launcher never treats an unsubscribed
process as the selected observer.

No camera, PX4, renderer, scheduler, subscriber, scored-window, or performance
threshold changes are permitted.

## Acceptance

- A regression proves the capacity environment exports at least 150 seconds even
  when a smaller unit-test readiness timeout is supplied.
- The selected observer backend wait is capped at 150 seconds instead of 90.
- Focused tests, Ruff, Bash syntax, and diff checks pass.
- A fresh native single-subscriber development run reaches capacity readiness and
  the unchanged 30-second scored simulation window, or preserves the next exact
  failure with complete cleanup evidence.
