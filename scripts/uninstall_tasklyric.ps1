param(
    [switch]$RestoreTaskbarPinned = $true,
    [switch]$RemoveDesktopShortcut = $true,
    [switch]$RemoveLogs,
    [switch]$Quiet
)

$root = Split-Path -Parent $PSScriptRoot
$startupFolder = [Environment]::GetFolderPath('Startup')
$desktopFolder = [Environment]::GetFolderPath('Desktop')
$backgroundShortcut = Join-Path $startupFolder 'TaskLyric Background.lnk'
$desktopShortcut = Join-Path $desktopFolder 'TaskLyric Launcher.lnk'
$pinnedFolder = Join-Path $env:APPDATA 'Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar'

function Write-Step {
    param([string]$Message)
    if (-not $Quiet) {
        Write-Host $Message
    }
}

Write-Step 'Stopping TaskLyric processes...'
try {
    python (Join-Path $root 'launcher.pyw') --stop 2>$null | Out-Null
} catch {}

$stopCommand = @(
    "Get-CimInstance Win32_Process",
    "| Where-Object { ($_.Name -ieq 'pythonw.exe' -or $_.Name -ieq 'python.exe') -and $_.CommandLine -and (",
    "$_.CommandLine -like '*TaskLyric__efb8867*main.py*' -or $_.CommandLine -like '*TaskLyric*main.py*' -or ",
    "$_.CommandLine -like '*TaskLyric__efb8867*launcher.pyw*' -or $_.CommandLine -like '*TaskLyric*launcher.pyw*') }",
    "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
) -join ' '
try {
    powershell -NoProfile -ExecutionPolicy Bypass -Command $stopCommand 2>$null | Out-Null
} catch {}

if (Test-Path $backgroundShortcut) {
    Remove-Item -LiteralPath $backgroundShortcut -Force -ErrorAction SilentlyContinue
    Write-Step "Removed: $backgroundShortcut"
}

if ($RemoveDesktopShortcut -and (Test-Path $desktopShortcut)) {
    Remove-Item -LiteralPath $desktopShortcut -Force -ErrorAction SilentlyContinue
    Write-Step "Removed: $desktopShortcut"
}

if ($RestoreTaskbarPinned -and (Test-Path $pinnedFolder)) {
    $backups = Get-ChildItem -Path $pinnedFolder -Filter '*.lnk.tasklyric-backup' -ErrorAction SilentlyContinue | Sort-Object FullName -Unique
    foreach ($backup in $backups) {
        $originalPath = $backup.FullName -replace '\.tasklyric-backup$',''
        Copy-Item -LiteralPath $backup.FullName -Destination $originalPath -Force
        Remove-Item -LiteralPath $backup.FullName -Force -ErrorAction SilentlyContinue
        Write-Step "Restored pinned shortcut: $originalPath"
    }
}

if ($RemoveLogs) {
    foreach ($path in @((Join-Path $root 'logs'), (Join-Path $root 'state'))) {
        if (Test-Path $path) {
            Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
            Write-Step "Removed: $path"
        }
    }
}

Write-Step 'TaskLyric uninstall cleanup completed.'
