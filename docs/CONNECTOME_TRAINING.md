# Connectome-constrained training

The 2026-09-22 formal comparison is immutable evaluation evidence. New training artifacts live under `results/connectome-training/` and never consume the formal episode directory.

Run the deterministic contract tests:

    $env:PYTHONPATH='src'; python -m pytest tests/connectome_training -q

Profile the complete MaleCNS controller:

    $env:PYTHONPATH='src'; python tools/connectome_training/profile_baseline.py --output results/connectome-training/stage-a/baseline_profile_v2.json

Choose a new output path for each run; existing evidence is refused rather than
overwritten. The v2 JSON retains per-call external start/end timestamps and
evaluates the 35 ms P95 Stage A gate using the external synchronous `step` call
duration. Controller-reported total, neural and residual overhead are separate
diagnostics. Fake controllers and undersampled runs cannot qualify as complete
MaleCNS latency evidence. A failed gate is retained as a baseline result.

This profiles the fixed `Brain/LIFNetwork` controller on synthetic black images,
not a trained `ConnectomeConstrainedCore` checkpoint or sensor-to-actuator flight
latency. See [the measurement correction and remaining gaps](CONNECTOME_LATENCY_CONTRACT_REPORT.md).

## Stage B offline training gate

Install the separate training dependency without changing the frozen project dependency manifest:

    python -m pip install -r requirements-connectome-training.txt

Run the deterministic offline sequence-learning gate:

    $env:PYTHONPATH='src'; python tools/connectome_training/train_stage_b.py --epochs 80

Initialize the allowed shared parameters against the complete frozen MaleCNS structure:

    $env:PYTHONPATH='src'; python tools/connectome_training/train_stage_b.py --initialize-full

The smoke artifact proves that the differentiable topology-constrained path can reduce loss on a separately generated validation sequence. Its report records distinct hashes for the training and validation feature tensors. It is not a flight-success result. The full initialization artifact binds the permitted input gains, cell-type biases, global membrane time constant and descending readout to the 166,700-neuron, 25,582,837-connection model. Its hashed parameter archive also records the exact feature-to-sensory-neuron and readout-neuron mappings needed to reconstruct the model. It does not claim that full-model optimization has run.

PX4/Gazebo closed-loop training remains gated on a separate plan. The old formal comparison and its manifest-covered files remain unchanged.

## Resumable offline curriculum

Run one bounded smoke batch, then resume the same run:

    $env:PYTHONPATH='src'; python tools/connectome_training/run_curriculum.py --profile smoke --max-batches 1
    $env:PYTHONPATH='src'; python tools/connectome_training/run_curriculum.py --profile smoke

The default behavior resumes the last atomically committed batch. Use `--restart` only to intentionally replace that output directory. The smoke profile uses a labelled tiny synthetic connectome and proves recovery, promotion, regression checks, and checkpoint integrity; it is not evidence that the complete MaleCNS model can fly.

The `desktop` and `full` profiles require the versioned train and validation sequence directories declared in `configs/connectome_curriculum_v1.yaml`, the complete MaleCNS source, and a `full-male-cns` parameter artifact. Missing evidence fails closed. These profiles train `ConnectomeConstrainedCore` parameters and never substitute the PPO multi-task actor.
