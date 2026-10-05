# Disarmed motion readiness implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline, task-by-task; one fresh whole-branch review at the end.

**Goal:** Obtain reviewable evidence of fixed OpenVINS readiness under a bounded physically coherent disarmed excitation.
**Architecture:** A deterministic1ms force policy and separate Gazebo fixture monitor extend the existing online capture. Only raw sensors reach VIO; simulator truth is isolated for fixture abort/audit.
**Tech Stack:** Python, installed Gazebo8.15, pinned PX4/OpenVINS/pymavlink.
**Spec:** docs/superpowers/specs/2026-10-06-openvins-motion-readiness.md

## Global Constraints

Standing user authorization covers design, execution, review, evidence and draft PR; no repeated approval. Keep existing load, ZUPT/public gate, noise config and all failures. No other task, competitor simulation or installation. Source truth never enters VIO. Preserve ledger and evidence.

## Review Focus

Paused/gapped update clocks; partial fixture construction cleanup; stale/armed heartbeat during an active pulse; force-call/recording failure after a command; separation of ground truth from raw sensor/native data and claims made from incomplete runs.

### Task 1: Fixed force and containment contract

Interfaces: tools/benchmark/disarmed_motion_probe.py exposes a deterministic policy and Gazebo callbacks; capture_disarmed_sensors adds an optional fixed profile.
- [x] Record version/license/maintenance/API source research, source hashes and prospective force profile before running.
- [x] Write and observe failing tests for impulse/timing, heartbeat, clock, finite-state and spatial/speed/attitude rejection.
- [x] Implement policy and isolated monitor, retaining latching failures and owned output closure; run focused GREEN.

### Task 2: Online measurement and audit

Interfaces: existing capture supervisor and sensor/native pipeline remain; optional motion callback uses the same scene and fresh per-step API.
- [x] Integrate optional profile and10ms supervisory stepping; validate setup/termination paths.
- [x] Freeze versions/config/code, preflight processes, run one25s requested physical attempt; retain any failure.
- [x] Audit force timing/impulse, actual motion and sensor response, native/public states, actual latency, disarmed ULog and resource release. Do not infer health from public flag alone.

### Task 3: Review and publication
- [x] Run applicable regression and update verified/implemented/untested/failed report.
- [x] One independent whole-branch review, one RED→GREEN correction pass with full regression if needed.
- [ ] Seal all evidence, commit and publish stacked draft PR against PR36, attach and update existing heartbeat to the actual next dependency.
