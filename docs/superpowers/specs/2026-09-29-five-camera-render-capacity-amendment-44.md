# Five-Camera Render Capacity Amendment 44: Preserve Performance Evidence

## Trigger

The fresh native-one development run
`dev-native-single-transition-20260929-225710/capacity-02-native-1-r1`
completed its 30.016 scored simulation seconds with valid renderer, PX4, ULog,
resource, topology, shutdown, restoration, and cleanup evidence. Its measured
phase-error p95 was 8.2 ms and its RTF was 0.6234, so both are legitimate
performance failures against the frozen 8 ms and 0.95 thresholds.

The camera-phase summary correctly set `accepted: false` and reported only
`phase_error_p95_exceeded`. The capacity scorer then treated that aggregate
flag as `camera_phase_summary_rejected` evidence while also recording the
underlying performance failure. This contradicts the capacity contract and
the existing per-field scorer tests, which require threshold misses to remain
valid evidence so the campaign can classify measured capacity.

## Root cause

`score_capacity_run` uses the phase summary's aggregate `accepted` flag as an
evidence gate before independently classifying frequency, phase, spacing, and
RTF thresholds. The aggregate flag intentionally includes performance gates,
so it cannot distinguish corrupt or incomplete evidence from a valid measured
threshold miss.

## Correction

Classify the phase summary by its explicit `reasons` list. Known performance
reasons (`image_frequency_out_of_range`, `phase_error_p95_exceeded`, and
`spacing_median_error_exceeded`) do not invalidate evidence when the capacity
scorer independently reproduces each failure from the frozen numeric fields.
A rejected phase summary
with any other or malformed reason still fails closed as
`camera_phase_summary_rejected`.

No phase calculation, percentile method, camera setting, scheduler behavior,
subscriber topology, PX4 behavior, runtime threshold, or acceptance threshold
may change.

## Acceptance

- A regression reproduces a real phase summary with `accepted: false` and only
  `phase_error_p95_exceeded`; evidence remains valid and performance fails.
- Unknown, missing, or malformed rejection reasons still invalidate evidence.
- The preserved native-one artifact scores as valid evidence with the original
  8.2 ms phase and 0.6234 RTF performance failures.
- Focused and full scorer tests pass before the three Task 6 development checks
  restart under new result IDs.
