# OpenVINS Lazy Runtime Prepare Integration Design

## Goal

Turn the single mapping qualified by the OpenVINS lazy-runtime study into a prospective launch input for a new supported-motion study, while stopping before any worker, OpenVINS, PX4, Gazebo, or physics process is created.

This stage derives a new package from the retained `dry-v5` preflight declaration and the independently audited lazy-runtime study. It does not repair or relabel `dry-v5`, and it does not authorize a physical retry.

## Inputs

The builder consumes two immutable sources:

1. The `dry-v5` supported-heartbeat/gauge preflight package: runtime binding v3, execution contract v3, trajectory policy, study manifest, and retained prelaunch audit.
2. The PR62 lazy-runtime study: exact provenance, all probe protocol and process-map records, the final passing audit, the fixed Ubuntu `libtbbmalloc2` package archive, and the current collector/auditor source files.

The lazy source is acceptable only if its independent auditor still passes against current files and the stored final audit exactly matches the recomputed result. The predicted mapping must remain the sole added mapping, be absent from ordinary ELF closure, belong to `libtbbmalloc2` version `2021.11.0-2ubuntu2`, and match the fixed upstream oneTBB source and package archive.

## Derived package

The builder creates a new directory containing:

- a copied trajectory policy;
- `lazy-runtime-contract.json`, which records the exact trigger scope, allocator path/device/inode/hash, package/source identities, source-study member identities, and false downstream claims;
- a new runtime binding v3 whose inventory contains every referenced lazy-contract input and whose baseline is freshly recomputed;
- a recomputed execution contract and exact future worker command pointing only to the new package;
- a study manifest that records both source packages and keeps physical execution, runtime closure, VIO health/accuracy, fusion, and flight false.

The allocator is added as a normal declared file identity. Existing owned-process map checks remain fail-closed: any other unknown mapping or any identity mismatch still refuses the future run. The contract describes the proven first-acknowledged-IMU trigger, but this prepare stage does not rerun or simulate it.

## Ordering and failure behavior

All source validation, audit recomputation, file identity reads, metadata writes, and the final baseline snapshot occur in the parent prepare process. The prepare entry point rejects active competing resources and an existing destination. It never imports Gazebo bindings, constructs `TestFixture`, instantiates `NativeClient`, launches PX4, or invokes the capture command.

Missing, duplicate, changed, replaced, unreadable, symlink-drifted, or extra source evidence fails closed. A failed preparation may leave its newly named partial output for diagnosis; it cannot update either source study. No observed path may be appended after failure and called prospective evidence.

## Independent audit

The auditor requires an exact output member set, recomputes the lazy-source audit and all current file identities, validates the derived contract, recomputes the binding baseline and execution contract, and reconstructs the exact command. It requires the capture destination to be absent and all downstream claims to remain false.

Passing this gate qualifies only a prepare-only launch declaration that knows the one fixed allocator mapping. Whole-runtime closure remains false because later camera, rendering, estimator, and PX4 mappings have not been observed under the new package.

## Next gate

Only after this package and auditor pass, tests and evidence are sealed, and no competing processes exist may a separately named physical study be designed. That future study gets at most one attempt under the unchanged 25 s, 1 ms physics, 250 Hz raw IMU, 10 Hz 160×120 RGBD, support/lateral force, watchdog, and safety settings. Any new lazy mapping returns to source research instead of being added ad hoc.
