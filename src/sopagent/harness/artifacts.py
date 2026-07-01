"""Artifact store: persist step outputs to disk."""
from __future__ import annotations

from pathlib import Path


class ArtifactStore:
    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, content: str) -> Path:
        path = self._dir / name
        path.write_text(content, encoding="utf-8")
        return path
