"""Local-only bridge from learned intentions to simulator setpoints."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import math
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from flydrones.multitask_contract import PolicyIntent


@dataclass(frozen=True)
class LocalVelocitySetpoint:
    vehicle_id: int
    velocity_mps: tuple[float, float, float]
    yaw_rate_rps: float
    source: str = "local-multitask-policy"


class MultiTaskSITLAdapter:
    """A per-process adapter that cannot route commands to another vehicle."""

    def __init__(
        self,
        *,
        maximum_speed_mps: float,
        maximum_yaw_rate_rps: float,
        sender: Callable[[LocalVelocitySetpoint], object] | None = None,
    ) -> None:
        self.maximum_speed_mps = float(maximum_speed_mps)
        self.maximum_yaw_rate_rps = float(maximum_yaw_rate_rps)
        if not all(
            math.isfinite(value) and value > 0.0
            for value in (self.maximum_speed_mps, self.maximum_yaw_rate_rps)
        ):
            raise ValueError("speed and yaw limits must be positive and finite")
        if sender is not None and not callable(sender):
            raise TypeError("sender must be callable")
        self._sender = sender

    @property
    def pybullet_available(self) -> bool:
        return importlib.util.find_spec("gym_pybullet_drones") is not None

    def to_setpoint(
        self,
        *,
        vehicle_id: int,
        intent: PolicyIntent,
    ) -> LocalVelocitySetpoint:
        if isinstance(vehicle_id, bool) or not isinstance(vehicle_id, int) or vehicle_id < 0:
            raise ValueError("vehicle_id must be a non-negative integer")
        if not isinstance(intent, PolicyIntent):
            raise TypeError("intent must be a PolicyIntent")
        checked = intent.checked()
        return LocalVelocitySetpoint(
            vehicle_id,
            tuple(value * self.maximum_speed_mps for value in checked.motion[:3]),  # type: ignore[arg-type]
            checked.motion[3] * self.maximum_yaw_rate_rps,
        )

    def step_vehicle(
        self,
        *,
        local_vehicle_id: int,
        commanded_vehicle_id: int,
        intent: PolicyIntent,
    ) -> LocalVelocitySetpoint:
        if local_vehicle_id != commanded_vehicle_id:
            raise ValueError("a local vehicle process cannot command another vehicle")
        if not isinstance(intent, PolicyIntent):
            raise TypeError("intent must be a PolicyIntent")
        setpoint = self.to_setpoint(vehicle_id=local_vehicle_id, intent=intent)
        if self._sender is not None:
            self._sender(setpoint)
        return setpoint

    def validate_backend(self, backend: str) -> dict[str, str]:
        if backend == "fast":
            return {"backend": "fast", "version": "builtin"}
        if backend == "px4":
            if shutil.which("wsl") is None:
                raise RuntimeError("PX4 backend requires WSL and the existing PX4/Gazebo setup")
            if not Path("assets/gazebo").is_dir():
                raise RuntimeError("PX4 backend requires generated assets/gazebo worlds")
            return {"backend": "px4", "version": "external-sitl"}
        if backend == "pybullet":
            if not self.pybullet_available:
                raise RuntimeError(
                    "pybullet validation requires the gym-pybullet-drones package"
                )
            try:
                version = importlib.metadata.version("gym-pybullet-drones")
            except importlib.metadata.PackageNotFoundError:
                version = "installed"
            return {"backend": "pybullet", "version": version}
        raise ValueError("backend must be fast, px4, or pybullet")
