# Depth-mask-v3 full MaleCNS initialization

The previously frozen full MaleCNS initialization is 12-channel and untrained. A separate 15-channel `depth-mask-v3` initialization can now be derived without loading its 25,582,837-edge graph. It retains the 166,700-neuron identity, 17,268 sensory neuron indices and 33 output neuron indices. The 17,268 sensory assignments are deterministically reassigned modulo 15 so every feature, including the three depth-validity channels, is represented. No learned gains, biases or readout are transferred.

The command pins the legacy manifest SHA-256 `55f7648a9009d6f450543b5cdc456b9d47ed26dccfe7e2592adcde3f5a7cfe35`, its parameter NPZ SHA-256 `a44d445e3dd0fa6c477c00dafd845ee5323ebfd8e21321f36318244acb954691`, and the MaleCNS source-file SHA-256 `b6be8b3dd901e2e0893303c04058a110d6e0fb9922a69022b26514efcf06100c`. It rejects non-default trainable values, wrong feature/output order or legacy mapping, verifies the saved destination by reloading, and refuses overwrite. The old files' hashes were unchanged after derivation. The new files are `results/connectome-training/stage-b/full-initialization-depth-mask-v3/{manifest.json,parameters.npz}` with SHA-256 `bb1cf71cdd1aaf65da8c2c0aa20605de4bf479d28361082d1338564bfd099caa` and `a7db2788633ee20ddbbc199de9ddf9b5ec771fda6d430efd8bf6262271aa2299`. New mapping digest: `f37eb99178974e8273bbd3bffe767a88872537778edba52e878d95830e63d26b`.

The source topology digest is inherited from the old verified builder; this run did not independently rebuild the graph. The modulo-15 assignment is a project-specific engineering mapping, not neurobiological evidence. This artifact is untrained and cannot establish policy quality, training speed, inference latency, collision avoidance or safe flight. Live non-truth PX4 EKF2 plus calibrated-camera observations and a checked EGO teacher corpus are still absent. Host free memory was 0.57–0.97 GiB during this stage, below the 4 GiB full MaleCNS probe gate; no Docker container, PX4, Gazebo, OpenVINS or full training was launched.

## Verification and status

Eleven new tests passed for deterministic mapping, 15-feature coverage, wrong/trained/malformed source refusal, source/model hash refusal, destination overwrite refusal and save/load identity. An initial adjacent-suite run with a relative `PYTHONPATH=src` reported 298 passed, 1 skipped and 2 unrelated subprocess import failures (`No module named 'tools'`); its failure remains part of the record. It is not a passing suite. The absolute-path rerun after the review fix reported **302 passed, 1 skipped, 1 existing PyTorch warning**. An independent read-only review identified a malformed-shape gap in the pure derivation; two new tests failed before a fix and passed after complete source validation. Changed-file Ruff and `git diff --check` passed. The generated artifact's mapping digest also matched a derivation performed with final code; the existing destination was not overwritten. The full repository suite was not repeated because current free memory is far below the full-model gate and this change is limited to the connectome-training package.

| Status | Boundary |
| --- | --- |
| Verified | A separately saved, loadable 15-feature untrained initialization with fixed source bytes and unchanged legacy files; 302 adjacent tests and 11 new focused tests. |
| Implemented only | Memory-light derivation command and failure checks; no full-graph construction in this stage. |
| Not tested | Full-model training, genuine observation corpus, learned policy, physical sensing/fusion, actual flight and multi-drone performance. |
| Failed or blocked | First adjacent-suite invocation failed on relative subprocess import paths; full training remains blocked by memory and source data. |

This stage does not change the earlier five-camera WSL2 0.873 RTF result against the 0.95 gate, the frozen PX4 TIMESYNC failure, or any historical physical and learning failures.
