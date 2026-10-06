# OpenVINS Lazy Runtime Mapping Closure Report

## Result

The `dry-v5` runtime refusal was caused by one previously undeclared library that OpenVINS loaded after its first IMU input:

`/usr/lib/x86_64-linux-gnu/libtbbmalloc.so.2.11`

A new isolated, non-physical study reproduced that transition with the exact frozen OpenVINS executable and estimator configuration. Before the synthetic IMU packet, the allocator was absent from the process map. After one acknowledged packet, exactly that allocator mapping was added. The OpenVINS process identity remained the same across the observation and exited normally after accepting one input.

This qualifies one prospective lazy mapping only. It does not qualify the complete runtime closure, estimator accuracy or health, PX4/Gazebo execution, fusion, arming, or flight.

## Cause and upstream evidence

The installed general oneTBB library and allocator came from Ubuntu packages `libtbb12:amd64` and `libtbbmalloc2:amd64`, both version `2021.11.0-2ubuntu2`. The general package declares an exact dependency on the allocator package. The selected allocator file has SHA-256 `5af2073ee206b88a82360bb692413cd24d9ab22107b4110442c560d4a2ac4b7c`; the general library has SHA-256 `1e2a936d4519f2a4f2e62411a9f680f967a4742525ecf5c2dcac57f1b82501e7`.

The matching upstream oneTBB tag is `v2021.11.0`, commit `8b829acc65569019edb896c5150d427f288e8aba`, licensed under Apache-2.0. Its allocator source names `libtbbmalloc.so.2` and calls the dynamic loader on first allocator initialization. Ordinary `ldd` output for the frozen OpenVINS probe contains `libtbb.so.12` but not `libtbbmalloc.so.2`; this explains why the existing static dependency snapshot did not include the allocator. The exact Ubuntu package archive is preserved with SHA-256 `3de9b639d4abe5d8f0e0adbb7e26e32bf9de9473b19155d76a3a24c88b62cfea`.

The upstream release is old enough that maintenance activity should not be inferred from the tag alone. Reuse cost is low for the narrow mapping contract because no source patch or package installation is needed. Generalizing it into a broad allowlist would be unsafe, so the integration must bind this exact package, path, file identity, and trigger while continuing to reject every other unknown mapping.

## Fixed study

The study used the frozen OpenVINS probe SHA-256 `9ae05353945b56877f2a6f48c0201a3caec5a18faf3f480d79a1eda99676465b` and estimator entry SHA-256 `eaa40224f0de2f4c5b0f1d33504d215670544b9cc000252a0e92f404478360e6`. It ran without PX4, Gazebo, training, ODOMETRY publication, EKF2 injection, or arming.

One synthetic IMU packet at sample time 1,000,000 ns was acknowledged as sequence 0. The process was PID 401, process group 274, session 274, and start tick 3675 before and after the trigger. Its scheduler state changed from `R` to `S`, which is expected and is not process identity drift. The only added mapping was the expected allocator at device `08:30`, inode `238769`. `/etc/ld.so.cache` disappeared between stable snapshots and is retained as a removed mapping; it does not broaden the allowed dependency set.

The successful study contains ten files and 399,695 bytes. Key hashes are:

- `provenance.json`: `5679ba49bd67f0a898f79b735bfc0eae0c556319c238ef778458127a789cfcf8`
- `probe-result.json`: `58db0bf79f4fc81cc72d70c1c574a137c54e10454e70b29c90a4438ca8322200`
- `maps-before.json`: `6e30d74d0abe2ad2cb6fbce1a953ea89b0a9248b3367d382c363346cd9372dd1`
- `maps-after.json`: `b77fe4afcf48a0cf4a8fb207dc162b260c2922e3e06a82f55636d948c8a85c74`

The original audit failed because it compared the volatile scheduler state as process identity. That result remains in `audit-v1.json`. The auditor was corrected to compare PID, process group, session, start tick, and executable, then strengthened to verify the exact probe member set, encoded request hash, acknowledgement, session command, empty one-IMU state outputs, and absence of a native refusal. `audit-v2.json` passed the identity correction; final `audit-v3.json` passed the full strengthened audit. The successful probe was not rerun for auditor-only changes.

## Verification

- Focused closure and audit tests: 30 passed.
- Full regression: 1,321 passed, 3 skipped, with 2 existing warnings, in 298.15 seconds.
- Changed-file Ruff: passed.
- Source-tree Ruff: 53 findings in 34 unchanged files, equal to the established source-tree baseline. A separate unrestricted `ruff check .` also inspected retained upstream research sources and therefore reported 216 findings in 45 files; it is preserved but is not the comparable project-source check.
- `git diff --check`: passed.
- Final Windows and WSL process scans found no remaining PX4, Gazebo, OpenVINS, training, or test process.
- Evidence archive: 38 members, 177,525 bytes, SHA-256 `045c9a83a748440bf3bf534eb06f352f6823d20475900200717c291a2b9eaa26`; CRC and per-member manifest verification passed.

## Classification

**Verified:** the historical unknown is the exact package-owned oneTBB allocator; the frozen OpenVINS process adds that one mapping after its first acknowledged IMU input; the mapping and protocol evidence pass the independent final audit.

**Implemented but not yet integrated:** a strict provenance collector, bounded one-input probe, and independent auditor. The runtime-binding launcher does not yet consume this contract.

**Not tested:** the new mapping contract inside a prepare-only full runtime binding, later lazy mappings, online VIO after the contract, PX4/Gazebo motion, estimator loss/reset handling, covariance and quality, and VIO-to-EKF2 injection.

**Still failed or blocked:** the earlier `dry-v5` physical attempt remains a safe startup refusal. PR48 remains a 6.417-second health refusal with indeterminate accuracy. The prior 29.5355 m VIO displacement-error lower-bound failure, old contact/mixing issue, startup failure, five-aircraft 0.873 RTF capacity failure, and all hardware/Linux/flight dependencies remain unchanged.

## Next gate

The next step is a new prepare-only integration stage. It must add this exact lazy allocator contract to the runtime declaration before any simulator or PX4 process starts, verify the prospective inputs and generated metadata, and stop without running physics. It must not reuse or relabel `dry-v5` as passing. Only after that prepare-only contract is independently audited may a new physical study be designed.
