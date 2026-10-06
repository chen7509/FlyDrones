import json


def write(path, value):
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def fixture(tmp_path):
    destination = tmp_path / "study" / "startup-preflight-v1"
    destination.mkdir(parents=True)
    result = {
        "status": "capture_completed",
        "errors": [],
        "startup_preflight_only": True,
        "startup_preflight_completed": True,
        "eligible_for_vio_input": False,
        "eligible_for_px4_fusion": False,
        "runtime_binding": {
            "pre_recorded": True,
            "declared_files_stable": True,
            "local_file_graph_verified": True,
            "phases": ["postgraph", "bootstrap"],
            "owned_phases": {"px4": [], "openvins": []},
            "runtime_mapping_coverage_verified": False,
            "errors": [],
            "runtime_closure_qualified": False,
        },
        "physical_execution_qualified": False,
        "vio_accuracy_qualified": False,
        "estimator_health_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }
    event = {"event": "leader_reaped", "returncode": 0}
    supervisor = {
        "worker_exit": 0,
        "capture_status": "capture_completed",
        "errors": [],
        "events": [event],
        "cleanup": {
            "events": [event],
            "errors": [],
            "no_executing_members": True,
            "group_absent": True,
            "sigkill_dispatched": False,
            "graceful_group_cleanup_verified": True,
            "all_descendant_cleanup_qualified": False,
        },
    }
    write(destination / "result.json", result)
    write(destination / "supervisor.json", supervisor)
    (destination / "runtime-binding-pre.json").write_text("{}\n")
    (destination / "runtime-binding-post.json").write_text("{}\n")
    (destination / "resource-graph.json").write_text("{}\n")
    events = destination.with_name(destination.name + ".supervisor-events.jsonl")
    events.write_text(json.dumps(event, sort_keys=True) + "\n")
    environment = destination.with_name(destination.name + ".supervisor-environment.json")
    environment.write_text("{}\n")
    dispatch = tmp_path / "dispatch.json"
    completion = tmp_path / "completion.json"
    write(
        dispatch,
        {
            "schema": "capture-startup-preflight-dispatch-v1",
            "destination": str(destination.resolve()),
            "head": "abc123",
            "resources_before": [],
            "physical_run": False,
        },
    )
    write(
        completion,
        {
            "schema": "capture-startup-preflight-completion-v1",
            "returncode": 0,
            "destination": str(destination.resolve()),
            "resources_after": [],
            "physical_run": False,
        },
    )
    return destination, dispatch, completion


def test_startup_preflight_audit_accepts_narrow_success(tmp_path):
    from tools.benchmark.audit_capture_startup_preflight import audit

    destination, dispatch, completion = fixture(tmp_path)
    result = audit(destination, dispatch, completion, expected_head="abc123")
    assert result["failures"] == []
    assert result["startup_preflight_qualified"] is True
    assert result["physical_execution_qualified"] is False


def test_startup_preflight_audit_rejects_each_material_drift(tmp_path):
    from tools.benchmark.audit_capture_startup_preflight import audit

    cases = {
        "head": lambda destination, dispatch, completion: None,
        "resource": lambda destination, dispatch, completion: _change(completion, "resources_after", ["px4"]),
        "physics": lambda destination, dispatch, completion: (destination / "physics-substeps.jsonl").write_text("bad"),
        "phase": lambda destination, dispatch, completion: _change_nested(
            destination / "result.json", ("runtime_binding", "phases"), ["postgraph", "bootstrap", "postfirststep"]
        ),
        "owned": lambda destination, dispatch, completion: _change_nested(
            destination / "result.json", ("runtime_binding", "owned_phases", "px4"), ["ready"]
        ),
        "claim": lambda destination, dispatch, completion: _change(destination / "result.json", "fusion_eligible", True),
        "journal": lambda destination, dispatch, completion: destination.with_name(
            destination.name + ".supervisor-events.jsonl"
        ).write_text("{}\n"),
        "sigkill": lambda destination, dispatch, completion: _change_nested(
            destination / "supervisor.json", ("cleanup", "sigkill_dispatched"), True
        ),
    }
    for index, (name, mutate) in enumerate(cases.items()):
        root = tmp_path / str(index)
        destination, dispatch, completion = fixture(root)
        mutate(destination, dispatch, completion)
        expected = "wrong" if name == "head" else "abc123"
        result = audit(destination, dispatch, completion, expected_head=expected)
        assert result["failures"], name
        assert result["startup_preflight_qualified"] is False


def _change(path, key, value):
    data = json.loads(path.read_text())
    data[key] = value
    write(path, data)


def _change_nested(path, keys, value):
    data = json.loads(path.read_text())
    target = data
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    write(path, data)
