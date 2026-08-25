from __future__ import annotations

import argparse
import shutil
import sys
import time

from . import __version__
from .api import HubApi, HubApiError
from .app_server import AppServerEngine, discover_models
from .config import ConfigStore
from .runner import ConnectorService, MockEngine
from .token_store import DpapiTokenStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rokidhub-connector")
    parser.add_argument("--config-dir", help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)

    pair = subparsers.add_parser("pair", help="Привязать этот ПК одноразовым кодом")
    pair.add_argument("--timeout", type=int, default=600)

    configure = subparsers.add_parser("configure", help="Настроить Hub и разрешённые папки")
    configure.add_argument("--allow-root", action="append", default=[])
    configure.add_argument("--hub-url")
    configure.add_argument("--name")
    configure.add_argument("--model")
    configure.add_argument("--effort")
    configure.add_argument("--service-tier")
    configure.add_argument("--access-mode", choices=["read_only", "ask", "full_project"])
    mode = configure.add_mutually_exclusive_group()
    mode.add_argument("--mock-mode", action="store_true", dest="mock_mode")
    mode.add_argument("--real-mode", action="store_false", dest="mock_mode")
    configure.set_defaults(mock_mode=None)

    subparsers.add_parser("doctor", help="Проверить локальную конфигурацию и связь")

    subparsers.add_parser("models", help="Показать модели установленного Codex App Server")

    run = subparsers.add_parser("run", help="Запустить исходящий polling loop")
    run.add_argument("--mock", action="store_true")
    run.add_argument("--once", action="store_true")

    gui = subparsers.add_parser("gui", help="Открыть Windows GUI")
    gui.add_argument("--minimized", action="store_true")
    gui.add_argument("--auto-start", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from pathlib import Path

    config_directory = Path(args.config_dir) if args.config_dir else None
    config_store = ConfigStore(config_directory)
    token_store = DpapiTokenStore(config_directory)
    try:
        if args.command == "configure":
            return _configure(args, config_store)
        if args.command == "pair":
            return _pair(args, config_store, token_store)
        if args.command == "doctor":
            return _doctor(config_store, token_store)
        if args.command == "models":
            return _models(config_store)
        if args.command == "run":
            return _run(args, config_store, token_store)
        if args.command == "gui":
            from .gui import main as gui_main

            return gui_main(config_directory, minimized=args.minimized, auto_start=args.auto_start)
    except (ValueError, RuntimeError, HubApiError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    return 1


def _configure(args: argparse.Namespace, store: ConfigStore) -> int:
    config = store.load()
    if args.hub_url:
        config.hub_url = args.hub_url.rstrip("/")
    if args.name:
        config.name = args.name.strip()
    if args.model is not None:
        config.model = args.model.strip()
    if args.effort is not None:
        config.reasoning_effort = args.effort.strip()
    if args.service_tier is not None:
        config.service_tier = args.service_tier.strip()
    if args.access_mode is not None:
        config.access_mode = args.access_mode
    if args.mock_mode is not None:
        config.mock_mode = args.mock_mode
    for value in args.allow_root:
        root = config.add_allowed_root(value)
        print(f"Разрешена папка: {root}")
    store.save(config)
    print(f"Конфигурация сохранена: {store.path}")
    if not config.allowed_roots:
        print("Перед запуском добавь папку: configure --allow-root C:\\path\\to\\project")
    return 0


def _pair(args: argparse.Namespace, config_store: ConfigStore, token_store: DpapiTokenStore) -> int:
    config = config_store.load()
    config_store.save(config)
    api = HubApi(config.hub_url, config.connector_id)
    started = api.pairing_start(config.name, __version__)
    print(f"Одноразовый код: {started['code']}")
    print("Введи его в кабинете RokidHub. Жду подтверждения…")
    deadline = time.monotonic() + max(10, min(args.timeout, 600))
    next_update = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = api.pairing_poll(str(started["poll_secret"]))
        if response.get("status") == "connected":
            token_store.save(str(response["access_token"]))
            config.paired_hub_url = config.hub_url
            config_store.save(config)
            print("ПК привязан. Токен защищён Windows DPAPI.")
            return 0
        if time.monotonic() >= next_update:
            print("Всё ещё жду подтверждения кода…")
            next_update = time.monotonic() + 30
        time.sleep(2)
    raise RuntimeError("Время одноразового кода истекло; запусти pair ещё раз")


def _doctor(config_store: ConfigStore, token_store: DpapiTokenStore) -> int:
    config = config_store.load()
    config.primary_allowed_root()
    token = token_store.load()
    executable = shutil.which(config.app_server_command[0])
    if not executable:
        raise RuntimeError(f"Не найдена команда {config.app_server_command[0]}")
    api = HubApi(config.hub_url, config.connector_id, token)
    api.status(__version__)
    print(f"RokidHub доступен; Connector {config.connector_id} авторизован.")
    print(f"Codex найден: {executable}")
    print(f"Разрешённая папка: {config.primary_allowed_root()}")
    return 0


def _models(config_store: ConfigStore) -> int:
    config = config_store.load()
    models = discover_models(config)
    for model in models:
        model_id = str(model.get("model") or model.get("id") or "")
        efforts = ", ".join(
            str(item.get("reasoningEffort"))
            for item in model.get("supportedReasoningEfforts", [])
            if isinstance(item, dict) and item.get("reasoningEffort")
        )
        tiers = ", ".join(
            str(item.get("id"))
            for item in model.get("serviceTiers", [])
            if isinstance(item, dict) and item.get("id")
        )
        marker = " *" if model.get("isDefault") else ""
        suffix = f"; tiers: {tiers}" if tiers else ""
        print(f"{model_id}{marker}: {efforts or 'default effort'}{suffix}")
    return 0


def _run(args: argparse.Namespace, config_store: ConfigStore, token_store: DpapiTokenStore) -> int:
    config = config_store.load()
    root = config.primary_allowed_root()
    token = token_store.load()
    api = HubApi(config.hub_url, config.connector_id, token)
    mock_mode = bool(args.mock or config.mock_mode)
    engine = MockEngine(str(root)) if mock_mode else AppServerEngine(config, config_store)
    mode = "mock" if mock_mode else "Codex app-server read-only"
    print(f"Connector запущен: {mode}; папка {root}")
    ConnectorService(api, engine, __version__).run(once=args.once)
    return 0
