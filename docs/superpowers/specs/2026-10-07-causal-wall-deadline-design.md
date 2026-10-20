# Causal wall-deadline semantics

## Problem

The immutable `study-v8/capture-v1` attempt reached Gazebo, PX4 and the pinned OpenVINS process, then failed at simulation time 10 ms. CameraInfo arrived 227,335,041 ns before RGB. A strictly later IMU arrived 948,721 ns after RGB and 41,370,365 ns before the failure latch, but the writer did not process it until 906,445 ns after failure. `ShadowInput.on_record()` called `CausalInput.tick(time.monotonic_ns())` after processing RGB, so CameraInfo age included callback, recording and fan-out service time and reached 269,654,127 ns. The fixed development limit is 250,000,000 ns.

The original causal-input specification defines the consumer watermark as the maximum **source arrival already seen**. `CausalInput.accept()` already advances that watermark and expires stale pending records. The explicit `tick()` exists so a separate owner can prove genuine source silence without extrapolating simulation time. It was not specified as a charge for time spent serving one accepted record.

## Contract

Keep all limits unchanged: eight pending RGB and CameraInfo records, 250 ms pending source-arrival wait, 200 ms image-to-latest-IMU sample lag, 4 ms IMU gap, 2 s online source watchdog and 2 s native transport deadline. Rejection remains latched. No event reordering, old-frame repetition, future look-ahead, reset synthesis, quality claim, fusion permission or truth input is allowed.

`ShadowInput.on_record()` must not advance the causal wall watermark to post-processing time. It submits records in the writer's exact FIFO order; `CausalInput.accept()` advances the watermark from each record's captured callback arrival. A later source record more than 250 ms after a pending record still fails during `accept()`. The public `CausalInput.tick()` remains unchanged and retains the exact-boundary/+1 ns silent-source refusal behavior. `CaptureWriter` invokes an idle callback from its single owner thread only after a timed queue wait and a locked recheck prove that the FIFO is empty. This callback forwards the explicit tick through the fan-out; a refusal is journaled, latched and blocks later pre-step force. Queued records are consumed before any idle tick.

This change does not make processing unbounded. Native write/ack remains bounded independently, fan-out retains its per-source 2 s limit, and `SourceWatchdog` retains startup and operational source-loss limits. The change only prevents local work on one FIFO record from being mislabeled as absence of a later source record that is already queued.

## Evidence and validation

Add a deterministic regression using the exact retained `study-v8` arrival and post-processing clocks. Before the fix it must latch `pending input exceeded wall wait` on RGB. After the fix, RGB remains pending and the already-arrived 4 ms IMU releases the 2 ms camera once; the frozen 250 ms value is unchanged. Add a second online-adapter case where the next source arrival itself crosses 250 ms; it must still latch the same refusal. Existing direct `tick()` boundary tests must continue to prove genuine silent-source expiry.

Run the focused causal/online/fan-out tests and full regression. Produce a fixed-input diagnostic and immutable evidence archive. Do not start PX4, Gazebo, OpenVINS, training or another physical run in this stage. A later physical candidate requires a separately frozen and audited package after this semantic correction is reviewed.
