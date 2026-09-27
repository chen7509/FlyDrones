# Five-camera render-capacity amendment 1

## Triggering evidence

Development run `results/camera-render-capacity/dev-native-single-20260927-203004/` failed before readiness and is retained. The renderer attestation rejected the native ready marker because it contains lifecycle/topology identity only, while the production Python phase marker contains five depth-observation summaries. Cleanup then rejected the owned Gazebo PID because `/usr/bin/gz` changed its argv from the Ruby launcher to the final `gz sim` process after registration. Collection also rejected the frozen implementation identity `native-cpp` because the close validator recognized only `native`.

## Binding correction

1. Capacity mode must run the renderer attestation as its own temporary five-topic image consumer, without passing the permanent observer ready marker. The attestation must exit before exact capacity subscriber topology is captured. The normal mission path continues to use its permanent Python phase-observer marker.
2. The launcher must wait until the Gazebo PID has completed the `/usr/bin/gz` exec transition before recording its immutable process identity. Failure to reach the final `gz sim` argv fails startup.
3. The auxiliary close validator must recognize the contract identity `native-cpp` and still require one stop event plus process exit code zero.
4. The failed development evidence is never reused. After tests and hash updates, all three Task 6 development checks restart with new identifiers.

No thresholds, sensor rates, vehicle count, trial duration, schedule, renderer profile, PX4 revision, or native source behavior changes.
