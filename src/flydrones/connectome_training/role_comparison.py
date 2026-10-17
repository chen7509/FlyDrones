"""One-shot internal role ablation through the actual curriculum producer."""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path

import torch

from .curriculum import run_curriculum
from .curriculum_config import CurriculumConfig
from .curriculum_session import ConnectomeCurriculumSession
from .model import dynamics_identity_suffix, topology_identity_suffix

COMPARISON_ROLES = (
    "descending-only-v1",
    "sensory-readout-v1",
    "shared-dynamics-v1",
)


def _snapshot(value: dict) -> dict:
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))


def _write(root: Path, result: dict) -> None:
    temporary = root / "comparison.json.writing"
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(root / "comparison.json")


def _shared_baseline(current: ConnectomeCurriculumSession) -> dict:
    return _snapshot(
        {
            "structure_identity": asdict(current.parameters.identity),
            "mapping_sha256": current.mapping_sha256,
            "dataset_sha256": current.dataset_sha256,
            "feature_profile": current.feature_profile,
            "device": str(current.device),
            "topology_format": current.model.topology_format,
            "dynamics_format": current.model.dynamics_format,
            "learning_initialization": current.learning_initialization,
            "initial_losses": current.initial_losses,
            "truncate_steps": current.truncate_steps,
            "loss_weights": asdict(current.loss_weights),
            "optimizer_class": type(current.optimizer).__module__ + "." + type(current.optimizer).__qualname__,
            "optimizer_options": [{k: v for k, v in group.items() if k != "params"} for group in current.optimizer.param_groups],
            "torch_version": str(torch.__version__),
        }
    )


def run_role_comparison(
    config: CurriculumConfig,
    output: str | Path,
    *,
    max_batches: int,
    device: str | None = None,
    learning_rate: float = 0.03,
    truncate_steps: int = 4,
    connectome_path: str | Path = "data/malecns_full.npz",
    parameters_path: str | Path = "results/connectome-training/stage-b/full-initialization",
    topology_format: str = "coo_reference",
    dynamics_format: str = "clipped-euler-v1",
) -> dict:
    """Run three fresh sessions with a common batch cap and checked baseline.

    Stage gates may stop or promote variants differently. Committed epoch counters
    are not optimizer-step counts, and exceptions do not roll back training.
    Existing output directories are never resumed, restarted or removed here.
    """
    if type(max_batches) is not int or max_batches < 1:
        raise ValueError("max_batches must be a positive integer")
    if isinstance(learning_rate, bool) or not math.isfinite(learning_rate) or learning_rate <= 0:
        raise ValueError("learning_rate must be finite and positive")
    if type(truncate_steps) is not int or truncate_steps < 1:
        raise ValueError("truncate_steps must be a positive integer")
    if device not in (None, "auto", "cpu", "cuda"):
        raise ValueError("unsupported device")
    topology_identity_suffix(topology_format)
    dynamics_identity_suffix(dynamics_format)
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    result = {
        "schema": "flydrones-internal-role-comparison-v1",
        "status": "RUNNING",
        "config": asdict(config),
        "per_variant_batch_cap": max_batches,
        "requested_session_options": {
            "device": device,
            "learning_rate": learning_rate,
            "truncate_steps": truncate_steps,
            "connectome_path": str(connectome_path),
            "parameters_path": str(parameters_path),
            "topology_format": topology_format,
            "dynamics_format": dynamics_format,
        },
        "shared_baseline": None,
        "variants": [],
        "training_success_verified": False,
        "flight_eligible": False,
        "scope": "Internal role ablation; same cap, potentially different stage trajectories/exposure/effort. No fair upstream baseline or full-model qualification. Epoch counters are not optimizer step counts. Errors can follow uncommitted parameter updates.",
    }
    _write(root, result)
    try:
        for profile in COMPARISON_ROLES:
            row = {"learning_profile": profile, "status": "RUNNING"}
            result["variants"].append(row)
            _write(root, result)
            current = ConnectomeCurriculumSession(
                config,
                device=device,
                learning_rate=learning_rate,
                truncate_steps=truncate_steps,
                connectome_path=connectome_path,
                parameters_path=parameters_path,
                topology_format=topology_format,
                dynamics_format=dynamics_format,
                learning_profile=profile,
            )
            try:
                baseline = _shared_baseline(current)
                if result["shared_baseline"] is None:
                    result["shared_baseline"] = baseline
                elif baseline != result["shared_baseline"]:
                    raise ValueError("learning-role comparison shared baseline mismatch")
                row.update(model_identity=current.model_identity, learning_roles=_snapshot(current.learning_roles))
                _write(root, result)
                variant_root = root / profile
                state = run_curriculum(config, variant_root, current, max_batches=max_batches)
                row.update(
                    status="RETURNED",
                    state=asdict(state),
                    committed_batches=len(list((variant_root / "reports").glob("*.json"))),
                    final_validation={stage.id: dict(current.evaluate(stage)) for stage in config.stages},
                    training_effort_lifetime=current.training_effort,
                )
                _write(root, result)
            finally:
                row["training_effort_lifetime"] = current.training_effort
                del current
        result["status"] = "FINISHED"
        result["all_curricula_complete"] = all(row["state"]["status"] == "COMPLETE" for row in result["variants"])
        _write(root, result)
        return _snapshot(result)
    except BaseException as exc:
        result["status"] = "ERROR"
        result["variants"][-1]["status"] = "ERROR"
        result["error"] = {"type": type(exc).__name__, "message": str(exc), "uncommitted_updates_possible": True}
        try:
            _write(root, result)
        except Exception as write_error:
            exc.add_note(f"comparison error record could not be persisted: {write_error!r}")
        raise
