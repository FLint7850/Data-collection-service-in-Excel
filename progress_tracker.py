from __future__ import annotations

import copy
import threading
from collections import deque
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional


SECTIONS = ("projects", "news")
CURSOR_PREFIX = "r1:"


@dataclass(frozen=True)
class ProgressChange:
    revision: int
    section: str
    item_id: str
    kind: str
    payload: object


class ProgressTracker:
    """Keeps lightweight entity revisions for cursor-based progress polling.

    Expensive JSON hashing is deliberately avoided. Entity snapshots are
    compared only when application code reports a mutation, never on every
    polling request.
    """

    def __init__(self, journal_limit: int = 4096) -> None:
        self._lock = threading.RLock()
        self._revision = 0
        self._journal: deque[ProgressChange] = deque(maxlen=max(128, journal_limit))
        self._items: Dict[str, Dict[str, Dict[str, object]]] = {
            section: {} for section in SECTIONS
        }
        self._initialized: set[str] = set()

    @property
    def cursor(self) -> str:
        with self._lock:
            return self._format_cursor(self._revision)

    def synchronize(
        self,
        section: str,
        items: Iterable[Dict[str, object]],
        *,
        initialize: bool = False,
    ) -> str:
        self._validate_section(section)
        incoming = {
            str(item["id"]): copy.deepcopy(item)
            for item in items
            if item.get("id") is not None
        }
        with self._lock:
            if initialize and section not in self._initialized:
                self._items[section] = incoming
                self._initialized.add(section)
                return self._format_cursor(self._revision)

            self._initialized.add(section)
            current = self._items[section]
            for item_id, item in incoming.items():
                self._publish_locked(section, item_id, item)
            for item_id in tuple(current):
                if item_id not in incoming:
                    self._remove_locked(section, item_id)
            return self._format_cursor(self._revision)

    def publish(self, section: str, item: Dict[str, object]) -> str:
        self._validate_section(section)
        item_id = str(item.get("id") or "")
        if not item_id:
            return self.cursor
        with self._lock:
            self._initialized.add(section)
            self._publish_locked(section, item_id, copy.deepcopy(item))
            return self._format_cursor(self._revision)

    def remove(self, section: str, item_id: object) -> str:
        self._validate_section(section)
        with self._lock:
            self._initialized.add(section)
            self._remove_locked(section, str(item_id))
            return self._format_cursor(self._revision)

    def delta(
        self,
        previous_cursor: str,
        sections: Iterable[str],
    ) -> Optional[Dict[str, object]]:
        requested = tuple(dict.fromkeys(sections))
        for section in requested:
            self._validate_section(section)

        with self._lock:
            previous_revision = self._parse_cursor(previous_cursor)
            if previous_revision is None or previous_revision > self._revision:
                return None

            earliest_revision = (
                self._journal[0].revision if self._journal else self._revision + 1
            )
            if previous_revision < earliest_revision - 1:
                return None

            payload: Dict[str, object] = {
                "cursor": self._format_cursor(self._revision)
            }
            collapsed: Dict[tuple[str, str], ProgressChange] = {}
            for change in self._journal:
                if (
                    change.revision <= previous_revision
                    or change.section not in requested
                ):
                    continue
                key = (change.section, change.item_id)
                previous = collapsed.get(key)
                collapsed[key] = self._merge_changes(previous, change)

            for section in requested:
                state_changes: List[Dict[str, object]] = []
                upserts: List[Dict[str, object]] = []
                removed_ids: List[str] = []
                for (change_section, item_id), change in collapsed.items():
                    if change_section != section:
                        continue
                    if change.kind == "remove":
                        removed_ids.append(item_id)
                    elif change.kind == "upsert":
                        upserts.append(copy.deepcopy(change.payload))
                    elif change.kind == "state":
                        state_changes.append(
                            {
                                "id": item_id,
                                "state": copy.deepcopy(change.payload),
                            }
                        )
                if state_changes:
                    payload[section] = state_changes
                if upserts:
                    payload[f"upsert_{section}"] = upserts
                if removed_ids:
                    payload[f"removed_{section}_ids"] = removed_ids
            return payload

    def _publish_locked(
        self,
        section: str,
        item_id: str,
        item: Dict[str, object],
    ) -> None:
        previous = self._items[section].get(item_id)
        if previous == item:
            return

        self._items[section][item_id] = item
        if previous is None or self._summary(previous) != self._summary(item):
            self._append_locked(section, item_id, "upsert", item)
            return

        state_delta = self._state_delta(
            previous.get("state"),
            item.get("state"),
        )
        if state_delta:
            self._append_locked(section, item_id, "state", state_delta)

    def _remove_locked(self, section: str, item_id: str) -> None:
        if item_id not in self._items[section]:
            return
        self._items[section].pop(item_id, None)
        self._append_locked(section, item_id, "remove", None)

    def _append_locked(
        self,
        section: str,
        item_id: str,
        kind: str,
        payload: object,
    ) -> None:
        self._revision += 1
        self._journal.append(
            ProgressChange(
                revision=self._revision,
                section=section,
                item_id=item_id,
                kind=kind,
                payload=copy.deepcopy(payload),
            )
        )

    @staticmethod
    def _merge_changes(
        previous: Optional[ProgressChange],
        current: ProgressChange,
    ) -> ProgressChange:
        if previous is None or current.kind in {"remove", "upsert"}:
            return current
        if previous.kind == "remove":
            return current
        if previous.kind == "upsert" and current.kind == "state":
            item = copy.deepcopy(previous.payload)
            if isinstance(item, dict):
                state = dict(item.get("state") or {})
                if isinstance(current.payload, dict):
                    state.update(current.payload)
                item["state"] = state
            return ProgressChange(
                current.revision,
                current.section,
                current.item_id,
                "upsert",
                item,
            )
        if previous.kind == "state" and current.kind == "state":
            state = dict(previous.payload) if isinstance(previous.payload, dict) else {}
            if isinstance(current.payload, dict):
                state.update(current.payload)
            return ProgressChange(
                current.revision,
                current.section,
                current.item_id,
                "state",
                state,
            )
        return current

    @staticmethod
    def _summary(item: Dict[str, object]) -> Dict[str, object]:
        return {key: value for key, value in item.items() if key != "state"}

    @staticmethod
    def _state_delta(previous: object, current: object) -> Dict[str, object]:
        previous_state = previous if isinstance(previous, dict) else {}
        current_state = current if isinstance(current, dict) else {}
        delta = {
            key: copy.deepcopy(value)
            for key, value in current_state.items()
            if key not in previous_state or previous_state[key] != value
        }
        for key in previous_state:
            if key not in current_state:
                delta[key] = None
        return delta

    @staticmethod
    def _format_cursor(revision: int) -> str:
        return f"{CURSOR_PREFIX}{revision}"

    @staticmethod
    def _parse_cursor(cursor: str) -> Optional[int]:
        if not cursor.startswith(CURSOR_PREFIX):
            return None
        try:
            return max(0, int(cursor[len(CURSOR_PREFIX) :]))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _validate_section(section: str) -> None:
        if section not in SECTIONS:
            raise ValueError(f"Unsupported progress section: {section}")
