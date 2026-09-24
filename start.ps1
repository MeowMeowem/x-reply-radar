# Windows: right-click > Run with PowerShell. First run sets everything up.
Set-Location $PSScriptRoot
if (-not (Test-Path .venv\Scripts\python.exe)) {
  Write-Host "Setting up (first run only)..."
  py -3 -m venv .venv
  .venv\Scripts\python.exe -m pip install -q --upgrade pip
  .venv\Scripts\python.exe -m pip install -q -r requirements.txt
  .venv\Scripts\python.exe -m playwright install chromium
}
if ($args[0] -eq "--demo") { .venv\Scripts\python.exe scripts\demo.py @($args | Select-Object -Skip 1) } else { .venv\Scripts\python.exe app.py }
