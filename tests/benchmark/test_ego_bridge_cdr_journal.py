"""Fail-closed opt-in bridge journal; fake serializers do not prove ROS CDR parity."""

import base64
import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from tools.benchmark.ego_bridge_cdr_journal import BridgeCDRJournal


def journal(stream=None, serializer=lambda message: message, clock=None):
    ticks = iter(range(100, 10000))
    return BridgeCDRJournal(
        stream or io.StringIO(), run_id="development-run-1", session_id="session-1",
        serializer=serializer, pid=37, clock=clock or (lambda: next(ticks)),
    )


def rows(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_publish_uses_identical_serialized_bytes_and_intent_precedes_raw_call():
    stream = io.StringIO()
    writer = journal(stream)
    writer.start_reset(17)
    calls = []

    def publish(payload):
        assert payload == b"\x00\x01cdr-payload"
        assert rows(stream)[-1]["phase"] == "publish_intent"
        calls.append(payload)

    writer.publish("depth", b"\x00\x01cdr-payload", 123, publish)
    events = rows(stream)
    assert [event["phase"] for event in events] == [
        "session_open", "reset", "publish_intent", "publish_returned"]
    assert [event["sequence"] for event in events] == [1, 2, 3, 4]
    assert events[2]["message_sequence"] == events[3]["message_sequence"] == 1
    assert events[2]["message_sha256"] == hashlib.sha256(calls[0]).hexdigest()
    assert base64.b64decode(events[2]["message_cdr_b64"], validate=True) == calls[0]
    assert events[3]["message_cdr_b64"] is None
    assert events[2]["message_bytes"] == len(calls[0])
    assert events[2]["sample_ns"] == 123
    assert events[2]["source"] == "unattested_socket"
    assert events[2]["truth_used"] == "unknown"
    assert events[2]["event_steady_ns"] <= events[3]["event_steady_ns"]
    assert writer.failed is False


def test_raw_command_bytes_are_recorded_before_decoder_and_reference_mutation():
    stream = io.StringIO()
    writer = journal(stream)
    writer.start_reset(3)
    changed = []
    payload = b"\x00\x01raw-command"
    message_sequence = writer.receive_command(payload)

    def decode(raw):
        assert raw == payload
        assert rows(stream)[-1]["phase"] == "command_received"
        assert changed == []
        return {"stamp_ns": 992, "trajectory_id": 7, "ready": True}

    parsed = decode(payload)
    writer.command_decoded(message_sequence, **parsed)
    changed.append(parsed)
    assert rows(stream)[-2]["message_sha256"] == hashlib.sha256(payload).hexdigest()
    assert base64.b64decode(rows(stream)[-2]["message_cdr_b64"], validate=True) == payload
    assert rows(stream)[-1]["phase"] == "command_decoded"
    assert rows(stream)[-1]["sample_ns"] == 992
    assert rows(stream)[-1]["trajectory_id"] == 7


def test_publish_failure_records_incomplete_intent_and_latches_session():
    stream = io.StringIO()
    writer = journal(stream)
    writer.start_reset(0)

    def fail(_payload):
        raise RuntimeError("publisher failed")

    with pytest.raises(RuntimeError, match="publisher failed"):
        writer.publish("odometry", b"bytes", 123, fail)
    assert [event["phase"] for event in rows(stream)][-2:] == [
        "publish_intent", "publish_failed"]
    assert writer.failed is True
    with pytest.raises(RuntimeError, match="journal failed"):
        writer.publish("depth", b"later", 124, lambda _: None)


def test_serialization_error_or_nonbytes_never_calls_ros_publisher():
    stream = io.StringIO()
    writer = journal(stream, serializer=lambda _: (_ for _ in ()).throw(ValueError("CDR")))
    writer.start_reset(0)
    published = []
    with pytest.raises(ValueError, match="CDR"):
        writer.publish("depth", object(), 123, published.append)
    assert published == []
    assert writer.failed is True
    writer = journal(io.StringIO(), serializer=lambda _: "not bytes")
    writer.start_reset(0)
    with pytest.raises(ValueError, match="serialized bytes"):
        writer.publish("depth", object(), 123, published.append)
    assert published == []


class BrokenStream(io.StringIO):
    def __init__(self, *, fail_at=0, fail_flush=False):
        super().__init__()
        self.calls = 0
        self.fail_at = fail_at
        self.fail_flush = fail_flush

    def write(self, value):
        self.calls += 1
        if self.calls == self.fail_at:
            raise OSError("journal write refused")
        return super().write(value)

    def flush(self):
        if self.fail_flush:
            raise OSError("journal flush refused")
        return super().flush()


def test_journal_write_or_flush_failure_prevents_ros_publication():
    published = []
    stream = BrokenStream(fail_at=3)
    writer = journal(stream)
    writer.start_reset(0)
    with pytest.raises(OSError, match="write refused"):
        writer.publish("depth", b"bytes", 123, published.append)
    assert published == []
    assert writer.failed is True
    stream = BrokenStream()
    writer = journal(stream)
    writer.start_reset(0)
    stream.fail_flush = True
    with pytest.raises(OSError, match="flush refused"):
        writer.publish("depth", b"bytes", 123, published.append)
    assert published == []
    assert writer.failed is True


def test_return_record_failure_preserves_irreversible_publish_and_latches():
    stream = BrokenStream(fail_at=4)
    writer = journal(stream)
    writer.start_reset(0)
    published = []
    with pytest.raises(OSError, match="write refused"):
        writer.publish("depth", b"bytes", 123, published.append)
    assert published == [b"bytes"]
    assert writer.failed is True
    assert [row["phase"] for row in rows(stream)][-1] == "publish_intent"
    with pytest.raises(RuntimeError, match="journal failed"):
        writer.publish("depth", b"again", 124, published.append)
    assert published == [b"bytes"]


def test_second_reset_and_command_decode_error_lock_the_session():
    writer = journal()
    writer.start_reset(0)
    with pytest.raises(ValueError, match="reset"):
        writer.start_reset(1)
    assert writer.failed is True
    writer = journal()
    writer.start_reset(0)
    writer.receive_command(b"broken")
    writer.fail("command_decode_failed")
    with pytest.raises(RuntimeError, match="journal failed"):
        writer.receive_command(b"again")


def test_concurrent_writers_have_one_sequence_and_no_interleaved_intents():
    stream = io.StringIO()
    writer = journal(stream)
    writer.start_reset(0)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda index: writer.publish("odometry", bytes([index]),
                                                   index, lambda _: None), range(20)))
    events = rows(stream)
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert [event["phase"] for event in events[2::2]] == ["publish_intent"] * 20
    assert [event["phase"] for event in events[3::2]] == ["publish_returned"] * 20


def test_open_new_refuses_existing_journal_without_modifying_it(tmp_path):
    path = tmp_path / "bridge.jsonl"
    path.write_text("historical evidence", encoding="utf-8")
    with pytest.raises(FileExistsError):
        BridgeCDRJournal.open_new(path, run_id="run", session_id="session",
                                  serializer=lambda value: value)
    assert path.read_text(encoding="utf-8") == "historical evidence"
