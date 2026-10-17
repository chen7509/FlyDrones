# EKF2 capture-health evidence plan

The user has authorized continued implementation. Keep the existing worktree
and PR65; push only `personal`.

1. Record an explicit synthetic regression in `test_capture_input_gate.py`:
   invalid horizontal/vertical velocity, dead reckoning, nonzero or malformed
   filter faults, and stale/future estimator-status time must refuse. Verify
   the first relevant assertions fail before implementation.
2. Extend `CaptureInputEvidence` and its gate without making source labels or
   caller booleans into authentication. Check original and copied observation
   health before the checked recorder mutates state.
3. Reuse the frozen four-run physical ULogs and OpenVINS health journals for a
   read-only per-public-frame report. Verify original ULog manifest hashes and
   preserve all frames, including missing/stale/invalid records. Do not train
   or start a simulator.
4. Run focused and affected/full regression, Ruff and staged diff checks;
   obtain independent read-only review. State exactly which conclusions are
   verified versus only implemented. Seal code/report/raw audit/tests/failed
   attempts with per-member hashes and CRC, commit/push PR65, then update the
   continuing automation with the next dependency.
