"""Real file-only CLI failures preserve partial inputs and never reuse output."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2]/'tools/benchmark/export_camera_px4_imu_dataset.py'


def test_failed_input_binding_keeps_request_and_completion(tmp_path):
    source = tmp_path/'source.ulg'
    source.write_bytes(b'not a ULog')
    output = tmp_path/'output'
    command = [sys.executable, str(SCRIPT), '--ulog', str(source), '--ulog-sha256', '0'*64,
               '--rgb-manifest', str(tmp_path/'missing.json'), '--rgb-manifest-sha256', '1'*64,
               '--rig', str(tmp_path/'missing-rig.json'), '--rig-sha256', '2'*64,
               '--body-id', 'body0', '--camera-id', 'camera_link', '--output', str(output)]
    result = subprocess.run(command, capture_output=True)
    assert result.returncode == 1
    assert (output/'request.json').exists()
    completion = json.loads((output/'completion.json').read_text())
    assert completion['status'] == 'failed' and 'SHA mismatch' in completion['error']
    assert not completion['training_eligible']
    assert not (output/'imu0/data.csv').exists()
    before = {p.name: p.read_bytes() for p in output.iterdir() if p.is_file()}
    second = subprocess.run(command, capture_output=True)
    assert second.returncode != 0
    assert before == {p.name: p.read_bytes() for p in output.iterdir() if p.is_file()}
