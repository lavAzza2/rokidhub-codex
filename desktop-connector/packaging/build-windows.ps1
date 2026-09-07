$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Create .venv and install .[build] before packaging."
}

Push-Location $projectRoot
$originalPath = $env:PATH
try {
    # Codex Desktop may prepend document/media helper runtimes to PATH. Their
    # unrelated ICU/OpenSSL/UCRT DLLs can be mistaken for application
    # dependencies by PyInstaller and make Qt fail at startup.
    $env:PATH = (($originalPath -split ';') | Where-Object {
        $_ -notmatch '\\codex-runtimes\\.*\\dependencies\\native(?:\\|$)'
    }) -join ';'
    & $python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name "RokidHub-Desktop-Connector-v0.6.0-beta.5" `
        --paths "src" `
        --collect-data "rokidhub_desktop_connector" `
        "packaging\windows_entry.py"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
} finally {
    $env:PATH = $originalPath
    Pop-Location
}
