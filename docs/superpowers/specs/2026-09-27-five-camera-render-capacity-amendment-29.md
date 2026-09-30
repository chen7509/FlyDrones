# Five-Camera Render Capacity Amendment 29: Pre-Resume Sensor Topology

## Trigger

Common-time attachment removed the nonzero attachment offsets, but the retained
rerun still produced three unhealthy estimators. The exact 20-publisher/20-
subscriber topology was only audited after Gazebo resumed. A per-process bridge
log line therefore allowed the first sensor ticks before all transport subscribers
were actually connected.

## Correction

Keep Gazebo paused after all five original PX4 bridges are present. While simulation
time remains frozen, require all 20 preloaded Gazebo sensor publishers and exactly
one PX4 subscriber per topic. Only then issue the single world resume and run the
concurrent five-vehicle EKF gate. Keep all topology, health, evidence, and scoring
requirements unchanged.

## Acceptance

- A structural test proves the exact sensor-topology audit occurs between the
  five-bridge barrier and the single world resume.
- Focused tests, Ruff, Bash syntax, and diff checks pass.
- The native single-subscriber development cell is rerun with failures preserved.
