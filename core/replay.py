from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Callable, Optional

OFF, RECORD, REPLAY = "off", "record", "replay"


class CassetteMiss(KeyError):
    pass


class Cassette:
    def __init__(self, path: str = "cassettes/default.json", mode: str = OFF) -> None:
        self.path = path
        self.mode = mode
        self.entries: dict[str, Any] = {}
        if mode == REPLAY and os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                self.entries = json.load(fh)
        elif mode == RECORD:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    @staticmethod
    def key(name: str, args: Any) -> str:
        blob = json.dumps({"name": name, "args": args}, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]

    def around(self, name: str, args: Any, call: Callable[[], Any]) -> Any:
        if self.mode == OFF:
            return call()
        key = self.key(name, args)
        seq = self.entries.setdefault(key, []) if self.mode == RECORD else self.entries.get(key)
        if self.mode == REPLAY:
            if not seq:
                raise CassetteMiss(f"no recording for {name} {key}")
            return seq.pop(0)
        value = call()
        seq.append(value)
        return value

    def save(self) -> None:
        if self.mode != RECORD:
            return
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.entries, fh, indent=2, sort_keys=True, default=str)
