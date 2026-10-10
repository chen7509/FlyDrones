"""Complete synthetic file composition, never a launch or physical producer.

Declarations, process/maps/dispatch observations and ULog samples are synthetic.
Real file identities, encoders, policies, bounded readers and auditors are used.
The tiny assets are not the installed scene; passing this fixture cannot attest
actual runtime load or authorize the prospective experiment.
"""

import copy
import hashlib
import json
import os
import stat
from pathlib import Path

from tests.benchmark.live_wire_joined_fixture import add_joined_sources, build_joined_wire_physics, read_joined_fixture
from tests.benchmark.live_wire_motion_fixture import write_lines
from tests.benchmark.live_wire_study_fixture import fixture, write
from tests.benchmark.test_live_wire_ulog_audit import raw_log
from tests.benchmark.test_openvins_wire_bootstrap import OWNER
from tools.benchmark.bound_resource_graph import build_graph
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot
from tools.benchmark.runtime_resource_binding import GENERATED_NAMES


def _runtime(capture, declaration, root, owner):
    """Retain synthetic lifecycle observations around real tiny-file identities."""
    generated = {}
    for name in GENERATED_NAMES:
        target = capture / name
        with target.open("xb") as stream:
            stream.write((root / name).read_bytes())
        generated[name] = [str(target)]
    generated_snapshot = snapshot(generated)
    selected = copy.deepcopy(declaration["inventory"])
    selected.update({"generated:" + role: paths for role, paths in generated.items()})
    pre = snapshot(selected)
    pre.update(
        declaration=copy.deepcopy(declaration),
        generated=generated_snapshot,
        environment=copy.deepcopy(declaration["environment"]),
    )

    class NoEdgeClient:
        def check_budget(self):
            return 0.0

        def query(self, *args):
            raise AssertionError("the explicit minimal synthetic world has no resource edges")

    graph = build_graph(capture / "world.sdf", NoEdgeClient(), pre["files"], capture)
    pre["resource_graph"] = graph
    context = declaration["graph"]["expected_context"]
    response = json.dumps(context)
    query = dict(
        command=[declaration["inventory"]["graph:resolver"][0], "context"],
        cwd=declaration["graph"]["cwd"],
        environment=declaration["graph"]["environment"],
        started_monotonic=0.0,
        ended_monotonic=0.0,
        stdout=response,
        stdout_hex=response.encode().hex(),
        stderr="",
        stderr_hex="",
        returncode=0,
        error=None,
        output_limit_exceeded=False,
        collection_errors=[],
    )
    write(capture / "resource-search-context.json", context)
    write(capture / "resource-query-0000.json", query)
    write(capture / "runtime-binding-pre.json", pre)
    write(capture / "runtime-binding-after-queries.json", snapshot(selected))
    write(capture / "runtime-binding-post.json", snapshot(selected))
    maps, owners = {}, {}
    phases = ["postgraph", "bootstrap", *declaration["runtime_maps"]["self_phases"]]
    rows = {row["role"]: row for row in pre["files"] if row["role"].startswith("runtime-root:")}

    def mapped(role):
        row = rows["runtime-root:" + role]
        identity = row["identity"]
        dev = f"{os.major(identity['device']):02x}:{os.minor(identity['device']):02x}"
        return f"1000-2000 r-xp 0000 {dev} {identity['inode']} {row['resolved']}\n"

    for phase in phases:
        maps["runtime-maps-" + phase] = dict(
            raw=mapped("px4"),
            summary=dict(
                phase=phase,
                unknown=[],
                mismatched=[],
                parse_error=None,
                observed_files_covered=True,
                runtime_closure_qualified=False,
            ),
        )
    for role, pid, ticks in (("px4", 321, 7), ("openvins", 322, 8)):
        identity = dict(
            pid=pid,
            pgrp=owner["pgrp"],
            session=owner["session"],
            start_ticks=ticks,
            state="R",
            executable=rows["runtime-root:" + role]["resolved"],
        )
        owners[role] = dict(identity, role=role)
        write(capture / ("runtime-owner-" + role + ".json"), owners[role])
        for phase in ("ready", "prestop"):
            maps[f"runtime-maps-{role}-{phase}"] = dict(
                raw=mapped(role),
                summary=dict(
                    role=role,
                    phase=phase,
                    observed_files_covered=True,
                    error=None,
                    identity_before=identity,
                    identity_after=dict(identity, state="S"),
                    unknown=[],
                    mismatched=[],
                ),
            )
    for name, pair in maps.items():
        (capture / (name + ".txt")).write_text(pair["raw"])
        write(capture / (name + ".json"), pair["summary"])
    write(
        capture / "process.json",
        dict(
            pid=owner["pid"],
            args=[declaration["inventory"]["runtime-root:px4"][0], "-i", "8", "-d", str(root / "etc")],
            started_wall_ns=1,
        ),
    )
    return dict(
        pre_recorded=True,
        declared_files_stable=True,
        local_file_graph_verified=True,
        phases=phases,
        owned_phases=declaration["runtime_maps"]["owned_roles"],
        runtime_mapping_coverage_verified=True,
        errors=[],
        runtime_closure_qualified=False,
        scope="declared self and registered owned phases only; whole runtime not qualified",
    )


def _supervisor(capture):
    owner = dict(pid=300, pgrp=300, session=300, start_ticks=2, state="R")
    empty = dict(members=[], executing=[], errors=[], vanished=[])
    pinned = dict(empty, members=[dict(owner, state="Z")])
    events = [
        dict(event="ownership", owner=owner, unreaped_until_cleanup=True),
        dict(event="leader_exit_unreaped", pid=300, code=1, status=0),
        dict(event="snapshot", label="before_signals", observation=pinned),
        dict(event="snapshot", label="confirm_drained", observation=pinned),
        dict(event="snapshot", label="after_signals", observation=pinned),
        dict(event="leader_reaped", returncode=0),
        dict(event="snapshot", label="after_leader_reap", observation=empty),
    ]
    for index, event in enumerate(events):
        event["monotonic_s"] = 13.0 + index / 10
    cleanup = dict(
        owner=owner,
        events=events,
        errors=[],
        final_snapshot=empty,
        no_executing_members=True,
        group_absent=True,
        sigkill_dispatched=False,
        graceful_group_cleanup_verified=True,
        all_descendant_cleanup_qualified=False,
    )
    write(
        capture / "supervisor.json",
        dict(
            status="worker_exited",
            worker_pid=300,
            worker_exit=0,
            timeout_s=300,
            capture_status="capture_completed",
            errors=[],
            cleanup=cleanup,
        ),
    )
    write_lines(capture.parent, capture.name + ".supervisor-events.jsonl", events)


def build_complete_fixture(root):
    root = root.resolve()
    manifest, docs, path = fixture(root)
    capture = Path(manifest["outputs"]["capture"])
    px4 = Path(docs["binding"]["inventory"]["runtime-root:px4"][0])
    exe_stat, cwd_stat = px4.stat(), root.stat()
    owner = dict(
        OWNER,
        pgrp=300,
        session=300,
        exe=str(px4),
        exe_device=exe_stat.st_dev,
        exe_inode=exe_stat.st_ino,
        cwd=str(root),
        cwd_device=cwd_stat.st_dev,
        cwd_inode=cwd_stat.st_ino,
    )
    generated = build_joined_wire_physics(capture, owner=owner)
    add_joined_sources(generated, initialized_at_ns=1_200_000_000)
    del generated
    e = read_joined_fixture(capture)
    session = json.loads((capture / "synthetic-wire-session.json").read_text())
    lifecycle = dict(
        failure=None,
        fusion_qualified=False,
        network_authorized=False,
        session=session,
        driver=dict(phase="closed", closed=True, failure=None, ready=False, fusion_qualified=False, network_authorized=False),
    )
    write(capture / "wire-lifecycle.json", lifecycle)
    write(
        capture / "wire-owner.json",
        dict(
            owner=owner,
            descriptor=dict(fd=8, device=5, inode=300, mode=stat.S_IFSOCK | 0o777, net=owner["net"]),
            configuration=docs["wire_config"],
            start_ns=10,
            total_deadline_ns=300_000_000_010,
        ),
    )
    runtime = _runtime(capture, docs["binding"], root, owner)
    _supervisor(capture)
    for original, target in (
        ("shadow/synthetic-fast-state.jsonl", "shadow/fast.jsonl"),
        ("shadow/synthetic-readiness-anchor.json", "readiness-anchor.json"),
        ("shadow/synthetic-motion-intent.jsonl", "motion-intent.jsonl"),
        ("shadow/synthetic-forces.jsonl", "motion-force.jsonl"),
        ("shadow/synthetic-heartbeat-observation.jsonl", "heartbeat-observations.jsonl"),
        ("shadow/estimator-readiness.jsonl", "estimator-readiness.jsonl"),
    ):
        with (capture / target).open("xb") as stream:
            stream.write((capture / original).read_bytes())
    write(capture / "motion-profile.json", e["motion"]["profile"])
    write(
        capture / "shadow/native-session.json",
        dict(
            pid=322,
            command=[
                docs["execution"]["inputs"]["shadow_binary"],
                docs["execution"]["inputs"]["shadow_config"],
                str(capture / "shadow/states.jsonl"),
                str(capture / "shadow/fast.jsonl"),
            ],
        ),
    )
    # Analytic binary ULog, parsed by the installed pyulog. Its two samples are
    # only a format/identity/unarmed check, not 25-second physical coverage.
    log = raw_log()
    entry = dict(path="px4-ulog/log/synthetic.ulg", bytes=len(log), sha256=hashlib.sha256(log).hexdigest(), valid_header=True)
    log_path = capture / entry["path"]
    log_path.parent.mkdir(parents=True)
    log_path.write_bytes(log)
    write(capture / "px4-ulog-manifest.json", dict(schema="flydrones-px4-ulog-capture-v1", logs=[entry]))
    write(
        capture / "result.json",
        dict(
            status="capture_completed",
            errors=[],
            estimator_run=True,
            end_sim_ns=25_000_000_000,
            eligible_for_px4_fusion=False,
            px4_exit_code=0,
            wire_lifecycle=lifecycle,
            runtime_binding=runtime,
            native_reference=e["physical"]["terminal"],
            physics_trace=e["physical"]["trace_terminal"],
            source_health=e["source_health"]["terminal"],
            motion=e["motion"]["motion_terminal"],
            motion_intent=e["motion"]["intent_terminal"],
            px4_ulogs=[entry],
        ),
    )
    # The following envelopes are simulated producer records. Their booleans
    # do not change the sidecar's explicit no-execution/no-authority boundary.
    write(
        Path(manifest["outputs"]["dispatch"]),
        dict(
            schema="live-wire-study-dispatch-v1",
            study_manifest=file_record(path),
            run_id=manifest["study_id"],
            role="development",
            seed=27601,
            destination=str(capture),
            command=manifest["command"],
            resources_before=[],
            single_actual_attempt=True,
            physical_run=True,
            fusion_eligible=False,
            started_wall_ns=1,
        ),
    )
    write(
        Path(manifest["outputs"]["completion"]),
        dict(
            schema="live-wire-study-completion-v1",
            run_id=manifest["study_id"],
            destination=str(capture),
            destination_exists=True,
            command_returncode=0,
            launcher_returncode=0,
            launcher_error=None,
            resources_after=[],
            physical_run=True,
            fusion_eligible=False,
            ended_wall_ns=15_000_000_000,
        ),
    )
    write(
        root / "synthetic-package-provenance.json",
        dict(
            schema="complete-offline-fixture-v1",
            synthetic_provenance=True,
            fake_interfaces=[
                "datagram",
                "daemon",
                "owner",
                "descriptor",
                "dispatch",
                "runtime_maps",
                "SDK_query",
                "native_ack",
                "fast_prediction",
                "physical_state",
                "force_api",
                "supervisor",
                "ULog",
            ],
            minimal_asset_graph=True,
            installed_scene_verified=False,
            physical_state_independent_of_force_commands=True,
            producer_commit_is_placeholder=True,
            native_estimator_run=False,
            physical_execution_qualified=False,
            live_qualified=False,
            fusion_qualified=False,
        ),
    )
    return path, capture
