# Generated RX queue-age refusal contract

Continue the full user goal under blanket plan approval. Previous turn progressed: producer2193e02/2c64fda/f279bd8 published one8-packet observation; no new packet or simulation is authorized by this plan. Current host~2.1GiB remains belowEGO2500MiB/physical-fullMaleCNS4GiB. This feature adds an opt-in refusal boundary to existing receiver data, not new clock/source/flight eligibility.

## Current problem and primary research

DatagramReceiver validates recvmsg duration and decode-time deadlines, but generatedRX metadata is stored unmapped. An increasing series of old queued packets can have current callback clocks and pass its timing checks. `LOCAL_POSITION_NED` boot time is not a timestamp_sample or hostclock. KeepPX4state100ms/fault/reset/camera checks separate from host packetqueue2s.

Reuse fixedLinuxv6.6timekeeping, Python3.12.3pytime.c (PSF), Linuxclock_gettime man-page and existing exactKernelRX NEW65/flags24; no dependency/clock setting/compile/model/physics. Kernel/Python maintenance and installedsource equivalence not newlyproved. Realtime may step, monotonic has a different origin and excludes suspend; a numeric subtraction across domains is rejected. Reject usingNS metadata because its historical read-time fallback could hide a queue. No unrelated estimator paper qualifies these clock semantics.

## Conditional interval model and hard limits

Observe monotonic m0, kernel profile realtime r, monotonic m1. For the declared constant-offset model O=R-M, each sample constrains O to[r-m1,r-m0]. Intersect all observed intervals. Empty intersections, regressions, bool/float/out-of-range clocks, >=2s sample spans and capacity exhaustion latch failure. No midpoint rounding, inferredfrequency, TTL increase or guessed offset. Initial anchor is captured after existing profile.enable_before_bind but before socket.bind, with prepared unboundsocket/FD/options checked; already-bound/unknownsocket cannot acquire retroactive age provenance. The sampler binds to exactly one receiver, kernelobject, clockcallable and start_ns; tags/sessionlabels are not authentication.

For generated timestamp K, conditional monotonic interval is[K-O_hi,K-O_lo]. Refuse K before initial realtime anchor, future/overflow/negative interval, or any possible future time at final check. Age interval at N is[N-(K-O_lo),N-(K-O_hi)]; require lower>=0 and upper<2,000,000,000ns. Strict boundary matches existing2s timeout. Missing metadata retains current strictparser refusal. Refresh age at final poll return after all journals/checks; an old packet cannot be revived by recently increasingdecode timestamps. Once a packet is issued this class cannot revoke it; callers must retain existing final-send guards.

IMPORTANT: intersected reads establish only observed model consistency. They cannot exclude an unobserved clockstep-and-return, authenticate a process, prove clockimplementation or qualify continuousmapping. All clock_mapping_qualified/source/network/fusion/training flags remainfalse. Passing this extra numerical policy never authorizes control or proves PX4sample freshness. A violation can add refusal; unknown domains cannot grant new authority. This is not hardware calibration.

## Integration

New tools/benchmark/kernel_queue_age.py owns bounded anchor/model evidence and failure state; exactKernelRX only. DatagramReceiver receives optional kernel_queue_age, verifies same prepared profile/clock/start and binds once; defaults andNS path unchanged. Sampling wraps the existing pre/post realtime observations (includingEAGAIN), preserving originalrawdata before clock callbacks. Add anchors to existing receive_return and model diagnostics to kernel_timestamp_observed, not a fourthregular event, preserving8192 event budget and originalload/cadence. ReceivedDatagram gets optional modeled_kernel_age_upper_ns without replacingreceived_ns or kernel_received_realtime_ns. poll/check failures latch both scopes as appropriate; the model remains non-controlling/unqualified. No livewire profile activation in this stage.

Sampler singlewriter/reentry/concurrency fails closed; evidence copies cannot mutate state. It has no journal or transport callback and cannot preempt suppliedclock calls; existing outer supervisor remains required. Max32768anchors, integer int64 math, sourcehighwaters andinitialanchor remain after failure. Clock callback errors retain successfulrawrecv data through existing refusaljournal; final journal delays count against age.

Final-send clarification before publication: in the opt-in mode, after issuing a packet, `receiver.check(packet)` requires the exact latest issued object and reassesses its age. No-argument/old/copied/other-receiver packet rejects; fresh later data cannot qualify an older cached packet. Defaults retain no-argumentcheck. This is a modeled refusal/identity policy, not process authentication. A queue-age model fault also prevents restoration reads; no reset/unlatch to obtain a positive rollback claim. Existing unconfigured restoration remains unchanged.

## Verification and old-data use

Fake preparedsockets/clocks: fresh/exact2s/stale initial and increasingbacklog; before-session/future/overflow; offset forward/backstep evenwhenrealtime stillincreases; spanuncertainty, missing RXmetadata, drift/descriptor/shared-clock/session mismatch, NS/subclass拒绝; EAGAINclock sampling; journal delay/reentry/callback failure; capacity, single-bind andimmutableevidence; finalage mustincludejournal delay. Preserve meaningfulRED and unaffected defaults.

Optional fixed-read numerical audit uses only the8 previouslysaved raw observations, no network replay. Derive realclock brackets from frozen execution ordering:attempt_m→attempt_R→send_start_m, recv_start_m→recv_start_R→recv_return_m. Their wide spans includejournal/processing. Report everypacket and all unavailable/model inconsistent cases. This is retrospective model arithmetic, NOT a historical before-bind sampler or newruntimebinding; do not fabricate it. All qualification staysfalse and prior failed bursts unchanged.

After focused/affected checks, independent review, source/hash/run/evidence report/seal, pushpersonal/updatePR65/automation. Fullgoalactive; real source/sample/reset/health/camera andresource-gated actualupstream builds/single→5→20/hardware work remain.
