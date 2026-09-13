from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Optional

from adapters.base import AccessItem, DriverBase, Identity, Page, TransientError, slice_page
from twins.driver import TwinDriver


class SlackDriver(ABC):
    app = "slack"
    supports_deactivation = True

    @abstractmethod
    def list_users(self, page: int = 1) -> Page: ...

    @abstractmethod
    def get_user(self, user_id: str) -> dict: ...

    @abstractmethod
    def list_channels(self, page: int = 1) -> Page: ...

    @abstractmethod
    def list_channel_members(self, channel_id: str, page: int = 1) -> Page: ...

    @abstractmethod
    def kick_from_channel(self, channel_id: str, user_id: str) -> dict: ...

    @abstractmethod
    def invite_to_channel(self, channel_id: str, user_id: str) -> dict: ...

    @abstractmethod
    def deactivate_user(self, user_id: str) -> dict: ...

    @abstractmethod
    def reactivate_user(self, user_id: str) -> dict: ...

    @abstractmethod
    def post_message(self, channel_id: str, text: str) -> dict: ...

    @abstractmethod
    def delete_message(self, channel_id: str, ts: str) -> dict: ...

    @abstractmethod
    def has_access(self, actor: str, resource_name: str) -> Optional[bool]: ...

    def all_users(self) -> list[dict]:
        return self._collect("list_users", self.list_users)  # type: ignore[attr-defined]

    def all_channels(self) -> list[dict]:
        return self._collect("list_channels", self.list_channels)  # type: ignore[attr-defined]

    def all_channel_members(self, channel_id: str) -> list[str]:
        return self._collect("list_channel_members", lambda p: self.list_channel_members(channel_id, p))  # type: ignore[attr-defined]

    def channel_by_name(self, name: str) -> Optional[dict]:
        return next((c for c in self.all_channels() if c["name"] == name.lstrip("#")), None)

    def inventory(self, identity: Identity, hr: dict) -> list[AccessItem]:
        uid = identity.principal_id
        assert uid is not None
        user = self.get_user(uid)
        items = [AccessItem("slack", "user", uid, "slack_account", "member", False,
                            hints={"handle": user.get("name"), "deleted": user.get("deleted", False)})]
        for channel in self.all_channels():
            members = self.all_channel_members(channel["id"])
            if uid not in members:
                continue
            items.append(
                AccessItem(
                    "slack", "channel_member", channel["id"], "#" + channel["name"], "member", True,
                    shared_with=sorted(m for m in members if m != uid),
                    content=channel.get("topic"), content_field="topic",
                    hints={"is_private": channel.get("is_private", False)},
                )
            )
        return items


class SlackTwin(SlackDriver, TwinDriver):
    def _user(self, data: dict, user_id: str) -> dict:
        user = next((u for u in data["slack"]["users"] if u["id"] == user_id), None)
        if user is None:
            raise TransientError(404, f"user {user_id} not found")
        return user

    def _channel(self, data: dict, channel_id: str) -> dict:
        channel = next((c for c in data["slack"]["channels"] if c["id"] == channel_id), None)
        if channel is None:
            raise TransientError(404, f"channel {channel_id} not found")
        return channel

    def list_users(self, page: int = 1) -> Page:
        return self._read("list_users", {"page": page}, lambda d: slice_page(
            [dict(u) for u in d["slack"]["users"] if not u.get("is_bot")], page, self.page_size))

    def get_user(self, user_id: str) -> dict:
        return self._read("get_user", {"user": user_id}, lambda d: dict(self._user(d, user_id)))

    def list_channels(self, page: int = 1) -> Page:
        return self._read("list_channels", {"page": page}, lambda d: slice_page(
            [{k: c[k] for k in ("id", "name", "is_private", "topic")} for c in d["slack"]["channels"]], page, self.page_size))

    def list_channel_members(self, channel_id: str, page: int = 1) -> Page:
        return self._read("list_channel_members", {"channel": channel_id, "page": page},
                          lambda d: slice_page(list(self._channel(d, channel_id)["members"]), page, self.page_size))

    def kick_from_channel(self, channel_id: str, user_id: str) -> dict:
        def mutate(d: dict) -> None:
            ch = self._channel(d, channel_id)
            ch["members"] = [m for m in ch["members"] if m != user_id]
        return self._write("kick_from_channel", {"channel": channel_id, "user": user_id}, mutate)

    def invite_to_channel(self, channel_id: str, user_id: str) -> dict:
        def mutate(d: dict) -> None:
            ch = self._channel(d, channel_id)
            if user_id not in ch["members"]:
                ch["members"].append(user_id)
        return self._write("invite_to_channel", {"channel": channel_id, "user": user_id}, mutate)

    def deactivate_user(self, user_id: str) -> dict:
        def mutate(d: dict) -> None:
            self._user(d, user_id)["deleted"] = True
            for ch in d["slack"]["channels"]:
                ch["members"] = [m for m in ch["members"] if m != user_id]
        return self._write("deactivate_user", {"user": user_id}, mutate)

    def reactivate_user(self, user_id: str) -> dict:
        return self._write("reactivate_user", {"user": user_id}, lambda d: self._user(d, user_id).__setitem__("deleted", False))

    def post_message(self, channel_id: str, text: str) -> dict:
        def mutate(d: dict) -> dict:
            ch = self._channel(d, channel_id)
            ts = f"{len(ch['messages']) + 1}.000"
            ch["messages"].append({"ts": ts, "text": text, "user": "U_OFFBOARD_BOT"})
            return {"ts": ts}
        return self._write("post_message", {"channel": channel_id, "chars": len(text)}, mutate)

    def delete_message(self, channel_id: str, ts: str) -> dict:
        def mutate(d: dict) -> None:
            ch = self._channel(d, channel_id)
            ch["messages"] = [m for m in ch["messages"] if m["ts"] != ts]
        return self._write("delete_message", {"channel": channel_id, "ts": ts}, mutate)

    def has_access(self, actor: str, resource_name: str) -> Optional[bool]:
        return self.state._slack_access(actor, resource_name)


class SlackLive(SlackDriver, DriverBase):
    def __init__(self, token: Optional[str] = None, cassette: Any = None, **kw: Any) -> None:
        DriverBase.__init__(self, **kw)
        self.token = token or os.environ.get("SLACK_BOT_TOKEN", "")
        self.cassette = cassette
        self.limit = 100
        self.supports_deactivation = os.environ.get("SLACK_ENTERPRISE_GRID", "").lower() in ("1", "true", "yes")
        self._cursors: dict[str, dict[int, str]] = {}

    def _post(self, method: str, params: dict) -> dict:
        req = urllib.request.Request(
            f"https://slack.com/api/{method}",
            data=urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}).encode(),
            method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503):
                raise TransientError(exc.code, exc.reason) from exc
            raise

    def _http(self, method: str, params: dict) -> dict:
        payload = self._post(method, params)
        if not payload.get("ok"):
            err = payload.get("error", "unknown")
            if err in ("ratelimited", "internal_error", "service_unavailable"):
                raise TransientError(429 if err == "ratelimited" else 500, err)
            if err in ("not_in_channel", "user_not_found", "already_in_channel", "message_not_found"):
                return payload
            raise RuntimeError(f"slack {method}: {err}")
        return payload

    def _api(self, op: str, args: dict, method: str, params: dict) -> dict:
        def call() -> dict:
            if self.cassette is not None:
                return self.cassette.around(op, {**args, "method": method}, lambda: self._http(method, params))
            return self._http(method, params)
        return self._call(op, args, call)

    def _paged(self, op: str, args: dict, method: str, params: dict, key: str, page: int, transform: Any) -> Page:
        cursors = self._cursors.setdefault(op + json.dumps(args, sort_keys=True), {})
        cursor = cursors.get(page) if page > 1 else None
        if page > 1 and cursor is None:
            return Page(items=[], total=0, next_page=None)
        payload = self._api(op, {**args, "page": page}, method, {**params, "limit": self.limit, "cursor": cursor})
        items = [transform(x) for x in payload.get(key, [])]
        nxt = (payload.get("response_metadata") or {}).get("next_cursor") or None
        if nxt:
            cursors[page + 1] = nxt
        total = (page - 1) * self.limit + len(items) + (1 if nxt else 0)
        return Page(items=items, total=total, next_page=page + 1 if nxt else None)

    def _collect(self, op: str, fetch: Any) -> list[Any]:
        items: list[Any] = []
        page: Optional[int] = 1
        while page is not None:
            result = fetch(page)
            items.extend(result.items)
            page = result.next_page
        return items

    @staticmethod
    def _user_view(u: dict) -> dict:
        profile = u.get("profile") or {}
        return {"id": u["id"], "name": u.get("name"), "real_name": u.get("real_name") or profile.get("real_name"),
                "email": profile.get("email"), "title": profile.get("title"), "deleted": u.get("deleted", False), "is_bot": u.get("is_bot", False)}

    def list_users(self, page: int = 1) -> Page:
        return self._paged("list_users", {}, "users.list", {}, "members", page, self._user_view)

    def get_user(self, user_id: str) -> dict:
        return self._user_view(self._api("get_user", {"user": user_id}, "users.info", {"user": user_id})["user"])

    def list_channels(self, page: int = 1) -> Page:
        return self._paged("list_channels", {}, "conversations.list", {"types": "public_channel,private_channel", "exclude_archived": "true"},
                           "channels", page, lambda c: {"id": c["id"], "name": c["name"], "is_private": c.get("is_private", False),
                                                       "topic": (c.get("topic") or {}).get("value", "")})

    def list_channel_members(self, channel_id: str, page: int = 1) -> Page:
        return self._paged("list_channel_members", {"channel": channel_id}, "conversations.members", {"channel": channel_id}, "members", page, lambda m: m)

    def kick_from_channel(self, channel_id: str, user_id: str) -> dict:
        return self._api("kick_from_channel", {"channel": channel_id, "user": user_id}, "conversations.kick", {"channel": channel_id, "user": user_id})

    def invite_to_channel(self, channel_id: str, user_id: str) -> dict:
        return self._api("invite_to_channel", {"channel": channel_id, "user": user_id}, "conversations.invite", {"channel": channel_id, "users": user_id})

    def deactivate_user(self, user_id: str) -> dict:
        if not self.supports_deactivation:
            raise PermissionError("admin.users.remove needs Enterprise Grid; set SLACK_ENTERPRISE_GRID=1 on a Grid workspace")
        return self._api("deactivate_user", {"user": user_id}, "admin.users.remove", {"user_id": user_id})

    def reactivate_user(self, user_id: str) -> dict:
        raise RuntimeError("reactivate_user is not available on this workspace plan; see the undo record")

    def post_message(self, channel_id: str, text: str) -> dict:
        return self._api("post_message", {"channel": channel_id, "chars": len(text)}, "chat.postMessage", {"channel": channel_id, "text": text})

    def delete_message(self, channel_id: str, ts: str) -> dict:
        return self._api("delete_message", {"channel": channel_id, "ts": ts}, "chat.delete", {"channel": channel_id, "ts": ts})

    def has_access(self, actor: str, resource_name: str) -> Optional[bool]:
        user = next((u for u in self.all_users() if u.get("email") == actor), None)
        if user is None:
            return False
        if resource_name == "slack_account":
            return not user["deleted"]
        channel = self.channel_by_name(resource_name)
        if channel is None:
            return None
        return user["id"] in self.all_channel_members(channel["id"])
