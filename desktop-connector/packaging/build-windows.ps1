param(
    [string]$ReleaseVersion = "0.6.0-beta.6",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Create .venv and install .[build] before packaging."
}

$productName = "RokidHub Desktop Connector"
$distributionName = "RokidHub-Desktop-Connector-v$ReleaseVersion"
$distDirectory = Join-Path $projectRoot "dist"
$applicationDirectory = Join-Path $distDirectory $productName
$artifactDirectory = Join-Path $projectRoot "artifacts"
$versionFile = Join-Path $PSScriptRoot "windows-version-info.txt"
$iconFile = Join-Path $projectRoot "src\rokidhub_desktop_connector\assets\favicon.ico"

if (-not (Test-Path -LiteralPath $versionFile)) {
    throw "Windows version metadata is missing: $versionFile"
}
$packageVersion = (& $python -c "from rokidhub_desktop_connector import __version__; print(__version__)").Trim()
$expectedReleaseVersion = $packageVersion -replace '^([0-9]+\.[0-9]+\.[0-9]+)b([0-9]+)$', '$1-beta.$2'
if ($ReleaseVersion -ne $expectedReleaseVersion) {
    throw "ReleaseVersion '$ReleaseVersion' does not match package version '$packageVersion' ($expectedReleaseVersion)."
}
if ((Get-Content -LiteralPath $versionFile -Raw) -notmatch [regex]::Escape("ProductVersion', '$ReleaseVersion")) {
    throw "Windows version metadata does not match $ReleaseVersion."
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
        --onedir `
        --windowed `
        --noupx `
        --name $productName `
        --version-file $versionFile `
        --icon $iconFile `
        --paths "src" `
        --collect-data "rokidhub_desktop_connector" `
        "packaging\windows_entry.py"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

    if (-not (Test-Path -LiteralPath (Join-Path $applicationDirectory "$productName.exe"))) {
        throw "PyInstaller output is incomplete: $applicationDirectory"
    }

    New-Item -ItemType Directory -Path $artifactDirectory -Force | Out-Null
    $portableZip = Join-Path $artifactDirectory "$distributionName-portable.zip"
    Compress-Archive -LiteralPath $applicationDirectory -DestinationPath $portableZip -CompressionLevel Optimal -Force

    if (-not $SkipInstaller) {
        $innoCandidates = @(
            (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1),
            (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
            "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
            "C:\Program Files\Inno Setup 6\ISCC.exe"
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
        $innoCompiler = $innoCandidates | Select-Object -First 1
        if (-not $innoCompiler) {
            throw "Inno Setup 6 is required for the installer. Install JRSoftware.InnoSetup or use -SkipInstaller."
        }
        & $innoCompiler `
            "/DAppVersion=$ReleaseVersion" `
            "/DSourceDir=$applicationDirectory" `
            "/DOutputDir=$artifactDirectory" `
            "/DOutputBaseFilename=$distributionName-setup" `
            (Join-Path $PSScriptRoot "windows-installer.iss")
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed with exit code $LASTEXITCODE" }
    }

    $releaseFiles = Get-ChildItem -LiteralPath $artifactDirectory -File | Where-Object {
        $_.Name -like "$distributionName-*"
    }
    $checksums = $releaseFiles | Sort-Object Name | ForEach-Object {
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $($_.Name)"
    }
    Set-Content -LiteralPath (Join-Path $artifactDirectory "SHA256SUMS.txt") -Value $checksums -Encoding utf8NoBOM
    $releaseFiles | Sort-Object Name | Select-Object Name, Length, FullName
} finally {
    $env:PATH = $originalPath
    Pop-Location
}
