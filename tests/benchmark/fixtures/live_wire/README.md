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
