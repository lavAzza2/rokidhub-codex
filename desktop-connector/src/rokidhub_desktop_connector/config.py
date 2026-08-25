from __future__ import annotations

import json
import os
import socket
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse


ACCESS_MODES = {"read_only", "ask", "full_project"}
LANGUAGE_PREFERENCES = {"auto", "ru", "en"}


def normalize_hub_url(value: str) -> str:
    return value.strip().rstrip("/")


def is_local_hub_url(value: str) -> bool:
    parsed = urlparse(normalize_hub_url(value))
    return parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def _path_key(value: str | Path) -> str:
    """Canonical comparison key, including Windows short/long temp paths."""
    return os.path.normcase(str(Path(value).expanduser().resolve(strict=False)))


def default_config_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "RokidHub" / "DesktopConnector"
    return Path.home() / "AppData" / "Local" / "RokidHub" / "DesktopConnector"


@dataclass
class ConnectorConfig:
    connector_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = field(default_factory=lambda: socket.gethostname() or "Windows PC")
    hub_url: str = "https://rokidhub.com"
    paired_hub_url: str = ""
    allowed_roots: list[str] = field(default_factory=list)
    default_root: str = ""
    conversation_threads: dict[str, str] = field(default_factory=dict)
    app_server_command: list[str] = field(default_factory=lambda: ["codex", "app-server"])
    model: str = ""
    reasoning_effort: str = ""
    service_tier: str = ""
    mock_mode: bool = False
    access_mode: str = "read_only"
    project_aliases: dict[str, str] = field(default_factory=dict)
    conversation_roots: dict[str, str] = field(default_factory=dict)
    language: str = "auto"

    def validate(self) -> None:
        uuid.UUID(self.connector_id)
        if not self.name.strip() or len(self.name) > 120:
            raise ValueError("Имя Connector должно содержать от 1 до 120 символов")
        self.hub_url = normalize_hub_url(self.hub_url)
        self.paired_hub_url = normalize_hub_url(self.paired_hub_url)
        parsed_hub_url = urlparse(self.hub_url)
        local_http = parsed_hub_url.scheme == "http" and is_local_hub_url(self.hub_url)
        if parsed_hub_url.scheme != "https" and not local_http:
            raise ValueError("Hub URL должен использовать HTTPS; HTTP разрешён только для 127.0.0.1")
        if not parsed_hub_url.netloc or parsed_hub_url.username or parsed_hub_url.password:
            raise ValueError("Некорректный Hub URL")
        if not self.app_server_command:
            raise ValueError("Не задана команда codex app-server")
        if len(self.model) > 160:
            raise ValueError("Идентификатор модели слишком длинный")
        if len(self.reasoning_effort) > 40:
            raise ValueError("Значение reasoning effort слишком длинное")
        if len(self.service_tier) > 80:
            raise ValueError("Значение service tier слишком длинное")
        if self.access_mode not in ACCESS_MODES:
            raise ValueError("Неизвестный профиль доступа")
        if self.language not in LANGUAGE_PREFERENCES:
            raise ValueError("Неизвестный язык интерфейса")
        allowed = {_path_key(item) for item in self.allowed_roots}
        if self.default_root and _path_key(self.default_root) not in allowed:
            raise ValueError("Папка по умолчанию должна быть в списке разрешённых проектов")
        for path, alias in self.project_aliases.items():
            if _path_key(path) not in allowed:
                raise ValueError("Голосовое имя задано для неразрешённой папки")
            clean = alias.strip()
            if not clean or len(clean) > 80:
                raise ValueError("Голосовое имя проекта должно содержать от 1 до 80 символов")
        aliases: set[str] = set()
        for path in self.allowed_roots:
            normalized = _normalize_project_name(self.project_alias(path))
            if normalized in aliases:
                raise ValueError("Голосовые имена проектов должны быть уникальными")
            aliases.add(normalized)

    def add_allowed_root(self, value: str) -> Path:
        root = Path(value).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError(f"Разрешённый путь не является папкой: {root}")
        normalized = str(root)
        if normalized.casefold() not in {item.casefold() for item in self.allowed_roots}:
            self.allowed_roots.append(normalized)
        if not self.default_root:
            self.default_root = normalized
        return root

    def primary_allowed_root(self) -> Path:
        if not self.allowed_roots:
            raise RuntimeError("Сначала явно добавь хотя бы одну разрешённую папку через configure --allow-root")
        selected = self.default_root or self.allowed_roots[0]
        matching = next(
            (item for item in self.allowed_roots if _path_key(item) == _path_key(selected)),
            None,
        )
        if matching is None:
            raise RuntimeError("Папка по умолчанию больше не входит в список разрешённых проектов")
        root = Path(matching).resolve(strict=True)
        if not root.is_dir():
            raise RuntimeError(f"Разрешённая папка недоступна: {root}")
        return root

    def project_alias(self, root: str | Path) -> str:
        path = str(Path(root))
        path_key = _path_key(path)
        configured = next(
            (alias for key, alias in self.project_aliases.items() if _path_key(key) == path_key),
            "",
        )
        return configured.strip() or Path(path).name

    def resolve_allowed_project(self, spoken_name: str) -> Path:
        wanted = _normalize_project_name(spoken_name)
        if not wanted:
            raise ValueError("Не расслышал название проекта")
        projects: list[tuple[Path, str]] = []
        for value in self.allowed_roots:
            path = Path(value).resolve(strict=True)
            projects.append((path, _normalize_project_name(self.project_alias(path))))
        exact = [path for path, alias in projects if alias == wanted]
        if len(exact) == 1:
            return exact[0]
        partial = [path for path, alias in projects if wanted in alias or alias in wanted]
        if len(partial) == 1:
            return partial[0]
        available = ", ".join(self.project_alias(path) for path, _alias in projects)
        if len(partial) > 1:
            raise ValueError(f"Название неоднозначно. Доступны: {available}")
        raise ValueError(f"Проект не найден. Доступны: {available}")


class ConfigStore:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or default_config_dir()
        self.path = self.directory / "config.json"

    def load(self) -> ConnectorConfig:
        if not self.path.exists():
            config = ConnectorConfig()
            config.validate()
            return config
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        config = ConnectorConfig(
            connector_id=str(payload.get("connector_id", uuid.uuid4())),
            name=str(payload.get("name", socket.gethostname() or "Windows PC")),
            hub_url=str(payload.get("hub_url", "https://rokidhub.com")),
            paired_hub_url=str(payload.get("paired_hub_url", "")),
            allowed_roots=[str(item) for item in payload.get("allowed_roots", [])],
            default_root=str(payload.get("default_root", "")),
            conversation_threads={str(key): str(value) for key, value in payload.get("conversation_threads", {}).items()},
            app_server_command=[str(item) for item in payload.get("app_server_command", ["codex", "app-server"])],
            model=str(payload.get("model", "")),
            reasoning_effort=str(payload.get("reasoning_effort", "")),
            service_tier=str(payload.get("service_tier", "")),
            mock_mode=bool(payload.get("mock_mode", False)),
            access_mode=str(payload.get("access_mode", "read_only")),
            project_aliases={str(key): str(value) for key, value in payload.get("project_aliases", {}).items()},
            conversation_roots={str(key): str(value) for key, value in payload.get("conversation_roots", {}).items()},
            language=str(payload.get("language", "auto")),
        )
        config.validate()
        return config

    def save(self, config: ConnectorConfig) -> None:
        config.validate()
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)


def _normalize_project_name(value: str) -> str:
    transliteration = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    converted = "".join(transliteration.get(char, char) for char in value.strip().casefold())
    return "".join(char for char in converted if char.isalnum())
