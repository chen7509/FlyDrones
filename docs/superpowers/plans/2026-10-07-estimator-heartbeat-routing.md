# Estimator-aware heartbeat routing correction plan

**Goal:** Diagnose and correct the source-sequence-426 heartbeat refusal from the immutable `study-v11/capture-v1` attempt without running another simulation.

**Spec:** `docs/superpowers/specs/2026-10-07-estimator-heartbeat-routing-design.md`

- [x] Preserve and inspect the exact failed record, fan-out dispositions, heartbeat journal, result, ULog, supervisor evidence, and process cleanup.
- [x] Trace the failure through `EstimatorJournaledHeartbeatFanout._after_shadow` and `EstimatorAwareReadiness.observe_ack_batch`; freeze the correction contract before implementation.
- [x] Add a failing regression for the exact no-`sample_ns` heartbeat and a refusal case for heartbeat-associated native acknowledgements.
- [x] Implement the narrow routing correction; retain strict sampled-source validation for estimator acknowledgements.
- [x] Run targeted and full regressions, lint changed Python, and independently audit the immutable attempt classification and correction claims.
- [x] Update the stage report and validation ledger and seal evidence with member hashes/CRC. Commit/push PR65 and monitor update follow; no physical retry is part of this stage.
