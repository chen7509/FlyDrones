# Five-Camera Render Capacity Amendment 36: Settled Warmup Frequency

## Trigger

After the flight-platform-first correction, all 20 flight-sensor sources, all 20
PX4 bridge connections, and all five EKF2 health gates passed. D3D12, the NVIDIA
adapter, mapped renderer libraries, five depth topics, and 160 x 120 dimensions
also passed. Renderer attestation was rejected only because its 11-frame warmup
frequency used the first activation frame as the interval origin.

Preserved native events show one or two subscription-activation images followed
by the required 100 ms cadence. For vehicle 0 the first timestamps are
`10.068, 10.072, 10.104, 10.204, ...` seconds; for vehicle 4 they are
`10.068, 10.084, 10.184, 10.284, ...`. The current first-to-last estimator reports
11.75 Hz and 10.92 Hz even though the settled intervals are 10 Hz.

## Correction

Keep collecting at least 11 warmup images per selected stream, but calculate the
temporary readiness-marker frequency from the third image through the latest
image. This deterministically excludes at most two subscription-activation frames
and still requires at least eight settled intervals. Record the original first
timestamp and the settled timestamp in the native observation state; do not
change image events or formal scoring.

The renderer attestation threshold remains 9.5..10.5 Hz. Camera dimensions,
format, scheduler, phase offsets, scored-window arithmetic, subscriber cells, and
all integrity gates remain unchanged.

## Acceptance

- A native unit regression proves two activation samples followed by 100 ms
  intervals produce exactly 10 Hz in the readiness marker.
- The existing 11-frame, 10 Hz marker fixture remains 10 Hz.
- Native CTest, cross-language parity, focused Python tests, Ruff, Bash syntax,
  and diff checks pass.
- A fresh native single-subscriber development run passes renderer attestation
  and continues to the unchanged selected-observer and 30-second scored gates.
