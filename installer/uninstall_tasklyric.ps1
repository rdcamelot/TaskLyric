param(
    [switch]$CleanConfig = $false,
    [switch]$Force = $false
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "========== TaskLyric Uninstall ==========" -ForegroundColor Cyan

if (-not $Force) {
    Write-Host "This will remove:" -ForegroundColor Yellow
    Write-Host "  - All TaskLyric processes"
    Write-Host "  - Compiled files (build/, build-tasklyric/)"
    Write-Host "  - Logs and temp files"
    Write-Host ""
    $confirm = Read-Host "Continue? (yes/no)"
    if ($confirm -ne "yes" -and $confirm -ne "y") {
        Write-Host "Cancelled" -ForegroundColor Red
        exit 0
    }
}

Write-Host "Stopping processes..." -ForegroundColor Yellow
try {
    python (Join-Path $root "launcher.pyw") --stop-all 2>&1 | Out-Null
} catch {}

Start-Sleep -Seconds 1

$dirs = @(
    "dist/TaskLyric",
    "build/host", "build/native", "build/launcher",
    "build-tasklyric/host", "build-tasklyric/native", "build-tasklyric/launcher",
    "logs", "state", "tmp",
    "__pycache__", "src/netease_taskbar_lyrics/__pycache__", "scripts/__pycache__"
)

Write-Host "Removing files..." -ForegroundColor Yellow
foreach ($dir in $dirs) {
    $path = Join-Path $root $dir
    if (Test-Path $path) {
        Remove-Item -Path $path -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "  - Removed $dir"
    }
}

if ($CleanConfig) {
    $cfg = Join-Path $root "config/tasklyric.config.json"
    if (Test-Path $cfg) {
        Remove-Item -Path $cfg -Force
        Write-Host "  - Removed config file"
    }
} else {
    Write-Host "  - Config preserved (use -CleanConfig to remove)"
}

Write-Host "`nDone!" -ForegroundColor Green
Write-Host "Next: cmake --build .\build-tasklyric --config Release`n" -ForegroundColor Cyan
