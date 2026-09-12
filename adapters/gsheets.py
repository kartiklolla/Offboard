from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any, Optional

from adapters.base import AccessItem, DriverBase, Identity, TransientError
from twins.driver import TwinDriver


class SheetsDriver(ABC):
    app = "sheets"

    @abstractmethod
    def read_rows(self, sheet_id: str) -> list[list[Any]]: ...

    @abstractmethod
    def append_rows(self, sheet_id: str, rows: list[list[Any]]) -> dict: ...

    @abstractmethod
    def delete_rows(self, sheet_id: str, start: int, count: int) -> dict: ...

    def inventory(self, identity: Identity, hr: dict) -> list[AccessItem]:
        return []

    def has_access(self, actor: str, resource_name: str) -> Optional[bool]:
        return None


class SheetsTwin(SheetsDriver, TwinDriver):
    def _sheet(self, data: dict, sheet_id: str) -> dict:
        sheet = data["sheets"].get(sheet_id)
        if sheet is None:
            raise TransientError(404, f"sheet {sheet_id} not found")
        return sheet

    def read_rows(self, sheet_id: str) -> list[list[Any]]:
        return self._read("read_rows", {"sheet": sheet_id}, lambda d: [list(r) for r in self._sheet(d, sheet_id)["rows"]])

    def append_rows(self, sheet_id: str, rows: list[list[Any]]) -> dict:
        def mutate(d: dict) -> dict:
            sheet = self._sheet(d, sheet_id)
            start = len(sheet["rows"])
            sheet["rows"].extend([list(r) for r in rows])
            return {"start_row": start, "count": len(rows)}
        return self._write("append_rows", {"sheet": sheet_id, "count": len(rows)}, mutate)

    def delete_rows(self, sheet_id: str, start: int, count: int) -> dict:
        def mutate(d: dict) -> None:
            sheet = self._sheet(d, sheet_id)
            del sheet["rows"][start : start + count]
        return self._write("delete_rows", {"sheet": sheet_id, "start": start, "count": count}, mutate)


class SheetsLive(SheetsDriver, DriverBase):
    def __init__(self, cassette: Any = None, **kw: Any) -> None:
        DriverBase.__init__(self, **kw)
        self.cassette = cassette
        self._service: Any = None

    def service(self) -> Any:
        if self._service is None:
            try:
                from google.oauth2.credentials import Credentials
                from googleapiclient.discovery import build
            except ImportError as exc:
                raise RuntimeError("live Sheets needs google-api-python-client and google-auth") from exc
            creds = Credentials(
                None,
                refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
                client_id=os.environ["GOOGLE_CLIENT_ID"],
                client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
                token_uri="https://oauth2.googleapis.com/token",
            )
            self._service = build("sheets", "v4", credentials=creds, cache_discovery=False)
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

    def read_rows(self, sheet_id: str) -> list[list[Any]]:
        resp = self._api("read_rows", {"sheet": sheet_id}, lambda: self.service().spreadsheets().values().get(spreadsheetId=sheet_id, range="A2:Z").execute())
        return resp.get("values", [])

    def append_rows(self, sheet_id: str, rows: list[list[Any]]) -> dict:
        before = len(self.read_rows(sheet_id))
        self._api("append_rows", {"sheet": sheet_id, "count": len(rows)}, lambda: self.service().spreadsheets().values().append(
            spreadsheetId=sheet_id, range="A1", valueInputOption="RAW", insertDataOption="INSERT_ROWS", body={"values": rows}).execute())
        return {"ok": True, "start_row": before, "count": len(rows)}

    def delete_rows(self, sheet_id: str, start: int, count: int) -> dict:
        body = {"requests": [{"deleteDimension": {"range": {"sheetId": 0, "dimension": "ROWS", "startIndex": start + 1, "endIndex": start + 1 + count}}}]}
        return self._api("delete_rows", {"sheet": sheet_id, "start": start, "count": count}, lambda: self.service().spreadsheets().batchUpdate(spreadsheetId=sheet_id, body=body).execute())
