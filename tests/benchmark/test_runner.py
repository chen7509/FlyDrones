import json

import pytest

from flydrones.benchmark.provenance import freeze_files, seal_manifest
from flydrones.benchmark.runner import (
    build_jobs,
    pending_jobs,
    require_frozen_manifest,
    snapshot_episode_inputs,
    verify_freeze_manifest,
)
from tools.benchmark.run_batch import prepare_job_directories


def test_batch_runner_keeps_its_logs_outside_fresh_episode(tmp_path):
    episode = tmp_path / 'formal' / 'episodes' / '1701' / 'fly_raw'
    logs = tmp_path / 'formal' / 'runner_logs' / '1701' / 'fly_raw'
    prepare_job_directories(episode, logs)
    assert logs.is_dir() and not episode.exists()
    episode.mkdir(parents=True)
    (episode / 'started.json').write_text('{"partial": true}')
    with pytest.raises(FileExistsError, match='partial episode'):
        prepare_job_directories(episode, logs)


CONTROLLERS = ['fly_raw', 'fly_guided', 'ego']


def test_formal_manifest_has_twenty_worlds_times_three_controllers():
    jobs = build_jobs(list(range(20)), CONTROLLERS)
    assert len(jobs) == 60
    assert len({(job['seed'], job['controller']) for job in jobs}) == 60
    for seed in range(20):
        assert {job['controller'] for job in jobs if job['seed'] == seed} == set(CONTROLLERS)


def test_failed_run_is_not_silently_retried():
    jobs = build_jobs([1701], CONTROLLERS)
    records = [{'seed': 1701, 'controller': 'fly_raw', 'status': 'collision'}]
    todo = pending_jobs(jobs, records)
    assert len(todo) == 2
    assert all(job['controller'] != 'fly_raw' for job in todo)


def test_controller_order_rotates_without_changing_job_identity():
    jobs = build_jobs([10, 11, 12], CONTROLLERS)
    assert [job['controller'] for job in jobs[:3]] == CONTROLLERS
    assert [job['controller'] for job in jobs[3:6]] == ['fly_guided', 'ego', 'fly_raw']
    assert [job['controller'] for job in jobs[6:9]] == ['ego', 'fly_raw', 'fly_guided']


def test_evaluation_requires_matching_frozen_manifest(tmp_path):
    frozen = tmp_path / 'frozen.json'
    with pytest.raises(ValueError, match='freeze'):
        require_frozen_manifest(frozen, 'expected')
    frozen.write_text(json.dumps({'phase': 'freeze', 'manifest_sha256': 'other'}))
    with pytest.raises(ValueError, match='mismatch'):
        require_frozen_manifest(frozen, 'expected')
    frozen.write_text(json.dumps({'phase': 'freeze', 'manifest_sha256': 'expected'}))
    assert require_frozen_manifest(frozen, 'expected')['phase'] == 'freeze'


def test_duplicate_terminal_record_is_rejected():
    jobs = build_jobs([1701], CONTROLLERS)
    records = [
        {'seed': 1701, 'controller': 'ego', 'status': 'timeout'},
        {'seed': 1701, 'controller': 'ego', 'status': 'success'},
    ]
    with pytest.raises(ValueError, match='duplicate'):
        pending_jobs(jobs, records)


def test_each_episode_gets_immutable_world_copies(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'world.json').write_text('{"seed":1701}', encoding='utf-8')
    (source / 'world.sdf').write_text('<sdf/>', encoding='utf-8')
    output = tmp_path / 'episode'
    world_json, world_sdf = snapshot_episode_inputs(
        source / 'world.json', source / 'world.sdf', output,
    )
    world_sdf.write_text('<sdf>mutated copy</sdf>', encoding='utf-8')
    assert (source / 'world.sdf').read_text(encoding='utf-8') == '<sdf/>'
    assert world_json.read_text(encoding='utf-8') == '{"seed":1701}'
    manifest = json.loads((output / 'input_manifest.json').read_text(encoding='utf-8'))
    assert manifest['world_sdf_sha256'] != ''


def test_formal_run_verifies_manifest_seal_and_frozen_files(tmp_path):
    frozen_input = tmp_path / 'controller.py'
    frozen_input.write_text('fixed')
    manifest = seal_manifest({
        'phase': 'freeze',
        'files': freeze_files([frozen_input], tmp_path),
    })
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest))
    assert verify_freeze_manifest(path, tmp_path)['manifest_sha256'] == manifest['manifest_sha256']
    frozen_input.write_text('tuned after freeze')
    with pytest.raises(ValueError, match='changed'):
        verify_freeze_manifest(path, tmp_path)
