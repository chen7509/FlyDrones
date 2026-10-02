# Renderer diagnosis evidence

This snapshot records the 2026-09-30 development diagnosis of the five-camera
capacity failure. It does not replace or amend the frozen formal campaign.

`diagnostic-summary.json` is the decision record. The `ogre2/` and `ogre1/`
directories retain each trial's manifest, score, summary, and a compact
renderer attestation. `sensors-experiments/` retains four increasingly strict
custom-plugin attempts. The paused-startup-aware 10 Hz throttle reached a
scored window at 0.7301 RTF, but a post-run audit found that its private server
config was not bound into the original runtime attestation. It is retained as
diagnostic-only; the recovered config and limitation are recorded beside the
trial. `raw-artifact-index.json` inventories all 535 local raw files, including
five PX4 ULogs per run, by byte
size and SHA-256; the raw data remain under the ignored development directories
listed in the index.

The corrected scored phase begins only after five-camera renderer attestation
and changes the scheduler to the cell's selected trigger count. Thus `idle-0`
means an initialized renderer with zero steady camera triggers. It is distinct
from the cold readiness baseline in which the renderer was never initialized.
`post-audit-phase-validation.json` records the amended transition and trigger
integrity checks against all six retained scored runs.

Ogre2 zero-trigger RTF was 0.8349 and 0.7798. Ogre1 zero-trigger RTF was
0.7567 with `libgz-rendering8-ogre.so.8.2.3` proven in the Gazebo process. The
0.95 capacity gate remains closed, and no formal rerun was authorized by these
development results.
