"""Synthetic retained runtime observations; no process, map or simulator access."""

import copy
import importlib.util

import pytest


def evidence():
    def file(role, path, inode):
        identity = dict(device=1, inode=inode, mode=33188, size=4, mtime_ns=1, ctime_ns=1)
        return dict(
            role=role,
            requested=path,
            resolved=path,
            links=[],
            identity=identity,
            path_identity=identity.copy(),
            bytes=4,
            sha256="a" * 64,
        )

    baseline = [file("runtime-root:px4", "/installed/px4", 10), file("runtime-root:openvins", "/installed/openvins", 11)]
    names = ("world.sdf", "world.json", "ground_albedo.png", "obstacle_albedo.png", "board_albedo.png", "gz_env.sh")
    generated = [file(name, "/capture/" + name, 20 + index) for index, name in enumerate(names)]

    def snapshot(rows, start, end):
        return dict(
            schema="declared-files-v1",
            files=copy.deepcopy(rows),
            started_monotonic_ns=start,
            ended_monotonic_ns=end,
            runtime_closure_qualified=False,
            scope="declared files only; runtime dlopen, environment and atomic snapshot unqualified",
        )

    declaration = dict(
        schema="capture-resource-binding-v3",
        inventory={row["role"]: [row["requested"]] for row in baseline},
        baseline=snapshot(baseline, 1, 2),
        environment={"GZ_SIM_RESOURCE_PATH": "/models"},
        generated={name: "a" * 64 for name in names},
        runtime_maps=dict(
            self_phases=["postimports", "postfinalize", "postfirststep"],
            owned_roles={role: ["ready", "prestop"] for role in ("px4", "openvins")},
            max_maps_bytes=8388608,
            max_observations=16,
        ),
    )
    files = baseline + [dict(row, role="generated:" + row["role"]) for row in generated]
    pre = dict(
        snapshot(files, 5, 6),
        declaration=copy.deepcopy(declaration),
        generated=snapshot(generated, 3, 4),
        environment=declaration["environment"].copy(),
    )
    post = snapshot(files, 100, 101)
    phases = ["postgraph", "bootstrap", *declaration["runtime_maps"]["self_phases"]]
    summary = dict(
        pre_recorded=True,
        declared_files_stable=True,
        local_file_graph_verified=True,
        phases=phases,
        owned_phases=copy.deepcopy(declaration["runtime_maps"]["owned_roles"]),
        runtime_mapping_coverage_verified=True,
        errors=[],
        runtime_closure_qualified=False,
        scope="declared self and registered owned phases only; whole runtime not qualified",
    )
    owners, maps = {}, {}
    for phase in phases:
        maps["runtime-maps-" + phase] = dict(
            raw="1000-2000 r-xp 0000 00:01 10 /installed/px4\n",
            summary=dict(
                phase=phase,
                unknown=[],
                mismatched=[],
                parse_error=None,
                observed_files_covered=True,
                runtime_closure_qualified=False,
            ),
        )
    for index, role in enumerate(("px4", "openvins")):
        identity = dict(pid=321 + index, pgrp=300, session=300, start_ticks=7 + index, state="R", executable="/installed/" + role)
        owners[role] = dict(identity, role=role)
        for phase in ("ready", "prestop"):
            maps["runtime-maps-" + role + "-" + phase] = dict(
                raw=f"1000-2000 r-xp 0000 00:01 {10 + index} /installed/{role}\n",
                summary=dict(
                    role=role,
                    phase=phase,
                    observed_files_covered=True,
                    error=None,
                    identity_before=identity.copy(),
                    identity_after=dict(identity, state="S"),
                    unknown=[],
                    mismatched=[],
                ),
            )
    process = dict(pid=321, args=["/installed/px4", "-i", "8", "-d", "/installed/etc"], started_wall_ns=1)
    return dict(declaration=declaration, pre=pre, post=post, summary=summary, maps=maps, owners=owners, process=process)


def audit(values):
    assert importlib.util.find_spec("tools.benchmark.audit_live_wire_runtime") is not None, "raw runtime audit missing"
    from tools.benchmark.audit_live_wire_runtime import audit_runtime_mapping_records

    return audit_runtime_mapping_records(**values)


def test_complete_raw_maps_recompute_coverage_without_runtime_authority():
    result = audit(evidence())
    assert result["runtime_records_consistent"] is True
    assert result["self_phases"] == 5 and result["owned_phases"] == 4
    assert result["owners"]["px4"]["pid"] == 321
    assert result["runtime_closure_qualified"] is False
    assert result["resource_graph_qualified"] is False
    assert result["live_qualified"] is False and result["fusion_qualified"] is False


@pytest.mark.parametrize(
    "fault",
    [
        "missing_raw",
        "unknown_map",
        "wrong_inode",
        "deleted_map",
        "empty_map",
        "summary_only",
        "map_error",
        "identity_reuse",
        "owner_dead",
        "wrong_exe",
        "process_pid",
        "process_instance",
        "baseline_drift",
        "post_drift",
        "duplicate_file",
        "alias_conflict",
        "missing_generated",
        "generated_hash",
        "generated_copy_drift",
        "missing_phase",
        "extra_phase",
        "phase_summary",
        "post_clock",
        "environment",
        "bool_inode",
        "unknown_role",
        "false_closure",
        "map_too_large",
        "invalid_digest",
        "owned_map_as_self",
        "observation_budget",
    ],
)
def test_success_summaries_do_not_hide_raw_runtime_failures(fault):
    e = evidence()
    px4 = e["maps"]["runtime-maps-px4-ready"]
    if fault == "missing_raw":
        del px4["raw"]
    elif fault == "unknown_map":
        px4["raw"] += "3000-4000 r-xp 0000 00:01 999 /unknown.so\n"
    elif fault == "wrong_inode":
        px4["raw"] = px4["raw"].replace(" 10 ", " 99 ")
    elif fault == "deleted_map":
        px4["raw"] = px4["raw"].replace("px4\n", "px4 (deleted)\n")
    elif fault == "empty_map":
        px4["raw"] = ""
    elif fault == "summary_only":
        e["maps"] = {}
    elif fault == "map_error":
        px4["summary"]["error"] = "permission denied"
    elif fault == "identity_reuse":
        px4["summary"]["identity_after"]["start_ticks"] += 1
    elif fault == "owner_dead":
        e["owners"]["px4"]["state"] = "Z"
    elif fault == "wrong_exe":
        px4["summary"]["identity_after"]["executable"] = "/wrong"
    elif fault == "process_pid":
        e["process"]["pid"] += 1
    elif fault == "process_instance":
        e["process"]["args"][2] = "0"
    elif fault == "baseline_drift":
        e["pre"]["files"][0]["sha256"] = "b" * 64
        e["post"]["files"] = copy.deepcopy(e["pre"]["files"])
    elif fault == "post_drift":
        e["post"]["files"][0]["sha256"] = "b" * 64
    elif fault == "duplicate_file":
        e["pre"]["files"].append(copy.deepcopy(e["pre"]["files"][0]))
        e["post"]["files"] = copy.deepcopy(e["pre"]["files"])
    elif fault == "alias_conflict":
        row = copy.deepcopy(e["pre"]["files"][0])
        row["requested"] = "/alias/px4"
        row["role"] = "bootstrap:selfmaps"
        row["identity"]["inode"] += 1
        e["pre"]["files"].append(row)
        e["post"]["files"] = copy.deepcopy(e["pre"]["files"])
    elif fault == "missing_generated":
        e["pre"]["files"].pop()
        e["post"]["files"] = copy.deepcopy(e["pre"]["files"])
    elif fault == "generated_hash":
        e["pre"]["files"][-1]["sha256"] = "b" * 64
        e["post"]["files"] = copy.deepcopy(e["pre"]["files"])
    elif fault == "generated_copy_drift":
        e["pre"]["generated"]["files"][0]["identity"]["inode"] += 1
    elif fault == "missing_phase":
        del e["maps"]["runtime-maps-postfirststep"]
    elif fault == "extra_phase":
        e["maps"]["runtime-maps-foreign"] = copy.deepcopy(px4)
    elif fault == "phase_summary":
        e["summary"]["phases"].remove("postfirststep")
    elif fault == "post_clock":
        e["post"]["started_monotonic_ns"] = 1
    elif fault == "environment":
        e["pre"]["environment"]["GZ_SIM_RESOURCE_PATH"] = "/other"
    elif fault == "bool_inode":
        e["pre"]["files"][0]["identity"]["inode"] = True
        e["post"]["files"] = copy.deepcopy(e["pre"]["files"])
    elif fault == "unknown_role":
        e["pre"]["files"][0]["role"] = "unfrozen"
        e["post"]["files"] = copy.deepcopy(e["pre"]["files"])
    elif fault == "false_closure":
        e["summary"]["runtime_closure_qualified"] = True
    elif fault == "map_too_large":
        px4["raw"] = " " * (8388608 + 1)
    elif fault == "invalid_digest":
        e["pre"]["files"][0]["sha256"] = "x" * 64
        e["post"]["files"] = copy.deepcopy(e["pre"]["files"])
    elif fault == "owned_map_as_self":
        px4["summary"] = dict(
            phase="px4-ready",
            unknown=[],
            mismatched=[],
            parse_error=None,
            observed_files_covered=True,
            runtime_closure_qualified=False,
        )
    elif fault == "observation_budget":
        e["declaration"]["runtime_maps"]["max_observations"] = 1
        e["pre"]["declaration"] = copy.deepcopy(e["declaration"])
    with pytest.raises(ValueError):
        audit(e)


def normal_supervisor(term=False):
    from tests.benchmark.test_native_supervisor_integration import fixture

    summary, _ = fixture(term)
    summary.update(worker_exit=0, timeout_s=300, capture_status="capture_completed")
    events = summary["cleanup"]["events"]
    next(row for row in events if row["event"] == "leader_exit_unreaped")["status"] = 0
    next(row for row in events if row["event"] == "leader_reaped")["returncode"] = 0
    return summary, copy.deepcopy(events)


@pytest.mark.parametrize("term", [False, True])
def test_existing_cleanup_state_machine_accepts_explicit_normal_profile(term):
    import inspect

    from tools.benchmark.native_supervisor_integration import audit_supervisor

    assert "profile" in inspect.signature(audit_supervisor).parameters, "normal supervisor profile missing"
    summary, journal = normal_supervisor(term)
    result = audit_supervisor(summary, journal, profile="normal-capture-v1")
    assert result["qualified"] and result["capture_status_retained"] == "capture_completed"
    assert result["all_descendant_cleanup_qualified"] is False
    # Explicit opt-in never changes the old fault-study expectation.
    with pytest.raises(ValueError):
        audit_supervisor(summary, journal)


@pytest.mark.parametrize(
    "fault", ["wait_exit", "reap_exit", "timeout", "capture_status", "missing_journal", "live_final", "kill", "unknown_profile"]
)
def test_normal_cleanup_rejects_inconsistent_raw_terminal_evidence(fault):
    from tools.benchmark.native_supervisor_integration import audit_supervisor

    summary, journal = normal_supervisor(True)
    events = summary["cleanup"]["events"]
    if fault == "wait_exit":
        next(row for row in events if row["event"] == "leader_exit_unreaped")["status"] = 2
    elif fault == "reap_exit":
        next(row for row in events if row["event"] == "leader_reaped")["returncode"] = 2
    elif fault == "timeout":
        summary["timeout_s"] = 90
    elif fault == "capture_status":
        summary["capture_status"] = "capture_failed"
    elif fault == "live_final":
        final = events[-1]["observation"]
        final["members"].append(dict(summary["cleanup"]["owner"], pid=999, state="S"))
        final["executing"] = copy.deepcopy(final["members"])
    elif fault == "kill":
        for row in events:
            if row["event"] in ("signal_intent", "signal_result"):
                row["signal"] = 9
    journal = [] if fault == "missing_journal" else copy.deepcopy(events)
    with pytest.raises(ValueError):
        audit_supervisor(summary, journal, profile="other" if fault == "unknown_profile" else "normal-capture-v1")
