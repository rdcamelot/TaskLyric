$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]

function Wait-WinRtTask {
    param(
        [Parameter(Mandatory = $true)]
        [object]$AsyncOperation,

        [Parameter(Mandatory = $true)]
        [type]$ResultType
    )

    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq "AsTask" -and
            $_.IsGenericMethod -and
            $_.GetParameters().Count -eq 1
        } |
        Select-Object -First 1

    $task = $method.MakeGenericMethod($ResultType).Invoke($null, @($AsyncOperation))
    return $task.GetAwaiter().GetResult()
}

try {
    $manager = Wait-WinRtTask `
        -AsyncOperation ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) `
        -ResultType ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
} catch {
    $payload = @{
        error = "session_manager_unavailable"
        message = $_.Exception.Message
    }
    ConvertTo-Json -InputObject $payload -Compress
    exit 0
}

if ($null -eq $manager) {
    ConvertTo-Json -InputObject @() -Compress
    exit 0
}

$sessions = New-Object System.Collections.Generic.List[object]

foreach ($session in $manager.GetSessions()) {
    try {
        $media = Wait-WinRtTask `
            -AsyncOperation ($session.TryGetMediaPropertiesAsync()) `
            -ResultType ([Windows.Media.MediaProperties.GlobalSystemMediaTransportControlsSessionMediaProperties])

        $timeline = $session.GetTimelineProperties()
        $playbackInfo = $session.GetPlaybackInfo()
        $playbackStatus = if ($null -ne $playbackInfo) { [string]$playbackInfo.PlaybackStatus } else { "Unknown" }

        $sessions.Add([pscustomobject]@{
            sourceAppUserModelId = $session.SourceAppUserModelId
            title = $media.Title
            artist = $media.Artist
            albumTitle = $media.AlbumTitle
            positionMs = [int64][math]::Round($timeline.Position.TotalMilliseconds)
            durationMs = [int64][math]::Round($timeline.EndTime.TotalMilliseconds)
            startTimeMs = [int64][math]::Round($timeline.StartTime.TotalMilliseconds)
            playbackStatus = $playbackStatus
        })
    } catch {
        continue
    }
}

ConvertTo-Json -InputObject @($sessions.ToArray()) -Compress -Depth 4
