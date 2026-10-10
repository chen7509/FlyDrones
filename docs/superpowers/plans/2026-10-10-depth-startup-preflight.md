# Startup-only raw-depth binding verification

**Goal:** Test study-v5's real worker prebinding path without physical simulation.

**Reuse:** Existing capture parser, exact execution contract, runtime binding, `--startup-preflight` early return and owned worker supervisor. No new simulator or control path.

1. [x] Recheck processes and confirm the early return remains before TestFixture/PX4 startup; freeze source manifest and an exclusive new output.
2. [x] Derive exact startup command with unchanged study-v5 declaration, run only once, retain all raw evidence even if it fails.
3. [x] Independently audit result, binding, process cleanup and absence of physical evidence; run relevant regression, write report, seal ZIP, commit and update draft PR65. Preserve study-v3 failure and do not promote this check to physical success.
