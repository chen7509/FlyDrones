"""Distinct once-only v2 static producer; no engine, PX4, Agent or sensor execution."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.metadata
import json
import sys
import time
from pathlib import Path

from tools.benchmark.calibration_capture_study import FOLDER as V1_FOLDER
from tools.benchmark.calibration_capture_study import SOURCE, arguments
from tools.benchmark.calibration_capture_study_v2 import FOLDER, ROOT, publish_study_v2
from tools.benchmark.capture_contract import _typed_equal, execution_contract
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot, write_manifest
from tools.benchmark.native_entry_dependencies import BASE_ENV, _run_tool, discover_entry_dependencies
from tools.benchmark.prepare_calibration_capture import AGENT, CATALOG, required_plugins, scope_before

RENDERER = "/usr/lib/x86_64-linux-gnu/gz-rendering-8/engine-plugins/libgz-rendering8-ogre2.so.8.2.3"


def select_entries(catalog, plugins, native, agent_paths, resolver):
    entries = {}
    seen = set()

    def add(role, paths):
        selected = [str(p) for p in paths if str(p) not in seen]
        seen.update(selected)
        if selected:
            entries[role] = list(dict.fromkeys(selected))

    for role, paths in catalog["inventory"].items():
        if (
            role.startswith("runtime-root:")
            and not role.startswith("runtime-root:python")
            and role not in {"runtime-root:openvins", "runtime-root:native-reference"}
        ):
            add(role, paths)
    add("renderer", [RENDERER])
    add("selected-world-model-plugins", plugins)
    add("current-python-native", native)
    add("resolver", [resolver])
    add("agent", agent_paths)
    candidates = list(dict.fromkeys(catalog["inventory"].get("runtime:dependencies", [])))
    return entries, candidates


def reuse_agent_cache(configuration, deployment):
    from tools.benchmark.agent_capture_runtime import AGENT_SHA256, BUNDLE_SHA256, LIBRARY_SHA256

    expected = {"bin/MicroXRCEAgent": AGENT_SHA256, **{"lib/" + name: sha for name, sha in LIBRARY_SHA256.items()}}
    binary, lib = Path(configuration["binary"]), Path(configuration["lib_dir"])
    if (
        configuration["schema"] != "capture-agent-runtime-v1"
        or configuration["port"] != 18888
        or binary.parent != lib.parent / "bin"
    ):
        raise ValueError("Agent cache configuration changed")
    if {p.name for p in lib.iterdir()} != set(LIBRARY_SHA256):
        raise ValueError("Agent cache directory member set changed")
    members = {r["member"]: r["deployed"] for r in deployment["members"]}
    if len(members) != len(deployment["members"]) or set(members) != set(expected):
        raise ValueError("Agent cache member set changed")
    rows = []
    for name, sha in expected.items():
        path = binary if name == "bin/MicroXRCEAgent" else lib / name.removeprefix("lib/")
        row = file_record(path)
        if row["sha256"] != sha or not _typed_equal(row, members[name]):
            raise ValueError("Agent cache pinned file changed")
        rows.append(row)
    bundle = file_record(configuration["bundle"])
    if bundle["sha256"] != BUNDLE_SHA256 or not _typed_equal(bundle, deployment["bundle"]):
        raise ValueError("Agent cache original bundle changed")
    return dict(files=rows, bundle=bundle, extracted=False, executed=False, transitive_license_certified=False)


def timed(operation, output, metadata):
    started = time.monotonic_ns()
    record = dict(
        metadata=metadata, start_monotonic_ns=started, start_utc=datetime.datetime.now(datetime.UTC).isoformat(), error=None
    )
    primary = None
    try:
        return operation()
    except BaseException as exc:
        primary = exc
        record["error"] = repr(exc)
        raise
    finally:
        raw = metadata.get("raw_query_path")
        hash_error = None
        try:
            record["raw_query_sha256"] = (
                hashlib.sha256(Path(raw).read_bytes()).hexdigest() if raw and Path(raw).is_file() else None
            )
        except Exception as exc:
            hash_error = exc
            record.update(raw_query_sha256=None, raw_query_error=repr(exc))
            if primary is not None:
                primary.add_note("SDK raw-record identity failure: " + repr(exc))
            else:
                record["error"] = repr(exc)
        ended = time.monotonic_ns()
        record.update(end_monotonic_ns=ended, elapsed_ns=ended - started, end_utc=datetime.datetime.now(datetime.UTC).isoformat())
        try:
            write_manifest(output, record)
        except Exception as exc:
            if primary is None:
                raise
            primary.add_note("paired-clock persistence failure: " + repr(exc))
        if primary is None and hash_error is not None:
            raise hash_error


class ClockedClient:
    def __init__(self, client, binary):
        self.client, self.binary, self.count = client, binary, 0

    def check_budget(self):
        return self.client.check_budget()

    def query(self, *args):
        number = getattr(self.client, "count", self.count)
        self.count += 1
        raw = self.client.output / f"resource-query-{number:04d}.json"
        clock = self.client.output / f"local-clock-{number:04d}.json"
        return timed(lambda: self.client.query(*args), clock, dict(argv=[str(self.binary), *args], raw_query_path=str(raw)))


def licenses(paths, output):
    selected = sorted({str(Path(p).resolve()) for p in paths if Path(p).is_file() and Path(p).suffix != ".py"})
    tool = file_record("/usr/bin/dpkg-query")
    argv = [tool["requested"], "-S", *selected]
    query = _run_tool(argv, dict(BASE_ENV))
    owner_row = dict(query, tool_before=tool, tool_after=None)
    primary = None
    if (
        query["error"] is not None
        or query["output_limit_exceeded"]
        or query["reader_complete"] is not True
        or type(query["exit"]) is not int
        or query["exit"] not in (0, 1)
    ):
        primary = ValueError("bounded installed license query failed: " + str(query["error"]))
    try:
        owner_row["tool_after"] = file_record(tool["requested"])
        if not _typed_equal(tool, owner_row["tool_after"]):
            raise ValueError("installed license tool changed")
    except Exception as exc:
        owner_row["postpin_error"] = repr(exc)
        if primary is None:
            primary = exc
        else:
            primary.add_note("installed license post-pin failure: " + repr(exc))
    try:
        write_manifest(output / "package-owner-query.json", owner_row)
    except Exception as exc:
        owner_row["persistence_error"] = repr(exc)
        if primary is None:
            primary = exc
        else:
            primary.add_note("installed license query persistence failure: " + repr(exc))
        try:
            write_manifest(output / "installed-license-query-failure.json", owner_row)
        except Exception as fallback:
            primary.add_note("installed license fallback persistence failure: " + repr(fallback))
    if primary is not None:
        raise primary
    owners = set()
    for line in bytes.fromhex(query["stdout_hex"]).decode(errors="strict").splitlines():
        if ": /" in line:
            owners.update(line.split(": /", 1)[0].split(", "))
    notices, packages, distributions = [Path(tool["requested"])], [], []
    record = dict(
        query=query,
        selected_owners=sorted(owners),
        package_notices=packages,
        python_distributions=distributions,
        partially_unowned=query["exit"] == 1,
        transitive_license_certified=False,
    )
    primary = None
    try:
        for owner in sorted(owners):
            notice = Path("/usr/share/doc") / owner.split(":", 1)[0] / "copyright"
            packages.append(dict(owner=owner, copyright=file_record(notice) if notice.is_file() else None))
            if notice.is_file():
                notices.append(notice)
        for package in ("numpy", "scipy", "pyulog", "pymavlink", "protobuf"):
            dist = importlib.metadata.distribution(package)
            files = [
                dist.locate_file(n) for n in dist.files or [] if "license" in str(n).lower() or "copyright" in str(n).lower()
            ]
            files = [p for p in files if p.is_file()]
            notices.extend(files)
            distributions.append(dict(package=package, version=dist.version, notices=[file_record(p) for p in files]))
    except Exception as exc:
        primary = exc
        record["error"] = repr(exc)
        raise
    finally:
        try:
            write_manifest(output / "installed-license-observations.json", record)
        except Exception as exc:
            if primary is None:
                raise
            primary.add_note("license observation persistence failure: " + repr(exc))
    return notices


def prepare_v2(unit):
    from tools.benchmark.bound_resource_graph import build_graph
    from tools.benchmark.calibration_capture_contract import copy_scene, scene_record
    from tools.benchmark.calibration_capture_study_v2 import audit_v2_preparation
    from tools.benchmark.native_resource_client import QUERY_ENV_KEYS, QueryClient
    from tools.benchmark.runtime_resource_binding import ENV_KEYS, validate_binding

    if FOLDER.exists():
        raise FileExistsError("one static raw preparation already exists; no replay")
    parent = FOLDER.parent
    started = time.monotonic_ns()
    start_utc = datetime.datetime.now(datetime.UTC).isoformat()
    cg = timed(lambda: scope_before(unit, parent), parent / "scope-local-clock.json", dict(operation="own-scope-before"))
    FOLDER.mkdir()
    primary = None
    try:
        source = scene_record(SOURCE)
        capture = FOLDER / "capture-input-v1"
        capture.mkdir()
        copy_scene(source, capture)
        wire = dict(
            schema="capture-wire-startup-v2",
            session_id="calibration-measurement-dev-1701",
            sim_origin_ns=0,
            remote_origin_ns=0,
            startup_max_wall_ns=60_000_000_000,
        )
        write_manifest(FOLDER / "wire-config.json", wire)
        old_agent = V1_FOLDER / "agent-runtime.json"
        old_deployment = V1_FOLDER / "agent-deployment.json"
        configuration = json.loads(old_agent.read_text(encoding="utf8"))
        reused = reuse_agent_cache(configuration, json.loads(old_deployment.read_text(encoding="utf8")))
        write_manifest(
            FOLDER / "agent-cache-reuse.json",
            dict(reused, source_configuration=file_record(old_agent), source_deployment=file_record(old_deployment)),
        )
        write_manifest(FOLDER / "agent-runtime.json", configuration)
        args = arguments(FOLDER)
        env = {key: None for key in set(ENV_KEYS) | set(QUERY_ENV_KEYS)}
        env.update(
            HOME="/home/yuchen7509",
            PATH="/usr/bin:/bin",
            LANG="C.UTF-8",
            GZ_SIM_RESOURCE_PATH=str(capture / "models"),
            GZ_SIM_SYSTEM_PLUGIN_PATH="",
            SDF_PATH="",
            GZ_FILE_PATH="",
            GZ_HOMEDIR=str(FOLDER / "gz-home"),
            MESA_SHADER_CACHE_DISABLE="true",
        )
        query_env = {key: env[key] for key in QUERY_ENV_KEYS}
        catalog = json.loads(CATALOG.read_text(encoding="utf8"))
        resolver = Path(catalog["inventory"]["graph:resolver"][0])
        pins = {row["role"]: row for row in catalog["baseline"]["files"] if row["role"] in ("graph:resolver", "graph:source")}
        for role, path in (("graph:resolver", resolver), ("graph:source", ROOT / "tools/benchmark/native/resource_resolver.cc")):
            if file_record(path)["sha256"] != pins[role]["sha256"]:
                raise ValueError("existing SDK resolver/source pin changed")
        sdk = FOLDER / "sdk"
        sdk.mkdir()
        client = ClockedClient(QueryClient(resolver, ROOT, query_env, sdk), resolver)
        context = client.query("context")
        installation = client.query("installation")
        write_manifest(sdk / "installed-context.json", context)
        write_manifest(sdk / "installed-directories.json", installation)
        contract = execution_contract(args, env)
        inventory = {}
        used = set()

        def add(role, paths):
            selected = []
            for value in paths:
                path = str(Path(value).absolute())
                if path not in used:
                    used.add(path)
                    selected.append(path)
            if selected:
                inventory[role] = selected

        add("graph:resolver", [resolver])
        add(
            "graph:source",
            [
                ROOT / "tools/benchmark/native/resource_resolver.cc",
            ],
        )
        # A former catalog supplies only installed native root candidates. All
        # selected bytes/dependencies are freshly observed; no old native runs.
        native = [str(Path("/usr/bin/python3"))]
        modules = []
        for module in tuple(sys.modules.values()):
            name = getattr(module, "__file__", None)
            if name and Path(name).is_file():
                modules.append(str(Path(name).resolve()))
                if Path(name).suffix == ".so":
                    native.append(str(Path(name).resolve()))
        for pattern in ("gz/**/*.so", "sdformat14*.so"):
            native.extend(str(p.resolve()) for p in Path("/usr/lib/python3/dist-packages").glob(pattern))
        entries, candidates = select_entries(
            catalog, required_plugins(capture, client), native, contract["agent"]["selected_paths"], str(resolver)
        )
        agent_configuration = contract["agent"]["configuration"]
        loader_paths = [
            p
            for p in contract["agent"]["selected_paths"]
            if p == agent_configuration["binary"] or Path(p).parent == Path(agent_configuration["lib_dir"])
        ]
        bill = discover_entry_dependencies(
            entries, candidates, loader_paths, agent_configuration["lib_dir"], sdk / "entry-dependencies"
        )
        add("graph:dependencies", [p for entry in bill["entries"] for p in entry["selected"]])
        add("runtime:entry-dependency-files", [row["requested"] for row in bill["files"]])
        add("runtime:python-modules", modules)
        add("runtime:installed-notices", licenses([path for paths in inventory.values() for path in paths], sdk))
        add("runtime:classic-material", [installation["classic_material"]])
        add(
            "runtime:project-source",
            sorted(
                p
                for scope in (ROOT / "src/flydrones", ROOT / "tools/benchmark", ROOT / "tools/connectome")
                for p in scope.rglob("*.py")
                if "__pycache__" not in p.parts
            ),
        )
        add("runtime:resolver-headers", [ROOT / "tools/benchmark/native/local_candidates.hh"])
        add("runtime:source-scene", [SOURCE / name for name in source["files"]])
        add(
            "runtime:original-models",
            [ROOT / "assets/gazebo/models/x500_benchmark/model.sdf", ROOT / "assets/gazebo/models/OakD-Benchmark/model.sdf"],
        )
        # The collector explicitly requires these original source/profile files.
        add(
            "runtime:px4-selected",
            [
                Path("/home/yuchen7509/PX4-Autopilot") / name
                for name in (
                    "build/px4_sitl_default/rootfs/gz_env.sh",
                    "build/px4_sitl_default/etc/init.d-posix/rcS",
                    "src/modules/simulation/gz_bridge/server.config",
                    "Tools/simulation/gz/models/x500/model.sdf",
                    "Tools/simulation/gz/models/x500_base/model.sdf",
                    "LICENSE",
                )
            ],
        )
        add("runtime:logger", [Path(p) for p in contract["logger_diagnostic"]["source_paths"]])
        add(
            "runtime:configuration",
            [
                FOLDER / "wire-config.json",
                FOLDER / "agent-runtime.json",
                FOLDER / "agent-cache-reuse.json",
                old_agent,
                old_deployment,
                CATALOG,
                AGENT,
                sdk / "entry-dependencies/entry-bill.json",
            ],
        )
        gz_env = Path("/home/yuchen7509/PX4-Autopilot/build/px4_sitl_default/rootfs/gz_env.sh")
        generated = {name: row["sha256"] for name, row in source["files"].items()}
        generated["gz_env.sh"] = file_record(gz_env)["sha256"]
        binding = dict(
            schema="capture-resource-binding-v4",
            capture_profile="target-bearing-raw-v1",
            calibration_scene=source,
            inventory=inventory,
            baseline=snapshot(inventory),
            environment={key: env[key] for key in (*ENV_KEYS, "MESA_SHADER_CACHE_DISABLE")},
            generated=generated,
            graph=dict(schema="generated-resource-graph-v1", cwd=str(ROOT), environment=query_env, expected_context=context),
            runtime_maps=dict(
                self_phases=["postimports", "postfinalize", "postfirststep"],
                owned_roles={"px4": ["ready", "prestop"], "agent": ["ready", "prestop"]},
                max_maps_bytes=8 * 1024**2,
                max_observations=16,
            ),
        )
        validate_binding(binding)
        write_manifest(FOLDER / "runtime-binding-v4.json", binding)
        write_manifest(FOLDER / "execution-contract.json", contract)
        proof_inventory = dict(inventory)
        for name in source["files"]:
            proof_inventory["generated:" + name] = [str(capture / name)]
        # The copied runtime gz_env bytes have their source record in baseline;
        # the actual runtime-generated path is separately rechecked by worker.
        pre = snapshot(proof_inventory)
        graph_client = ClockedClient(QueryClient(resolver, ROOT, query_env, FOLDER / "graph-queries"), resolver)
        (FOLDER / "graph-queries").mkdir()
        graph_context = graph_client.query("context")
        graph = build_graph(capture / "world.sdf", graph_client, pre["files"], FOLDER / "graph-queries")
        after = snapshot(proof_inventory)
        pre["resource_graph"] = graph
        preparation = dict(
            schema="raw-static-sdk-preparation-v2",
            entry_bill_sha256=hashlib.sha256((sdk / "entry-dependencies/entry-bill.json").read_bytes()).hexdigest(),
            binding_sha256=hashlib.sha256((FOLDER / "runtime-binding-v4.json").read_bytes()).hexdigest(),
            execution_sha256=hashlib.sha256((FOLDER / "execution-contract.json").read_bytes()).hexdigest(),
            pre=pre,
            after_queries=after,
            graph=graph,
            context=graph_context,
            queries=[json.loads(p.read_text()) for p in sorted((FOLDER / "graph-queries").glob("resource-query-*.json"))],
            documents_hex={row["source"]: Path(row["source"]).read_bytes().hex() for row in graph["documents"]},
            query_clocks=[json.loads(p.read_text()) for p in sorted((FOLDER / "graph-queries").glob("local-clock-*.json"))],
            audit=None,
        )
        from tools.benchmark.audit_live_wire_resources import audit_resource_graph_records

        preparation["audit"] = audit_resource_graph_records(
            declaration=binding,
            pre=pre,
            after_queries=after,
            graph=graph,
            context=graph_context,
            queries=preparation["queries"],
            documents={p: bytes.fromhex(data) for p, data in preparation["documents_hex"].items()},
        )
        audit_v2_preparation(binding, preparation, sdk / "entry-dependencies/entry-bill.json", bill)
        write_manifest(FOLDER / "preparation.json", preparation)
        result = publish_study_v2()
        write_manifest(parent / "native-freeze-result.json", result)
        return result
    except Exception as exc:
        primary = exc
        try:
            write_manifest(parent / "native-freeze-failure.json", dict(error=repr(exc), folder=str(FOLDER), qualification=False))
        except Exception as writer:
            exc.add_note("native failure persistence error: " + repr(writer))
        raise
    finally:
        ended = time.monotonic_ns()
        record = dict(
            cgroup=str(cg),
            start_monotonic_ns=started,
            end_monotonic_ns=ended,
            elapsed_ns=ended - started,
            start_utc=start_utc,
            end_utc=datetime.datetime.now(datetime.UTC).isoformat(),
            qualification=False,
        )
        counter_error = None
        try:
            record.update(
                limits={
                    name: (cg / name).read_text().strip() for name in ("memory.max", "memory.swap.max", "cpu.max", "pids.max")
                },
                memory_events=(cg / "memory.events").read_text(),
                memory_peak=(cg / "memory.peak").read_text() if (cg / "memory.peak").exists() else None,
            )
        except Exception as exc:
            counter_error = exc
            record["counter_error"] = repr(exc)
            if primary is not None:
                primary.add_note("scope final counter failure: " + repr(exc))
        try:
            write_manifest(parent / "sdk-inside-after.json", record)
        except Exception as exc:
            if primary is None:
                raise
            primary.add_note("scope final persistence failure: " + repr(exc))
        if primary is None and counter_error is not None:
            raise counter_error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", required=True, action="store_true")
    parser.add_argument("--unit", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(prepare_v2(args.unit)))


if __name__ == "__main__":
    main()
