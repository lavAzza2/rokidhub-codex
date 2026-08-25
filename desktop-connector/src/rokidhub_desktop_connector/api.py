from __future__ import annotations

import json
import ssl
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi


_HTTPS_CONTEXT = ssl.create_default_context(cafile=certifi.where())


class HubApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class HubApi:
    base_url: str
    connector_id: str
    token: str | None = None
    timeout_seconds: float = 20

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8") if method != "GET" else None
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            headers["X-RokidHub-Connector-ID"] = self.connector_id
        request = Request(
            f"{self.base_url.rstrip('/')}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(  # noqa: S310 - URL is user-configured and validated
                request,
                timeout=self.timeout_seconds,
                context=_HTTPS_CONTEXT,
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                error = json.loads(exc.read().decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                error = {}
            code = str(error.get("error", "http_error"))
            raise HubApiError(f"RokidHub вернул HTTP {exc.code}: {code}", exc.code, code) from exc
        except URLError as exc:
            raise HubApiError(f"Не удалось соединиться с RokidHub: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise HubApiError("RokidHub вернул не-JSON ответ") from exc
        if not isinstance(result, dict):
            raise HubApiError("RokidHub вернул неожиданный JSON")
        return result

    def pairing_start(self, name: str, client_version: str) -> dict[str, Any]:
        return self._request("POST", "/api/v1/desktop/pairing/start", {
            "connector_id": self.connector_id,
            "name": name,
            "client_version": client_version,
        })

    def pairing_poll(self, poll_secret: str) -> dict[str, Any]:
        return self._request("POST", "/api/v1/desktop/pairing/poll", {
            "connector_id": self.connector_id,
            "poll_secret": poll_secret,
        })

    def status(self, client_version: str, default_project_name: str = "") -> dict[str, Any]:
        return self._request("POST", "/api/v1/desktop/status", {
            "client_version": client_version,
            "default_project_name": default_project_name[:80],
        })

    def poll_job(self) -> dict[str, Any]:
        return self._request("POST", "/api/v1/desktop/jobs/poll", {})

    def publish_event(
        self,
        job_id: str,
        lease_id: str,
        sequence: int,
        kind: str,
        message: str = "",
        status: str | None = None,
        error_code: str | None = None,
        project_name: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "lease_id": lease_id,
            "sequence": sequence,
            "type": kind,
            "message": message[:4000],
        }
        if status:
            payload["status"] = status
        if error_code:
            payload["error_code"] = error_code[:64]
        if project_name:
            payload["project_name"] = project_name[:80]
        return self._request("POST", f"/api/v1/desktop/jobs/{job_id}/events", payload)
