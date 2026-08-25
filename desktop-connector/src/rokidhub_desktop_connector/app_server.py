from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import __version__

from .approval import LocalApprovalHandler
from .config import ConfigStore, ConnectorConfig


class AppServerError(RuntimeError):
    pass


class AppServerClient:
    """Small JSONL client for the versioned `codex app-server` stdio protocol."""

    def __init__(
        self,
        command: list[str],
        cwd: Path,
        approval_handler: Callable[[str, dict[str, Any]], str] | None = None,
    ):
        self.command = command
        self.cwd = cwd
        self.process: subprocess.Popen[str] | None = None
        self._next_id = 1
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._pending_lock = threading.Lock()
        self._notifications: queue.Queue[dict[str, Any]] = queue.Queue()
        self._writer_lock = threading.Lock()
        self.approval_handler = approval_handler

    def start(self) -> None:
        if self.process is not None:
            return
        resolved_command = _resolve_subprocess_command(self.command)
        self.process = subprocess.Popen(
            resolved_command,
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            bufsize=1,
            shell=False,
        )
        threading.Thread(target=self._read_loop, name="codex-app-server-reader", daemon=True).start()
        self.request("initialize", {
            "clientInfo": {
                "name": "rokidhub_desktop_connector",
                "title": "RokidHub Desktop Connector",
                "version": __version__,
            },
        })
        self.notify("initialized", {})

    def close(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if process.stdin:
            process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()

    def request(self, method: str, params: dict[str, Any], timeout: float = 30) -> dict[str, Any]:
        if self.process is None:
            raise AppServerError("codex app-server не запущен")
        with self._pending_lock:
            request_id = self._next_id
            self._next_id += 1
            response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._pending[request_id] = response_queue
        self._send({"method": method, "id": request_id, "params": params})
        try:
            response = response_queue.get(timeout=timeout)
        except queue.Empty as exc:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise AppServerError(f"codex app-server не ответил на {method}") from exc
        if "error" in response:
            error = response["error"]
            message = error.get("message", "unknown error") if isinstance(error, dict) else str(error)
            raise AppServerError(f"{method}: {message}")
        result = response.get("result", {})
        return result if isinstance(result, dict) else {}

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"method": method, "params": params})

    def list_models(self) -> list[dict[str, Any]]:
        """Return picker-visible models advertised by this installed app-server."""
        result = self.request("model/list", {"limit": 100, "includeHidden": False})
        data = result.get("data", [])
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    def wait_notification(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        timeout: float = 3600,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        deferred: list[dict[str, Any]] = []
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AppServerError("Истекло время ожидания события Codex")
                try:
                    notification = self._notifications.get(timeout=min(remaining, 1))
                except queue.Empty:
                    if self.process is None or self.process.poll() is not None:
                        raise AppServerError("codex app-server завершился до окончания turn")
                    continue
                if predicate(notification):
                    return notification
                deferred.append(notification)
        finally:
            for notification in deferred:
                self._notifications.put(notification)

    def _send(self, message: dict[str, Any]) -> None:
        process = self.process
        if process is None or process.stdin is None or process.poll() is not None:
            raise AppServerError("codex app-server недоступен")
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        with self._writer_lock:
            process.stdin.write(f"{line}\n")
            process.stdin.flush()

    def _read_loop(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            request_id = message.get("id")
            if isinstance(request_id, int) and ("result" in message or "error" in message):
                with self._pending_lock:
                    target = self._pending.pop(request_id, None)
                if target:
                    target.put(message)
                continue
            if isinstance(request_id, int) and isinstance(message.get("method"), str):
                threading.Thread(
                    target=self._handle_server_request,
                    args=(request_id, str(message["method"]), message.get("params", {})),
                    daemon=True,
                    name="codex-local-approval",
                ).start()
                continue
            self._notifications.put(message)

    def _handle_server_request(self, request_id: int, method: str, params: Any) -> None:
        values = params if isinstance(params, dict) else {}
        handler = self.approval_handler
        if handler is None or method not in LocalApprovalHandler.SUPPORTED_METHODS:
            self._send({
                "id": request_id,
                "error": {"code": -32001, "message": "This local interaction is unavailable"},
            })
            return
        try:
            decision = handler(method, values)
        except Exception:
            decision = "decline"
        self._send({"id": request_id, "result": {"decision": decision}})


class AppServerEngine:
    REMOTE_INSTRUCTIONS = (
        "This thread is controlled by a remote voice client. Work in analysis-only mode. "
        "Do not request writes, network access, secrets, or external actions. Keep the final "
        "answer under 700 characters and do not reproduce source files, patches, credentials, "
        "or terminal logs. Return only a concise spoken summary in plain language."
    )

    def __init__(self, config: ConnectorConfig, config_store: ConfigStore):
        self.config = config
        self.config_store = config_store
        self.root = config.primary_allowed_root()
        self.current_approval_root = self.root
        self.client = AppServerClient(config.app_server_command, self.root, self._handle_approval)
        self.loaded_threads: set[str] = set()
        self.active_turns: dict[str, str] = {}

    def close(self) -> None:
        self.client.close()

    def default_project_name(self) -> str:
        return self.config.project_alias(self.config.primary_allowed_root())

    def project_name(self, job: dict[str, Any]) -> str:
        if str(job.get("action", "")) == "select_project":
            root = self.config.resolve_allowed_project(str(job.get("prompt", "")))
        else:
            root = self._root_for_conversation(str(job["conversation_id"]))
        return self.config.project_alias(root)

    def execute(self, job: dict[str, Any]) -> str:
        action = str(job["action"])
        conversation_id = str(job["conversation_id"])
        if action == "select_project":
            return self._select_project(conversation_id, str(job.get("prompt", "")))
        root = self._root_for_conversation(conversation_id)
        self.current_approval_root = root
        self.client.start()
        if action == "steer":
            return self._steer(conversation_id, str(job.get("prompt", "")))
        if action == "interrupt":
            return self._interrupt(conversation_id)

        thread_id = self.config.conversation_threads.get(conversation_id)
        if thread_id is None:
            if action not in {"start", "continue"}:
                raise AppServerError("Локальный Codex thread для продолжения не найден")
            result = self.client.request("thread/start", {
                "cwd": str(root),
                "approvalPolicy": self._approval_policy(),
                "developerInstructions": self._remote_instructions(),
            })
            thread_id = str(result.get("thread", {}).get("id", ""))
            if not thread_id:
                raise AppServerError("thread/start не вернул thread id")
            self.config.conversation_threads[conversation_id] = thread_id
            self.config_store.save(self.config)
            self.loaded_threads.add(thread_id)
        elif thread_id not in self.loaded_threads:
            self.client.request("thread/resume", {
                "threadId": thread_id,
                "cwd": str(root),
                "approvalPolicy": self._approval_policy(),
            })
            self.loaded_threads.add(thread_id)

        prompt = str(job.get("prompt", ""))
        turn_params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": prompt}],
            "clientUserMessageId": str(job["job_id"]),
            "cwd": str(root),
            "approvalPolicy": self._approval_policy(),
            "sandboxPolicy": self._sandbox_policy(root),
        }
        if self.config.model:
            turn_params["model"] = self.config.model
        if self.config.reasoning_effort:
            turn_params["effort"] = self.config.reasoning_effort
        if self.config.service_tier:
            turn_params["serviceTier"] = self.config.service_tier
        result = self.client.request("turn/start", turn_params)
        turn = result.get("turn", {})
        turn_id = str(turn.get("id", "")) if isinstance(turn, dict) else ""
        if not turn_id:
            raise AppServerError("turn/start не вернул turn id")
        self.active_turns[conversation_id] = turn_id

        # Deltas can belong to several agent messages: interim commentary and
        # the terminal answer. Keep them separated by the schema's itemId and
        # prefer the authoritative completed turn instead of concatenating all
        # assistant narration into the text sent to Hub/TTS.
        delta_parts: dict[str, list[str]] = {}
        delta_order: list[str] = []
        completed_messages: list[dict[str, Any]] = []
        while True:
            notification = self.client.wait_notification(
                lambda item: item.get("params", {}).get("turnId") == turn_id
                or item.get("params", {}).get("turn", {}).get("id") == turn_id,
            )
            method = notification.get("method")
            params = notification.get("params", {})
            if method == "item/agentMessage/delta":
                delta = params.get("delta")
                item_id = params.get("itemId")
                if isinstance(delta, str) and isinstance(item_id, str) and item_id:
                    if item_id not in delta_parts:
                        delta_parts[item_id] = []
                        delta_order.append(item_id)
                    delta_parts[item_id].append(delta)
            if method == "item/completed":
                item = params.get("item")
                if isinstance(item, dict) and item.get("type") == "agentMessage":
                    completed_messages.append(item)
            if method == "turn/completed":
                self.active_turns.pop(conversation_id, None)
                completed_turn = params.get("turn", {})
                status = completed_turn.get("status") if isinstance(completed_turn, dict) else None
                if status == "failed":
                    error = completed_turn.get("error", {})
                    raise AppServerError(str(error.get("message", "Codex turn failed")))
                break
        answer = _last_agent_message(completed_turn)
        if not answer:
            answer = _last_agent_message({"items": completed_messages})
        if not answer and delta_order:
            answer = "".join(delta_parts[delta_order[-1]]).strip()
        if not answer:
            answer = "Codex завершил анализ без текстовой сводки."
        return _bounded_summary(answer)

    def _select_project(self, conversation_id: str, spoken_name: str) -> str:
        root = self.config.resolve_allowed_project(spoken_name)
        self.config.conversation_roots[conversation_id] = str(root)
        self.config_store.save(self.config)
        return f"Выбран проект {self.config.project_alias(root)}. Скажи задачу для этого проекта."

    def _root_for_conversation(self, conversation_id: str) -> Path:
        configured = self.config.conversation_roots.get(conversation_id)
        if configured:
            candidate = Path(configured).resolve(strict=True)
            allowed = {str(Path(item).resolve(strict=True)).casefold() for item in self.config.allowed_roots}
            if str(candidate).casefold() in allowed:
                return candidate
        root = self.config.primary_allowed_root()
        self.config.conversation_roots[conversation_id] = str(root)
        self.config_store.save(self.config)
        return root

    def _approval_policy(self) -> str:
        return {"read_only": "never", "ask": "on-request", "full_project": "untrusted"}[self.config.access_mode]

    def _sandbox_policy(self, root: Path) -> dict[str, Any]:
        if self.config.access_mode == "full_project":
            return {"type": "workspaceWrite", "writableRoots": [str(root)], "networkAccess": False}
        return {"type": "readOnly", "networkAccess": False}

    def _remote_instructions(self) -> str:
        if self.config.access_mode == "read_only":
            return self.REMOTE_INSTRUCTIONS
        if self.config.access_mode == "ask":
            return (
                "This thread is controlled by a remote voice client. Analyze first. Before any file change or command "
                "that needs elevated permissions, request approval from the local PC user. Never use network access, "
                "external services, destructive actions, secrets, or paths outside the selected project. Keep the final "
                "answer under 700 characters and return only a concise spoken summary."
            )
        return (
            "The local PC user explicitly enabled workspace write access for the selected project only. You may make "
            "ordinary in-project edits and run non-destructive local checks. Never use network access, external services, "
            "destructive actions, secrets, or paths outside the selected project. Request local approval when required. "
            "Keep the final answer under 700 characters and return only a concise spoken summary."
        )

    def _handle_approval(self, method: str, params: dict[str, Any]) -> str:
        if self.config.access_mode == "read_only":
            return "decline"
        handler = LocalApprovalHandler(self.current_approval_root, language=self.config.language)
        decision = handler(method, params)
        print(f"Локальное подтверждение {method}: {decision}")
        return decision

    def _steer(self, conversation_id: str, prompt: str) -> str:
        thread_id = self.config.conversation_threads.get(conversation_id)
        turn_id = self.active_turns.get(conversation_id)
        if not thread_id or not turn_id:
            raise AppServerError("Нет активного turn для команды «продолжай»")
        self.client.request("turn/steer", {
            "threadId": thread_id,
            "expectedTurnId": turn_id,
            "input": [{"type": "text", "text": prompt}],
        })
        return "Уточнение передано в активный Codex turn."

    def _interrupt(self, conversation_id: str) -> str:
        thread_id = self.config.conversation_threads.get(conversation_id)
        turn_id = self.active_turns.get(conversation_id)
        if not thread_id or not turn_id:
            raise AppServerError("Нет активного turn для остановки")
        self.client.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
        return "Codex остановлен."


def _last_agent_message(turn: dict[str, Any]) -> str:
    items = turn.get("items", []) if isinstance(turn, dict) else []
    messages = [
        item
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, dict)
        and item.get("type") == "agentMessage"
        and isinstance(item.get("text"), str)
        and item["text"].strip()
    ]
    for item in reversed(messages):
        if item.get("phase") == "final_answer":
            return item["text"].strip()
    return messages[-1]["text"].strip() if messages else ""


def _bounded_summary(value: str) -> str:
    clean = value.replace("\x00", "").strip()
    if len(clean) <= 4000:
        return clean
    return clean[:3999].rstrip() + "…"


def discover_models(config: ConnectorConfig) -> list[dict[str, Any]]:
    """Query the local installed Codex catalog without creating a thread or turn."""
    root = config.primary_allowed_root()
    client = AppServerClient(config.app_server_command, root)
    client.start()
    try:
        return client.list_models()
    finally:
        client.close()


def _resolve_subprocess_command(command: list[str]) -> list[str]:
    """Resolve Windows npm shims to an actual executable without invoking a shell."""
    if not command:
        raise AppServerError("Не задана команда codex app-server")
    executable = command[0]
    resolved = shutil.which(executable)
    if os.name == "nt":
        suffix = Path(resolved or executable).suffix.casefold()
        if suffix in {".cmd", ".bat", ".ps1"} and Path(resolved or executable).stem.casefold() == "codex":
            shim = Path(resolved or executable)
            script = shim.parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            node = shim.parent / "node.exe"
            node_executable = str(node) if node.is_file() else shutil.which("node.exe")
            if script.is_file() and node_executable:
                return [node_executable, str(script), *command[1:]]
        if suffix in {"", ".cmd", ".bat", ".ps1"}:
            executable_name = f"{Path(executable).stem}.exe"
            executable_candidate = shutil.which(executable_name)
            if executable_candidate:
                resolved = executable_candidate
                suffix = Path(resolved).suffix.casefold()
        if suffix in {".cmd", ".bat", ".ps1"}:
            raise AppServerError(
                "Команда Codex указывает на script shim. Укажи путь к codex.exe в локальной конфигурации.",
            )
    return [resolved or executable, *command[1:]]
