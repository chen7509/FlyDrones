# Live wire study preparation implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. Existing user
> preapproval covers offline design, implementation, tests and review. It does
> not remove the explicit separate live-activation restriction. Preserve this
> worktree and all evidence; no new task or parallel simulator.

**Goal:** Produce a reviewable prospective full-load unarmed wire study and a
raw-evidence auditor without starting that study during offline implementation.

**Architecture:** Reuse capture declarations, runtime binding, clock lane,
SerialTimesyncObserver and the single production wire lifecycle. Add a pure
study validator and an offline auditor, not another receiver, process manager,
filter or launcher. Preparation and post-run qualification are separate.

**Tech Stack:** Python 3.12, existing pytest/Ruff and WSL pymavlink 2.4.49 tests.

**Spec:** `../specs/2026-10-08-live-wire-study-design.md`.

## Global constraints

- No actual UDP, PX4/Gazebo/OpenVINS, ODOMETRY, EKF2 changes or arming in Tasks 1–3.
- Keep 25 s / 1 ms physics / 250 Hz IMU / 10 Hz 160x120 RGB-D, native estimator,
  original airframe/gravity/support/lateral force and all safety profiles.
- Keep original wire 8 s wall bootstrap / 500 accepted samples / 2 s health,
  simulation readiness 8 s / 200 ms future anchor, ordinary wall/supervisor 300 s.
- Clock profile: explicitly chosen simulation-domain epoch 0/0; actual positive
  samples must come from committed PostUpdate observations, never request echo.
- No held-out tuning, historical manifest rewrite, log overwrite or pass inferred
  solely from a summary, model convergence flag or successful send syscall.
- Publish personal only, retain draft PR65. Large-object publication remains
  pending; do not mark remote artifacts present until their exact head is verified.

## Review focus

1. A valid startup-only manifest/result must never qualify as live communication.
2. Matching local model output without an actual cold PX4 epoch/status chain must
   remain unqualified; packet identity alone is not sender authentication.
3. Cross-session clock or status records, shifted timestamps and missing records
   must not pass by independently satisfying field shapes.
4. Partial send/restore side effects and failed runtime cleanup cannot disappear
   behind a successful normal-case boolean.
5. A new study must preserve estimator/physical load, not silently reuse an old
   helper-only run or omit unavailable inputs through filtering.

### Task 1: Strict pure prospective study contract

**Files:** create `tools/benchmark/live_wire_study.py` and
`tests/benchmark/test_live_wire_study.py`. Reuse validators in
`capture_contract.py`, `runtime_resource_binding.py` and existing trajectory
policy; avoid modifying those validators unless a reproduced incompatibility
requires its own test.

**Interfaces:** `validate_live_wire_study(document, *, execution, binding,
wire_config, gauge_policy) -> dict` takes already-read documents, performs no
filesystem/network/process I/O and returns a defensive normalized copy.
`validate_live_wire_study_files(manifest_path) -> dict` is a separate read-only
path/hash adapter; it must not dispatch, import Gazebo runtime or construct a
socket. Do not overload a study's `prepared` flag into `live_qualified`.
Reuse only pure shape/value validators in the document layer. Existing
`capture_contract.validate_declaration`, `execution_contract` and
`wire_configuration_record` access the filesystem and belong in the file adapter.

- [x] Read relevant committed capture contracts, installed-startup artifacts and
  the spec. Define exact manifest schema `live-wire-study-v1`, explicit study ID,
  producer commit, development seed 27601, expected normal outcome, command,
  input file identities, selected profiles, clock scope, limits, audit-version
  hash and output paths. Reject unknown/missing keys and bool-as-int.
- [x] Write failing tests for valid unchanged full-load input, startup-only flag,
  missing native/config/reference inputs, synthetic epoch scope, wrong limits,
  modified wire config, profile drift, duplicate/colliding output paths, nonlocal
  endpoint and unknown authority fields. All qualification outputs start false.
- [x] Run `python -m pytest tests/benchmark/test_live_wire_study.py -q`; retain
  the actual RED cause, distinguishing missing API from behavior assertions.
- [x] Implement the strict pure contract by invoking existing pure validators and
  comparing explicit required invariants, never reconstructing lookup order.
  The file adapter must compare exact declared hashes and preserve lexical and
  resolved identities; missing files refuse rather than get omitted.
- [x] Add guards against network/process effects and Gazebo runtime imports to
  the file adapter, plus a failed hash/missing-file case. An ordinary `subprocess`
  module import through existing validators is allowed; spawning is not. Run the
  new tests plus capture-contract regressions;
  expect all pass. Commit only explicit files and logs intended for publication.

### Task 2: Raw chain auditor, with synthetic provenance kept explicit

**Files:** create `tools/benchmark/audit_live_wire_study.py` and
`tests/benchmark/test_live_wire_study_audit.py`. Consume existing segmented wire
journals, owned listener evidence, clock JSONL and capture runtime artifacts.

**Interfaces:** `audit_live_wire_study(study_path) -> dict` is read-only and
returns structured checks/refusals. It uses Task 1's manifest validation. Factor
pure joins only when needed for unit tests; do not add an alternate live codec.

- [ ] Inventory the exact current producer fields from retained in-process
  lifecycle records and installed-startup artifacts. Bind each required fact to
  its raw source and record any unobservable property as an explicit limitation.
  Synthetic fixture mode is separately named and cannot return live qualification.
  Preserve the producer's exact bootstrap latest-status replay and maintenance
  boundary snapshot as allowed non-counting records, with the existing listener
  ordinal normalization. Include both in the positive fixture; neither supplies
  an accepted sample or excuses a mismatched/arbitrary duplicate.
- [ ] Write tests that start with one consistent synthetic record chain and
  independently remove/change the raw request, response tc1, selected clock
  membership, kernel send return, owned status, cold-start evidence, listener
  ordinal, descriptor/session identity and runtime input hash. Include a real
  startup-only result that must be refused. Run and retain RED.
- [ ] Implement exact manifest/member hashing, sequence and identity joins,
  original clock monotonicity and 1 ms observation coverage, pinned observer
  replay, 500 accepted bootstrap samples and two accepted maintenance pairs.
  Preserve actual-vs-modeled labels; reject reset/gap/unexpected replay instead of
  rebasing. The two explicit non-counting boundary records above are not faults.
- [ ] Add baseline apply/readback/restore checks with original deadline and
  complete shutdown evidence. Test successful send without receipt, missing
  restore readback, armed input and cleanup failures despite normal summary flags.
- [ ] Add workload/provenance checks: 25000 actual callbacks, full raw/native
  processing according to the frozen existing profile (including allowed final
  camera later-IMU refusal), ULog unarmed evidence and required runtime phases.
  Test missing ULog, source/native gaps and lowered declared load. Do not invent
  a fresh accuracy qualification; reuse the frozen gauge/health auditors only
  where their exact inputs are available.
- [ ] Run the new audit tests and directly affected existing observer/clock/
  lifecycle tests, with WSL pinned-codec routing where Windows lacks pymavlink.
  Expect GREEN. Retain all negative fixture outcomes; commit.

### Task 3: Prepare the reviewable package and activation decision

**Files:** new unique `results/live-wire-study-dev-1701/study-v1/` preparation
artifacts; report `docs/LIVE_WIRE_STUDY_PREPARATION_REPORT.md`. This task creates
no live dispatch or capture output.

- [ ] Generate a prospective command, complete declaration and manifest for the
  actual installed selection using read-only resolution. Reuse the exact selected
  model/config/binaries from the installed preflight; explain and hash any later
  committed source differences. No giant inventory rescan substitutes for selection.
- [ ] Freeze the exact audit implementation/version and all selected input hashes
  before any later activation. Bind the existing one-shot dispatch behavior and
  failure preservation; don't introduce a second general launcher.
- [ ] Run Task 1 validation on the actual files; deliberately mutated copies must
  refuse. These tests are offline and create no socket or simulator. Report
  preparation qualified separately from all still-false live outcomes.
- [ ] Independent whole-package review of spec, plan, validator and auditor,
  especially the five review-focus cases; repair Important/Critical once with
  demonstrated RED/GREEN. No new physical trial as a review shortcut.
- [ ] Seal/report the prepared package and targeted tests, changed Ruff and
  `git diff --check`; commit. Update PR65 with local/remote publication distinction.
- [ ] Evaluate the separate activation gate against the latest user scope. If
  actual communication remains restricted, leave the package ready for review
  and continue independent offline goal work; never execute simply because a
  manifest exists. Do not mark the overall FlyDrones goal complete.

## Later live acceptance (not an instruction to launch now)

Once actual live communication is authorized and the above gates pass, exactly
one new normal dispatch may use the prepared production command under the
existing supervisor. Monitor the actual handle; don't restart on observation
timeouts. Audit and preserve the terminal result, even if it fails before force.
Only after normal qualification may separately frozen live fault studies proceed.
ODOMETRY/EKF2/arming remain outside this package even then.
