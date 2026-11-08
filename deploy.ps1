# Deploy the agent + React dashboard to the ESP32 over USB (mpremote).
#
#   powershell -File deploy.ps1                 # app code + prebuilt UI
#   powershell -File deploy.ps1 -Build          # rebuild the UI first
#   powershell -File deploy.ps1 -Port COM7
#
# Prerequisites (one-off):
#   * MicroPython ESP32_GENERIC_S3-SPIRAM_OCT flashed at offset 0
#   * /lib/microdot deployed (see AGENTS.md — `mip install` does not work)
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

function MPRun([string[]]$args) {
  & python -m mpremote connect $Port @args
  if ($LASTEXITCODE -ne 0) { throw "mpremote failed: $($args -join ' ')" }
}

function Copy-Verified([string]$local, [string]$remote) {
  if (-not (Test-Path $local)) { throw "missing $local" }
  $size = (Get-Item $local).Length
  Write-Host ("-> {0} ({1:N0} B)" -f $remote, $size)
  MPRun @("cp", $local, ":$remote")
  $got = (& python -m mpremote connect $Port exec "import os;print(os.stat('$remote')[6])" | Select-Object -Last 1).Trim()
  if ($got -ne "$size") { throw "size mismatch for $remote (device $got, local $size)" }
}

if ($Build) {
  Write-Host "Building the dashboard..."
  Push-Location ui
  npm run build
  Pop-Location
}

if (-not (Test-Path "www/index.html")) {
  throw "www/index.html missing — run 'npm run build' inside ui/ first"
}

Write-Host "Ensuring www/assets exists..."
& python -m mpremote connect $Port exec "import os`ntry: os.mkdir('www/assets')`nexcept OSError: pass"
if ($LASTEXITCODE -ne 0) { throw "could not create www/assets" }

Write-Host "Deploying application code..."
$code = @(
  "config.py", "config_schema.py", "yamlish.py", "agent_tools.py",
  "agent_core.py", "llm.py", "net.py",
  "server.py", "main.py", "boot.py", "fsutil.py", "memory.py", "cron.py",
  "skillstore.py", "sessions.py", "delegate.py", "checkpoint.py", "todo.py",
  "gateway.py", "logbuf.py", "prompt.py", "providers.py", "exec_py.py",
  "read_file.py", "write_file.py", "patch_file.py", "search_files.py"
)
foreach ($f in $code) {
  if (Test-Path $f) { Copy-Verified $f $f }
}

foreach ($dir in @("tools", "skills")) {
  if (Test-Path $dir) {
    Write-Host "-> $dir/"
    MPRun @("cp", "-r", $dir, ":$dir")
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
& python -m mpremote connect $Port reset

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
