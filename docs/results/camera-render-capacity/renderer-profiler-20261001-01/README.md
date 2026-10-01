# Renderer profiler evidence — 2026-10-01

This compact snapshot records the profiler-led zero-trigger investigation on
the frozen five-PX4, Ogre2, D3D12/NVIDIA WSL configuration.

The PX4 default Gazebo server configuration loads `custom::GstCameraSystem`.
That plugin searches the Gazebo topic list for a regular `/image` camera until
it finds one. This experiment has depth-image sensors only, so the search never
completed and ran on every simulation update. A private, run-scoped server
configuration removed only this unused plugin; the shared PX4 configuration
was not changed.

The exact final-code trial reached 0.7895341714 RTF, with five healthy,
disarmed, landed PX4 vehicles and all five 160 × 120 depth topics at about
10 Hz. An earlier valid exploratory run with the same retained behavior reached
0.8573505872 RTF. Their 0.0678 range exceeds the 0.03 repeatability limit, so
this snapshot does not claim a stable RTF improvement. Runtime attestation
bound the private server-config path and SHA-256, proved the forbidden plugin
entry absent, and proved that `libGstCameraSystem.so` was not mapped by Gazebo.
Cleanup and shared-file restoration both passed.

The corresponding profiler run reached 0.8506595481 RTF and captured 10,906
`cpu-clock:u` samples with zero lost samples. The former GStreamer hot path was
absent. Remaining cumulative samples were led by Gazebo Transport publisher
discovery (43.31%), Physics update (29.13%), DART forward step (23.10%), and
subscriber-change handling (12.91%). Sensors `PostUpdate` was 2.09% and
`RenderUtil::UpdateFromECM` was 1.00%.

The 0.95 real-time gate remains closed. One-camera, five-camera, and formal
12-slot trials were therefore not run. Bullet Featherstone, DART PGS, and
removing SceneBroadcaster were tested as bounded development experiments and
rejected; their outcomes are in `rejected-experiments.json`.

Files:

- `score.json`: valid exact-final-code zero-trigger score.
- `manifest-summary.json`: health, cleanup, restoration, and frozen inputs.
- `renderer-attestation-summary.json`: renderer, depth, server-config, and
  mapped-library proof.
- `profile-summary.json`: profiler method, result, and hotspot percentages.
- `rejected-experiments.json`: bounded alternatives and rejection reasons.
- `raw-artifact-index.json`: hashes of this compact snapshot.
