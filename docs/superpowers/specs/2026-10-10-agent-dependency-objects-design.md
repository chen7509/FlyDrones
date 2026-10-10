# XRCE Agent dependency-object provenance design

## Purpose

Turn the five observed Agent superbuild dependency IDs into locally verifiable Git source inputs, without building software or changing the selected Agent features. The previously sealed Agent source candidate and its failures remain unchanged.

## Fixed inputs and boundary

Use the exact IDs in `prepare_pinned_xrce_agent.py` for Fast-CDR, Fast-DDS, foonathan/memory, spdlog, and XRCE Client. Fetch into separate bare Git repositories in a new results directory; never resolve a moving branch during qualification or use an existing system package as a substitute. Disable Git replacement refs for verification. Capture requested URL/ID, actual fetched object type, commit/tree IDs, raw license blob and hash, tree entry modes, gitlinks/submodules, and direct build-time fetch declarations. A failed or partial fetch remains a failed input, not a qualified dependency.

This stage qualifies only the direct source objects. A commit exists locally does not prove transitive closure, compiler compatibility, Linux permissions, runtime ABI, built executable, or PX4 interchange. The optional XRCE Client remains in the set because the selected default Agent P2P profile is on. Googletest is conditional on CI tests and must be recorded as conditional, not silently treated as part of the default binary.

## Evidence and safety

Record exact command, exit, stdout/stderr, UTC observation, object IDs, license evidence, source size and submodule/fetch findings. Avoid a full build while host free memory is low. Preserve all failures. A future build requires an independently frozen transitive closure, resource budget and isolated Linux compiler/link environment; it does not inherit qualification just because these direct objects are fetched.
