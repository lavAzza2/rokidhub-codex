from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Any, Callable

from .i18n import resolve_language


DecisionPrompt = Callable[[str, str], str]


class LocalApprovalHandler:
    """Resolve App Server approvals only through a local Windows prompt."""

    SUPPORTED_METHODS = {
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
    }

    def __init__(
        self,
        allowed_root: Path,
        prompt: DecisionPrompt | None = None,
        *,
        language: str = "auto",
    ):
        self.allowed_root = allowed_root.resolve(strict=True)
        self.prompt = prompt or windows_decision_prompt
        self.language = resolve_language(language)

    def __call__(self, method: str, params: dict[str, Any]) -> str:
        if method not in self.SUPPORTED_METHODS:
            return "decline"
        requested_path = params.get("cwd") if method.endswith("commandExecution/requestApproval") else params.get("grantRoot")
        if requested_path and not _is_within(Path(str(requested_path)), self.allowed_root):
            return "decline"
        if method.endswith("commandExecution/requestApproval"):
            network = params.get("networkApprovalContext")
            if network:
                unknown = "неизвестный адрес" if self.language == "ru" else "unknown address"
                target = str(network.get("host", unknown)) if isinstance(network, dict) else unknown
                detail = (
                    f"Codex запрашивает сетевой доступ к: {target}"
                    if self.language == "ru"
                    else f"Codex requests network access to: {target}"
                )
            else:
                missing = "Команда не указана" if self.language == "ru" else "Command was not provided"
                command = str(params.get("command") or missing)
                detail = f"Команда:\n{command[:1200]}" if self.language == "ru" else f"Command:\n{command[:1200]}"
            title = "RokidHub · подтверждение команды" if self.language == "ru" else "RokidHub · command approval"
        else:
            detail = (
                "Codex запрашивает разрешение изменить файлы выбранного проекта."
                if self.language == "ru"
                else "Codex requests permission to change files in the selected project."
            )
            title = "RokidHub · подтверждение записи" if self.language == "ru" else "RokidHub · write approval"
        reason = str(params.get("reason") or "").strip()
        if self.language == "ru":
            body = (
                f"{detail}\n\nПроект: {self.allowed_root}\n"
                + (f"Причина: {reason[:600]}\n\n" if reason else "\n")
                + "Разрешить один раз?\n\nДа — разрешить, Нет — отклонить, Отмена — остановить задачу."
            )
        else:
            body = (
                f"{detail}\n\nProject: {self.allowed_root}\n"
                + (f"Reason: {reason[:600]}\n\n" if reason else "\n")
                + "Allow once?\n\nYes — allow, No — decline, Cancel — stop the task."
            )
        decision = self.prompt(title, body)
        return decision if decision in {"accept", "decline", "cancel"} else "decline"


def windows_decision_prompt(title: str, body: str) -> str:
    if os.name != "nt":
        return "decline"
    # Yes / No / Cancel, warning icon, default to No, foreground and topmost.
    flags = 0x00000003 | 0x00000030 | 0x00000100 | 0x00010000 | 0x00040000
    result = ctypes.windll.user32.MessageBoxW(None, body, title, flags)
    return {6: "accept", 7: "decline", 2: "cancel"}.get(result, "decline")


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root)
        return True
    except (OSError, ValueError):
        return False
