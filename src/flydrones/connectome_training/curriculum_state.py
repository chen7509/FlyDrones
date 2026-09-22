from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
from typing import IO
from uuid import uuid4

SCHEMA = "flydrones-connectome-curriculum-state-v1"


def _sha256(value: str, name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
        raise ValueError(f"{name} must be a SHA-256 digest")


@dataclass(frozen=True)
class CurriculumState:
    run_id: str
    config_digest: str
    profile: str
    status: str
    stage_index: int
    batch_index: int
    global_updates: int
    environment_steps: int
    latest_checkpoint: str | None
    best_checkpoint: str | None
    best_score: float | None
    completed_stages: tuple[str, ...]
    failed_attempts: int
    last_committed_batch: str | None
    baseline_losses: dict[str, float]
    model_identity: str

    def validate(self) -> None:
        if not self.run_id or not self.profile or not self.model_identity:
            raise ValueError("curriculum state identity fields must be non-empty")
        _sha256(self.config_digest, "config_digest")
        if self.status not in {"COMMITTED", "COMPLETE", "FAILED"}:
            raise ValueError("only committed terminal states may be persisted")
        for name in (
            "stage_index",
            "batch_index",
            "global_updates",
            "environment_steps",
            "failed_attempts",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.best_score is not None and not math.isfinite(self.best_score):
            raise ValueError("best_score must be finite")
        if any(not math.isfinite(float(value)) for value in self.baseline_losses.values()):
            raise ValueError("baseline losses must be finite")


class StateStore:
    def __init__(self, root: str | Path, config_digest: str):
        _sha256(config_digest, "config_digest")
        self.root = Path(root)
        self.config_digest = config_digest
        self.path = self.root / "state.json"
        self.temporary = self.root / "state.json.writing"

    def load(self) -> CurriculumState | None:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.pop("schema", None) != SCHEMA:
            raise ValueError("unsupported curriculum state schema")
        payload["completed_stages"] = tuple(payload["completed_stages"])
        state = CurriculumState(**payload)
        state.validate()
        if state.config_digest != self.config_digest:
            raise ValueError("curriculum state config digest mismatch")
        return state

    def commit(self, state: CurriculumState) -> Path:
        state.validate()
        if state.config_digest != self.config_digest:
            raise ValueError("curriculum state config digest mismatch")
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {"schema": SCHEMA, **asdict(state)}
        self.temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        self.temporary.replace(self.path)
        return self.path


class RunLock:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.path = self.root / "run.lock"
        self._stream: IO[str] | None = None
        self._token: str | None = None

    @staticmethod
    def _process_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            open_process = ctypes.windll.kernel32.OpenProcess
            open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            open_process.restype = wintypes.HANDLE
            wait = ctypes.windll.kernel32.WaitForSingleObject
            wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            wait.restype = wintypes.DWORD
            handle = open_process(0x00100000, False, pid)
            if not handle:
                return ctypes.windll.kernel32.GetLastError() == 5
            try:
                return wait(handle, 0) == 258
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _remove_if_stale(self) -> bool:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            pid = int(payload["pid"])
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return False
        if self._process_alive(pid):
            return False
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        return True

    def __enter__(self) -> RunLock:
        self.root.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            try:
                descriptor = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                break
            except FileExistsError as error:
                if attempt == 0 and self._remove_if_stale():
                    continue
                raise RuntimeError(
                    f"curriculum output is already locked: {self.path}"
                ) from error
        else:
            raise RuntimeError(f"could not acquire curriculum lock: {self.path}")
        self._token = uuid4().hex
        self._stream = os.fdopen(descriptor, "w", encoding="utf-8")
        json.dump({"pid": os.getpid(), "token": self._token}, self._stream)
        self._stream.write("\n")
        self._stream.flush()
        os.fsync(self._stream.fileno())
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if payload.get("token") == self._token:
            self.path.unlink(missing_ok=True)
        self._token = None
