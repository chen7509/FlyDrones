# Five-Camera Render Capacity Amendment 26: Selected Observer Readiness

## Trigger

The first statically preloaded five-vehicle native single-subscriber run completed
with valid PX4, sensor-topology, renderer-witness, ULog, and cleanup evidence. Its
only frozen performance failure was real-time factor below 0.95. After correcting
the temporary development config hash subset, an unchanged rerun failed before
readiness because the selected native observer retained its 30-second default and
received no images during that window. The independent renderer witness and the
camera scheduler already allow 150 seconds for the same slow sequential PX4 and
Gazebo startup.

## Correction

Pass `--readiness-timeout-s 150` explicitly to the selected native observer. Keep
the renderer witness, scheduler, warmup, campaign duration, frozen thresholds,
failure preservation, and evidence acceptance rules unchanged. Recalculate the
frozen source hashes and rerun the native single-subscriber development cell.

## Acceptance

- A focused test proves both the scheduler topology timeout and selected native
  observer readiness timeout are 150 seconds.
- The targeted render-capacity suite and Ruff pass.
- The rerun either produces accepted evidence or preserves a new concrete failure
  without weakening the frozen contract.
