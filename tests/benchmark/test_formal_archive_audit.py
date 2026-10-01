import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from tools.benchmark.audit_archive import audit_archive

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "evidence/fly-ego-comparison-2026-09-22.zip"
INDEX = ROOT / "evidence/fly-ego-comparison-2026-09-22.sha256.json"


def test_formal_archive_retains_all_failed_episodes_and_reports_ulog_gap():
    audit = audit_archive(ARCHIVE, INDEX, ROOT)

    assert audit["worlds"] == 20
    assert audit["episodes"] == 60
    assert audit["status_counts"] == {
        "fly_raw": {"collision": 19, "out_of_bounds": 1},
        "fly_guided": {"collision": 20},
        "ego": {"collision": 18, "success": 2},
    }
    assert audit["formal_ulog_count"] == 0


def test_formal_archive_rejects_changed_index_digest(tmp_path):
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    index["results/fly-ego-comparison/formal/summary.json"] = "0" * 64
    changed = tmp_path / "changed-index.json"
    changed.write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(ValueError, match="changed archived file"):
        audit_archive(ARCHIVE, changed, ROOT)


def test_formal_archive_rejects_changed_runtime_world_even_with_updated_index(tmp_path):
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    name = next(path for path in index if "/formal/episodes/" in path and
                path.endswith("/world.sdf"))
    changed_archive = tmp_path / "changed.zip"
    with zipfile.ZipFile(ARCHIVE) as source, zipfile.ZipFile(
        changed_archive, "w", compression=zipfile.ZIP_DEFLATED
    ) as destination:
        for item in source.namelist():
            payload = source.read(item)
            if item == name:
                payload += b"<!-- unrelated obstacle edit -->"
                index[name] = hashlib.sha256(payload).hexdigest()
            destination.writestr(item, payload)
    changed_index = tmp_path / "changed-index.json"
    changed_index.write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(ValueError, match="episode runtime world differs"):
        audit_archive(changed_archive, changed_index, ROOT)
