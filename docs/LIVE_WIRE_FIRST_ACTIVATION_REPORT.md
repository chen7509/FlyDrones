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
This seal paragraph was added after archiving. Publication of this increment is
local; no remote push, second physical run or full-model test is claimed.
