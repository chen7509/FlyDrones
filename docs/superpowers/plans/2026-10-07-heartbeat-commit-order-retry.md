# Heartbeat commit-order retry package plan

- [x] Add source/archive validators and RED drift tests.
- [x] Build and independently audit a fresh prepare-only `study-v20` package.
- [x] Commit the stable builder/package evidence, then re-audit the committed tree.
- [ ] Run exactly one startup-only preflight; physical execution requires a later separate boundary.
