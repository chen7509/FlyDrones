# Five-camera render-capacity amendment 9

## Triggering evidence

Restarted development run
`results/camera-render-capacity/dev-native-single-20260927-211802/` found all
five depth topics, but the temporary Python renderer witness did not reach its
five-stream warmup marker before the launcher deadline. Earlier preserved runs
show the same Python Transport boundary intermittently timing out or missing a
single stream. Repeating this witness in every formal slot would turn the
capacity experiment into a test of its setup helper.

## Binding correction

1. Use the frozen native C++ observer as the temporary five-stream renderer
   witness for every capacity cell, including the Python cell.
2. Native readiness for active subscribers requires at least 11 images per
   selected camera. Its atomic ready marker uses the existing
   `flydrones-camera-phase-ready-v1` schema and records per-topic width, height,
   message count, and simulation-time frequency so the unchanged renderer
   attestor can consume it.
3. The native witness always uses five subscribers, exits before the selected
   observer starts, and is never included in the scored phase summary.
4. After renderer attestation, preserve a setup summary derived from the native
   ready marker and clean stop. Then start the selected zero-, one-, or
   five-subscriber observer and perform the existing exact topology checks.
5. Use this same handoff for every cell so Python and native scored observers
   receive identical renderer setup and no simultaneous witness subscription.
6. Rebuild, rerun native CTest/parity/hash checks, freeze the new executable
   hash, and restart all Task 6 development checks with new identifiers.

No camera dimensions, rate, schedule, PX4 revision, scored duration, RTF gate,
or scored observer implementation changes.
