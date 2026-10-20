"""Join complete bridge CDR records to pinned EGO diagnostic identities.

This is an offline byte-identity candidate. Strict field mode may compare a
canonical command digest after separately recording the DDS raw zero padding;
the socket source, planner binary, and teacher label remain unqualified.
"""

from __future__ import annotations

from flydrones.benchmark.ego_diagnostic_reconcile import _reconcile_diagnostics
from tools.benchmark.ego_bridge_cdr_audit import audit_bridge_cdr_journal

_INPUT_KINDS = frozenset({"odometry", "depth", "camera_pose"})


def reconcile_cdr_diagnostics(bridge_rows: list[dict], planner_rows: list[dict],
                              server_rows: list[dict], *, run_id: str,
                              session_id: str, verify_payload_fields: bool = False) -> dict:
    """Match raw or strictly canonicalized CDR digests without source grants."""
    audit = audit_bridge_cdr_journal(bridge_rows)
    if type(verify_payload_fields) is not bool:
        raise ValueError("verify_payload_fields must be boolean")
    field_audit = None
    if verify_payload_fields:
        from tools.benchmark.ego_cdr_field_audit import audit_ego_cdr_fields

        field_audit = audit_ego_cdr_fields(bridge_rows)
    if audit["run_id"] != run_id or audit["session_id"] != session_id:
        raise ValueError("bridge run or session mismatch")

    decoded = {row["message_sequence"]: row for row in bridge_rows
               if row["phase"] == "command_decoded"}
    projected = []
    command_metadata = {}
    command_transport = {}
    for row in bridge_rows:
        phase, kind = row["phase"], row["kind"]
        if phase == "publish_intent" and kind in _INPUT_KINDS:
            sample_ns = row["sample_ns"]
        elif phase == "command_received":
            metadata = decoded[row["message_sequence"]]
            sample_ns = metadata["sample_ns"]
            identity = (field_audit["position_command_canonicalizations"][row["message_sequence"]]
                        if field_audit is not None else None)
            digest = identity["canonical_sha256"] if identity else row["message_sha256"]
            key = (digest, sample_ns)
            if key in command_metadata:
                raise ValueError("ambiguous canonical command identity")
            command_metadata[key] = metadata
            command_transport[key] = identity
        else:
            continue
        projected.append({
            "schema": 1, "run_id": run_id, "session": session_id,
            "pid": row["pid"], "sequence": len(projected) + 1,
            "kind": kind, "message_sha256": (digest if phase == "command_received"
                                              else row["message_sha256"]),
            "sample_ns": sample_ns, "event_steady_ns": row["event_steady_ns"],
            "source": row["source"], "source_profile_sha256": None,
            "truth_used": "unknown",
        })

    match = _reconcile_diagnostics(projected, planner_rows, server_rows,
                                   run_id=run_id, session_id=session_id,
                                   source_mode="unattested_cdr")
    selected_commands = [row for row in server_rows
                         if row.get("event") == "server_command_published"
                         and row.get("command_sha256") == match["command_sha256"]]
    if len(selected_commands) != 1:
        raise ValueError("server command identity ambiguous")
    command_stamp = int(selected_commands[0]["command_stamp_ns"])
    metadata = command_metadata.get((match["command_sha256"], command_stamp))
    if (metadata is None or metadata["ready"] is not True
            or metadata["trajectory_id"] != match["trajectory_id"]):
        raise ValueError("bridge command decode identity or readiness mismatch")
    selected_transport = command_transport.get((match["command_sha256"], command_stamp))
    match["canonical_digest_identity_candidate"] = (
        match["identity_match"] if selected_transport is not None else False)
    match["digest_identity_candidate"] = (
        match["identity_match"] and (selected_transport is None
                                      or selected_transport["padding_bytes"] == 0))
    match["command_raw_sha256"] = (selected_transport["raw_sha256"]
                                   if selected_transport is not None else match["command_sha256"])
    match["command_canonical_sha256"] = match["command_sha256"]
    match["command_transport_padding_bytes"] = (selected_transport["padding_bytes"]
                                                 if selected_transport is not None else None)
    match["byte_exact_command_transport_match"] = (
        selected_transport is not None and selected_transport["padding_bytes"] == 0)
    match["recorded_order_candidate"] = match["current_observation_match"]
    match["identity_match"] = False
    match["current_observation_match"] = False
    match["cdr_journal_internal_complete"] = audit["journal_complete"]
    match["cdr_payload_fields_verified"] = field_audit is not None
    match["stamp_binding_verified"] = field_audit is not None
    match["cdr_field_audit"] = field_audit
    match["ros_runtime_type_support_verified"] = False
    match["source_attested"] = False
    match["dds_delivery_verified"] = False
    return match
