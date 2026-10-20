# EGO v3 actual compilation failure (2026-10-14)

The frozen v3 attempt ran once and failed during actual C++ compilation. It passed the source/patch and CRLF-aware whitespace checks, then `plan_env` failed while compiling `grid_map.cpp`. Docker recorded exit 2 and `OOMKilled=true`; the outer runner and its parent exited 1. No package finished, `ego_planner` was not processed, no new image was committed, and no `binaries-after.txt` was produced. This is a build resource failure, not a fruit-fly policy evaluation.

## Admission and identity

The parent sampled 2885MiB available Windows memory; the frozen runner independently sampled 2848MiB, above the unchanged 2500MiB admission gate. Current Windows and WSL command inventories were inspected for competing project compilation/training/simulation. Docker had no running or matching owned container. The earlier refused admission-v1 remains unchanged; this actual attempt has a separate admission-v2 directory.

The actual container ID was `6479e44788f5bd2c7ad2447c6d8b3d6a4a5eb1ac121ed4edd1c7f96a9a5b1fb8`, with name `fly-ego-causal-v2-build-1701-v3`. Its running inspect recorded the pinned base image `sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a`, memory and memory-swap 1610612736 bytes, NanoCpus 1000000000, network `none`, and 128 PIDs. StartedAt was 2026-10-14T01:31:22.573678836Z (09:31 Beijing); completion was recorded at 01:36:07.7514179Z. Colcon reported 4min34s total and 4min33s for the failed package.

The patch SHA remained `bcf739842f3868fb082efce4a9a82609a7d5eb0833dea6c39e80ed9c57433fe9`; build script SHA `baa2742cb343e97c77408075ec29278099851b2a32b9569a36cee518e8ee4b37`; runner SHA `acd64e458d149de48f64a9ec77640174faf6a1361be3051dda8769702fed3dc3`; prospective SHA `cb5f8a4a16731a845a120dafc1fb2005a3d1a4c1eda78abfa802c155a857bb22`. All four prospective inputs were rehashed before and after and matched. The prospective file is also checked by the evidence audit. Parent-before's `run_ps1_started=false` describes the instant before dispatch, not the final attempt status; the command, real inspect, compiler snapshot and completion establish the subsequent run.

## What the observations establish

A retained Docker process snapshot shows the actual timeout→colcon→CMake→gmake→C++→cc1plus chain for `grid_map.cpp`. The compiler emitted deprecation warnings, then `c++: fatal error: Killed signal terminated program cc1plus`. The runner's final state string was `true 2`. The retained stats file shows 1.499GiB / 1.5GiB and 99.94% memory usage. An earlier tool response showed 99.92%; it was a different observation, not the retained file. These observations support an OOM failure under the frozen resource budget; they do not measure the compiler's required minimum memory, prove an exact peak, or independently reconstruct kernel OOM victim selection. No kernel event log or full-lifetime descendant trace was collected. The actual timeout was not reached.

Docker's [official resource constraints documentation](https://docs.docker.com/engine/containers/resource_constraints/) states that `--memory` sets a hard limit and equal positive `--memory-swap`/`--memory` disables swap. This explains the declared budget's semantics; it does not replace this run's evidence. The chosen interface remains the existing Docker CLI and ROS2 Humble/colcon toolchain, with 1 CPU and no network; no dependency or compiler option was changed. Upstream EGO remains pinned to the same GPL3 source; no maintenance or algorithm suitability claim is added.

Read-only commands inside the actual running container observed Git 2.34.1, GCC 11.4.0, upstream HEAD `23a8d5a191711dd65633df689bd00f55d4dea8f9`, and Bspline.msg SHA `6a81d3687daf49f3152f514ed5639e55374be32dd438a4f1c90900503f8e3f85`. Existing `traj_utils` type-support library hashes are retained. Those libraries and `binaries-before.txt` belong to the base installation, not newly generated artifacts from this attempt. The colcon log archive contains both historical logs and the new failed attempt; its existence alone is not build success.

Cleanup queried the exact owned name and recorded an empty result; a subsequent Docker ps also returned no running containers. The actual parent handle completed with exit 1. This establishes the recorded owned-container cleanup, not every descendant's lifetime or DDS/runtime closure.

## Remaining work

The one v3 attempt is consumed. Do not rerun its runner or overwrite its files when host memory next exceeds 2500MiB. Additional memory/capacity analysis requires a separately declared plan; no higher cap, swap, weaker optimization, physics load, or safety threshold is authorized by this failure record. Preserve v2, both v3 admissions and all old failed studies.

No new runtime, DDS subscription, same-input original/patch comparison, teacher, fusion or physical qualification passed. Complete MaleCNS remains untrained; PX4 source/sample/reset/clock and calibrated-camera dependencies remain open. Five-machine 0.873RTF<0.95 and other historical failures remain failures. The goal panel still records blocked; this authorized actual attempt does not fabricate an active state or completion of the overall goal.

Evidence: `evidence/ego-build-v3-oom-dev-1701.zip`, 40 members, SHA `28400eb8776984a10530e0f6fa5835938c68fa77bc21da306b7340fc3394a3bb`, retains the pre-review report with the 99.92/99.94 attribution error. Independent review verified CRC, member hashes, inputs and raw failure evidence, and identified that minor attribution error. The archive is not rewritten; `evidence/ego-build-v3-oom-correction.json` binds this corrected report and the unchanged archive. No experimental result was changed or rerun.
