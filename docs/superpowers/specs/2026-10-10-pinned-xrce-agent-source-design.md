# Pinned XRCE Agent build-input design

## Purpose and boundary

Prepare an auditable source input for a future bounded build of the PX4 v1.17-compatible Micro XRCE-DDS Agent v2.4.3. The previous source investigation fixed Agent commit `73622810d984349b80bbac0ef55fc0b694d62222` but showed that its default superbuild follows movable Fast-CDR `2.2.x` and Fast-DDS `2.14.x` branches. The new input must copy the fixed Agent Git blobs into a separate destination and replace only the five upstream dependency references with full observed object IDs. This stage does not fetch, compile, launch or qualify those dependencies or an Agent executable.

## Immutable inputs

| Input | Required value |
| --- | --- |
| Agent commit/tree | `73622810d984349b80bbac0ef55fc0b694d62222` / `30de05fce045d2cc40c3b911f4dc5085b24f1ab4` |
| `CMakeLists.txt` Git blob SHA-256 | `99a4934796b9bf98abb365e42eb6b0cdf57ca40067d2996aa4f03179491d329b` |
| `cmake/SuperBuild.cmake` Git blob SHA-256 | `86ac7d0e6643b62e4449b108e2ee76ae4e6d35004e3156970682841a74c65b29` |
| Fast-CDR | `757d5e422253568c487ad97c22e44680fc1ddbaf` |
| Fast-DDS | `575d045b55c16be1074ccd9eebf95e3e4274fe61` |
| foonathan/memory | `0f0775770fd1c506fa9c5ad566bd6ba59659db66` |
| spdlog | `eb3220622e73a4889eee355ffa37972b3cac3df5` |
| XRCE Client (default P2P) | `d44dc3fa0c488376e34d26ed92853f1c66dcb670` |

These IDs were observed on 2026-10-10. Source identity does not establish whether every remote object is a commit or builds with this Agent; that requires local `git cat-file -t` and a later bounded build. Do not treat a branch/tag name or an unpinned Docker base as a substitute. Keep default Agent feature profiles rather than narrowing the binary simply to fit current memory. The future build must fix compiler, CMake flags, transitive source objects and linked runtime libraries, use a bounded single-job budget, and check resource availability before launch.

The earlier source-research archive hashed **Windows checkout bytes**, which Git expanded to CRLF under `core.autocrlf=true` and `.gitattributes text=auto`. That archive remains valid evidence of that checkout, but the cross-platform preparer binds **Git blob bytes** instead. Its first real attempt correctly refused before writing when the checkout hash was mistakenly used as a blob hash; the failure remains in `results/px4-agent-v243-pinned-source-dev-1701/prepare-console.txt`.

## Preparation contract

The preparer reads the Agent Git tree and blob bytes with replacement refs disabled, not Windows checkout bytes, and rejects a wrong HEAD, wrong tree, changed selected source hashes, nonregular Git entries, unsafe or Windows-aliased names, duplicate paths, the reserved manifest name, oversized blobs or a pre-existing destination. It requires exactly one occurrence of each old CMake dependency declaration and replaces only those text bytes. The output is a new directory containing the 213 source files plus a manifest with input identity, each output file SHA-256, original Git modes, dependency IDs, and `agent_binary_built_or_run=false`, `px4_agent_interoperability_verified=false`. No PX4 rootfs, EGO baseline or sealed past evidence changes.

Normal, wrong-commit, altered-CMake, duplicate-reference, missing-reference, symlink-mode, unsafe-path and existing-destination tests must fail closed. A successful preparation is a reproducible **candidate source tree**, not a compiled binary or a license/ABI guarantee. All errors and partial preparation artifacts remain identifiable; later studies use a fresh destination rather than overwriting them.
