# Execute frozen clone motion audit

1. Add synthetic tests for parsing clone pose records, frame direction, exact
   observation matching, malformed/duplicate poses, and relative motion under
   an arbitrary common global gauge. Run red before implementation.
2. Add logging-only clone-pose output immediately before upstream feature
   initialization in the isolated diagnostic checkout. Rebuild ROS-free
   `ov_msckf_lib` and replay the frozen 604-frame input once. Verify exact
   original state CSV SHA-256 and 1001 observation-pose matches.
3. Implement the offline comparator using the previous audited EKF2 pose
   interpolation and fixed extrinsic. Score all 183 attempts into a CSV plus
   aggregate JSON. Record clone and EKF2 ray geometry separately, relative
   rotation/translation/baseline discrepancies, and every invalid case.
4. Preserve trace, source patch, library/input/config hashes, all outputs and
   failures in a non-overwriting indexed ZIP. Write a report that distinguishes
   development-data diagnosis from visual fusion or flight readiness.
5. Run focused tests, Ruff, `git diff --check`, and full regression with the
   current worktree's `src` on `PYTHONPATH`; diagnose failures. Commit and
   request read-only review before creating a draft PR on the geometry branch.
