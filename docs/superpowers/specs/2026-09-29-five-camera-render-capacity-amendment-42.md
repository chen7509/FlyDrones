# Five-Camera Render Capacity Amendment 42: Reuse Full Selected Observer

## Trigger

The permanent-subscriber native-five run proved both `1/1/1/1/1` selected and
`2/2/2/2/2` overlap image-subscriber topologies, but both observers received
zero images. The scheduler timed out with `trigger_connections_incomplete` and
zero triggers. The native-one run passed with overlap only on vehicle 0, so the
all-topic duplicate subscription is the differentiating condition.

## Correction

When the selected cell already subscribes to all five depth topics, use its own
11-frame readiness marker for renderer attestation and do not create a temporary
five-camera witness. The selected observer remains the only image subscriber on
every topic for discovery, attestation, and scoring.

Cells with zero or one selected subscriber retain the temporary five-camera
witness because their selected observer cannot attest all five rendered streams.
No camera, PX4, renderer, scheduler, subscriber-count, readiness-count,
scored-window, or performance threshold changes are permitted.

## Acceptance

- Regressions prove five-subscriber cells omit the temporary witness and use the
  selected readiness marker for renderer attestation.
- Regressions prove zero/one-subscriber cells retain the temporary witness.
- Focused tests, CTest, Ruff, Bash syntax, and diff checks pass.
- Fresh native-one and native-five development runs reach their scored windows,
  or preserve the next exact failure with complete cleanup evidence.
