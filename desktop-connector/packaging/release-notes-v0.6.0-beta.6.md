## RokidHub Desktop Connector 0.6.0-beta.6

This release changes how the Windows Connector is packaged to reduce heuristic
antivirus false positives and make installation and updates more predictable.

### What changed

- The recommended download is now a per-user Windows installer.
- The application uses PyInstaller `onedir` instead of a self-extracting
  `onefile` executable, so it no longer unpacks its runtime into a random
  temporary `_MEI...` directory on every launch.
- UPX is explicitly disabled.
- The application and installer now contain a stable product name, description,
  version and RokidHub icon.
- A single-instance guard prevents duplicate Connector tray icons.
- Existing autostart entries are migrated to the installed executable.
- A portable ZIP and SHA-256 checksums are included.
- Windows builds can be reproduced by the pinned GitHub Actions workflow.

### Which file to download

Use `RokidHub-Desktop-Connector-v0.6.0-beta.6-setup.exe` for a normal install.
The installer does not require administrator rights and preserves the local
configuration and DPAPI-protected Connector token during an update.

The portable ZIP is intended for diagnostics and manual use. Extract the whole
folder before launching `RokidHub Desktop Connector.exe`.

### Unsigned beta notice

This beta is not Authenticode-signed yet. Windows SmartScreen or third-party
antivirus software may therefore still warn about an unknown publisher. Do not
disable antivirus protection and do not add broad exclusions. Verify the file
against `SHA256SUMS.txt`. If an antivirus deletes the download, report its name,
the detection name and the exact release file in a GitHub issue so the artifact
can be submitted to that vendor as a false positive.

### Verification

- Desktop Connector: 38 automated tests passed.
- RokidHub backend pairing/job contract: 31 automated tests passed.
- The installed beta completed a production pairing round trip against
  `https://rokidhub.com`, stored the new credential with Windows DPAPI and passed
  the authenticated health check.
