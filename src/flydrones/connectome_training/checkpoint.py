from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import random
from typing import Any

import numpy as np
import torch

SCHEMA = "flydrones-connectome-checkpoint-v1"


def _digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rng_state() -> dict[str, Any]:
    numpy_state = np.random.get_state()
    return {
        "python": random.getstate(),
        "numpy": {
            "bit_generator": numpy_state[0],
            "keys": torch.tensor(
                numpy_state[1].astype(np.int64, copy=False), dtype=torch.int64
            ),
            "position": int(numpy_state[2]),
            "has_gauss": int(numpy_state[3]),
            "cached_gaussian": float(numpy_state[4]),
        },
        "torch": torch.get_rng_state(),
    }


def _validate_metadata(metadata: dict) -> None:
    required = {"epoch", "seed", "dataset_sha256"}
    missing = required - set(metadata)
    if missing:
        raise ValueError(f"checkpoint metadata missing: {', '.join(sorted(missing))}")
    digest = str(metadata["dataset_sha256"])
    if len(digest) != 64 or any(
        char not in "0123456789abcdef" for char in digest.lower()
    ):
        raise ValueError("dataset_sha256 must be a SHA-256 hex digest")
    if int(metadata["epoch"]) < 0:
        raise ValueError("checkpoint epoch must be non-negative")


def save_checkpoint(
    path: str | Path,
    *,
    model_state: dict,
    optimizer_state: dict,
    metadata: dict,
) -> Path:
    _validate_metadata(metadata)
    path = Path(path)
    temporary = path.with_name(path.name + ".writing")
    if path.exists() or temporary.exists():
        raise FileExistsError(path if path.exists() else temporary)
    temporary.mkdir(parents=True)
    payload_path = temporary / "checkpoint.pt"
    payload = {
        "model_state": model_state,
        "optimizer_state": optimizer_state,
        "metadata": dict(metadata),
        "rng_state": _rng_state(),
    }
    torch.save(payload, payload_path)
    manifest = {
        "schema": SCHEMA,
        "checkpoint_sha256": _digest(payload_path),
        "metadata": dict(metadata),
    }
    (temporary / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.rename(path)
    return path


def load_checkpoint(path: str | Path) -> dict:
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    payload_path = path / "checkpoint.pt"
    if manifest.get("schema") != SCHEMA:
        raise ValueError("unsupported connectome checkpoint schema")
    if manifest.get("checkpoint_sha256") != _digest(payload_path):
        raise ValueError("checkpoint.pt hash mismatch")
    payload = torch.load(payload_path, weights_only=True, map_location="cpu")
    if not isinstance(payload, dict) or set(payload) != {
        "model_state",
        "optimizer_state",
        "metadata",
        "rng_state",
    }:
        raise ValueError("checkpoint payload does not match the contract")
    _validate_metadata(payload["metadata"])
    if payload["metadata"] != manifest.get("metadata"):
        raise ValueError("checkpoint metadata does not match manifest")
    return payload
