# Fixed XRCE Agent dependency objects: local provenance

The five direct superbuild IDs in the [pinned Agent source](PX4_AGENT_PINNED_SOURCE_REPORT.md) have now been fetched into **separate bare Git stores** and verified locally as commits. Their fetched IDs, protected local refs, trees, root `LICENSE` blobs and tree entries were read back with Git replacement refs disabled. A second script independently re-read the objects and ran `git fsck --full --no-reflogs` on each store. This is source provenance, **not** transitive closure, a binary build, a PX4 handshake, or EKF2 fusion.

The [design](superpowers/specs/2026-10-10-agent-dependency-objects-design.md) and [plan](superpowers/plans/2026-10-10-agent-dependency-objects.md) used the exact IDs observed in the previous Agent source study. No moving branch was selected during fetch. GitHub repository metadata was observed on 2026-10-10 UTC and saved with the evidence; a repository's current activity does not establish the maintenance or compatibility of these historical commits. No Agent, PX4, Gazebo, Docker build, OpenVINS or trainer ran in this stage. Host free physical memory at the final snapshot was about 1.15 GiB, so no compiler/link step was attempted.

| Input | Exact local commit / tree prefix | Root license | Findings |
| --- | --- | --- | --- |
| [Fast-CDR](https://github.com/eProsima/Fast-CDR) | `757d5e4` / `ae95785` | Apache-2.0 | 106 tree entries; no gitlink. |
| [Fast-DDS](https://github.com/eProsima/Fast-DDS) | `575d045` / `341cda2` | Apache-2.0 | 3,844 tree entries; four mapped gitlinks. CMake can use installed Asio, Boost, OpenSSL and SQLite according to selected options; installed versions and selection remain unfrozen. |
| [foonathan/memory](https://github.com/foonathan/memory) | `0f07757` / `a8275df` | zlib-style | 129 entries; its test-only doctest fetch was recorded, not treated as an Agent runtime dependency. |
| [spdlog](https://github.com/gabime/spdlog) | `eb32206` / `5ea770c` | MIT (fixed raw `LICENSE`; GitHub API says `NOASSERTION`) | 158 entries; benchmark-only fetch recorded. |
| [XRCE Client](https://github.com/eProsima/Micro-XRCE-DDS-Client) | `d44dc3f` / `a662af0` | Apache-2.0 | 315 entries; default client superbuild can fetch Micro-CDR. |
| [Micro-CDR](https://github.com/eProsima/Micro-CDR), transitive candidate | `3d1b177` / `c85ff6f` | Apache-2.0 | `v2.0.1` tag was observed as this commit, fetched and verified separately. It is not one of the Agent's five direct pins. |

Fast-DDS records gitlinks for `thirdparty/android-ifaddrs` (`7b1ce82`), `asio` (`ed6aa8a`), `fastcdr` (`1bc9c91`) and `tinyxml2` (`8c8293b`). `.gitmodules` maps all four, but those commit objects have **not** been fetched or qualified here. Notably, the Fast-DDS gitlink Fast-CDR ID differs from the Agent's directly pinned Fast-CDR ID. Its CMake `eprosima_find_thirdparty` path may use installed packages or update submodules depending on options; the eventual selection requires an explicit build contract. The XRCE Client's default `UCLIENT_SUPERBUILD=ON` references Micro-CDR `v2.0.1` when no matching package is found. Its object is now local, but the Agent has not been rebuilt to pin that nested reference. Conditional googletest/doctest/benchmark fetches and system libraries are inventoried, not silently counted as closed.

The fixed Git stores are under `results/px4-agent-dependency-objects-dev-1701/*.git`. The manifest `direct-objects-v4.json` records commit/tree, license hash, gitlinks and candidate build-fetch lines. The exact `v2.0.1` tag observation is retained separately in `micro_cdr-tag-observation.txt` and checked before accepting the Micro-CDR candidate. These static lines include comments and optional tests; they are **not** a resolved CMake dependency graph. `independent-audit-v3.json` confirms all six local objects, refs, raw license bytes, tree-entry counts and saved tag observation, with `fsck` exit zero. An initial independent audit wrongly assumed every bare fetch had a pack file and failed on a repository using loose objects. Its failure note is retained; the corrected audit checks either storage form. Review also found that the first auditor accepted symlink-mode `LICENSE` and `.gitmodules` entries; both now fail closed. Forty-four focused and adjacent Agent/PX4 source tests passed. An initial test command used two nonexistent test paths and ran no tests; its output is retained before the corrected run. Changed-file Ruff and `git diff --check` passed.

| Gate | Result |
| --- | --- |
| Five exact direct Git commits/trees/license blobs locally present | Verified. |
| One nested Micro-CDR tag resolved to an exact local commit | Verified as a source candidate. |
| Gitlink/system package/transitive CMake closure and deterministic build inputs | **Not verified.** |
| Agent binary, runtime libraries, XRCE/PX4 transport and actual DDS/ULog parity | **Not built or tested.** |
| VIO→EKF2, policy training, 5/20-aircraft capacity or flight | Unaffected by this source study. |

Next, resolve the four Fast-DDS gitlinks and determine their actual default build selection, pin the nested Micro-CDR fetch in an isolated source candidate, and freeze the compiler, flags, system packages and runtime libraries. Only then, and only with adequate memory and no competing simulator/training process, attempt a bounded one-job Agent build. A successful source audit is not permission to publish ODOMETRY, alter EKF2, arm, or admit training data.
