# Causal pair corrected physical attempt plan

- [x] Re-audit `study-v10` from the committed tree; retain its pre-dispatch `binding baseline` refusal after the declared auditor changed, with `capture-v1` absent.
- [x] Generate and audit a fresh `study-v11`, run one separate non-physical startup preflight, and reject any further declared-file drift.
- [x] Record a one-shot dispatch and run the production command exactly once at `study-v11/capture-v1`.
- [x] Record completion and post-run resource evidence without overwriting or retrying the target.
- [x] Independently audit the complete outcome, classify the heartbeat-routing refusal precisely and keep all downstream claims closed.
- [x] Seal the physical-attempt and fixed-input routing-correction evidence and update the report. PR/monitor updates follow the commit; no retry is part of this stage.
