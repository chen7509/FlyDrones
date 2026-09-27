# Five-camera render-capacity amendment 5

## Triggering evidence

Development run `results/camera-render-capacity/dev-native-single-20260927-210043/`
completed its 30-second scored window, preserved five ULogs, verified one exact
depth subscriber, and cleaned up successfully. Its generated phase summary was
nevertheless invalid: it mixed scheduler triggers emitted before the native
observer handoff with scored images, and it used the observer's later local
epoch instead of the unchanged scheduler epoch. This produced 67 unmatched
triggers and `target_offsets_invalid`. The summary also omitted the image
width, height, pixel format, and scorer-facing frequency field even though the
native JSONL records contained them.

## Binding correction

1. Build the scored phase summary only from trigger and image samples whose
   scheduled camera target lies inside the recorded half-open simulation-time
   window `[start_sim_ns, end_sim_ns)`.
2. Use the scheduler-ready epoch as the single phase epoch. Replace the
   observer-local lifecycle epoch before calling the shared phase summarizer;
   do not alter measured image timestamps or scheduler trigger timestamps.
3. Retain exactly one start, topology, ready, and stop record so the existing
   lifecycle checks remain fail-closed.
4. Enrich every selected vehicle summary from scored native/Python image facts:
   `frequency_hz`, `width`, `height`, and `format`. Mixed or missing metadata
   remains invalid and cannot be inferred from the configured model.
5. Make a successful trial CLI exit depend on `score_capacity_run`, so an
   evidence or performance rejection cannot be reported as a successful slot.
6. Restart Task 6 development checks with new identifiers. Preserve the prior
   run as evidence of the defect.

No camera rate, resolution, scheduler dispatch, PX4 revision, RTF threshold,
scored duration, or subscriber topology changes.
