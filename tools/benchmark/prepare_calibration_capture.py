"""One concrete static SDK/input preparation; never starts a simulator, Agent or PX4."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path

from tools.benchmark.calibration_capture_study import FOLDER, ROOT, SOURCE, arguments, publish_study
from tools.benchmark.capture_contract import execution_contract
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot, write_manifest

CATALOG = ROOT / "results/declared-launch-environment-dev-1701/dry-v1/runtime-binding-v3.json"
AGENT = ROOT / "results/agent-capture-contract-dev-1701/agent-runtime.json"


def runtime_catalog(catalog):
    selected = []
    for role, paths in catalog["inventory"].items():
        if (
            role.startswith("runtime-root:")
            and not role.startswith("runtime-root:python")
            and role not in {"runtime-root:openvins", "runtime-root:native-reference"}
        ):
            selected.extend(paths)
        elif role == "runtime:dependencies":
            selected.extend(path for path in paths if path.startswith(("/lib/", "/usr/lib/")))
    return selected


def required_plugins(scene, client):
    """Discover selected plugins before baseline; final graph queries recheck them."""
    from tools.benchmark.selected_resource_graph import references

    names = set()
    for path in sorted(Path(scene).rglob("*.sdf")):
        for reference in references(path.read_bytes(), "sdf"):
            if reference["kind"] == "plugin":
                names.add(reference["text"])
    return [client.query("plugin", name)["selected"] for name in sorted(names)]


def stage_agent(bundle, destination):
    """Materialize exact sealed bytes; never launch or install the Agent."""
    from tools.benchmark.agent_capture_runtime import AGENT_SHA256, BUNDLE_SHA256, LIBRARY_SHA256

    bundle, destination = Path(bundle), Path(destination)
    if destination.exists():
        raise FileExistsError("Agent deployment already exists")
    before = file_record(bundle)
    if before["sha256"] != BUNDLE_SHA256 or before["bytes"] > 8 * 1024**2:
        raise ValueError("sealed Agent bundle hash/size changed")
    expected = {"bin/MicroXRCEAgent": AGENT_SHA256, **{"lib/" + name: sha for name, sha in LIBRARY_SHA256.items()}}
    with tarfile.open(bundle, "r:gz") as archive:
        members = archive.getmembers()
        if (
            len(members) != len(expected) + 2
            or {m.name for m in members} != set(expected) | {"bin", "lib"}
            or sum(m.size for m in members) > 64 * 1024**2
        ):
            raise ValueError("sealed Agent bundle member set/size changed")
        for member in members:
            if member.name in {"bin", "lib"}:
                if not member.isdir():
                    raise ValueError("Agent bundle directory type changed")
            elif member.issym():
                if member.name.startswith("lib/") is False or "/" in member.linkname or "lib/" + member.linkname not in expected:
                    raise ValueError("Agent bundle alias escapes fixed member set")
            elif not member.isfile():
                raise ValueError("Agent bundle unsupported member type")
        destination.mkdir(parents=True, exist_ok=False)
        (destination / "bin").mkdir()
        (destination / "lib").mkdir()
        rows, total = [], 0
        for name, sha in sorted(expected.items()):
            member = archive.getmember(name)
            with archive.extractfile(member) as stream:
                data = stream.read(64 * 1024**2 + 1)
            total += len(data)
            if total > 64 * 1024**2 or hashlib.sha256(data).hexdigest() != sha:
                raise ValueError("Agent deployment pinned member changed")
            path = destination / name
            with path.open("xb") as stream:
                stream.write(data)
            path.chmod(0o755 if name == "bin/MicroXRCEAgent" else 0o644)
            rows.append(
                dict(
                    member=name,
                    archive_type=member.type.decode(),
                    archive_link=member.linkname,
                    archive_mode=member.mode,
                    deployed=file_record(path),
                )
            )
    after = file_record(bundle)
    if before != after:
        raise ValueError("Agent bundle changed during deployment")
    return dict(
        bundle=before,
        bundle_after=after,
        members=rows,
        deployed_bytes=total,
        executed=False,
        alias_policy="regular copies of original linked bytes",
        qualification=False,
    )


def scope_before(unit, output):
    from tools.benchmark.calibration_capture_scope import manager_environment

    lines = [line[3:] for line in Path("/proc/self/cgroup").read_text().splitlines() if line.startswith("0::")]
    if len(lines) != 1:
        raise ValueError("static preparation cgroup unknown")
    group = lines[0]
    cg = Path("/sys/fs/cgroup" + group)
    limits = {name: (cg / name).read_text().strip() for name in ("memory.max", "memory.swap.max", "cpu.max", "pids.max")}
    props = subprocess.run(
        ["systemctl", "--user", "show", unit, "--property=InvocationID", "--property=ControlGroup"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
        env=manager_environment(),
    )
    identities = dict(line.split("=", 1) for line in props.stdout.splitlines() if "=" in line)
    record = dict(pid=os.getpid(), cgroup=group, limits=limits, systemd_properties=props.stdout, qualification=False)
    write_manifest(output / "sdk-inside-before.json", record)
    if (
        re.fullmatch(r"fly-calibration-prepare-[0-9a-f]{24}\.scope", unit) is None
        or not group.endswith("/" + unit)
        or identities.get("ControlGroup") != group
        or not identities.get("InvocationID")
        or limits != {"memory.max": str(512 * 1024**2), "memory.swap.max": "0", "cpu.max": "100000 100000", "pids.max": "64"}
    ):
        raise ValueError("static preparation own scope/limits differ")
    return cg


def dependencies(roots, agent_lib, output):
    found = set()
    records = []
    for path in sorted(set(map(str, roots))):
        env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
        if (
            Path(path).parent.resolve() == Path(agent_lib).resolve()
            or Path(path).resolve() == (Path(agent_lib).parent / "bin/MicroXRCEAgent").resolve()
        ):
            env["LD_LIBRARY_PATH"] = agent_lib
        record = dict(
            path=path,
            argv=["/usr/bin/ldd", path],
            environment=env,
            exit=None,
            stdout_hex="",
            stderr_hex="",
            error=None,
            invoked=False,
        )
        try:
            if not Path(path).is_file():
                raise FileNotFoundError(path)
            with Path(path).open("rb") as stream:
                if stream.read(4) != b"\x7fELF":
                    continue
            record["invoked"] = True
            result = subprocess.run(record["argv"], capture_output=True, env=env, timeout=10)
            record.update(exit=result.returncode, stdout_hex=result.stdout.hex(), stderr_hex=result.stderr.hex())
            if result.returncode or b"not found" in result.stdout:
                raise ValueError("declared current library dependency missing: " + path)
            for line in result.stdout.decode().splitlines():
                match = re.search(r"(?:=>\s+)?(/[^\s]+)\s+\(", line)
                if match:
                    found.add(match[1])
        except BaseException as exc:
            record["error"] = repr(exc)
            if isinstance(exc, subprocess.TimeoutExpired):
                record.update(stdout_hex=(exc.stdout or b"").hex(), stderr_hex=(exc.stderr or b"").hex())
            raise
        finally:
            if record["invoked"] or record["error"]:
                records.append(record)
                # Exclusive per-query records retain earlier observations if a
                # later query times out, fails to spawn, or loses its root.
                write_manifest(output / f"ldd-query-{len(records):04d}.json", record)
                if record["error"]:
                    write_manifest(output / "ldd-observations.json", records)
    write_manifest(output / "ldd-observations.json", records)
    return sorted(found)


def licenses(paths, output):
    selected = sorted({str(Path(path).resolve()) for path in paths if Path(path).is_file() and Path(path).suffix != ".py"})
    query = subprocess.run(["dpkg-query", "-S", *selected], capture_output=True, timeout=20)
    owners = set()
    for line in query.stdout.decode(errors="replace").splitlines():
        if ": /" in line:
            owners.update(line.split(": /", 1)[0].split(", "))
    records = []
    notice_paths = []
    for owner in sorted(owners):
        path = Path("/usr/share/doc") / owner.split(":", 1)[0] / "copyright"
        if path.is_file():
            notice_paths.append(path)
            records.append(dict(owner=owner, file=file_record(path)))
        else:
            records.append(dict(owner=owner, copyright=None))
    python = []
    for package in ("numpy", "scipy", "pyulog", "pymavlink", "protobuf"):
        dist = importlib.metadata.distribution(package)
        members = [
            dist.locate_file(name)
            for name in dist.files or []
            if "license" in str(name).lower() or "copyright" in str(name).lower()
        ]
        members = [path for path in members if path.is_file()]
        notice_paths.extend(members)
        python.append(dict(package=package, version=dist.version, notices=[file_record(path) for path in members]))
    write_manifest(
        output / "installed-license-observations.json",
        dict(
            argv=["dpkg-query", "-S", *selected],
            exit=query.returncode,
            stdout_hex=query.stdout.hex(),
            stderr_hex=query.stderr.hex(),
            package_notices=records,
            python_distributions=python,
            transitive_license_certified=False,
        ),
    )
    return notice_paths


def prepare(unit):
    from tools.benchmark.bound_resource_graph import build_graph
    from tools.benchmark.calibration_capture_contract import copy_scene, scene_record
    from tools.benchmark.calibration_capture_study import audit_preparation
    from tools.benchmark.native_resource_client import QUERY_ENV_KEYS, QueryClient
    from tools.benchmark.runtime_resource_binding import ENV_KEYS, validate_binding

    if FOLDER.exists():
        raise FileExistsError("one static raw preparation already exists; no replay")
    parent = FOLDER.parent
    cg = scope_before(unit, parent)
    FOLDER.mkdir()
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
        historical_agent = json.loads(AGENT.read_text(encoding="utf8"))
        deployed = FOLDER / "agent-deployment-v1"
        deployment = stage_agent(historical_agent["bundle"], deployed)
        write_manifest(FOLDER / "agent-deployment.json", deployment)
        write_manifest(
            FOLDER / "agent-runtime.json",
            dict(
                schema="capture-agent-runtime-v1",
                bundle=historical_agent["bundle"],
                binary=str(deployed / "bin/MicroXRCEAgent"),
                lib_dir=str(deployed / "lib"),
                port=18888,
            ),
        )
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
        client = QueryClient(resolver, ROOT, query_env, sdk)
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
        roots = runtime_catalog(catalog)
        roots.extend(required_plugins(capture, client))
        roots.extend([Path("/usr/bin/python3"), resolver, *contract["agent"]["selected_paths"]])
        roots.extend(
            Path(module.__file__).resolve() for module in tuple(sys.modules.values()) if getattr(module, "__file__", None)
        )
        for pattern in ("gz/**/*.so", "gz/**/*.py", "sdformat14*.so"):
            roots.extend(Path("/usr/lib/python3/dist-packages").glob(pattern))
        add("runtime:installed-roots", roots)
        add("graph:dependencies", dependencies(roots, contract["agent"]["configuration"]["lib_dir"], sdk))
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
            [FOLDER / "wire-config.json", FOLDER / "agent-runtime.json", FOLDER / "agent-deployment.json", CATALOG, AGENT],
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
        graph_client = QueryClient(resolver, ROOT, query_env, FOLDER / "graph-queries")
        (FOLDER / "graph-queries").mkdir()
        graph_context = graph_client.query("context")
        graph = build_graph(capture / "world.sdf", graph_client, pre["files"], FOLDER / "graph-queries")
        after = snapshot(proof_inventory)
        pre["resource_graph"] = graph
        preparation = dict(
            schema="raw-static-sdk-preparation-v1",
            binding_sha256=hashlib.sha256((FOLDER / "runtime-binding-v4.json").read_bytes()).hexdigest(),
            execution_sha256=hashlib.sha256((FOLDER / "execution-contract.json").read_bytes()).hexdigest(),
            pre=pre,
            after_queries=after,
            graph=graph,
            context=graph_context,
            queries=[json.loads(p.read_text()) for p in sorted((FOLDER / "graph-queries").glob("resource-query-*.json"))],
            documents_hex={row["source"]: Path(row["source"]).read_bytes().hex() for row in graph["documents"]},
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
        audit_preparation(binding, preparation)
        write_manifest(FOLDER / "preparation.json", preparation)
        result = publish_study(FOLDER)
        write_manifest(parent / "native-freeze-result.json", result)
        return result
    except Exception as exc:
        write_manifest(parent / "native-freeze-failure.json", dict(error=repr(exc), folder=str(FOLDER), qualification=False))
        raise
    finally:
        write_manifest(
            parent / "sdk-inside-after.json",
            dict(
                cgroup=str(cg),
                limits={
                    name: (cg / name).read_text().strip() for name in ("memory.max", "memory.swap.max", "cpu.max", "pids.max")
                },
                memory_events=(cg / "memory.events").read_text(),
                memory_peak=(cg / "memory.peak").read_text() if (cg / "memory.peak").exists() else None,
                qualification=False,
            ),
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true", required=True)
    parser.add_argument("--unit", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.unit)))


if __name__ == "__main__":
    main()
