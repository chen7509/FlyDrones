# Fixed XRCE Typed Odometry Diagnostic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Obtain a bounded, reproducible synthetic `VehicleOdometry` sample across fixed XRCE Client → rebuilt Agent → existing ROS 2 collector, or preserve a precise failure without overstating PX4 provenance.

**Architecture:** A test-only C client uses the fixed PX4 topic/type/QoS contract and the body of a sealed synthetic CDR. A small Python harness freezes the exact binaries, starts only owned processes in one offline Docker container, captures XRCE/entity/typed callback evidence, and checks journal CDR parity and cleanup.

**Tech Stack:** Pinned C Micro-XRCE-DDS Client d44dc3f, Agent v2.4.3 runtime bundle, ROS 2 Humble with CycloneDDS and Fast DDS development conditions, pinned `px4_msgs` collector, Python 3.12, Docker/WSL2.

**Spec:** `docs/superpowers/specs/2026-10-12-xrce-typed-odometry-design.md`

## Global Constraints

- No PX4, Gazebo, OpenVINS, trainer, network egress, arming or ODOMETRY injection.
- Image `sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a`; Agent bundle SHA-256 `4279d999c02836e3f7076e948d2e92aefcc08bf62ea8c0e3e597dde2896c3262`.
- Fixed PX4 topic `rt/fmu/out/vehicle_odometry`, DDS type `px4_msgs::msg::dds_::VehicleOdometry_`, message version 0, best-effort writer as in generated fixed PX4 source; frozen v6 CDR is synthetic only.
- Host free >=1.5 GiB, container max 1 CPU/768 MiB/128 PID, outer 30 s; source and binary read-only, versioned evidence paths never overwritten.
- No successful classification from `sendto`, client exit or Agent log alone; require typed callback, exact CDR parity and owned cleanup. Never set `px4_source_authenticated` or `fusion_qualified` true.

**Execution amendment:** Attempts use immutable, uniquely named runners under `results/xrce-typed-odometry-dev-1701*` instead of one reusable `run.py`. The typed callback and CDR result is verified for v8–v10, but the historical Windows/WSL Docker daemon identity is not, so the owned-cleanup requirement is **not fully satisfied**. The report keeps this separate from callback validity. Missing-Agent testing had a bounded outer timeout; the C client has no independent internal no-Agent deadline.

## Review Focus

- CDR encapsulation: strip exactly the first four bytes before XRCE write; check resulting callback CDR against the frozen full CDR.
- DDS type/topic/QoS drift: reject any mismatch with generated fixed PX4 values instead of trying alternative names or weaker QoS after observing failure.
- Delayed discovery: actual readiness and one bounded send; do not repeat a stale sample to manufacture a passing rate.
- Partial process failure: preserve raw Agent/client/collector logs, journal terminal state, signal sequence and container cleanup.
- Synthetic attribution: collector GID and data cannot be mistaken for a PX4/ULog source or eligible training input.

---

### Task 1: Freeze inputs and test-only client contract

**Files:**
- Create: `tools/connectome/xrce_typed_probe/client.c`
- Create: `tools/connectome/xrce_typed_probe/CMakeLists.txt`
- Create: `tests/test_xrce_typed_probe.py`

**Interfaces:** Client consumes a fixed hex payload file and `127.0.0.1:<port>`; it prints structured session/entity/send status and exits nonzero on refusal. It does not expose a product control API.

- [ ] Write failing tests for the exact four-byte encapsulation, CDR hash, invalid payload, wrong topic/type/version, and nonzero status refusal.
- [ ] Implement the C client with pinned XRCE APIs and binary entity creation; match fixed PX4 QoS and one send.
- [ ] Compile with `-Wall -Wextra -Werror`, run fixed/negative tests and record exact source hash.

### Task 2: Bounded offline build and owned runtime harness

**Files:**
- Create: `tools/connectome/xrce_typed_probe/run.py`
- Extend: `tests/test_xrce_typed_probe.py`
- Write attempt records under a new `results/xrce-typed-odometry-dev-1701[-vN]` directory.

**Interfaces:** The harness emits `preflight.json`, per-process logs, `result.json`, and a fail-closed `audit.json`; no data or health flows back to PX4.

- [ ] Test preflight refusal for changed image/bundle/collector/message/CDR, low memory, competing process, occupied port and nonempty evidence path.
- [ ] Build the client offline in an owned 1-job, bounded container from read-only fixed source/install; verify binary hashes and loader closure.
- [ ] Start Agent, collector and client in one `--network none` container with actual readiness, 30 s bound and per-child cleanup; preserve any failure.
- [ ] Run missing-Agent and malformed-input refusals separately from the successful attempt, each in a uniquely named evidence directory.

### Task 3: Evidence review, report and publication

**Files:**
- Create: `docs/XRCE_TYPED_ODOMETRY_DIAGNOSTIC_REPORT.md`
- Create: `results/xrce-typed-odometry-dev-1701*/audit.py` and `seal.py`
- Create: `evidence/xrce-typed-odometry-dev-1701.zip`

- [ ] Independently compare Agent session/entity logs, typed sample/finish, full CDR and fields against frozen v6 data, all hashes, deadlines, and owned process/container release.
- [ ] Run targeted tests, adjacent ROS/CDR regression tests, changed Ruff and `git diff --check`; preserve failures.
- [ ] Write verified/implemented/untested/failed table, seal every original attempt with member SHA-256 and CRC, commit and push only `personal`, then update draft PR65.
