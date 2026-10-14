# Mission state safety implementation plan

Use executing-plans inline and TDD under the user's existing autonomous authorization.

Goal: prevent malformed local state from producing mission motion or new local tasks, and retain deterministic lease handoff without heavy model or simulator execution.

Design: validate tuple/list finite real three-vectors, battery in [0,100], finite nonnegative depth age and an exact bool localization flag before local detection/relay work. Invalid values latch existing emergency, stop intent and release only an owned active lease once. Valid localization false and existing stale-depth/battery/geofence thresholds keep their existing actions. Continue safe inbound ledger merges, refusing numeric conversion overflow, but only nominal state may create detection/relay work. Use a scaled norm for large finite return vectors. This does not authenticate telemetry or install a new health producer.

- [x] Reproduce NaN depth age bypass, malformed state and unsafe local task creation; test neighbor takeover and terminal latch using actual MissionAgent/TaskLedger objects. Initial21RED, later4vectorRED+1peerRED retained.
- [x] Implement bounded numeric checks and safety ordering in existing mission_agent.py; no new dependency or model load. Independent review's three Important cases addressed with actual failing cases before correction.
- [x] Run focused and adjacent mission/ledger/contract/UDP tests sequentially; preserve RED and GREEN. Final87 passed, Ruff/diff passed. No broad/full-model/physical run.
- [x] Independently review and seal evidence with hashes/CRC; final code and 31-member archive review found no Critical/Important/Minor findings. Report exact software boundaries; publication uses only personal and PR65. Automation advances low-memory dependencies under original authorization.

Full MaleCNS learning, real calibrated sensor/source health, PX4 safety execution and physical recovery remain separate required stages. This fix is not their substitute.

The immutable evidence archive retains the pre-publication plan with Task4 pending. This later ledger records review/publication preparation without rewriting that archive or the earlier failures.
