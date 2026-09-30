# Five-Camera Render Capacity Amendment 45: Do Not Score Pre-Readiness Failures

## Trigger

The directed Task 6 failure
`dev-native-fault-am44-wsl-20260929-231352/capacity-04-native-5-r1`
used the frozen native executable in `schedule-observe` mode and stopped with
exit 4 immediately after exactly five trigger records. It never produced a
scored epoch and recorded zero scored simulation seconds. Cleanup succeeded
and all shared PX4 files were restored.

Despite never reaching readiness, `run_capacity_trial` unconditionally called
the capacity scorer and wrote `score.json`. The synthesized score included an
`image_frequency_out_of_range` performance failure derived from absent scored
images. This violates the Task 6 fail-closed contract: a pre-readiness failure
is preserved as execution evidence but is not a measured capacity result.

## Root cause

The trial finalization path always summarizes and scores after cleanup. It does
not distinguish a completed scored window from startup/readiness failure.

## Correction

Continue writing the immutable manifest and diagnostic summary for every
failure. Call `score_capacity_run` and write `score.json` only when a scored
window completed and `scored_duration_sim_s` is positive. Return `score: null`
for unscored trials, and make the CLI return its existing nonzero status for a
null score.

This changes no camera, scheduler, PX4, renderer, timing, resource, or
performance threshold. It does not hide a failed scheduled campaign slot; the
manifest remains rejected and the missing score keeps the slot incomplete.

## Acceptance

- An observer/readiness failure returns `score: null`, preserves manifest and
  summary, and creates no `score.json` or `scored-epoch.json`.
- Normal completed windows still write and return their exact score.
- The directed live rerun stops after five trigger records, has native exit 4,
  has no scored epoch or score, cleans all owned processes, and restores shared
  files.
- The native-one and native-five development checks are rerun under new IDs
  after this correction.
