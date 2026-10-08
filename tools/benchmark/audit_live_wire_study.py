"""Offline wire evidence readers. Full live-chain qualification is not implemented.

Integrity of retained files is distinct from receipt by PX4, source provenance,
or runtime success. These helpers grant neither live nor fusion qualification.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

from tools.benchmark.capture_contract import _typed_equal, _unique_pairs
from tools.benchmark.declared_runtime_snapshot import file_record
from tools.benchmark.openvins_segmented_journal import SegmentedWireJournal


def _equal(value, expected, label):
    if not _typed_equal(value, expected):
        raise ValueError("inconsistent " + label)


def _shape(value, keys, label):
    if type(value) is not dict or value.keys() != set(keys):
        raise ValueError("invalid " + label + " schema")


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("invalid " + label)


def _json(raw):
    def invalid(value):
        raise ValueError("nonfinite JSON: " + value)

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            invalid(value)
        return number

    return json.loads(raw, object_pairs_hook=_unique_pairs, parse_constant=invalid, parse_float=finite_float)


def _read_stable(path, maximum):
    if path.is_symlink() or path.stat().st_size > maximum:
        raise ValueError("symlink or oversized evidence member")
    before = file_record(path)
    with path.open("rb") as source:
        data = source.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("evidence member exceeded read bound")
    _equal(file_record(path), before, "evidence identity during read")
    _equal(len(data), before["bytes"], "evidence read length")
    _equal(hashlib.sha256(data).hexdigest(), before["sha256"], "evidence read hash")
    return data, before


def read_segmented_wire_records(directory, terminal):
    """Verify producer member index against terminal evidence and raw JSONL.

    The supplied terminal record still needs binding to capture/owner evidence by
    the complete auditor. Original directory strings may differ from an archive's
    extraction path; only the exact indexed local member names are opened here.
    """
    directory = Path(directory)
    keys = (
        "profile",
        "directory",
        "phase",
        "limits",
        "closed",
        "failure",
        "records",
        "bytes",
        "channels",
        "segments",
        "active",
        "unsealed",
        "failed_record",
        "unpersisted_failures",
        "complete_retention",
        "fsync_proven",
        "network_authorized",
        "fusion_qualified",
    )
    _shape(terminal, keys, "retention")
    limits = dict(segments=64, events_per_segment=8192, bytes=512 * 1024 * 1024)
    for key, expected in dict(
        profile="capture-wire-segmented-v1",
        limits=limits,
        closed=True,
        failure=None,
        active=None,
        unsealed=[],
        failed_record=None,
        unpersisted_failures={},
        complete_retention=True,
        fsync_proven=False,
        network_authorized=False,
        fusion_qualified=False,
    ).items():
        _equal(terminal[key], expected, "retention " + key)
    if type(terminal["directory"]) is not str or not terminal["directory"]:
        raise ValueError("original retention directory missing")
    phases = ("bootstrap", "maintenance", "stopping")
    if terminal["phase"] not in phases:
        raise ValueError("unknown terminal phase")
    _integer(terminal["records"], 1, 64 * 8192, "record count")
    _integer(terminal["bytes"], 1, limits["bytes"], "total bytes")
    channels = terminal["channels"]
    if type(channels) is not dict or not channels or not channels.keys() <= SegmentedWireJournal.CHANNELS:
        raise ValueError("unknown/empty channel set")
    for count in channels.values():
        _integer(count, 0, terminal["records"], "channel count")
    members = terminal["segments"]
    if type(members) is not list or not 1 <= len(members) <= 64:
        raise ValueError("invalid segment count")
    manifest_raw, manifest_identity = _read_stable(directory / "manifest.json", 1024 * 1024)
    index = _json(manifest_raw)
    expected_index = copy.deepcopy(terminal)
    expected_index.update(complete_retention=False, manifest_scope="member_index_not_completion_grant")
    _equal(index, expected_index, "member index versus terminal retention")
    expected_names = {"manifest.json", *(f"segment-{n:04d}.jsonl" for n in range(len(members)))}
    _equal({path.name for path in directory.iterdir()}, expected_names, "directory members")
    rows, identities = [], [manifest_identity]
    counts = {key: 0 for key in channels}
    total_bytes, phase_index = 0, 0
    for number, member in enumerate(members):
        _shape(member, ("name", "first_index", "last_index", "records", "bytes", "sha256"), "segment")
        _equal(member["name"], f"segment-{number:04d}.jsonl", "segment name")
        _integer(member["records"], 1, 8192, "segment records")
        if number < len(members) - 1:
            _equal(member["records"], 8192, "full preceding segment")
        _integer(member["bytes"], 1, limits["bytes"] - total_bytes, "segment bytes")
        _equal(member["first_index"], len(rows), "segment first index")
        _equal(member["last_index"], len(rows) + member["records"] - 1, "segment last index")
        data, identity = _read_stable(directory / member["name"], member["bytes"])
        identities.append(identity)
        _equal(len(data), member["bytes"], "member length")
        _equal(identity["sha256"], member["sha256"], "member hash")
        if not data.endswith(b"\n"):
            raise ValueError("unterminated JSONL member")
        lines = data.splitlines()
        _equal(len(lines), member["records"], "member line count")
        for line in lines:
            row = _json(line)
            _shape(row, ("index", "source", "source_index", "phase", "event"), "wire row")
            _equal(row["index"], len(rows), "global ordinal")
            if type(row["source"]) is not str or row["source"] not in counts:
                raise ValueError("undeclared channel")
            _equal(row["source_index"], counts[row["source"]], "channel ordinal")
            if row["phase"] not in phases or phases.index(row["phase"]) < phase_index:
                raise ValueError("invalid/regressed phase")
            phase_index = phases.index(row["phase"])
            if type(row["event"]) is not dict:
                raise ValueError("event must be a dictionary")
            counts[row["source"]] += 1
            rows.append(row)
        total_bytes += len(data)
    _equal(counts, channels, "final channel counts")
    _equal(len(rows), terminal["records"], "total records")
    _equal(total_bytes, terminal["bytes"], "total bytes")
    if phase_index > phases.index(terminal["phase"]):
        raise ValueError("terminal phase precedes retained event")
    for identity in identities:
        _equal(file_record(identity["requested"]), identity, "final evidence identity")
    _equal({path.name for path in directory.iterdir()}, expected_names, "final directory members")
    return dict(
        records=rows, channels=counts, members=identities, integrity_verified=True, live_qualified=False, fusion_qualified=False
    )


def _clock_records(clock, attempts, context):
    signature = context["clock_signature"]
    if type(signature) is not list or len(signature) != 3 or type(signature[0]) is not str:
        raise ValueError("invalid clock signature")
    for value in signature[1:]:
        _integer(value, 0, 2**63 - 1, "clock origin")
    _shape(
        clock,
        (
            "session_id",
            "observations",
            "attempts",
            "failure",
            "pending_callback_ns",
            "runtime_source_proven",
            "px4_clock_consumption_proven",
            "network_authorized",
            "fusion_qualified",
        ),
        "clock evidence",
    )
    _equal(clock["session_id"], signature[0], "clock session")
    for field in ("failure", "pending_callback_ns"):
        _equal(clock[field], None, "terminal clock " + field)
    for field in ("runtime_source_proven", "px4_clock_consumption_proven", "network_authorized", "fusion_qualified"):
        _equal(clock[field], False, "clock authority " + field)
    for rows in (clock["observations"], clock["attempts"], attempts):
        if type(rows) is not list or len(rows) != 25000:
            raise ValueError("complete 25000-step clock evidence required")
    previous = context["start_ns"]
    for iteration, (disk, attempt, observation) in enumerate(zip(attempts, clock["attempts"], clock["observations"]), 1):
        _shape(observation, ("iteration", "sim_ns", "callback_ns", "journal_return_ns"), "clock observation")
        callback, returned = observation["callback_ns"], observation["journal_return_ns"]
        _integer(callback, previous, context["total_deadline_ns"] - 1, "callback time")
        _integer(returned, callback, min(callback + 2_000_000_000, context["total_deadline_ns"]) - 1, "journal return")
        _equal(observation["iteration"], iteration, "clock iteration")
        _equal(observation["sim_ns"], iteration * 1_000_000, "clock step")
        expected = dict(
            kind="clock_observation_attempt",
            session_id=signature[0],
            iteration=iteration,
            sim_ns=iteration * 1_000_000,
            dt_ns=1_000_000,
            paused=False,
            callback_ns=callback,
        )
        _equal(disk, expected, "disk clock attempt")
        _equal(attempt, dict(expected, journal_return_ns=returned, accepted=True), "committed clock attempt")
        previous = returned
    return clock["observations"]


def _replay_status_records(records, context):
    """Replay the actual fixed cold/maintenance classes, including legal replays."""
    from tools.benchmark.openvins_timesync_bootstrap import ColdTimesyncBootstrap
    from tools.benchmark.owned_daemon_connection import validate_owner

    validate_owner(context["owner"])
    epoch = hashlib.sha256(json.dumps(context["owner"], sort_keys=True).encode()).hexdigest()
    rows = [row for row in records if row["source"] in ("cold", "maintenance")]
    cursor = 0

    def emitted(source, event):
        nonlocal cursor
        if cursor >= len(rows):
            raise ValueError("missing produced status record")
        _equal(source, rows[cursor]["source"], "status channel")
        _equal(event, rows[cursor]["event"], "replayed status event")
        cursor += 1

    cold = ColdTimesyncBootstrap(context["clock_signature"][0], epoch, context["start_ns"], lambda event: emitted("cold", event))
    maintenance = None
    while cursor < len(rows):
        row = rows[cursor]
        event, source = row["event"], row["source"]
        kind = event.get("kind")
        args = dict(now_ns=event.get("now_ns"), epoch_token=epoch)
        if source == "cold":
            if kind == "empty_snapshot":
                cold.confirm_empty(bytes.fromhex(event["raw_hex"]), 0, **args)
            elif kind == "reply_intent":
                cold.reserve_reply(event["intent"]["request_ns"], event["intent"]["response_ns"], **args)
            elif kind == "first_status":
                cold.confirm_first(bytes.fromhex(event["raw_hex"]), 0, **args)
            elif kind == "stream_start":
                cold.begin_stream(event["listener_token"], **args)
            elif kind == "raw_chunk":
                cold.feed_stream(bytes.fromhex(event["raw_hex"]), event["listener_token"], **args)
            elif kind == "stream_finished":
                cold.finish_stream(0, cold._listener, **args)
            elif kind == "continuation_transfer_attempt":
                _equal(event["deadline_ns"], context["total_deadline_ns"], "maintenance deadline")
                maintenance = cold.take_continuation(
                    event["listener_token"], event["deadline_ns"], lambda item: emitted("maintenance", item), **args
                )
            else:
                raise ValueError("unexpected/unproduced cold event")
        else:
            if maintenance is None:
                raise ValueError("maintenance before handoff")
            if kind == "listener_transport_claim":
                maintenance._claim_transport(event["now_ns"])
            elif kind == "reply_intent":
                maintenance.reserve_reply(event["intent"]["request_ns"], event["intent"]["response_ns"], **args)
            elif kind == "raw_chunk":
                maintenance.feed_stream(bytes.fromhex(event["raw_hex"]), event["listener_token"], **args)
            elif kind == "cancellation_requested":
                state = maintenance.progress
                if not state["maintenance_healthy"] or state["pending_reply"]:
                    raise ValueError("maintenance stopped without healthy completed pair")
                maintenance.cancel(event["reason"], **args)
            else:
                raise ValueError("unexpected/unproduced maintenance event")
    if (
        cold.progress["modeled_accepted_samples"] != 500
        or not cold.progress["continuation_taken"]
        or maintenance is None
        or maintenance.progress["failure"] is not None
        or maintenance.progress["phase"] != "cancelled"
        or maintenance.progress["maintenance_correlated_samples"] < 2
        or maintenance.progress["modeled_accepted_samples"] - 500 < 2
    ):
        raise ValueError("incomplete normal bootstrap/maintenance")
    return rows, maintenance.progress["modeled_accepted_samples"] - 500


def audit_wire_protocol_records(*, records, clock, clock_attempts, context):
    """Check raw protocol joins, not ownership, interval restoration or workload.

    Inputs can be synthetic. Runtime/transport binding and file provenance remain
    prerequisites for the still-unimplemented whole-study auditor.
    """
    from tools.benchmark.openvins_timesync_wire import PinnedCodec

    _shape(context, ("owner", "start_ns", "total_deadline_ns", "clock_signature"), "protocol context")
    _integer(context["start_ns"], 0, 2**64 - 300_000_000_000, "start time")
    _equal(context["total_deadline_ns"], context["start_ns"] + 300_000_000_000, "total deadline")
    observations = _clock_records(clock, clock_attempts, context)
    if type(records) is not list or not records or len(records) > 64 * 8192:
        raise ValueError("invalid protocol history")
    counts = {}
    for index, row in enumerate(records):
        _shape(row, ("index", "source", "source_index", "phase", "event"), "protocol row")
        _equal(row["index"], index, "global index")
        if type(row["source"]) is not str or row["source"] not in SegmentedWireJournal.CHANNELS:
            raise ValueError("unexpected protocol channel")
        _equal(row["source_index"], counts.get(row["source"], 0), "source index")
        counts[row["source"]] = counts.get(row["source"], 0) + 1
        if type(row["event"]) is not dict or row["event"].get("kind") == "refusal":
            raise ValueError("invalid/refused normal protocol row")
    status_rows, maintenance_accepted = _replay_status_records(records, context)
    intents = [r for r in status_rows if r["event"]["kind"] == "reply_intent"]
    statuses = [r for r in status_rows if r["event"]["kind"] in ("first_status", "stream_status", "maintenance_status")]
    if len(intents) != len(statuses):
        raise ValueError("missing status for reserved reply")
    receiver = [r for r in records if r["source"] == "receiver" and r["event"]["kind"] == "receive_return"]
    selections = [r for r in records if r["source"] == "selection"]
    wire_rows = [r for r in records if r["source"] == "wire"]
    codec = PinnedCodec()
    rx_cursor = pair_cursor = 0
    received = selected = decoded = prepared = None
    sent = reserved = False
    last_time = context["start_ns"]
    for row in wire_rows:
        event = row["event"]
        kind = event.get("kind")
        now = event.get("at_last_checked_ns")
        _integer(now, last_time, context["total_deadline_ns"] - 1, "wire checked time")
        last_time = now
        if kind == "receive":
            if prepared is not None or rx_cursor >= len(receiver) or rx_cursor >= len(selections):
                raise ValueError("missing receive/selection or incomplete previous send")
            rx, selection = receiver[rx_cursor], selections[rx_cursor]
            if not rx["index"] < selection["index"] < row["index"]:
                raise ValueError("receive/selection causal order")
            rx_cursor += 1
            raw = bytes.fromhex(event["raw_hex"])
            returned = rx["event"]
            for key, value in dict(
                data_hex=event["raw_hex"],
                data_length=len(raw),
                flags=0,
                ancillary_count=0,
                peer=["127.0.0.1", 14588],
                received_ns=event["received_ns"],
                return_type="tuple",
            ).items():
                _equal(returned.get(key), value, "receiver " + key)
            _integer(event["received_ns"], context["start_ns"], now, "receive time")
            _equal(event["peer"], ["127.0.0.1", 14588], "wire peer")
            selected = selection["event"]
            _shape(selected, ("session_id", "observation", "received_ns", "selected_ns"), "selection")
            _equal(selected["session_id"], context["clock_signature"][0], "selected session")
            _equal(selected["received_ns"], event["received_ns"], "selected receive time")
            observation = selected["observation"]
            _integer(observation.get("iteration"), 1, 25000, "selected iteration")
            _equal(observation, observations[observation["iteration"] - 1], "selected committed observation")
            _integer(selected["selected_ns"], max(observation["journal_return_ns"], event["received_ns"]), now, "selected time")
            if now - min(observation["callback_ns"], event["received_ns"]) >= 2_000_000_000:
                raise ValueError("stale selected input")
            _equal(event["observed_sim_ns"], observation["sim_ns"], "received simulation observation")
            received, decoded = event, None
        elif kind == "decoded":
            if received is None or decoded is not None:
                raise ValueError("decoded event without unique receive")
            decoded = codec.decode_datagram(bytes.fromhex(received["raw_hex"]))
            _equal(event["messages"], decoded, "raw decoded messages")
            if any(m["system"] != 9 or m["component"] != 1 for m in decoded):
                raise ValueError("unexpected header identity")
            for message in decoded:
                if message["type"] == "HEARTBEAT" and message["fields"]["base_mode"] >= 128:
                    raise ValueError("armed heartbeat")
        elif kind == "reply_prepared":
            if decoded is None or prepared is not None or pair_cursor >= len(intents):
                raise ValueError("reply without raw request/status intent")
            requests = [m for m in decoded if m["type"] == "TIMESYNC"]
            if len(requests) != 1 or requests[0]["fields"]["tc1"] != 0:
                raise ValueError("missing/ambiguous original request")
            request = requests[0]["fields"]["ts1"]
            signature = context["clock_signature"]
            response = selected["observation"]["sim_ns"] - signature[1] + signature[2]
            _equal(event["request_ns"], request, "prepared request")
            _equal(event["response_ns"], response, "independent response")
            _equal(event["clock_session"], signature[0], "response session")
            raw = codec.encode_reply(request, response, event["sequence"])
            _equal(event["raw_hex"], raw.hex(), "encoded response")
            intent = intents[pair_cursor]
            _equal(
                intent["event"]["intent"],
                dict(
                    request_ns=request,
                    response_ns=response,
                    transmission_proven=False,
                    network_authorized=False,
                    fusion_qualified=False,
                ),
                "observer reply intent",
            )
            if not row["index"] < intent["index"]:
                raise ValueError("reply/intent causal order")
            prepared, sent, reserved = event, False, False
        elif kind == "reserved":
            if prepared is None or reserved:
                raise ValueError("unexpected duplicate reservation")
            _equal(event["intent"], intents[pair_cursor]["event"]["intent"], "wire reservation")
            if row["index"] <= intents[pair_cursor]["index"]:
                raise ValueError("reservation precedes observer")
            reserved = True
        elif kind == "send_attempt":
            if prepared is None or not reserved or sent:
                raise ValueError("send without unique prepared reservation")
            _equal(event["raw_hex"], prepared["raw_hex"], "actual send bytes")
            _equal(event["peer"], ["127.0.0.1", 14588], "send peer")
            sent = True
        elif kind == "send_return":
            if prepared is None or not sent:
                raise ValueError("send return without attempt")
            _equal(event["count"], len(bytes.fromhex(prepared["raw_hex"])), "kernel send count")
            _integer(event["send_started_ns"], selected["selected_ns"], event["returned_ns"], "send start")
            _integer(
                event["returned_ns"],
                event["send_started_ns"],
                min(event["send_started_ns"] + 2_000_000_000, context["total_deadline_ns"]) - 1,
                "send return",
            )
            status = statuses[pair_cursor]
            if status["index"] <= row["index"] or status["event"]["now_ns"] < event["returned_ns"]:
                raise ValueError("status precedes completed send")
            pair_cursor += 1
            prepared = None
    if prepared is not None or pair_cursor != len(intents) or rx_cursor != len(receiver) or rx_cursor != len(selections):
        raise ValueError("incomplete protocol joins")
    return dict(
        protocol_consistent=True,
        bootstrap_accepted=500,
        maintenance_accepted=maintenance_accepted,
        noncounting_boundaries=2,
        reply_chains=pair_cursor,
        clock_observations=25000,
        owner_transport_qualified=False,
        interval_qualified=False,
        workload_qualified=False,
        live_qualified=False,
        fusion_qualified=False,
    )
