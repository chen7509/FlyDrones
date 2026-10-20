# Estimator Physical Retry Design

## Goal

Create one new immutable physical-capture package whose declared inputs include the successful current-code capture startup preflight. Preserve the prior refusal and keep every workload and safety threshold unchanged.

## Gate

The builder accepts only a qualified prepare-only source, a successful startup-preflight result, its matching supervisor journal and independent audit, and an empty active-resource scan. It copies the frozen policy contracts, adds a startup-authorization contract and all preflight evidence to the runtime binding, refreshes the declared-file snapshot, and emits a new command targeting a never-used directory.

The auditor independently checks source and startup evidence, recomputes the binding, execution declaration and command, verifies that only package paths changed, and keeps all downstream qualifications false. Building and auditing never execute the command.

## Execution boundary

After the package and code are committed and re-audited, at most one physical capture may run. It must retain 25 s simulation duration, 1 ms physics, 250 Hz raw IMU, 10 Hz 160×120 RGB-D, the original vehicle/gravity/support/lateral force profiles, readiness anchor, watchdogs, wall limits, and failure handling. Any refusal is retained without retry.
