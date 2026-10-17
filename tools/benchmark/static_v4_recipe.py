"""Fixed Windows recipe request producer. A request is never a native prepin."""


def build_fixed_request():
    import ast
    import hashlib
    import json
    import sys
    import zipfile
    from pathlib import Path

    from tools.benchmark.static_v4_identity import strict_path

    if sys.platform != "win32":
        raise ValueError("prospective request builder requires Windows;not native observer")
    root = Path(__file__).resolve().parents[2]
    native = "/mnt/" + root.drive[0].lower() + root.as_posix()[2:]

    def path(relative):
        return native + "/" + relative

    def read(relative):
        return (root / relative).read_bytes()

    def digest(data):
        return hashlib.sha256(data).hexdigest()

    def record(relative, expected=None):
        file = root / relative
        before = file.stat()
        h = hashlib.sha256()
        count = 0
        with file.open("rb") as stream:
            while data := stream.read(65536):
                count += len(data)
                h.update(data)
        after = file.stat()
        fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, k) != getattr(after, k) for k in fields) or count != after.st_size:
            raise ValueError("prospective bytes changed")
        result = dict(bytes=count, sha256=h.hexdigest())
        if expected is not None and result != expected:
            raise ValueError("fixed original input bytes changed: " + relative)
        return result

    sources = [root / "results/target-bearing-runtime-freeze-v4-dev-1701/run-static-preparation-v4.py"]
    for scope in ("src/flydrones", "tools/benchmark", "tools/connectome"):
        sources.extend(p for p in (root / scope).rglob("*.py") if "__pycache__" not in p.parts)
    source_sha = {p.relative_to(root).as_posix(): record(p.relative_to(root).as_posix())["sha256"] for p in sorted(set(sources))}
    scene = "results/target-bearing-scene-production-dev-1701/actual-scene-v3"
    manifest = read(scene + "/manifest.json")
    if digest(manifest) != "0a66c427e1d9d7d9de1557d46bfb12a04398e27b467e4acc246240f5d06c6da4":
        raise ValueError("sealed scene manifest changed")
    rows = json.loads(manifest)["files"]
    if len(rows) != 44:
        raise ValueError("original scene membership count changed")
    if {p.relative_to(root / scene).as_posix() for p in (root / scene).rglob("*") if p.is_file()} != set(rows) | {
        "manifest.json"
    }:
        raise ValueError("original scene exact membership changed")
    expected = {path(scene + "/" + name): record(scene + "/" + name, value) for name, value in rows.items()}
    expected[path(scene + "/manifest.json")] = record(scene + "/manifest.json")
    config_name = "results/target-bearing-runtime-freeze-dev-1701/frozen-study-v1/agent-runtime.json"
    deployment_name = "results/target-bearing-runtime-freeze-dev-1701/frozen-study-v1/agent-deployment.json"
    config = json.loads(read(config_name))
    deployment = json.loads(read(deployment_name))
    if config["schema"] != "capture-agent-runtime-v1" or config["port"] != 18888:
        raise ValueError("original Agent configuration changed")
    # Constants are read as source data; no old runtime module import or execution.
    constants = {}
    for node in ast.parse(read("tools/benchmark/agent_capture_runtime.py")).body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in ("BUNDLE_SHA256", "AGENT_SHA256", "LIBRARY_SHA256")
        ):
            constants[node.targets[0].id] = ast.literal_eval(node.value)
    member_sha = {
        "bin/MicroXRCEAgent": constants["AGENT_SHA256"],
        **{"lib/" + k: v for k, v in constants["LIBRARY_SHA256"].items()},
    }
    members = {r["member"]: r["deployed"] for r in deployment["members"]}
    if len(members) != 14 or len(deployment["members"]) != 14 or set(members) != set(member_sha):
        raise ValueError("original14 Agent membership changed")
    agent_root = path("results/target-bearing-runtime-freeze-dev-1701/frozen-study-v1/agent-deployment-v1")
    if config["binary"] != agent_root + "/bin/MicroXRCEAgent" or config["lib_dir"] != agent_root + "/lib":
        raise ValueError("literal Agent cache paths changed")
    for member, sha in member_sha.items():
        selected = agent_root + "/" + member
        if members[member]["requested"] != selected or members[member]["sha256"] != sha:
            raise ValueError("Agent original byte pin changed")
        expected[selected] = record(selected.removeprefix(native + "/"), dict(bytes=members[member]["bytes"], sha256=sha))
    bundle = "results/agent-offline-build-dev-1701/runtime-bundle.tar.gz"
    if config["bundle"] != path(bundle):
        raise ValueError("Agent original bundle path changed")
    expected[path(bundle)] = record(bundle, dict(bytes=5940628, sha256=constants["BUNDLE_SHA256"]))
    historical = "evidence/static-v3-harness-failure-dev-1701.zip"
    if record(historical)["sha256"] != "9368f59c76e9fde2833b693321d2f91896e8ff6d7dc5387679296135c64df7b5":
        raise ValueError("retained path source archive changed")
    retained_name = "results/target-bearing-runtime-freeze-v3-dev-1701/frozen-study-v3/sdk/entry-dependencies/entry-bill.json"
    with zipfile.ZipFile(root / historical) as archive:
        retained = archive.read(retained_name)
    if read(retained_name) != retained:
        raise ValueError("retained lexical path candidates differ")
    bill = json.loads(retained)
    if len(bill["files"]) != 463 or len(bill["input_candidates"]) != 145 or bill["complete"] is not False:
        raise ValueError("retained partial scope changed")
    candidate_paths = sorted({r["requested"] for r in bill["files"]} | set(bill["input_candidates"]))
    tools = [
        "/usr/bin/sha256sum",
        "/usr/bin/python3",
        "/usr/bin/ldd",
        "/usr/bin/readelf",
        "/lib64/ld-linux-x86-64.so.2",
        "/usr/bin/systemctl",
        "/usr/bin/systemd-run",
        "/usr/bin/env",
        "/usr/bin/timeout",
        "/usr/bin/dpkg-query",
        "/usr/bin/time",
    ]
    groups = {
        "project-source": [path(n) for n in source_sha],
        "sealed-scene": sorted(k for k in expected if k.startswith(path(scene) + "/")),
        "agent-cache": sorted(agent_root + "/" + n for n in member_sha),
        "agent-bundle": [path(bundle)],
        "agent-metadata": [
            path(config_name),
            path(deployment_name),
            path("results/agent-capture-contract-dev-1701/agent-runtime.json"),
        ],
        "native-candidates": candidate_paths,
        "catalog": [
            path("results/declared-launch-environment-dev-1701/dry-v1/runtime-binding-v3.json"),
            path(historical),
            path(retained_name),
        ],
        "tools": tools,
        "project-inputs": [
            path(n)
            for n in (
                "tools/benchmark/native/resource_resolver.cc",
                "tools/benchmark/native/local_candidates.hh",
                "config/px4/source-diagnostic-v1/logger_topics.txt",
                "config/px4/source-diagnostic-v1/profile.json",
                "LICENSE",
            )
        ],
        "px4-inputs": [
            "/home/yuchen7509/PX4-Autopilot/" + n
            for n in (
                "build/px4_sitl_default/rootfs/gz_env.sh",
                "build/px4_sitl_default/etc/init.d-posix/rcS",
                "src/modules/simulation/gz_bridge/server.config",
                "Tools/simulation/gz/models/x500/model.sdf",
                "Tools/simulation/gz/models/x500_base/model.sdf",
                "LICENSE",
            )
        ],
        "original-models": sorted(
            path(p.relative_to(root).as_posix())
            for name in ("x500_benchmark", "OakD-Benchmark")
            for p in (root / "assets/gazebo/models" / name).rglob("*")
            if p.is_file()
        ),
    }
    for name in (
        config_name,
        deployment_name,
        "results/agent-capture-contract-dev-1701/agent-runtime.json",
        "results/declared-launch-environment-dev-1701/dry-v1/runtime-binding-v3.json",
        historical,
        retained_name,
        *[v.removeprefix(native + "/") for v in groups["project-inputs"] + groups["original-models"]],
    ):
        expected[path(name)] = record(name)
    for values in groups.values():
        for selected in values:
            strict_path(selected)
    protocol = dict(
        schema="fixed-installed-metadata-protocol-v4",
        distributions=["numpy", "scipy", "pyulog", "pymavlink", "protobuf"],
        roots=[
            "/usr/lib/python3/dist-packages",
            "/usr/local/lib/python3.12/dist-packages",
            "/home/yuchen7509/.local/lib/python3.12/site-packages",
        ],
        package_database="/var/lib/dpkg/status",
        owner_tool="/usr/bin/dpkg-query",
        notices_root="/usr/share/doc",
        required_notice="copyright",
        transitive_license_certified=False,
    )
    return dict(
        schema="static-recipe-request-v4",
        source_root=native,
        source_sha256=source_sha,
        coverage=groups,
        files=sorted({selected for values in groups.values() for selected in values}),
        expected_bytes=expected,
        metadata_protocol=protocol,
        native_preidentity_observed=False,
        scene_copied=False,
        nonce="0" * 64,
        unit="fly-calibration-prepare-" + "0" * 24 + ".scope",
        sdk_environment=dict(
            HOME="/home/yuchen7509",
            PATH="/usr/bin:/bin",
            LANG="C.UTF-8",
            PYTHONPATH=native + "/src:" + native,
            OPENBLAS_NUM_THREADS="1",
            OMP_NUM_THREADS="1",
        ),
        static_limits={"memory.max": "536870912", "memory.swap.max": "0", "cpu.max": "100000 100000", "pids.max": "64"},
        versions=[[p, "--version"] for p in tools],
    )


def audit_recipe_request(request):
    # Fresh literal data and full current code reconstruct the expected request.
    # This is a prospective Windows declaration check, never native authority.
    if request != build_fixed_request():
        raise ValueError("exact fixed recipe request/source/input coverage differs")
    return request


if __name__ == "__main__":
    raise SystemExit("no recipe CLI or native dispatch")
