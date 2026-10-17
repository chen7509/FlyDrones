"""Compare a retained wire journal with PX4 ULog, without network or simulation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.benchmark.openvins_receiver_parity import (  # noqa: E402
    audit_pairs,
    decode_sent_packets,
    read_receiver_log,
)


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key " + key)
        result[key] = value
    return result


def read_clock(path):
    def reject_constant(value):
        raise ValueError("nonfinite JSON constant " + value)

    clock = json.loads(path.read_bytes(), object_pairs_hook=strict_object, parse_constant=reject_constant)
    if not isinstance(clock, dict) or set(clock) != {"schema", "px4_minus_remote_us"}:
        raise ValueError("invalid frozen clock contract")
    if clock["schema"] != "px4-receiver-parity-clock-v1":
        raise ValueError("invalid frozen clock schema")
    return clock["px4_minus_remote_us"]


def identity(path):
    data = path.read_bytes()
    return {"path": str(path.resolve()), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packets", type=Path, required=True)
    parser.add_argument("--ulog", type=Path, required=True)
    parser.add_argument("--clock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError(args.output)
    inputs = {}
    try:
        for role in ("packets", "ulog", "clock"):
            inputs[role] = identity(getattr(args, role))
        offset = read_clock(args.clock)
        records = json.loads(args.packets.read_bytes(), object_pairs_hook=strict_object)
        sent = decode_sent_packets(records)
        rows, framing = read_receiver_log(args.ulog)
        result = audit_pairs(sent, rows, px4_minus_remote_us=offset)
        result['ulog_framing'] = framing
        for role, before in inputs.items():
            if identity(getattr(args, role)) != before:
                raise ValueError("input changed during audit: " + role)
    except (OSError, ValueError, TypeError, KeyError, OverflowError, ImportError) as exc:
        result = {
            "schema": "px4-d6f12ad-receiver-field-parity-v1",
            "field_parity_pass": False,
            "failures": [{"reason": str(exc), "type": type(exc).__name__}],
            "receiver_stage_qualified": False, "timesync_convergence_qualified": False,
            "ekf2_fusion_qualified": False,
        }
    result["inputs"] = inputs
    result["audit_network_access"] = False
    result["task5_authorized"] = False
    with args.output.open("x", encoding="utf8") as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["field_parity_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
