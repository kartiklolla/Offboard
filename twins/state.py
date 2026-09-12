from __future__ import annotations

import copy
import json
import os
from typing import Any, Optional

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture_path(seed: str) -> str:
    for ext in ("json", "yaml", "yml"):
        candidate = os.path.join(FIXTURES_DIR, f"{seed}.{ext}")
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError(f"no fixture for seed {seed!r} in {FIXTURES_DIR}")


def _read(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        if path.endswith((".yaml", ".yml")):
            try:
                import yaml
            except ImportError as exc:
                raise RuntimeError("YAML fixture requested but pyyaml is not installed") from exc
            return yaml.safe_load(fh)
        return json.load(fh)


class TwinState:
    def __init__(self, data: dict) -> None:
        self._pristine = copy.deepcopy(data)
        self.data: dict = copy.deepcopy(data)
        self.stale: dict = copy.deepcopy(data)
        self.write_count = 0

    @classmethod
    def load(cls, path: str) -> "TwinState":
        return cls(_read(path))

    @classmethod
    def seed(cls, seed: str) -> "TwinState":
        return cls.load(fixture_path(seed))

    def reset(self) -> None:
        self.data = copy.deepcopy(self._pristine)
        self.stale = copy.deepcopy(self._pristine)
        self.write_count = 0

    def snapshot(self) -> dict:
        return copy.deepcopy(self.data)

    def mark_written(self) -> None:
        self.write_count += 1

    def patch(self, ops: list[dict]) -> None:
        for op in ops:
            target = self._resolve(op["path"])
            parent, last = target
            if op["op"] == "set":
                parent[last] = op["value"]
            elif op["op"] == "delete":
                if isinstance(parent, list):
                    parent.pop(int(last))
                else:
                    parent.pop(last, None)
            else:
                raise ValueError(f"unknown patch op {op['op']!r}")
        self.stale = copy.deepcopy(self.data)
        self._pristine = copy.deepcopy(self.data)

    def _resolve(self, path: str) -> tuple[Any, Any]:
        parts = path.split("/")
        node: Any = self.data
        for part in parts[:-1]:
            node = node[int(part)] if isinstance(node, list) else node[part]
        last = parts[-1]
        return node, (int(last) if isinstance(node, list) else last)

    @property
    def now(self) -> str:
        return self.data["now"]

    def person(self, email: str) -> Optional[dict]:
        return next((p for p in self.data["people"] if p["email"] == email), None)

    def has_access(self, actor: str, resource_name: str) -> Optional[bool]:
        checks = [self._github_access, self._slack_access, self._drive_access]
        for check in checks:
            found = check(actor, resource_name)
            if found is not None:
                return found
        return None

    def _github_access(self, actor: str, resource_name: str) -> Optional[bool]:
        gh = self.data["github"]
        login = self._login(actor)
        if resource_name == gh["org"]:
            return login in gh["members_logins"]
        for repo in gh["repos"]:
            if repo["full_name"] == resource_name:
                return login in {c["login"] for c in repo["collaborators"]}
            for key in repo["deploy_keys"]:
                if key["title"] == resource_name:
                    return True
        return None

    def _slack_access(self, actor: str, resource_name: str) -> Optional[bool]:
        sl = self.data["slack"]
        user = next((u for u in sl["users"] if u.get("email") == actor), None)
        for channel in sl["channels"]:
            if channel["name"] == resource_name.lstrip("#"):
                return bool(user) and not user.get("deleted") and user["id"] in channel["members"]
        if resource_name == "slack_account":
            return bool(user) and not user.get("deleted")
        return None

    def _drive_access(self, actor: str, resource_name: str) -> Optional[bool]:
        for f in self.data["drive"]["files"]:
            if f["name"] == resource_name:
                if f["owner"] == actor:
                    return True
                return any(p["email"] == actor for p in f["permissions"])
        return None

    def _login(self, actor: str) -> Optional[str]:
        if "@" not in actor:
            return actor
        person = self.person(actor)
        if person:
            return person.get("github_login")
        return next((m["login"] for m in self.data["github"]["members"] if m.get("email") == actor), None)
