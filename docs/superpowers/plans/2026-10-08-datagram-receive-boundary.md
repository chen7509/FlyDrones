# Datagram receive boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans inline with TDD and a final independent review.

**Goal:** Replace caller-invented receive envelopes with a bounded direct recvmsg adapter, verified offline only.
**Architecture:** One supplied socket, existing external session guard, immutable packet return; no socket factory, sender, simulation clock inference or live qualification.
**Tech Stack:** Python3.12, stdlib socket metadata/recvmsg API; injected test sockets only.
**Spec:** docs/superpowers/specs/2026-10-08-datagram-receive-boundary-design.md

## Global Constraints
- No actual UDP/socket creation, PX4/Gazebo/OpenVINS, ODOMETRY, mutations, arming or training study.
- Exact127.0.0.1 local14548/peer14588;4096bytes,8s global/2s syscall bound,8192events.
- Every sender-process/network/live/fusion qualification remains false.
- Preserve evidence; only personal remote and existing draftPR65.

## Review Focus
- Received bytes survive post-receive clock/guard/journal failure.
- Callback reentry cannot consume another packet or release an envelope after refusal.
- Empty UDP packet differs from EAGAIN; no silent retry/truncation.
- Supplied socket/peer/guard do not prove producer PID, kernel arrival or simulation time.
- Cap exhaustion refuses before consuming input, without losing a returned packet record.

### Task 1: Read boundary and offline fault matrix
**Files:** tools/benchmark/openvins_datagram_receive.py; tests/benchmark/test_openvins_datagram_receive.py.
**Interfaces:** DatagramReceiver.poll→ReceivedDatagram or None; evidence retains returned data/failure and false authority.
- [ ] Retain fixed API/source/license/reuse research.
- [ ] Write synthetic normal/boundary/fault cases; record initial RED accurately.
- [ ] Implement bounded adapter and pass tests; no real socket operations.
- [ ] Final read-only review and one Important/Critical RED→GREEN pass.
- [ ] Full pytest, changed Ruff/diff; preserve counts/skips/failed counterexamples.
- [ ] Report and exclusive evidence/hash/CRC, commit/push personal, update/verify/attach PR65.

## Ruling
User explicitly preapproved every routine step; no repeated plan approval. Current authority remains offline. Do not extend this stage to a real network study just because code can accept a real socket.
