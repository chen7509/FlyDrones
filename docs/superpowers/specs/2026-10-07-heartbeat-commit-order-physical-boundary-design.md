# Heartbeat commit-order physical boundary design

## Goal

Create a committed, independently reproducible, one-shot physical execution
boundary for the qualified `study-v21` package. Boundary construction and
audit do not run physics.

## Required evidence

- Exact committed Git HEAD from a separate immutable file and live Git query.
- `study-v21` live post-startup package audit with no failures.
- The successful startup-only dispatch, completion and independent audit.
- `evidence/heartbeat-commit-order-retry-preflight-dev-1701.zip` pinned by
  name and SHA-256, with CRC, unique members, manifest and every member hash
  verified. All consumed live artifacts must match archived bytes.
- Exact 25 s / 1 ms / 250 Hz / 10 Hz 160x120 execution contract, estimator,
  profiles, 10 s source startup and 2 s operational limits.
- Exact command and fresh `study-v21/capture-v1`; dispatch, output and
  completion paths must also be absent. Active resources must be empty.

## One-shot behavior

The committed executor re-audits the boundary immediately before dispatch,
uses exclusive creation for dispatch/output/completion and records every
return code, partial destination and post-run resource scan. Any outcome is
retained and cannot be rerun at the same destination.
