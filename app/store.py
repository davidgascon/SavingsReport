"""The single JSON data file. The editor is the only writer (SPEC.md: Editor features)."""
from __future__ import annotations

import copy
import io
import json
import os
import threading
import uuid

DEFAULT_DATA = {
    "version": 1,
    "settings": {"rack_online_since": None},
    "categories": ["Hardware", "Software", "Subscriptions", "Services", "Other"],
    "people": ["Me"],
    "entries": [],
    "power_readings": [],
    "rates": [],
}

_lock = threading.RLock()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def load(path: str) -> dict:
    with _lock:
        if not os.path.exists(path):
            return copy.deepcopy(DEFAULT_DATA)
        with io.open(path, encoding="utf-8") as f:
            data = json.load(f)
    for key, value in DEFAULT_DATA.items():
        data.setdefault(key, copy.deepcopy(value))
    return data


def save(path: str, data: dict) -> None:
    """Atomic write: a crash mid-save never leaves a half-written file."""
    with _lock:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)


def write_text(path: str, text: str) -> None:
    with _lock:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
