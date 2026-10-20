# Retained startup-only negative fixture

`installed-startup-result.json` is an exact byte copy of
`results/installed-wire-startup-dev-1701/study-v1/startup-preflight-v1/result.json`.
SHA256: `bea9ffb42b6a412ab757f1ad1d036e8db17c4871d63e17fec2441dcaeb6d930c`.

It records `capture_completed` for startup preparation only, explicitly marks
`startup_preflight_only=true` and `estimator_run=false`, and has no completed
physics/owned-runtime coverage. It must never qualify as a full live-wire run.
The adapter test places these unchanged bytes under a synthetic prospective
manifest to exercise the result gate, rather than merely rejecting an old
manifest schema. This relocation is test setup, not a new physical capture.

## Retained anchor subset

`retained-anchor-subset.json` contains original selected records from
`results/openvins-health-physical-dev-1701-v2/development-seed-27201/capture-v1`.
SHA256: `421c15f47dc7ff9e91891369df69ccbc08a8c1f5bc25ce894899dba93e0117d5`.
Sources 403/674/675/677, their fan-out records, the first heartbeat observation
and reconciliation, camera acknowledgement 626 and its estimator readiness
record are included with the saved anchor. The extractor/provenance in
`results/live-wire-study-audit-dev-1701/anchor-fixture-provenance-v1.json`
records all six original input file hashes. This subset exercises attribution
and independent corruptions; it deliberately cannot establish complete capture
coverage. The independent fixed-input audit consumes the full six source files.
