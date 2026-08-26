# Changelog

## Unreleased

## 0.6.0-beta.3 — 2026-08-26

- The Overview page now presents the active access policy as a compact summary
  that opens Security; the policy selector and full-access confirmation live in
  Security only.

## 0.6.0-beta.2 — 2026-08-26

- Explicit project voice aliases are now authoritative: after the user removes
  the real folder name from an alias list, it no longer reappears in Settings
  or remains silently available to the voice project resolver.

## 0.6.0-beta.1 — 2026-08-25

- The overview uses a green check and green status text only while the Connector
  process is running; a paired but stopped Connector now uses the neutral palette.
- Explicit single-frame camera commands can capture a JPEG through Nexus and
  deliver it once to the leased Connector as a local Codex App Server image.
- Camera frames are re-encoded without original EXIF, bounded to 5 MiB, verified
  by SHA-256 and removed from Hub/PC temporary storage after retrieval or expiry.
- Project-specific voice aliases handle alternative STT spellings without
  exposing local paths to RokidHub.

## 0.5.0-beta.1 — 2026-08-25

- First public vertical-slice release.
- Separate revocable pairing for Nexus and every Windows PC.
- Outbound-only HTTPS polling between Connector and RokidHub.
- Local Codex App Server threads, turns, steer and interrupt.
- Allowed-folder project aliases and voice project selection.
- Read-only, ask and scoped workspace-write policies with local approval.
- Modern RU/EN Windows GUI, tray behavior and optional per-user autostart.
- RU/EN Nexus HUD, STT locale and voice control phrases.
