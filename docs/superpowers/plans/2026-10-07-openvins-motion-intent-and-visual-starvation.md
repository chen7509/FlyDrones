# OpenVINS motion-intent and visual-starvation plan

- [x] Add failing tests for truth-free motion intent, session/reset/clock failures and actuation-before-ack refusal.
- [x] Implement the Python motion-intent evidence gate without changing OpenVINS or physical capture code.
- [x] Add failing tests for immutable PPM/config/log validation and an external corner/translation proxy.
- [x] Run the read-only diagnostic on sealed `study-v21/capture-v1` and retain uncertainty boundaries.
- [x] Run focused/full regression, update the report, seal evidence, commit, push and update PR 65.
