# First authorized communication trial and callback refusal repair

2026-10-09. Physical producer: 7766bfc. No completed communication qualification.

## Execution and retained failures

The user's instruction to start after enabling Docker was interpreted in the
immediately preceding scope: one 25-second unarmed TIMESYNC and message-interval
query/apply/restore study, with no ODOMETRY, EKF2 parameter mutation, arming,
setpoints, training or swarm expansion. Docker responded and the installed image
ID matched the pinned EGO image
`sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a`.
No container was running; no EGO planning call was made. Host free memory before
the trial was 1,015,934,976 bytes, still below the separate full-connectome
4-GiB preflight. That full-model check was not run or relaxed.

The v5 activation CLI refused before intent/dispatch. Its execution declaration
had identical SHA256, inode, mode, size, mtime and ctime but WSL device identity
changed from 68 to 115. `activation-cli-output.txt` and
`execution-identity-diagnosis.json` preserve that observation. No explanation for
the mount lifecycle beyond that measured identity change is asserted.

An independent v6 preparation retained v5 and all previous sealed evidence.
Its generator differs from v5 by exactly three version-name substitutions;
production code was unchanged. It revalidated the installed selection, 610
declared files, 82 static sources, 8 XML documents, 46 references, 40 read-only
native queries and five mutation refusals. The simulation seed, endpoint,
limits, profiles and command were compared to v5, differing only in versioned
output/input paths. No model or safety threshold was changed.

The selected v6 manifest SHA256 is
`b1e254e98b26c2183741a2a0f8db91d92de34d165cced42918e8c8254693d9d2`.
The explicit executor recorded one activation request, one dispatch and one
terminal completion. The declared 25s / 1ms physics / 250Hz raw IMU / 10Hz
160x120 RGB-D workload was requested, but **not completed**.

## Observed failure

The retained wire coordinator reports `bootstrap progress timeout`, followed by
an exception from the stopped PostUpdate wrapper. The native log contains
`pybind11::error_already_set`; supervisor worker exit is -6 (SIGABRT).
This is not an algorithm accuracy or training-loss result.

- Three clock callbacks and three fresh-reference records reach sim 3ms.
- The source journal contains one IMU, one CameraInfo and one depth record.
- One actual native IMU acknowledgement exists. There are no native camera
  estimates, health records or fast-state predictions in this capture.
- No motion force or readiness anchor was recorded. Heartbeat observations and
  ULog lists are empty. Absence of an arming command is not a substitute for
  missing positive unarmed telemetry evidence.
- The interval state has unknown baseline, `mutation_attempted=false` and
  `restore_attempted=false`. A baseline query was attempted; full request/receipt,
  restoration and live convergence are not qualified.
- The worker did not produce a normal terminal result. The supervisor's fallback
  `estimator_run=false` must not be used to deny the actual native process/IMU
  acknowledgement evidence. Runtime post snapshots and normal cleanup evidence
  from the worker are incomplete.
- Outer supervision recorded original-owned-group cleanup: no executing members,
  group absent after reap, no group SIGKILL. This does not cover escaped groups
  or prove successful internal cleanup. PX4 startup was interrupted.
- The frozen study auditor rejects the failed capture at its capture-status
  gate. It does not certify later raw protocol/runtime/ULog checks after that
  early refusal. All live/fusion qualification remains false.

The 2-second bootstrap progress deadline remains unchanged. Logs support a
startup/progress failure; they do not yet attribute it to low RAM, Docker,
rendering, scheduler delays or a specific PX4 startup defect. Do not extend a
watchdog or call the trial a WSL capacity measurement from this single run.

### Read-only startup timing diagnosis

A subsequent read-only audit of the retained v6 `wire-owner.json`, segmented
wire journal, and `wire-clock.jsonl` narrows the failing transition. The owned
wire start clock was recorded as monotonic 392190302651 ns; that timestamp
does not independently date the socket bind. The exact `never published\n`
snapshot was accepted at 392982936914 ns (0.792634263 s later), moving the
bootstrap from `empty_pending` to `first_ready` and resetting its progress
timer. The refusal occurred at 394982970648 ns, **2.000033734 s after that
transition**, while still in `first_ready`. This matches the source's fixed
2-second inclusive progress gate; it is not the 8-second total window.

The receiver logged 91 receive attempts after the empty snapshot, but no
received datagram or `reply_intent`. A separate `GET_MESSAGE_INTERVAL` baseline
query was sent after the first clock callback, with no ACK or readback before
the stop; no interval mutation was attempted. The first and last Gazebo clock
callbacks arrived 1.256698994 s and 1.880335515 s after the empty snapshot.
The simulation had advanced only 3 ms by the last callback. The PX4 log shows
startup reaching “Gazebo world is ready” and then being interrupted; there is
no positive heartbeat, TIMESYNC request, or completed arming-state ULog in
this capture.

Thus the observed failure is specifically **no first TIMESYNC request before
the fixed `first_ready` progress deadline**. The retained data cannot identify
whether PX4 startup, the lockstep scheduling/render path, host contention or
another cause delayed that request. Three milliseconds of startup simulation
also cannot establish a steady-state RTF. The frozen protocol expressly forbids
resetting the progress timer without a phase transition, so repeating v6 or
moving the timer to hide startup would not validate the original contract.
No additional physical run, sensor/estimator replay, or configuration change
was made for this diagnosis.

Read-only inspection of the checked-out PX4 `d6f12ad` sources adds a narrower
startup hypothesis: `rcS` sources `px4-rc.mavlink` late in startup, the onboard
link configures `TIMESYNC` at 10 Hz, and `MavlinkStream::update` sends its first
message immediately once that stream actually runs. Those four source files
were clean in the local checkout. The missing request is therefore consistent
with startup not reaching or scheduling the onboard stream before the wall
deadline, but this capture lacks a timestamped `rcS`/stream-start event and
cannot prove which stage held it up or exclude a transport problem. The 3 ms
Gazebo record does not by itself establish when PX4's stream loop ran.

### PX4 bridge-stage comparison (later read-only audit)

The failed v6 `px4.log` (SHA256
`a9cc6ebeda2a4ce7f08b3ec1d2c7619d07c503c79cfb69b90faa27e4f0d205ab`)
was compared without rerunning physics against the four completed 25-second
health-cohort PX4 logs in `results/openvins-health-physical-dev-1701-v2`.
All five contain `Gazebo world is ready` and `PX4_GZ_MODEL_NAME set` at log
lines 35–36. The failed run then terminates its startup script with status 15;
it has **no** `lockstep_scheduler` initial-time, `gz_bridge` world/model,
MAVLink Onboard, or startup-success record. Each completed run contains all
four later markers (initial-time line 37, bridge line 38, Onboard line
42–43, success line 51–52). This comparison establishes marker presence,
not wall-clock latency: the PX4 text logs have no monotonic timestamp per
line and the earlier cohort is a separate run.

The current checked-out PX4 source is `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`;
`px4-rc.gzsim`, `GZBridge.cpp` and `lockstep_scheduler.cpp` are clean in that
checkout (SHA256 respectively `dba9b8e3bfd4a5e7fef6cdb6ba7d6a23d593884886b6b91d132568f0ea4038eb`,
`8f6f1d7e450e341137be573a51674c6ffc518ef63badbdaa71667d0f462b8dfd`,
`92c8d2e153eea5deefc0aa427c601d92aa9f3c7fa8f3db40714fbdb3bd2f2117`).
`px4-rc.gzsim` invokes `gz_bridge start` immediately after the model-attach
message. `GZBridge::init` subscribes to `/world/<world>/clock` and waits for
its first callback before other required sensor subscriptions; the startup
script reaches MAVLink later. This makes bridge/clock startup an upstream
candidate for the missing TIMESYNC request. Because the failed log lacks
even the bridge's first world/model message, it does **not** prove whether
the command entered its task, subscribed to clock, or had not flushed a
message by interruption. The Python-side clock callbacks do not prove PX4's
separate subscriber received a clock. No bridge code or runtime parameter
was changed for this audit.

The comparison is separately sealed as
`evidence/live-wire-px4-startup-audit-dev-1701.zip` (11 members,
23,347 bytes, SHA256 `d943142bc89ddf2dcc5d2bf25432cdec3b7c00b6b3896a48a4abf31fdab2628d`).
It contains the five exact PX4 logs, three clean-checkout source files, the
read-only builder and a marker/identity JSON; member hashes and ZIP CRC were
verified. The failed log was byte-equal to the original v6 sealed ZIP. The
four completed logs were copied from retained local cohort results at audit
time, not misrepresented as original v6 members.

The same checkout's earlier, completed, single-aircraft health-cohort
development capture ran 25 s of simulation with the same declared physics,
IMU and camera rates. Its supervisor observed the worker from monotonic
7.680028769 s to 86.092704011 s, about 78.413 s overall (25/78.413 ≈ 0.319
simulated seconds per wall second, including startup and cleanup). That is a
separate run, not a measured RTF for v6. Even if the interval transaction had
established its proposed 100 Hz TIMESYNC rate immediately, 500 accepted
samples require roughly 5 s of simulation; at that historical average pace
the simulated interval alone would take about 15.7 s wall time, beyond the
frozen 8 s total bootstrap window. This is a **feasibility warning for this
WSL2 host**, not a proof of the exact v6 bottleneck or a license to change the
rate, threshold, clock basis or physics load and call the original study passed.

## Bounded repair

`bind_capture_wire` now retains both callback and stop-path exceptions instead
of propagating them across the native callback boundary. It skips the clock and
original callback when stopping/closed. Shared errors and driver failure remain
latched; pre-step health prevents subsequent motion, and the existing outer
runner and CaptureJournal retain `capture_failed`. The current stepping chunk
may finish; this is not immediate cancellation of an in-flight step.

The [official pybind11 exception documentation](https://pybind11.readthedocs.io/en/stable/advanced/exceptions.html#handling-exceptions-from-python-in-c)
describes Python callback exceptions becoming `error_already_set` in C++, which
matches the observed native abort. This is a local wrapper repair using the
existing installed Gazebo/pybind boundary, with no new dependency or version
upgrade. Installed-version provenance remains the v6 declared inventory; the
current documentation does not prove installed patch equivalence or maintenance.
No new sensor, dynamics or estimator algorithm was adopted.

Five behavioral counterexamples fail before the repair (four escaped exception
errors and one assertion failure). The first attempted WSL pytest invocation
failed because pytest is not installed there; a second unittest invocation was
interrupted by the deliberately escaping KeyboardInterrupt. Both logs remain;
neither is presented as a completed five-case run. The final RED completed all
five cases. Tests cover original callback failure, stopping, closed state,
invalid clock input and interrupted stop handling.

Windows hooks/contract/explicit-entry tests passed: 52 in 65.84s. WSL initial
adjacent run passed 60 actual-codec/lifecycle cases but included one pytest-only
module import error; Windows subsequently covered that module. The corrected WSL
unittest run passed all 60 cases in 49.346s, exit 0. Changed-file Ruff and diff checks passed.
Independent read-only review found no Critical/Important/Minor issues. No new
whole-repository regression or post-repair physical trial is claimed.

## Next dependency

Diagnose the retained startup timing sequence and pinned PX4 listener readiness
before designing a separate retry. Keep 2s progress / 8s bootstrap and all
existing watchdogs and workload fixed unless a genuinely different research
question is explicitly designed; do not silently loosen them to pass.
The read-only timing audit above completes the first step: the next question is
why no PX4 TIMESYNC request reached the owned receiver in that fixed window.
That needs bounded startup/lockstep evidence or a separately frozen diagnostic
study, not a blind repeat of the failed physical capture.
The bridge-stage comparison above narrows that study: timestamp the owned
PX4 log's model-attach, first bridge/clock, MAVLink Onboard and startup-success
markers against the existing Gazebo clock and receiver journals, with a
bounded read-only observer. Preserve missing markers as missing; never infer
their occurrence from another process's clock. This is a separate diagnostic
condition with its own instrumentation cost, not a qualification retry or a
reason to relax the original 2s/8s windows.
`tools/benchmark/observe_px4_startup.py` now provides that opt-in,
standalone read-only file observer. It must start before the study creates
`px4.log`; it records first **observation** time on the host monotonic clock,
file identity and absent markers as null, with a 1 MiB input and explicit
wall deadline. Path aliases between log and output, nonregular/symlink logs,
replacement, disappearance, observed shrink, changed-prefix rewrite and
existing output fail closed. Eight Windows tests passed and one symlink test
was skipped for host privilege; a separate real POSIX dangling-symlink probe
passed in WSL. Ruff passed and an actual CLI missing-log invocation returned
the expected refusal. A truncate-and-regrow with an identical consumed prefix
is not distinguishable by this bounded file observer; its marker evidence
cannot serve as a source-authenticated PX4 event trace. This tool has not been
run alongside PX4/Gazebo, so it supplies no v6 timestamps and cannot qualify
the wire bootstrap by itself. A later physical diagnostic needs a separately
frozen manifest, new output path and resource-clear check before using it.
Its synthetic/CLI evidence is sealed in
`evidence/live-wire-px4-startup-observer-dev-1701-v3.zip` (9 members,
6,845 bytes, SHA256 `3ffcc9b8f4f47148b47ce1c290811a10e85ab85632d6404556c70a9d64ec6077`);
member hashes and ZIP CRC were verified.
The callback fix changes selected source bytes: v6 cannot be reused for another
attempt, and no v7 has been prepared or executed. Preserve the v5 refusal and v6
physical failure independently. Full learning/division, deployment-visible
corpus, fair comparison, five/20-aircraft gates and hardware evidence remain open.

## Evidence seal

`evidence/live-wire-first-activation-dev-1701.zip`: 269 members, 1,414,390 bytes,
SHA256 `2a1effc4ba82273f38d77199ef855c93015851e7821e39efa60faa4b054a556f`.
All archived member bytes and CRC were verified. It includes the complete v6
directory and same-level supervisor journal, v5 rejection, preparation generator,
source inventory, failed and passing test logs, review, and 82 frozen producer
sources. The changed lifecycle source is reconstructed from producer Git bytes
with line endings checked against the predeclared digest, explicitly not a
pre-run copy. Other source copies match frozen digests after the run. Installed
libraries are represented by declared identities/hashes, not full binary copies.
This seal paragraph was added after archiving. The archive itself was not
rewritten by later publication and audit changes. No second physical run or
full-model test is claimed.
