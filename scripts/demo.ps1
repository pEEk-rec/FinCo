# Start FinCo for a live demo: the API (reachable from your phone) and the web app.
#   powershell -File scripts\demo.ps1           start both; the demo begins at "connect your bank"
#   powershell -File scripts\demo.ps1 -Reset    wipe the demo data first, to play it from the start
#   powershell -File scripts\demo.ps1 -Stop     stop both
param([switch]$Stop, [switch]$Reset, [string]$Token = "phone")

$root = Split-Path -Parent $PSScriptRoot
$cache = Join-Path (Split-Path -Parent $root) ".dev-cache"
$logs = Join-Path $cache "temp"

function Stop-Port($port) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}

Stop-Port 8765
Stop-Port 5173
if ($Stop) { "Stopped."; return }
$db = Join-Path $root "data\demo_live.db"
if ($Reset) { Start-Sleep 1; Remove-Item "$db*" -Force -ErrorAction SilentlyContinue; "Demo data wiped." }

# Keep every cache and temp file on D:, never C:
$env:TEMP = $logs; $env:TMP = $logs
$env:npm_config_cache = Join-Path $cache "npm"
$env:FINCO_MIN_ASK_PAISE = "100"   # demo: ask about every payment of Rs 1 or more

Start-Process -WindowStyle Hidden -FilePath (Join-Path $root ".venv\Scripts\copilot.exe") `
    -ArgumentList "serve", "--db", $db, "--demo", "empty", "--token", $Token, "--real-time", "--lan" `
    -WorkingDirectory $root `
    -RedirectStandardOutput (Join-Path $logs "api.out") -RedirectStandardError (Join-Path $logs "api.err")
Start-Process -WindowStyle Hidden -FilePath "npx.cmd" -ArgumentList "vite", "--host", "0.0.0.0" `
    -WorkingDirectory (Join-Path $root "frontend") `
    -RedirectStandardOutput (Join-Path $logs "web.out") -RedirectStandardError (Join-Path $logs "web.err")

Start-Sleep -Seconds 10
# Secure (HTTPS) address for the phone, through Tailscale: needed for notifications and install.
$secure = $null
try {
    tailscale serve --bg --https=443 http://127.0.0.1:5173 *> $null
    $dns = ((tailscale status --json | ConvertFrom-Json).Self.DNSName).TrimEnd(".")
    if ($dns) { $secure = "https://$dns" }
} catch { }
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -like "192.168.*" } |
    Select-Object -First 1).IPAddress
"`nFinCo is running."
"  Laptop : http://localhost:5173/#token=$Token"
"  Phone  : http://${ip}:5173/#token=$Token   (same Wi-Fi, no notifications)"
if ($secure) { "  Phone  : $secure/#token=$Token   (HTTPS via Tailscale: install + notifications)" }
"  Alerts : the phone macro posts to http://${ip}:8765/api/capture/sms"
"  Watch the alerts arrive:  Get-Content '$logs\api.err' -Wait"
"  Stop   : powershell -File scripts\demo.ps1 -Stop"
