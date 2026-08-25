$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "start.ps1") gui @args
exit $LASTEXITCODE
