from __future__ import annotations

import json

import pytest


def api():
    from tools.benchmark import audit_openvins_receiver_parity

    return audit_openvins_receiver_parity


@pytest.mark.parametrize("body", [
    '{"schema":"px4-receiver-parity-clock-v1","px4_minus_remote_us":0,"px4_minus_remote_us":1}',
    '{"schema":"px4-receiver-parity-clock-v1","px4_minus_remote_us":NaN}',
    '{"schema":"wrong","px4_minus_remote_us":0}',
    '{"schema":"px4-receiver-parity-clock-v1","px4_minus_remote_us":0,"extra":0}',
])
def test_clock_declaration_rejects_duplicate_nonfinite_unknown_fields(tmp_path, body):
    path = tmp_path / "clock.json"
    path.write_text(body)
    with pytest.raises(ValueError):
        api().read_clock(path)


def test_cli_retains_input_failure_and_refuses_overwrite(tmp_path):
    packet = tmp_path / "packet.json"
    ulog = tmp_path / "log.ulg"
    clock = tmp_path / "clock.json"
    out = tmp_path / "audit.json"
    packet.write_text("[]")
    ulog.write_bytes(b"ULog-placeholder")
    clock.write_text('{"schema":"invalid"}')
    args = ["--packets", str(packet), "--ulog", str(ulog), "--clock", str(clock), "--output", str(out)]
    assert api().main(args) == 2
    result = json.loads(out.read_text())
    assert result["field_parity_pass"] is False
    assert result["receiver_stage_qualified"] is False
    assert result["task5_authorized"] is False
    assert len(result["inputs"]) == 3
    before = out.read_bytes()
    with pytest.raises(FileExistsError):
        api().main(args)
    assert out.read_bytes() == before
