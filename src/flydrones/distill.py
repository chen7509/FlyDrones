"""Distill the fast reflex teacher into a MaleCNS descending-neuron readout."""

from __future__ import annotations

import math

import numpy as np

from .reflex_training import FlyObservation, FlyReflexPolicy


STIMULUS_OBSERVATIONS = {
    0: FlyObservation(),
    1: FlyObservation(vertical_flow=0.7),
    2: FlyObservation(vertical_flow=-0.7),
    3: FlyObservation(rotation=0.7),
    4: FlyObservation(rotation=-0.7),
    5: FlyObservation(loom_left=0.9),
    6: FlyObservation(loom_right=0.9),
}


def _ordered_round(responses: dict, round_index: int) -> list[dict]:
    trials = sorted(
        (trial for trial in responses.get("trials", []) if int(trial.get("round", -1)) == round_index),
        key=lambda trial: int(trial["index"]),
    )
    indexes = [int(trial["index"]) for trial in trials]
    expected = sorted(STIMULUS_OBSERVATIONS)
    if indexes != expected:
        raise ValueError(f"round {round_index} needs stimulus indexes {expected}, got {indexes}")
    return trials


def _teacher_targets(policy: FlyReflexPolicy, trials: list[dict]) -> np.ndarray:
    rows = []
    for trial in trials:
        command = policy.act(STIMULUS_OBSERVATIONS[int(trial["index"])])
        rows.append((command.throttle, command.yaw, command.forward - policy.params.cruise))
    return np.asarray(rows, dtype=float)


def distill_cached_responses(
    responses: dict,
    policy: FlyReflexPolicy,
    ridge: float = 1.0,
) -> tuple[dict, dict]:
    """Fit round 0 and validate on the independently recorded round 1."""
    outputs = list(responses.get("outputs", []))
    if not outputs:
        raise ValueError("responses contain no descending-neuron outputs")
    training = _ordered_round(responses, 0)
    heldout = _ordered_round(responses, 1)
    x_train = np.asarray([[trial["rates"][name] for name in outputs] for trial in training], dtype=float)
    x_heldout = np.asarray([[trial["rates"][name] for name in outputs] for trial in heldout], dtype=float)
    baseline = x_train[0]
    centered = x_train - baseline
    heldout_centered = x_heldout - baseline
    y_train = _teacher_targets(policy, training)
    y_heldout = _teacher_targets(policy, heldout)

    regularizer = max(0.0, float(ridge)) * np.eye(centered.shape[1])
    weights = np.linalg.solve(centered.T @ centered + regularizer, centered.T @ y_train)
    predictions = heldout_centered @ weights
    axes = ("throttle", "yaw", "forward")
    rmse = {
        axis: float(math.sqrt(np.mean(np.square(y_heldout[:, column] - predictions[:, column]))))
        for column, axis in enumerate(axes)
    }

    sign_checks: dict[str, bool] = {}
    for row, trial in enumerate(heldout):
        for column, axis in enumerate(axes):
            target = y_heldout[row, column]
            if abs(target) > 1e-6:
                sign_checks[f"{trial['stimulus']}:{axis}"] = bool(predictions[row, column] * target > 0)
    # Keep the same predeclared neutral-command gate used by the existing
    # full-connectome calibration reports in this repository.
    rest_ok = bool(np.max(np.abs(predictions[0])) <= 0.20)
    checks = {
        "throttle_rmse": rmse["throttle"] <= 0.20,
        "yaw_rmse": rmse["yaw"] <= 0.25,
        "forward_rmse": rmse["forward"] <= 0.10,
        "all_directions": all(sign_checks.values()),
        "rest_neutral": rest_ok,
    }

    readout_axes = {}
    for column, axis in enumerate(axes):
        terms = {
            name: round(float(value), 9)
            for name, value in zip(outputs, weights[:, column])
            if abs(value) >= 1e-8
        }
        readout_axes[axis] = {"gain": 1.0, "terms": terms}
    readout_axes["lateral"] = {"gain": 0.0, "terms": {}}
    readout = {
        "teacher_policy_format": "flydrones-reflex-policy-v1",
        "source_neurons": int(responses.get("neurons", 0)),
        "ridge": float(ridge),
        "cruise": float(policy.params.cruise),
        "baseline": {name: round(float(value), 6) for name, value in zip(outputs, baseline)},
        "axes": readout_axes,
    }
    validation_rows = []
    for row, trial in enumerate(heldout):
        validation_rows.append(
            {
                "stimulus": trial["stimulus"],
                "index": int(trial["index"]),
                "target": dict(zip(axes, y_heldout[row].round(6).tolist())),
                "prediction": dict(zip(axes, predictions[row].round(6).tolist())),
            }
        )
    validation = {
        "accepted": all(checks.values()),
        "checks": checks,
        "rmse": {axis: round(value, 6) for axis, value in rmse.items()},
        "direction_checks": sign_checks,
        "training_trials": len(training),
        "heldout_trials": len(heldout),
        "criteria": "RMSE throttle <= 0.20, yaw <= 0.25, forward <= 0.10; all nonzero directions correct; rest abs <= 0.20",
        "heldout": validation_rows,
        "limitation": "Synthetic visual stimuli and cached neural responses; forest flight is not yet validated.",
    }
    return readout, validation
