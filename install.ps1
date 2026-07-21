param(
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $project ".venv\Scripts\python.exe"

if (-not $Python) {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $Python = $pyLauncher.Source
    }
    elseif ($pythonCommand) {
        $Python = $pythonCommand.Source
    }
    else {
        throw "Python 3.10+ was not found. Re-run with -Python C:\path\to\python.exe"
    }
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    & $Python -m venv (Join-Path $project ".venv")
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -e "${project}[dev]"
& $venvPython -m pytest

Write-Host "Installed successfully."
Write-Host "Run: $project\ips3608.cmd start"
