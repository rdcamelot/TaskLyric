param()

$desktop = [Environment]::GetFolderPath('Desktop')
$startMenuUser = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$startMenuCommon = Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs'
$roots = @($desktop, $startMenuUser, $startMenuCommon) | Where-Object { $_ -and (Test-Path $_) }
$backups = @()
foreach ($rootPath in $roots | Select-Object -Unique) {
    $backups += Get-ChildItem -Path $rootPath -Filter '*.lnk.tasklyric-backup' -Recurse -ErrorAction SilentlyContinue
}
$backups = $backups | Sort-Object FullName -Unique
if (-not $backups) {
    Write-Host 'No TaskLyric shortcut backups were found.'
    return
}
foreach ($backup in $backups) {
    $originalPath = $backup.FullName -replace '\.tasklyric-backup$',''
    Copy-Item -LiteralPath $backup.FullName -Destination $originalPath -Force
    Write-Host "Restored shortcut: $originalPath"
}
