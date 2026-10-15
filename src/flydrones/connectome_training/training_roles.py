"""Actual parameter participation for controlled connectome learning ablations."""

from __future__ import annotations

import json
import math
from hashlib import sha256

import torch

PARAMETER_ORDER = ("raw_input_gain", "type_bias_mv", "raw_tau_m", "readout")
DEFAULT_LEARNING_PROFILE = "shared-dynamics-v1"
ROLE_PROFILES = {
    "descending-only-v1": ("readout",),
    "sensory-readout-v1": ("raw_input_gain", "readout"),
    DEFAULT_LEARNING_PROFILE: PARAMETER_ORDER,
}


def learning_parameters(profile: str) -> tuple[str, ...]:
    if type(profile) is not str or profile not in ROLE_PROFILES:
        raise ValueError("unsupported learning profile")
    return ROLE_PROFILES[profile]


def _tensor_digest(value: torch.Tensor) -> str:
    header = json.dumps({"shape": list(value.shape), "dtype": str(value.dtype)}, sort_keys=True).encode()
    data = value.detach().cpu().contiguous().reshape(-1).view(torch.uint8).numpy().tobytes()
    return sha256(header + b"\0" + data).hexdigest()


def _named(model):
    named = dict(model.named_parameters())
    if tuple(named) != PARAMETER_ORDER:
        raise ValueError("learning parameter membership/order does not match core")
    if any(value.requires_grad for value in model.buffers()):
        raise ValueError("learning cannot optimize fixed topology buffers")
    if any(value.layout != torch.strided or not torch.isfinite(value).all() for value in named.values()):
        raise ValueError("learning parameters must be finite strided tensors")
    return named


def _record(model, profile):
    active = learning_parameters(profile)
    named = _named(model)
    frozen = [name for name in named if name not in active]
    return dict(
        schema="connectome-learning-roles-v1",
        profile=profile,
        trainable=list(active),
        frozen=frozen,
        frozen_initial_sha256={name: _tensor_digest(named[name]) for name in frozen},
    )


def configure_learning_roles(model, profile: str) -> dict:
    contract = _record(model, profile)
    for name, parameter in model.named_parameters():
        parameter.requires_grad_(name in contract["trainable"])
        parameter.grad = None
    return contract


def learning_identity_suffix(contract: dict) -> str:
    learning_parameters(contract["profile"])
    digest = sha256(json.dumps(contract, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return f":learning={contract['profile']}:{digest}"


def validate_learning_state(model, state: dict, contract: dict) -> None:
    if _record(model, contract["profile"]) != contract:
        raise ValueError("learning frozen initialization contract changed")
    named = _named(model)
    if not isinstance(state, dict) or set(state) != set(named):
        raise ValueError("learning state parameter membership mismatch")
    for name, parameter in named.items():
        value = state[name]
        if (
            not isinstance(value, torch.Tensor)
            or value.layout != torch.strided
            or value.shape != parameter.shape
            or value.dtype != parameter.dtype
            or not torch.isfinite(value).all()
        ):
            raise ValueError(f"learning parameter state invalid: {name}")
        if name in contract["frozen"] and _tensor_digest(value) != contract["frozen_initial_sha256"][name]:
            raise ValueError(f"frozen learning parameter changed: {name}")


def validate_learning_setup(model, optimizer, contract: dict) -> None:
    named = _named(model)
    validate_learning_state(model, named, contract)
    if any(p.requires_grad != (name in contract["trainable"]) for name, p in named.items()):
        raise ValueError("learning parameter gradient flags changed")
    expected = [id(named[name]) for name in contract["trainable"]]
    actual = [id(p) for group in optimizer.param_groups for p in group["params"]]
    if actual != expected:
        raise ValueError("optimizer learning parameter membership/order changed")


def validate_learning_optimizer_state(model, optimizer, state: dict, contract: dict) -> None:
    """Preflight the current producer's single-group Adam format before copying."""
    if type(optimizer) is not torch.optim.Adam:
        raise ValueError("learning optimizer must be Adam")
    if not isinstance(state, dict) or set(state) != {"state", "param_groups"}:
        raise ValueError("optimizer state schema mismatch")
    reference = optimizer.state_dict()["param_groups"]
    groups = state["param_groups"]
    if not isinstance(groups, list) or len(groups) != 1 or len(reference) != 1:
        raise ValueError("optimizer group membership mismatch")
    group = groups[0]
    expected_ids = list(range(len(contract["trainable"])))
    if (
        not isinstance(group, dict)
        or set(group) != set(reference[0])
        or not isinstance(group["params"], list)
        or group["params"] != expected_ids
        or any(type(index) is not int for index in group["params"])
    ):
        raise ValueError("optimizer serialized learning order mismatch")
    for name in ("lr", "eps", "weight_decay"):
        value = group[name]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (name == "lr" and value == 0):
            raise ValueError("optimizer numeric hyperparameter invalid")
    betas = group["betas"]
    if (
        not isinstance(betas, tuple)
        or len(betas) != 2
        or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v < 1 for v in betas)
    ):
        raise ValueError("optimizer beta hyperparameter invalid")
    for key, value in group.items():
        if key not in {"params", "lr", "eps", "weight_decay", "betas"}:
            original = reference[0][key]
            if type(value) is not type(original) or value != original:
                raise ValueError("optimizer mode changed")
    values = state["state"]
    if not isinstance(values, dict) or any(type(i) is not int or i not in expected_ids for i in values):
        raise ValueError("optimizer state index mismatch")
    named = dict(model.named_parameters())
    for index, row in values.items():
        required = {"step", "exp_avg", "exp_avg_sq"} | ({"max_exp_avg_sq"} if group["amsgrad"] else set())
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError("optimizer moment schema mismatch")
        step = row["step"]
        if (
            not isinstance(step, torch.Tensor)
            or step.layout != torch.strided
            or step.dtype not in (torch.float32, torch.float64)
            or step.shape != ()
            or not torch.isfinite(step)
            or float(step) < 0
            or float(step) != int(float(step))
        ):
            raise ValueError("optimizer step invalid")
        parameter = named[contract["trainable"][index]]
        for key in required - {"step"}:
            value = row[key]
            if (
                not isinstance(value, torch.Tensor)
                or value.layout != torch.strided
                or value.shape != parameter.shape
                or value.dtype != parameter.dtype
                or not torch.isfinite(value).all()
                or (key != "exp_avg" and torch.any(value < 0))
            ):
                raise ValueError("optimizer moment invalid")
