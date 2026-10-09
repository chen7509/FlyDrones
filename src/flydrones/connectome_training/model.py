from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from torch import nn
from torch.nn import functional as functional

from flydrones.brain.connectome import Connectome

from .parameters import ParameterSet, build_structure_identity


def _inverse_softplus(value: torch.Tensor) -> torch.Tensor:
    if torch.any(value <= 0):
        raise ValueError("inverse softplus requires positive values")
    return value + torch.log(-torch.expm1(-value))


@dataclass(frozen=True)
class RecurrentState:
    voltage: torch.Tensor

    def detached(self) -> RecurrentState:
        return RecurrentState(self.voltage.detach())


class ConnectomeConstrainedCore(nn.Module):
    def __init__(
        self,
        connectome: Connectome,
        parameter_set: ParameterSet,
    ):
        super().__init__()
        expected = build_structure_identity(
            connectome, parameter_set.identity.model_sha256
        )
        actual = parameter_set.identity
        if (
            expected.topology_sha256 != actual.topology_sha256
            or expected.neurons != actual.neurons
            or expected.connections != actual.connections
            or expected.cell_types != actual.cell_types
        ):
            raise ValueError("parameter identity does not match connectome topology")

        weights = connectome.weights.tocoo().astype(np.float32)
        order = np.lexsort((weights.col, weights.row))
        rows = np.asarray(weights.row[order], np.int64)
        columns = np.asarray(weights.col[order], np.int64)
        values = np.asarray(weights.data[order], np.float32)
        if not np.isfinite(values).all():
            raise ValueError("connectome weights contain non-finite values")

        input_features = np.asarray(parameter_set.input_feature_index, np.int64)
        inputs = np.asarray(parameter_set.input_neuron_index, np.int64)
        outputs = np.asarray(parameter_set.output_neuron_index, np.int64)

        cell_types = parameter_set.identity.cell_types
        type_lookup = {name: index for index, name in enumerate(cell_types)}
        mapped_types = [
            type_lookup.get(str(value) or "__unknown__") for value in connectome.types
        ]
        if any(value is None for value in mapped_types):
            raise ValueError("connectome contains a cell type absent from parameters")
        type_index = np.asarray(mapped_types, np.int64)

        magnitudes = np.abs(values)
        incoming = np.bincount(rows, weights=magnitudes, minlength=connectome.n)
        normalized = magnitudes / np.maximum(1.0, incoming[rows])
        edge_indices = torch.tensor(np.vstack([rows, columns]), dtype=torch.long)
        edge_values = torch.tensor(np.sign(values) * normalized, dtype=torch.float32)
        fixed_topology = torch.sparse_coo_tensor(
            edge_indices,
            edge_values,
            (connectome.n, connectome.n),
            check_invariants=True,
        ).coalesce()

        self.register_buffer("edge_row", torch.tensor(rows, dtype=torch.long))
        self.register_buffer("edge_column", torch.tensor(columns, dtype=torch.long))
        self.register_buffer("edge_sign", torch.tensor(np.sign(values), dtype=torch.float32))
        self.register_buffer("edge_magnitude", torch.tensor(magnitudes, dtype=torch.float32))
        self.register_buffer("fixed_topology", fixed_topology)
        self.register_buffer("type_index", torch.tensor(type_index, dtype=torch.long))
        self.register_buffer(
            "input_feature_index", torch.tensor(input_features, dtype=torch.long)
        )
        self.register_buffer("input_neuron_index", torch.tensor(inputs, dtype=torch.long))
        self.register_buffer("output_neuron_index", torch.tensor(outputs, dtype=torch.long))

        input_gain = torch.tensor(parameter_set.input_gain, dtype=torch.float32)
        tau_offset = torch.tensor(parameter_set.tau_m_ms - 1.0, dtype=torch.float32)
        self.raw_input_gain = nn.Parameter(_inverse_softplus(input_gain))
        self.type_bias_mv = nn.Parameter(
            torch.tensor(parameter_set.type_bias_mv, dtype=torch.float32)
        )
        self.raw_tau_m = nn.Parameter(_inverse_softplus(tau_offset))
        self.readout = nn.Parameter(
            torch.tensor(parameter_set.readout, dtype=torch.float32)
        )
        self.n_neurons = int(connectome.n)
        self.input_features = tuple(parameter_set.input_features)
        self.n_features = len(parameter_set.input_features)
        self.n_outputs = len(parameter_set.outputs)

    @property
    def input_gain(self) -> torch.Tensor:
        return functional.softplus(self.raw_input_gain)

    @property
    def tau_m_ms(self) -> torch.Tensor:
        return 1.0 + functional.softplus(self.raw_tau_m)

    def initial_state(
        self,
        batch_size: int,
        *,
        device: torch.device | None = None,
        dtype: torch.dtype | None = None,
    ) -> RecurrentState:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        reference = self.raw_input_gain
        return RecurrentState(
            torch.zeros(
                batch_size,
                self.n_neurons,
                device=device or reference.device,
                dtype=dtype or reference.dtype,
            )
        )

    def forward_step(
        self,
        features: torch.Tensor,
        state: RecurrentState,
        dt_s: float,
    ) -> tuple[torch.Tensor, RecurrentState]:
        if features.ndim != 2 or features.shape[1] != self.n_features:
            raise ValueError("features must have shape (batch, feature)")
        if state.voltage.shape != (features.shape[0], self.n_neurons):
            raise ValueError("recurrent state shape does not match features")
        if not torch.isfinite(features).all():
            raise ValueError("features contain non-finite values")
        if not np.isfinite(dt_s) or dt_s <= 0:
            raise ValueError("dt_s must be positive and finite")
        drive = self.type_bias_mv[self.type_index].expand(
            features.shape[0], -1
        ).clone()
        drive.index_add_(
            1,
            self.input_neuron_index,
            features[:, self.input_feature_index]
            * self.input_gain[self.input_feature_index],
        )
        recurrent = torch.sparse.mm(
            self.fixed_topology, torch.sigmoid(state.voltage).T
        ).T
        alpha = torch.clamp(dt_s * 1000.0 / self.tau_m_ms, 0.0, 1.0)
        voltage = state.voltage + alpha * (
            -state.voltage + drive + recurrent
        )
        rates = torch.sigmoid(voltage)
        command = torch.tanh(rates[:, self.output_neuron_index] @ self.readout.T)
        return command, RecurrentState(voltage)

    def forward_sequence(
        self,
        features: torch.Tensor,
        truncate_steps: int,
        *,
        state: RecurrentState | None = None,
        dt_s: float = 0.05,
    ) -> tuple[torch.Tensor, RecurrentState]:
        if features.ndim != 3 or features.shape[2] != self.n_features:
            raise ValueError("features must have shape (batch, time, feature)")
        if features.shape[1] < 1:
            raise ValueError("feature sequence must be non-empty")
        if truncate_steps < 1:
            raise ValueError("truncate_steps must be positive")
        if not torch.isfinite(features).all():
            raise ValueError("features contain non-finite values")
        current = state or self.initial_state(
            features.shape[0], device=features.device, dtype=features.dtype
        )
        commands = []
        for index in range(features.shape[1]):
            command, current = self.forward_step(
                features[:, index], current, dt_s
            )
            commands.append(command)
            if (
                (index + 1) % truncate_steps == 0
                and index + 1 < features.shape[1]
            ):
                current = current.detached()
        return torch.stack(commands, dim=1), current
