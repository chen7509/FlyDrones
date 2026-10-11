# Bounded offline XRCE Agent build

## Goal

Build the fixed upstream Micro XRCE-DDS Agent v2.4.3 on the existing Ubuntu WSL host from previously verified Git objects, while recording the actual Fast-DDS nested package choices and runtime libraries. A binary alone will not qualify PX4/DDS provenance or VIO fusion.

## Source and selection contract

- Keep the sealed `source-v4` and bare object stores unchanged. Create a fresh Linux build checkout and record every copied or patched source byte. Agent direct projects must resolve to the five fixed commits already audited; the XRCE Client's Micro-CDR tag must resolve to the audited `3d1b177…` object.
- Use an isolated Git URL rewrite file for the nine distinct known repository URLs. Because Agent Fast-CDR `757d5e4…` differs from the Fast-DDS gitlink `1bc9c91…`, create a new local combined object store with both commits and verify each `cat-file -e` before use. Do not mutate the sealed stores.
- Deny unbound HTTP(S) fetches during this build attempt. Keep the original Agent profile enabled, tests off, Release and Ninja, with one compile job. In a copied build-policy source, set Fast-DDS `THIRDPARTY_Asio=FORCE`, `THIRDPARTY_TinyXML2=FORCE`, `THIRDPARTY_fastcdr=OFF`, `THIRDPARTY_UPDATE=OFF`; use Agent's pinned direct Fast-CDR 2.2.0. Record the exact patch and selected caches. If upstream CMake rejects any option or the selected package differs, stop and preserve failure.
- Record host and WSL memory, process absence, toolchain, source/object identities, CMake cache, build logs, executable hash, `ldd`/readelf runtime closure and bounded `--help` result. Keep an explicit wall deadline and do not run PX4/Gazebo/OpenVINS/learning concurrently. A failed or timed-out build is retained without editing test conditions post hoc.

## Gates

First prove local Git rewrite and nested CMake selection, then attempt one bounded one-job build if host memory remains sufficient. Inspect actual selected dependencies and link closure independently. Passing this stage means only that an Agent executable builds and starts under `--help`; it does not prove authenticated PX4 publication, camera calibration, EKF2 fusion, or safe flight.
