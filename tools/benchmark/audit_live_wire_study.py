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


def audit_owned_listener_records(*, records, context, daemon_path):
    """Join retained connection/command/stdout records, not attest a launch.

    SO_PEERCRED observations bind the recorded connection to the declared owner.
    The producer does not journal every owner recheck or a kernel descriptor ID;
    this helper cannot prove fresh launch, absence of FD transfer, or daemon exit.
    Caller must separately verify runtime ownership, workload and cleanup.
    """
    from pathlib import PurePosixPath

    from tools.benchmark.openvins_listener_transport import ReplyEnvelope, listener_command
    from tools.benchmark.openvins_timesync_bootstrap import parse_snapshot
    from tools.benchmark.openvins_timesync_listener import TimesyncListenerDecoder
    from tools.benchmark.owned_daemon_connection import validate_owner

    _shape(context, ("owner", "start_ns", "total_deadline_ns", "clock_signature"), "listener context")
    validate_owner(context["owner"])
    start, end = context["start_ns"], context["total_deadline_ns"]
    _integer(start, 0, 2**64 - 300_000_000_001, "listener start")
    _integer(end, start + 8_000_000_001, start + 300_000_000_000, "listener deadline")
    if (
        type(daemon_path) is not str
        or not daemon_path.startswith("/")
        or "\0" in daemon_path
        or ".." in PurePosixPath(daemon_path).parts
        or not 1 <= len(daemon_path.encode()) <= 107
    ):
        raise ValueError("invalid daemon path")
    if type(records) is not list or not records:
        raise ValueError("missing listener records")
    counters = {}
    for index, row in enumerate(records):
        _shape(row, ("index", "source", "source_index", "phase", "event"), "listener record")
        _equal(row["index"], index, "record index")
        if type(row["source"]) is not str or type(row["event"]) is not dict:
            raise ValueError("record source/event")
        _equal(row["source_index"], counters.get(row["source"], 0), "source index")
        counters[row["source"]] = row["source_index"] + 1
    owned = [r for r in records if r["source"] == "owned"]
    last = start
    for row in owned:
        item = row["event"]
        keys = {"source", "command_index", "event", "at_ns"}
        if "time_basis" in item:
            _equal(item["time_basis"], "last_checked_clock_during_cleanup", "cleanup time basis")
            keys.add("time_basis")
        _shape(item, keys, "owned envelope")
        if item["command_index"] is not None:
            _integer(item["command_index"], 0, 3, "owned command index")
        if type(item["event"]) is not dict:
            raise ValueError("owned event schema")
        _integer(item["at_ns"], last, end - 1, "owned clock")
        last = item["at_ns"]
        if item["source"] not in ("coordinator", "transport", "bootstrap", "maintenance"):
            raise ValueError("unknown owned source")
    # Retention mirrors are separate producer writes. Neither is a substitute for
    # the other, and arbitrary duplicate status rows cannot supply missing I/O.
    for source, mirrored in (("cold", "bootstrap"), ("maintenance", "maintenance")):
        direct = [r for r in records if r["source"] == source]
        wrappers = [r for r in owned if r["event"]["source"] == mirrored]
        _equal(len(wrappers), len(direct), "owned status mirror count")
        for raw, wrapped in zip(direct, wrappers):
            _equal(wrapped["event"]["command_index"], None, "status command index")
            _equal(wrapped["event"]["event"], raw["event"], "owned status mirror")
            if (source == "cold" and wrapped["index"] >= raw["index"]) or (
                source == "maintenance" and raw["index"] >= wrapped["index"]
            ):
                raise ValueError("status mirror ordering")
    coordinators = [r for r in owned if r["event"]["source"] == "coordinator"]
    expected_order = [
        ("command_open", 0),
        ("command_finished", 0),
        ("command_open", 1),
        ("command_finished", 1),
        ("command_open", 2),
        ("command_finished", 2),
        ("maintenance_started", None),
        ("command_open", 3),
    ]
    _equal(
        [(r["event"]["event"].get("kind"), r["event"]["command_index"]) for r in coordinators],
        expected_order,
        "owned command lifecycle",
    )
    roles = ("empty", "first", "stream", "maintenance")
    for row in coordinators:
        item = row["event"]
        event = item["event"]
        if event["kind"] == "maintenance_started":
            _equal(event, {"kind": "maintenance_started", "deadline_ns": end}, "maintenance deadline")
        else:
            _equal(event, {"kind": event["kind"], "role": roles[item["command_index"]]}, "command role")
    bootstrap_records = maintenance_records = 0
    for number in range(4):
        opened = next(r for r in coordinators if r["event"]["command_index"] == number)
        boundary = (
            next(
                r
                for r in coordinators
                if r["event"]["command_index"] == number and r["event"]["event"]["kind"] == "command_finished"
            )["index"]
            if number < 3
            else len(records)
        )
        direct = [r for r in records if r["source"] == f"listener-{number}"]
        wrappers = [r for r in owned if r["event"]["source"] == "transport" and r["event"]["command_index"] == number]
        _equal(len(direct), len(wrappers), "transport mirror count")
        if len(direct) < 6:
            raise ValueError("incomplete listener transport")
        for i, (raw, wrapped) in enumerate(zip(direct, wrappers)):
            _equal(wrapped["event"]["event"], raw["event"], "transport mirror")
            upper = direct[i + 1]["index"] if i + 1 < len(direct) else boundary
            if not opened["index"] < raw["index"] < wrapped["index"] < upper:
                raise ValueError("transport mirror/command order")
        deadline = start + 8_000_000_000 if number < 3 else end
        entry = opened["event"]["at_ns"]
        connection, peer = direct[0]["event"], direct[1]["event"]
        _shape(connection, ("kind", "observation"), "connect envelope")
        _shape(peer, ("kind", "observation"), "peer envelope")
        _equal(connection["kind"], "connection", "connect kind")
        _equal(peer["kind"], "connection", "peer kind")
        attempt, observation = connection["observation"], peer["observation"]
        _shape(attempt, ("kind", "path", "owner", "deadline_ns", "at_ns"), "connect attempt")
        _equal(attempt["kind"], "connect_attempt", "connect operation")
        _equal(attempt["path"], daemon_path, "socket path")
        _equal(attempt["owner"], context["owner"], "connection owner")
        _integer(attempt["at_ns"], entry, deadline - 1, "connect time")
        _integer(
            attempt["deadline_ns"], attempt["at_ns"] + 1, min(deadline, attempt["at_ns"] + 2_000_000_000), "connect deadline"
        )
        _shape(observation, ("kind", "owner", "peer", "at_ns"), "peer observation")
        _equal(observation["kind"], "peer_observed", "peer operation")
        _equal(observation["owner"], context["owner"], "observed owner")
        _equal(observation["peer"], {k: context["owner"][k] for k in ("pid", "uid", "gid")}, "peer credential")
        _integer(observation["at_ns"], attempt["at_ns"], attempt["deadline_ns"] - 1, "peer time")
        command = listener_command("snapshot" if number < 2 else "stream", 1 if number < 2 else 500 if number == 2 else 4096)
        decoder = (
            None
            if number < 2
            else TimesyncListenerDecoder(0, 500 if number == 2 else 4096, entry, output_profile="px4-d6f12ad-multi-v1")
        )
        envelope, snapshot = ReplyEnvelope(), b""
        offset, pending, eof, parsed, cancelled = 0, None, False, False, False
        last = observation["at_ns"]
        consumer = "cold" if number < 3 else "maintenance"
        chunks = [
            r
            for r in records
            if r["source"] == consumer and r["event"].get("kind") == "raw_chunk" and opened["index"] < r["index"] < boundary
        ]
        used = count = 0
        for i in range(2, len(direct)):
            row, wrapper = direct[i], wrappers[i]["event"]
            event, kind = row["event"], row["event"].get("kind")
            now = event.get("at_ns", event.get("returned_clock_ns", wrapper["at_ns"]))
            _integer(now, last, deadline - 1, "listener event time")
            _integer(wrapper["at_ns"], now, deadline - 1, "listener wrapper time")
            last = now
            if parsed or cancelled:
                raise ValueError("record after listener terminal")
            if kind == "send_attempt":
                _shape(event, ("kind", "offset", "raw_hex", "at_ns"), "command attempt")
                if offset == len(command):
                    raise ValueError("command retransmission")
                _equal(event["offset"], offset, "command offset")
                _equal(event["raw_hex"], command[offset:].hex(), "allowed command bytes")
                pending = now
            elif kind == "send_return":
                _shape(event, ("kind", "count", "offset", "returned_clock_ns"), "command return")
                if pending is None:
                    raise ValueError("command return without attempt")
                _equal(event["offset"], offset, "command return offset")
                _integer(event["count"], 1, len(command) - offset, "command send count")
                offset += event["count"]
                pending = None
            elif kind == "recv_return":
                _shape(event, ("kind", "raw_hex", "eof", "returned_clock_ns"), "daemon read")
                if offset != len(command) or pending is not None or eof:
                    raise ValueError("read before command sent or after EOF")
                raw = bytes.fromhex(event["raw_hex"])
                _equal(raw.hex(), event["raw_hex"], "canonical raw bytes")
                _equal(event["eof"], not raw, "daemon EOF")
                if not raw:
                    envelope.finish()
                    eof = True
                else:
                    data = envelope.feed(raw)
                    if number < 2:
                        snapshot += data
                        if len(snapshot) > 1024:
                            raise ValueError("snapshot size")
                    elif data:
                        if used >= len(chunks):
                            raise ValueError("missing consumer stdout")
                        chunk = chunks[used]
                        used += 1
                        upper = direct[i + 1]["index"] if i + 1 < len(direct) else boundary
                        if not row["index"] < chunk["index"] < upper:
                            raise ValueError("stdout consumer order")
                        _equal(chunk["event"]["raw_hex"], data.hex(), "daemon stdout to consumer")
                        process_time = chunk["event"]["now_ns"]
                        _integer(process_time, wrapper["at_ns"], min(deadline - 1, now + 1_999_999_999), "stdout processing time")
                        count += len(decoder.feed(data, process_time))
            elif kind == "parsed_eof":
                _shape(event, ("kind", "terminal", "at_ns"), "parsed daemon EOF")
                if not eof or number == 3:
                    raise ValueError("missing daemon EOF or premature maintenance exit")
                expected = dict(parse_snapshot(snapshot, 0), raw_hex=snapshot.hex()) if number < 2 else decoder.finish(now, 0)
                _equal(event["terminal"], expected, "parsed terminal")
                target_kind = ("empty_snapshot", "first_status", "stream_finished")[number]
                matches = [
                    r
                    for r in records
                    if r["source"] == "cold" and r["event"].get("kind") == target_kind and row["index"] < r["index"] < boundary
                ]
                _equal(len(matches), 1, "terminal consumer count")
                if number < 2:
                    _equal(matches[0]["event"]["raw_hex"], snapshot.hex(), "snapshot to cold consumer")
                else:
                    _equal(matches[0]["event"]["terminal"], expected, "stream terminal to cold consumer")
                parsed = True
            elif kind == "cancellation_requested":
                _shape(event, ("kind", "reason"), "listener cancel")
                if number != 3 or i != len(direct) - 2 or eof or pending is not None:
                    raise ValueError("unexpected listener cancellation")
                _equal(event["reason"], "owned maintenance close", "cancel reason")
                decoder.check(now)
            elif kind == "cancellation_result":
                if number != 3 or direct[i - 1]["event"].get("kind") != "cancellation_requested":
                    raise ValueError("cancel result without intent")
                _equal(
                    event,
                    dict(
                        kind="cancellation_result",
                        incomplete_frame_bytes=0,
                        socket_close_returned=True,
                        close_error=None,
                        daemon_exit_proven=False,
                    ),
                    "socket cancellation result",
                )
                _equal(decoder.incomplete_frame_bytes, 0, "partial maintenance frame")
                cancelled = True
            else:
                raise ValueError("unknown or failed transport event")
        _equal(used, len(chunks), "all consumer raw chunks matched")
        if number < 3 and not parsed or number == 3 and not cancelled:
            raise ValueError("listener terminal missing")
        if number == 2:
            bootstrap_records = count
            _equal(count, 500, "bootstrap record count")
        elif number == 3:
            maintenance_records = count
            _integer(count, 3, 4095, "maintenance boundary plus responses")
    _equal(
        sum(1 for r in owned if r["event"]["source"] == "transport"),
        sum(1 for r in records if r["source"] in {f"listener-{i}" for i in range(4)}),
        "all transport mirrors consumed",
    )
    return dict(
        listener_records_consistent=True,
        connections=4,
        completed_commands=3,
        bootstrap_records=bootstrap_records,
        maintenance_records=maintenance_records,
        owner_launch_qualified=False,
        daemon_exit_proven=False,
        live_qualified=False,
        fusion_qualified=False,
    )


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


def audit_wire_interval_records(records, context):
    """Verify the normal raw rate transaction; no failure cleanup or live grant.

    This is an offline cross-check of the producer's normal bounded command
    sequence. PinnedCodec and restorable_interval retain the actual wire/PX4
    conversions. Caller must also verify protocol, owner, clock and shutdown.
    """
    from tools.benchmark.openvins_timesync_interval import restorable_interval
    from tools.benchmark.openvins_timesync_wire import PinnedCodec

    start = context["start_ns"]
    _integer(start, 0, 2**64 - 300_000_000_000, "interval start")
    deadline = start + 8_000_000_000
    if type(records) is not list or not records:
        raise ValueError("missing raw transaction history")
    for index, row in enumerate(records):
        _equal(row["index"], index, "transaction global ordinal")
    codec = PinnedCodec()
    commands, states = [], []
    pending = receive = None
    sequence = 0
    acknowledgments = readbacks = 0
    previous_events = []

    def complete(command):
        return (
            command is not None
            and command["returned"] is not None
            and command["pending_state"] is not None
            and command["ack"] is not None
            and (command["operation"] == "set" or command["readback"] is not None)
        )

    for row in records:
        if row["source"] != "wire":
            continue
        event, index = row["event"], row["index"]
        kind, now = event.get("kind"), event.get("at_last_checked_ns")
        _integer(now, start, context["total_deadline_ns"] - 1, "transaction event time")
        if kind in ("interval_send_attempt", "reply_prepared"):
            _equal(event["sequence"], sequence, "shared outgoing sequence")
            sequence = (sequence + 1) % 256
        if kind == "interval_send_attempt":
            if len(commands) >= 6 or pending is not None and not complete(pending):
                raise ValueError("command before prior raw responses completed")
            _integer(now, start, deadline - 1, "command startup deadline")
            raw = codec.encode_interval_command(event["operation"], event["value"], event["sequence"])
            _equal(event["raw_hex"], raw.hex(), "raw command encoding")
            _equal(event["peer"], ["127.0.0.1", 14588], "command peer")
            pending = dict(
                operation=event["operation"],
                value=event["value"],
                command=511 if event["operation"] == "set" else 510,
                attempt_index=index,
                attempt_ns=now,
                raw_bytes=len(raw),
                returned=None,
                pending_state=None,
                phase=None,
                ack=None,
                readback=None,
                last_response_index=None,
            )
            commands.append(pending)
        elif kind == "interval_send_return":
            if pending is None or pending["returned"] is not None:
                raise ValueError("unexpected command return")
            _equal(event["count"], pending["raw_bytes"], "command send length")
            _integer(event["send_started_ns"], pending["attempt_ns"], deadline - 1, "command send start")
            _integer(
                event["returned_ns"],
                event["send_started_ns"],
                min(deadline, event["send_started_ns"] + 2_000_000_000) - 1,
                "command return deadline",
            )
            pending["returned"] = event["returned_ns"]
        elif kind == "receive":
            receive = event
        elif kind == "decoded":
            if receive is None:
                raise ValueError("decoded transaction input without raw bytes")
            decoded = codec.decode_datagram(bytes.fromhex(receive["raw_hex"]))
            _equal(decoded, event["messages"], "transaction decoded bytes")
            for message in decoded:
                if message["system"] != 9 or message["component"] != 1:
                    raise ValueError("unexpected interval input identity")
                if message["type"] == "HEARTBEAT":
                    fields = message["fields"]
                    if fields["autopilot"] != 12 or fields["mavlink_version"] != 3 or not 0 <= fields["base_mode"] < 128:
                        raise ValueError("unarmed PX4 heartbeat required")
                if message["type"] not in ("COMMAND_ACK", "MESSAGE_INTERVAL"):
                    continue
                if pending is None or pending["returned"] is None or pending["pending_state"] is None:
                    raise ValueError("response without sent command and original pending deadline")
                bound = pending["pending_state"]
                _integer(receive["received_ns"], pending["returned"], bound["deadline_ns"] - 1, "response receive deadline")
                _integer(now, receive["received_ns"], bound["deadline_ns"] - 1, "response processing deadline")
                response = codec.interval_response(message)
                if response["kind"] == "ack":
                    if pending["ack"] is not None:
                        raise ValueError("duplicate command ACK")
                    _equal(response["command"], pending["command"], "ACK command")
                    _equal(response["result"], 0, "accepted ACK")
                    pending["ack"] = response
                    acknowledgments += 1
                else:
                    if pending["operation"] != "get" or pending["readback"] is not None:
                        raise ValueError("unsolicited or duplicate readback")
                    pending["readback"] = restorable_interval(response["interval_us"])
                    readbacks += 1
                pending["last_response_index"] = index
            receive = None
        elif kind == "interval_state":
            state = event["state"]
            for key, value in dict(
                primary_failure=None,
                terminal_failure=None,
                restore_failures=[],
                terminal_pending=None,
                cleanup_deadline_ns=None,
                candidate_us=10000,
                network_authorized=False,
                live_rate_qualified=False,
                fusion_qualified=False,
            ).items():
                _equal(state.get(key), value, "normal interval state " + key)
            history = state["events"]
            if type(history) is not list or len(history) > 96 or len(history) < len(previous_events):
                raise ValueError("invalid interval history")
            _equal(history[: len(previous_events)], previous_events, "interval event history prefix")
            previous_events = history
            bound = state["pending"]
            if bound is not None:
                _shape(bound, ("command", "sent_ns", "deadline_ns", "ack", "interval_us"), "pending command")
                if pending is None or pending["returned"] is None:
                    raise ValueError("pending state without raw send")
                _equal(bound["command"], pending["command"], "pending command identity")
                _integer(bound["sent_ns"], start, pending["attempt_ns"], "original command reservation time")
                _equal(bound["deadline_ns"], min(deadline, bound["sent_ns"] + 2_000_000_000), "original operation deadline")
                if pending["returned"] >= bound["deadline_ns"]:
                    raise ValueError("command return after original operation deadline")
                if pending["pending_state"] is None:
                    if pending["ack"] is not None or pending["readback"] is not None:
                        raise ValueError("pending deadline supplied after response")
                    pending["pending_state"] = copy.deepcopy(bound)
                    pending["phase"] = state["phase"]
                else:
                    for key in ("command", "sent_ns", "deadline_ns"):
                        _equal(bound[key], pending["pending_state"][key], "immutable pending " + key)
                    _equal(state["phase"], pending["phase"], "pending phase")
            elif pending is not None and not complete(pending):
                raise ValueError("state discarded incomplete raw transaction")
            states.append(row)
    if not complete(pending) or not states or not commands:
        raise ValueError("incomplete raw rate transaction")
    baseline = restorable_interval(commands[0]["readback"])
    if baseline == 10000:
        pattern = [("baseline", "get", None, baseline), ("final", "get", None, baseline)]
    else:
        pattern = [
            ("baseline", "get", None, baseline),
            ("apply", "set", 10000, None),
            ("apply_readback", "get", None, 10000),
            ("restore", "set", baseline, None),
            ("restore_readback", "get", None, baseline),
            ("final", "get", None, baseline),
        ]
    _equal(len(commands), len(pattern), "normal command count")
    for command, (phase, operation, value, readback) in zip(commands, pattern):
        for key, expected in dict(phase=phase, operation=operation, value=value, readback=readback).items():
            _equal(command[key], expected, "raw transaction " + key)
        if not complete(command):
            raise ValueError("missing raw transaction response")
    cold_finished = [r["index"] for r in records if r["source"] == "cold" and r["event"]["kind"] == "stream_finished"]
    maintenance = [r["index"] for r in records if r["source"] == "wire" and r["event"]["kind"] == "maintenance_bound"]
    replies = [r["index"] for r in records if r["source"] == "wire" and r["event"]["kind"] == "reply_prepared"]
    if len(cold_finished) != 1 or len(maintenance) != 1 or not replies:
        raise ValueError("missing unique body/handoff boundary")
    before_body = commands[0 if baseline == 10000 else 2]
    restore_or_final = commands[1 if baseline == 10000 else 3]
    if not before_body["last_response_index"] < replies[0] < cold_finished[0] < restore_or_final["attempt_index"]:
        raise ValueError("apply/body/restore causal order")
    terminal = states[-1]
    if not pending["last_response_index"] < terminal["index"] < maintenance[0]:
        raise ValueError("restoration did not precede maintenance handoff")
    for key, value in dict(
        phase="done",
        pending=None,
        baseline_us=baseline,
        final_us=baseline,
        mutation_attempted=baseline != 10000,
        restore_attempted=baseline != 10000,
        modeled_transaction_pass=True,
    ).items():
        _equal(terminal["event"]["state"][key], value, "terminal raw/state agreement " + key)
    return dict(
        interval_consistent=True,
        baseline_us=baseline,
        candidate_us=10000,
        command_count=len(commands),
        ack_count=acknowledgments,
        readback_count=readbacks,
        owner_transport_qualified=False,
        live_qualified=False,
        fusion_qualified=False,
    )
