"""Reiterable, identity-pinned sequence files; no persistent decoded image cache."""

from __future__ import annotations

import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .dataset import SequenceProvenance, load_sequence


def _discover(roots):
    paths = []
    for raw in roots:
        path = Path(raw)
        if not path.exists():
            raise FileNotFoundError(f"sequence evidence path does not exist: {path}")
        if (path / "manifest.json").is_file():
            paths.append(path)
        elif path.is_dir():
            paths.extend(sorted(item.parent for item in path.rglob("manifest.json")))
    if not paths:
        raise ValueError("sequence evidence paths contain no sequence manifests")
    canonical = tuple(path.resolve(strict=True) for path in paths)
    if len(set(canonical)) != len(canonical):
        raise ValueError("duplicate sequence directory")
    return canonical


def _pins(path):
    result = []
    for name in ("manifest.json", "samples.npz"):
        h = sha256()
        with (path / name).open("rb") as stream:
            before = os.fstat(stream.fileno())
            for block in iter(lambda: stream.read(65536), b""):
                h.update(block)
            after = os.fstat(stream.fileno())

        def fields(s):
            return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)

        if fields(before) != fields(after):
            raise ValueError("sequence corpus file changed while hashing")
        result.append((after.st_size, h.hexdigest()))
    return tuple(result)


@dataclass(frozen=True)
class SequenceSummary:
    path: Path
    provenance: SequenceProvenance
    frames: int
    pins: tuple


class FileSequenceCorpus:
    """Owned file catalog, ordinary drift checks, not hostile filesystem proof.

    One complete sequence is still decoded eagerly. A caller retaining yielded
    objects is outside the catalog's reference lifetime bound.
    """

    def __init__(self, roots, *, loader=load_sequence):
        self._roots = tuple(roots)
        self._paths = _discover(self._roots)
        self._loader = loader
        summaries = []
        for path in self._paths:
            before = _pins(path)
            sequence = loader(path)
            if _pins(path) != before:
                raise ValueError("sequence corpus file changed during catalog decode")
            summaries.append(SequenceSummary(path, sequence.provenance, len(sequence.frames), before))
            del sequence
        self.summaries = tuple(summaries)
        self.frame_count = sum(row.frames for row in self.summaries)

    def __iter__(self):
        if _discover(self._roots) != self._paths:
            raise ValueError("sequence corpus membership changed")
        for row in self.summaries:
            if _pins(row.path) != row.pins:
                raise ValueError("sequence corpus file identity changed")
            sequence = self._loader(row.path)
            if _pins(row.path) != row.pins or sequence.provenance != row.provenance or len(sequence.frames) != row.frames:
                raise ValueError("sequence corpus file/summary changed during decode")
            try:
                yield sequence
            finally:
                del sequence
