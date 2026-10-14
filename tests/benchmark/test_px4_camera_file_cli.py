"""Actual file CLI failure lifecycle, no live source or backend."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2]/'tools/benchmark/produce_px4_camera_file.py'


def command(tmp_path):
    source = tmp_path/'source.ulg'
    source.write_bytes(b'constructed wrong-hash source')
    frames = tmp_path/'frames.json'
    frames.write_text(json.dumps({'frame_ns': [1_000_000_000]}))
    out = tmp_path/'produced'
    return [sys.executable, str(SCRIPT), '--ulog', str(source), '--ulog-sha256', 'a'*64,
            '--rig', str(tmp_path/'rig.json'), '--rig-sha256', 'b'*64,
            '--body-id', 'body0', '--camera-id', 'camera_link', '--frames-json', str(frames),
            '--frames-sha256', hashlib.sha256(frames.read_bytes()).hexdigest(), '--output', str(out)], out


def test_file_cli_retains_refusal_request_and_completion(tmp_path):
    argv, out = command(tmp_path)
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    request = json.loads((out/'request.json').read_text())
    completion = json.loads((out/'completion.json').read_text())
    assert request['argv'] == argv[1:]
    assert completion['status'] == 'failed'
    assert completion['error']
    assert completion['training_eligible'] is completion['flight_eligible'] is False


def test_file_cli_never_overwrites_an_existing_result(tmp_path):
    argv, out = command(tmp_path)
    subprocess.run(argv, capture_output=True, timeout=30)
    before = {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()}
    result = subprocess.run(argv, capture_output=True, timeout=30)
    assert result.returncode != 0
    assert {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()} == before
