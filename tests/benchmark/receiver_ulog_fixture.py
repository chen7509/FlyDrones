"""Analytic ULog v1 bytes, independent of pyulog and the production comparator."""

import struct


def record(kind, payload):
    return struct.pack('<HB', len(payload), ord(kind)) + payload


def receiver_log(rows):
    fields = [('uint64_t', 'timestamp', 'Q'), ('uint64_t', 'timestamp_sample', 'Q'),
              ('uint8_t', 'pose_frame', 'B'), ('float[3]', 'position', '3f'),
              ('float[4]', 'q', '4f'), ('uint8_t', 'velocity_frame', 'B'),
              ('float[3]', 'velocity', '3f'), ('float[3]', 'angular_velocity', '3f'),
              ('float[3]', 'position_variance', '3f'), ('float[3]', 'orientation_variance', '3f'),
              ('float[3]', 'velocity_variance', '3f'), ('uint8_t', 'reset_counter', 'B'),
              ('int8_t', 'quality', 'b')]
    header = b'ULog\x01\x12\x35\x01' + struct.pack('<Q', 1)
    format_text = 'vehicle_visual_odometry:' + ''.join(f'{t} {name};' for t, name, _ in fields)
    definitions = header + record('B', bytes(40)) + record('F', format_text.encode())
    subscription = record('A', b'\x00\x00\x00vehicle_visual_odometry')
    data_records = []
    for row in rows:
        payload = struct.pack('<H', 0)
        for _, name, encoding in fields:
            values = row[name] if isinstance(row[name], list) else [row[name]]
            payload += struct.pack('<' + encoding, *(float('nan') if v is None else v for v in values))
        data_records.append(record('D', payload))
    return definitions, subscription, data_records
