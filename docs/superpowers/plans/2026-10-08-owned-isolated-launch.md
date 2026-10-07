# Owned isolated launch implementation

Spec: ../specs/2026-10-08-owned-isolated-launch-design.md
Execution: inline, preapproved by user; retain every failed run. Existing worktree.

## Global constraints

No live simulator/estimator/ODOMETRY/stream/parameter/arming/training. Reuse owned
group supervision and snapshots. Never fallback to host networking. No dependency
install. Physical/fusion/runtime-closure flags remain false.

## Review focus

- Extra inherited socket or FD must refuse before command creation.
- Failed close or pre-spawn identity/file drift must not release the command.
- Child failure and post failure must preserve both reasons and cleanup evidence.
- Namespace success must not qualify actual PX4 cold filter or dynamic uORB index.
- Test injection must not be an available production CLI bypass.

## Task1: validated namespace observation and worker gate

Files: tools/benchmark/isolated_namespace.py;
tests/benchmark/test_isolated_namespace.py.
Interfaces: validate_observation(parent, observation, ready); run_worker(envelope,
output, backend=None) returns a result with exit/error/qualification fields.

- [ ] Write invalid identity/topology/FD and journal-failure cases; observe RED.
- [ ] Implement strict pure gate and actual proc/ip observation; snapshot checks
      reuse declared_runtime_snapshot. Worker rechecks before command creation.
- [ ] Run focused tests; verify command was never invoked for refused cases.

## Task2: existing-supervisor composition

Interface: launch_isolated(command, output, inventory, environment, timeout_s)
creates exclusive evidence root and returns terminal result. No shell/fallback.

- [ ] Test missing roles/undeclared executable, envelope drift, invalid timeout,
      missing worker result, post snapshot failure and supervisor failure.
- [ ] Implement exact command/environment declaration and pre/post capture;
      existing supervise_worker owns group cleanup and signal evidence.
- [ ] Verify targeted snapshot/supervisor regressions and changed Ruff/diff.

## Task3: prospective ordinary-process harness and review

File: tests/benchmark/check_isolated_namespace.py; fresh results directory.

- [ ] Freeze selected runtime/dependency and producer hashes before harness.
- [ ] Run normal, exit7, TERM-resistant timeout and direct-worker refusal once;
      verify original-group evidence, command marker, namespace/mapping/topology,
      exact environment and parent-state stability. No physical processes.
- [ ] Run full pytest with explicit current-tree PYTHONPATH.
- [ ] Independent bounded review; repair material findings with RED/GREEN evidence.
- [ ] Report scope/remaining gates, seal ZIP/hash/CRC, commit/push personal and
      update existing draftPR65. Do not mark overall goal complete.
