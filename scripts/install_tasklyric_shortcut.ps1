param(
    [switch]$Startup,
    [switch]$Desktop,
    [switch]$LaunchCloudMusic,
    [switch]$RestartCloudMusicWithDebug,
    [switch]$ReplaceCloudMusicShortcut,
    [switch]$CleanupLegacyShortcuts,
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

function Get-LauncherCommand {
    if ($launcherExe) {
        return @{
            TargetPath = $launcherExe
            Arguments = @('--remote-debug-port', $Port)
        }
    }

    if (-not (Test-Path $launcher)) {
        throw "launcher.pyw not found: $launcher"
    }
    $pythonw = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if (-not $pythonw) {
        throw 'pythonw.exe was not found in PATH.'
    }
    return @{
        TargetPath = $pythonw.Source
        Arguments = @('"' + $launcher + '"', '--remote-debug-port', $Port)
    }
}

function Find-CloudMusicExecutable {
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

    $processPath = Get-CimInstance Win32_Process -Filter "name='cloudmusic.exe'" -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty ExecutablePath
    if ($processPath -and (Test-Path $processPath)) {
        return $processPath
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

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($LinkPath)
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

function Get-CloudMusicShortcutCandidates {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $startMenuUser = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    $startMenuCommon = Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs'
    $taskbarPinned = Join-Path $env:APPDATA 'Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar'
    $roots = @($desktop, $startMenuUser, $startMenuCommon, $taskbarPinned) | Where-Object { $_ -and (Test-Path $_) }
    $patterns = @('*网易云*.lnk', '*CloudMusic*.lnk', '*NetEase*Music*.lnk')
    $results = @()
    foreach ($rootPath in $roots | Select-Object -Unique) {
        foreach ($pattern in $patterns) {
            $results += Get-ChildItem -Path $rootPath -Filter $pattern -Recurse -ErrorAction SilentlyContinue
        }
    }
    $shell = New-Object -ComObject WScript.Shell
    $filtered = foreach ($item in ($results | Sort-Object FullName -Unique)) {
        $name = $item.Name
        if ($name -match '卸载|Uninstall') {
            continue
        }
        $shortcut = $shell.CreateShortcut($item.FullName)
        $target = [string]$shortcut.TargetPath
        $targetLower = $target.ToLowerInvariant()
        $nameLower = $name.ToLowerInvariant()
        if ($targetLower -like '*cloudmusic.exe' -or $nameLower -like '*cloudmusic*' -or $name -like '*网易云*') {
            $item
        }
    }
    return $filtered | Sort-Object FullName -Unique
}

function Backup-ShortcutIfNeeded {
    param([string]$LinkPath)
    $backupPath = "$LinkPath.tasklyric-backup"
    if ((Test-Path $LinkPath) -and -not (Test-Path $backupPath)) {
        try {
            Copy-Item -LiteralPath $LinkPath -Destination $backupPath -Force -ErrorAction Stop
        } catch {
            Write-Warning "Backup skipped due to permissions: $LinkPath"
        }
    }
}

$launcherCommand = Get-LauncherCommand
$cloudMusicExe = Find-CloudMusicExecutable
$cloudMusicIcon = if ($cloudMusicExe) { "$cloudMusicExe,0" } else { "$env:SystemRoot\System32\SHELL32.dll,220" }

$targets = @()
if ($Startup) {
    $targets += [Environment]::GetFolderPath('Startup')
}
if ($Desktop) {
    $targets += [Environment]::GetFolderPath('Desktop')
}
if ($targets.Count -eq 0) {
    $targets += [Environment]::GetFolderPath('Desktop')
}
$targets = $targets | Select-Object -Unique

$desktopMode = $targets -contains [Environment]::GetFolderPath('Desktop')
$startupMode = $targets -contains [Environment]::GetFolderPath('Startup')
$shouldLaunchCloudMusic = $LaunchCloudMusic.IsPresent
$shouldRestartWithDebug = $RestartCloudMusicWithDebug.IsPresent -or $shouldLaunchCloudMusic -or $startupMode

$arguments = @($launcherCommand.Arguments)
if ($shouldLaunchCloudMusic) {
    $arguments += '--launch-cloudmusic'
}
if ($shouldRestartWithDebug) {
    $arguments += '--restart-cloudmusic-with-debug'
}

foreach ($target in $targets) {
    if (-not (Test-Path $target)) {
        continue
    }
    $name = if ($target -eq [Environment]::GetFolderPath('Startup')) { 'TaskLyric Background.lnk' } else { 'TaskLyric Launcher.lnk' }
    $linkPath = Join-Path $target $name
    Set-Shortcut -LinkPath $linkPath -TargetPath $launcherCommand.TargetPath -Arguments $arguments -WorkingDirectory $root -IconLocation $cloudMusicIcon -Description 'Launch NetEase Cloud Music with TaskLyric.'
    Write-Host "Created shortcut: $linkPath"

    if ($CleanupLegacyShortcuts) {
        $legacy = Join-Path $target 'TaskLyric.lnk'
        if (Test-Path $legacy) {
            Remove-Item -LiteralPath $legacy -Force -ErrorAction SilentlyContinue
            Write-Host "Removed legacy shortcut: $legacy"
        }
    }
}

if ($ReplaceCloudMusicShortcut) {
    $shortcutTargets = Get-CloudMusicShortcutCandidates
    if (-not $shortcutTargets) {
        Write-Warning 'No Cloud Music shortcut was found to replace.'
    }
    if (-not $cloudMusicExe) {
        Write-Warning 'Cloud Music executable was not found; cannot replace Cloud Music shortcuts.'
    }
    $cloudMusicArguments = @("--remote-debugging-port=$Port")
    foreach ($shortcutFile in $shortcutTargets) {
        if (-not $cloudMusicExe) {
            continue
        }
        Backup-ShortcutIfNeeded -LinkPath $shortcutFile.FullName
        try {
            Set-Shortcut -LinkPath $shortcutFile.FullName -TargetPath $cloudMusicExe -Arguments $cloudMusicArguments -WorkingDirectory (Split-Path -Parent $cloudMusicExe) -IconLocation $cloudMusicIcon -Description 'Launch NetEase Cloud Music with remote debug port for TaskLyric.'
            Write-Host "Replaced shortcut target: $($shortcutFile.FullName)"
        } catch {
            Write-Warning "Failed to replace shortcut due to permissions: $($shortcutFile.FullName)"
        }
    }
}
