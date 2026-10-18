"""Explicit v2 native consumer in capture; process correlation is not authentication."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import select
import time

from tools.benchmark.managed_capture_source import ManagedCaptureSource, ManagedEstimateNativeClient
from tools.benchmark.openvins_causal_input import CausalInput

PROFILE = "offset-reset-v2"
LIFECYCLE_FIELDS = {
    "native_profile",
    "native_pid",
    "native_session",
    "camera_imu_offset_ns",
    "reset_total",
    "native_lifecycle_known",
}


class NativeLifecycleBinding:
    def __init__(self, process, session, offset_ns):
        if (
            type(session) is not str
            or len(session) != 64
            or any(c not in "0123456789abcdef" for c in session)
            or type(offset_ns) is not int
            or not -1_000_000_000 <= offset_ns <= 1_000_000_000
            or type(process.pid) is not int
            or process.pid <= 0
            or process.poll() is not None
        ):
            raise ValueError("explicit live native lifecycle required")
        self.process, self.pid, self.session, self.offset_ns = process, process.pid, session, offset_ns
        self.failure = None

    def accept(self, row):
        if self.failure:
            raise ValueError("native lifecycle refusal latched: " + self.failure)
        try:
            if (
                self.process.pid != self.pid
                or self.process.poll() is not None
                or row.get("native_profile") != PROFILE
                or row.get("native_pid") != self.pid
                or type(row.get("native_pid")) is not int
                or row.get("native_session") != self.session
                or type(row.get("camera_imu_offset_ns")) is not int
                or row["camera_imu_offset_ns"] != self.offset_ns
                or row.get("native_lifecycle_known") is not True
                or type(row.get("reset_total")) is not int
                or row["reset_total"] != 0
                or type(row.get("reset_counter")) is not int
                or row["reset_counter"] != 0
            ):
                raise ValueError("native lifecycle process/session/offset/reset changed")
            return row["reset_counter"]
        except BaseException as exc:
            self.failure = repr(exc)
            raise


class OffsetCausalInput(CausalInput):
    def __init__(self, *, session_id, clock_id, offset_ns):
        if type(offset_ns) is not int or not -1_000_000_000 <= offset_ns <= 1_000_000_000:
            raise ValueError("bounded integer native time offset required")
        super().__init__(session_id=session_id, clock_id=clock_id)
        self.offset_ns = offset_ns
        profile = self.profile
        profile.update(
            schema="flydrones-gazebo-raw-imu-causal-offset-v2",
            sample_to_camera_offset_ns=offset_ns,
            time_offset_scope="bound calibration consumed; measurement/clock qualification separate",
        )
        self._profile_json = json.dumps(profile, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self.profile_sha256 = hashlib.sha256(self._profile_json.encode()).hexdigest()

    def _release(self):
        actions = []
        while self._pending["rgb"]:
            stamp = min(self._pending["rgb"])
            lookup = stamp + self.offset_ns
            if not 0 <= lookup < 2**63:
                self._reject("shifted camera timestamp outside IMU range")
            if stamp not in self._pending["info"] or self._imu_latest is None or self._imu_latest <= lookup:
                break
            if self._imu_first > lookup or self._imu_latest - lookup > 200_000_000:
                self._reject("camera lacks bounded shifted IMU history")
            rgb, rgb_seq = self._pending["rgb"].pop(stamp)
            info, info_seq = self._pending["info"].pop(stamp)
            actions.append(
                dict(
                    kind="camera",
                    sample_ns=stamp,
                    imu_lookup_ns=lookup,
                    rgb_sequence=rgb_seq,
                    info_sequence=info_seq,
                    camera_info=copy.deepcopy(info["camera_info"]),
                    source_arrival_ns=rgb["arrival_monotonic_ns"],
                    info_arrival_ns=info["arrival_monotonic_ns"],
                    imu_boundary_ns=self._imu_latest,
                    imu_boundary_sequence=self._imu_sequence,
                    release_sequence=self._last_sequence,
                    release_wall_ns=self._watermark,
                    release_sim_ns=self._sim_watermark,
                    profile_sha256=self.profile_sha256,
                    eligible_for_px4_fusion=False,
                )
            )
        return actions


class OffsetResetSource(ManagedCaptureSource):
    OFFSET_RESET_V2 = True

    def __init__(self, artifact, *, native_session, **kwargs):
        if artifact.timeshift_rounding_error_ns != "0":
            raise ValueError("native v2 needs exact integer nanosecond offset")
        super().__init__(artifact, **kwargs)
        self.native_session = native_session
        self.lifecycle = None

    def attach_native(self, process):
        super().attach_native(process)
        self.lifecycle = NativeLifecycleBinding(process, self.native_session, self.artifact.timeshift_ns)

    def _accept_native_camera(self, ack):
        self.lifecycle.accept(ack)

    def _native_reset(self, prediction):
        return self.lifecycle.accept(prediction)

    def _native_fast_fields(self, prediction):
        return dict(
            native_profile=PROFILE,
            native_session=self.native_session,
            reset_total=prediction["reset_total"],
            native_state13=copy.deepcopy(prediction["state13"]),
            native_covariance12=copy.deepcopy(prediction["covariance12"]),
            native_lifecycle=copy.deepcopy({key: prediction[key] for key in LIFECYCLE_FIELDS | {"reset_counter"}}),
        )

    def wire_snapshot(self, sim_ns):
        # Same atomic calibrated image/current-state join as diagnostics. This
        # grants only receiver transport eligibility, never controller readiness.
        return self.latest_diagnostic(sim_ns)

    def validate_wire_selection(self, state):
        with self._access():
            if state["native_pid"] != self._pid or state["native_session"] != self.native_session:
                raise ValueError("wire/native session changed")
            self.lifecycle.accept(state["native_lifecycle"])
            if not 0 <= self._now() - state["receipt_ns"] < 2_000_000_000:
                raise ValueError("wire native receipt expired")


class OffsetResetNativeClient(ManagedEstimateNativeClient):
    def __init__(self, *args, **kwargs):
        self._prefeed_started = self._prefeed_released = False
        super().__init__(*args, **kwargs)

    def release_prefeed(self, binding, role):
        """Consume constructed-manager identity, observe owned maps, release once."""
        if getattr(self, '_prefeed_started', False) or self.sequence or self.closed or self.failed:
            raise ValueError('prefeed unavailable/already attempted')
        self._prefeed_started = True
        trace = dict(profile='native-prefeed-v1', native_pid=self.process.pid, ready=None, mapping=None,
                     release_attempted=False, release_bytes_returned=None, error=None,
                     source_authenticated=False, fusion_verified=False, readiness_raw_hex='')
        primary = None
        deadline = time.monotonic() + self.timeout_s
        try:
            require_prefeed_phases(binding.required_owned, role)
            raw = b''
            while b'\n' not in raw:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('prefeed readiness deadline')
                if self.process.poll() is not None:
                    raise ValueError('native exited before prefeed')
                reads, _, _ = select.select([self.ack_fd], [], [], remaining)
                if reads:
                    part = os.read(self.ack_fd, 8193-len(raw))
                    if not part:
                        raise ValueError('prefeed EOF')
                    raw += part
                    trace['readiness_raw_hex'] = raw.hex()
                    if len(raw) > 8192:
                        raise ValueError('prefeed readiness bound')
            if raw.count(b'\n') != 1 or not raw.endswith(b'\n'):
                raise ValueError('extra prefeed output')
            from tools.benchmark.capture_online_estimates import _pairs
            ready = json.loads(raw, object_pairs_hook=_pairs)
            if type(ready) is not dict or set(ready) != LIFECYCLE_FIELDS | {'event','reset_counter'} or ready['event'] != 'native_prefeed_ready':
                raise ValueError('prefeed readiness schema')
            trace['ready'] = ready
            self.managed_source.lifecycle.accept(ready)
            if time.monotonic() >= deadline:
                raise TimeoutError('prefeed identity deadline')
            trace['mapping'] = binding.observe_owned(role, 'prefeed')
            if (trace['mapping'].get('observed_files_covered') is not True
                    or trace['mapping'].get('identity_after', {}).get('pid') != self.process.pid
                    or binding.errors):
                raise ValueError('prefeed owned mappings not covered')
            self.managed_source.lifecycle.accept(ready)
            if time.monotonic() >= deadline:
                raise TimeoutError('prefeed map/release deadline')
            trace['release_attempted'] = True
            trace['release_bytes_returned'] = os.write(self.process.stdin.fileno(), b'\x01')
            if trace['release_bytes_returned'] != 1:
                raise ValueError('prefeed short release')
            self._prefeed_released = True
            return trace
        except BaseException as exc:
            primary = exc
            trace['error'] = self._feed_failure = self.failed = repr(exc)
            self.managed_source.latch_failure(exc)
            raise
        finally:
            try:
                with (self.output/'native-prefeed.json').open('x', encoding='utf-8') as stream:
                    json.dump(trace, stream, indent=2, allow_nan=False)
            except BaseException as cleanup:
                if primary is None:
                    self.failed = self._feed_failure = repr(cleanup)
                    self.managed_source.latch_failure(cleanup)
                    raise
                from tools.benchmark.capture_online_estimates import _secondary
                _secondary(primary, [cleanup])

    def send(self, action, pixels=None):
        if not self._prefeed_released:
            raise ValueError('native prefeed barrier not released')
        return super().send(action, pixels)

    def _validate_ack_contract(self, ack):
        self.managed_source.lifecycle.accept(ack)

    def _validate_native_contract(self, row, ack):
        self.managed_source.lifecycle.accept(row)
        if row.get("camera_imu_offset_s") != float(self.managed_source.artifact.timeshift_decimal_s):
            raise ValueError("native propagated offset differs from calibration")


def install_offset_causal(shadow, source):
    if type(source) is not OffsetResetSource or shadow.sequence != 0 or shadow.delivery_acks:
        raise ValueError("v2 causal source must be installed before first capture input")
    shadow.causal = OffsetCausalInput(
        session_id=shadow.causal.session_id, clock_id=shadow.causal.clock_id, offset_ns=source.artifact.timeshift_ns
    )


def require_prefeed_phases(roles, role='openvins'):
    if type(roles) is not dict or role != 'openvins' or roles.get(role) != ['prefeed','ready','prestop']:
        raise ValueError('v2 requires prefeed/ready/prestop owned maps before child creation')
