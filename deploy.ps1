# Deploy the agent + React dashboard to the ESP32 over USB (mpremote).
#
#   powershell -File deploy.ps1                 # app code + prebuilt UI
#   powershell -File deploy.ps1 -Build          # rebuild the UI first
#   powershell -File deploy.ps1 -Port COM7
#
# Prerequisites (one-off):
#   * MicroPython ESP32_GENERIC_S3-SPIRAM_OCT flashed at offset 0
#   * /lib/microdot deployed (see AGENTS.md -- `mip install` does not work)
#   * tooling: python -m pip install esptool mpremote
#
# The UI is a compiled bundle (ui/ -> www/): index.html, assets/app.js,
# assets/app.css plus their .gz twins. Only three files are served, so the
# deploy is small even though app.js is ~420 KB.
param(
  [string]$Port = "COM11",
  [switch]$Build,
  [switch]$SkipUI
)

$ErrorActionPreference = "Stop"

# Every mpremote call goes through here with a timeout. A hung transfer used
# to block the whole deploy forever (a bare `mpremote connect` waits on stdin
# indefinitely), so now it fails fast naming the command that stalled.
# Returns the command's stdout text; throws on timeout or non-zero exit.
$MPRunTimeoutSec = 180

function MPRun([string[]]$mpArgs) {
  $job = Start-Job -ScriptBlock {
    param($root, $port, $cargs)
    Set-Location $root
    $out = & python -m mpremote connect $port @cargs 2>&1 | Out-String
    Write-Output $out
    Write-Output ("EXIT:" + $LASTEXITCODE)
  } -ArgumentList $PSScriptRoot, $Port, (,$mpArgs)
  $finished = Wait-Job $job -Timeout $MPRunTimeoutSec
  $raw = Receive-Job $job
  Remove-Job $job -Force -ErrorAction SilentlyContinue
  if (-not $finished) {
    throw "mpremote timed out after ${MPRunTimeoutSec}s: $($mpArgs -join ' ')"
  }
  $lines = @($raw -split "`r?`n")
  $exitLine = @($lines | Where-Object { $_ -match "^EXIT:" })[-1]
  $body = (($lines | Where-Object { $_ -notmatch "^EXIT:" }) -join "`n").Trim()
  if ($body) { Write-Host $body }
  $code = if ($exitLine) { [int]($exitLine -replace "^EXIT:", "").Trim() } else { 1 }
  if ($code -ne 0) { throw "mpremote failed (exit $code): $($mpArgs -join ' ')" }
  return $body
}

function Copy-Verified([string]$local, [string]$remote) {
  if (-not (Test-Path $local)) { throw "missing $local" }
  $size = (Get-Item $local).Length
  Write-Host ("-> {0} ({1:N0} B)" -f $remote, $size)
  MPRun @("cp", $local, ":$remote") | Out-Null
  $out = MPRun @("exec", "import os;print(os.stat('$remote')[6])")
  $got = (($out -split "`r?`n") | Select-Object -Last 1).Trim()
  if ($got -ne "$size") { throw "size mismatch for $remote (device $got, local $size)" }
}

if ($Build) {
  Write-Host "Building the dashboard..."
  Push-Location ui
  npm run build
  Pop-Location
}

if (-not (Test-Path "www/index.html")) {
  throw "www/index.html missing -- run 'npm run build' inside ui/ first"
}

Write-Host "Stopping app (waiting for REPL)..."
$repl = MPRun @("exec", "print('IN-REPL')")
if ($repl -notmatch "IN-REPL") { throw "no REPL - the board may still be booting or the port is wrong" }

Write-Host "Ensuring app/ and www/assets exist..."
MPRun @("exec", "import os`nfor _d in ('app', 'www', 'www/assets'):`n try: os.mkdir(_d)`n except OSError: pass") | Out-Null

Write-Host "Deploying application code (app/ + entry points)..."
$code = @(
  "config.py", "config_schema.py", "yamlish.py", "agent_tools.py",
  "agent_core.py", "llm.py", "net.py",
  "server.py", "fsutil.py", "memory.py", "cron.py",
  "skillstore.py", "sessions.py", "delegate.py", "checkpoint.py", "todo.py",
  "gateway.py", "logbuf.py", "prompt.py", "providers.py", "exec_py.py",
  "read_file.py", "write_file.py", "patch_file.py", "search_files.py"
)
foreach ($f in $code) {
  $local = Join-Path "app" $f
  if (Test-Path $local) { Copy-Verified $local ("app/" + $f) }
}
foreach ($f in @("main.py", "boot.py")) {
  if (Test-Path $f) { Copy-Verified $f $f }
}

foreach ($dir in @("app/tools", "skills")) {
  if (Test-Path $dir) {
    $remote = ($dir -replace "\\", "/")
    Write-Host "-> $remote/"
    MPRun @("cp", "-r", $dir, ":$remote")
  }
}

if (-not $SkipUI) {
  Write-Host "Deploying dashboard bundle..."
  foreach ($f in @("index.html", "favicon.svg", "assets/app.js", "assets/app.css",
                   "assets/app.js.gz", "assets/app.css.gz")) {
    $local = Join-Path "www" $f
    if (Test-Path $local) { Copy-Verified $local ("www/" + $f) }
  }
}

Write-Host ""
Write-Host "Deploy complete. Rebooting..."
MPRun @("reset") | Out-Null

Start-Sleep -Seconds 8
Write-Host "Waiting for the device to answer..."
for ($i = 0; $i -lt 10; $i++) {
  try {
    $r = Invoke-WebRequest -Uri "http://192.168.5.56/api/status" -TimeoutSec 5 -UseBasicParsing
    if ($r.StatusCode -eq 200) { Write-Host "Device is up: http://192.168.5.56/"; break }
  } catch {
    Start-Sleep -Seconds 3
  }
}
