param(
    [switch]$Startup,
    [switch]$Desktop,
    [switch]$LaunchCloudMusic,
    [switch]$RestartCloudMusicWithDebug,
    [int]$Port = 9222
)

$root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $root 'launcher.pyw'
if (-not (Test-Path $launcher)) {
    throw "launcher.pyw not found: $launcher"
}

$pythonw = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if (-not $pythonw) {
    throw 'pythonw.exe was not found in PATH.'
}

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

$arguments = @('"' + $launcher + '"', '--remote-debug-port', $Port)
if ($LaunchCloudMusic) {
    $arguments += '--launch-cloudmusic'
}
if ($RestartCloudMusicWithDebug) {
    $arguments += '--restart-cloudmusic-with-debug'
}
$argumentLine = [string]::Join(' ', $arguments)

$wsh = New-Object -ComObject WScript.Shell
foreach ($target in $targets | Select-Object -Unique) {
    if (-not (Test-Path $target)) {
        continue
    }
    $linkPath = Join-Path $target 'TaskLyric.lnk'
    $shortcut = $wsh.CreateShortcut($linkPath)
    $shortcut.TargetPath = $pythonw.Source
    $shortcut.Arguments = $argumentLine
    $shortcut.WorkingDirectory = $root
    $shortcut.IconLocation = "$env:SystemRoot\System32\SHELL32.dll,220"
    $shortcut.Save()
    Write-Host "Created shortcut: $linkPath"
}
