# Pinned OpenVINS offline smoke test

Use only development-world `1701` RGB PPMs and its corresponding PX4 ULog.
Verify the raw archive, camera-info, manifests, IMU arrays, file hashes and
strict time order before exporting input. Never use Gazebo truth as VIO input
or initialize from a truth pose. Keep upstream OpenVINS at commit
`69488123ed9362dd44b6f28e7f4680abbff1442b`; an isolated research runner
may link its GPL-3.0 library but must not become the commercial flight-stack
backend. Use the pinned upstream configuration parser and explicit camera-to-
IMU transform; record all provisional noise/time settings.

Start with a bounded offline smoke test on the complete IMU-covered development
window. Report input counts, actual processing time, initialization, output
state count and any crash or reason for rejection. If the first attempt fails,
diagnose the precise interface or observability cause before making any change.
Do not tune against the 20 held-out worlds, replace the full fly controller,
feed VIO into PX4, or claim a task-success result from this offline test.
Archive all inputs/configuration, runner source, binary hashes, stdout/stderr,
and every failed attempt for independent reproduction.
