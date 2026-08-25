# Privacy

RokidHub · Codex is designed so that Codex/ChatGPT authentication, source files,
absolute project paths, Codex thread/turn identifiers and local approval policy
remain on the Windows PC.

RokidHub receives a bounded voice prompt, device-safe project alias, job state,
short status events and a short final summary required to deliver the headset
experience. It stores only SHA-256 verifiers for independently revocable Nexus
and Desktop Connector access tokens; raw access tokens are returned once to the
corresponding device.

The Android token is protected by Android Keystore-backed encryption. The PC
token is protected with Windows DPAPI for the current Windows user. The Connector
opens outbound HTTPS requests only and does not expose Codex App Server to the
LAN or internet.

Do not include secrets in spoken prompts. Server-side retention and account
deletion are governed by the RokidHub privacy terms shown on rokidhub.com.
