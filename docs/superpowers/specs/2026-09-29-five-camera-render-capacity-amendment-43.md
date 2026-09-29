# Five-Camera Render Capacity Amendment 43: Single-Process Warmup Transition

## Trigger

The final native-one rerun preserved a healthy selected vehicle-0 stream with
745 images, but the temporary five-camera witness received images only from
vehicles 0, 3, and 4. Vehicles 1 and 2 had discovered subscriber endpoints yet
delivered no images for the full readiness window. Earlier runs failed with
different missing subsets. This proves that cross-process Gazebo image fanout is
not a stable renderer-attestation mechanism on this runtime.

## Correction

Extend the native observer with a single-process warmup transition. It initially
subscribes to all five depth topics, records the existing 11-frame renderer
attestation marker, then waits for an explicit release marker. For cells with
zero or one selected subscriber it unsubscribes the unselected topics in place,
writes the selected readiness marker, and continues scoring without replacing
the process or retained selected connection. Five-subscriber cells keep all five
subscriptions and proceed directly.

The runner must prove the five warmup subscriptions before starting the
scheduler, wait for renderer attestation, signal the transition, and prove the
exact frozen selected topology before publishing the observer PID. Python-five
continues to use its selected five-camera observer directly.

No camera, PX4, renderer, scheduler, subscriber-count, readiness-count,
scored-window, or performance threshold changes are permitted.

## Acceptance

- Native commands carry five warmup subscribers, a distinct attestation marker,
  and an explicit release marker.
- The native observer rejects invalid selected/warmup count combinations,
  requires 11 images on every warmup stream, and unsubscribes only unselected
  image topics after release.
- The runner proves five warmup subscribers and the post-release selected
  topology without starting a second native observer.
- Focused tests, native CTest/parity, Ruff, Bash syntax, and diff checks pass.
- Fresh native-one and native-five development runs reach their scored windows,
  or preserve the next exact failure with complete cleanup evidence.
