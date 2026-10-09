# Opt-in Gazebo depth payload provenance

The sealed 25-second OpenVINS motion study contains RGB frames and depth metadata, but no depth pixels. It therefore cannot be replayed as an EGO obstacle observation. This stage adds a **disabled-by-default** path for future unarmed captures to retain the exact `gz.msgs.Image` depth protobuf. No old capture was altered or promoted to a teacher corpus.

The opt-in requires the existing prospective execution declaration, runtime binding and source fan-out. The callback accepts only the frozen 160×120 `R_FLOAT32` image (step 640, 76,800 data bytes), then copies the serialized protobuf without normalizing invalid pixels. The single writer creates an exclusive `depth-messages/<sample_ns>.pb`, records path, size and SHA-256 in the sensor event, and closes a write-once manifest. The verifier reconciles events, manifest and exactly the declared in-root files; fan-out checks the sidecar but passes **no depth payload** to OpenVINS. A malformed opt-in callback latches writer failure so later queued source records cannot be delivered. The preexisting callback behavior remains unchanged when the option is off. Filesystem checks reject a linked depth directory before writing; they do not claim to withstand hostile concurrent directory replacement or guarantee crash durability without `fsync`.

The source choice is the existing Gazebo Sensors 8.2.2 `gz.msgs.Image` interface, with the pinned Apache-2.0 [RGB-D sensor implementation](https://github.com/gazebosim/gz-sensors/blob/9348f9fe8a11b9d50381819f51e17e136aedab8a/src/RgbdCameraSensor.cc). The installed WSL protobuf descriptor reports `gz.msgs.Image` and `R_FLOAT32=13`. Earlier repository research recorded the upstream as nonarchived and last pushed 2026-10-02; installed package patch equivalence remains unproven. Reusing the existing callback and writer avoids a new runtime service. The extra 10 Hz byte copy and roughly 19.2 MB per 250 raw frames are prospective resource costs, not measured physical performance.

## Verification and boundaries

The RED record includes missing CLI/adapter, absent writer support, missing/changed sidecar acceptance, undeclared file/event mismatch, and pre-review linked-directory/queued-delivery failures. After fixes, the focused plus adjacent capture, fan-out, wire lifecycle and EKF2 shadow suite reported **159 passed, 1 skipped**. Changed-file Ruff and `git diff --check` passed. Independent read-only review found two Important fail-closed gaps and then a legacy-compatibility gap; all were fixed, and the reviewer confirmed no remaining Critical or Important findings. The reviewer did not run tests. No Docker container, PX4, Gazebo, OpenVINS or EGO planner was launched in this stage; the current Windows free physical memory check reported 539,428 KiB. The frozen five-camera 0.873 RTF < 0.95 result and v6 TIMESYNC failure are unchanged.

| Status | Result |
| --- | --- |
| Verified | Exact-byte sidecar/event/manifest path on synthetic messages, source refusal and tamper cases, opt-in declaration/forwarding, legacy option-off behavior, 159 adjacent tests and independent review. |
| Implemented only | Capture callback wiring and source fan-out check; no fresh physical depth frame was collected. |
| Not tested | 25-second physical capture with this option, added I/O load, calibrated metric depth, nontruth PX4 EKF2 pairing, EGO teacher trajectory, fair paired scenarios, training or flight. |
| Failed or blocked | Historical VIO/RTF/TIMESYNC failures remain; a new physical run is deferred until its own frozen profile and sufficient host resources are available. |

This path preserves input provenance only. It grants no VIO, EKF2 fusion, EGO planner, full fruit-fly policy or flight-safety qualification.
