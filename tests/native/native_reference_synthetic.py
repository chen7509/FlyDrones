import importlib.util
import json
import sys
from pathlib import Path

import gz.sim8 as sim

path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("_fly_native_reference_test", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
passed = []
for mode in ["good", "missing", "partial", "quaternion", "topology", "pre_gap", "post_epoch", "duplicate_pre", "new_ecm"]:
    e = sim.EntityComponentManager()
    mod.fixture(e)
    p = mod.Probe()
    refused = False
    try:
        p.pre(e, 2000000 if mode == "pre_gap" else 1000000, 1000000)
        if mode == "duplicate_pre":
            p.pre(e, 1000000, 1000000)
        if mode != "missing":
            p.inject(e, mode)
        state = p.post(sim.EntityComponentManager() if mode == "new_ecm" else e, 2000000 if mode == "post_epoch" else 1000000)
        assert state["canary_overwritten"] and state["position"] == [0.0, 0.0, 0.2]
    except RuntimeError:
        refused = True
    assert refused == (mode != "good"), mode
    if refused:
        assert p.status()["failed"]
        try:
            p.pre(e, 2000000, 1000000)
        except RuntimeError:
            pass
        else:
            raise AssertionError("refusal not latched")
    passed.append(mode)
print(json.dumps(dict(passed=passed, scope="synthetic ECM only; injected outputs in test binary, not physics")))
