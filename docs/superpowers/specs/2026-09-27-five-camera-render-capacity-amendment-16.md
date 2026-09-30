# Five-camera render-capacity amendment 16

## Triggering evidence

Restarted development run
`results/camera-render-capacity/dev-native-single-20260927-215304/` produced
strict passing startup-health evidence for all five PX4 instances. The Python
scheduler and native renderer witness nevertheless stopped at their fixed
30 wall second internal readiness deadlines. Process start ticks show vehicles
3 and 4 started near or after that deadline; the scheduler's final topology
snapshot therefore contained only vehicles 0 through 2, and the renderer
witness could not receive five image streams.

The outer capacity setup deadline is 180 wall seconds, but both auxiliary
processes retained shorter hard-coded 30 second deadlines from the former
overlapping startup procedure. Sequential sensor-healthy startup legitimately
needs more setup time without changing the scored experiment.

## Binding correction

1. Add native CLI option `--readiness-timeout-s` with a 30 second default and
   use it only for the native topology/image readiness deadline.
2. Start the setup-only five-camera renderer witness with a 150 second
   readiness deadline.
3. Start the unchanged Python scheduler with a 150 second topology deadline.
4. Keep the selected observer's default 30 second handoff deadline, the outer
   180 second capacity setup deadline, the 30 simulation second scored window,
   and the 120 wall second scored timeout unchanged.
5. Preserve this failed run, rebuild and re-hash the native executable, update
   frozen hashes, and restart all three Task 6 checks with new identifiers.

This correction allocates time to setup; it does not change trigger timing,
sensor frequency, PX4 state, or performance acceptance.
