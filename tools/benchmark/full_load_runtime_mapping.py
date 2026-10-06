"""Prospective contracts for one full-load runtime mapping study."""

from __future__ import annotations

import copy
import glob
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

from tools.benchmark.capture_contract import declared_command, execution_contract, read_declaration
from tools.benchmark.declared_runtime_snapshot import file_record, parse_ldd, snapshot, write_manifest
from tools.benchmark.native_resource_client import QUERY_ENV_KEYS
from tools.benchmark.runtime_resource_binding import ENV_KEYS, GENERATED_NAMES

SCENE_NAMES = tuple(name for name in GENERATED_NAMES if name != "gz_env.sh")
RUNTIME_MAPS = dict(
    self_phases=["postimports", "postfinalize", "postfirststep"],
    owned_roles={"px4": ["ready", "prestop"], "openvins": ["ready", "prestop"]},
    max_maps_bytes=8 * 1024 * 1024,
    max_observations=16,
)
LAZY_PATTERNS = {
    "physics-dartsim": "/usr/lib/x86_64-linux-gnu/gz-physics-7/engine-plugins/libgz-physics7-dartsim-plugin.so.*",
    "renderer-ogre2": "/usr/lib/x86_64-linux-gnu/gz-rendering-8/engine-plugins/libgz-rendering8-ogre2.so.*",
    "sensor-base": "/usr/lib/x86_64-linux-gnu/libgz-sensors8.so.8.*",
    "sensor-rendering": "/usr/lib/x86_64-linux-gnu/libgz-sensors8-rendering.so.8.*",
    "sensor-rgbd": "/usr/lib/x86_64-linux-gnu/libgz-sensors8-rgbd_camera.so.8.*",
    "sensor-camera": "/usr/lib/x86_64-linux-gnu/libgz-sensors8-camera.so.8.*",
    "sensor-depth": "/usr/lib/x86_64-linux-gnu/libgz-sensors8-depth_camera.so.8.*",
    "sensor-imu": "/usr/lib/x86_64-linux-gnu/libgz-sensors8-imu.so.8.*",
    "sensor-magnetometer": "/usr/lib/x86_64-linux-gnu/libgz-sensors8-magnetometer.so.8.*",
    "sensor-navsat": "/usr/lib/x86_64-linux-gnu/libgz-sensors8-navsat.so.8.*",
    "sensor-air-pressure": "/usr/lib/x86_64-linux-gnu/libgz-sensors8-air_pressure.so.8.*",
}


def select_unique_candidate(reason, candidates):
    if type(reason) is not str or not reason:
        raise ValueError("selection reason required")
    lexical = [str(Path(path).absolute()) for path in candidates]
    selected = {}
    for path in lexical:
        candidate = Path(path)
        if candidate.is_file():
            resolved = str(candidate.resolve(strict=True))
            selected.setdefault(resolved, []).append(path)
    if len(selected) != 1:
        raise ValueError(f"{reason} requires one canonical candidate, found {len(selected)}")
    canonical = next(iter(selected))
    return dict(selection_reason=reason, candidates=lexical, selected=canonical,
                aliases=selected[canonical], identity=file_record(canonical))


def ldd_closure(roots, *, runner=subprocess.run, parser=parse_ldd):
    if type(roots) is not list or not roots:
        raise ValueError("runtime roots required")
    root_paths = sorted({row["selected"] for row in roots})
    dependencies = {}
    commands = []
    for root in root_paths:
        before = file_record(root)
        command = ["/usr/bin/ldd", root]
        completed = runner(command, capture_output=True, text=True, timeout=10)
        record = dict(command=command, returncode=completed.returncode,
                      stdout=completed.stdout, stderr=completed.stderr)
        commands.append(record)
        resolved = parser(completed.stdout, completed.returncode)
        after = file_record(root)
        if before != after:
            raise ValueError("runtime root changed during ldd")
        for path in resolved:
            row = file_record(path)
            dependencies[row["resolved"]] = row
    return dict(roots=root_paths, dependencies=sorted(dependencies),
                dependency_records=[dependencies[path] for path in sorted(dependencies)], commands=commands)


def runtime_inventory(roots, closure):
    if type(roots) is not list or type(closure) is not dict:
        raise ValueError("runtime inventory inputs")
    inventory = {}
    selected = set()
    for row in sorted(roots, key=lambda item: item["selection_reason"]):
        role = "runtime-root:" + row["selection_reason"]
        path = row["selected"]
        if role in inventory or path in selected:
            raise ValueError("duplicate runtime root role or canonical path")
        selected.add(path)
        inventory[role] = [path]
    dependencies = [path for path in closure["dependencies"] if path not in selected]
    if len(dependencies) != len(set(dependencies)):
        raise ValueError("duplicate runtime dependency")
    if dependencies:
        inventory["runtime:dependencies"] = sorted(dependencies)
    return inventory


def generated_hashes(archive, expected_sha256, prefix, gz_env):
    archive = Path(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("scene archive hash mismatch")
    result = {}
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        for name in SCENE_NAMES:
            member = prefix + name
            if names.count(member) != 1:
                raise ValueError("scene archive member missing or duplicated")
            result[name] = hashlib.sha256(bundle.read(member)).hexdigest()
    result["gz_env.sh"] = hashlib.sha256(Path(gz_env).read_bytes()).hexdigest()
    return result


def merge_binding(base, additions, generated):
    if type(base) is not dict or base.get("schema") != "capture-resource-binding-v2":
        raise ValueError("sealed v2 resource binding required")
    if set(generated) != set(GENERATED_NAMES):
        raise ValueError("complete generated hashes required")
    inventory = copy.deepcopy(base["inventory"])
    canonical = {str(Path(path).resolve(strict=True)): role
                 for role, paths in inventory.items() for path in paths}
    overlaps, added = [], []
    for role in sorted(additions):
        if role in inventory:
            raise ValueError("runtime role collides with sealed resource role")
        kept = []
        for path in additions[role]:
            resolved = str(Path(path).resolve(strict=True))
            if resolved in canonical:
                overlaps.append(resolved)
            else:
                canonical[resolved] = role
                kept.append(resolved)
                added.append(resolved)
        if kept:
            inventory[role] = kept
    doc = copy.deepcopy(base)
    doc.update(schema="capture-resource-binding-v3", inventory=inventory,
               baseline=snapshot(inventory),
               generated=copy.deepcopy(generated), runtime_maps=copy.deepcopy(RUNTIME_MAPS))
    return doc, dict(overlaps=sorted(set(overlaps)), added=added,
                     base_paths=sum(len(paths) for paths in base["inventory"].values()),
                     final_paths=sum(len(paths) for paths in inventory.values()))


def study_args(output, shadow_binary, shadow_config, reference_module, reference_sha256):
    output = Path(output)
    return SimpleNamespace(
        output=output,
        shadow_binary=Path(shadow_binary), shadow_config=Path(shadow_config),
        reference_module=Path(reference_module), reference_sha256=reference_sha256,
        reference_fault_profile=None, source_fanout_profile="ready-shadow-heartbeat-v1",
        motion_profile="supported-ready-v1", physics_trace_profile="substep-ready-v1",
        execution_contract=None, runtime_binding=output.parent / "runtime-binding-v3.json",
    )


def declared_study_command(args, python, capture_script):
    return declared_command(args, python, capture_script)


def ensure_prepare_allowed(output, resources):
    if resources:
        raise ValueError("competing resources present")
    output = Path(output)
    if output.exists():
        raise FileExistsError(str(output))
    return True


def _reason(value):
    return re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")


def imported_extension_roots():
    import gz.math7  # noqa: F401
    from gz.msgs10.camera_info_pb2 import CameraInfo  # noqa: F401
    from gz.msgs10.image_pb2 import Image  # noqa: F401
    from gz.msgs10.imu_pb2 import IMU  # noqa: F401
    from gz.sim8 import TestFixture  # noqa: F401
    from gz.transport13 import Node  # noqa: F401
    from pymavlink import mavutil  # noqa: F401

    rows = []
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, "__file__", None)
        if path and (path.endswith(".so") or ".so." in path):
            rows.append(select_unique_candidate("python-" + _reason(name), [path]))
    return rows


def project_input_paths(root):
    from tools.benchmark import capture_disarmed_sensors  # noqa: F401
    from tools.benchmark.runtime_resource_binding import estimator_inputs  # noqa: F401

    root = Path(root).resolve()
    paths = []
    for module in tuple(sys.modules.values()):
        value = getattr(module, "__file__", None)
        if value:
            path = Path(value).resolve()
            if path.is_file() and path.is_relative_to(root):
                paths.append(str(path))
    return sorted(set(paths))


def select_runtime_roots(base, *, python, px4, openvins, reference, extensions=None,
                         patterns=LAZY_PATTERNS, globber=glob.glob):
    rows = [
        select_unique_candidate("python", [python]),
        select_unique_candidate("px4", [px4]),
        select_unique_candidate("openvins", [openvins]),
        select_unique_candidate("native-reference", [reference]),
    ]
    for path in base["inventory"].get("declared:resources", []):
        if ".so" in Path(path).name:
            rows.append(select_unique_candidate("gazebo-system-" + _reason(Path(path).name), [path]))
    rows.extend(imported_extension_roots() if extensions is None else extensions)
    for reason, pattern in patterns.items():
        rows.append(select_unique_candidate(reason, sorted(globber(pattern))))
    unique = {}
    aliases = {}
    for row in rows:
        selected = row["selected"]
        if selected in unique:
            aliases.setdefault(selected, [unique[selected]["selection_reason"]]).append(row["selection_reason"])
        else:
            unique[selected] = row
    return [unique[path] for path in sorted(unique)], aliases


def package_owners(roots, *, runner=subprocess.run):
    rows = []
    for row in roots:
        path = row["selected"]
        if not path.startswith("/usr/"):
            rows.append(dict(path=path, owner=None, version=None, source="local-explicit"))
            continue
        owner = runner(["/usr/bin/dpkg-query", "-S", path], capture_output=True, text=True, timeout=10)
        if owner.returncode != 0 or not owner.stdout.strip() or ": " not in owner.stdout:
            raise ValueError("installed runtime root has no package owner: " + path)
        package = owner.stdout.split(": ", 1)[0].split(",", 1)[0]
        version = runner(["/usr/bin/dpkg-query", "-W", "-f=${Version}", package],
                         capture_output=True, text=True, timeout=10)
        if version.returncode != 0 or not version.stdout.strip():
            raise ValueError("runtime root package version unavailable: " + package)
        rows.append(dict(path=path, owner=package, version=version.stdout.strip(), source="dpkg-query"))
    return rows


def prepare_study(output, *, base_binding, base_binding_sha256, scene_archive, scene_archive_sha256,
                  scene_prefix, gz_env, px4, shadow_binary, shadow_config, reference_module,
                  reference_sha256, capture_script, resources, python=sys.executable):
    ensure_prepare_allowed(output, resources)
    output = Path(output)
    output.mkdir(parents=True)
    base_path = Path(base_binding)
    if hashlib.sha256(base_path.read_bytes()).hexdigest() != base_binding_sha256:
        raise ValueError("sealed resource binding hash mismatch")
    base = read_declaration(base_path)
    roots, aliases = select_runtime_roots(
        base, python=python, px4=px4, openvins=shadow_binary, reference=reference_module)
    closure = ldd_closure(roots)
    additions = runtime_inventory(roots, closure)
    additions["runtime:project-inputs"] = project_input_paths(Path(__file__).resolve().parents[2])
    config = Path(shadow_config)
    from tools.benchmark.runtime_resource_binding import estimator_inputs

    additions["runtime:estimator-inputs"] = [str(Path(path).resolve()) for path in
                                               estimator_inputs(shadow_binary, config, reference_module)]
    px4_path = Path(px4)
    px4_root = px4_path.parents[3]
    additions["runtime:px4-startup"] = [str(path.resolve()) for path in (
        px4_path, px4_root / "build/px4_sitl_default/rootfs/gz_env.sh",
        px4_root / "build/px4_sitl_default/etc/init.d-posix/rcS",
        px4_root / "src/modules/simulation/gz_bridge/server.config",
    )]
    hashes = generated_hashes(scene_archive, scene_archive_sha256, scene_prefix, gz_env)
    binding, merge = merge_binding(base, additions, hashes)
    args = study_args(output / "capture-v1", shadow_binary, shadow_config, reference_module, reference_sha256)
    contract = execution_contract(args)
    contract_path = output / "execution-contract.json"
    binding_path = output / "runtime-binding-v3.json"
    args.execution_contract, args.runtime_binding = contract_path, binding_path
    write_manifest(contract_path, contract)
    write_manifest(binding_path, binding)
    command = declared_study_command(args, python, capture_script)
    manifest = dict(
        schema="full-load-runtime-mapping-study-v1", prepare_only=True,
        command=command, base_binding=str(base_path.resolve()), base_binding_sha256=base_binding_sha256,
        scene_archive=str(Path(scene_archive).resolve()), scene_archive_sha256=scene_archive_sha256,
        runtime_roots=roots, root_aliases=aliases, package_owners=package_owners(roots),
        ldd=closure, merge=merge, execution_contract=contract,
        runtime_mapping_coverage_verified=False, runtime_closure_qualified=False,
        vio_accuracy_qualified=False, estimator_health_qualified=False,
        fusion_eligible=False, flight_ready=False,
    )
    write_manifest(output / "study-manifest.json", manifest)
    return manifest


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--base-binding", required=True, type=Path)
    parser.add_argument("--base-binding-sha256", required=True)
    parser.add_argument("--scene-archive", required=True, type=Path)
    parser.add_argument("--scene-archive-sha256", required=True)
    parser.add_argument("--scene-prefix", required=True)
    parser.add_argument("--gz-env", required=True, type=Path)
    parser.add_argument("--px4", required=True, type=Path)
    parser.add_argument("--shadow-binary", required=True, type=Path)
    parser.add_argument("--shadow-config", required=True, type=Path)
    parser.add_argument("--reference-module", required=True, type=Path)
    parser.add_argument("--reference-sha256", required=True)
    parser.add_argument("--capture-script", required=True, type=Path)
    parser.add_argument("--prepare-only", action="store_true", required=True)
    args = parser.parse_args(argv)
    from tools.benchmark.capture_disarmed_sensors import active_resources

    result = prepare_study(
        args.output, base_binding=args.base_binding, base_binding_sha256=args.base_binding_sha256,
        scene_archive=args.scene_archive, scene_archive_sha256=args.scene_archive_sha256,
        scene_prefix=args.scene_prefix, gz_env=args.gz_env, px4=args.px4,
        shadow_binary=args.shadow_binary, shadow_config=args.shadow_config,
        reference_module=args.reference_module, reference_sha256=args.reference_sha256,
        capture_script=args.capture_script, resources=active_resources())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()


__all__ = [
    "ENV_KEYS", "GENERATED_NAMES", "QUERY_ENV_KEYS", "RUNTIME_MAPS", "SCENE_NAMES",
    "declared_study_command", "ensure_prepare_allowed", "execution_contract", "generated_hashes",
    "ldd_closure", "merge_binding", "prepare_study", "runtime_inventory", "select_runtime_roots",
    "select_unique_candidate", "study_args",
]
