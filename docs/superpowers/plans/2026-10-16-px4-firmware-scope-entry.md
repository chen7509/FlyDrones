# PX4 firmware scope entry implementation plan

> Use superpowers:executing-plans inline under standing autonomy; no new chat or staged approval.

Goal: put actual scope/zero-swap checks before the original one-job compiler invocation.

Architecture: new primitive px4_firmware_scope_entry_v2.py verifies its actual Linux process/cgroup and execs only fixed make. New run_px4_status_firmware_build_v2.py derives from immutable v1 runner and wires the entry into the real bounded dispatch command with entry byte pins and all original admissions/cleanup.

Tech stack: existing Python/os/sys, Windows/WSL/systemd tooling for future native use only; explicit inert protocols in tests.

Spec: docs/superpowers/specs/2026-10-16-px4-firmware-scope-entry-design.md

Global constraints: old v1 runner/v4 refusal/consumed sources/raw untouched. Same original fixed firmware result path, no folder retry, no native execution/resource polls this software phase. Original dual4GiB/15GiB disk/two gates/one job/5400s deadlines retained; add zero swap/TasksMax256. No SDK/sim, no authentication/compiled/flight qualification. All prior history/budgets/false qualifications remain binding.

Review focus: virtual-file permission/error/overlong reads; current cgroup drift between samples; wrong UID/owner/member/unit; entry byte drift before/after dispatch; launcher started is not compiler or binary proof.

- [x] New guarded tests first, missing-interface then actual copied-v1 command behavior RED, implement primitive entry and v2 actual dispatch routing. Exercise all fail-closed branches via inert OS/reader/exec protocols, clean exact make args/env, module/direct-main before-effect refusal and original filename preservation. Only necessary affected pure/software neighbors under explicit child guard, no legacy native tests/probes.
- [x] One independent whole source review against exact current/frozen source/spec/plan; grade effects, one bounded fix pass if required. Final focused tests/Ruff/diff, preservation and honest report; seal prospective evidence/fixtures and independent delivery integrity without source/native reapproval.
- [x] Publish software and sole plan-byte ledger only personal/draftPR65, preserve full PR/automation suffix and three histories; automationACTIVE/goalblockedreadonly, final publication integrity audit. Future real build still requires complete fresh current source/receipt/admission under original once protocol, not this test output.
