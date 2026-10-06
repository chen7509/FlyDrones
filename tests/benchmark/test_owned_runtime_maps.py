import json
from types import SimpleNamespace

import pytest

from tools.benchmark.owned_runtime_maps import OwnedRuntimeMaps, parse_maps

STAT = "321 (child) S 1 321 321 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 77 0 0 0\n"
MAP = "1000-2000 r-xp 0000 08:01 12 /usr/lib/libexample.so\n"


def observer(tmp_path, *, stat=STAT, exe="/usr/bin/child", maps=MAP, limit=1024):
    values = {"stat": stat, "exe": exe, "maps": maps}
    obj = OwnedRuntimeMaps(
        tmp_path,
        {"/usr/bin/child": {"device": 2049, "inode": 11},
         "/usr/lib/libexample.so": {"device": 2049, "inode": 12}},
        max_maps_bytes=limit,
        max_observations=4,
        stat_reader=lambda _pid: values["stat"],
        exe_reader=lambda _pid: values["exe"],
        maps_reader=lambda _pid, _limit: values["maps"],
        path_resolver=lambda value: value,
    )
    return obj, values


def test_registered_identity_and_mapping_are_persisted(tmp_path):
    obj, _ = observer(tmp_path)
    row = obj.register("px4", SimpleNamespace(pid=321), "/usr/bin/child")
    assert row["start_ticks"] == 77
    result = obj.observe("px4", "ready")
    assert result["observed_files_covered"] is True
    assert json.loads((tmp_path / "runtime-maps-px4-ready.json").read_text())["role"] == "px4"


@pytest.mark.parametrize("change,match", [
    ("pid", "identity"), ("start", "identity"), ("exec", "executable"),
    ("oversize", "size"), ("deleted", "mapping"), ("unknown", "covered"),
])
def test_identity_and_mapping_failures_are_retained(tmp_path, change, match):
    obj, values = observer(tmp_path)
    obj.register("px4", SimpleNamespace(pid=321), "/usr/bin/child")
    if change == "pid":
        values["stat"] = STAT.replace("321 (child)", "322 (child)")
    elif change == "start":
        values["stat"] = STAT.replace(" 77 0 0", " 78 0 0")
    elif change == "exec":
        values["exe"] = "/usr/bin/other"
    elif change == "oversize":
        values["maps"] = "x" * 1025
    elif change == "deleted":
        values["maps"] = MAP.rstrip() + " (deleted)\n"
    else:
        values["maps"] = MAP.replace("libexample.so", "other.so")
    with pytest.raises(ValueError, match=match):
        obj.observe("px4", "ready")
    assert (tmp_path / "runtime-maps-px4-ready.json").exists()


def test_duplicate_role_phase_and_budget_are_refused(tmp_path):
    obj, _ = observer(tmp_path)
    obj.register("px4", SimpleNamespace(pid=321), "/usr/bin/child")
    with pytest.raises(ValueError, match="registered"):
        obj.register("px4", SimpleNamespace(pid=321), "/usr/bin/child")
    obj.observe("px4", "ready")
    with pytest.raises(ValueError, match="repeated"):
        obj.observe("px4", "ready")
    for phase in ("a", "b", "c"):
        obj.observe("px4", phase)
    with pytest.raises(ValueError, match="budget"):
        obj.observe("px4", "d")


def test_parser_rejects_malformed_and_nonabsolute():
    assert parse_maps(MAP)[0]["inode"] == 12
    for text in ("bad", MAP.replace("/usr/lib", "relative"), MAP.rstrip() + " (deleted)\n"):
        with pytest.raises(ValueError):
            parse_maps(text)
