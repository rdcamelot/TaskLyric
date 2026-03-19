param(
    [int]$Port = 9222,
    [switch]$RestartExisting
)

$running = Get-CimInstance Win32_Process -Filter "name='cloudmusic.exe'"
$exePath = $null
if ($running) {
    $exePath = ($running | Select-Object -First 1).ExecutablePath
}

if (-not $exePath) {
    $candidates = @(
        "D:\CloudMusic\CloudMusic\cloudmusic.exe",
        "$env:ProgramFiles\NetEase\CloudMusic\cloudmusic.exe",
        "$env:LOCALAPPDATA\Programs\NetEase\CloudMusic\cloudmusic.exe"
    )
    $exePath = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}

if (-not $exePath) {
    throw "Unable to locate cloudmusic.exe. Start NetEase Cloud Music once or edit this script with your install path."
}

if ($running -and -not $RestartExisting) {
    Write-Host "NetEase Cloud Music is already running. Close it first, or rerun with -RestartExisting." -ForegroundColor Yellow
    Write-Host "Exact sync via Chromium remote debugging only attaches reliably when Cloud Music is started with the debug port." -ForegroundColor Yellow
    exit 1
}

if ($running -and $RestartExisting) {
    $running | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force
    }
    Start-Sleep -Milliseconds 800
}

$workingDirectory = Split-Path -Parent $exePath
Start-Process -FilePath $exePath -WorkingDirectory $workingDirectory -ArgumentList "--remote-debugging-port=$Port"
Write-Host "Started NetEase Cloud Music with --remote-debugging-port=$Port" -ForegroundColor Green
