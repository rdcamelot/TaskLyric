param()

$pinned = Join-Path $env:APPDATA 'Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar'
if (-not (Test-Path $pinned)) {
    Write-Host 'Pinned taskbar shortcut folder was not found.'
    return
}
$backups = Get-ChildItem -Path $pinned -Filter '*.lnk.tasklyric-backup' -ErrorAction SilentlyContinue | Sort-Object FullName -Unique
if (-not $backups) {
    Write-Host 'No TaskLyric taskbar shortcut backups were found.'
    return
}
foreach ($backup in $backups) {
    $originalPath = $backup.FullName -replace '\.tasklyric-backup$',''
    Copy-Item -LiteralPath $backup.FullName -Destination $originalPath -Force
    Write-Host "Restored shortcut: $originalPath"
}
