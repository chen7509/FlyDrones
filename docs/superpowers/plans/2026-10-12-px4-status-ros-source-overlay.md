# PX4 EstimatorStatus ROS source overlay plan

**Goal:** Prepare an exact, provenance-bound ROS message source candidate for
the pinned PX4 status topic without modifying or relabeling the old ROS tree.

**Design:** [spec](../specs/2026-10-12-px4-status-ros-source-overlay-design.md)

1. [x] Confirm the real v2 parent passes its existing verifier, record both
   message hashes and the single-constant diff; keep current processes and
   memory gates unchanged.
2. [x] Write RED tests for a v3 overlay derivation and verifier on a synthetic
   parent: only one file changes, parent stays byte-identical, wrong pins,
   changed/linked parent or output, duplicate destination and profile drift
   refuse.
3. [x] Implement minimal derivation and strict v3 verification in the existing
   build-source module; run focused tests GREEN and affected regression.
4. [x] Create one real exclusive derived source tree, verify its 260-file
   manifest and exact replacement, record source-only limitations, changed
   Ruff/diff, independent review and sealed evidence with CRC/member hashes.
5. [x] Commit and push only to `personal`, update PR65 and the continuing
   automation. A later build and typed status subscriber require new bounded
   execution evidence, not a relabel of this source check.
