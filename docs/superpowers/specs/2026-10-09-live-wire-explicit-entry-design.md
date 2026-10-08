# Explicit one-attempt wire-study entry

## Intent and scope

The reviewed offline live-wire package now has a fresh v4 declaration at
36b4f67. The existing public executor still rejects this kind of study. Build a
small explicit entry into the already reviewed one-attempt mechanics so the
next requested scope decision concerns an executable, reviewable action.
Implementation and fake-runner tests are within the user's automatic plan
approval. **This document does not authorize actual UDP, PX4/Gazebo/OpenVINS
execution.** The earlier explicit offline-only instruction remains in force.

This is a bounded addition to an existing execution flow, with a written brief
because activation boundaries matter. Do not create a second launcher or change
the capture runner, wire protocol, safety, workload, clock or fusion gates.

## Interface and behavior

Add `execute_live_wire(manifest_path, *, approved_manifest_sha256,
resources_fn, runner=subprocess.run)` in the existing
`execute_openvins_health_physical_run.py`. Require a lowercase 64-hex digest that
matches the exact current manifest bytes. Obtain the plan via the existing
`prepare_live_wire_execution`, which validates exact command, inputs, complete
source dependencies and output absence. Check the frozen plan's manifest digest
against the supplied digest before any request record or dispatch.

The digest is an explicit caller selection, **not cryptographic proof of human
consent**. The operator/agent must have separate user authorization before
invoking this entry with a real runner. Do not write `user_authorized=true` or
rewrite the prepared manifest's offline authorization field. Preparation remains
read-only and does not activate anything merely because a public entry exists.

Create an exclusive `activation-request.json` beside the manifest containing
the supplied digest and exact manifest/executor records, request wall time,
`request_is_not_dispatch=true`, and `fusion_eligible=false`. Its schema describes
caller intent, not proof of actual execution or consent. Refuse if this path
already exists, aliases an existing input, or overlaps an output. Before writing
it, reject active competing resources; `_execute_once` still rechecks resources
and all frozen identities immediately before its own exclusive dispatch.
Once intent is written, a failed attempt is retained and cannot be retried under
the same study. A pre-dispatch failure may leave only intent and the caller's
exception/log; do not manufacture completion or claim physical execution then.

Reuse `_execute_once` unchanged: same original plan/profile, command, dispatch,
completion, supervisor, stdout and cleanup behavior. It revalidates the plan;
the new receipt cannot bypass declaration or resource checks. Runtime is still
bounded by the existing ordinary 300 s capture/300 s supervisor configuration.

Extend CLI with mutually exclusive `--study` (existing health path) and
`--live-wire-study`. The wire path requires `--approved-manifest-sha256` and
forbids `--development-gate`. The health path rejects a supplied wire digest.
Legacy health behavior and direct rejection of wire manifests remain unchanged.
No default or bare `--study` may select the new branch accidentally.

## Fixed actual action, if separately authorized later

Exactly one new normal development study, seed27601, 25 s simulation, 1 ms
physics, 250 Hz raw IMU, 10 Hz 160x120 RGB-D, original supported-motion profile
and one native OpenVINS worker. It is unarmed SITL. Outgoing traffic is limited
to the reviewed TIMESYNC exchange and its message-interval query/apply/restore;
no ODOMETRY, EKF2 parameter mutation, mode/setpoint/arming command or training.
Keep all existing source/native/clock/watchdog/failure and evidence gates.
Success only qualifies this communication stage, not VIO fusion or flight.

Before requesting actual activation, regenerate the prospective package under
a new v5 study identity with the committed executor, because v4 freezes the
old executor bytes. Preserve v1–v4. No failed study is relabeled or overwritten.
Review source, final preparation and exact permitted action before invocation.

## Research and choices

Reuse the fixed upstream/source/API research in
`2026-10-08-live-wire-study-design.md` and the existing PSF Python subprocess
one-shot wrapper; no new dependency, protocol, estimator or scientific algorithm.
PX4 d6f12ad (BSD-3-Clause), pymavlink2.4.49 (retained LGPL provenance), Gazebo8.15
(Apache2), Python3.12.3 (PSF) and native OpenVINS/config remain fixed. Maintenance
and installation provenance remain the retained observations, not newly inferred
support or hardware qualification. Entry overhead is one small JSON intent and
the existing bounded manifest validation; physical CPU/RAM cost remains untested.

Rejected: calling the private runner ad hoc, silently treating a prepared
manifest as authorization, adding an unconditional launch flag, or rewriting
offline records to claim live consent. The existing complete validator and
one-attempt execution path are sufficient; a new global process supervisor is
outside scope.

## Required verification

With fake runners only: correct exact digest reaches the original command once;
missing/malformed/wrong digest makes no dispatch; mutated declaration/source
refuses; repeated request refuses; output alias refuses; competing resources
before intent and at the second gate refuse; retained intent is not completion;
runner failure/exception keeps existing completion behavior. Test CLI route
exclusivity and that default health entry cannot activate a wire manifest.
Run targeted and full ordinary regression, changed Ruff/diff and one independent
review. Actual v5 preparation must validate all installed selected files and
existing mutation cases, with outputs absent. Never use a real runner in tests.
