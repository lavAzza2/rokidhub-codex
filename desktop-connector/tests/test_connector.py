from __future__ import annotations

import tempfile
import unittest
import os
import ssl
import threading
from pathlib import Path
from unittest.mock import patch

from rokidhub_desktop_connector.api import HubApi
from rokidhub_desktop_connector.app_server import AppServerEngine, _bounded_summary, _resolve_subprocess_command
from rokidhub_desktop_connector.approval import LocalApprovalHandler
from rokidhub_desktop_connector.autostart import build_autostart_command
from rokidhub_desktop_connector.config import ConfigStore, ConnectorConfig, is_local_hub_url
from rokidhub_desktop_connector.gui import Utf8LogDecoder, effort_label, pairing_code_from_line, utf8_process_environment
from rokidhub_desktop_connector.i18n import Translator, detect_system_language, resolve_language
from rokidhub_desktop_connector.runner import ConnectorService, MockEngine
from rokidhub_desktop_connector.token_store import DpapiTokenStore


class ConfigTests(unittest.TestCase):
    def test_local_hub_is_identified_separately_from_production(self):
        self.assertTrue(is_local_hub_url("http://127.0.0.1:8000"))
        self.assertTrue(is_local_hub_url("http://localhost:8000/"))
        self.assertFalse(is_local_hub_url("https://rokidhub.com"))

    def test_allowed_roots_and_thread_mapping_stay_in_local_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            root = directory / "workspace"
            root.mkdir()
            store = ConfigStore(directory / "config")
            config = ConnectorConfig(hub_url="http://127.0.0.1:8000")
            config.add_allowed_root(str(root))
            config.default_root = str(root.resolve())
            config.conversation_threads["conversation"] = "local-thread"
            config.model = "gpt-local-test"
            config.reasoning_effort = "low"
            config.service_tier = "fast"
            config.mock_mode = True
            config.access_mode = "ask"
            config.paired_hub_url = "http://127.0.0.1:8000/"
            config.project_aliases[str(root.resolve())] = "Рокид"
            config.conversation_roots["conversation"] = str(root.resolve())
            config.language = "en"
            store.save(config)

            loaded = store.load()
            self.assertEqual(loaded.primary_allowed_root(), root.resolve())
            self.assertEqual(loaded.default_root, str(root.resolve()))
            self.assertEqual(loaded.conversation_threads, {"conversation": "local-thread"})
            self.assertEqual(loaded.model, "gpt-local-test")
            self.assertEqual(loaded.reasoning_effort, "low")
            self.assertEqual(loaded.service_tier, "fast")
            self.assertTrue(loaded.mock_mode)
            self.assertEqual(loaded.access_mode, "ask")
            self.assertEqual(loaded.project_alias(root), "Рокид")
            self.assertEqual(loaded.resolve_allowed_project("рокид"), root.resolve())
            self.assertEqual(loaded.conversation_roots["conversation"], str(root.resolve()))
            self.assertEqual(loaded.language, "en")
            self.assertEqual(loaded.paired_hub_url, "http://127.0.0.1:8000")
            self.assertNotIn("token", store.path.read_text(encoding="utf-8").casefold())

    def test_hub_api_uses_a_strict_bundled_ca_context(self):
        with patch("rokidhub_desktop_connector.api.urlopen") as open_url:
            response = open_url.return_value.__enter__.return_value
            response.read.return_value = b'{"ok": true}'

            result = HubApi("https://rokidhub.com", "connector-id").status("test")

        self.assertTrue(result["ok"])
        context = open_url.call_args.kwargs["context"]
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_autostart_command_contains_gui_but_no_secret(self):
        command = build_autostart_command(Path("C:/Users/Test/AppData/Local/RokidHub/DesktopConnector"))
        self.assertIn("rokidhub_desktop_connector", command)
        self.assertIn("--auto-start", command)
        self.assertIn("--minimized", command)
        self.assertNotIn("token", command.casefold())

    def test_effort_labels_are_human_readable_without_changing_protocol_value(self):
        self.assertEqual(effort_label("low"), "Быстро · low")
        self.assertEqual(effort_label("low", language="en"), "Fast · low")
        self.assertEqual(effort_label("custom"), "custom")

    def test_language_auto_detection_and_manual_override(self):
        self.assertEqual(detect_system_language("ru-RU"), "ru")
        self.assertEqual(detect_system_language("en-US"), "en")
        self.assertEqual(resolve_language("auto", "ru-RU"), "ru")
        self.assertEqual(resolve_language("en", "ru-RU"), "en")
        self.assertEqual(Translator("en").text("start"), "Start Connector")
        self.assertIn("Настройки", Translator("ru").text("pc_unpaired_tooltip"))
        self.assertIn("triple-tap", Translator("en").text("glasses_unpaired_tooltip"))

    def test_qprocess_output_is_forced_to_utf8(self):
        environment = utf8_process_environment()
        self.assertEqual(environment.value("PYTHONUTF8"), "1")
        self.assertEqual(environment.value("PYTHONIOENCODING"), "utf-8")

    def test_utf8_log_decoder_preserves_split_cyrillic_chunks(self):
        expected = "Connector запущен: Codex; папка RokidGlasses"
        payload = (expected + "\r\nСледующая строка\n").encode("utf-8")
        split = payload.index("з".encode("utf-8")) + 1
        decoder = Utf8LogDecoder()

        lines = decoder.feed(payload[:split])
        lines += decoder.feed(payload[split:-3])
        lines += decoder.feed(payload[-3:], final=True)

        self.assertEqual(lines, [expected, "Следующая строка"])

    def test_pairing_code_is_detected_in_cli_output(self):
        self.assertEqual(pairing_code_from_line("Одноразовый код: 1234-5678"), "1234-5678")
        self.assertIsNone(pairing_code_from_line("Всё ещё жду подтверждения кода…"))

    def test_spoken_cyrillic_can_match_latin_folder_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "RokidGlasses"
            project.mkdir()
            config = ConnectorConfig(hub_url="http://127.0.0.1:8000", allowed_roots=[str(project)])
            self.assertEqual(config.resolve_allowed_project("Рокид Глассес"), project.resolve())

    def test_explicit_default_root_does_not_reorder_allowed_projects(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            first = directory / "first"
            second = directory / "second"
            first.mkdir()
            second.mkdir()
            config = ConnectorConfig(
                hub_url="http://127.0.0.1:8000",
                allowed_roots=[str(first), str(second)],
                default_root=str(second),
            )

            config.validate()

            self.assertEqual(config.primary_allowed_root(), second.resolve())
            self.assertEqual(config.allowed_roots, [str(first), str(second)])

    def test_default_root_must_be_an_allowed_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "allowed"
            outside = Path(temporary) / "outside"
            root.mkdir()
            outside.mkdir()
            config = ConnectorConfig(
                hub_url="http://127.0.0.1:8000",
                allowed_roots=[str(root)],
                default_root=str(outside),
            )

            with self.assertRaises(ValueError):
                config.validate()

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI only")
    def test_dpapi_token_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = DpapiTokenStore(Path(temporary))
            store.save("raw-secret-token")

            self.assertEqual(store.load(), "raw-secret-token")
            self.assertNotIn(b"raw-secret-token", store.path.read_bytes())


class FakeApi:
    def __init__(self, job):
        self.job = job
        self.events = []
        self.status_calls = 0

    def status(self, client_version, default_project_name=""):
        self.status_calls += 1
        self.default_project_name = default_project_name
        return {"connected": True}

    def poll_job(self):
        job, self.job = self.job, None
        return {"job": job, "poll_after_seconds": 2}

    def publish_event(self, job_id, lease_id, sequence, kind, message="", status=None, error_code=None, project_name=None):
        self.events.append({
            "job_id": job_id,
            "lease_id": lease_id,
            "sequence": sequence,
            "type": kind,
            "message": message,
            "status": status,
            "error_code": error_code,
            "project_name": project_name,
        })
        return {"accepted": True}


class RunnerTests(unittest.TestCase):
    def test_mock_round_trip_publishes_only_status_and_short_final(self):
        api = FakeApi({
            "job_id": "job-1",
            "lease_id": "lease-1",
            "conversation_id": "conversation-1",
            "action": "start",
            "prompt": "Проверь проект",
        })
        service = ConnectorService(api, MockEngine("C:\\allowed"), "0.1.0")
        service.run(once=True)

        self.assertEqual(api.status_calls, 1)
        self.assertEqual([item["type"] for item in api.events], ["status", "final"])
        self.assertEqual(api.default_project_name, "allowed")
        self.assertTrue(all(item["project_name"] == "allowed" for item in api.events))
        self.assertNotIn("Проверь проект", api.events[-1]["message"])

    def test_interrupt_is_dispatched_while_primary_turn_is_running(self):
        class StopPolling(RuntimeError):
            pass

        class StreamingApi(FakeApi):
            def __init__(self):
                super().__init__(None)
                self.jobs = [
                    {"job_id": "job-start", "lease_id": "lease-start", "conversation_id": "c1", "action": "start", "prompt": "Анализ"},
                    {"job_id": "job-stop", "lease_id": "lease-stop", "conversation_id": "c1", "action": "interrupt", "prompt": ""},
                ]

            def poll_job(self):
                if self.jobs:
                    return {"job": self.jobs.pop(0), "poll_after_seconds": 0}
                raise StopPolling()

        class BlockingEngine:
            def __init__(self):
                self.started = threading.Event()
                self.release = threading.Event()
                self.actions = []

            def execute(self, job):
                action = job["action"]
                self.actions.append(action)
                if action == "start":
                    self.started.set()
                    self.release.wait(timeout=2)
                    return "Основной turn остановлен."
                self.assert_started()
                self.release.set()
                return "Остановка передана."

            def assert_started(self):
                if not self.started.wait(timeout=2):
                    raise AssertionError("primary turn was not started")

            def close(self):
                self.release.set()

        api = StreamingApi()
        engine = BlockingEngine()
        service = ConnectorService(api, engine, "0.1.0")

        with self.assertRaises(StopPolling):
            service.run()
        self.assertEqual(engine.actions, ["start", "interrupt"])


class FakeAppServerClient:
    def __init__(self):
        self.requests = []
        self.notifications = [
            {"method": "item/agentMessage/delta", "params": {"turnId": "turn-1", "itemId": "commentary-1", "delta": "Сначала посмотрю проект."}},
            {"method": "item/completed", "params": {"turnId": "turn-1", "item": {"id": "commentary-1", "type": "agentMessage", "phase": "commentary", "text": "Сначала посмотрю проект."}}},
            {"method": "item/agentMessage/delta", "params": {"turnId": "turn-1", "itemId": "final-1", "delta": "Короткий итог."}},
            {"method": "item/completed", "params": {"turnId": "turn-1", "item": {"id": "final-1", "type": "agentMessage", "phase": "final_answer", "text": "Короткий итог."}}},
            {"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "completed", "items": [
                {"id": "commentary-1", "type": "agentMessage", "phase": "commentary", "text": "Сначала посмотрю проект."},
                {"id": "final-1", "type": "agentMessage", "phase": "final_answer", "text": "Короткий итог."},
            ]}}},
        ]

    def start(self):
        return

    def close(self):
        return

    def request(self, method, params, timeout=30):
        self.requests.append((method, params))
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}}
        if method == "turn/start":
            return {"turn": {"id": "turn-1"}}
        return {}

    def wait_notification(self, predicate, timeout=3600):
        for index, notification in enumerate(self.notifications):
            if predicate(notification):
                return self.notifications.pop(index)
        raise AssertionError("matching notification not found")


class AppServerEngineTests(unittest.TestCase):
    def test_real_request_is_forced_read_only_without_network_or_approvals(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            root = directory / "workspace"
            root.mkdir()
            store = ConfigStore(directory / "config")
            config = ConnectorConfig(
                hub_url="http://127.0.0.1:8000",
                allowed_roots=[str(root)],
                model="gpt-test-codex",
                reasoning_effort="high",
                service_tier="fast",
            )
            engine = AppServerEngine(config, store)
            fake = FakeAppServerClient()
            engine.client = fake

            result = engine.execute({
                "job_id": "job-1",
                "conversation_id": "conversation-1",
                "action": "start",
                "prompt": "Проанализируй проект",
            })

            self.assertEqual(result, "Короткий итог.")
            turn_params = next(params for method, params in fake.requests if method == "turn/start")
            self.assertEqual(turn_params["approvalPolicy"], "never")
            self.assertEqual(turn_params["sandboxPolicy"], {"type": "readOnly", "networkAccess": False})
            self.assertEqual(turn_params["cwd"], str(root.resolve()))
            self.assertEqual(turn_params["model"], "gpt-test-codex")
            self.assertEqual(turn_params["effort"], "high")
            self.assertEqual(turn_params["serviceTier"], "fast")

    def test_steer_uses_expected_active_turn_id_from_installed_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            root = directory / "workspace"
            root.mkdir()
            store = ConfigStore(directory / "config")
            config = ConnectorConfig(
                hub_url="http://127.0.0.1:8000",
                allowed_roots=[str(root)],
                conversation_threads={"conversation-1": "thread-1"},
            )
            engine = AppServerEngine(config, store)
            fake = FakeAppServerClient()
            engine.client = fake
            engine.active_turns["conversation-1"] = "turn-active"

            result = engine.execute({
                "job_id": "job-2",
                "conversation_id": "conversation-1",
                "action": "steer",
                "prompt": "Продолжай короче",
            })

            self.assertIn("передано", result)
            method, params = fake.requests[-1]
            self.assertEqual(method, "turn/steer")
            self.assertEqual(params["expectedTurnId"], "turn-active")

    def test_summary_is_bounded_for_hub(self):
        self.assertEqual(len(_bounded_summary("x" * 5000)), 4000)
        self.assertTrue(_bounded_summary("x" * 5000).endswith("…"))

    def test_access_profiles_use_installed_schema_and_stay_scoped_to_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            store = ConfigStore(root / "config")
            config = ConnectorConfig(hub_url="http://127.0.0.1:8000", allowed_roots=[str(root)], access_mode="ask")
            engine = AppServerEngine(config, store)
            self.assertEqual(engine._approval_policy(), "on-request")
            self.assertEqual(engine._sandbox_policy(root), {"type": "readOnly", "networkAccess": False})

            config.access_mode = "full_project"
            self.assertEqual(engine._approval_policy(), "untrusted")
            self.assertEqual(engine._sandbox_policy(root), {
                "type": "workspaceWrite",
                "writableRoots": [str(root)],
                "networkAccess": False,
            })

    def test_project_selection_is_resolved_and_stored_only_locally(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            first = directory / "first"
            selected = directory / "rokid"
            first.mkdir()
            selected.mkdir()
            store = ConfigStore(directory / "config")
            config = ConnectorConfig(
                hub_url="http://127.0.0.1:8000",
                allowed_roots=[str(first), str(selected)],
                default_root=str(first),
                project_aliases={str(selected): "Очки"},
            )
            engine = AppServerEngine(config, store)

            result = engine.execute({
                "job_id": "job-project",
                "conversation_id": "conversation-project",
                "action": "select_project",
                "prompt": "очки",
            })

            self.assertIn("Очки", result)
            self.assertEqual(config.conversation_roots["conversation-project"], str(selected.resolve()))
            self.assertEqual(store.load().conversation_roots["conversation-project"], str(selected.resolve()))
            self.assertEqual(engine.project_name({
                "conversation_id": "conversation-project",
                "action": "continue",
            }), "Очки")

    def test_local_approval_rejects_paths_outside_selected_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "allowed"
            outside = Path(temporary) / "outside"
            root.mkdir()
            outside.mkdir()
            prompts = []
            handler = LocalApprovalHandler(root, lambda title, body: prompts.append((title, body)) or "accept")

            accepted = handler("item/commandExecution/requestApproval", {"cwd": str(root), "command": "pytest"})
            declined = handler("item/commandExecution/requestApproval", {"cwd": str(outside), "command": "pytest"})

            self.assertEqual(accepted, "accept")
            self.assertEqual(declined, "decline")
            self.assertEqual(len(prompts), 1)

    def test_local_approval_uses_selected_english_language(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            prompts = []
            handler = LocalApprovalHandler(
                root,
                lambda title, body: prompts.append((title, body)) or "decline",
                language="en",
            )

            decision = handler("item/fileChange/requestApproval", {"grantRoot": str(root)})

            self.assertEqual(decision, "decline")
            self.assertIn("write approval", prompts[0][0])
            self.assertIn("Allow once?", prompts[0][1])

    @unittest.skipUnless(os.name == "nt", "Windows executable resolution only")
    def test_codex_npm_shim_resolves_to_executable_without_shell(self):
        resolved = _resolve_subprocess_command(["codex", "app-server"])
        self.assertTrue(resolved[0].casefold().endswith(".exe"))
        self.assertEqual(resolved[-1], "app-server")
        self.assertFalse(any(item.casefold().endswith((".cmd", ".bat", ".ps1")) for item in resolved))


if __name__ == "__main__":
    unittest.main()
