from __future__ import annotations

import hashlib
import importlib
import json
import os
import urllib.error
from typing import Any, Callable, Optional

OFF, RECORD, REPLAY = "off", "record", "replay"


class CassetteMiss(KeyError):
    pass


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _plain(dict.__getitem__(value, k)) for k in dict.keys(value)}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _capture(exc: BaseException) -> dict:
    kind = type(exc)
    record = {"type": f"{kind.__module__}.{kind.__qualname__}", "args": [str(a) for a in exc.args]}
    if isinstance(exc, urllib.error.HTTPError):
        record["code"] = exc.code
        record["reason"] = str(exc.reason)
        record["url"] = exc.url
    return record


def _rebuild(record: dict) -> BaseException:
    if "code" in record:
        return urllib.error.HTTPError(record.get("url", ""), record["code"], record.get("reason", ""), {}, None)  # type: ignore[arg-type]
    module, _, name = record["type"].rpartition(".")
    try:
        kind = getattr(importlib.import_module(module), name)
        return kind(*record["args"])
    except Exception:
        return RuntimeError(f"{record['type']}: {' '.join(record['args'])}")


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
        if self.mode == REPLAY:
            seq = self.entries.get(key)
            if not seq:
                raise CassetteMiss(f"no recording for {name} {key}")
            entry = seq.pop(0)
            if isinstance(entry, dict) and "__error__" in entry:
                raise _rebuild(entry["__error__"])
            return entry
        seq = self.entries.setdefault(key, [])
        try:
            value = call()
        except Exception as exc:
            seq.append({"__error__": _capture(exc)})
            raise
        seq.append(_plain(value))
        return value

    def save(self) -> None:
        if self.mode != RECORD:
            return
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.entries, fh, indent=2, sort_keys=True, default=str)
