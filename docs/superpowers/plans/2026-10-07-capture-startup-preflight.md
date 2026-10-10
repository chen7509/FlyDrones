# Capture Startup Preflight Plan

- [x] Preserve and independently audit the `study-v5/capture-v1` startup refusal and cleanup evidence.
- [x] Add RED/GREEN coverage for optional declared environment keys in `RuntimeBinding.start`.
- [x] Add an opt-in capture CLI startup-preflight path that stops before TestFixture/PX4/OpenVINS/force.
- [x] Require complete declared inputs and propagate the flag through the real supervisor worker command.
- [x] Generate and independently audit a new prepare-only package, then run one non-physical startup preflight at a new destination.
- [x] Seal the final current-code package and preflight evidence after commit; do not start another physical target in this plan.
