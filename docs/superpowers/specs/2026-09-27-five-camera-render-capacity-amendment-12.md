# Five-camera render-capacity amendment 12

## Triggering evidence

Restarted development run
`results/camera-render-capacity/dev-native-single-20260927-213331/`
completed its scored window but was evidence-invalid because the scheduler
recorded a missed vehicle-2 slot planned for 31.140 seconds and next processed
simulation time 31.168 seconds. The independent clock probe retained every
4 ms clock sample from 31.120 through 31.168 seconds, while the scheduler log
jumped from 31.124 directly to 31.168 seconds.

The scheduler callback stored only the latest clock value. Its foreground loop
performed synchronous `topic_list()` and publisher connection health calls
before dispatch. When one health call blocked while clock callbacks continued,
intermediate clock samples were overwritten and an otherwise delivered trigger
slot was classified as missed. The same run produced 300 selected images at
10.001 Hz, showing that the renderer and selected observer continued normally.

## Binding correction

1. Dispatch the frozen `TriggerSchedulerState` directly from the serialized
   `/clock` callback after readiness. Each delivered clock sample is processed
   once before a later sample can replace it.
2. Keep topology and trigger-connection health checks in the foreground loop;
   they remain fail-closed but cannot block clock-driven dispatch.
3. Serialize JSONL writes and scheduler state shared by the callback and
   foreground lifecycle loop. Callback publish, queue, or state failures must
   be relayed to the foreground and preserve a nonzero stop record.
4. Keep the 4 ms dispatch delay, no-catch-up rule for an actually missing clock
   sample, phase offsets, readiness deadlines, and all scoring thresholds
   unchanged.
5. Preserve this run, update frozen hashes, and restart all three Task 6
   development checks with new identifiers.

This is a scheduler liveness correction. It does not hide genuine clock loss:
`TriggerSchedulerState` still emits `missed` records when two delivered clock
samples span more than one due slot.
