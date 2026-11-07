# Deploy over USB with mpremote (https://docs.micropython.org/en/latest/reference/mpremote.html).
# 1) Flash MicroPython first (once):
#      esptool --chip esp32s3 --port COM9 erase_flash
#      esptool --chip esp32s3 --port COM9 write_flash -z 0 ESP32_GENERIC_S3-*.bin
#    Use a recent ESP32-S3 build with PSRAM + LittleFS (Oct 2025+).
# 2) Install Microdot (once):
#      mpremote connect COM9 mip install github:miguelgrinberg/microdot/src/microdot
# 3) Copy project files (repeat after every edit):
#      mpremote connect COM9 cp -r config.py agent_tools.py llm.py net.py server.py main.py boot.py tools www :
#    or run this script:  powershell -File deploy.ps1 -Port COM9
param([string]$Port = "COM9")

$ErrorActionPreference = "Stop"
$mpremote = "mpremote"

function MPRun($args) {
  Write-Host "> mpremote $args"
  & $mpremote @args
  if ($LASTEXITCODE -ne 0) { throw "mpremote failed: $args" }
}

MPRun @("connect", $Port, "cp", "config.py", ":config.py")
MPRun @("connect", $Port, "cp", "agent_tools.py", ":agent_tools.py")
MPRun @("connect", $Port, "cp", "llm.py", ":llm.py")
MPRun @("connect", $Port, "cp", "net.py", ":net.py")
MPRun @("connect", $Port, "cp", "server.py", ":server.py")
MPRun @("connect", $Port, "cp", "main.py", ":main.py")
MPRun @("connect", $Port, "cp", "boot.py", ":boot.py")
MPRun @("connect", $Port, "cp", "-r", "tools", ":tools")
MPRun @("connect", $Port, "cp", "-r", "www", ":www")
Write-Host "Deploy done. Reset the board: mpremote connect $Port reset"
