# Five-Camera Render Capacity Amendment 28: Common-Time PX4 Attachment

## Trigger

The restored per-instance EKF gate accepted vehicle 0 but rejected vehicle 1.
Vehicle 0 attached near simulation time zero; vehicle 1 attached after the first
resume/pause cycle at about 3.5 simulated seconds and never received the full IMU,
gyroscope, and magnetometer inputs. Earlier retained runs failed on other later
vehicles. Static Gazebo topic cardinality stayed exact, so transport discovery
alone did not prove sensor ingestion.

## Correction

Use the statically preloaded world as intended: keep simulation time frozen while
all five PX4 processes attach to their named models. Require all five original
bridges before issuing the single recorded world resume. After exact 20/20 sensor
topology is established, check all five vehicles concurrently through isolated
MAVLink ports and preserve one startup-health JSON per vehicle. Remove the obsolete
per-instance resume/pause pulses and their artifact requirements. Do not restart a
bridge, retry a failed vehicle, or weaken any health or scoring condition.

## Acceptance

- Structural tests prove there are no per-instance world pulses, the common resume
  follows the five-bridge barrier, and the concurrent health gate follows resume.
- Five startup-health records remain mandatory trial evidence.
- Focused tests, Ruff, Bash syntax, and diff checks pass.
- The native single-subscriber development cell is rerun with failures preserved.
