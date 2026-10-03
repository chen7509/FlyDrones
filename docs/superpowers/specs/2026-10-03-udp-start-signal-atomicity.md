# Atomic start signal for four-process UDP stress trial

The full project regression intermittently failed when workers observed
`start.json` immediately after the parent created it but before its JSON bytes
were written. Two workers recorded `JSONDecodeError`, produced no trajectory CSV,
and the parent failed later during aggregation. This is a test-harness and
distributed-simulation startup race, unrelated to OpenVINS feature geometry.

Publish the start signal atomically in the existing output directory: write a
temporary file fully, then replace `start.json`. Workers may keep their existing
wait-for-existence behavior. Preserve the existing trial configuration,
simulated dynamics, UDP communication, start timestamp and acceptance criteria.
Do not suppress worker errors or treat missing traces as passing. A stale
temporary file from an interrupted previous trial must be replaced safely.

Add a deterministic test that pauses publication after the temporary file has
been written and verifies no worker-visible `start.json` exists until the
atomic replace. Then rerun the four-process stress test repeatedly and the
full suite. Record all failures and distinguish kinematic UDP simulation from
PX4 physics, HITL and real flight.
