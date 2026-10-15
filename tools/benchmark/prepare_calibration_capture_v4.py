"""Inert preparation entry; actual admission belongs to the primitive bootstrap."""

import sys


def _authorize(ticket):
    keys = {
        "schema",
        "nonce",
        "unit",
        "InvocationID",
        "ControlGroup",
        "claim_sha256",
        "recipe_sha256",
        "preidentity_sha256",
        "sdk_start_sha256",
    }
    if type(ticket) is not dict or set(ticket) != keys or ticket["schema"] != "static-sdk-ticket-reference-v4":
        raise ValueError("exact untrusted SDK ticket reference required")
    for key in ("nonce", "claim_sha256", "recipe_sha256", "preidentity_sha256", "sdk_start_sha256"):
        value = ticket[key]
        if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("ticket digest/nonce malformed")
    gate = sys.modules.get("tools.benchmark.static_v4_bootstrap")
    expected = __file__.replace("\\", "/").rsplit("/", 1)[0] + "/static_v4_bootstrap.py"
    if gate is None or getattr(gate, "__file__", "").replace("\\", "/") != expected:
        raise ValueError("already loaded literal bootstrap required;Task4 pending")
    validate = getattr(gate, "revalidate_sdk_reference", None)
    if not callable(validate):
        raise ValueError("actual receipt/current SDK revalidation unavailable")
    # This API must reread literal receipts/current own scope/PID, not attest a
    # caller object. Arbitrary in-process mutation is outside this boundary.
    return validate(ticket)


def prepare_v4(ticket):
    state = _authorize(ticket)
    from tools.benchmark.calibration_capture_pipeline_v4 import prepare

    return prepare(ticket, state)


if __name__ == "__main__":
    raise SystemExit("direct preparation entry denied;use admitted primitive bootstrap")
