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

When you explicitly say a camera command, the Nexus plugin captures one frame,
removes the original metadata by re-encoding it, and sends a JPEG of at most
5 MiB through RokidHub. The frame is scoped to your Nexus installation, job and
selected PC, has no public URL, and can be downloaded once by the current job
lease. RokidHub clears the bytes after that download or their short expiry; the
Connector deletes its local temporary copy after the Codex turn. Background or
silent capture is not supported.

Do not include secrets in spoken prompts. Server-side retention and account
deletion are governed by the RokidHub privacy terms shown on rokidhub.com.
