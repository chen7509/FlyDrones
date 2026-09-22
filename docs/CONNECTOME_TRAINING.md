# Connectome-constrained training

The 2026-09-22 formal comparison is immutable evaluation evidence. New training artifacts live under `results/connectome-training/` and never consume the formal episode directory.

Run the deterministic contract tests:

    $env:PYTHONPATH='src'; python -m pytest tests/connectome_training -q

Profile the complete MaleCNS controller:

    $env:PYTHONPATH='src'; python tools/connectome_training/profile_baseline.py

The generated JSON separates total, neural and residual overhead latency and evaluates the 35 ms P95 Stage A gate. A failed gate is retained as a baseline result.

## Stage B offline training gate

Install the separate training dependency without changing the frozen project dependency manifest:

    python -m pip install -r requirements-connectome-training.txt

Run the deterministic offline sequence-learning gate:

    $env:PYTHONPATH='src'; python tools/connectome_training/train_stage_b.py --epochs 80

Initialize the allowed shared parameters against the complete frozen MaleCNS structure:

    $env:PYTHONPATH='src'; python tools/connectome_training/train_stage_b.py --initialize-full

The smoke artifact proves that the differentiable topology-constrained path can reduce held-out sequence loss. It is not a flight-success result. The full initialization artifact binds the permitted input gains, cell-type biases, global membrane time constant and descending readout to the 166,700-neuron, 25,582,837-connection model; it does not claim that full-model optimization has run.

PX4/Gazebo closed-loop training remains gated on a separate plan. The old formal comparison and its manifest-covered files remain unchanged.
