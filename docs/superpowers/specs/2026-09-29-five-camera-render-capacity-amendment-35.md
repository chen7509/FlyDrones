# Five-Camera Render Capacity Amendment 35: Flight Platform Before Camera Load

## Trigger

The first official no-lockstep development run improved the Gazebo flight-sensor
source gate from 13/20 to 19/20, but vehicle 4 never produced magnetometer data.
The preserved ULog confirms that this was not a `gz topic` false negative:
vehicle 4 contains no `sensor_mag`, while vehicle 3 contains only one sample.
During the 20-second wall-clock source witness the simulation advanced only to
0.432 seconds and several PX4 instances reported sensor timeouts.

The capacity backend currently starts both the five-camera trigger scheduler and
the temporary five-subscriber renderer witness immediately after Gazebo advertises
`/clock`, before any PX4 instance is launched. Camera render load therefore
competes with the flight-sensor and EKF2 startup gate that is supposed to establish
the test platform.

## Correction

In capacity mode, do not wait for or start camera auxiliaries at Gazebo base
readiness. First launch all five PX4 instances and require the existing 20-source,
20/20 publisher/subscriber, and five-vehicle EKF2/disarmed/landed gates. The
launcher then writes `px4-capacity-platform-ready.json` and waits for the capacity
backend to start the unchanged scheduler and temporary five-camera renderer
witness. Only after this handoff may renderer attestation and the selected scored
observer proceed.

Keep the non-capacity handshake unchanged. Preserve the platform-ready marker and
all failed runs. Do not change the camera model, trigger schedule, subscriber
cells, PX4 build, dynamics, thresholds, or scored duration.

## Acceptance

- Structural tests prove capacity PX4 health precedes the platform-ready marker,
  and that the backend waits for this marker before starting the scheduler and
  renderer witness.
- Non-capacity launch still waits for its existing camera auxiliaries before PX4.
- `px4-capacity-platform-ready.json` is required preserved evidence.
- Focused tests, Ruff, Bash syntax, and diff checks pass.
- A fresh native single-subscriber development run must pass the unchanged
  source, topology, PX4 health, renderer, camera, and cleanup gates before work
  advances to the five-subscriber cell.
