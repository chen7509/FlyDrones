"""Pure retained-runtime joins for the live-wire auditor; never starts a runtime.

Inputs are already-read records. Full study declaration, file authenticity,
resource-graph selection and workload need their own checks. Stable snapshots and
parsed mappings are observations, not an atomic or hostile-actor proof.
"""

from __future__ import annotations

import copy
import re
import stat
from pathlib import PurePosixPath

from tools.benchmark.audit_live_wire_study import _equal, _integer, _shape
from tools.benchmark.owned_runtime_maps import _device_parts, parse_maps
from tools.benchmark.runtime_resource_binding import GENERATED_NAMES


def _path(value):
    if (
        type(value) is not str
        or not value.startswith("/")
        or "\0" in value
        or ".." in PurePosixPath(value).parts
        or value.endswith(" (deleted)")
    ):
        raise ValueError("invalid recorded Linux path")


def _file(row):
    _shape(row, ("role", "requested", "resolved", "links", "identity", "path_identity", "bytes", "sha256"), "runtime file")
    if type(row["role"]) is not str or not row["role"]:
        raise ValueError("runtime file role")
    for key in ("requested", "resolved"):
        _path(row[key])
    if type(row["sha256"]) is not str or re.fullmatch("[0-9a-f]{64}", row["sha256"]) is None:
        raise ValueError("runtime file digest")
    _integer(row["bytes"], 0, 2**63 - 1, "file bytes")
    for key in ("identity", "path_identity"):
        identity = row[key]
        _shape(identity, ("device", "inode", "mode", "size", "mtime_ns", "ctime_ns"), "file identity")
        for field in ("device", "inode", "mode", "size"):
            _integer(identity[field], 0, 2**64 - 1, "identity " + field)
        for field in ("mtime_ns", "ctime_ns"):
            _integer(identity[field], -(2**63), 2**63 - 1, "identity " + field)
        if not stat.S_ISREG(identity["mode"]):
            raise ValueError("non-regular runtime file")
        _equal(identity["size"], row["bytes"], "identity size")
    if type(row["links"]) is not list or len(row["links"]) > 40:
        raise ValueError("runtime file links")
    for link in row["links"]:
        _shape(link, ("path", "target", "identity"), "recorded link")
        _path(link["path"])
        if type(link["target"]) is not str or not link["target"] or "\0" in link["target"]:
            raise ValueError("link target")
        _shape(link["identity"], ("device", "inode", "mode", "size", "mtime_ns", "ctime_ns"), "link identity")
        if any(type(value) is not int for value in link["identity"].values()) or not stat.S_ISLNK(link["identity"]["mode"]):
            raise ValueError("link identity")


def _snapshot(value):
    if type(value) is not dict:
        raise ValueError("runtime snapshot")
    _equal(value.get("schema"), "declared-files-v1", "snapshot schema")
    _equal(value.get("runtime_closure_qualified"), False, "snapshot scope")
    _integer(value.get("started_monotonic_ns"), 0, 2**64 - 1, "snapshot start")
    _integer(value.get("ended_monotonic_ns"), value["started_monotonic_ns"], 2**64 - 1, "snapshot end")
    rows = value.get("files")
    if type(rows) is not list or not rows or len(rows) > 10000:
        raise ValueError("snapshot files missing or excessive")
    seen, aliases = set(), {}
    for row in rows:
        _file(row)
        if row["requested"] in seen:
            raise ValueError("duplicate requested runtime file")
        seen.add(row["requested"])
        # Same resolved file may legitimately be reached via multiple declared
        # lexical aliases. They must carry the same actual identity and content.
        identity = {k: row[k] for k in ("identity", "path_identity", "bytes", "sha256")}
        if row["resolved"] in aliases:
            _equal(identity, aliases[row["resolved"]], "conflicting resolved aliases")
        aliases[row["resolved"]] = identity
    return rows


def _owner(value, *, role=None):
    keys = {"pid", "pgrp", "session", "start_ticks", "state", "executable"}
    _shape(value, keys | ({"role"} if role is not None else set()), "runtime owner")
    if role is not None:
        _equal(value["role"], role, "registered role")
    for key in ("pid", "pgrp", "session", "start_ticks"):
        _integer(value[key], 0 if key == "start_ticks" else 2 if key == "pid" else 1, 2**64 - 1, key)
    if type(value["state"]) is not str or value["state"] not in set("RSDTtWKPI"):
        raise ValueError("runtime owner not live")
    _path(value["executable"])
    return {key: value[key] for key in keys - {"state"}}


def audit_runtime_mapping_records(*, declaration, pre, post, summary, maps, owners, process):
    """Recompute declared file/map identity joins; no current /proc or file I/O.

    The caller must validate the *whole* prospective declaration separately.
    This function consumes its runtime-related fields and compares the entire
    declaration with the recorded pre-run copy. It does not resolve resources.
    """
    try:
        return _audit(declaration, pre, post, summary, maps, owners, process)
    except (KeyError, TypeError, IndexError, OverflowError) as exc:
        raise ValueError("malformed retained runtime records") from exc


def _audit(declaration, pre, post, summary, maps, owners, process):
    _equal(declaration["schema"], "capture-resource-binding-v3", "runtime binding version")
    _equal(pre["declaration"], declaration, "actual/prospective declaration")
    _equal(pre["environment"], declaration["environment"], "runtime search environment")
    before, after = _snapshot(pre), _snapshot(post)
    _equal(before, after, "pre/post files")
    if post["started_monotonic_ns"] < pre["ended_monotonic_ns"]:
        raise ValueError("post snapshot precedes pre")
    baseline = _snapshot(declaration["baseline"])
    generated = _snapshot(pre["generated"])
    if declaration["baseline"]["ended_monotonic_ns"] > pre["started_monotonic_ns"]:
        raise ValueError("declaration snapshot not prior to run")
    if pre["generated"]["ended_monotonic_ns"] > pre["started_monotonic_ns"]:
        raise ValueError("generated snapshot not prior to merged snapshot")
    inventory = declaration["inventory"]
    if type(inventory) is not dict or not inventory:
        raise ValueError("missing runtime inventory")
    expected_inventory = [(role, path) for role, paths in inventory.items() for path in paths]
    _equal([(row["role"], row["requested"]) for row in baseline], expected_inventory, "inventory baseline membership")
    _equal([row for row in before if row["role"] in inventory], baseline, "prospective baseline files")
    copies = [dict(row, role=row["role"].removeprefix("generated:")) for row in before if row["role"].startswith("generated:")]
    _equal(copies, generated, "generated snapshots")
    _equal([row["role"] for row in copies], list(GENERATED_NAMES), "generated set/order")
    _equal({row["role"]: row["sha256"] for row in copies}, declaration["generated"], "generated declared digests")
    if any(
        row["role"] not in inventory and row["role"] != "bootstrap:selfmaps" and not row["role"].startswith("generated:")
        for row in before
    ):
        raise ValueError("unexplained runtime inventory addition")
    known = {row["resolved"]: row for row in before}
    runtime = declaration["runtime_maps"]
    self_phases = runtime["self_phases"]
    roles = runtime["owned_roles"]
    _integer(runtime["max_maps_bytes"], 1, 8388608, "maps read bound")
    _integer(runtime["max_observations"], 1, 64, "maps observation bound")
    if (
        type(self_phases) is not list
        or not {"postimports", "postfinalize", "postfirststep"} <= set(self_phases)
        or len(set(self_phases)) != len(self_phases)
        or set(roles) != {"px4", "openvins"}
        or any(phases != ["ready", "prestop"] for phases in roles.values())
    ):
        raise ValueError("incomplete runtime phase profile")
    phase_order = ["postgraph", "bootstrap", *self_phases]
    if len(set(phase_order)) != len(phase_order):
        raise ValueError("duplicate runtime self phase")
    _equal(summary["phases"], phase_order, "completed self phases")
    _equal(summary["owned_phases"], roles, "completed owned phases")
    for key in ("pre_recorded", "declared_files_stable", "local_file_graph_verified", "runtime_mapping_coverage_verified"):
        _equal(summary[key], True, "runtime summary " + key)
    _equal(summary["errors"], [], "runtime errors")
    _equal(summary["runtime_closure_qualified"], False, "runtime authority")
    if sum(len(phases) for phases in roles.values()) > runtime["max_observations"]:
        raise ValueError("owned observations exceed declared budget")
    expected_maps = {"runtime-maps-" + phase: (None, phase) for phase in phase_order}
    expected_maps.update(
        {"runtime-maps-" + role + "-" + phase: (role, phase) for role, phases in roles.items() for phase in phases}
    )
    _shape(maps, expected_maps, "map observations")
    _shape(owners, roles, "registered owners")
    registered = {}
    for role in roles:
        registered[role] = _owner(owners[role], role=role)
        root = inventory["runtime-root:" + role]
        if type(root) is not list or len(root) != 1:
            raise ValueError("runtime root is not unique")
        rows = [row for row in baseline if row["requested"] == root[0]]
        if len(rows) != 1:
            raise ValueError("runtime root missing from baseline")
        _equal(registered[role]["executable"], rows[0]["resolved"], "owned executable selection")
    if registered["px4"]["pid"] == registered["openvins"]["pid"]:
        raise ValueError("owned role PID collision")
    _shape(process, ("pid", "args", "started_wall_ns"), "PX4 launch record")
    _equal(process["pid"], registered["px4"]["pid"], "PX4 launched PID")
    args = process["args"]
    if type(args) is not list or len(args) != 5:
        raise ValueError("PX4 launch arguments")
    _equal(args[:4], [inventory["runtime-root:px4"][0], "-i", "8", "-d"], "PX4 instance arguments")
    _path(args[4])
    _integer(process["started_wall_ns"], 1, 2**64 - 1, "PX4 launch time")
    loaded_count = 0
    for key, value in maps.items():
        _shape(value, ("raw", "summary"), "runtime map pair")
        raw, record = value["raw"], value["summary"]
        if type(raw) is not str or not raw or len(raw.encode()) > runtime["max_maps_bytes"]:
            raise ValueError("missing or excessive raw map")
        mapped = parse_maps(raw)
        if not mapped:
            raise ValueError("raw map contains no file observation")
        loaded_count += len(mapped)
        for row in mapped:
            actual = known.get(row["path"])
            if actual is None:
                raise ValueError("unknown loaded file")
            _equal(row["inode"], actual["identity"]["inode"], "mapped inode")
            _equal(
                tuple(int(v, 16) for v in row["device"].split(":")), _device_parts(actual["identity"]["device"]), "mapped device"
            )
        _equal(record["unknown"], [], "map unknown summary")
        _equal(record["mismatched"], [], "map mismatch summary")
        _equal(record["observed_files_covered"], True, "map coverage summary")
        role = record.get("role")
        expected_role, expected_phase = expected_maps[key]
        _equal(role, expected_role, "map role from declared stage")
        _equal(record["phase"], expected_phase, "map phase from declared stage")
        if role is None:
            _shape(
                record,
                ("phase", "unknown", "mismatched", "parse_error", "observed_files_covered", "runtime_closure_qualified"),
                "self map summary",
            )
            _equal(key, "runtime-maps-" + record["phase"], "self map phase")
            _equal(record["parse_error"], None, "self map parse error")
            _equal(record["runtime_closure_qualified"], False, "self map authority")
        else:
            _shape(
                record,
                (
                    "role",
                    "phase",
                    "observed_files_covered",
                    "error",
                    "identity_before",
                    "identity_after",
                    "unknown",
                    "mismatched",
                ),
                "owned map summary",
            )
            if role not in registered or record["phase"] not in roles[role]:
                raise ValueError("unexpected owned map phase")
            _equal(key, "runtime-maps-" + role + "-" + record["phase"], "owned map role/phase")
            _equal(record["error"], None, "owned map error")
            for bound in ("identity_before", "identity_after"):
                _equal(_owner(record[bound]), registered[role], "same owned process")
            if registered[role]["executable"] not in {row["path"] for row in mapped}:
                raise ValueError("owned executable absent from raw mapping")
    return dict(
        runtime_records_consistent=True,
        self_phases=len(phase_order),
        owned_phases=sum(len(v) for v in roles.values()),
        mapped_file_observations=loaded_count,
        owners=copy.deepcopy(registered),
        resource_graph_qualified=False,
        runtime_closure_qualified=False,
        live_qualified=False,
        fusion_qualified=False,
    )
