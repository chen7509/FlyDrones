# Actual cached OpenVINS dataset consumption (2026-10-14)

**The real upstream consumer exited0 and produced185 publicly initialized
candidate pose rows from245 requested camera frames.** No estimator threshold,
configuration, calibration flag or upstream algorithm changed. This verifies
recorded-input API consumption and output generation; it does not qualify
accuracy, measured calibration, continuous clock health, a live PX4 source,
EKF2 fusion, teacher data, training or flight. The251 earlier rejected PX4
pose rows remain rejected.

## Frozen consumer, source and admission

This completes the independently planned **build-free** consumption task from
`2026-10-14-openvins-cached-consumer.md`. The separate new native-CSV/PNG C++
adapter and its native parser tests remain uncompiled/untested; this execution
does not close that plan. No compiler, PX4, Gazebo, ROS, optimizer or control
process was launched, and no previous exporter or native run was repeated.

Windows CLI parent42288 ran2026-10-14T12:14:59.271082Z through12:15:07.590301Z
(20:14:59–20:15:07 Beijing) and exited0. The actual first admission persisted
Windows2241687552 / WSL7056961536bytes; second admission persisted
Windows2217701376 / WSL7044259840bytes. Both exceeded the independently frozen
1GiB reserve, found no classified competitors, and recorded Docker empty.
The initial read-only snapshot2361782272bytes was earlier than those two gates.
The older parent23316 admission refusal and unknown first counter are retained;
none of the new observations backfills it.

The exact archived GPL runner-v3 binary/source and three historical YAMLs were
extracted from `evidence/openvins-offline-1701.zip`, SHA256
`29fee032d5400108053cdfa5f010c90519a878ce3e5c46a1c549f29085dd0bb7`.
Executable SHA256 is
`bf811d145e82a0b70b7eb242349d429e56261212dc5e6986491720b9fd460899`.
`ldd` resolved the expected existing library, SHA256
`ef649cc55d9d4471dbf9e549561a877752a48ae08d568a3433e157cb8e747b45`,
with the clean pinned source
`69488123ed9362dd44b6f28e7f4680abbff1442b` checked before/after.
LD_LIBRARY_PATH and LD_PRELOAD were removed for resolution and execution.
Code, binary, source, configuration and bridge snapshots were unchanged.
No new estimator binary was built; GPL linkage remained in the isolated process.
Corresponding upstream source is the
[pinned OpenVINS tree](https://github.com/rpng/open_vins/tree/69488123ed9362dd44b6f28e7f4680abbff1442b);
the wrapper source and upstream GPL license are retained with the evidence.

The input is the recorded development27201 dataset produced earlier, **not**
the historical1701 dataset that initialized0frames. The source ULog remains
`55428c6d37e75d7fa2d53ab67a6527b4350fa020dca4a761a44fa7aec68d1028`;
RGB manifest remains
`6d71edb71136d4c0b696f900c46b5913dad586bb71b2b0f8e340a649fb631bdf`.
All515 sealed dataset members, camera/IMU journal identities and original PPM
bytes were checked. File/hash binding is not live device authentication.

## Actual inputs and returned states

| Quantity | Actual record |
|---|---:|
| Complete camera identities in ledger | 251 |
| Native requested/returned camera rows | 245 |
| Explicit camera range refusals | 6 |
| Complete IMU rows in bridge input | 6123 |
| IMU feed count returned by native | 6102 |
| Unconsumed IMU tail retained | 21 |
| Public `initialized()` false/true rows | 60 / 185 |

The six camera refusals are2ms,100ms,200ms,300ms,400ms and25s, outside the
complete IMU0.5–24.988s interval. They remain in the full ledger and source
dataset; they were not hidden to improve results. The native stream is0.5–24.9s
and uses the original PPM decoded by OpenCV to grayscale. **It does not consume
the generated PNG or RGB directly.** The bridge converts integer nanoseconds
to legacy microseconds only when exact; it never rounds or shifts a sample.

The existing runner feeds the immediately following IMU sample as an offline
buffer boundary. Its last returned feed is source index6101 at24.904s;
indices6102–6122 (24.908–24.988s) are a retained, unconsumed tail. Do not claim
all6123 IMU rows were fed. The native count, source prefix and code establish
this relationship, rather than an independently instrumented per-IMU call
receipt. Offline look-ahead does not prove causal network arrival or online use.

All245 actual CSV row identities match requested timestamps. The first60 rows
contain no invented pose; the subsequent185 rows have finite pose/quaternion
values from the original public initialized path. First initialization is
at6.5s, with position(-0.0825364761,-0.2939059701,0.2765173333)m; the final
24.9s position is(-0.3133915755,0.4110925927,0.0009667286)m. These are the
estimator's internal global-frame candidates, not LOCAL_NED or truth.
Maximum quaternion-norm deviation is2.220446049250313e-16, a numerical
integrity observation, not an accuracy metric. Floating state reference time
at the final frame is24.900000000000002s; original integer image identity is
retained. There was no truth alignment, reference trajectory scoring,
covariance export, timing calibration or health/reset qualification.

## Resource and ownership evidence

Actual Windows launcher56068 created
`fly-openvins-dataset-cached-consume-a72300c494196fb51848169e.scope`.
Inside helper PID41255 observed the exact cgroup and InvocationID
`5dd59b73ef1f4e41945bd56ec7f00643` before launching `/usr/bin/time` PID41257.
The **native ELF PID was not separately sampled**; neither wrapper PID is
mislabelled as that native PID. Exact argv and executable identity are retained.

Inside limits before/after were MemoryMax201326592bytes (192MiB), swap0,
cpu.max100000/100000 and pids.max64. The command/profile configured120s inner
and150s outer wait unchanged; scope RuntimeMaxSec was not independently read
back as an additional property before its removal.
The time wrapper observed wall2.69s, user0.45s/system0.20s and maxRSS66984KiB.
The owned cgroup reported memory.peak78888960bytes and all memory.events0,
including oom/oom_kill. These are distinct observed counters, not a claim of
the native ELF alone's exact peak or the minimum future memory requirement.
Native/time/launcher/parent exited0. The observed owned cgroup path was absent
afterward; this proves that owned group release only. Escaped-descendant
closure remains unknown. No unrelated process was stopped.

## Review, preservation and remaining qualifications

Independent read-only raw-artifact review checked every frame and IMU bridge
row/journal relationship, returned identities/counts/states, archive binary/
source/YAML bytes, source/library checks, actual limits/exit/release and old
archive/code hashes. It found no Critical/Important/Minor issue. This phase
changed no implementation; the preparation's12software tests were not rerun
as new progress. Existing REDs, admission refusals, preparation ZIP and
historical failures remain intact. The cached runtime attempt is now consumed:
**do not execute its CLI again or overwrite its study.**

All live-source, clock-epoch, measured spatial/time calibration, teacher,
fusion, training and flight qualifications remain false. The rig/epoch are
caller declarations, mounting is the old static simulation candidate,
timeoffset0 and EuRoC noise are uncalibrated, and the original calibration
flags remain false. Public initialization has not measured their validity.
No archived held-out benchmark was used or tuned, no neural model was trained,
and no estimator output was delivered to PX4.

Next work is production association with an owned PX4/camera/IMU run and
measured spatial/time calibration consumption, with real firmware, reset,
sample and clock evidence. The separate C++/PNG consumer remains pending its
own declared2GiB gate and native validation; physical/fullMaleCNS/PX4 firmware
retain their4GiB and all safety thresholds. EGOv3 remains consumed after OOM.
This material offline milestone is one dependency of the full goal, not
completion of the drone system or permission to use these poses for control.
