# TaskLyric

[中文](README.md) | [English](README.en.md)

TaskLyric is a Windows taskbar lyrics tool for NetEase Cloud Music PC.

The goal is to render synchronized lyrics into the Windows taskbar area instead of using a normal floating overlay window.

## Status

This project is still in development, but the core flow is usable:

- Windows taskbar lyric rendering
- Main lyric and translated lyric display
- Real NetEase Cloud Music playback progress synchronization
- Previous, play or pause, and next controls
- Dynamic taskbar layout probing and repositioning
- Remote-debug-enabled NetEase Cloud Music taskbar shortcut
- Startup watcher that follows NetEase Cloud Music startup and shutdown

Still unfinished:

- Production installer and update flow
- Full settings UI
- Long-term compatibility with future NetEase Cloud Music updates
- A more stable native in-process integration

## Why It May Not Be Running The Latest Code

TaskLyric is not currently installed into a system-wide application directory. The install scripts mainly create or modify Windows shortcuts that point back to this repository.

That means:

- If you pulled newer code while an old `pythonw.exe` instance is still running, stop and restart TaskLyric.
- If you rebuilt the native components, make sure the shortcuts point to the current `build\launcher\tasklyric_launcher.exe` or an equivalent fresh artifact.
- If NetEase Cloud Music was updated and sync breaks again, rerun the install command so the pinned taskbar shortcut starts Cloud Music with `--remote-debugging-port=9222`.

Stop the current TaskLyric instance manually:

```powershell
python launcher.pyw --stop
```

## Requirements

- Windows 11 preferred
- NetEase Cloud Music PC
- Python 3.10+
- CMake
- MinGW Makefiles or a compatible Windows C++ toolchain
- .NET SDK for the Windows media-session helper

## Build

Build the native host and launcher:

```powershell
cmake -S . -B build -G "MinGW Makefiles"
cmake --build build
```

Build the Windows media-session helper:

```powershell
dotnet build tools\TaskLyric.MediaSessionHelper\TaskLyric.MediaSessionHelper.csproj
```

Smoke test the host DLL:

```powershell
python scripts\smoke_test_host.py
```

## Recommended Install

Install both the background watcher and the pinned NetEase taskbar shortcut fix:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_tasklyric_shortcut.ps1 -Startup -TaskbarPinned
```

This does two things:

- Creates `TaskLyric Background.lnk` in the Windows Startup folder. It keeps a lightweight watcher running and starts TaskLyric when NetEase Cloud Music starts.
- Updates the pinned NetEase Cloud Music taskbar shortcut so clicking the original taskbar icon starts Cloud Music with `--remote-debugging-port=9222`.

The default install does not force-restart an already running NetEase process. If you explicitly want the watcher to restart a NetEase process that was launched without the remote-debug argument, add `-RestartCloudMusicWithDebug`.

Note: `-TaskbarPinned` alone does not start TaskLyric. It only fixes the pinned NetEase shortcut arguments. To make TaskLyric follow the taskbar NetEase icon, use it together with `-Startup`.

If no pinned NetEase taskbar shortcut is found, pin NetEase Cloud Music to the taskbar first, then rerun the install command.

## Optional Install

Install only the background watcher:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_tasklyric_shortcut.ps1 -Startup
```

Create a desktop launcher:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_tasklyric_shortcut.ps1 -Desktop
```

Only fix the pinned NetEase taskbar shortcut:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_tasklyric_shortcut.ps1 -TaskbarPinned
```

Manual remote-debug launch:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\launch_cloudmusic_with_debug.ps1 -Port 9222 -RestartExisting
python main.py --remote-debug-port 9222
```

## Uninstall And Restore

Uninstall the TaskLyric integration:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_tasklyric.ps1
```

This stops TaskLyric, removes the Startup watcher shortcut, removes the optional desktop shortcut, and restores any pinned NetEase taskbar shortcut modified by TaskLyric.

Restore only the pinned taskbar shortcut:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restore_taskbar_shortcuts.ps1
```

Remove logs and state files as well:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_tasklyric.ps1 -RemoveLogs
```

## Development

Run the live bridge:

```powershell
python main.py
```

Common flags:

```powershell
python main.py --no-translation
python main.py --poll-interval 1.0 --tick-ms 120
python main.py --remote-debug-port 9222
python main.py --remote-debug-port 0
```

Run the local replay flow:

```powershell
python scripts\run_runtime_dev.py
```

Keep the native window visible for inspection:

```powershell
python scripts\run_runtime_dev.py --step-delay-ms 500 --hold-seconds 8
```

Package local artifacts:

```powershell
powershell -ExecutionPolicy Bypass -File installer\package_tasklyric.ps1
```

## How It Works

The current connection path is:

1. If NetEase Cloud Music is started with `--remote-debugging-port`, TaskLyric attaches to its Chromium page and subscribes to `audioplayer.onLoad`, `audioplayer.onPlayProgress`, `audioplayer.onPlayState`, and `audioplayer.onSeek`.
2. If remote-debug is unavailable, it tries `tools/TaskLyric.MediaSessionHelper` for Windows media-session data.
3. If that helper is unavailable, it tries the PowerShell SMTC probe.
4. If no usable media session exists, it falls back to NetEase window metadata and local state.
5. It resolves the current song and fetches LRC plus translated lyrics from public NetEase interfaces.
6. The Python live bridge pushes the current lyric line to `tasklyric_host.dll`.
7. The native layer renders lyrics into the taskbar area with DirectComposition, Direct2D, and DirectWrite.

The remote-debug path matters because current NetEase desktop builds may disable parts of the system media-session stack, so SMTC may not provide reliable progress and pause state.

## Repository Layout

- `host/`: host DLL exported API
- `native/`: taskbar window, layout probing, and native bridge
- `launcher/`: native launcher wrapper
- `runtime/`: earlier runtime and fixture replay logic
- `src/netease_taskbar_lyrics/`: current live bridge, NetEase integration, and Python launcher logic
- `scripts/`: install, uninstall, debug, and replay scripts
- `tools/`: helper tools, including the Windows media-session helper
- `installer/`: local packaging scripts
- `docs/`: architecture and design notes
- `betterncm-plugin/`: earlier BetterNCM prototype kept for reference

## Diagnostics

Useful files:

- `logs\tasklyric-host.log`
- `logs\tasklyric-launcher.log`
- `logs\tasklyric-window.log`
- `state\last-event.json`
- `state\last-native-update.json`

If sync breaks after a NetEase update, check:

- Whether `cloudmusic.exe` was started with `--remote-debugging-port=9222`
- Whether `http://127.0.0.1:9222/json/list` is reachable
- Whether an old TaskLyric `pythonw.exe` process is still running
- Whether the recommended install command has been rerun


Verify media routing and playback-state logic:

```powershell
python scripts\verify_media_logic.py
```

Inspect the current NetEase, remote-debug, SMTC, and selected TaskLyric media source:

```powershell
python scripts\verify_media_logic.py --live
```

Watch play/pause or lock-screen recovery state changes continuously:

```powershell
python scripts\verify_media_logic.py --watch-seconds 60 --watch-interval 1
```

Normally, `selectedSession.sourceAppUserModelId` should be `cloudmusic.remote-debug`, not Chrome, Edge, Bilibili, or another browser media source.

## Disclaimer

This project is for technical research and learning purposes only.

Data is obtained from publicly accessible network interfaces. This project is not affiliated with or endorsed by NetEase Cloud Music or any official service provider. Any consequences arising from use of this project are the sole responsibility of the user.

This repository does not include account cookies, tokens, passwords, or other private credentials, and it does not encourage bypassing official restrictions.

## License

This project is licensed under the [MIT License](LICENSE).
