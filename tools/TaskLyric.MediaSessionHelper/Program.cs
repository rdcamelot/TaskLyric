using System.Text.Json;
using Windows.Media.Control;

var command = args.Length > 0 ? args[0].Trim().ToLowerInvariant() : "snapshot";
var exitCode = command switch
{
    "snapshot" => await Commands.RunSnapshotAsync(),
    "watch" => await Commands.RunWatchAsync(ParseIntervalMs(args)),
    "control" => await Commands.RunControlAsync(ParseAction(args)),
    _ => await Commands.RunUsageAsync($"Unknown command: {command}"),
};

return exitCode;

static int ParseIntervalMs(string[] commandArgs)
{
    for (var index = 1; index < commandArgs.Length - 1; index += 1)
    {
        if (!string.Equals(commandArgs[index], "--interval-ms", StringComparison.OrdinalIgnoreCase))
        {
            continue;
        }

        if (int.TryParse(commandArgs[index + 1], out var intervalMs))
        {
            return Math.Clamp(intervalMs, 80, 2000);
        }
    }

    return 220;
}

static string ParseAction(string[] commandArgs)
{
    for (var index = 1; index < commandArgs.Length - 1; index += 1)
    {
        if (string.Equals(commandArgs[index], "--action", StringComparison.OrdinalIgnoreCase))
        {
            return commandArgs[index + 1].Trim().ToLowerInvariant();
        }
    }

    return string.Empty;
}

static class Commands
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = false,
    };

    public static async Task<int> RunUsageAsync(string? errorMessage = null)
    {
        if (!string.IsNullOrWhiteSpace(errorMessage))
        {
            await WriteLineAsync(new ErrorEnvelope("usage", errorMessage));
        }

        await WriteLineAsync(new
        {
            type = "usage",
            commands = new[]
            {
                "snapshot",
                "watch --interval-ms 220",
                "control --action toggle-play-pause|play|pause|next|previous",
            },
        });
        return 1;
    }

    public static async Task<int> RunSnapshotAsync()
    {
        try
        {
            var manager = await GlobalSystemMediaTransportControlsSessionManager.RequestAsync();
            var snapshot = await MediaSessionReader.ReadPreferredSnapshotAsync(manager);
            await WriteLineAsync(new StateEnvelope(snapshot));
            return 0;
        }
        catch (Exception exception)
        {
            await WriteLineAsync(new ErrorEnvelope("snapshot", exception.Message));
            return 2;
        }
    }

    public static async Task<int> RunWatchAsync(int intervalMs)
    {
        while (true)
        {
            try
            {
                var manager = await GlobalSystemMediaTransportControlsSessionManager.RequestAsync();
                while (true)
                {
                    var snapshot = await MediaSessionReader.ReadPreferredSnapshotAsync(manager);
                    await WriteLineAsync(new StateEnvelope(snapshot));
                    await Task.Delay(intervalMs);
                }
            }
            catch (Exception exception)
            {
                await WriteLineAsync(new ErrorEnvelope("watch", exception.Message));
                await Task.Delay(1500);
            }
        }
    }

    public static async Task<int> RunControlAsync(string action)
    {
        if (string.IsNullOrWhiteSpace(action))
        {
            return await RunUsageAsync("Missing --action for control command.");
        }

        try
        {
            var manager = await GlobalSystemMediaTransportControlsSessionManager.RequestAsync();
            var session = await MediaSessionReader.FindPreferredSessionAsync(manager);
            if (session is null)
            {
                await WriteLineAsync(new ControlEnvelope(action, false, "No active media session was found."));
                return 3;
            }

            var ok = action switch
            {
                "toggle-play-pause" => await session.TryTogglePlayPauseAsync(),
                "play" => await session.TryPlayAsync(),
                "pause" => await session.TryPauseAsync(),
                "next" => await session.TrySkipNextAsync(),
                "previous" => await session.TrySkipPreviousAsync(),
                _ => false,
            };

            if (!ok)
            {
                await WriteLineAsync(new ControlEnvelope(action, false, "The selected media session rejected the command."));
                return 4;
            }

            await WriteLineAsync(new ControlEnvelope(action, true, string.Empty));
            return 0;
        }
        catch (Exception exception)
        {
            await WriteLineAsync(new ErrorEnvelope("control", exception.Message));
            return 5;
        }
    }

    private static Task WriteLineAsync(object payload)
    {
        var json = JsonSerializer.Serialize(payload, JsonOptions);
        Console.Out.WriteLine(json);
        return Console.Out.FlushAsync();
    }
}

static class MediaSessionReader
{
    private static readonly string[] NeteaseKeywords = ["cloudmusic", "netease"];

    public static async Task<MediaSessionSnapshot?> ReadPreferredSnapshotAsync(GlobalSystemMediaTransportControlsSessionManager manager)
    {
        var session = await FindPreferredSessionAsync(manager);
        return session is null ? null : await TryBuildSnapshotAsync(session);
    }

    public static async Task<GlobalSystemMediaTransportControlsSession?> FindPreferredSessionAsync(GlobalSystemMediaTransportControlsSessionManager manager)
    {
        var candidates = new List<(int Score, GlobalSystemMediaTransportControlsSession Session)>();
        foreach (var session in manager.GetSessions())
        {
            var media = await TryGetMediaPropertiesAsync(session);
            if (media is null || string.IsNullOrWhiteSpace(media.Title))
            {
                continue;
            }

            var playbackInfo = session.GetPlaybackInfo();
            var source = session.SourceAppUserModelId ?? string.Empty;
            var score = 0;
            if (NeteaseKeywords.Any(keyword => source.Contains(keyword, StringComparison.OrdinalIgnoreCase)))
            {
                score += 100;
            }

            if (playbackInfo.PlaybackStatus == GlobalSystemMediaTransportControlsSessionPlaybackStatus.Playing)
            {
                score += 30;
            }

            score += Math.Min(media.Title.Length, 24);
            candidates.Add((score, session));
        }

        if (candidates.Count == 0)
        {
            return null;
        }

        var neteaseCandidates = candidates.Where(item =>
            NeteaseKeywords.Any(keyword => (item.Session.SourceAppUserModelId ?? string.Empty).Contains(keyword, StringComparison.OrdinalIgnoreCase))
        ).ToList();

        if (neteaseCandidates.Count > 0)
        {
            return neteaseCandidates.OrderByDescending(item => item.Score).First().Session;
        }

        return candidates.Count == 1
            ? candidates[0].Session
            : candidates.OrderByDescending(item => item.Score).First().Session;
    }

    private static async Task<MediaSessionSnapshot?> TryBuildSnapshotAsync(GlobalSystemMediaTransportControlsSession session)
    {
        var media = await TryGetMediaPropertiesAsync(session);
        if (media is null || string.IsNullOrWhiteSpace(media.Title))
        {
            return null;
        }

        var playbackInfo = session.GetPlaybackInfo();
        var playbackControls = playbackInfo.Controls;
        var timeline = session.GetTimelineProperties();

        return new MediaSessionSnapshot(
            SourceAppUserModelId: session.SourceAppUserModelId ?? string.Empty,
            Title: media.Title ?? string.Empty,
            Artist: media.Artist ?? string.Empty,
            AlbumTitle: media.AlbumTitle ?? string.Empty,
            PositionMs: (long)Math.Round(timeline.Position.TotalMilliseconds),
            DurationMs: (long)Math.Round(timeline.EndTime.TotalMilliseconds),
            StartTimeMs: (long)Math.Round(timeline.StartTime.TotalMilliseconds),
            MinSeekTimeMs: (long)Math.Round(timeline.MinSeekTime.TotalMilliseconds),
            MaxSeekTimeMs: (long)Math.Round(timeline.MaxSeekTime.TotalMilliseconds),
            PlaybackStatus: playbackInfo.PlaybackStatus.ToString(),
            CanPause: playbackControls.IsPauseEnabled,
            CanPlay: playbackControls.IsPlayEnabled,
            CanGoNext: playbackControls.IsNextEnabled,
            CanGoPrevious: playbackControls.IsPreviousEnabled,
            CanSeek: playbackControls.IsPlaybackPositionEnabled,
            CanTogglePlayPause: playbackControls.IsPlayPauseToggleEnabled,
            FetchedAtUtc: DateTimeOffset.UtcNow
        );
    }

    private static async Task<GlobalSystemMediaTransportControlsSessionMediaProperties?> TryGetMediaPropertiesAsync(GlobalSystemMediaTransportControlsSession session)
    {
        try
        {
            return await session.TryGetMediaPropertiesAsync();
        }
        catch
        {
            return null;
        }
    }
}

internal sealed record MediaSessionSnapshot(
    string SourceAppUserModelId,
    string Title,
    string Artist,
    string AlbumTitle,
    long PositionMs,
    long DurationMs,
    long StartTimeMs,
    long MinSeekTimeMs,
    long MaxSeekTimeMs,
    string PlaybackStatus,
    bool CanPause,
    bool CanPlay,
    bool CanGoNext,
    bool CanGoPrevious,
    bool CanSeek,
    bool CanTogglePlayPause,
    DateTimeOffset FetchedAtUtc
);

internal sealed record StateEnvelope(MediaSessionSnapshot? Session)
{
    public string Type { get; } = "state";
}

internal sealed record ErrorEnvelope(string Scope, string Message)
{
    public string Type { get; } = "error";
}

internal sealed record ControlEnvelope(string Action, bool Ok, string Message)
{
    public string Type { get; } = "control";
}
