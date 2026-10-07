"""Offline field parity for pinned PX4 LOCAL_FRD/BODY_FRD ODOMETRY.

This component cannot qualify delivery, TIMESYNC convergence, health, rollback,
fusion or Task 5. It compares retained wire fields to a complete receiver stream.
"""

from __future__ import annotations

import importlib.metadata
import io
import math
import struct

from tools.benchmark.openvins_ekf2_integration import WIRE_FIELD_NAMES, decode_candidate

MAX_US = 2**63 - 1
TIME_TOLERANCE_US = 1
MAX_ARRIVAL_AGE_US = 100_000
VECTORS = {"position": 3, "q": 4, "velocity": 3, "angular_velocity": 3,
           "position_variance": 3, "orientation_variance": 3, "velocity_variance": 3}
INTEGERS = {"timestamp", "timestamp_sample", "pose_frame", "velocity_frame", "reset_counter", "quality"}


def integer(value, name, minimum=0, maximum=MAX_US):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("invalid " + name)
    return value


def number(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("invalid " + name)
    try:
        rounded = struct.unpack("<f", struct.pack("<f", value))[0]
    except (OverflowError, struct.error) as exc:
        raise ValueError("unrepresentable " + name) from exc
    if value != rounded:
        raise ValueError("not a decoded float32 " + name)
    return rounded


def vector(value, size, name, *, unavailable=False):
    if not isinstance(value, list) or len(value) != size:
        raise ValueError("invalid shape " + name)
    if unavailable:
        if any(item is not None for item in value):
            raise ValueError("expected unavailable " + name)
        return value
    return [number(item, name) for item in value]


def expected_fields(sent):
    if not isinstance(sent, dict) or set(sent) != {"id", "source_system", "source_component", "wire"}:
        raise ValueError("invalid sender record")
    if not isinstance(sent["id"], str) or not sent["id"]:
        raise ValueError("invalid send identity")
    if integer(sent["source_system"], "sender system") != 254 or integer(sent["source_component"], "sender component") != 191:
        raise ValueError("unexpected sender identity")
    wire = sent["wire"]
    if not isinstance(wire, dict) or set(wire) != WIRE_FIELD_NAMES:
        raise ValueError("invalid wire fields")
    for key, expected in (("frame_id", 20), ("child_frame_id", 12), ("quality", 1), ("estimator_type", 3)):
        if integer(wire[key], key) != expected:
            raise ValueError("wire profile " + key)
    integer(wire["time_usec"], "sample time", 1)
    integer(wire["reset_counter"], "reset counter", 0, 255)
    q = vector(wire["q"], 4, "q")
    if abs(math.sqrt(sum(x * x for x in q)) - 1.) > 1e-5:
        raise ValueError("non-unit quaternion")
    pose = vector(wire["pose_covariance"], 21, "pose covariance")
    velocity = wire["velocity_covariance"]
    if not isinstance(velocity, list) or len(velocity) != 21:
        raise ValueError("invalid velocity covariance")
    for i, value in enumerate(velocity):
        if i in (0, 1, 2, 6, 7, 11):
            number(value, "velocity covariance")
        elif value is not None:
            raise ValueError("angular covariance must remain unavailable")
    vector([wire[k] for k in ("rollspeed", "pitchspeed", "yawspeed")], 3, "angular rates", unavailable=True)
    result = {
        "pose_frame": 2, "velocity_frame": 3,
        "position": [number(wire[k], k) for k in ("x", "y", "z")],
        "q": q, "velocity": [number(wire[k], k) for k in ("vx", "vy", "vz")],
        "angular_velocity": [None] * 3,
        "position_variance": [pose[i] for i in (0, 6, 11)],
        "orientation_variance": [pose[i] for i in (15, 18, 20)],
        "velocity_variance": [velocity[i] for i in (0, 6, 11)],
        "reset_counter": wire["reset_counter"], "quality": 1,
    }
    if any(x < 0 for key in ("position_variance", "orientation_variance", "velocity_variance") for x in result[key]):
        raise ValueError("negative variance")
    return result


def audit_pairs(sent, received, *, px4_minus_remote_us):
    """Compare ordered whole streams without fitting a clock to received data.

    The caller must freeze and prove the clock offset separately. Even a match
    cannot establish TIMESYNC convergence: TimesyncStatus has no converged flag.
    """
    integer(px4_minus_remote_us, "offset", -MAX_US, MAX_US)
    if not isinstance(sent, list) or not isinstance(received, list):
        raise ValueError("streams must be lists")
    failures = []
    if not sent or not received:
        failures.append({"reason": "empty_stream"})
    if len(sent) != len(received):
        failures.append({"reason": "sample_count_mismatch"})
    matched = 0
    ids = set()
    last_wire = last_sample = last_arrival = -1
    for index, (packet, row) in enumerate(zip(sent, received, strict=False)):
        try:
            expected = expected_fields(packet)
            if packet["id"] in ids:
                raise ValueError("duplicate send identity")
            ids.add(packet["id"])
            sample = packet["wire"]["time_usec"]
            if sample <= last_wire:
                raise ValueError("duplicate or regressed wire sample")
            last_wire = sample
            if not isinstance(row, dict) or set(row) != INTEGERS | set(VECTORS):
                raise ValueError("invalid receiver schema")
            for key in INTEGERS:
                integer(row[key], key)
            for key, size in VECTORS.items():
                vector(row[key], size, key, unavailable=key == "angular_velocity")
            if row["timestamp_sample"] <= last_sample or row["timestamp"] <= last_arrival:
                raise ValueError("duplicate or regressed receiver sample")
            last_sample, last_arrival = row["timestamp_sample"], row["timestamp"]
            expected_sample = integer(sample + px4_minus_remote_us, "mapped sample", 1)
            if abs(row["timestamp_sample"] - expected_sample) > TIME_TOLERANCE_US:
                raise ValueError("sample clock mismatch")
            age = row["timestamp"] - row["timestamp_sample"]
            if age <= TIME_TOLERANCE_US:
                raise ValueError("arrival/sample ambiguous or future")
            if age > MAX_ARRIVAL_AGE_US:
                raise ValueError("arrival age exceeded")
            for key, value in expected.items():
                if row[key] != value:
                    raise ValueError("field mismatch " + key)
            matched += 1
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            failures.append({"index": index, "reason": str(exc)})
    return {
        "schema": "px4-d6f12ad-receiver-field-parity-v1",
        "sent_count": len(sent), "received_count": len(received), "matched_count": matched,
        "failures": failures, "field_parity_pass": not failures,
        "px4_minus_remote_us": px4_minus_remote_us,
        "time_tolerance_us": TIME_TOLERANCE_US, "max_arrival_age_us": MAX_ARRIVAL_AGE_US,
        "timesync_convergence_qualified": False, "receiver_stage_qualified": False,
        "ekf2_fusion_qualified": False,
    }


def decode_sent_packets(records):
    """Decode retained unsigned MAVLink 2 bytes; never open a transport."""
    if not isinstance(records, list):
        raise ValueError("invalid packet journal")
    decoded = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {"id", "packet_hex"}:
            raise ValueError("invalid packet record")
        packet = bytes.fromhex(record["packet_hex"])
        if len(packet) < 12 or packet[0] != 0xFD or packet[2:4] != b"\0\0" or len(packet) != packet[1] + 12:
            raise ValueError("not one unsigned MAVLink2 packet")
        fields = decode_candidate(packet)
        fields.pop("mavpackettype")
        for key, value in list(fields.items()):
            if isinstance(value, list):
                fields[key] = [None if isinstance(x, float) and math.isnan(x) else x for x in value]
            elif isinstance(value, float) and math.isnan(value):
                fields[key] = None
        decoded.append({"id": record["id"], "source_system": packet[5], "source_component": packet[6], "wire": fields})
    return decoded


def extract_receiver_rows(ulog):
    """Extract decoded rows. Raw file evidence must enter through read_receiver_log."""
    if ulog.file_corruption or ulog.dropouts:
        raise ValueError("ULog corruption or dropout")
    topics = [topic for topic in ulog.data_list if topic.name == "vehicle_visual_odometry"]
    if len(topics) != 1 or topics[0].multi_id != 0:
        raise ValueError("missing or ambiguous vehicle_visual_odometry")
    data = topics[0].data
    columns = sorted(INTEGERS) + [f"{key}[{i}]" for key, size in VECTORS.items() for i in range(size)]
    if any(key not in data for key in columns):
        raise ValueError("missing ULog field")
    lengths = {len(data[key]) for key in columns}
    if len(lengths) != 1 or 0 in lengths:
        raise ValueError("empty or inconsistent ULog column lengths")

    def scalar(key, index):
        value = data[key][index]
        if hasattr(value, "item"):
            value = value.item()
        if isinstance(value, float) and math.isnan(value):
            return None
        return value

    rows = []
    for index in range(next(iter(lengths))):
        row = {key: scalar(key, index) for key in INTEGERS}
        row.update({key: [scalar(f"{key}[{i}]", index) for i in range(size)] for key, size in VECTORS.items()})
        rows.append(row)
    return rows


def validate_ulog_stream(raw):
    """Check complete v1 framing and subscription accounting before pyulog.

    This narrow evidence profile refuses appended logs, unsubscribe/reuse and
    unknown records. It is not a general ULog validator or a content checksum.
    pyulog 1.2.4 can silently ignore truncated tails and overwrite subscriptions.
    """
    if not isinstance(raw, bytes) or len(raw) < 16 or raw[:8] != b'ULog\x01\x12\x35\x01':
        raise ValueError('invalid or unsupported ULog header')
    offset = 16
    count = receiver_count = 0
    subscriptions = {}
    topics = set()
    formats = set()
    data_section = False
    while offset < len(raw):
        start = offset
        if len(raw)-offset < 3:
            raise ValueError(f'truncated ULog record header at {offset}')
        size, kind = struct.unpack_from('<HB', raw, offset)
        offset += 3
        if len(raw)-offset < size:
            raise ValueError(f'truncated ULog payload at {start}')
        payload = raw[offset:offset+size]
        offset += size
        count += 1
        kind = chr(kind)
        if count == 1 and kind != 'B':
            raise ValueError('missing initial ULog flags')
        if kind == 'B':
            if count != 1 or size < 40:
                raise ValueError('invalid ULog flags placement/size')
            if any(payload[8:40]):
                raise ValueError('unsupported ULog incompatibility or appended data')
        elif kind == 'F':
            name, separator, fields = payload.decode('ascii').partition(':')
            if data_section or not name or not separator or not fields or name in formats:
                raise ValueError('invalid or repeated ULog format')
            formats.add(name)
        elif kind == 'A':
            data_section = True
            if size <= 3:
                raise ValueError('short ULog subscription')
            multi_id, msg_id = struct.unpack_from('<BH', payload)
            name = payload[3:].decode('ascii')
            key = (name, multi_id)
            if msg_id in subscriptions or key in topics:
                raise ValueError('reused ULog subscription id/topic')
            if name not in formats:
                raise ValueError('undefined ULog subscription format')
            subscriptions[msg_id] = key
            topics.add(key)
        elif kind == 'D':
            if size < 2:
                raise ValueError('short ULog data record')
            msg_id = struct.unpack_from('<H', payload)[0]
            if msg_id not in subscriptions:
                raise ValueError('ULog data without subscription')
            if subscriptions[msg_id][0] == 'vehicle_visual_odometry':
                receiver_count += 1
        elif kind == 'O':
            raise ValueError('ULog dropout')
        elif kind not in 'IMPQLCS':
            raise ValueError('unsupported ULog record type '+kind)
        if kind in 'LC':
            data_section = True
    if count == 0:
        raise ValueError('empty ULog messages')
    return {'profile': 'complete-unappended-ulog-v1', 'bytes': len(raw),
            'message_count': count, 'receiver_data_count': receiver_count}


class _ObservedULogBuffer(io.BytesIO):
    """Keep the last read even after pyulog closes its input.

    Pinned 1.2.4 normally finishes by attempting a three-byte header at EOF.
    Its swallowed internal struct.error exits without that terminal read.
    """

    def __init__(self, raw):
        super().__init__(raw)
        self.last_read = None

    def read(self, size=-1):
        start = self.tell()
        result = super().read(size)
        self.last_read = (start, size, len(result))
        return result


def read_receiver_log(path):
    """Validate and decode the same immutable byte buffer, without transport."""
    raw = path.read_bytes()
    framing = validate_ulog_stream(raw)
    if importlib.metadata.version('pyulog') != '1.2.4':
        raise ValueError('unverified pyulog version')
    from pyulog import ULog

    stream = _ObservedULogBuffer(raw)
    try:
        parsed = ULog(stream, disable_str_exceptions=False)
    except (struct.error, NotImplementedError, IndexError, RecursionError) as exc:
        raise ValueError(f'ULog parser {type(exc).__name__}: {exc}') from exc
    finally:
        stream.close()
    if stream.last_read != (len(raw), 3, 0):
        raise ValueError('ULog parser did not reach normal EOF')
    rows = extract_receiver_rows(parsed)
    if len(rows) != framing['receiver_data_count']:
        raise ValueError('raw/decoded receiver count mismatch')
    return rows, framing
