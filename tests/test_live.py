from __future__ import annotations

import os
import tempfile
import unittest
import urllib.error
from typing import Any
from unittest import mock

from adapters.base import TransientError
from adapters.github import GitHubLive, LiveResponse
from adapters.slack import SlackLive
from core.replay import RECORD, REPLAY, Cassette, CassetteMiss


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api", code, "err", {}, None)


class FakeGitHub(GitHubLive):
    def __init__(self, routes: dict[str, Any]) -> None:
        super().__init__(token="t", org="acme-demo")
        self.routes = routes
        self.calls: list[str] = []
        self.params: list[dict] = []

    def _http(self, method: str, path: str, body: Any = None, params: Any = None) -> Any:
        key = f"{method} {path}" + (f"?page={params['page']}" if params and "page" in params else "")
        self.calls.append(key)
        self.params.append(dict(params or {}))
        answer = self.routes.get(key, self.routes.get(f"{method} {path}"))
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            if "/contents/" in path or method == "DELETE":
                return {"status": 404, "json": None, "link": ""}
            raise http_error(404)
        return {"status": 200, "json": answer.get("json"), "link": answer.get("link", "")}


class GitHubLivePlumbing(unittest.TestCase):
    def test_org_members_are_enriched_with_profile_name_and_email(self) -> None:
        gh = FakeGitHub({
            "GET /orgs/acme-demo/members": {"json": [{"login": "dmehta-demo"}, {"login": "priyanair"}]},
            "GET /users/dmehta-demo": {"json": {"login": "dmehta-demo", "name": "Dhruv Mehta", "email": "dhruv@acme.dev"}},
            "GET /users/priyanair": {"json": {"login": "priyanair", "name": "Priya Nair", "email": None}},
        })
        members = gh.all_org_members()
        self.assertEqual(members[0], {"login": "dmehta-demo", "name": "Dhruv Mehta", "email": "dhruv@acme.dev"})
        self.assertIsNone(members[1]["email"])

    def test_pagination_follows_the_link_header(self) -> None:
        gh = FakeGitHub({
            "GET /orgs/acme-demo/repos?page=1": {"json": [{"full_name": "acme-demo/a", "description": ""}], "link": '<x>; rel="next"'},
            "GET /orgs/acme-demo/repos?page=2": {"json": [{"full_name": "acme-demo/b", "description": None}], "link": ""},
        })
        self.assertEqual([r["full_name"] for r in gh.all_repos()], ["acme-demo/a", "acme-demo/b"])

    def test_collaborators_are_direct_grants_only(self) -> None:
        gh = FakeGitHub({"GET /repos/acme-demo/billing/collaborators": {"json": [{"login": "dmehta-demo", "role_name": "write"}]}})
        gh.list_collaborators("acme-demo/billing")
        self.assertEqual(gh.params[-1].get("affiliation"), "direct")

    def test_a_repo_without_workflows_returns_no_files_instead_of_crashing(self) -> None:
        gh = FakeGitHub({})
        self.assertEqual(gh.get_workflow_files("acme-demo/website"), {})

    def test_workflow_bodies_are_decoded(self) -> None:
        import base64

        body = base64.b64encode(b"uses deploy key 'dmehta-laptop'\n").decode()
        gh = FakeGitHub({
            "GET /repos/acme-demo/billing/contents/.github/workflows": {"json": [{"type": "file", "path": ".github/workflows/deploy.yml"}]},
            "GET /repos/acme-demo/billing/contents/.github/workflows/deploy.yml": {"json": {"content": body}},
        })
        files = gh.get_workflow_files("acme-demo/billing")
        self.assertIn("dmehta-laptop", files[".github/workflows/deploy.yml"])

    def test_reads_retry_on_a_transient_error_and_writes_do_not(self) -> None:
        gh = FakeGitHub({"GET /orgs/acme-demo/repos": TransientError(503, "down")})
        with self.assertRaises(TransientError):
            gh.all_repos()
        self.assertEqual(len(gh.calls), 3)
        gh = FakeGitHub({"DELETE /repos/acme-demo/billing/collaborators/dmehta-demo": TransientError(500, "down")})
        with self.assertRaises(TransientError):
            gh.remove_collaborator("acme-demo/billing", "dmehta-demo")
        self.assertEqual(len(gh.calls), 1)


class FakeSlack(SlackLive):
    def __init__(self, routes: dict[str, Any]) -> None:
        super().__init__(token="t")
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []

    def _post(self, method: str, params: dict) -> dict:
        self.calls.append((method, dict(params)))
        answers = self.routes[method]
        if callable(answers):
            return answers(params)
        return answers


class SlackLivePlumbing(unittest.TestCase):
    def test_cursor_pagination_walks_every_page(self) -> None:
        pages = {
            None: {"ok": True, "members": [{"id": "U1", "name": "a", "profile": {}}], "response_metadata": {"next_cursor": "c2"}},
            "c2": {"ok": True, "members": [{"id": "U2", "name": "b", "profile": {"email": "b@acme.dev"}}], "response_metadata": {"next_cursor": ""}},
        }
        sl = FakeSlack({"users.list": lambda p: pages[p.get("cursor")]})
        users = sl.all_users()
        self.assertEqual([u["id"] for u in users], ["U1", "U2"])
        self.assertEqual(users[1]["email"], "b@acme.dev")

    def test_ratelimited_is_transient_and_not_in_channel_is_tolerated(self) -> None:
        sl = FakeSlack({"conversations.kick": {"ok": False, "error": "ratelimited"}})
        with self.assertRaises(TransientError):
            sl.kick_from_channel("C1", "U1")
        sl = FakeSlack({"conversations.kick": {"ok": False, "error": "not_in_channel"}})
        self.assertEqual(sl.kick_from_channel("C1", "U1")["error"], "not_in_channel")

    def test_deactivation_is_refused_off_enterprise_grid(self) -> None:
        with mock.patch.dict(os.environ, {"SLACK_ENTERPRISE_GRID": ""}):
            sl = FakeSlack({"admin.users.remove": {"ok": True}})
        self.assertFalse(sl.supports_deactivation)
        with self.assertRaises(PermissionError):
            sl.deactivate_user("U1")
        self.assertEqual(sl.calls, [])

    def test_deactivation_goes_through_on_enterprise_grid(self) -> None:
        with mock.patch.dict(os.environ, {"SLACK_ENTERPRISE_GRID": "1"}):
            sl = FakeSlack({"admin.users.remove": {"ok": True}})
        self.assertTrue(sl.supports_deactivation)
        self.assertTrue(sl.deactivate_user("U1")["ok"])

    def test_twin_supports_deactivation(self) -> None:
        from adapters.slack import SlackTwin
        from twins.state import TwinState

        self.assertTrue(SlackTwin(TwinState.seed("acme")).supports_deactivation)


if __name__ == "__main__":
    unittest.main()


class CassetteRoundTrip(unittest.TestCase):
    def setUp(self) -> None:
        self.path = os.path.join(tempfile.mkdtemp(), "c.json")

    def record(self, calls: list[Any]) -> None:
        cassette = Cassette(self.path, RECORD)
        for index, outcome in enumerate(calls):
            def call(outcome: Any = outcome) -> Any:
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
            try:
                cassette.around("op", {"i": index}, call)
            except Exception:
                pass
        cassette.save()

    def replay(self, index: int) -> Any:
        def boom() -> Any:
            raise AssertionError("replay must not reach the network")
        return Cassette(self.path, REPLAY).around("op", {"i": index}, boom)

    def test_a_summarising_response_records_its_real_body(self) -> None:
        self.record([LiveResponse(status=200, json=[{"login": "dmehta"}], link="")])
        self.assertEqual(self.replay(0)["json"], [{"login": "dmehta"}])

    def test_an_http_error_is_recorded_and_re_raised(self) -> None:
        self.record([http_error(404)])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.replay(0)
        self.assertEqual(caught.exception.code, 404)

    def test_a_transient_error_is_recorded_and_re_raised(self) -> None:
        self.record([TransientError(500, "err")])
        with self.assertRaises(TransientError):
            self.replay(0)

    def test_a_call_that_was_never_recorded_misses(self) -> None:
        self.record([LiveResponse(status=200, json=None, link="")])
        with self.assertRaises(CassetteMiss):
            self.replay(1)
