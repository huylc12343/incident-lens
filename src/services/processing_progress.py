"""Live, per-incident workflow progress for polling clients."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock

from src.models.api import ProcessingProgress


class ProcessingProgressRegistry:
    def __init__(self) -> None:
        self._items: dict[str, ProcessingProgress] = {}
        self._lock = RLock()

    def update(self, incident_id: str, stage: str, message: str) -> None:
        with self._lock:
            self._items[incident_id] = ProcessingProgress(
                stage=stage,
                message=message,
                started_at=datetime.now(UTC),
            )

    def get(self, incident_id: str) -> ProcessingProgress | None:
        with self._lock:
            item = self._items.get(incident_id)
            return item.model_copy(deep=True) if item is not None else None

    def delete(self, incident_id: str) -> None:
        with self._lock:
            self._items.pop(incident_id, None)
