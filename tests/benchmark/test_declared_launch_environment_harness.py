import json
import sys
from pathlib import Path

from tools.benchmark import declared_launch_environment_harness as harness


def test_harness_contract_and_command_are_absolute_and_conservative(tmp_path):
    contract = harness.harness_contract('/home/test')
    assert contract['schema'] == 'capture-execution-v2'
    assert contract['launch_environment']['PYTHONPATH'] is None
    assert contract['launch_environment']['SDF_PATH'] == ''
    assert contract['physical_environment_qualified'] is False
    python = Path(sys.executable)
    command = harness.child_command(tmp_path / 'capture', tmp_path / 'contract.json', python)
    assert command[0] == str(python)
    assert Path(command[1]).is_absolute()


def test_child_records_environment_and_terminal_result(tmp_path):
    contract = harness.harness_contract('/home/test')
    path = tmp_path / 'contract.json'
    path.write_text(json.dumps(contract))
    materialized = {key: value for key, value in contract['launch_environment'].items() if value is not None}
    raw = b''.join(key.encode() + b'=' + value.encode() + b'\0'
                   for key, value in materialized.items())
    output = tmp_path / 'capture'
    assert harness.run_child(output, path, reader=lambda: raw) == 0
    result = json.loads((output / 'result.json').read_text())
    assert result['status'] == 'capture_completed'
    assert result['environment_transport_verified'] is False
    assert result['physical_environment_qualified'] is False
    assert result['fusion_eligible'] is False
