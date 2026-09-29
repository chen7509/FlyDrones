# Five-Camera Render Capacity Amendment 40: Subscription Discovery Barriers

## Trigger

The staged-overlap native-one rerun preserved all PX4 platform evidence but the
temporary witness received zero images. The scheduler proved that all five
depth and trigger topics existed, then timed out with
`trigger_connections_incomplete` and published zero triggers. This shows that
starting the scheduler and witness together still races Gazebo Transport
subscriber discovery.

## Correction

After the PX4 platform gate, start only the renderer witness and wait until
Gazebo topic introspection proves exactly one image subscriber on every depth
topic. Start the scheduler only after that barrier. After renderer attestation,
start the selected observer and prove the exact overlap topology before waiting
for its readiness. The overlap expectation is one witness subscriber on every
topic plus one selected subscriber on each selected topic. Stop the witness only
after the selected observer is ready.

Persist both discovery snapshots in the development run. No camera, PX4,
renderer, scheduler, subscriber-count, readiness-count, scored-window, or
performance threshold changes are permitted.

## Acceptance

- A regression proves the initial five-witness subscriber barrier precedes the
  scheduler start.
- A regression proves overlap subscriber expectations for 0, 1, and 5 selected
  subscribers.
- Focused tests, CTest, Ruff, Bash syntax, and diff checks pass.
- Fresh native-one and native-five development runs reach their scored windows,
  or preserve the next exact failure with complete cleanup evidence.
