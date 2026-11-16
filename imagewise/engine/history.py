"""Undo / redo history (no UI code).

Stores snapshots of the whole editing state. Snapshots share the big images by
reference, so they are tiny. A snapshot has a `key` (cheap to compare) and
`data` (what is needed to restore it).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MAX_STATES = 100


@dataclass
class Snapshot:
    key: Any
    data: Any


class History:
    def __init__(self):
        self._states: list[Snapshot] = []
        self._index = -1

    def reset(self, snapshot: Snapshot) -> None:
        """Start a fresh history (for example when a new image is opened)."""
        self._states, self._index = [snapshot], 0

    @property
    def current_key(self):
        return self._states[self._index].key if self._states else None

    def push(self, snapshot: Snapshot) -> bool:
        """Record a new state after the current one (dropping any redo states)."""
        if not self._states:
            self.reset(snapshot)
            return True
        if snapshot.key == self.current_key:
            return False
        del self._states[self._index + 1:]
        self._states.append(snapshot)
        if len(self._states) > MAX_STATES:
            del self._states[0]
        self._index = len(self._states) - 1
        return True

    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return 0 <= self._index < len(self._states) - 1

    def undo(self) -> Snapshot | None:
        if self.can_undo:
            self._index -= 1
            return self._states[self._index]
        return None

    def redo(self) -> Snapshot | None:
        if self.can_redo:
            self._index += 1
            return self._states[self._index]
        return None
