from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from rokidhub_desktop_connector.config import ConfigStore, ConnectorConfig
from rokidhub_desktop_connector.gui import ConnectorWindow
from rokidhub_desktop_connector.token_store import DpapiTokenStore


if len(sys.argv) != 2:
    raise SystemExit("usage: capture-article-screenshots.py OUTPUT_DIRECTORY")

output_directory = Path(sys.argv[1]).resolve()
output_directory.mkdir(parents=True, exist_ok=True)
temporary = tempfile.TemporaryDirectory()
config_directory = Path(temporary.name) / "config"
projects = [
    "C:\\Projects\\RokidGlasses",
    "C:\\Projects\\RokidHub",
    "C:\\Projects\\NexusPlugin",
]

store = ConfigStore(config_directory)
store.save(
    ConnectorConfig(
        name="Рабочий ПК",
        hub_url="https://rokidhub.com",
        allowed_roots=projects,
        default_root=projects[1],
        reasoning_effort="high",
        service_tier="fast",
        access_mode="ask",
        project_aliases={
            projects[0]: "Очки",
            projects[1]: "Хаб",
            projects[2]: "Плагин",
        },
        language="ru",
    )
)

app = QApplication([])
window = ConnectorWindow(store, DpapiTokenStore(config_directory))
window.resize(1184, 800)
window.show()


def capture() -> None:
    screens = [
        ("overview", "04-connector-overview.png"),
        ("projects", "05-connector-projects.png"),
        ("codex", "06-connector-codex.png"),
        ("security", "07-connector-security.png"),
        ("activity", "08-connector-activity.png"),
        ("settings", "09-connector-settings.png"),
    ]
    for page, filename in screens:
        window._nav_buttons[page].click()
        app.processEvents()
        if not window.grab().save(str(output_directory / filename)):
            raise RuntimeError(f"could not save {filename}")
    window._quitting = True
    window.close()
    app.quit()


QTimer.singleShot(750, capture)
app.exec()
temporary.cleanup()
