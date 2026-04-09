param(
    [switch]$Startup,
    [switch]$Desktop,
    [switch]$TaskbarPinned,
    [switch]$LaunchCloudMusic,
    [switch]$RestartCloudMusicWithDebug,
    [int]$Port = 9222
)

$root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $root 'launcher.pyw'
$launcherExeCandidates = @(
    (Join-Path $root 'build-tasklyric\launcher\tasklyric_launcher.exe'),
    (Join-Path $root 'build\launcher\tasklyric_launcher.exe'),
    (Join-Path $root 'dist\tasklyric_launcher.exe')
)
$launcherExe = $launcherExeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($launcherExe) {
    $targetPath = $launcherExe
    $baseArguments = @('--remote-debug-port', $Port)
} else {
    if (-not (Test-Path $launcher)) {
        throw "launcher.pyw not found: $launcher"
    }
    $pythonw = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if (-not $pythonw) {
        throw 'pythonw.exe was not found in PATH.'
    }
    $targetPath = $pythonw.Source
    $baseArguments = @('"' + $launcher + '"', '--remote-debug-port', $Port)
}

function Get-CloudMusicExecutable {
    $processPath = Get-CimInstance Win32_Process -Filter "name='cloudmusic.exe'" -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty ExecutablePath
    if ($processPath -and (Test-Path $processPath)) {
        return $processPath
    }
    $candidates = @(
        'D:\CloudMusic\CloudMusic\cloudmusic.exe',
        (Join-Path $env:ProgramFiles 'NetEase\CloudMusic\cloudmusic.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\NetEase\CloudMusic\cloudmusic.exe')
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }
    return $null
}

function Set-Shortcut {
    param(
        [string]$LinkPath,
        [string]$TargetPath,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [string]$IconLocation,
        [string]$Description
    )

    $wsh = New-Object -ComObject WScript.Shell
    $shortcut = $wsh.CreateShortcut($LinkPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.Arguments = [string]::Join(' ', $Arguments)
    $shortcut.WorkingDirectory = $WorkingDirectory
    if ($IconLocation) {
        $shortcut.IconLocation = $IconLocation
    }
    if ($Description) {
        $shortcut.Description = $Description
    }
    $shortcut.Save()
}

function Backup-ShortcutIfNeeded {
    param([string]$LinkPath)
    $backupPath = "$LinkPath.tasklyric-backup"
    if ((Test-Path $LinkPath) -and -not (Test-Path $backupPath)) {
        Copy-Item -LiteralPath $LinkPath -Destination $backupPath -Force
    }
}

function Get-PinnedTaskbarCloudMusicLinks {
    $pinned = Join-Path $env:APPDATA 'Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar'
    if (-not (Test-Path $pinned)) {
        return @()
    }
    $patterns = @('*网易云*.lnk', '*CloudMusic*.lnk', '*NetEase*Music*.lnk')
    $results = @()
    foreach ($pattern in $patterns) {
        $results += Get-ChildItem -Path $pinned -Filter $pattern -ErrorAction SilentlyContinue
    }
    return $results | Sort-Object FullName -Unique
}

$cloudMusicExe = Get-CloudMusicExecutable
$iconLocation = if ($cloudMusicExe) { "$cloudMusicExe,0" } else { "$env:SystemRoot\System32\SHELL32.dll,220" }

$targets = @()
if ($Startup) {
    $targets += [Environment]::GetFolderPath('Startup')
}
if ($Desktop) {
    $targets += [Environment]::GetFolderPath('Desktop')
}
$targets = $targets | Select-Object -Unique

foreach ($target in $targets) {
    if (-not (Test-Path $target)) {
        continue
    }

    if ($target -eq [Environment]::GetFolderPath('Startup')) {
        $arguments = @($baseArguments)
        if ($LaunchCloudMusic) {
            $arguments += '--launch-cloudmusic'
        }
        if ($RestartCloudMusicWithDebug) {
            $arguments += '--restart-cloudmusic-with-debug'
        }
        $linkName = 'TaskLyric Background.lnk'
        $description = 'Watch Cloud Music and start TaskLyric when it is running.'
    } else {
        $arguments = @($baseArguments)
        $arguments += '--launch-cloudmusic'
        $arguments += '--restart-cloudmusic-with-debug'
        $linkName = 'TaskLyric Launcher.lnk'
        $description = 'Launch NetEase Cloud Music with TaskLyric in the stable recovery flow.'
    }

    $linkPath = Join-Path $target $linkName
    Set-Shortcut -LinkPath $linkPath -TargetPath $targetPath -Arguments $arguments -WorkingDirectory $root -IconLocation $iconLocation -Description $description
    Write-Host "Created shortcut: $linkPath"
}

if ($TaskbarPinned) {
    $taskbarLinks = Get-PinnedTaskbarCloudMusicLinks
    if (-not $taskbarLinks) {
        Write-Warning 'No pinned Cloud Music taskbar shortcut was found.'
    }
    if (-not $cloudMusicExe) {
        throw 'cloudmusic.exe was not found, so the pinned taskbar shortcut cannot be updated safely.'
    }
    foreach ($shortcutFile in $taskbarLinks) {
        Backup-ShortcutIfNeeded -LinkPath $shortcutFile.FullName
        $arguments = @("--remote-debugging-port=$Port")
        Set-Shortcut -LinkPath $shortcutFile.FullName -TargetPath $cloudMusicExe -Arguments $arguments -WorkingDirectory (Split-Path -Parent $cloudMusicExe) -IconLocation $iconLocation -Description 'Launch NetEase Cloud Music with the remote debug port required by TaskLyric.'
        Write-Host "Updated pinned taskbar shortcut: $($shortcutFile.FullName)"
    }
}
