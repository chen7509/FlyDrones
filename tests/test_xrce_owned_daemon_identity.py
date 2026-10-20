"""Prospective WSL Docker daemon identity and owned-name refusal tests."""

from __future__ import annotations

import copy
import subprocess

import pytest

from tools.connectome.xrce_typed_probe.daemon_identity import (
    DaemonProbeError,
    observe,
    validate_pair,
)

OWNED = "flydrones-owned-xrce-future"


def runner_with(*, daemon="daemon-id", context="default", owned="", failed=None):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        verb = args[5]
        value = {"info": daemon, "context": context, "ps": owned}[verb]
        return subprocess.CompletedProcess(args, 1 if verb == failed else 0,
                                           value + "\n" if value else "", "failure" if verb == failed else "")

    return run, calls


def test_same_wsl_cli_daemon_and_absent_owned_name() -> None:
    runner, calls = runner_with()
    before = observe(OWNED, runner=runner, clock_ns=lambda: 42)
    after = observe(OWNED, runner=runner, clock_ns=lambda: 84)
    proof = validate_pair(before, after, OWNED)
    assert proof["same_daemon"] is True
    assert proof["owned_container_absent"] is True
    assert proof["px4_source_authenticated"] is False
    assert len(calls) == 6
    assert all(command[:5] == ["wsl", "-d", "Ubuntu", "--", "docker"] for command in calls)
    assert calls[2][-1] == "{{.Names}}"


@pytest.mark.parametrize("failed", ["info", "context", "ps"])
def test_query_error_is_refusal_even_when_output_is_empty(failed) -> None:
    runner, _ = runner_with(failed=failed)
    with pytest.raises(DaemonProbeError, match="query failed") as failure:
        observe(OWNED, runner=runner, clock_ns=lambda: 1)
    assert failure.value.record["queries"][failed]["returncode"] == 1
    assert failure.value.record["owned_name"] == OWNED


def test_daemon_or_context_drift_is_refused() -> None:
    first, _ = runner_with()
    before = observe(OWNED, runner=first, clock_ns=lambda: 1)
    for changed in ({"daemon": "other-daemon-id"}, {"context": "desktop-linux"}):
        second, _ = runner_with(**changed)
        after = observe(OWNED, runner=second, clock_ns=lambda: 2)
        with pytest.raises(ValueError, match="identity changed"):
            validate_pair(before, after, OWNED)


def test_owned_name_or_ambiguous_output_is_refused_without_deleting() -> None:
    for name in (OWNED, OWNED + "\nother"):
        runner, calls = runner_with(owned=name)
        with pytest.raises(ValueError, match="owned container"):
            observe(OWNED, runner=runner, clock_ns=lambda: 1)
        assert all("rm" not in command for command in calls)


def test_record_mutation_and_wrong_name_are_refused() -> None:
    runner, _ = runner_with()
    before = observe(OWNED, runner=runner, clock_ns=lambda: 1)
    after = observe(OWNED, runner=runner, clock_ns=lambda: 2)
    altered = copy.deepcopy(after)
    altered["queries"]["info"]["args"][5] = "ps"
    with pytest.raises(ValueError, match="record"):
        validate_pair(before, altered, OWNED)
    with pytest.raises(ValueError, match="record schema"):
        validate_pair(before, after, "different")


def test_dotted_owned_name_escapes_docker_regex() -> None:
    runner, calls = runner_with()
    observe("flydrones.source-1701", runner=runner, clock_ns=lambda: 1)
    assert "name=^/flydrones\\.source-1701$" in calls[2]


@pytest.mark.parametrize("invalid", [False, 0.0])
def test_mutated_ps_returncode_type_is_refused(invalid) -> None:
    runner, _ = runner_with()
    before = observe(OWNED, runner=runner, clock_ns=lambda: 1)
    after = copy.deepcopy(before)
    after["sample_monotonic_ns"] = 2
    after["queries"]["ps"]["returncode"] = invalid
    with pytest.raises(ValueError, match="ps query failed"):
        validate_pair(before, after, OWNED)
