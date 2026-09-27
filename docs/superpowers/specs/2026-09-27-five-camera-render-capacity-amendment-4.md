# Five-camera render-capacity amendment 4

## Triggering evidence

Development run `results/camera-render-capacity/dev-native-single-20260927-203933/` completed four of five temporary CLI depth captures at 160x120 and approximately 10 Hz, while vehicle 1 timed out. All follow-up `gz topic -f` calls timed out. The renderer and four streams were healthy, but sequential short-lived CLI subscribers are not a reliable five-stream readiness mechanism for triggered cameras.

## Binding correction

1. In capacity mode, launch the existing Python five-camera phase probe as a temporary renderer witness. It subscribes to all five image and trigger streams concurrently, uses the unchanged scheduler epoch, and requires 11 images per vehicle before writing the established `flydrones-camera-phase-ready-v1` marker.
2. Feed that marker to the existing renderer attestor. After attestation, signal the temporary probe to close and require a successful exit before exact capacity subscriber topology is measured.
3. Keep the selected capacity observer running throughout setup. Its data before the scored epoch is warmup only. The temporary Python witness is never used for the scored phase summary.
4. Preserve the temporary witness log, summary, and ready marker as setup evidence. Restart all Task 6 development checks with new identifiers.

No scored observer, scheduler timing, performance threshold, sensor configuration, PX4 revision, or trial duration changes.
