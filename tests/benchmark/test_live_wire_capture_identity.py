"""Cross-file identity joins; explicitly synthetic, no runtime execution."""

import copy
import stat

import pytest

from tests.benchmark import test_live_wire_runtime_audit as runtime_fixture
from tools.benchmark import audit_live_wire_study as audit


def evidence():
    runtime = runtime_fixture.evidence()
    owner = dict(
        pid=321,
        pgrp=300,
        session=300,
        start_ticks=7,
        uid=1000,
        gid=1000,
        exe="/installed/px4",
        cwd="/capture/rootfs",
        exe_device=1,
        exe_inode=10,
        cwd_device=1,
        cwd_inode=100,
        net="net:[5]",
        user="user:[6]",
    )
    configuration = dict(schema="capture-wire-v1", session_id="normal-v1.clock", sim_origin_ns=0, remote_origin_ns=0)
    header = dict(
        owner=owner,
        descriptor=dict(fd=8, device=5, inode=300, mode=stat.S_IFSOCK | 0o777, net=owner["net"]),
        configuration=configuration,
        start_ns=10,
        total_deadline_ns=300_000_000_010,
    )
    owned = dict(
        owner=owner.copy(),
        path="/tmp/px4-sock-8",
        start_ns=10,
        deadline_ns=300_000_000_010,
        failure=None,
        cleanup_errors=[],
        refusal_journal_error=None,
        construction_refusal=None,
    )
    core = dict(failure=None, cleanup_errors=[], owned=owned)
    session = dict(
        failure=None,
        cleanup_errors=[],
        refusal_journal_error=None,
        restoration_init_error=None,
        observed_bootstrap_complete=True,
        interval_transaction_pass=True,
        clock_signature=["normal-v1.clock", 0, 0],
        core=core,
    )
    lifecycle = dict(
        failure=None,
        fusion_qualified=False,
        network_authorized=False,
        driver=dict(phase="closed", closed=True, failure=None, ready=False, fusion_qualified=False, network_authorized=False),
        session=session,
    )
    result = dict(
        status="capture_completed",
        errors=[],
        estimator_run=True,
        end_sim_ns=25_000_000_000,
        eligible_for_px4_fusion=False,
        px4_exit_code=0,
        wire_lifecycle=copy.deepcopy(lifecycle),
    )
    return dict(
        result=result,
        wire_owner=header,
        lifecycle=lifecycle,
        wire_config=configuration,
        runtime=runtime_fixture.audit(runtime),
        pre=runtime["pre"],
        cleanup=dict(
            qualified=True, owner=dict(pid=300, pgrp=300, session=300, start_ticks=2), capture_status_retained="capture_completed"
        ),
    )


def run(data):
    assert hasattr(audit, "audit_wire_capture_identity"), "capture identity join missing"
    return audit.audit_wire_capture_identity(**data)


def test_raw_runtime_owner_and_descriptor_join():
    out = run(evidence())
    assert out["capture_identity_consistent"] is True
    assert out["context"]["owner"]["pid"] == 321
    assert out["live_qualified"] is False


def test_nonboolean_startup_flag_is_not_silently_ignored():
    data = evidence()
    data["result"]["startup_preflight_only"] = 1
    with pytest.raises(ValueError):
        run(data)


@pytest.mark.parametrize(
    "fault",
    [
        "startup",
        "end",
        "estimator",
        "armed_authority",
        "px4_exit",
        "mirror",
        "header_pid",
        "start_ticks",
        "exe_inode",
        "namespace",
        "descriptor_type",
        "descriptor_bool",
        "deadline",
        "clock",
        "owned_peer",
        "path",
        "owned_start",
        "owned_cleanup",
        "core_failure",
        "session_failure",
        "driver_open",
        "supervisor_group",
        "supervisor_birth",
        "runtime_false",
        "pre_missing",
        "closed_ready",
    ],
)
def test_independent_identity_corruptions_refuse(fault):
    data = evidence()
    if fault == "startup":
        data["result"]["startup_preflight_only"] = True
    elif fault == "end":
        data["result"]["end_sim_ns"] -= 1
    elif fault == "estimator":
        data["result"]["estimator_run"] = False
    elif fault == "armed_authority":
        data["result"]["eligible_for_px4_fusion"] = True
    elif fault == "px4_exit":
        data["result"]["px4_exit_code"] = 9
    elif fault == "mirror":
        data["result"]["wire_lifecycle"]["failure"] = "lost write"
    elif fault == "header_pid":
        data["wire_owner"]["owner"]["pid"] = 322
    elif fault == "start_ticks":
        data["runtime"]["owners"]["px4"]["start_ticks"] += 1
    elif fault == "exe_inode":
        data["wire_owner"]["owner"]["exe_inode"] += 1
    elif fault == "namespace":
        data["wire_owner"]["descriptor"]["net"] = "net:[8]"
    elif fault == "descriptor_type":
        data["wire_owner"]["descriptor"]["mode"] = stat.S_IFREG | 0o600
    elif fault == "descriptor_bool":
        data["wire_owner"]["descriptor"]["fd"] = False
    elif fault == "deadline":
        data["wire_owner"]["total_deadline_ns"] += 1
    elif fault == "clock":
        data["lifecycle"]["session"]["clock_signature"][2] = 1000000
    elif fault == "owned_peer":
        data["lifecycle"]["session"]["core"]["owned"]["owner"]["pid"] = 322
    elif fault == "path":
        data["lifecycle"]["session"]["core"]["owned"]["path"] = "/tmp/other"
    elif fault == "owned_start":
        data["lifecycle"]["session"]["core"]["owned"]["start_ns"] += 1
    elif fault == "owned_cleanup":
        data["lifecycle"]["session"]["core"]["owned"]["cleanup_errors"] = ["error"]
    elif fault == "core_failure":
        data["lifecycle"]["session"]["core"]["failure"] = "failure"
    elif fault == "session_failure":
        data["lifecycle"]["session"]["failure"] = "failure"
    elif fault == "driver_open":
        data["lifecycle"]["driver"]["closed"] = False
    elif fault == "supervisor_group":
        data["cleanup"]["owner"]["pgrp"] += 1
    elif fault == "supervisor_birth":
        data["cleanup"]["owner"]["start_ticks"] = 99
    elif fault == "runtime_false":
        data["runtime"]["runtime_records_consistent"] = False
    elif fault == "pre_missing":
        data["pre"]["files"] = []
    elif fault == "closed_ready":
        data["lifecycle"]["driver"]["ready"] = True
    if fault != "mirror":
        data["result"]["wire_lifecycle"] = copy.deepcopy(data["lifecycle"])
    with pytest.raises(ValueError):
        run(data)
