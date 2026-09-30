# Five-Camera Render Capacity Amendment 46: Fail-Closed Metric and Snapshot Review

Date: 2026-09-30

## Trigger

Pre-merge review found that a missing or non-finite camera frequency, phase-error,
or spacing metric could be represented as a performance threshold miss. Three
such Python-cell failures could therefore satisfy the old root-cause rule and
open production integration without valid measurements. The review also found
that pre-readiness slots were assigned derived performance failures and that the
snapshot verifier accepted any twelve unique schedule names from the manifest.

## Required behavior

1. Missing, boolean, NaN, or infinite camera metrics are evidence failures.
   Only finite measured values may produce performance threshold failures.
2. A slot that does not complete the frozen scored duration is explicitly
   `unscored` and cannot contain derived performance failures.
3. Missing metrics in every Python repetition must force an inconclusive,
   production-ineligible campaign result.
4. Capacity snapshots must match `capacity_schedule()` in full identity, order,
   cell, implementation, subscriber count, repetition, and sequence.
5. Manifest, summary, and raw-index campaign IDs must agree. The source and
   compact snapshot roots must contain exactly the expected entries.
6. The preserved `task7-frozen-20260929-234951` raw campaign remains immutable;
   any performance labels synthesized by its historical runner for unscored
   slots are retained as provenance and are not treated as measurements.

## Acceptance

- Unit tests cover missing, NaN, and infinite frequency, phase-error, and spacing
  inputs plus an end-to-end false-eligibility regression.
- Campaign-runner tests prove pre-readiness records remain unscored with no
  performance failures.
- Snapshot mutation tests cover schedule content, source-root entries, and all
  campaign-ID relationships.
- The original raw campaign still verifies against its committed compact copy
  without rewriting either evidence set.
