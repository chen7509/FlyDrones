"""Offline integrity audit of one opt-in EGO bridge byte journal.

Completeness here means internal journal framing only. It is not source,
DDS-delivery, planner-consumption or training-label qualification.
"""

from __future__ import annotations

import base64
import binascii
import hashlib

from tools.benchmark.ego_bridge_cdr_journal import MAX_NS, TOPIC

CORE = frozenset({
    "schema", "run_id", "session", "pid", "sequence", "message_sequence",
    "phase", "kind", "topic", "sample_ns", "event_steady_ns",
    "message_sha256", "message_bytes", "message_cdr_b64", "source",
    "source_profile_sha256", "truth_used",
})
EXTRA = {"reset": frozenset({"seed"}),
         "command_decoded": frozenset({"trajectory_id", "ready"})}


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= MAX_NS:
        raise ValueError(f"invalid {label}")
    return value


def _bytes(row: dict) -> bytes:
    encoded = row["message_cdr_b64"]
    if type(encoded) is not str:
        raise ValueError("missing raw CDR bytes")
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid raw CDR bytes") from exc
    if (not payload or base64.b64encode(payload).decode("ascii") != encoded
            or hashlib.sha256(payload).hexdigest() != row["message_sha256"]
            or len(payload) != _integer(row["message_bytes"], "message length", minimum=1)):
        raise ValueError("raw CDR digest or length mismatch")
    return payload


def audit_bridge_cdr_journal(rows: object) -> dict:
    """Reject a partial/changed journal; never infer runtime source identity."""
    if type(rows) is not list or len(rows) < 3:
        raise ValueError("incomplete bridge journal")
    if (type(rows[0]) is not dict or type(rows[1]) is not dict
            or type(rows[-1]) is not dict):
        raise ValueError("malformed bridge journal boundary")
    if rows[0].get("phase") != "session_open" or rows[1].get("phase") != "reset":
        raise ValueError("missing journal session or reset")
    if rows[-1].get("phase") != "closed":
        raise ValueError("incomplete bridge journal close")
    first = rows[0]
    run_id, session, pid = first.get("run_id"), first.get("session"), first.get("pid")
    if type(run_id) is not str or not run_id or type(session) is not str or not session:
        raise ValueError("invalid bridge identity")
    _integer(pid, "pid", minimum=1)
    last_clock = -1
    next_message = 1
    pending_publish = None
    pending_command = None
    publication_count = 0
    received_command_count = 0
    for sequence, row in enumerate(rows, 1):
        if type(row) is not dict or type(row.get("phase")) is not str:
            raise ValueError("malformed bridge row")
        phase = row["phase"]
        if row.keys() != CORE | EXTRA.get(phase, frozenset()):
            raise ValueError("unexpected bridge journal fields")
        if (row["schema"] != "flydrones-ego-bridge-cdr-v1" or row["run_id"] != run_id
                or row["session"] != session
                or _integer(row["pid"], "pid", minimum=1) != pid
                or _integer(row["sequence"], "journal sequence", minimum=1) != sequence):
            raise ValueError("bridge identity or sequence gap")
        clock = _integer(row["event_steady_ns"], "journal steady clock", minimum=1)
        if clock < last_clock:
            raise ValueError("journal clock regressed")
        last_clock = clock
        if row["source_profile_sha256"] is not None or row["truth_used"] != "unknown":
            raise ValueError("bridge source has been relabeled")
        kind = row["kind"]
        if kind is None:
            if row["topic"] is not None or row["source"] is not None:
                raise ValueError("unexpected source on lifecycle row")
        elif (type(kind) is not str or kind not in TOPIC or row["topic"] != TOPIC[kind]
              or row["source"] != ("unattested_ego_server"
                                   if kind == "position_command" else "unattested_socket")):
            raise ValueError("unexpected bridge source or topic")
        if pending_publish is not None and phase != "publish_returned":
            raise ValueError("incomplete publish intent")
        if phase in ("session_open", "reset", "closed"):
            if ((phase == "session_open" and sequence != 1)
                    or (phase == "reset" and sequence != 2)
                    or (phase == "closed" and sequence != len(rows))
                    or kind is not None or row["message_sequence"] is not None
                    or row["sample_ns"] is not None or row["message_sha256"] is not None
                    or row["message_bytes"] is not None or row["message_cdr_b64"] is not None):
                raise ValueError("invalid bridge lifecycle")
            if phase == "reset":
                _integer(row["seed"], "reset seed")
            if phase == "closed" and pending_command is not None:
                raise ValueError("incomplete command decode")
        elif phase in ("publish_intent", "command_received"):
            message_seq = _integer(row["message_sequence"], "message sequence", minimum=1)
            if message_seq != next_message:
                raise ValueError("message sequence gap")
            next_message += 1
            _bytes(row)
            if phase == "publish_intent":
                if kind == "position_command":
                    raise ValueError("bridge cannot publish command")
                _integer(row["sample_ns"], "publication sample")
                pending_publish = row
            else:
                if kind != "position_command" or row["sample_ns"] is not None:
                    raise ValueError("invalid raw command receipt")
                if pending_command is not None:
                    raise ValueError("overlapping raw commands")
                pending_command = message_seq
                received_command_count += 1
        elif phase == "publish_returned":
            if (pending_publish is None or row["message_cdr_b64"] is not None
                    or any(row[key] != pending_publish[key]
                           for key in ("kind", "topic", "message_sequence", "sample_ns",
                                       "message_sha256", "message_bytes"))):
                raise ValueError("unmatched publish return")
            pending_publish = None
            publication_count += 1
        elif phase == "command_decoded":
            if (kind != "position_command" or row["message_sequence"] != pending_command
                    or row["message_cdr_b64"] is not None
                    or row["message_sha256"] is not None or row["message_bytes"] is not None
                    or type(row["ready"]) is not bool):
                raise ValueError("unmatched command decode")
            _integer(row["sample_ns"], "command stamp")
            _integer(row["trajectory_id"], "trajectory id")
            pending_command = None
        else:
            raise ValueError("failure or unknown bridge phase")
    return {
        "run_id": run_id,
        "session_id": session,
        "publication_count": publication_count,
        "received_command_count": received_command_count,
        "journal_complete": True,
        "source_attested": False,
        "dds_delivery_verified": False,
        "planner_consumption_verified": False,
        "teacher_qualified": False,
    }
