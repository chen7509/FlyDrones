import hashlib
import json
import zipfile

import pytest

from tools.benchmark.reconstruct_evidence_parts import reconstruct


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fixture(tmp_path):
    archive = tmp_path / 'evidence.zip'
    with zipfile.ZipFile(archive, 'w') as target:
        target.writestr('result.json', b'{"status":"failed"}')
    payload = archive.read_bytes()
    index = {'archive_sha256': _sha(payload), 'archive_bytes': len(payload),
             'members': {'result.json': {'bytes': 19,
                                         'sha256': _sha(b'{"status":"failed"}')}}}
    index_path = tmp_path / 'evidence.sha256.json'
    index_path.write_text(json.dumps(index))
    chunks = [payload[:30], payload[30:]]
    parts = []
    for number, chunk in enumerate(chunks):
        name = f'evidence.zip.part{number:03d}'
        (tmp_path / name).write_bytes(chunk)
        parts.append({'name': name, 'bytes': len(chunk), 'sha256': _sha(chunk)})
    manifest = {'schema': 'flydrones-evidence-parts-v1',
                'archive': 'evidence.zip', 'archive_bytes': len(payload),
                'archive_sha256': _sha(payload),
                'index': index_path.name, 'index_sha256': _sha(index_path.read_bytes()),
                'parts': parts}
    manifest_path = tmp_path / 'evidence.parts.json'
    manifest_path.write_text(json.dumps(manifest))
    return manifest_path, payload


def test_reconstruct_checks_parts_and_zip_members(tmp_path):
    manifest, expected = _fixture(tmp_path)
    output = tmp_path / 'rebuilt.zip'
    reconstruct(manifest, output)
    assert output.read_bytes() == expected
    with pytest.raises(FileExistsError):
        reconstruct(manifest, output)


def test_reconstruct_rejects_corrupted_part_without_publishing(tmp_path):
    manifest, _ = _fixture(tmp_path)
    (tmp_path / 'evidence.zip.part001').write_bytes(b'corrupt')
    output = tmp_path / 'rebuilt.zip'
    with pytest.raises(ValueError, match='part'):
        reconstruct(manifest, output)
    assert not output.exists()
