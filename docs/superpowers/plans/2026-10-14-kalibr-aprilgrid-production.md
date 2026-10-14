# Kalibr AprilGrid Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for native execution and superpowers:requesting-code-review for independent final review.

**Goal:** Produce a pinned, metric, self-contained AprilGrid target for future real camera/IMU measurement capture.
**Architecture:** Fixed generator emits raster, metric layout, UV mesh, collidable SDF and hashes; upstream drawing oracle independently verifies raster. Existing capture stays frozen.
**Tech Stack:** Python stdlib/Pillow, SDF1.9, Collada1.4.1; no new installation.
**Spec:** docs/superpowers/specs/2026-10-14-kalibr-aprilgrid-production.md

## Global Constraints
Kalibr pin1f60227442d25e36365ef5f72cd80b9666d73467; 3x3 IDs0..8/0.12m/spacing0.25/border2/16px per module/margin200px/960square. Original4GiB physical/fullMaleCNS/firmware and2GiB C++ gates unchanged. EGOv3/cached OpenVINS consumed, no rerun. All qualification false. Preserve failure bytes and existing evidence, push personal only.

## Review Focus
- Family _other or border1 would silently produce wrong target: test official pin pixels.
- Raster top-bottom vs metric y-up could mirror or reorder IDs: test all ID rect locations and metric corners.
- Symmetry squares can overlap outer margin or tags: compare complete canvas oracle.
- SDF mesh/slab/texture disagreement: test exact dimensions, UV references and hashes.
- Repeated output or partial failure must not overwrite prior artifacts: exercise refusal and preserved incomplete directory.

### Task1: Fixed metric asset producer
Files: tools/benchmark/make_kalibr_aprilgrid_target.py; tests/benchmark/test_kalibr_aprilgrid_target.py; tests/benchmark/fixtures/kalibr_aprilgrid_reference.py; third_party/kalibr-aprilgrid/NOTICE.txt and LICENSE.
Interface: make_target(output: Path)->dict; CLI --output required. No load/trajectory or detector claim.
- [x] Write pixel/oracle, YAML/layout/SDF/mesh/hash, refusal/failure and CLI tests; execute RED and preserve exact argv/exits.
- [x] Implement fixed assets and exclusive failure retention; GREEN plus necessary adjacent asset regression and Ruff/diff.
- [x] Execute actual asset CLI once into independent development result directory; independently audit full decoded pixels/geometry/hash and file inventory.

### Task2: Evidence and publication
- [x] Independent code review; fix any actual findings with behavior RED/GREEN.
- [x] Report verified asset production / implemented model / untested rendering and measured calibration; preserve all failures and source research bytes, seal ZIP with every member SHA/size/CRC; independent archive review.
- [x] Commit and push personal, append PR65 preserving history and verify head/body; separate publication ledger and prepublication plan. Update heartbeat prompt preserving all gates/history. Remain quiet for preparation only.

Ruling: Independent review found required COLLADA metadata missing;1actualRED then5GREEN, immutablev1 and declared correctedv2 retained. Official schema v1false/v2true. Final18passed31.86s/Ruff0. XML schema pass is not renderer acceptance.

Ruling: Preserve exact upstream source/license through two exact-path .gitattributes -text/-whitespace entries, following existing pinned fixtures; product code remains checked. Preserve original staged diff exit2/raw and first draft ZIP, create canonicalv2 seal. No product or experiment bytes changed.

Publication: implementation77d636f98fb6c0b628358e13737b1889e07a8e6f pushed onlypersonal; PR65head/body exact verified. Canonical95members/204318B SHAa17dc100c6c57bfd163b4a618c8b9e3d64c063ea3da2b8415da5198117faddf2 independent94mapped/allCRC zeroC/I/M. Asset preparation complete; all measurement/native/render qualifications pending and original gates unchanged.
