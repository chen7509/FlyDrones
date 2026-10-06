# Estimator Physical Retry Plan

- [x] Verify the current committed startup preflight and its independent audit.
- [x] Implement a prepare-only builder that binds the startup evidence and emits a fresh physical destination.
- [x] Implement an independent package auditor and failure tests.
- [ ] Build, audit, commit, and re-audit the new package without executing it.
- [ ] If every gate remains green and resources are empty, run at most one new physical target and preserve all evidence.
