# Security policy

Please do not disclose vulnerabilities in a public issue. Report them privately
through the repository owner's GitHub profile or the RokidHub contact channel.

Never attach access tokens, Codex authentication files, private source code,
DPAPI blobs, Android signing keys or production `.env` files to a report.

The public beta intentionally excludes unrestricted/danger-full access. Start
with read-only mode, allow only explicit project folders, and review every local
write or command approval. See [`docs/architecture.md`](docs/architecture.md)
for trust boundaries and the threat model.
