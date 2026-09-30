# Five-camera render-capacity amendment 2

## Triggering evidence

Review of the retained first development failure found that the temporary run directory is derived only from the frozen slot name. A corrected development retry or a later new campaign would therefore collide with stale evidence from an earlier campaign. The same evidence also captured an empty argv for the newly spawned native observer, creating a window in which ownership-safe cleanup could classify a live owned process as already gone.

## Binding correction

1. Derive the temporary PX4/Gazebo run directory from both the frozen slot name and the absolute output directory. Different development or campaign identities therefore receive different `/tmp` directories while a single slot remains deterministic.
2. Process identity registration must wait briefly for a nonempty `/proc/<pid>/cmdline` and fail closed if it never becomes observable. PID, start ticks, and the final nonempty argv remain the cleanup identity.
3. Add `process_ownership.py` to the frozen trial and campaign hashes.
4. Remove the old temporary directory only after confirming its processes are gone and its restoration evidence is accepted. The retained output evidence remains unchanged.

No experimental threshold, schedule, native executable, sensor configuration, or PX4 behavior changes.
