from __future__ import annotations

import hashlib
import time
import sys
import tempfile
from pathlib import Path
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Protocol

from .api import HubApi


class JobEngine(Protocol):
    def default_project_name(self) -> str: ...

    def project_name(self, job: dict[str, Any]) -> str: ...

    def execute(self, job: dict[str, Any]) -> str: ...

    def close(self) -> None: ...


class MockEngine:
    def __init__(self, allowed_root: str):
        self.allowed_root = allowed_root

    def execute(self, job: dict[str, Any]) -> str:
        action = str(job.get("action", ""))
        if action == "select_project":
            return f"Mock: выбран проект {str(job.get('prompt', '')).strip()}."
        if action == "interrupt":
            return "Mock: активная задача остановлена."
        if action == "steer":
            return "Mock: уточнение принято для активной задачи."
        return "Mock: запрос обработан в безопасном read-only режиме; локальные файлы не читались."

    def default_project_name(self) -> str:
        return Path(self.allowed_root).name

    def project_name(self, job: dict[str, Any]) -> str:
        if str(job.get("action", "")) == "select_project":
            return _public_project_name(str(job.get("prompt", "")))
        return self.default_project_name()

    def close(self) -> None:
        return


class ConnectorService:
    def __init__(self, api: HubApi, engine: JobEngine, client_version: str):
        self.api = api
        self.engine = engine
        self.client_version = client_version

    def run(self, once: bool = False) -> None:
        self.api.status(self.client_version, _engine_project_name(self.engine, None))
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rokidhub-codex-job")
        active: Future[None] | None = None
        try:
            while True:
                response = self.api.poll_job()
                job = response.get("job")
                if not isinstance(job, dict):
                    if once:
                        return
                    time.sleep(max(1, min(int(response.get("poll_after_seconds", 2)), 15)))
                    continue
                if once:
                    self._handle(job)
                    return
                action = str(job.get("action", ""))
                if action in {"steer", "interrupt"} and active is not None and not active.done():
                    # Control calls must reach app-server while the primary turn is
                    # still active, so they bypass the single-worker job queue.
                    self._handle(job)
                else:
                    active = executor.submit(self._handle, job)
        finally:
            executor.shutdown(wait=True)
            self.engine.close()

    def _handle(self, job: dict[str, Any]) -> None:
        job_id = str(job["job_id"])
        lease_id = str(job["lease_id"])
        sequence = 1
        try:
            project_name = _engine_project_name(self.engine, job)
        except Exception as exc:
            spoken_project = str(job.get("prompt", "")).strip()
            print(
                f"Job {job_id} project resolution failed locally: "
                f"prompt={spoken_project!r}; {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            self.api.publish_event(
                job_id,
                lease_id,
                sequence,
                "error",
                "Локальный Connector не смог выбрать разрешённый проект.",
                error_code=type(exc).__name__,
            )
            return
        self.api.publish_event(
            job_id,
            lease_id,
            sequence,
            "status",
            "Codex анализирует",
            status="running",
            project_name=project_name,
        )
        sequence += 1
        temporary: tempfile.TemporaryDirectory[str] | None = None
        try:
            temporary = self._prepare_attachment(job)
            result = self.engine.execute(job)
        except Exception as exc:
            print(f"Job {job_id} failed locally: {type(exc).__name__}: {exc}", file=sys.stderr)
            self.api.publish_event(
                job_id,
                lease_id,
                sequence,
                "error",
                "Локальный Codex не завершил задачу. Подробности доступны только в окне Connector.",
                error_code=type(exc).__name__,
            )
            return
        finally:
            job.pop("local_image_path", None)
            if temporary is not None:
                temporary.cleanup()
        self.api.publish_event(job_id, lease_id, sequence, "final", result[:4000], project_name=project_name)

    def _prepare_attachment(self, job: dict[str, Any]) -> tempfile.TemporaryDirectory[str] | None:
        metadata = job.get("attachment")
        if metadata is None:
            return None
        if not isinstance(metadata, dict):
            raise ValueError("Некорректные метаданные фото")
        if str(metadata.get("mime_type", "")) != "image/jpeg":
            raise ValueError("Connector принимает только JPEG с камеры очков")
        expected_size = int(metadata.get("byte_size", 0))
        expected_sha256 = str(metadata.get("sha256", "")).lower()
        if expected_size <= 0 or expected_size > 5 * 1024 * 1024:
            raise ValueError("Некорректный размер фото")
        if len(expected_sha256) != 64 or any(char not in "0123456789abcdef" for char in expected_sha256):
            raise ValueError("Некорректная контрольная сумма фото")
        content = self.api.download_attachment(str(job["job_id"]), str(job["lease_id"]))
        if len(content) != expected_size or hashlib.sha256(content).hexdigest() != expected_sha256:
            raise ValueError("Фото повреждено при передаче")
        if len(content) < 4 or not content.startswith(b"\xff\xd8\xff") or not content.endswith(b"\xff\xd9"):
            raise ValueError("Полученный файл не является JPEG")
        temporary = tempfile.TemporaryDirectory(prefix="rokidhub-codex-photo-")
        image_path = Path(temporary.name) / "capture.jpg"
        image_path.write_bytes(content)
        job["local_image_path"] = str(image_path)
        return temporary


def _engine_project_name(engine: JobEngine, job: dict[str, Any] | None) -> str:
    method_name = "default_project_name" if job is None else "project_name"
    method = getattr(engine, method_name, None)
    if not callable(method):
        return ""
    value = method() if job is None else method(job)
    return _public_project_name(str(value))


def _public_project_name(value: str) -> str:
    return " ".join(value.replace("/", " ").replace("\\", " ").split())[:80]
