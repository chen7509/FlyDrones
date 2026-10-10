# Mask-aware connectome input profile (2026-10-09)

## Outcome

The checked v3 depth archive now has an explicit path into the connectome learner and offline inference controller. The new `depth-mask-v3` profile contains three valid-only inverse-depth sector medians, three sector validity fractions, and the nine existing motion, luminance and goal features. A sector with no measurement contributes zero depth and zero coverage; an image with no valid depth is refused. Missing pixels are never filled with inferred distances.

The legacy 12-feature profile remains the default. Parameter artifacts select exactly one ordered feature tuple, and a v3 mapping must cover all 15 channels. The v3 version and order enter the mapping digest, which also binds curriculum identity and checkpoint metadata. Training, evaluation and offline inference select features from that identity; v1 and v3 frame or checkpoint crossing is refused. The controller still returns only a bounded intent marked `flight_eligible=false` and does not publish to PX4.

## Verification

The new feature, mapping, curriculum, artifact and controller tests first exposed missing v3 support, then passed after implementation. A read-only independent review found no Critical or Important defect. Its two test-coverage findings were addressed with bidirectional v1/v3 checkpoint refusal and malformed v3 RGB/state cases. A further RED test showed that adding a null mask to the image digest changed legacy inference evidence; the final implementation keeps the old two-array digest exactly and adds a version marker plus mask bytes only for v3.

The first connectome suite had **286 passed, 1 skipped, 1 failed**: the unchanged bounded-output Docker inspection test timed out. That test passed alone on immediate rerun. An initial repository suite was stopped at 27% when an unrelated ADS test process began competing for the host's limited memory; its partial log is retained and is not a pass. After that process exited, the final full repository run finished with **4086 passed, 36 skipped, 3 warnings, 0 failed** in 578.93 seconds. The warnings are duplicate ZIP member construction in a rejection test, PyTorch sparse checkpoint validation, and missing legacy MaleCNS groups. Changed-file Ruff and `git diff --check` passed.

The sealed evidence package is `evidence/mask-aware-connectome-feature-dev-1701.zip`; its adjacent `.sha256` file records the package digest. The package includes source and tests, spec and plan, report, the initial failures, the interrupted run, final test logs, and independent review notes. Each member has a SHA-256 and ZIP CRC verification. It contains no physical or full-model training result.

## Boundaries and next dependency

| Status | Evidence boundary |
| --- | --- |
| Verified | Synthetic v3 feature extraction, tiny-core train/evaluate and offline inference parity; legacy hash/identity compatibility; final repository regression. |
| Implemented only | Full-curriculum profile selection and early sequence refusal; no full MaleCNS execution on v3 data. |
| Not tested | Real non-truth v3 corpus, full-model training speed and checkpoint, live EGO guidance, PX4 fusion, multi-drone performance. |
| Failed or stopped | Initial bounded-output test timed out under load but passed alone and in final suite; first full repository run was deliberately stopped during independent ADS testing. Both logs are retained. |

All v3 input and training tests use synthetic tiny models and arrays. They do not show a trained full MaleCNS policy, a real EGO teacher corpus, improved training speed or decisions, PX4/EKF2 fusion, safe flight, or a fair real-source comparison. The repository still lacks a deployed observation producer binding live PX4 EKF2 state, calibrated camera frames and pinned EGO planner output without truth leakage. Docker availability alone cannot fill that gap. The full model memory gate is also not met on this host at the latest check.

The next independent step is that live, provenance-bound capture adapter, followed by validation of a v3 corpus and full-model resource probe before training. Historical failed physical runs and the frozen five-drone RTF failure remain unchanged.
