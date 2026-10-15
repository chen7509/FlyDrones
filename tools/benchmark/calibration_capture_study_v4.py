"""Inert study entry. Importing this file cannot publish or prepare a study."""

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
    return validate(ticket)


def publish_study_v4(ticket):
    state = _authorize(ticket)
    from tools.benchmark.calibration_capture_pipeline_v4 import publish

    return publish(ticket, state)


def audit_v4_preparation(binding, preparation, bill_path, bill):
    from tools.benchmark.calibration_capture_pipeline_v4 import audit_preparation

    return audit_preparation(binding, preparation, bill_path, bill)


def verify_study_v4(path, sha, *, require_absent=True):
    from tools.benchmark.calibration_capture_pipeline_v4 import verify

    return verify(path, sha, require_absent=require_absent)


if __name__ == "__main__":
    raise SystemExit("direct study entry denied;use admitted same-SDK publisher")
