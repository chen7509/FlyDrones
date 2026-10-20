"""Create a separate, untrained v3 full MaleCNS initialization without graph loading."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from flydrones.connectome_training.masked_full_initialization import (
    create_masked_initialization,
)
from flydrones.connectome_training.parameters import load_parameter_set, parameter_mapping_digest

LEGACY_MANIFEST_SHA256 = "55f7648a9009d6f450543b5cdc456b9d47ed26dccfe7e2592adcde3f5a7cfe35"
LEGACY_PARAMETERS_SHA256 = "a44d445e3dd0fa6c477c00dafd845ee5323ebfd8e21321f36318244acb954691"
FULL_MODEL_SHA256 = "b6be8b3dd901e2e0893303c04058a110d6e0fb9922a69022b26514efcf06100c"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("results/connectome-training/stage-b/full-initialization"))
    parser.add_argument("--model", type=Path, default=Path("data/malecns_full.npz"))
    parser.add_argument("--destination", type=Path, default=Path("results/connectome-training/stage-b/full-initialization-depth-mask-v3"))
    args = parser.parse_args()
    destination = create_masked_initialization(
        args.source, args.model, args.destination,
        expected_manifest_sha256=LEGACY_MANIFEST_SHA256,
        expected_parameters_sha256=LEGACY_PARAMETERS_SHA256,
        expected_model_sha256=FULL_MODEL_SHA256,
    )
    parameters = load_parameter_set(destination)
    print(json.dumps({
        "destination": str(destination),
        "feature_profile": "depth-mask-v3",
        "untrained_initialization": True,
        "neurons": parameters.identity.neurons,
        "connections": parameters.identity.connections,
        "mapped_input_neurons": int(parameters.input_neuron_index.size),
        "feature_count": len(parameters.input_features),
        "mapping_sha256": parameter_mapping_digest(parameters),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
