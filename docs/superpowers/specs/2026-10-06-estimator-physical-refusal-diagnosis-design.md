# Estimator Physical Refusal Diagnosis Design

## Goal

Preserve the single `study-v2/capture-v1` physical refusal and close only the two pre-motion defects it exposed: the estimator readiness gate's rejection of the producer's documented one-physics-step timestamp lead, and undeclared renderer libraries mapped at the first Gazebo step. This stage must not rerun the 25 s capture or claim VIO, fusion, flight, capacity, or fruit-fly-policy results.

## Retained failure

The study stopped at simulation time 10 ms after 26.7009 s wall time. It remained disarmed and applied no support or lateral force. Runtime binding rejected 24 mappings at `postfirststep`; the source fan-out also rejected an IMU record whose 4 ms sample timestamp was observed from the 3 ms callback phase. PX4 later required SIGKILL. These are runtime-evidence and harness failures before a scoreable trajectory, not estimator-accuracy or learning failures.

The failed capture and the earlier shell-quoting launch failure are immutable evidence. A future attempt must use a new destination and a newly audited declaration.

## Timestamp contract

The frozen producer records `sim_age_at_callback_ns = observed_sim_ns - sample_ns`. Existing provenance validation and tests allow a sensor sample to lead the callback phase by exactly one frozen 1 ms physics step. Estimator-aware readiness shall therefore require the derived field to be present and exact, permit a lead no greater than 1,000,000 ns, and continue to reject future wall-clock arrival, larger simulation lead, inconsistent derived age, regressed acknowledgement sequence/sample, or a camera acknowledgement later than the releasing source sample.

This is a causality correction, not timestamp interpolation and not permission to consume unseen IMU data.

## Renderer mapping diagnosis

The 24 new mappings appear only after first renderer stepping. Twenty-three are package-owned shared libraries in the OGRE-Next/OpenGL/Mesa/DRM/X11/Wayland dependency path. The remaining mapping is the mutable Mesa shader-cache index and cannot be declared as immutable code.

Mesa's official environment contract allows `MESA_SHADER_CACHE_DISABLE=true`. A later isolated, prospectively declared renderer probe may use that setting to prevent the mutable cache mapping while preserving the same renderer, physics, cameras, resolutions, and rates. It must perform a bounded first step without PX4, OpenVINS, training, force, or flight; capture before/after process mappings; verify exact package ownership, versions, licenses, hashes, and stable identities; and fail on any unlisted or changed mapping. Disabling a disk cache is not a capacity result and cannot alter the frozen physical acceptance thresholds.

## Outputs and boundaries

This stage produces the timestamp fix with RED/GREEN tests, a failure report, installed-package provenance, and a plan for an isolated renderer qualification. Until that qualification and a new prepare-only audit pass, `runtime_closure_qualified`, `physical_execution_qualified`, `vio_accuracy_qualified`, `fusion_eligible`, and `flight_ready` remain false. No failed evidence may be overwritten or backfilled.
