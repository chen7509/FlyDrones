# Declared Launch Environment Design

## Purpose

The sealed full-load study in PR58 froze argv, files, resource lookup context, workload, and safety gates, but its only online attempt stopped before physics because the supervisor inherited an environment that the worker's runtime binding did not accept. This design makes the process environment an executable part of the prospective contract. The old `dry-v4/capture-v1` evidence remains immutable and failed.

This stage may qualify only the environment transport and refusal mechanism. It does not qualify runtime mapping coverage, VIO, estimator health, PX4 fusion, learning, or flight readiness.

## Source basis and adoption decision

The installed runtime is CPython 3.12.3. CPython is PSF-licensed and maintained upstream. Its `subprocess.Popen(env=...)` API supplies the child environment explicitly; the fixed executable is already an absolute path, so no child-side PATH search is needed. Linux `execve(2)` defines `envp` as the environment supplied to the new image, and `environ(7)` distinguishes a missing name from a present `name=` entry. These APIs are adopted directly; no new package or service is added.

The implementation will use the fixed resource binding as its source of truth. It will not infer allowed variables from a failed process, `/proc/<pid>/environ`, or a post-run observation. Runtime cost is one small JSON declaration, one sibling supervisor record, one worker record, and one explicit environment mapping passed at process creation.

## Contract

Legacy captures without a v3 runtime binding retain `capture-execution-v1` behavior. A prospective v3 binding produces `capture-execution-v2` with an exact `launch_environment` object.

`launch_environment` is the union of:

- every key in the binding's exact `environment` map;
- every key in the sealed generated-resource graph's exact `environment` map.

Overlapping keys must have exactly the same type and value. Every key is present in the declaration. A string means the variable is present with exactly that value, including the empty string. `null` means the variable must be absent. No caller variable outside the non-null declared set is inherited by the worker.

The environment contract rejects duplicate JSON keys, non-string/non-null values, empty or invalid names, `=` or NUL in names, NUL in values, oversized declarations, conflicting overlap values, and missing graph/binding maps. This preserves absent-versus-empty semantics and prevents an ambient `PYTHONPATH`, loader hook, proxy, locale, or terminal variable from entering the worker unless it is prospectively declared.

## Parent and worker evidence

The capture parent validates the execution declaration and v3 binding before starting the supervisor. It materializes exactly the non-null values and passes them to `Popen(env=...)`.

Before spawning, the supervisor exclusively writes a sibling record containing:

- the exact declared nullable map;
- the exact materialized child map;
- the execution-contract path and SHA-256;
- a statement that no ambient variables are inherited;
- conservative false qualification fields.

The worker reads its initial environment from `/proc/self/environ`, preserving present empty values and rejecting malformed or duplicate entries. Before resource inspection, generated files, `TestFixture`, PX4, or OpenVINS, it exclusively writes `execution-environment-worker.json` with the observed map, declared map, contract hash, and equality result. On mismatch it raises after writing the refusal evidence; the supervisor still creates/retains terminal failure and performs bounded cleanup.

For v2, the worker does not prepend the Gazebo model paths a second time. The exact frozen `GZ_SIM_RESOURCE_PATH` is already its initial value. It may add only per-run values after the initial proof, such as the unique `GZ_PARTITION` and the fixed PX4 child variables; the runtime binding continues to compare its declared lookup keys and graph context.

## Tests and bounded runtime validation

Unit tests cover:

- absent versus present-empty values;
- deterministic union and overlap conflict;
- hostile inherited `PYTHONPATH`, loader, proxy, and locale values not reaching the worker;
- malformed names, values, duplicates, and oversize;
- exact parent materialization and supervisor spawn argument;
- worker `/proc` parsing, duplicate/malformed records, mismatch, and exclusive evidence-write failure;
- v1 compatibility and v2 refusal before resource inspection;
- exact contract hash and supervisor/worker equality.

A bounded Linux harness launches a small absolute-path Python child through the real supervisor with a hostile parent environment. The child records `/proc/self/environ`; the audit must prove exact equality to the declared non-null map, absence of hostile variables, bounded cleanup, and no SIGKILL. It does not launch PX4, Gazebo, OpenVINS, training, or a physical study.

Only after this mechanism and its independent audit pass may a separately named physical environment-preflight study be designed. PR58's failed run is never rerun, relabeled, or used as a pass.

## Boundaries and next dependency

This stage does not change 300/300 budgets, 25 s / 1 ms / 250 Hz / 10 Hz 160×120 workload, the supported motion, readiness/watchdog limits, safety thresholds, sensor values, OpenVINS configuration, ODOMETRY, arming, or EKF2.

After the declared environment gate, the trajectory/gauge contract must be frozen before the next online VIO accuracy study. Truth remains limited to external termination and offline scoring.
