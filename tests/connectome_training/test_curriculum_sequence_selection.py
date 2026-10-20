"""Real sequence files, without model construction or training."""
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import yaml

from flydrones.connectome_training.curriculum_config import load_curriculum_config
from flydrones.connectome_training.curriculum_session import (
    _full_components,
    _sequence_directories,
    _validate_profile_sequences,
)
from flydrones.connectome_training.dataset import TrainingSequence, write_sequence
from tests.connectome_training.test_dataset import frame, provenance, target


def sequence(path, seed=101, split='train'):
    return write_sequence(path, TrainingSequence(
        replace(provenance(), seed=seed, split=split,
                world_sha256=f'{seed:064x}'), [frame(50)], [target()],
    ))


@pytest.mark.parametrize('selection', ['same_path', 'parent_and_child', 'lexical_alias'])
def test_repeated_sequence_selection_refuses(tmp_path, selection):
    path = sequence(tmp_path / 'episodes' / 'one')
    if selection == 'same_path':
        paths = (path, path)
    elif selection == 'parent_and_child':
        paths = (path.parent, path)
    else:
        paths = (path, path.parent / 'one' / '..' / 'one')
    with pytest.raises(ValueError, match='duplicate sequence directory'):
        _sequence_directories(tuple(map(str, paths)))


def test_symlink_to_same_sequence_refuses(tmp_path):
    path = sequence(tmp_path / 'episode')
    alias = tmp_path / 'alias'
    try:
        alias.symlink_to(path, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f'directory symlink unavailable: {exc}')
    with pytest.raises(ValueError, match='duplicate sequence directory'):
        _sequence_directories((str(path), str(alias)))


def test_distinct_sequences_preserve_requested_and_sorted_order(tmp_path):
    sequence(tmp_path / 'episodes' / 'b', 102)
    sequence(tmp_path / 'episodes' / 'a', 101)
    first = sequence(tmp_path / 'first', 103)
    loaded = _sequence_directories((str(first), str(tmp_path / 'episodes')))
    assert [row.provenance.seed for row in loaded] == [103, 101, 102]


def test_identical_content_at_distinct_paths_is_not_identity_qualification(tmp_path):
    one = sequence(tmp_path / 'one')
    two = sequence(tmp_path / 'two')
    # Copied-content/job provenance is a separate corpus gate; path uniqueness
    # must not claim to prove independent physical rollouts.
    assert len(_sequence_directories((str(one), str(two)))) == 2


def test_missing_and_empty_source_are_still_refused(tmp_path):
    with pytest.raises(FileNotFoundError, match='sequence evidence path'):
        _sequence_directories((str(tmp_path / 'absent'),))
    with pytest.raises(ValueError, match='no sequence manifests'):
        _sequence_directories((str(tmp_path),))


def test_full_curriculum_requires_exactly_one_sequence_per_declared_seed(tmp_path):
    original = Path(__file__).resolve().parents[2] / 'configs' / 'connectome_curriculum_v1.yaml'
    config_data = yaml.safe_load(original.read_text(encoding='utf-8'))
    config_path = tmp_path / 'curriculum.yaml'
    train_dir, val_dir = tmp_path / 'train', tmp_path / 'val'
    train_dir.mkdir()
    val_dir.mkdir()
    first = sequence(train_dir / 'first', 1101)
    sequence(train_dir / 'duplicate', 1101)
    second = sequence(train_dir / 'second', 1102)
    sequence(val_dir / 'validation', 9101, split='val')
    config_data['stages'][0]['train_paths'] = [str(train_dir)]
    config_data['stages'][0]['validation_paths'] = [str(val_dir)]
    config_data['profiles']['full']['stages'] = ['stability']
    config_path.write_text(yaml.safe_dump(config_data), encoding='utf-8')
    selected = load_curriculum_config(config_path, 'full')
    missing = tmp_path / 'no-connectome.npz'
    with pytest.raises(ValueError, match='exactly one sequence'):
        _full_components(selected, missing, tmp_path / 'no-parameters')

    config_data['stages'][0]['train_paths'] = [str(first), str(second)]
    config_path.write_text(yaml.safe_dump(config_data), encoding='utf-8')
    selected = load_curriculum_config(config_path, 'full')
    with pytest.raises(FileNotFoundError, match='connectome source'):
        _full_components(selected, missing, tmp_path / 'no-parameters')


def test_full_curriculum_rejects_mixed_depth_feature_profiles_before_model_load():
    old = TrainingSequence(provenance(), [frame(50)], [target()])
    masked_frame = replace(frame(100), depth_valid=np.ones((4, 6), np.bool_))
    masked_target = replace(target(), horizon_valid=np.array([True, True]))
    masked = TrainingSequence(replace(provenance(), seed=102),
                              [masked_frame], [masked_target])
    with pytest.raises(ValueError, match="depth-mask-v3"):
        _validate_profile_sequences([old, masked], "depth-mask-v3")
    with pytest.raises(ValueError, match="legacy-v1"):
        _validate_profile_sequences([old, masked], "legacy-v1")
    _validate_profile_sequences([masked], "depth-mask-v3")
    _validate_profile_sequences([old], "legacy-v1")
