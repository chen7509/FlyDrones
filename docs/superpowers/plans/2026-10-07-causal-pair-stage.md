# Causal camera-pair stage plan

- [x] Record fixed upstream versions, licenses, maintenance metadata and exact-time/IMU-queue source evidence.
- [x] Add exact `study-v9` and stage-boundary tests; run them against current code and retain the expected RED output.
- [x] Implement the minimal stage-aware 250 ms expiry without changing limits, ordering, capacity, watchdogs or fusion gates.
- [x] Run focused GREEN tests and a fixed `study-v9` replay with source identities and original RGB bytes.
- [x] Add an independent audit covering normal, boundary and fault cases; run targeted and full regression.
- [x] Seal evidence, update the report and PR, and keep physical execution unauthorized.
