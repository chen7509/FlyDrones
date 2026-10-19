"""Fixed NO_ROS source selection. No discovery, compiler invocation or old-library fallback."""

from pathlib import Path

PROFILE = "fixed-source-openvins-v1"
STEP_NAMES = ("configure", "openvins-library", "adapter")
LIBRARY = "libov_msckf_lib.so"
SOURCES = (
    "ov_core/src/cpi/CpiV1.cpp",
    "ov_core/src/cpi/CpiV2.cpp",
    "ov_core/src/dummy.cpp",
    "ov_core/src/feat/Feature.cpp",
    "ov_core/src/feat/FeatureDatabase.cpp",
    "ov_core/src/feat/FeatureInitializer.cpp",
    "ov_core/src/sim/BsplineSE3.cpp",
    "ov_core/src/track/TrackAruco.cpp",
    "ov_core/src/track/TrackBase.cpp",
    "ov_core/src/track/TrackDescriptor.cpp",
    "ov_core/src/track/TrackKLT.cpp",
    "ov_core/src/track/TrackSIM.cpp",
    "ov_core/src/utils/print.cpp",
    "ov_init/src/ceres/Factor_GenericPrior.cpp",
    "ov_init/src/ceres/Factor_ImageReprojCalib.cpp",
    "ov_init/src/ceres/Factor_ImuCPIv1.cpp",
    "ov_init/src/ceres/State_JPLQuatLocal.cpp",
    "ov_init/src/dummy.cpp",
    "ov_init/src/dynamic/DynamicInitializer.cpp",
    "ov_init/src/init/InertialInitializer.cpp",
    "ov_init/src/sim/SimulatorInit.cpp",
    "ov_init/src/static/StaticInitializer.cpp",
    "ov_core/src/types/Landmark.cpp",
    "ov_msckf/src/dummy.cpp",
    "ov_msckf/src/sim/Simulator.cpp",
    "ov_msckf/src/state/State.cpp",
    "ov_msckf/src/state/StateHelper.cpp",
    "ov_msckf/src/state/Propagator.cpp",
    "ov_msckf/src/core/VioManager.cpp",
    "ov_msckf/src/core/VioManagerHelper.cpp",
    "ov_msckf/src/update/UpdaterHelper.cpp",
    "ov_msckf/src/update/UpdaterMSCKF.cpp",
    "ov_msckf/src/update/UpdaterSLAM.cpp",
    "ov_msckf/src/update/UpdaterZeroVelocity.cpp",
)


def source_recipe(upstream):
    upstream = Path(upstream)
    if not upstream.is_absolute() or any(c in upstream.as_posix() for c in (";", '"', "$", "\n", "\r")):
        raise ValueError("literal absolute upstream directory required")
    return "set(FIXED_OPENVINS_SOURCES\n" + "".join('  "' + (upstream / name).as_posix() + '"\n' for name in SOURCES) + ")\n"


def prepare_sources(build, upstream):
    path = Path(build) / "openvins-fixed-sources.cmake"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(source_recipe(upstream))
    return path
