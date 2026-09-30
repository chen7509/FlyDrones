# Five-Camera Render Capacity Amendment 38: Overlap Observer Handoff

## Trigger

The first native five-subscriber development run completed the PX4 platform
gate and temporary renderer attestation, but the selected observer timed out
before readiness. The temporary witness received 11 images from every vehicle.
After the witness exited, the selected observer received 735 images from each
of vehicles 0, 1, and 2, while vehicles 3 and 4 received zero images even though
all five trigger streams continued. Cleanup and shared-file restoration passed.

This isolates the defect to the replacement subscription handoff. Destroying
all five temporary Gazebo Transport subscriptions before creating the five
selected subscriptions leaves two streams disconnected for the entire
readiness window on this runtime.

## Correction

Start the scheduler, temporary renderer witness, and selected observer together
after the PX4 platform gate. Keep the renderer attestation based on the temporary
witness. After attestation, stop only the witness, retain the already-warmed
selected observer, and publish its PID only after its own readiness marker.

The existing pre-score topic introspection remains authoritative: it must prove
that the temporary witness has disappeared and that the selected observer has
exactly the frozen subscriber topology before the scored window begins.

No camera, PX4, renderer, scheduler, subscriber-count, readiness-count,
scored-window, or performance threshold changes are permitted.

## Acceptance

- A regression proves the selected observer belongs to the initial capacity
  auxiliary process set alongside the scheduler and renderer witness.
- The backend does not create a replacement observer after witness shutdown.
- Focused tests, CTest, Ruff, Bash syntax, and diff checks pass.
- Fresh native-one and native-five development runs preserve exact subscriber
  topology and reach their scored windows, or preserve the next exact failure
  with complete cleanup evidence.
