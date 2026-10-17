# RX startup observer implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline; independent requesting-code-review before real observation. User approved continued plans.

**Goal:** Obtain every first/later raw generated-RX observation in one distinct non-controlling local trace, without qualifying live source timing.
**Architecture:** One standalone diagnostic entry, stateless ancillary observation decoder, existing exact RX prepare/check and owned supervisor, strict frozen source/profile; no production parser change.
**Tech:** Existing Python/socket/struct/JSON/hash and installed capability files, pytest fakes.
**Spec:** docs/superpowers/specs/2026-10-12-rx-startup-observer-design.md

## Global boundaries and review

Eight packets/50ms inter-send lower bound/20ms hold/200ms poll/5s inner/20s outer+2s kill/25s supervisor; ephemeral loopback only; no warm/discard/retry/network-control/physics/training/kernel tuning; all gatesfalse. Review successful syscall before clock exception, malformed observation continues versus identity fault stops, journal partial delivery/cleanup, actual module/profilecopy, timer and namespace scope. No new global process subsystem.

- [x] Preserve read-only research/context and write spec/plan before implementation.
- [x] Add RED tests in tests/benchmark/test_rx_startup_observer.py; implement tools/benchmark/observe_kernel_rx_startup.py and run fake fault/regression checks.
- [x] Independent review and corrections, freeze selected modules/ABI/profile/spec/plan and commit before dispatch.
- [x] One owned WSL observer run only; retain all missing/present raw records, failures and originalFD/group evidence; hash/audit without rerun.
- [x] Final targeted/affected checks, independent evidence review, report distinctions and seal hashes/CRC; commit/push personal, update PR65/automation. Full goal active; next actual source/clock/health and resource-gated physical/model/upstream work remains.

Publication: producer2193e02 and report/seal2c64fda pushed only personal; PR65 and ACTIVE automation updated.83members allhash/CRC independently verified after seal, resolving review sequencing note. Archive preserves the pending-publication plan snapshot; this checked state is subsequent publication evidence, not capture input history.
