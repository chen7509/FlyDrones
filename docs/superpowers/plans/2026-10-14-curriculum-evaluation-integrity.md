# Curriculum evaluation integrity plan

Use executing-plans inline and TDD under the existing autonomous authorization.

Goal: protect the actual curriculum promotion, regression rollback and persisted counters without loading or training the full MaleCNS graph.

Design: accept finite real loss values only (exclude bool/strings), require an exact bool parameters_finite, and refuse coercive training counters while preserving nonnegative integer values, existing omitted-counter zero defaults and thresholds. A completed-stage regression with parameters_finite=False must prevent promotion, retain the failed candidate/report and restore the best checkpoint. A nonfinite current candidate must never be latest for resume: restore best if present, otherwise record FAILED/latest=null. Malformed metrics/counters refuse before candidate publication or state commit. Existing valid evaluation, resume and checkpoint behavior must remain compatible. No model/source/teacher authority is added.

- [x] Reproduce invalid flag/loss/counter coercion and ignored regression-finite failure using actual run_curriculum/StateStore with deterministic protocol sessions. Initial11failed1passed; review2failed retained.
- [x] Implement bounded validation and rollback gate correction in curriculum.py; address independently reproduced nonfinite resume defect.
- [x] Verify current-failure candidate retention, completed-stage rollback, valid promotion/resume and adjacent config/state behavior; final33passed1.31s/style/diff. Preserve original failures and 48 actual protocol artifact files.
- [x] Independent code and 75-member archive review found no Critical/Important/Minor. Immutable hash/CRC evidence and report complete; publication uses personal/PR65 and keeps automation on low-memory dependencies. No actual complete-model training was performed.

The immutable archive retains the pre-publication Task4-pending plan. This later publication ledger does not rewrite that archive or any original failure.
