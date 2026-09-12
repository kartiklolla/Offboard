from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any, Optional

from adapters.base import AccessItem, DriverBase, Identity, Page, TransientError, slice_page
from twins.driver import TwinDriver

INTERNAL_DOMAINS = tuple(d for d in os.environ.get("INTERNAL_DOMAINS", "acme.dev").split(",") if d)


def is_external(email: str, domains: tuple[str, ...] = INTERNAL_DOMAINS) -> bool:
    return not any(email.lower().endswith("@" + d.lower()) for d in domains)


class DriveDriver(ABC):
    app = "drive"

    @abstractmethod
    def list_files(self, page: int = 1) -> Page: ...

    @abstractmethod
    def get_file(self, file_id: str) -> dict: ...

    @abstractmethod
    def list_permissions(self, file_id: str, page: int = 1) -> Page: ...

    @abstractmethod
    def transfer_ownership(self, file_id: str, new_owner: str) -> dict: ...

    @abstractmethod
    def remove_permission(self, file_id: str, permission_id: str) -> dict: ...

    @abstractmethod
    def add_permission(self, file_id: str, email: str, role: str) -> dict: ...

    @abstractmethod
    def has_access(self, actor: str, resource_name: str) -> Optional[bool]: ...

    def all_files(self) -> list[dict]:
        return self._collect("list_files", self.list_files)  # type: ignore[attr-defined]

    def all_permissions(self, file_id: str) -> list[dict]:
        return self._collect("list_permissions", lambda p: self.list_permissions(file_id, p))  # type: ignore[attr-defined]

    def inventory(self, identity: Identity, hr: dict) -> list[AccessItem]:
        email = identity.principal_id
        assert email is not None
        items: list[AccessItem] = []
        for f in self.all_files():
            perms = self.all_permissions(f["id"])
            if f["owner"] == email:
                kind = "folder" if f["mime"] == "folder" else "file"
                internal = [p["email"] for p in perms if not is_external(p["email"])]
                items.append(
                    AccessItem(
                        "drive", kind, f["id"], f["name"], "owner", False,
                        shared_with=sorted(internal), owner=email,
                        content=self.get_file(f["id"]).get("body") if f["mime"] != "folder" else None,
                        content_field="body", hints={"mime": f["mime"]},
                    )
                )
                for p in perms:
                    if is_external(p["email"]):
                        items.append(
                            AccessItem(
                                "drive", "external_share", p["id"], f["name"], p["role"], False,
                                shared_with=[p["email"]], owner=email,
                                hints={"file_id": f["id"], "external_email": p["email"]},
                            )
                        )
                continue
            mine = next((p for p in perms if p["email"] == email), None)
            if mine:
                items.append(
                    AccessItem(
                        "drive", "permission", mine["id"], f["name"], mine["role"], False,
                        owner=f["owner"], hints={"file_id": f["id"], "mime": f["mime"]},
                    )
                )
        return items


class DriveTwin(DriveDriver, TwinDriver):
    def _file(self, data: dict, file_id: str) -> dict:
        f = next((x for x in data["drive"]["files"] if x["id"] == file_id), None)
        if f is None:
            raise TransientError(404, f"file {file_id} not found")
        return f

    def list_files(self, page: int = 1) -> Page:
        return self._read("list_files", {"page": page}, lambda d: slice_page(
            [{k: f[k] for k in ("id", "name", "mime", "owner")} for f in d["drive"]["files"]], page, self.page_size))

    def get_file(self, file_id: str) -> dict:
        return self._read("get_file", {"file": file_id}, lambda d: dict(self._file(d, file_id)))

    def list_permissions(self, file_id: str, page: int = 1) -> Page:
        return self._read("list_permissions", {"file": file_id, "page": page},
                          lambda d: slice_page([dict(p) for p in self._file(d, file_id)["permissions"]], page, self.page_size))

    def transfer_ownership(self, file_id: str, new_owner: str) -> dict:
        def mutate(d: dict) -> None:
            f = self._file(d, file_id)
            previous = f["owner"]
            f["permissions"] = [p for p in f["permissions"] if p["email"] != new_owner]
            f["owner"] = new_owner
            f["permissions"].append({"id": f"P_{file_id}_{previous.split('@')[0]}", "email": previous, "role": "writer"})
        return self._write("transfer_ownership", {"file": file_id, "new_owner": new_owner}, mutate)

    def remove_permission(self, file_id: str, permission_id: str) -> dict:
        def mutate(d: dict) -> None:
            f = self._file(d, file_id)
            f["permissions"] = [p for p in f["permissions"] if p["id"] != permission_id]
        return self._write("remove_permission", {"file": file_id, "permission_id": permission_id}, mutate)

    def add_permission(self, file_id: str, email: str, role: str) -> dict:
        def mutate(d: dict) -> dict:
            f = self._file(d, file_id)
            pid = f"P_{file_id}_{email.split('@')[0]}"
            f["permissions"] = [p for p in f["permissions"] if p["email"] != email]
            f["permissions"].append({"id": pid, "email": email, "role": role})
            return {"permission_id": pid}
        return self._write("add_permission", {"file": file_id, "email": email, "role": role}, mutate)

    def has_access(self, actor: str, resource_name: str) -> Optional[bool]:
        return self.state._drive_access(actor, resource_name)


class DriveLive(DriveDriver, DriverBase):
    def __init__(self, cassette: Any = None, **kw: Any) -> None:
        DriverBase.__init__(self, **kw)
        self.cassette = cassette
        self._service: Any = None
        self._tokens: dict[str, dict[int, str]] = {}

    def service(self) -> Any:
        if self._service is None:
            try:
                from google.oauth2.credentials import Credentials
                from googleapiclient.discovery import build
            except ImportError as exc:
                raise RuntimeError("live Drive needs google-api-python-client and google-auth") from exc
            creds = Credentials(
                None,
                refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
                client_id=os.environ["GOOGLE_CLIENT_ID"],
                client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
                token_uri="https://oauth2.googleapis.com/token",
            )
            self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def _api(self, op: str, args: dict, fn: Any) -> Any:
        def call() -> Any:
            def raw() -> Any:
                try:
                    return fn()
                except Exception as exc:
                    status = getattr(getattr(exc, "resp", None), "status", None)
                    if status in (429, 500, 502, 503):
                        raise TransientError(status, str(exc)) from exc
                    raise
            if self.cassette is not None:
                return self.cassette.around(op, args, raw)
            return raw()
        return self._call(op, args, call)

    def _collect(self, op: str, fetch: Any) -> list[Any]:
        items: list[Any] = []
        page: Optional[int] = 1
        while page is not None:
            result = fetch(page)
            items.extend(result.items)
            page = result.next_page
        return items

    def list_files(self, page: int = 1) -> Page:
        token = self._tokens.setdefault("files", {}).get(page) if page > 1 else None
        resp = self._api("list_files", {"page": page}, lambda: self.service().files().list(
            q="trashed = false", pageSize=100, pageToken=token, corpora="allDrives", includeItemsFromAllDrives=True, supportsAllDrives=True,
            fields="nextPageToken, files(id, name, mimeType, owners(emailAddress))").execute())
        items = [{"id": f["id"], "name": f["name"], "mime": "folder" if f["mimeType"].endswith("folder") else f["mimeType"].split(".")[-1],
                  "owner": (f.get("owners") or [{}])[0].get("emailAddress", "")} for f in resp.get("files", [])]
        nxt = resp.get("nextPageToken")
        if nxt:
            self._tokens["files"][page + 1] = nxt
        return Page(items=items, total=(page - 1) * 100 + len(items) + (1 if nxt else 0), next_page=page + 1 if nxt else None)

    def get_file(self, file_id: str) -> dict:
        meta = self._api("get_file", {"file": file_id}, lambda: self.service().files().get(fileId=file_id, fields="id,name,mimeType,owners(emailAddress)", supportsAllDrives=True).execute())
        body = None
        if meta["mimeType"] == "application/vnd.google-apps.document":
            body = self._api("get_file", {"file": file_id, "export": "text/plain"}, lambda: self.service().files().export(fileId=file_id, mimeType="text/plain").execute().decode(errors="ignore"))
        return {"id": meta["id"], "name": meta["name"], "mime": meta["mimeType"], "owner": (meta.get("owners") or [{}])[0].get("emailAddress", ""), "body": body}

    def list_permissions(self, file_id: str, page: int = 1) -> Page:
        resp = self._api("list_permissions", {"file": file_id, "page": page}, lambda: self.service().permissions().list(
            fileId=file_id, fields="permissions(id, emailAddress, role, type)", supportsAllDrives=True).execute())
        items = [{"id": p["id"], "email": p.get("emailAddress", ""), "role": p["role"]} for p in resp.get("permissions", []) if p.get("type") == "user" and p["role"] != "owner"]
        return Page(items=items, total=len(items), next_page=None)

    def transfer_ownership(self, file_id: str, new_owner: str) -> dict:
        return self._api("transfer_ownership", {"file": file_id, "new_owner": new_owner}, lambda: self.service().permissions().create(
            fileId=file_id, transferOwnership=True, body={"type": "user", "role": "owner", "emailAddress": new_owner}, supportsAllDrives=True).execute())

    def remove_permission(self, file_id: str, permission_id: str) -> dict:
        return self._api("remove_permission", {"file": file_id, "permission_id": permission_id}, lambda: self.service().permissions().delete(
            fileId=file_id, permissionId=permission_id, supportsAllDrives=True).execute() or {"ok": True})

    def add_permission(self, file_id: str, email: str, role: str) -> dict:
        return self._api("add_permission", {"file": file_id, "email": email, "role": role}, lambda: self.service().permissions().create(
            fileId=file_id, body={"type": "user", "role": role, "emailAddress": email}, sendNotificationEmail=False, supportsAllDrives=True).execute())

    def has_access(self, actor: str, resource_name: str) -> Optional[bool]:
        f = next((x for x in self.all_files() if x["name"] == resource_name), None)
        if f is None:
            return None
        if f["owner"] == actor:
            return True
        return any(p["email"] == actor for p in self.all_permissions(f["id"]))
