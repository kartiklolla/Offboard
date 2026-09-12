from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from adapters.base import RISK, AccessItem
from adapters.registry import Drivers
from agent import policy as P
from core.gate import Action


@dataclass
class PlannedAction:
    action: Action
    precondition: Callable[[], Any]
    describe: Callable[[], str]
    apply: Callable[[], Any]
    postcondition: Callable[[], Any]
    undo: dict
    depends_on: Optional[str] = None

    @property
    def name(self) -> str:
        return self.action.name

    def view(self) -> dict:
        return {"name": self.name, "verb": self.action.verb, "app": self.action.app, "op": self.action.op, "risk": self.action.risk.value, "depends_on": self.depends_on}


def _action(app: str, op: str, args: dict, resource: str, verb: str, item: AccessItem) -> Action:
    return Action(app=app, op=op, args=args, risk=RISK[op], resource=resource, verb=verb, item_key=item.key)


def actions_for(item: AccessItem, disposition: P.Disposition, drivers: Drivers, hr_record: dict) -> list[PlannedAction]:
    if disposition.disposition in (P.ESCALATE, P.NEEDS_HUMAN, P.KEEP):
        return []
    builder = _BUILDERS.get((item.app, item.kind))
    if builder is None:
        return []
    return builder(item, disposition, drivers, hr_record)


def _github_org_member(item: AccessItem, d: P.Disposition, drivers: Drivers, hr: dict) -> list[PlannedAction]:
    gh = drivers.github
    login = hr["github_login"]
    org = item.resource_name
    return [PlannedAction(
        _action("github", "remove_org_member", {"login": login}, org, "revoke", item),
        precondition=lambda: any(m["login"] == login for m in gh.all_org_members()),
        describe=lambda: f"-member {login} from org {org}",
        apply=lambda: gh.remove_org_member(login),
        postcondition=lambda: not any(m["login"] == login for m in gh.all_org_members()),
        undo={"op": "add_org_member", "args": {"login": login, "role": item.role}, "supported": False, "note": "re-adding requires an invitation the user must accept"},
    )]


def _github_repo_collaborator(item: AccessItem, d: P.Disposition, drivers: Drivers, hr: dict) -> list[PlannedAction]:
    gh = drivers.github
    login = hr["github_login"]
    repo = item.resource_name
    return [PlannedAction(
        _action("github", "remove_collaborator", {"repo": repo, "login": login}, repo, "revoke", item),
        precondition=lambda: any(c["login"] == login for c in gh.all_collaborators(repo)),
        describe=lambda: f"-collaborator {login} ({item.role}) on {repo}",
        apply=lambda: gh.remove_collaborator(repo, login),
        postcondition=lambda: not any(c["login"] == login for c in gh.all_collaborators(repo)),
        undo={"op": "add_collaborator", "args": {"repo": repo, "login": login, "permission": item.role}},
    )]


def _github_deploy_key(item: AccessItem, d: P.Disposition, drivers: Drivers, hr: dict) -> list[PlannedAction]:
    gh = drivers.github
    repo = item.hints["repo"]
    key_id = int(item.resource_id)
    title = item.resource_name
    return [PlannedAction(
        _action("github", "delete_deploy_key", {"repo": repo, "key_id": key_id}, title, "revoke", item),
        precondition=lambda: any(k["id"] == key_id for k in gh.all_deploy_keys(repo)),
        describe=lambda: f"-deploy key {title} ({item.role}) on {repo}",
        apply=lambda: gh.delete_deploy_key(repo, key_id),
        postcondition=lambda: not any(k["id"] == key_id for k in gh.all_deploy_keys(repo)),
        undo={"op": "add_deploy_key", "args": {"repo": repo, "title": title, "read_only": item.role == "read_only"}, "supported": False, "note": "the private half of the key is not held; a new key pair would be needed"},
    )]


def _slack_user(item: AccessItem, d: P.Disposition, drivers: Drivers, hr: dict) -> list[PlannedAction]:
    sl = drivers.slack
    uid = item.resource_id
    live = drivers.mode == "live"
    return [PlannedAction(
        _action("slack", "deactivate_user", {"user": uid}, "slack_account", "revoke", item),
        precondition=lambda: not sl.get_user(uid).get("deleted", False),
        describe=lambda: f"-deactivate Slack user {item.hints.get('handle', uid)} ({uid})",
        apply=lambda: sl.deactivate_user(uid),
        postcondition=lambda: sl.get_user(uid).get("deleted", False) is True,
        undo={"op": "reactivate_user", "args": {"user": uid}, "supported": not live, "note": "reactivation needs a workspace admin in the Slack UI on non-Enterprise plans" if live else None},
    )]


def _slack_channel_member(item: AccessItem, d: P.Disposition, drivers: Drivers, hr: dict) -> list[PlannedAction]:
    sl = drivers.slack
    cid = item.resource_id
    uid = item.hints.get("user_id") or hr.get("slack_user_id")
    name = item.resource_name
    return [PlannedAction(
        _action("slack", "kick_from_channel", {"channel": cid, "user": uid}, name, "revoke", item),
        precondition=lambda: uid in sl.all_channel_members(cid),
        describe=lambda: f"-remove {uid} from {name}{' (private)' if item.hints.get('is_private') else ''}",
        apply=lambda: sl.kick_from_channel(cid, uid),
        postcondition=lambda: uid not in sl.all_channel_members(cid),
        undo={"op": "invite_to_channel", "args": {"channel": cid, "user": uid}},
    )]


def _drive_owned(item: AccessItem, d: P.Disposition, drivers: Drivers, hr: dict) -> list[PlannedAction]:
    dr = drivers.drive
    file_id = item.resource_id
    name = item.resource_name
    owner = hr["email"]
    new_owner = d.transfer_to
    if not new_owner:
        return []

    def owner_perm() -> Optional[dict]:
        return next((p for p in dr.all_permissions(file_id) if p["email"] == owner), None)

    def remove_leftover() -> Any:
        perm = owner_perm()
        if perm is None:
            return {"ok": True, "status": 200, "note": "no leftover permission"}
        return dr.remove_permission(file_id, perm["id"])

    transfer = PlannedAction(
        _action("drive", "transfer_ownership", {"file": file_id, "new_owner": new_owner}, name, "transfer", item),
        precondition=lambda: dr.get_file(file_id)["owner"] == owner,
        describe=lambda: f"~owner {name}: {owner} -> {new_owner} (keeps {len(item.shared_with)} existing sharees)",
        apply=lambda: dr.transfer_ownership(file_id, new_owner),
        postcondition=lambda: dr.get_file(file_id)["owner"] == new_owner,
        undo={"op": "transfer_ownership", "args": {"file": file_id, "new_owner": owner}, "supported": drivers.mode != "live", "note": None if drivers.mode != "live" else "transfer back requires the former owner to accept"},
    )
    revoke = PlannedAction(
        _action("drive", "remove_permission", {"file": file_id, "email": owner}, name, "revoke", item),
        precondition=lambda: dr.get_file(file_id)["owner"] != owner and owner_perm() is not None,
        describe=lambda: f"-permission {owner} (writer, left over from transfer) on {name}",
        apply=remove_leftover,
        postcondition=lambda: owner_perm() is None,
        undo={"op": "add_permission", "args": {"file": file_id, "email": owner, "role": "writer"}},
        depends_on=transfer.name,
    )
    return [transfer, revoke]


def _drive_permission(item: AccessItem, d: P.Disposition, drivers: Drivers, hr: dict) -> list[PlannedAction]:
    dr = drivers.drive
    file_id = item.hints["file_id"]
    perm_id = item.resource_id
    email = hr["email"]
    name = item.resource_name
    return [PlannedAction(
        _action("drive", "remove_permission", {"file": file_id, "permission_id": perm_id}, name, "revoke", item),
        precondition=lambda: any(p["id"] == perm_id for p in dr.all_permissions(file_id)),
        describe=lambda: f"-permission {email} ({item.role}) on {name} (owned by {item.owner})",
        apply=lambda: dr.remove_permission(file_id, perm_id),
        postcondition=lambda: not any(p["email"] == email for p in dr.all_permissions(file_id)),
        undo={"op": "add_permission", "args": {"file": file_id, "email": email, "role": item.role}},
    )]


_BUILDERS: dict[tuple[str, str], Callable[..., list[PlannedAction]]] = {
    ("github", "org_member"): _github_org_member,
    ("github", "repo_collaborator"): _github_repo_collaborator,
    ("github", "deploy_key"): _github_deploy_key,
    ("slack", "user"): _slack_user,
    ("slack", "channel_member"): _slack_channel_member,
    ("drive", "folder"): _drive_owned,
    ("drive", "file"): _drive_owned,
    ("drive", "permission"): _drive_permission,
}


def evidence_log_action(drivers: Drivers, sheet_id: str, rows: list[list[Any]]) -> PlannedAction:
    sh = drivers.sheets
    before: dict[str, int] = {}

    def pre() -> bool:
        before["n"] = len(sh.read_rows(sheet_id))
        return True

    return PlannedAction(
        Action("sheets", "append_rows", {"sheet": sheet_id, "count": len(rows)}, RISK["append_rows"], "evidence", "log", None),
        precondition=pre,
        describe=lambda: f"+{len(rows)} evidence rows to sheet {sheet_id}",
        apply=lambda: sh.append_rows(sheet_id, rows),
        postcondition=lambda: len(sh.read_rows(sheet_id)) >= before.get("n", 0) + len(rows),
        undo={"op": "delete_rows", "args": {"sheet": sheet_id, "start": before.get("n", 0), "count": len(rows)}},
    )


def summary_action(drivers: Drivers, channel: dict, text: str, posted: dict) -> PlannedAction:
    sl = drivers.slack
    cid = channel["id"]
    name = "#" + channel["name"]

    undo_args: dict[str, Any] = {"channel": cid, "ts": None}

    def apply() -> Any:
        result = sl.post_message(cid, text)
        posted["ts"] = result.get("ts")
        undo_args["ts"] = posted["ts"]
        return result

    return PlannedAction(
        Action("slack", "post_message", {"channel": cid, "chars": len(text)}, RISK["post_message"], name, "notify", None),
        precondition=lambda: sl.channel_by_name(channel["name"]) is not None,
        describe=lambda: f"+message to {name} ({len(text)} chars, {text.count('[s')} citations)",
        apply=apply,
        postcondition=lambda: bool(posted.get("ts")),
        undo={"op": "delete_message", "args": undo_args, "note": "ts is filled in by apply before the step is written"},
    )
