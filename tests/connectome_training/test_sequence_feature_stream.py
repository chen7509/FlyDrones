import io
import json
import math
import struct
import weakref
import zipfile
import zlib
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace

import numpy as np
import pytest
import torch
from test_learning_roles import config as config
from test_learning_roles import inert_backends as inert_backends

from flydrones.connectome_training import curriculum_session as sessions
from flydrones.connectome_training.dataset import load_sequence, write_sequence
from flydrones.connectome_training.features import FEATURE_NAMES, MASKED_FEATURE_NAMES, sequence_tensors
from flydrones.connectome_training.model import ConnectomeConstrainedCore
from flydrones.connectome_training.trainer import TrainingEffort, evaluate_sequences, train_epoch


def sequence_file(tmp_path, config, version=1, *, split="train", seed=1101, name="sequence"):
    value = sessions._synthetic_sequence(config.stages[0], split, seed)
    if version >= 2:
        for target in value.targets:
            target.horizon_valid = np.ones(len(target.horizon_enu), dtype=bool)
    if version == 3:
        for frame in value.frames:
            frame.depth_m[0, 0] = np.nan
            frame.depth_valid = np.isfinite(frame.depth_m)
    return write_sequence(tmp_path / name, value)


def streamed(path, profile="legacy-v1"):
    from flydrones.connectome_training.feature_sequence import load_feature_sequence

    return load_feature_sequence(path, profile=profile)


@pytest.mark.parametrize("version", [1, 2, 3])
def test_canonical_tensor_and_digest_bytes_equal_eager(tmp_path, config, version):
    path = sequence_file(tmp_path, config, version)
    profile = "depth-mask-v3" if version == 3 else "legacy-v1"
    eager, reduced = load_sequence(path), streamed(path, profile)
    assert reduced.sample_count == len(eager.frames)
    assert reduced.provenance == eager.provenance
    assert not hasattr(reduced, "frames")
    for actual, expected in zip(
        sequence_tensors(reduced, profile=profile), sequence_tensors(eager, profile=profile), strict=True
    ):
        assert actual.dtype == expected.dtype == torch.float32
        assert torch.equal(actual, expected)
    assert sessions._dataset_digest({"s": ([eager], [eager])}, profile) == sessions._dataset_digest(
        {"s": ([reduced], [reduced])}, profile
    )


@pytest.mark.parametrize("version", [1, 3])
def test_actual_full_components_does_not_call_eager_image_loader(tmp_path, config, tiny_artifacts, monkeypatch, version):
    train = sequence_file(tmp_path, config, version)
    val = sequence_file(tmp_path, config, version, split="val", seed=2101, name="validation")
    stage = replace(
        config.stages[0], train_paths=(str(train),), validation_paths=(str(val),), train_seeds=(1101,), validation_seeds=(2101,)
    )
    names = MASKED_FEATURE_NAMES if version == 3 else FEATURE_NAMES
    source, folder, _, parameters = tiny_artifacts(feature_names=names)
    # Explicit tiny fixture exercises production routing, never full-MaleCNS qualification.
    parameters.identity = replace(parameters.identity, label="full-male-cns")
    monkeypatch.setattr(sessions, "load_parameter_set", lambda _: parameters)
    calls = []
    original = sessions.load_sequence
    monkeypatch.setattr(sessions, "load_sequence", lambda path: (calls.append(path), original(path))[1])
    _, _, datasets = sessions._full_components(replace(config, stages=(stage,)), source, folder)
    assert calls == []
    partition = datasets[stage.id][0]
    assert partition.frame_count == 8
    assert next(iter(partition)).sample_count == 8
    full_route = replace(config, stages=(stage,), profile=replace(config.profile, data_mode="file-evidence"))
    current = sessions.ConnectomeCurriculumSession(full_route, device="cpu", connectome_path=source, parameters_path=folder)
    result = current.train_batch(stage, 1101)
    assert result["environment_steps"] == 16
    assert current.training_effort["counts"]["optimizer_step_calls_returned"] == 2
    assert calls == []


def rewrite(path, mutate):
    with zipfile.ZipFile(path / "samples.npz") as archive:
        entries = [(info.filename, archive.read(info)) for info in archive.infolist()]
    entries = mutate(entries)
    with zipfile.ZipFile(path / "samples.npz", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)
    manifest = json.loads((path / "manifest.json").read_bytes())
    manifest["samples_sha256"] = sha256((path / "samples.npz").read_bytes()).hexdigest()
    (path / "manifest.json").write_text(json.dumps(manifest))


def array_payload(value):
    output = io.BytesIO()
    np.save(output, value, allow_pickle=False)
    return output.getvalue()


def test_reader_never_uses_whole_member_numpy_loader(tmp_path, config, monkeypatch):
    path = sequence_file(tmp_path, config)
    monkeypatch.setattr(np.lib.npyio.NpzFile, "__getitem__", lambda *args: pytest.fail("eager member decode"))
    assert streamed(path).sample_count == 8


@pytest.mark.parametrize("version", [1, 3])
@pytest.mark.parametrize("topology", ["coo_reference", "csr_compact_v1"])
def test_actual_raw_gradients_adam_metrics_and_effort_equal(tmp_path, config, tiny_artifacts, monkeypatch, version, topology):
    profile = "depth-mask-v3" if version == 3 else "legacy-v1"
    names = MASKED_FEATURE_NAMES if version == 3 else FEATURE_NAMES
    paths = [sequence_file(tmp_path, config, version, name=str(i), seed=1101 + i) for i in range(2)]
    eager = [load_sequence(path) for path in paths]
    corpus = sessions._sequence_directories(tuple(str(p) for p in paths), profile=profile)
    _, _, connectome, parameters = tiny_artifacts(feature_names=names)
    a = ConnectomeConstrainedCore(connectome, parameters, topology_format=topology, dynamics_format="frozen-drive-exponential-v1")
    b = ConnectomeConstrainedCore(connectome, parameters, topology_format=topology, dynamics_format="frozen-drive-exponential-v1")
    oa, ob = torch.optim.Adam(a.parameters(), lr=0.003), torch.optim.Adam(b.parameters(), lr=0.003)
    ea, eb = TrainingEffort(), TrainingEffort()
    gradients = []
    original = torch.nn.utils.clip_grad_norm_

    def capture(parameters, *args, **kwargs):
        parameters = list(parameters)
        gradients.append([None if p.grad is None else p.grad.clone() for p in parameters])
        return original(parameters, *args, **kwargs)

    monkeypatch.setattr(torch.nn.utils, "clip_grad_norm_", capture)
    for _ in range(2):
        assert train_epoch(a, eager, oa, 3, effort=ea) == train_epoch(b, corpus, ob, 3, effort=eb)
        assert evaluate_sequences(a, eager, 3) == evaluate_sequences(b, corpus, 3)
        for left, right in zip(gradients[-4:-2], gradients[-2:], strict=True):
            assert all((x is None and y is None) or torch.equal(x, y) for x, y in zip(left, right, strict=True))
        assert all(torch.equal(x, y) for x, y in zip(a.parameters(), b.parameters(), strict=True))
    assert ea.snapshot() == eb.snapshot()
    assert ea.optimizer_step_calls_returned == 4 and ea.frames_at_returned_optimizer_steps == 32
    assert any(p.grad is not None and torch.count_nonzero(p.grad) for p in a.parameters())


def test_each_image_row_is_released_before_next_frame(tmp_path, config, monkeypatch):
    from flydrones.connectome_training import feature_sequence as reader
    from flydrones.connectome_training import features

    path = sequence_file(tmp_path, config)
    refs, reads = [], []
    original_features, original_read = features.frame_features, reader._read_exact

    def observed(frame, **kwargs):
        assert not any(ref() is not None for ref in refs)
        refs.extend([weakref.ref(frame), weakref.ref(frame.rgb), weakref.ref(frame.depth_m)])
        return original_features(frame, **kwargs)

    def bounded(stream, count):
        reads.append((stream.name, count))
        return original_read(stream, count)

    monkeypatch.setattr(features, "frame_features", observed)
    monkeypatch.setattr(reader, "_read_exact", bounded)
    value = streamed(path)
    assert value.sample_count == 8 and not any(ref() is not None for ref in refs)
    rgb_reads = [n for name, n in reads if name == "rgb.npy"]
    depth_reads = [n for name, n in reads if name == "depth_m.npy"]
    # Two preflight header reads precede the eight image rows.
    assert len(rgb_reads) == len(depth_reads) == 10
    assert rgb_reads[-8:] == [6 * 9 * 3] * 8 and max(rgb_reads) == 6 * 9 * 3
    assert depth_reads[-8:] == [6 * 9 * 4] * 8 and max(depth_reads) == 6 * 9 * 4


@pytest.mark.parametrize(
    "fault", ["duplicate", "unexpected", "float64", "fortran", "shape", "count", "truncated", "trailing", "object", "npy3"]
)
def test_noncanonical_members_refuse(tmp_path, config, fault):
    path = sequence_file(tmp_path, config)

    def mutate(entries):
        if fault == "duplicate":
            return entries + [entries[0]]
        if fault == "unexpected":
            return entries + [("extra.npy", array_payload(np.ones(8)))]
        result = []
        for name, payload in entries:
            if name == "depth_m.npy":
                value = np.load(io.BytesIO(payload), allow_pickle=False)
                if fault == "float64":
                    payload = array_payload(value.astype(np.float64))
                elif fault == "fortran":
                    payload = array_payload(np.asfortranarray(value))
                elif fault == "shape":
                    payload = array_payload(value.reshape(8, -1))
                elif fault == "count":
                    payload = array_payload(value[:-1])
                elif fault == "truncated":
                    payload = payload[:-1]
                elif fault == "trailing":
                    payload += b"x"
                elif fault == "object":
                    out = io.BytesIO()
                    np.save(out, np.array([object()], dtype=object))
                    payload = out.getvalue()
                else:
                    payload = payload[:6] + bytes([3, 0]) + payload[8:]
            result.append((name, payload))
        return result

    if fault == "duplicate":
        with pytest.warns(UserWarning, match="Duplicate name"):
            rewrite(path, mutate)
    else:
        rewrite(path, mutate)
    with pytest.raises(ValueError):
        streamed(path)


@pytest.mark.parametrize(
    "member,change",
    [
        ("sim_ns.npy", lambda a: np.concatenate((a[:-1], a[-2:-1]))),
        ("frame_ns.npy", lambda a: np.concatenate((a[:-1], a[-1:] + 1))),
        ("teacher_horizon_enu.npy", lambda a: np.concatenate((a[:-1], np.full_like(a[-1:], np.nan)))),
        ("teacher_yaw_rate.npy", lambda a: np.concatenate((a[:-1], np.full_like(a[-1:], np.inf)))),
    ],
)
def test_invalid_last_row_never_reaches_optimizer(tmp_path, config, monkeypatch, member, change):
    from test_learning_roles import session

    path = sequence_file(tmp_path, config)
    rewrite(
        path,
        lambda entries: [
            (name, array_payload(change(np.load(io.BytesIO(payload)))) if name == member else payload)
            for name, payload in entries
        ],
    )
    current = session(config, "shared-dynamics-v1")
    before = [p.detach().clone() for p in current.model.parameters()]
    monkeypatch.setattr(current.optimizer, "step", lambda: pytest.fail("optimizer reached damaged sequence"))

    # No sequence is yielded until the final row and stream integrity are checked.
    def partition():
        yield streamed(path)

    effort = TrainingEffort()
    with pytest.raises(ValueError):
        train_epoch(current.model, partition(), current.optimizer, 3, effort=effort)
    assert effort.epoch_calls_started == 1 and effort.sequence_calls_started == 0
    assert all(torch.equal(a, b) for a, b in zip(before, current.model.parameters(), strict=True))


@pytest.mark.parametrize("operation", ["success", "badrow", "badheader"])
def test_all_member_streams_close(tmp_path, config, monkeypatch, operation):
    path = sequence_file(tmp_path, config)
    if operation != "success":
        name = "depth_m.npy"
        value = np.ones((8, 6, 9), np.float64 if operation == "badheader" else np.float32)
        if operation == "badrow":
            value[-1, 0, 0] = np.nan
        rewrite(path, lambda entries: [(n, array_payload(value) if n == name else p) for n, p in entries])
    opened = []
    original = zipfile.ZipFile.open

    def tracked(*args, **kwargs):
        stream = original(*args, **kwargs)
        opened.append(stream)
        return stream

    monkeypatch.setattr(zipfile.ZipFile, "open", tracked)
    if operation == "success":
        streamed(path)
    else:
        with pytest.raises(ValueError):
            streamed(path)
    assert opened and all(stream.closed for stream in opened)


@pytest.mark.parametrize("kind", ["manifest", "samples", "hash"])
def test_decode_drift_or_wrong_hash_refuses(tmp_path, config, monkeypatch, kind):
    from flydrones.connectome_training import feature_sequence as reader

    path = sequence_file(tmp_path, config)
    if kind == "hash":
        (path / "samples.npz").write_bytes((path / "samples.npz").read_bytes() + b"x")
    else:
        original = reader.sequence_tensors
        changed = False

        def drift(*args, **kwargs):
            nonlocal changed
            if not changed:
                changed = True
                file = path / ("manifest.json" if kind == "manifest" else "samples.npz")
                file.write_bytes(file.read_bytes() + b" ")
            return original(*args, **kwargs)

        monkeypatch.setattr(reader, "sequence_tensors", drift)
    with pytest.raises(ValueError, match="hash|changed"):
        streamed(path)


@pytest.mark.parametrize("profile", ["depth-mask-v3", "unknown"])
def test_wrong_profile_refuses(tmp_path, config, profile):
    path = sequence_file(tmp_path, config)
    with pytest.raises(ValueError, match="profile"):
        streamed(path, profile)
    reduced = streamed(path)
    with pytest.raises(ValueError, match="profile"):
        sequence_tensors(reduced, profile=profile)


def test_crc_corruption_refuses(tmp_path, config):
    import struct

    path = sequence_file(tmp_path, config)
    payload = bytearray((path / "samples.npz").read_bytes())
    # Change one central-directory CRC, keeping the declared content hash honest.
    offset = payload.index(b"PK\x01\x02")
    crc = struct.unpack_from("<I", payload, offset + 16)[0]
    struct.pack_into("<I", payload, offset + 16, crc ^ 1)
    (path / "samples.npz").write_bytes(payload)
    manifest = json.loads((path / "manifest.json").read_bytes())
    manifest["samples_sha256"] = sha256(payload).hexdigest()
    (path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(zipfile.BadZipFile, match="CRC"):
        streamed(path)


@pytest.mark.parametrize("value", [0, True, 8.0, 9])
def test_manifest_sample_count_refuses(tmp_path, config, value):
    path = sequence_file(tmp_path, config)
    manifest = json.loads((path / "manifest.json").read_bytes())
    manifest["samples"] = value
    (path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        streamed(path)


def test_npy2_headers_follow_same_rows(tmp_path, config):
    path = sequence_file(tmp_path, config)

    def convert(entries):
        result = []
        for name, payload in entries:
            array = np.load(io.BytesIO(payload), allow_pickle=False)
            out = io.BytesIO()
            np.lib.format.write_array(out, array, version=(2, 0), allow_pickle=False)
            result.append((name, out.getvalue()))
        return result

    rewrite(path, convert)
    assert all(
        torch.equal(x, y) for x, y in zip(sequence_tensors(streamed(path)), sequence_tensors(load_sequence(path)), strict=True)
    )


@pytest.mark.parametrize("fault", ["dtype", "shape", "nan", "labels", "empty"])
def test_prepared_tensors_are_checked(tmp_path, config, fault):
    value = streamed(sequence_file(tmp_path, config))
    if fault == "dtype":
        value = replace(value, features=value.features.double())
    elif fault == "shape":
        value = replace(value, features=value.features.squeeze(0))
    elif fault == "nan":
        value.features[0, -1, 0] = float("nan")
    elif fault == "labels":
        value = replace(value, commands=value.commands[:, :-1])
    else:
        value = replace(value, features=value.features[:, :0], commands=value.commands[:, :0], clearance=value.clearance[:, :0])
    with pytest.raises(ValueError):
        sequence_tensors(value)


def refresh_hash(path):
    manifest = json.loads((path / "manifest.json").read_bytes())
    manifest["samples_sha256"] = sha256((path / "samples.npz").read_bytes()).hexdigest()
    (path / "manifest.json").write_text(json.dumps(manifest))


def test_review_original_zip_names_refuse_before_output(tmp_path, config, monkeypatch):
    path = sequence_file(tmp_path, config)
    rewrite(path, lambda entries: [("rgb.npy!suffix" if n == "rgb.npy" else n, b) for n, b in entries])
    payload = (path / "samples.npz").read_bytes()
    assert payload.count(b"rgb.npy!suffix") == 2
    (path / "samples.npz").write_bytes(payload.replace(b"rgb.npy!suffix", b"rgb.npy\0suffix"))
    refresh_hash(path)
    allocated = []
    original = np.empty
    monkeypatch.setattr(np, "empty", lambda *a, **k: (allocated.append(a), original(*a, **k))[1])
    with pytest.raises(ValueError, match="name|membership"):
        streamed(path)
    assert not allocated


def compression_fault_archive(path, fault):
    with zipfile.ZipFile(path / "samples.npz") as archive:
        entries = [(i.filename, archive.read(i)) for i in archive.infolist()]
    local, central = bytearray(), bytearray()
    for name, original in entries:
        content = original
        if name == "depth_m.npy" and fault == "hidden-output":
            content += b"HIDDEN-OUTPUT"
        encoder = zlib.compressobj(wbits=-15)
        mode = zlib.Z_SYNC_FLUSH if name == "depth_m.npy" and fault == "unterminated" else zlib.Z_FINISH
        compressed = encoder.compress(content) + encoder.flush(mode)
        if name == "depth_m.npy" and fault == "compressed-tail":
            compressed += b"HIDDEN-COMPRESSED-TAIL"
        encoded = name.encode()
        checksum, offset = zlib.crc32(original), len(local)
        local += struct.pack(
            "<IHHHHHIIIHH", 0x04034B50, 20, 0, 8, 0, 0, checksum, len(compressed), len(original), len(encoded), 0
        )
        local += encoded + compressed
        central += struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50,
            20,
            20,
            0,
            8,
            0,
            0,
            checksum,
            len(compressed),
            len(original),
            len(encoded),
            0,
            0,
            0,
            0,
            0,
            offset,
        )
        central += encoded
    ending = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(entries), len(entries), len(central), len(local), 0)
    (path / "samples.npz").write_bytes(local + central + ending)
    refresh_hash(path)


@pytest.mark.parametrize("fault", ["hidden-output", "unterminated", "compressed-tail"])
def test_review_compressed_integrity_refuses(tmp_path, config, monkeypatch, fault):
    path = sequence_file(tmp_path, config)
    compression_fault_archive(path, fault)
    opened = []
    original = zipfile.ZipFile.open

    def tracked(*args, **kwargs):
        value = original(*args, **kwargs)
        opened.append(value)
        return value

    monkeypatch.setattr(zipfile.ZipFile, "open", tracked)
    with pytest.raises(ValueError, match="compress|decoded|terminat|payload"):
        streamed(path)
    assert all(value.closed for value in opened)


def test_review_npy_header_limit_precedes_advertised_read():
    from flydrones.connectome_training import feature_sequence as reader

    class Budgeted(io.BytesIO):
        def read(self, n=-1):
            assert 0 <= n <= 10000, "oversized NPY header read requested"
            return super().read(n)

    payload = b"\x93NUMPY\x02\x00" + struct.pack("<I", 1_000_000_000) + b"tiny"
    with pytest.raises(ValueError, match="header"):
        reader._header(Budgeted(payload), SimpleNamespace(file_size=len(payload)), 1)


def test_review_row_size_representability_precedes_allocation():
    from flydrones.connectome_training import feature_sequence as reader

    shape = (1, 1, 2**61)
    out = io.BytesIO()
    np.lib.format.write_array_header_1_0(out, dict(descr="<f4", fortran_order=False, shape=shape))
    payload = out.getvalue()
    info = SimpleNamespace(file_size=len(payload) + math.prod(shape) * 4)
    with pytest.raises(ValueError, match="size|dimension|represent"):
        reader._header(io.BytesIO(payload), info, 1)


@pytest.mark.parametrize("method", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_integrity_chunk_drain_and_stored_parity(tmp_path, config, method):
    value = sessions._synthetic_sequence(config.stages[0], "train", 1101)
    for frame in value.frames:
        frame.rgb = np.repeat(frame.rgb, 100, axis=1)
        frame.depth_m = np.repeat(frame.depth_m, 100, axis=1)
    path = write_sequence(tmp_path / "wide", value)
    with zipfile.ZipFile(path / "samples.npz") as archive:
        entries = [(i.filename, archive.read(i)) for i in archive.infolist()]
    with zipfile.ZipFile(path / "samples.npz", "w", compression=method) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)
    refresh_hash(path)
    assert all(
        torch.equal(a, b) for a, b in zip(sequence_tensors(streamed(path)), sequence_tensors(load_sequence(path)), strict=True)
    )


def test_unsupported_compression_refuses_before_member_open(tmp_path, config, monkeypatch):
    path = sequence_file(tmp_path, config)
    with zipfile.ZipFile(path / "samples.npz") as archive:
        entries = [(i.filename, archive.read(i)) for i in archive.infolist()]
    with zipfile.ZipFile(path / "samples.npz", "w", compression=zipfile.ZIP_BZIP2) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)
    refresh_hash(path)
    monkeypatch.setattr(zipfile.ZipFile, "open", lambda *a, **k: pytest.fail("unsupported decoder opened"))
    with pytest.raises(ValueError, match="compression"):
        streamed(path)
