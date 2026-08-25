# Rokid Nexus → RokidHub → local Codex

Status: MVP vertical slice, protocol version `v1`.

This integration is independent of the existing AIUI bridge and the
`rokidhub.yandex` Nexus plugin. It does not change the Yandex command contract.

## Trust boundaries

```text
RV101 glasses
  ↕ Bluetooth / Nexus plugin UX (STT, HUD, short TTS)
Android Nexus plugin: rokidhub.codex
  ↕ HTTPS, Nexus installation bearer token
RokidHub
  ↕ outbound-only HTTPS polling, Desktop Connector bearer token
RokidHub Desktop Connector (Windows)
  ↕ localhost stdio JSONL
codex app-server
  ↕ local Codex authentication and local workspace
User-selected folder on the PC
```

RokidHub never connects to `codex app-server`. The Connector starts or connects
to app-server locally and is the only bridge between Hub jobs and Codex events.
The current transport is HTTPS polling so no router configuration, port forward,
or inbound PC listener is required. A future WSS transport replaces only the
Hub↔Connector delivery loop; job envelopes, authentication and event sequence
numbers stay unchanged.

## Identity and pairing

There are two unrelated revocable credentials:

- `NexusInstallation(plugin_id="rokidhub.codex")` authenticates the phone/glasses
  side. It is not the existing `rokidhub.yandex` credential.
- `DesktopConnector` authenticates exactly one PC connector.

Both pairing flows use a short-lived one-time display code plus a 256-bit poll
secret. The raw access token is returned once. Hub stores only SHA-256 token
verifiers and compares them with a constant-time function. Revocation sets
`revoked_at`; future authenticated calls fail.

The short code is entered only in the authenticated RokidHub cabinet. The poll
secret is never displayed and prevents somebody who only saw the code from
claiming the issued bearer token. Production ingress should rate-limit pairing
start, poll and claim routes independently.

## Data placement

| Data | Hub | PC | Nexus |
|---|---:|---:|---:|
| Nexus/Desktop raw bearer token | no | Desktop token only, DPAPI | Nexus token only, Android secure storage |
| Token SHA-256 verifier | yes | no | no |
| Codex OAuth / ChatGPT session | no | yes, owned by Codex | no |
| Allowed folder paths | no | yes | no |
| Full project alias list / selected absolute root | no | yes | no |
| Current display-safe project alias (max 80 chars) | yes | yes | yes |
| Source tree and files | no | yes | no |
| Codex thread id / turn id | no | yes | no |
| Opaque `conversation_id` | yes | yes | yes |
| Voice prompt, bounded status/result text | yes | yes | yes |
| File patches, command output, secrets | no | local only | no |

The MVP asks Codex for a spoken summary under 700 characters and applies a hard
4000-character transport bound. It is not a
source file, patch, terminal log or secret-bearing tool result. Companion PWA
support must define a separate encrypted content contract before carrying longer
code or files.

## Hub job state machine

```text
queued → dispatched → running → completed
                    ↘ needs_input → (new continue/steer job)
                    ↘ failed
                    ↘ interrupted

dispatched -- lease expires --> dispatched with a new lease_id
```

Every job belongs to one Hub user, one Nexus installation and one Desktop
Connector. Connector poll queries by that exact connector row, and event publish
requires both its bearer token and the current `lease_id`. Nexus reads a job only
through the installation that created it.

`client_request_id` makes Nexus retries idempotent. `conversation_id` is generated
by Hub for `start` and `select_project`; `continue`, `steer`, `interrupt` and
`summarize` must reuse it. `select_project` carries only the spoken alias. The
Connector resolves it against local allowed roots and persists the selected root
locally for that conversation.
The Connector keeps the local mapping from `conversation_id` to Codex thread id
and active turn id. Hub never receives those local ids.

## HTTP v1 contract

All API paths are relative to the configured Django script prefix.

Nexus Codex plugin:

- `POST /api/v1/nexus/codex/pairing/start`
- `POST /api/v1/nexus/codex/pairing/poll`
- `POST /api/v1/nexus/codex/status`
- `POST /api/v1/nexus/codex/jobs`
- `GET /api/v1/nexus/codex/jobs/{job_id}?after_sequence=N`

Authenticated calls use `Authorization: Bearer …` and
`X-RokidHub-Installation-ID: …`.

Desktop Connector:

- `POST /api/v1/desktop/pairing/start`
- `POST /api/v1/desktop/pairing/poll`
- `POST /api/v1/desktop/status`
- `POST /api/v1/desktop/jobs/poll`
- `POST /api/v1/desktop/jobs/{job_id}/events`

Authenticated calls use `Authorization: Bearer …` and
`X-RokidHub-Connector-ID: …`.

`POST /api/v1/desktop/status` also returns `codex_nexus_paired`, a boolean that
only reflects a non-revoked `rokidhub.codex` Nexus installation owned by the
same user. The response does not expose the Nexus installation id, token or any
Yandex plugin state. Before the PC is paired, the Connector cannot determine a
user-scoped glasses status and must display it as unknown.

A polled job contains `job_id`, `conversation_id`, `action`, `prompt` and a
short-lived `lease_id`. Event bodies contain:

```json
{
  "lease_id": "uuid",
  "sequence": 2,
  "type": "status | delta | needs_input | final | error",
  "status": "running | completed | failed | interrupted",
  "message": "bounded display-safe text",
  "project_name": "short voice alias; never an absolute path"
}
```

Sequences are unique per job, so safe HTTP retries do not duplicate events.
Nexus HUD maps job states to «Подключаю ПК», «Codex анализирует», «Нужен ответ»,
«Готово», «Ошибка» or «Остановлено» and renders `project_name` in the small
footer. TTS uses only the final short summary. Hub rejects project metadata with
path separators; the Connector sends only the locally configured voice alias.

## Codex app-server adapter

The adapter follows the installed CLI schema, not a hand-written substitute.
For `codex-cli 0.144.5` the schema is generated with:

```powershell
codex app-server generate-json-schema --out .\schemas
```

The local flow is `initialize`, `initialized`, `thread/start` (or
`thread/resume`), `turn/start`, then streamed notifications including
`item/agentMessage/delta` and `turn/completed`. Active turns support
`turn/steer` with `expectedTurnId` and `turn/interrupt`. See the
[official Codex App Server documentation](https://developers.openai.com/codex/app-server).

Agent deltas stay inside the Connector. The adapter groups them by the schema's
`itemId` and publishes only the last completed `agentMessage`, preferring
`phase=final_answer`; interim `phase=commentary` text is never appended to the
Hub/TTS result.

The local GUI offers three policy profiles: `readOnly` + `never`, `readOnly` +
`on-request` with a local Windows approval prompt, and `workspaceWrite` scoped to
the selected root with `untrusted` command approvals. Network remains disabled.
`dangerFullAccess` is intentionally unavailable. The Connector refuses to start
a Codex job until the user has configured an existing allowed root. Hub and Nexus
cannot widen the root or change the local profile.

## Threat model

| Threat | MVP control | Remaining work |
|---|---|---|
| Hub database leak | only token hashes; no Codex auth, paths or source | retention policy for prompts/results |
| Stolen Nexus token | scoped to one plugin installation; user revocation | device attestation/risk signals |
| Stolen Desktop token | DPAPI at rest; scoped connector id; revocation | signed installer and auto-update |
| Cross-user routing | all jobs bind user + Nexus + Desktop rows | multi-device audit UI |
| Replay/duplicate delivery | idempotency key, lease id, event sequence | WSS session nonce |
| Prompt asks for writes/exfiltration | local access profile, root checks, network disabled, local PC approval | richer diff preview before approval |
| Malicious Hub job changes cwd | local allowlist resolution rejects it | signed policy snapshots |
| Connector crash | lease expiry permits redelivery | resumable WSS and backoff telemetry |

## WSS migration

The Connector will still open the connection outbound. After authenticating the
same connector credential over `wss://`, Hub can push `job.available`; Connector
then acknowledges the job lease and publishes the same sequenced events. HTTPS
poll remains a recovery path. No app-server socket is exposed to Hub or the LAN.
