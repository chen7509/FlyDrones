# Pinned listener framing implementation plan

Execution: superpowers:executing-plans, inline, existing isolated worktree.
Spec: ../specs/2026-10-08-listener-wire-format-design.md
Goal: decode the fixed native multi-record format without sanitizing corruption.
Stack: Python strict parser; unchanged C++ source probe with explicit fake uORB.

## Global constraints and review focus

No live PX4/Gazebo/estimator, network, parameters, training or gate changes.
Never refresh the 2s deadline with partial bytes or accept escapes inside fields.
Raw bytes count against unchanged limits; explicit profile, no autodetection.
Existing plain behavior must stay compatible; malformed output latches failure.
Native fixture is not a real uORB/buffering/clock/delivery/throughput proof.

## Task1: exact pinned framing

Files: tools/benchmark/openvins_timesync_listener.py;
tests/benchmark/test_openvins_listener_wire_format.py; tests/fixtures/timesync/.
Interface: TimesyncListenerDecoder(instance, expected_records, start_ns,
*, output_profile='plain-v1'); feed/check/finish remain compatible.

- [x] Retain recorded native bytes and provenance; tests for native two-record
      acceptance and split/byte fragments must fail before implementation.
- [x] Add exact-prefix profile and refuse missing/unknown/inside-field prefixes,
      partial timeout/EOF, trailing bytes, mismatched count and invalid profile.
- [x] Verify raw counts, default rejection, unchanged field/ordinal validation,
      observer handoff and synthetic 500-record chain; commit targeted changes.

## Task2: review and evidence

- [x] Independent code/evidence review; material findings need RED/GREEN repair.
- [x] Run full pytest with current-tree PYTHONPATH and changed Ruff/diff checks.
- [x] Report native probe scope, metadata/reused source hashes and old test gap;
      seal new ZIP/CRC/hash without replacing prior evidence.
- [x] Update parent plan, commit/push personal and existing PR65; overall goal
      and actual bootstrap/live gates stay open.

Offline cold snapshot/replay composition is now implemented and reviewed under
`2026-10-08-timesync-cold-bootstrap.md`; actual process/source/transport binding
and live convergence remain unverified. See OPENVINS_TIMESYNC_BOOTSTRAP_REPORT.
