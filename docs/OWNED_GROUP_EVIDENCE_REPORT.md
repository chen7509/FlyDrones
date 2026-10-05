# Owned process-group cleanup evidence

**Four bounded real Linux subprocess studies recorded signal outcomes and ended with the owned process group absent.** This is process-lifecycle validation only: no PX4, Gazebo, OpenVINS or training was started. PR44's missing historical signal evidence remains unknown and unchanged.

## Change and rationale

The previous supervisor waited/reaped the leader first, then sent group signals without recording outcomes. The new real path records leader pid/pgrp/session/start ticks, waits with `waitid(WNOWAIT)` and retains that leader until identity-checked group cleanup finishes. It records every signal intent/result and bounded membership observation, then reaps and scans again. Group absence, no executing members, zombies, SIGKILL dispatch and graceful cleanup are distinct fields. The scope is the original owned group; descendants that escape with setsid/setpgid are not tracked or certified.

Checked JSONL writes happen before/after actions. Write/flush/close errors remain in terminal in-memory evidence and prevent successful qualification, while safe owned cleanup continues. Clock/scan failure does not silently skip bounded escalation. Wait/reap errors and Python interruption still attempt cleanup, journal closure and terminal summary. Capture-level ULog retention now considers supervisor errors, abrupt worker failure and unqualified cleanup. If group exit remains unknown, it retains the runtime path without copying possibly unflushed logs. Existing ULog evidence is hash/path/header verified without overwrite. These decisions are unit-tested, not new PX4 evidence. A successful capture also requires qualified graceful group cleanup.

Source research used fixed CPython3.12.3 source/docs under the PSF license, current GitHub maintenance metadata, [Python subprocess documentation](https://docs.python.org/3.12/library/subprocess.html), and Linux [waitid](https://man7.org/linux/man-pages/man2/waitid.2.html), [kill](https://man7.org/linux/man-pages/man2/kill.2.html) and [proc stat](https://man7.org/linux/man-pages/man5/proc_pid_stat.5.html) manuals. The installed WSL interpreter is3.12.3/GCC13.3 with kernel6.6.87.2; distribution source-patch equivalence is not claimed. A proc-stat HTML snapshot fetch hit a TLS EOF and is retained as a fetch failure; the page was read through the web tool. No verification bypass or install. Standard-library reuse avoids another daemon/dependency; polling adds bounded cleanup work and is not a simulator capacity optimization.

## Frozen actual subprocess study

Producer `95dc10a`; `tests/benchmark/check_owned_groups.py` freezes direct source hashes before creating any test group and verifies them afterward. Every leader is a newly created session. A separate sentinel group remains alive with unchanged identity throughout, then the harness explicitly terminates its own sentinel (exit−15).

| Case | Wall seconds | Supervisor status / leader exit | SIGKILL dispatched | Final group absent | Graceful group cleanup |
|---|---:|---|---|---|---|
| Normal exit |0.4592|worker_exited /0|false|true|true|
| Leader exits, child remains |1.3818|worker_exited /0|false|true|true|
| TERM-resistant child |4.0678|worker_exited /0|true|true|false|
| Overall timeout |2.1262|supervisor_timeout /−15|false|true|true|

The resistant-child case is an expected escalation test, not a graceful-cleanup pass. Timeout remains a failed execution even when group cleanup succeeds. Recorded child-ready/TERM files, per-signal journal, unreaped leader state, final scan and unchanged sentinel identity support these distinctions. Group scans are observations, not an atomic kernel-wide proof; non-atomic /proc races are logged and a final live/unknown observation prompts bounded cleanup before reap.

## Review and verification

The initial module-missing test failed before implementation. First unit run exposed a Windows synthetic-test use of unavailable `signal.SIGKILL`; the Linux numeric constant was used explicitly without changing the intended signal. Independent review identified3 Important findings (unrelated kernel zero-group records, late live member after an apparently drained scan, and new supervisor-error ULog retention), plus clock/reap interruption gaps under active development. Eight focused new cases failed before fixes and then passed. Subsequent ULog boundary audit added four RED→GREEN cases for abrupt exit, unknown exit, existing evidence and copy failure;66 targeted tests pass. No Critical findings. The extra capture-level retention hardening followed the real process harness and was tested synthetically; no physical or harness rerun is claimed. Initial full regression937 passed; final full regression941 passed with two existing loader warnings. Changed Ruff passes; whole-repository lint retains50 errors in32 unchanged files. The lifecycle report does not claim whole-repository lint success.

| Status | Scope |
|---|---|
| Verified | Synthetic identity/scan/signal/journal/refusal paths; four real owned-group studies, complete action journals, unrelated sentinel protected, final groups absent. |
| Implemented | Real supervisor integration, unreaped-leader ownership, bounded signal evidence, error retention and stricter capture success gate. |
| Untested | New supervisor under actual PX4/Gazebo native-fault capture; real ULog fallback under supervisor error; escaped descendants. |
| Retained failures | PR44 all-descendant historical cleanup unknown; prior VIO drift, contact aliasing, startup failures and five-camera0.873RTF<0.95. |

Next design one independently named, prospectively frozen short native-fault capture using this supervisor; verify the owned group's signal outcomes, ULog, zero-force refusal and post-reap absence without backfilling PR44. After that, integrate composite readiness and shadow input delivery for the supported-motion online VIO study. Do not relax public initialized, quality/reset/covariance or fusion gates.
