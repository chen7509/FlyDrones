# Five-Camera Render Capacity Amendment 39: Staged Observer Overlap

## Trigger

Amendment 38 started the temporary renderer witness and selected observer in the
same initial process batch. In the fresh native-one rerun, the scheduler proved
all five depth and trigger topics existed but timed out with
`trigger_connections_incomplete`. Both native observers received zero images.
The prior witness-first run had established all five streams, so concurrent
initial discovery is the new differentiating condition.

## Correction

Restore the initial auxiliary batch to the scheduler and temporary renderer
witness. After the witness reaches readiness and renderer attestation succeeds,
start the selected observer while the witness remains alive. Wait for selected
observer readiness, then stop the witness, validate its clean evidence, and only
then publish the selected observer PID to the launcher.

The launcher continues to require the exact frozen selected-subscriber topology
after witness shutdown. No camera, PX4, renderer, scheduler, subscriber-count,
readiness-count, scored-window, or performance threshold changes are permitted.

## Acceptance

- A regression proves renderer attestation precedes selected-observer launch.
- The same regression proves selected-observer launch and readiness precede the
  renderer witness completion signal.
- Focused tests, CTest, Ruff, Bash syntax, and diff checks pass.
- Fresh native-one and native-five development runs reach their scored windows,
  or preserve the next exact failure with complete cleanup evidence.
