"""Assertions for simulation-time stepping, independent of wall-clock latency."""


def require_offboard(custom_mode: int, base_mode: int) -> None:
    if ((int(custom_mode) >> 16) & 255) != 6 or not (int(base_mode) & 128):
        raise RuntimeError(f'PX4 not armed OFFBOARD: custom={custom_mode}, base={base_mode}')


class StepClock:
    def __init__(self, dt_ns: int):
        if type(dt_ns) is not int or dt_ns <= 0:
            raise ValueError('period must be a positive integer in nanoseconds')
        self.dt_ns = dt_ns
        self.sim_ns = 0

    def accept_time(self, sim_ns: int) -> None:
        if type(sim_ns) is not int or sim_ns < self.sim_ns:
            raise ValueError('simulation clock moved backwards or is not integer')
        self.sim_ns = sim_ns

    def next_target(self) -> int:
        return self.sim_ns + self.dt_ns

    def assert_paused(self, before_ns: int, after_ns: int) -> None:
        if before_ns != after_ns:
            raise RuntimeError(f'simulation advanced during decision: {before_ns} -> {after_ns}')
