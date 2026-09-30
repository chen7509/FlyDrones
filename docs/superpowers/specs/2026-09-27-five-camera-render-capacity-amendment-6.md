# Five-camera render-capacity amendment 6

## Triggering evidence

Restarted development run
`results/camera-render-capacity/dev-native-single-20260927-211023/` proved five
rendered streams at approximately 10 Hz and produced an accepted renderer
attestation, but the temporary renderer witness exited 2 because one setup-only
phase p95 was 8.2 ms. The witness was therefore applying the formal scored
phase threshold before the selected observer and scored epoch existed.

The same run also recorded `UNKNOWN_PIXEL_FORMAT` from the Python witness. The
Gazebo protobuf exposes `fields_by_name` and `values_by_number` through native
descriptor maps which do not satisfy `collections.abc.Mapping`; the guarded
lookup skipped a valid `R_FLOAT32` enum.

## Binding correction

1. Treat the temporary renderer witness as setup evidence only. Accept exit 0,
   or exit 2 only when its summary has five complete 9.5..10.5 Hz streams and
   every integrity counter is zero. Only phase/spacing threshold reasons may be
   ignored at this setup stage.
2. Keep the formal 8 ms phase and spacing thresholds unchanged for the selected
   observer inside the scored 30-second window.
3. Read Python protobuf pixel format names directly from the field enum
   descriptor. Unknown or missing enum values remain
   `UNKNOWN_PIXEL_FORMAT` and fail the scored metadata gate.
4. Restart all Task 6 development checks with new identifiers and retain this
   failed run.

No renderer, camera, scheduler, PX4, scored-duration, or performance threshold
changes.
