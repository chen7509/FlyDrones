# Fixed Fast-DDS Gitlink Objects Plan

**Goal:** Make the four Fast-DDS gitlink source objects locally verifiable while keeping actual build selection and Agent runtime unqualified.

**Spec:** [source audit design](../specs/2026-10-10-fastdds-gitlink-objects-design.md)

## Task 1: Bind and fetch

- [x] Record current process/memory preflight and inspect the fixed parent `.gitmodules`, tree, Agent superbuild and Fast-DDS CMake options.
- [x] Write RED/GREEN tests for parent path/URL/object binding and exact local commit identity.
- [x] Fetch each fixed object to a separate bare store, retaining all failures and read-back IDs. Asio needed one same-SHA retry after a recorded TLS EOF.

## Task 2: Audit provenance and selection limits

- [x] Inventory fixed-tree license paths, root and nested gitlinks, build fetch declarations, current metadata and source sizes.
- [x] Run an independent Git-object read-back and `fsck`; targeted tests and changed-file checks complete at publication gate.
- [x] State clearly that the four objects close only their own gitlink references. Wider default Agent source/system closure and build selection remain unverified.

## Task 3: Publish evidence

- [ ] Seal all fixed source objects, failure logs, exact hashes, report and checks; independently verify every archive member.
- [ ] Review, commit and push only to `personal`; update draft PR65 and the continuing automation with remaining gaps.
