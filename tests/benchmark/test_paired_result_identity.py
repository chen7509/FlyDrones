"""Constructed development JSON only; no simulator, ULog qualification or flight."""

import json
import sys
from types import SimpleNamespace

import pytest

from flydrones.benchmark.provenance import seal_manifest, sha256_file
from flydrones.benchmark.runner import build_jobs
from tools.benchmark import report_results, run_batch


def fixture_campaign(tmp_path, monkeypatch):
    monkeypatch.setattr(run_batch, 'ROOT', tmp_path)
    monkeypatch.setattr(report_results, 'ROOT', tmp_path)
    formal = tmp_path / 'formal'
    formal.mkdir()
    freeze = seal_manifest({'phase': 'freeze', 'files': {}})
    freeze_path = tmp_path / 'freeze.json'
    freeze_path.write_text(json.dumps(freeze), encoding='utf-8')
    world_json = formal / 'world.json'
    world_sdf = formal / 'world.sdf'
    world_json.write_text(json.dumps({'seed': 1701}), encoding='utf-8')
    world_sdf.write_text('<sdf/>', encoding='utf-8')
    jobs = build_jobs([1701], ['fly_raw', 'ego'])
    jobs_path = formal / 'jobs.json'
    jobs_path.write_text(json.dumps(jobs), encoding='utf-8')
    worlds = [{'seed': 1701, 'world_json': 'formal/world.json',
               'world_sdf': 'formal/world.sdf', 'world_json_sha256': sha256_file(world_json),
               'world_sdf_sha256': sha256_file(world_sdf)}]
    seeds = seal_manifest({'generated_after_freeze_sha256': freeze['manifest_sha256'],
                           'worlds': worlds, 'jobs_sha256': sha256_file(jobs_path)})
    (formal / 'seed_manifest.json').write_text(json.dumps(seeds), encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['run_batch', '--freeze-manifest', str(freeze_path),
                                    '--formal-dir', str(formal)])

    def no_launch(*_args, **_kwargs):
        pytest.fail('result validation must precede any new launch')

    monkeypatch.setattr(run_batch.subprocess, 'run', no_launch)
    monkeypatch.setattr(run_batch.subprocess, 'check_call', no_launch)
    return formal, freeze_path, freeze['manifest_sha256']


def write_result(formal, freeze_sha, path_controller, **updates):
    result = {'seed': 1701, 'controller': path_controller, 'status': 'collision',
              'freeze_manifest_sha256': freeze_sha, 'odometry_source': 'gazebo_model_truth',
              'camera_pose_source': 'gazebo_model_truth'}
    result.update(updates)
    path = formal / 'episodes' / '1701' / path_controller / 'result.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result), encoding='utf-8')
    return path


@pytest.mark.parametrize('update', [
    {'seed': 1702}, {'seed': '1701'}, {'seed': True}, {'controller': 'fly_guided'},
    {'freeze_manifest_sha256': 'f' * 64}, {'status': 'running'}, {'status': True},
    {'status': 'unrecognized'},
])
def test_batch_refuses_mismatched_existing_result_without_edit_or_retry(tmp_path, monkeypatch, update):
    formal, freeze_path, sha = fixture_campaign(tmp_path, monkeypatch)
    write_result(formal, sha, 'fly_raw')
    bad = write_result(formal, sha, 'ego', **update)
    original = bad.read_bytes()
    with pytest.raises(ValueError, match='episode result'):
        run_batch.main()
    assert bad.read_bytes() == original
    assert not (formal / 'runner_logs').exists()
    assert not (formal / 'batch_state.json').exists()


def test_later_bad_existing_result_blocks_earlier_pending_launch(tmp_path, monkeypatch):
    formal, freeze_path, sha = fixture_campaign(tmp_path, monkeypatch)
    bad = write_result(formal, sha, 'ego', seed=1702)
    original = bad.read_bytes()
    with pytest.raises(ValueError, match='episode result'):
        run_batch.main()
    assert bad.read_bytes() == original
    assert not (formal / 'episodes' / '1701' / 'fly_raw').exists()
    assert not (formal / 'runner_logs').exists()


@pytest.mark.parametrize('status', [
    'success', 'timeout', 'collision', 'out_of_bounds', 'controller_error', 'infrastructure_error',
])
def test_matching_terminal_failure_or_success_is_consumed_not_retried(tmp_path, monkeypatch, status):
    formal, freeze_path, sha = fixture_campaign(tmp_path, monkeypatch)
    paths = [write_result(formal, sha, name, status=status) for name in ('fly_raw', 'ego')]
    originals = [path.read_bytes() for path in paths]
    assert run_batch.main() == 0
    assert [path.read_bytes() for path in paths] == originals
    assert not (formal / 'runner_logs').exists()


@pytest.mark.parametrize('update', [
    {'seed': 1702}, {'controller': 'ego'}, {'status': 'running'},
])
def test_report_refuses_cross_pair_or_nonterminal_before_ulog_processing(tmp_path, monkeypatch, update):
    formal, freeze_path, sha = fixture_campaign(tmp_path, monkeypatch)
    bad = write_result(formal, sha, 'fly_raw', **update)
    original = bad.read_bytes()

    def should_not_reach_ulog(*_args, **_kwargs):
        pytest.fail('pair identity must be checked before independent ULog gate')

    monkeypatch.setattr(report_results, 'verify_episode_ulog_evidence', should_not_reach_ulog)
    with pytest.raises(ValueError, match='episode result'):
        report_results.load_results(formal, freeze_path)
    assert bad.read_bytes() == original


def test_all_existing_terminal_results_publish_complete_resume_ledger(tmp_path, monkeypatch):
    formal, freeze_path, sha = fixture_campaign(tmp_path, monkeypatch)
    paths = [write_result(formal, sha, name) for name in ('fly_raw', 'ego')]
    original = [path.read_bytes() for path in paths]
    assert run_batch.main() == 0
    state = json.loads((formal / 'batch_state.json').read_text(encoding='utf-8'))
    assert state['completed'] == state['total'] == 2
    assert state['freeze_manifest_sha256'] == sha
    assert [record['job']['controller'] for record in state['records']] == ['fly_raw', 'ego']
    assert all(record['status'] == 'collision' and 'returncode' not in record for record in state['records'])
    assert [path.read_bytes() for path in paths] == original


def test_new_failure_then_existing_failure_both_reach_final_resume_ledger(tmp_path, monkeypatch):
    formal, freeze_path, sha = fixture_campaign(tmp_path, monkeypatch)
    old = write_result(formal, sha, 'ego')
    original = old.read_bytes()
    launches = []

    def constructed_result_producer(argv, **_kwargs):
        # Substitute only the external backend boundary; actual runner/JSON ledger execute.
        launches.append(argv)
        write_result(formal, sha, 'fly_raw', status='controller_error')
        return SimpleNamespace(returncode=2)

    monkeypatch.setattr(run_batch.subprocess, 'run', constructed_result_producer)
    assert run_batch.main() == 0
    assert len(launches) == 1
    state = json.loads((formal / 'batch_state.json').read_text(encoding='utf-8'))
    assert state['completed'] == state['total'] == 2
    assert [record['status'] for record in state['records']] == ['controller_error', 'collision']
    assert state['records'][0]['returncode'] == 2
    assert 'returncode' not in state['records'][1]
    assert old.read_bytes() == original
