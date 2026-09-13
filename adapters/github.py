from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

from adapters.base import AccessItem, DriverBase, Identity, Page, TransientError, slice_page
from twins.driver import TwinDriver


class GitHubDriver(ABC):
    app = "github"

    @abstractmethod
    def list_org_members(self, page: int = 1) -> Page: ...

    @abstractmethod
    def list_repos(self, page: int = 1) -> Page: ...

    @abstractmethod
    def get_repo(self, full_name: str) -> dict: ...

    @abstractmethod
    def list_collaborators(self, full_name: str, page: int = 1) -> Page: ...

    @abstractmethod
    def list_deploy_keys(self, full_name: str, page: int = 1) -> Page: ...

    @abstractmethod
    def get_workflow_files(self, full_name: str) -> dict[str, str]: ...

    @abstractmethod
    def remove_collaborator(self, full_name: str, login: str) -> dict: ...

    @abstractmethod
    def add_collaborator(self, full_name: str, login: str, permission: str) -> dict: ...

    @abstractmethod
    def remove_org_member(self, login: str) -> dict: ...

    @abstractmethod
    def delete_deploy_key(self, full_name: str, key_id: int) -> dict: ...

    @abstractmethod
    def has_access(self, actor: str, resource_name: str) -> Optional[bool]: ...

    def all_org_members(self) -> list[dict]:
        return self._collect("list_org_members", self.list_org_members)  # type: ignore[attr-defined]

    def all_repos(self) -> list[dict]:
        return self._collect("list_repos", self.list_repos)  # type: ignore[attr-defined]

    def all_collaborators(self, full_name: str) -> list[dict]:
        return self._collect("list_collaborators", lambda p: self.list_collaborators(full_name, p))  # type: ignore[attr-defined]

    def all_deploy_keys(self, full_name: str) -> list[dict]:
        return self._collect("list_deploy_keys", lambda p: self.list_deploy_keys(full_name, p))  # type: ignore[attr-defined]

    def inventory(self, identity: Identity, hr: dict) -> list[AccessItem]:
        login = identity.principal_id
        assert login is not None
        items: list[AccessItem] = []
        members = {m["login"] for m in self.all_org_members()}
        org = self.org_name()
        if login in members:
            items.append(AccessItem("github", "org_member", org, org, "member", False, owner=None))
        for repo in self.all_repos():
            name = repo["full_name"]
            collabs = {c["login"]: c["permission"] for c in self.all_collaborators(name)}
            if login in collabs:
                items.append(
                    AccessItem(
                        "github", "repo_collaborator", name, name, collabs[login], False,
                        shared_with=sorted(l for l in collabs if l != login),
                        content=repo.get("description"), content_field="description",
                    )
                )
            keys = self.all_deploy_keys(name)
            mine = [k for k in keys if k.get("created_by") == login or login in k["title"]]
            if not mine:
                continue
            workflows = self.get_workflow_files(name) if mine else {}
            for key in mine:
                used_by = [path for path, body in workflows.items() if key["title"] in body]
                items.append(
                    AccessItem(
                        "github", "deploy_key", str(key["id"]), key["title"],
                        "read_only" if key.get("read_only") else "read_write", False,
                        last_used=key.get("last_used"), owner=key.get("created_by"),
                        hints={"repo": name, "used_by": used_by, "age_hours": self._age_hours(key.get("last_used"))},
                    )
                )
        return items

    @abstractmethod
    def org_name(self) -> str: ...

    def _age_hours(self, ts: Optional[str]) -> Optional[float]:
        if not ts:
            return None
        then = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return round((self.now() - then).total_seconds() / 3600, 1)

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class GitHubTwin(GitHubDriver, TwinDriver):
    def now(self) -> datetime:
        return datetime.fromisoformat(self.state.now.replace("Z", "+00:00"))

    def org_name(self) -> str:
        return self.state.data["github"]["org"]

    def _repo(self, data: dict, full_name: str) -> dict:
        repo = next((r for r in data["github"]["repos"] if r["full_name"] == full_name), None)
        if repo is None:
            raise TransientError(404, f"repo {full_name} not found")
        return repo

    def list_org_members(self, page: int = 1) -> Page:
        return self._read("list_org_members", {"page": page}, lambda d: slice_page(
            [m for m in d["github"]["members"] if m["login"] in d["github"]["members_logins"]], page, self.page_size))

    def list_repos(self, page: int = 1) -> Page:
        return self._read("list_repos", {"page": page}, lambda d: slice_page(
            [{"full_name": r["full_name"], "description": r["description"]} for r in d["github"]["repos"]], page, self.page_size))

    def get_repo(self, full_name: str) -> dict:
        return self._read("get_repo", {"repo": full_name}, lambda d: {
            "full_name": full_name, "description": self._repo(d, full_name)["description"]})

    def list_collaborators(self, full_name: str, page: int = 1) -> Page:
        return self._read("list_collaborators", {"repo": full_name, "page": page},
                          lambda d: slice_page(self._repo(d, full_name)["collaborators"], page, self.page_size))

    def list_deploy_keys(self, full_name: str, page: int = 1) -> Page:
        return self._read("list_deploy_keys", {"repo": full_name, "page": page},
                          lambda d: slice_page(self._repo(d, full_name)["deploy_keys"], page, self.page_size))

    def get_workflow_files(self, full_name: str) -> dict[str, str]:
        return self._read("get_workflow_files", {"repo": full_name}, lambda d: dict(self._repo(d, full_name)["workflows"]))

    def remove_collaborator(self, full_name: str, login: str) -> dict:
        def mutate(d: dict) -> None:
            repo = self._repo(d, full_name)
            repo["collaborators"] = [c for c in repo["collaborators"] if c["login"] != login]
        return self._write("remove_collaborator", {"repo": full_name, "login": login}, mutate)

    def add_collaborator(self, full_name: str, login: str, permission: str) -> dict:
        def mutate(d: dict) -> None:
            repo = self._repo(d, full_name)
            repo["collaborators"] = [c for c in repo["collaborators"] if c["login"] != login]
            repo["collaborators"].append({"login": login, "permission": permission})
        return self._write("add_collaborator", {"repo": full_name, "login": login, "permission": permission}, mutate)

    def remove_org_member(self, login: str) -> dict:
        def mutate(d: dict) -> None:
            d["github"]["members_logins"] = [l for l in d["github"]["members_logins"] if l != login]
            for repo in d["github"]["repos"]:
                repo["collaborators"] = [c for c in repo["collaborators"] if c["login"] != login]
        return self._write("remove_org_member", {"login": login}, mutate)

    def delete_deploy_key(self, full_name: str, key_id: int) -> dict:
        def mutate(d: dict) -> None:
            repo = self._repo(d, full_name)
            repo["deploy_keys"] = [k for k in repo["deploy_keys"] if k["id"] != key_id]
        return self._write("delete_deploy_key", {"repo": full_name, "key_id": key_id}, mutate)

    def has_access(self, actor: str, resource_name: str) -> Optional[bool]:
        return self.state._github_access(actor, resource_name)


class GitHubLive(GitHubDriver, DriverBase):
    def __init__(self, token: Optional[str] = None, org: Optional[str] = None, cassette: Any = None, **kw: Any) -> None:
        DriverBase.__init__(self, **kw)
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self.org = org or os.environ.get("GITHUB_ORG", "")
        self.cassette = cassette
        self.per_page = 30

    def org_name(self) -> str:
        return self.org

    def _http(self, method: str, path: str, body: Optional[dict] = None, params: Optional[dict] = None) -> Any:
        url = f"https://api.github.com{path}"
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "offboard-agent",
        })
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
                return {"status": resp.status, "json": json.loads(raw) if raw else None, "link": resp.headers.get("Link", "")}
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503) or (exc.code == 403 and "rate limit" in exc.read().decode(errors="ignore").lower()):
                raise TransientError(exc.code, exc.reason) from exc
            if exc.code == 404 and method == "DELETE":
                return {"status": 404, "json": None, "link": ""}
            raise

    def _api(self, op: str, args: dict, method: str, path: str, body: Optional[dict] = None, params: Optional[dict] = None) -> Any:
        def call() -> Any:
            if self.cassette is not None:
                return self.cassette.around(op, {**args, "method": method, "path": path}, lambda: self._http(method, path, body, params))
            return self._http(method, path, body, params)
        return self._call(op, args, call)

    def _page(self, op: str, args: dict, path: str, page: int, transform: Any) -> Page:
        resp = self._api(op, {**args, "page": page}, "GET", path, params={"per_page": self.per_page, "page": page})
        items = [transform(x) for x in (resp["json"] or [])]
        has_next = 'rel="next"' in (resp["link"] or "")
        total = (page - 1) * self.per_page + len(items) if not has_next else (page * self.per_page) + 1
        return Page(items=items, total=total, next_page=page + 1 if has_next else None)

    def _collect(self, op: str, fetch: Any) -> list[Any]:
        items: list[Any] = []
        page: Optional[int] = 1
        while page is not None:
            result = fetch(page)
            items.extend(result.items)
            page = result.next_page
        return items

    def list_org_members(self, page: int = 1) -> Page:
        listed = self._page("list_org_members", {}, f"/orgs/{self.org}/members", page, lambda m: {"login": m["login"]})
        return Page(items=[self._profile(m["login"]) for m in listed.items], total=listed.total, next_page=listed.next_page)

    def _profile(self, login: str) -> dict:
        resp = self._api("list_org_members", {"login": login}, "GET", f"/users/{login}")
        user = resp["json"] or {}
        return {"login": login, "name": user.get("name"), "email": user.get("email")}

    def list_repos(self, page: int = 1) -> Page:
        return self._page("list_repos", {}, f"/orgs/{self.org}/repos", page,
                          lambda r: {"full_name": r["full_name"], "description": r.get("description")})

    def get_repo(self, full_name: str) -> dict:
        resp = self._api("get_repo", {"repo": full_name}, "GET", f"/repos/{full_name}")
        return {"full_name": full_name, "description": resp["json"].get("description")}

    def list_collaborators(self, full_name: str, page: int = 1) -> Page:
        return self._page("list_collaborators", {"repo": full_name}, f"/repos/{full_name}/collaborators", page,
                          lambda c: {"login": c["login"], "permission": c.get("role_name", "write")})

    def list_deploy_keys(self, full_name: str, page: int = 1) -> Page:
        return self._page("list_deploy_keys", {"repo": full_name}, f"/repos/{full_name}/keys", page,
                          lambda k: {"id": k["id"], "title": k["title"], "read_only": k.get("read_only", True),
                                     "created_by": (k.get("added_by") or ""), "last_used": k.get("last_used")})

    def get_workflow_files(self, full_name: str) -> dict[str, str]:
        import base64
        try:
            resp = self._api("get_workflow_files", {"repo": full_name}, "GET", f"/repos/{full_name}/contents/.github/workflows")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {}
            raise
        files: dict[str, str] = {}
        for entry in resp["json"] or []:
            if entry.get("type") != "file":
                continue
            content = self._api("get_workflow_files", {"repo": full_name, "path": entry["path"]}, "GET", f"/repos/{full_name}/contents/{entry['path']}")
            files[entry["path"]] = base64.b64decode(content["json"].get("content", "")).decode(errors="ignore")
        return files

    def remove_collaborator(self, full_name: str, login: str) -> dict:
        return self._api("remove_collaborator", {"repo": full_name, "login": login}, "DELETE", f"/repos/{full_name}/collaborators/{login}")

    def add_collaborator(self, full_name: str, login: str, permission: str) -> dict:
        return self._api("add_collaborator", {"repo": full_name, "login": login, "permission": permission}, "PUT",
                         f"/repos/{full_name}/collaborators/{login}", body={"permission": permission})

    def remove_org_member(self, login: str) -> dict:
        return self._api("remove_org_member", {"login": login}, "DELETE", f"/orgs/{self.org}/members/{login}")

    def delete_deploy_key(self, full_name: str, key_id: int) -> dict:
        return self._api("delete_deploy_key", {"repo": full_name, "key_id": key_id}, "DELETE", f"/repos/{full_name}/keys/{key_id}")

    def has_access(self, actor: str, resource_name: str) -> Optional[bool]:
        if resource_name == self.org:
            return any(m["login"] == actor for m in self.all_org_members())
        if "/" in resource_name:
            return any(c["login"] == actor for c in self.all_collaborators(resource_name))
        return None
