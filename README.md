# RokidHub · Codex

Public beta integration for running local Codex tasks from Rokid RV101 glasses:

```text
RV101 → Nexus Android plugin → RokidHub → Windows Desktop Connector → local Codex App Server
```

No inbound PC port is opened. Codex/ChatGPT authorization, source code, project
paths and local policy stay on the user's computer. RokidHub routes bounded job
envelopes and stores only hashes of separate revocable Nexus and PC tokens.

## Downloads

Use the latest [GitHub Release](https://github.com/lavAzza2/rokidhub-codex/releases/latest):

- `RokidHub-Codex-Nexus-v*.apk` — Nexus plugin for Android;
- `RokidHub-Desktop-Connector-v*.exe` — standalone Windows application;
- `SHA256SUMS.txt` — checksums for both files.

The Windows beta is not Authenticode-signed yet, so Microsoft SmartScreen may
show a warning. Verify its SHA-256 checksum before running it.

## Setup

1. Install Codex locally and sign in on the PC. Confirm `codex --version` works.
2. Download and run Desktop Connector. In Settings, add allowed project folders,
   choose the default project and local access policy, then click **Pair PC**.
3. Enter the one-time PC code in the Codex integration card at
   [rokidhub.com](https://rokidhub.com).
4. Install the APK through Nexus, grant STT/HUD/TTS permissions, open
   **RokidHub · Codex**, and enter its one-time code in the same card.
5. Speak a task. The project alias is shown in the HUD footer; source paths and
   Codex credentials never leave the PC.

Russian and English UI/STT are selected from the Android phone and Windows
locale. Voice controls include `продолжай` / `continue`, `останови` / `stop`,
short summary, and `выбери проект …` / `select project …`.

## Repository

- [`android-plugin`](android-plugin) — separate `rokidhub.codex` Nexus plugin;
- [`desktop-connector`](desktop-connector) — PySide6 GUI and outbound HTTPS poller;
- [`docs/architecture.md`](docs/architecture.md) — protocol, data placement,
  job/thread states, threat model and WSS migration path.

The Django backend is deployed separately as part of RokidHub. Its Codex API
contract is documented here, but server credentials and deployment files are not.

## Development

Android:

```powershell
cd android-plugin
.\gradlew.bat testDebugUnitTest assembleRelease
```

Desktop Connector:

```powershell
cd desktop-connector
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[build]"
.\.venv\Scripts\python.exe -m pytest
.\packaging\build-windows.ps1
```

Release signing credentials are supplied only through local environment
variables or GitHub secrets. Keys and raw bearer tokens must never be committed.

## Status

`v0.5.0-beta.1` is an early public beta. Keep local backups and start with the
read-only policy. Automatic dangerous actions and unrestricted filesystem access
are intentionally unavailable.
