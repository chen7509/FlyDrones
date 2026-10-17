import gc
import weakref

import pytest
import torch
from test_learning_roles import config as _base_config
from test_learning_roles import inert_backends as _base_inert
from test_learning_roles import session

from flydrones.connectome_training import curriculum_session as sessions
from flydrones.connectome_training.dataset import write_sequence
from flydrones.connectome_training.trainer import evaluate_sequences, train_epoch

config = _base_config
inert_backends = _base_inert


def files(config, tmp_path):
    for index in range(3):
        write_sequence(tmp_path / str(index), sessions._synthetic_sequence(config.stages[0], "train", 1101 + index))
    return tmp_path


def test_actual_directory_catalog_retains_no_decoded_sequence(config, tmp_path, monkeypatch):
    folder = files(config, tmp_path)
    original = sessions.load_sequence
    refs = []

    def observed(path):
        value = original(path)
        refs.append(weakref.ref(value))
        return value

    monkeypatch.setattr(sessions, "load_sequence", observed)
    corpus = sessions._sequence_directories((str(folder),))
    gc.collect()
    assert len(refs) == 3
    assert not any(r() is not None for r in refs)
    assert not isinstance(corpus, list)


def test_rehearsal_is_reiterable_without_materializing_all_sequences(config, monkeypatch):
    current = session(config, "shared-dynamics-v1")
    refs = []

    class Corpus:
        frame_count = 24

        def __iter__(self):
            for i in range(3):
                value = sessions._synthetic_sequence(config.stages[0], "train", 1101 + i)
                refs.append(weakref.ref(value))
                yield value
                del value

    current.datasets[config.stages[0].id] = (Corpus(), current.datasets[config.stages[0].id][1])
    counts = []

    def train(model, sequences, *a, **k):
        count = 0
        for sequence in sequences:
            assert sum(r() is not None for r in refs) <= 1
            assert len(sequence.frames) == 8
            count += 1
            del sequence
        counts.append(count)
        return {"total": 1}

    monkeypatch.setattr(sessions, "train_epoch", train)
    result = current.train_batch(config.stages[0], 1101)
    assert counts == [3] * config.stages[0].epochs_per_batch
    assert result["environment_steps"] == 24 * config.stages[0].epochs_per_batch


def test_actual_trainer_releases_sequence_before_requesting_next(config):
    current = session(config, "shared-dynamics-v1")
    refs = []

    def stream():
        for index in range(2):
            gc.collect()
            assert not any(r() is not None for r in refs)
            value = sessions._synthetic_sequence(config.stages[0], "train", 1101 + index)
            refs.append(weakref.ref(value))
            yield value
            del value

    train_epoch(current.model, stream(), current.optimizer, current.truncate_steps)


@pytest.mark.parametrize("operation", ["digest", "features", "evaluate"])
def test_production_readers_release_before_next_decode(config, tmp_path, monkeypatch, operation):
    folder = files(config, tmp_path)
    original = sessions.load_sequence
    refs = []

    def observed(path):
        assert not any(r() is not None for r in refs)
        value = original(path)
        refs.append(weakref.ref(value))
        return value

    monkeypatch.setattr(sessions, "load_sequence", observed)
    corpus = sessions._sequence_directories((str(folder),))
    current = session(config, "shared-dynamics-v1")
    if operation == "digest":
        sessions._dataset_digest({"stage": (corpus, [])}, current.feature_profile)
    elif operation == "features":
        sessions._validate_profile_sequences(corpus, current.feature_profile)
    else:
        evaluate_sequences(current.model, corpus, current.truncate_steps)


@pytest.mark.parametrize("mutation", ["manifest", "samples", "member"])
def test_later_epoch_cannot_silently_change_file_corpus(config, tmp_path, mutation):
    folder = files(config, tmp_path)
    corpus = sessions._sequence_directories((str(folder),))
    assert len(list(corpus)) == 3
    if mutation == "member":
        write_sequence(folder / "new", sessions._synthetic_sequence(config.stages[0], "train", 9999))
    else:
        path = folder / "0" / ("manifest.json" if mutation == "manifest" else "samples.npz")
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="corpus"):
        next(iter(corpus))


def test_duplicate_paths_refuse(config, tmp_path):
    folder = files(config, tmp_path)
    with pytest.raises(ValueError, match="duplicate"):
        sessions._sequence_directories((str(folder), str(folder / "0")))


def test_actual_training_and_digest_match_eager_corpus_across_epochs(config, tmp_path, monkeypatch):
    folder = files(config, tmp_path)
    original = sessions._smoke_components

    def components(cfg, partition):
        c, p, d = original(cfg)
        d[cfg.stages[0].id] = (partition, d[cfg.stages[0].id][1])
        return c, p, d

    eager = [sessions.load_sequence(folder / str(i)) for i in range(3)]
    monkeypatch.setattr(sessions, "_smoke_components", lambda cfg: components(cfg, eager))
    a = session(config, "shared-dynamics-v1")
    corpus = sessions._sequence_directories((str(folder),))
    monkeypatch.setattr(sessions, "_smoke_components", lambda cfg: components(cfg, corpus))
    b = session(config, "shared-dynamics-v1")
    assert a.dataset_sha256 == b.dataset_sha256 and a.model_identity == b.model_identity
    ma = a.train_batch(config.stages[0], 1101)
    mb = b.train_batch(config.stages[0], 1101)
    for key in ["train_loss", "environment_steps", "updates"]:
        assert ma[key] == mb[key]
    assert all(torch.equal(x, y) for x, y in zip(a.model.parameters(), b.model.parameters()))
    assert a.evaluate(config.stages[0]) == b.evaluate(config.stages[0])
