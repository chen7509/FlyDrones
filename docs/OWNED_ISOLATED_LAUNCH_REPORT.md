# Owned isolated launch boundary

Date:2026-10-08. Design/plan:b2cb4f4. Runtime producer:7121080.

Sealed evidence: `evidence/owned-isolated-launch-dev-1701.zip`, SHA256
`8987976232e6e840b0dcabae506bd987bde7c44118242dad099ef6340466725b`.
89 members,187909 bytes; CRC and member hashes verified. The prior channel ZIP
is unchanged. The archive contains the report/plan before this publication note
and final publication checkbox; the external manifest records the ZIP identity.

## Result and scope

Implemented `tools/benchmark/isolated_namespace.py`: a declared command can run
inside an owned user/network namespace only after the wrapper verifies its
identity, mapped credentials, loopback topology, inherited descriptors, exact
environment and selected file hashes. The existing original-process-group
supervisor remains responsible for timeout, signals, reap and cleanup evidence.
Isolation failure never falls back to the host network.

One prospectively declared four-case ordinary-process harness verified normal
completion, nonzero command exit, resistant-child timeout and direct host-worker
refusal. This is no longer just the prior socket feasibility probe, but still
is **not** a PX4/Gazebo launch or proof of cold TIMESYNC filter ownership.
No simulation, estimator, MAVLink traffic, stream/parameter change, ODOMETRY,
EKF2 fusion, arming or training was performed.

## Reused sources and integration

The preceding channel evidence fixes the OS candidate: unshare from installed
util-linux2.39.3-9ubuntu6.6 (GPL-2-or-later), iproute2 6.1.0-1ubuntu6.2 (package
GPL-2), Python3.12.3 (PSF), WSL kernel6.6.87.2. The fixed util-linux v2.39.3 source,
installed version/copyright/maintenance observations and
[namespace API documentation](https://man7.org/linux/man-pages/man7/network_namespaces.7.html)
are reused from that sealed archive, with source-member and archive hashes.
No new upstream activity or installed-patch equivalence is inferred. The
[fixed CPython3.12.3 implementation](https://github.com/python/cpython/blob/v3.12.3/Lib/subprocess.py)
and its documentation are reused from earlier supervision research: Popen defaults
to closing extra descriptors, and the existing supervisor explicitly starts a
new session. The command itself also uses close_fds=True and exact env, without
a shell. No new algorithm/paper-derived estimator model was introduced.

Reusing `supervise_worker`, GroupEvidence, `snapshot`, `verify_unchanged` and
`write_manifest` preserves the existing bounded cleanup and declared-file
semantics. The wrapper validates before bringing up loopback, closes gate evidence
before command creation, rechecks observation/files/environment immediately before
spawn and checks post state. Command and post failures are recorded separately.
The parent hashes the declaration and passes that exact digest to the worker;
successful exit/status text alone is insufficient qualification.

Resource cost remains unqualified for the actual physical study. No dependency
installation, host-root invocation, firewall, veth or host routing change was
made. Explicit executable/dependency inventories are not complete Python/numpy
or future simulator runtime closure; that flag stays false. External dependencies
and actual selected runtime mappings still belong to the existing capture binding.

## Actual retained run

`results/owned-isolated-launch-dev-1701/runtime-v1/prospective.json` freezes four
cases, command/environment and selected file snapshot before execution. Same
machine/normal host UID1000; namespace root maps solely to that UID/GID. Each
worker is the original group/session leader; command children stay in that group.
Only normal execution sets the boundary's `isolated_launch_qualified=true`.

|Case|Elapsed wall seconds|Worker/command exit|Observed outcome|
|---|---:|---|---|
|normal|2.20098|0 /0|Gate, command, post files and graceful group cleanup passed.|
|exit7|2.23786|2 /7|Command failure retained; group drained without SIGKILL.|
|timeout|7.52799|−15 /unavailable|4s supervisor deadline, then TERM and actual resistant-child SIGKILL; failed execution retained.|
|direct-refusal|Not scored|2 /not started|Same host namespace rejected; command marker absent.|

All four original groups were observed absent with no executing members after
reap; this does not cover escaped descendants. The timeout's worker could not
write terminal/post evidence after TERM. The supervisor's `capture_failed` and
parent post snapshot remain; no worker post evidence was manufactured.

Actual child markers were separately matched against declared environment,
worker namespace IDs, credentials, process group/session and startup ordering.
All four disk signal journals match the supervisor's retained in-memory events.
Declared pre/post file records match. These elapsed times include synthetic
startup/command/cleanup; they are not VIO/TIMESYNC latency or capacity results.

The reviewer requested that marker comparisons be executable assertions in the
harness. That improvement and nine new tests were added after runtime-v1; the
fixed existing inputs passed the new offline audit, without another process run.
The old producer harness was exported from Git after the run and its hash matches
the original pre/post inventory. It is labeled a post-run export, not a runtime
copy. The production wrapper was unchanged after runtime-v1.

## Failure coverage and review

The initial38 tests failed because the module was absent, not because behavior
assertions had executed. During implementation, two actual counterexamples exposed
an incorrect supervisor contract argument and missing post-topology comparison;
both passed after repair. A missing bound-envelope API was separately recorded.
An additional actual counterexample rejected qualification based on only a
successful terminal label. All RED outputs and subsequent GREEN checks remain.

Tests also cover same namespace, bad UID/GID mappings, boolean identities, foreign
interface/address/route, inherited socket/extra FD, environment drift, changed
dependency before spawn, setup error, actual manifest short-write/close failures,
pre-command identity drift, child spawn/nonzero errors and post-read failure.
Focused suite:147 passed,2 existing Windows symlink skips. Changed Ruff and Git
whitespace checks passed. Whole-repository lint is not claimed.

Final full regression with this worktree's explicit PYTHONPATH:2494 passed,
3 skipped,2 existing warnings in328.22s. The completed session returned exit0.
This includes the final harness marker checks; it does not turn ordinary-process
fixtures into actual PX4 integration evidence.

Independent review found no blocking issue. A suspected IPv6 omission was
withdrawn after the installed read-only `ip -j route show table all` returned both
address families. The marker-check improvement above was the sole nonblocking
verification finding; its nine tests are new GREEN coverage, not claimed RED fixes.

## Remaining boundaries and next work

|State|Evidence boundary|
|---|---|
|Verified|Declared isolated launch and refusals in ordinary-process fixtures; selected-file stability and original-group cleanup.|
|Implemented|Reusable namespace wrapper, explicit argv/environment and declaration-digest checks.|
|Not tested|PX4/Gazebo in this namespace, discovery/rendering, real cold filter, uORB association, live listener and500 accepted exchanges.|
|Still closed|Physical network qualification, runtime closure, EKF2 fusion, policy control, hardware calibration and swarm expansion.|

Working directory is inherited by this narrow wrapper. Its observed namespace
qualification does not qualify relative command inputs. Before any real capture,
compose it with the existing explicit capture working-directory/resource binding;
do not call argv/env alone a complete reproducibility contract. This wrapper also
does not isolate filesystem UNIX daemon socket paths, protect against hostile
administrators, supply atomic/fsync guarantees, or retrospectively prove a clean
PX4 filter. These remain explicit, not silently satisfied by a new namespace.

Next complete the cold first-reply/status association using the existing decoder,
observer and reversible interval transaction. Keep subsequent replies withheld
until the chosen fresh status matches. The actual PX4 lifecycle/socket path,
uORB instance and routing/only-responder evidence must be explicit. Missing,
ambiguous, stale or extra status refuses; no nonce/generation is invented.
Preserve25s total,8s readiness,2s watchdogs and500 accepted samples. The namespace
is not permission to perform the separately gated live Task5.

Historical VIO/capture failures and five-camera0.873RTF<0.95 remain unchanged.
Complete fruit-fly learning/division, fair upstream comparison, single-aircraft
closed loop and5/20-aircraft evidence remain the project goal downstream.
