# Estimator Physical Retry Plan

- [x] Verify the current committed startup preflight and its independent audit.
- [x] Implement a prepare-only builder that binds the startup evidence and emits a fresh physical destination.
- [x] Implement an independent package auditor and failure tests.
- [x] Build, audit, commit, and re-audit the new package without executing it.
- [x] If every gate remains green and resources are empty, run at most one new physical target and preserve all evidence. The sole `study-v8/capture-v1` attempt failed closed at 10 ms simulation time on the fixed 250 ms causal-input wall-wait limit; it will not be rerun or overwritten.
