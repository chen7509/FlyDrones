# Five-Camera Render Capacity Amendment 41: Permanent Subscriber Ownership

## Trigger

The subscription-barrier native-one rerun reached the complete scored window
with accepted PX4, renderer, topology, cleanup, and restoration evidence. The
selected observer warmed up while the witness remained active, but after the
first witness connection exited it received no scored-window images: 301 scored
triggers and zero images. This proves that preserving a later second subscriber
is insufficient on this Gazebo runtime.

## Correction

Start the selected observer first and prove its frozen selected image-subscriber
topology. Then start the temporary five-camera witness and prove the combined
overlap topology. Start the scheduler only after both barriers, so the permanent
selected connection owns the stream before the temporary witness joins.

For the native selected observer, disable trigger-topic observation. Formal
phase scoring already uses the authoritative scheduler trigger log, and the
native `trigger-received` records are discarded by the collector. Removing this
unused subscription prevents the observer from satisfying or perturbing the
camera sensor's trigger connection gate.

After attestation and selected readiness, stop the witness and retain the
original selected image connection. No camera, PX4, renderer, scheduler,
subscriber-count, readiness-count, scored-window, or performance threshold
changes are permitted.

## Acceptance

- A regression proves native selected observers disable trigger observation.
- A regression proves selected-subscriber discovery precedes witness discovery,
  overlap discovery, and scheduler start.
- Focused tests, CTest, Ruff, Bash syntax, and diff checks pass.
- Fresh native-one and native-five development runs reach their scored windows,
  or preserve the next exact failure with complete cleanup evidence.
