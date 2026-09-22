# Connectome-constrained training

The 2026-09-22 formal comparison is immutable evaluation evidence. New training artifacts live under `results/connectome-training/` and never consume the formal episode directory.

Run the deterministic contract tests:

    $env:PYTHONPATH='src'; python -m pytest tests/connectome_training -q

Profile the complete MaleCNS controller:

    $env:PYTHONPATH='src'; python tools/connectome_training/profile_baseline.py

The generated JSON separates total, neural and residual overhead latency and evaluates the 35 ms P95 Stage A gate. A failed gate is retained as a baseline result.
