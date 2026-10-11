"""The Agent preparer must retain each declared library alias as its own path."""

import importlib.util
from pathlib import Path


def preparer():
    path = Path(__file__).resolve().parents[2] / "results/live-wire-study-dev-1701/prepare-v12.py"
    spec = importlib.util.spec_from_file_location("agent_live_wire_preparer", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_agent_selection_preserves_all_requested_aliases(tmp_path):
    script = preparer()
    binary = str(tmp_path / "bin" / "Agent")
    declaration = str(tmp_path / "agent.json")
    bundle = str(tmp_path / "bundle.tar.gz")
    alias = str(tmp_path / "lib" / "libmicrocdr.so")
    versioned = str(tmp_path / "lib" / "libmicrocdr.so.2.0.1")
    inventory = {"existing": [str(tmp_path / "existing")]}
    selected = [declaration, bundle, binary, alias, versioned]
    script.add_agent_selection(inventory, selected, binary)
    assert inventory["runtime-root:agent"] == [binary]
    assert inventory["runtime:agent-selected"] == [declaration, bundle, alias, versioned]


def test_negative_binding_cases_have_distinct_output_names():
    script = preparer()
    names = [script.negative_binding_name(case) for case in ("lazy_leaf_missing", "agent_missing_role")]
    assert len(set(names)) == 2
