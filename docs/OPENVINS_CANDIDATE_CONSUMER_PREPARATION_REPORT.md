# Recorded camera/PX4 IMU consumer preparation (2026-10-14)

**Implemented and software-verified; no new native consumer or compiler ran.**
The recorded dataset has a concrete out-of-process OpenVINS consumer bridge,
but its actual runtime remains untested. No VIO trajectory, measured camera
calibration, live PX4 source, fusion, training, teacher or flight qualification
was obtained. The previous 251 rejected PX4 pose rows remain rejected.

## Research and independently declared resources

The clean cached OpenVINS source is pinned to
`69488123ed9362dd44b6f28e7f4680abbff1442b`; its existing library is SHA256
`ef649cc55d9d4471dbf9e549561a877752a48ae08d568a3433e157cb8e747b45`.
The pinned public `feed_measurement_imu`, `feed_measurement_camera` and
`initialized()` APIs and installed OpenCV4.6.0 were inspected. Upstream is
GPL-3.0; library linkage stays in the isolated research process, outside the
MIT flight stack. The copied license and primary headers are in the research
evidence. [Upstream calibration guidance](https://docs.openvins.com/gs-calibration.html)
requires appropriate visual and motion data; the historical static mounting,
zero offset and EuRoC noise remain unqualified candidates.

The first independent design supplies a native CSV/PNG C++ adapter. Its
declared fresh Windows/WSL2GiB gate, 1024MiB compile cap and 512MiB runtime cap
were frozen before execution. The header-interface test failed its resource
fixture before starting a compiler: **1 setup error / 8 deselected**, not a
C++ behavior RED. The held header was restored byte-exact. The first counter
was not persisted; a later diagnosis observed Windows1661972480bytes. The
new C++ adapter and its seven native parser cases are **uncompiled/untested**.
Do not lower that frozen gate or infer C++ success from Python checks.

A separate build-free architecture reuses the exact archived GPL offline
runner-v3 binary/source from `evidence/openvins-offline-1701.zip`, SHA256
`29fee032d5400108053cdfa5f010c90519a878ce3e5c46a1c549f29085dd0bb7`.
The prior64.7MiB maximum RSS observation is a cost estimate, not a guarantee
for these different inputs. This independent study declares fresh Windows
and WSL each1GiB, 192MiB MemoryMax, MemorySwapMax0, CPU100%, TasksMax64,
120s inner / 150s outer wait, followed by bounded owned-launcher cleanup.
It eliminates compilation; it does not alter the pending2GiB design,
4GiB physical/fullMaleCNS gates or consumed EGOv3 budget. No resource cap,
optimization, sensor load, estimator threshold or initialization gate changed.

## Production interface and evidence boundary

`tools/benchmark/openvins_cached_bridge.py` verifies the fixed sealed dataset
manifest, all515 dataset members, CSV/journal cardinalities and raw numerical
identity, complete frame identities and original PPM hashes. The legacy
nanoseconds-to-microseconds adaptation refuses any fractional microsecond
instead of rounding. It preserves all6123 IMU rows and all251 camera identities:
245 overlapping frames are requested, while six outside the IMU range have
explicit refusal ledger entries. The bridge was actually produced from the
sealed recorded files in test directories; no estimator ran in those tests.

The archived native runner decodes the original PPM to grayscale. It does
**not** consume generated PNG or RGB directly. It uses the immediately following
IMU sample as offline look-ahead and stops at the final camera boundary. Any
unconsumed IMU tail must be derived from actual returned native counts; no
tail count or initialization result has been invented here. The historical
three YAML files are copied byte-exact without calibration or tuning. Future
dispatch verifies ELF library resolution, removes LD_LIBRARY_PATH/PRELOAD,
snapshots code/config/binary, rechecks source/data, records actual owned scope
and limits, and requires actual state-row identities and returned counts.

The source ULog remains
`55428c6d37e75d7fa2d53ab67a6527b4350fa020dca4a761a44fa7aec68d1028`;
RGB manifest remains
`6d71edb71136d4c0b696f900c46b5913dad586bb71b2b0f8e340a649fb631bdf`.
These hashes and caller epoch declarations do not authenticate a live device,
measure exposure/IMU time offset or qualify static extrinsics. Controlled
static directories are required; hostile concurrent replacement, arbitrary
in-process reflection and escaped-descendant closure remain outside evidence.

## Validation and actual refusal

The initial bridge API tests were **3 actual failures** for the absent module.
The real sealed-file positive path and changed-manifest refusal then passed.
Independent pre-dispatch review found Windows compiler/estimator competitors
were omitted and timeout paths could leave the owned launcher unbounded.
The original **2 review failures**, then **1 launcher-termination failure**,
were preserved before repairs. Process classification now covers both hosts;
scope stops require observed exact InvocationID and ControlGroup. Unknown
scope ownership is retained as unknown, while only this function's Popen
launcher receives bounded terminate/wait/kill. The helper verifies the actual
inside limits and nonempty invocation before launching any native command.
Third pre-dispatch review closed these Important findings. PPM-to-grayscale
was retained as an explicit qualification boundary.

An actual Windows CLI parent **PID23316 exited1**, refusing the first cached
resource admission **before** creating the study, extracting its executable,
launching a scope, compiling or running OpenVINS. Its exact first admission
counter was not saved. The subsequent persisted observation was
Windows547086336bytes, WSL6869364736bytes, no classified competitors and Docker
empty; this is a later observation, not the missing dispatch-time counter.
Later read-only facts likewise cannot fill that historical gap. No native
runtime attempt was consumed, and no real cached-study output exists.
The earlier CLI source was reconstructed after the run by reversing only the
later admission-record change; its SHA304fde04 matches the dispatch record.
This preserves those exact bytes but is not a pre-dispatch source snapshot.

That evidence gap has a separate **1 actual RED** and repair: the cached CLI
now requires an exclusive `--admission-record` path and writes its exact
first facts even when refused. Final software validation is **12passed1.43s**:
10 bridge/ownership/evidence cases plus two adjacent one-shot/refusal cases.
The scope tests use explicit Popen/systemctl protocol doubles; they do not
prove real cgroup lifecycle or runtime cleanup. Ruff passed. The initial
Ruff B904 failure and every RED/setup failure are retained. This is focused
software verification, not a full-suite, native compilation or calibration pass.

## Next actual dependency

After fresh1GiB dual-host admission and no competitor/owned-study conflict,
execute the frozen cached CLI once with a new admission-record filename.
Follow only actual PID/unit/handle if the study exists; never overwrite it
or retry after a real native failure. Audit actual state rows, initialization,
native counts, IMU tail, resources and owned cgroup release before reporting
consumption. Even exit0 would leave all source/clock/calibration/teacher/fusion/
training/flight qualifications false. If resources remain unavailable, retain
these untested statuses and continue independent calibration/source research;
do not present more exports or validators as a completed VIO pipeline.
