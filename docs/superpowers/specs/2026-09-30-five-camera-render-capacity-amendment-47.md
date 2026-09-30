# Amendment 47: Correct zero-trigger baseline and audit the render engine

The `first-imu-dt-camera-20260930-01` campaign used zero depth subscribers for
`idle-0`, but its scheduler continued to trigger all five cameras at 10 Hz.
That cell measured output-subscription overhead, not a true steady
zero-trigger baseline. Its recorded evidence remains immutable and is relabeled
accurately in the report.

Development runs now retain the five-camera warmup required for renderer and
depth-stream attestation, then wait for the attestation release marker and
change scheduler output to the cell's selected vehicle count before scoring.
The transition is recorded once in `camera-scheduler.jsonl`. Missed-trigger
accounting also follows the selected scored streams. The unchanged default
keeps all configured streams when no release transition is requested.

The capacity runner also accepts an explicit `ogre2` or `ogre` development
render-engine setting. The launcher passes it to Gazebo, and renderer
attestation rejects the run unless the matching
`libgz-rendering8-<engine>.so` is mapped in the Gazebo process. The formal
campaign configuration and acceptance thresholds are unchanged.

Corrected Ogre2 development evidence measured 0.7798–0.8349 RTF with an
initialized renderer and zero steady triggers, 0.7024 with one 10 Hz camera,
and 0.5135 with five 10 Hz cameras. A valid Ogre1 zero-trigger trial measured
0.7567 and was therefore stopped before one- and five-camera expansion. These
results close the Ogre1 fallback and keep the formal 0.95 gate closed.

The exact Gazebo Sim 8.15.0 Sensors source was also tested with event-only
scene updates capped at 10 Hz after the paused startup phase. Process-map
attestation proved the custom plugin, and a later audit recovered the private
server config with the exact custom Sensors entry. Because the original
runtime attestation did not bind or preserve that config, the 0.7301 RTF cell
is diagnostic-only under the amended evidence rules. The runner now proves
the live Gazebo process's `GZ_SIM_SERVER_CONFIG_PATH`, binds the config path,
SHA-256, and exact Sensors entry into renderer attestation, and preserves the
config. Full suppression and throttling during paused startup
failed the required triggered-camera handshake. Future work must preserve that
handshake and profile below the event gate or compare the same frozen workload
on native Linux.

The scored-phase validator now also requires exactly one selected-stream phase
transition before scoring, zero scored triggers for `idle-0`, and no scored
trigger outside the selected vehicle range. The retained raw logs pass these
new integrity checks; the five-camera run still fails only its recorded phase
error performance threshold.
