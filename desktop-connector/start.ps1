param(
    [ValidateSet("pair", "configure", "doctor", "models", "run", "gui")]
    [string]$Command = "run",
    [switch]$Mock,
    [switch]$Once,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ConnectorArguments
)

$ErrorActionPreference = "Stop"
$connectorPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $connectorPython)) {
    $connectorPython = Join-Path (Split-Path -Parent $PSScriptRoot) ".venv\Scripts\python.exe"
    $connectorSource = Join-Path $PSScriptRoot "src"
    $env:PYTHONPATH = if ($env:PYTHONPATH) { "$connectorSource;$env:PYTHONPATH" } else { $connectorSource }
}
if (-not (Test-Path -LiteralPath $connectorPython)) {
    throw "Сначала создай окружение: py -m venv .venv; .\.venv\Scripts\pip.exe install -e ."
}
$connectorArgs = @("-m", "rokidhub_desktop_connector", $Command)
$connectorArgs += $ConnectorArguments
if ($Mock) { $connectorArgs += "--mock" }
if ($Once) { $connectorArgs += "--once" }
& $connectorPython @connectorArgs
exit $LASTEXITCODE
