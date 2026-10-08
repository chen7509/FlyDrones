from hashlib import sha256

import numpy as np
import pytest
from scipy import sparse

from flydrones.brain.connectome import Connectome
from flydrones.connectome_training.features import FEATURE_NAMES
from flydrones.connectome_training.parameters import (
    build_structure_identity,
    initial_parameter_set,
    save_parameter_set,
)


@pytest.fixture
def tiny_artifacts(tmp_path):
    def make(*, zero=False, feature_names=FEATURE_NAMES):
        weights = np.zeros((16, 16), np.float32)
        if not zero:
            weights[0, 1], weights[1, 0] = 0.5, -1.0
        connectome = Connectome(
            "tiny-connectome", sparse.csc_matrix(weights),
            np.array(["A"] * 16), np.array(["L"] * 16),
        )
        source = tmp_path / "tiny.npz"
        connectome.save(source)
        identity = build_structure_identity(connectome, sha256(source.read_bytes()).hexdigest())
        parameters = initial_parameter_set(
            identity, feature_names, ("vx", "vy", "vz", "yaw_rate"),
            np.array([0, 1, 2, 3]),
        )
        parameters.readout[:] = np.diag([0.3, -0.2, 0.4, 0.1])
        folder = save_parameter_set(tmp_path / "parameters", parameters)
        return source, folder, connectome, parameters
    return make
