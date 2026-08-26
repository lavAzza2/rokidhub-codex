# RokidHub Codex v0.6.0-beta.2

This patch release fixes project voice alias editing in RokidHub Desktop
Connector.

Previously, the physical folder name was appended again every time aliases were
loaded. Removing `RokidGlasses` (or another folder name) in Settings therefore
looked successful but the value returned immediately. An explicitly saved alias
list is now used exactly as configured. The folder name remains the initial
fallback only until the user saves aliases for that project.

The Android plugin is functionally unchanged and is included so the public APK
and Windows Connector share one release version.
