from __future__ import annotations

import json
import os
import re
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

SCOPES = "https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/spreadsheets"
PORT = 8788
REDIRECT = f"http://localhost:{PORT}/"


def load_env() -> None:
    if os.path.exists(".env"):
        for line in open(".env"):
            if "=" in line and not line.startswith("#"):
                k, v = line.rstrip("\n").split("=", 1)
                os.environ.setdefault(k, v)


def write_env(key: str, value: str) -> None:
    env = open(".env").read() if os.path.exists(".env") else ""
    line = f"{key}={value}"
    env, n = re.subn(rf"^{key}=.*$", line, env, flags=re.M)
    if not n:
        env = env.rstrip("\n") + "\n" + line + "\n"
    open(".env", "w").write(env)


def main() -> int:
    load_env()
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env first", file=sys.stderr)
        return 1
    state = secrets.token_urlsafe(16)
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": REDIRECT, "response_type": "code",
        "scope": SCOPES, "access_type": "offline", "prompt": "consent", "state": state,
    })
    got: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Done, you can close this tab.")

        def log_message(self, *a: object) -> None:
            pass

    HTTPServer.allow_reuse_address = True
    server = HTTPServer(("localhost", PORT), Handler)
    print("opening browser; sign in as the demo Drive owner\n" + url)
    webbrowser.open(url)
    server.handle_request()
    if got.get("state") != state or "code" not in got:
        print("auth failed: " + json.dumps(got), file=sys.stderr)
        return 1
    body = urllib.parse.urlencode({
        "code": got["code"], "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": REDIRECT, "grant_type": "authorization_code",
    }).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", body) as resp:
        tok = json.load(resp)
    if "refresh_token" not in tok:
        print("no refresh_token in response: " + json.dumps(tok), file=sys.stderr)
        return 1
    write_env("GOOGLE_REFRESH_TOKEN", tok["refresh_token"])
    print("\nGOOGLE_REFRESH_TOKEN written to .env")
    return 0


if __name__ == "__main__":
    sys.exit(main())
