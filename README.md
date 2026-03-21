# TaskLyric

TaskLyric is a Windows taskbar lyrics project for NetEase Cloud Music PC.

The goal is to render synchronized lyrics into the taskbar area in a native way, instead of using a floating overlay window.

## Status

This project is in active development.

What is already available:

- a buildable host DLL skeleton
- a native bridge for `tasklyric.config` and `tasklyric.update`
- a native taskbar window attached to `Shell_TrayWnd`
- DirectComposition / Direct2D / DirectWrite based rendering
- Win11 taskbar layout probing via UI Automation
- a live bridge that follows real NetEase playback through a Chromium remote-debug bridge first, then a .NET SMTC helper, then PowerShell SMTC, with a cloudmusic.exe window fallback when media sessions are unavailable
- native taskbar transport controls for previous, play or pause, and next
- lyric lookup through NetEase public interfaces with main lyric and translated lyric support
- local development fixtures and replay scripts
- packaging scripts for local development builds

What is not finished yet:

- in-process NetEase Cloud Music injection
- direct hooking of NetEase client events and the desktop-lyrics toggle button
- a production-grade installer and automatic update flow
- a full settings UI for themes and typography

## Quick Start

Build the native host:

```powershell
cmake -S . -B build -G "MinGW Makefiles"
cmake --build build
```

The build now also produces a native launcher stub `tasklyric_launcher.exe`, which starts the background launcher without a console window. In a clean build directory used in this repo, the executable is usually generated at `build-tasklyric\launcher\tasklyric_launcher.exe`.

Build the Windows media-session helper:

```powershell
dotnet build tools\TaskLyric.MediaSessionHelper\TaskLyric.MediaSessionHelper.csproj
```

Smoke test the host DLL:

```powershell
python scripts\smoke_test_host.py
```

Run the live bridge for real NetEase playback:

```powershell
python main.py
```

Optional live-bridge flags:

```powershell
python main.py --no-translation
python main.py --poll-interval 1.0 --tick-ms 120
python main.py --remote-debug-port 9222
python main.py --remote-debug-port 0
```

For exact progress, pause, and seek synchronization on current NetEase desktop builds, start Cloud Music with a Chromium remote debugging port first:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\launch_cloudmusic_with_debug.ps1 -Port 9222 -RestartExisting
python main.py --remote-debug-port 9222
```

Run TaskLyric in the background without opening a terminal window:

```powershell
.\build-tasklyric\launcher\tasklyric_launcher.exe --remote-debug-port 9222
```

If PowerShell says `tasklyric_launcher.exe` is not recognized, use one of these forms instead:

```powershell
.\build-tasklyric\launcher\tasklyric_launcher.exe --remote-debug-port 9222 --restart-cloudmusic-with-debug
D:\code\TaskLyric\build-tasklyric\launcher\tasklyric_launcher.exe --remote-debug-port 9222 --restart-cloudmusic-with-debug
```

This safer default no longer restarts a manually opened Cloud Music instance. TaskLyric will start only after the remote-debug target is actually ready.

If you explicitly want TaskLyric to restart Cloud Music into debug mode for exact pause, seek, previous, and next synchronization, add:

```powershell
--restart-cloudmusic-with-debug
```

Stop only the TaskLyric child process but keep the background launcher watcher alive:

```powershell
python launcher.pyw --stop
```

If you really want to stop both the watcher and TaskLyric, use:

```powershell
python launcher.pyw --stop-all
```

After `--stop-all`, automatic startup is disabled until you launch the watcher again (or sign out and sign back in so the Startup shortcut runs again).

Launching `launcher.pyw` repeatedly is now safe: only one launcher instance will stay alive.

Create a product-style desktop launcher shortcut:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_tasklyric_shortcut.ps1 -Desktop -CleanupLegacyShortcuts
```

This creates `TaskLyric Launcher.lnk`. Double-clicking it starts the TaskLyric watcher without opening a terminal.

Current behavior: `TaskLyric Launcher.lnk` starts the TaskLyric watcher only. It does not force-launch Cloud Music unless you explicitly install it with `-LaunchCloudMusic`.

If you want one-click launch (Cloud Music + TaskLyric), recreate desktop shortcut with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_tasklyric_shortcut.ps1 -Desktop -LaunchCloudMusic -CleanupLegacyShortcuts
```

Install a Startup shortcut so TaskLyric watches Cloud Music automatically after you sign in:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_tasklyric_shortcut.ps1 -Startup -CleanupLegacyShortcuts
```

This creates `TaskLyric Background.lnk` in the Startup folder. It watches `cloudmusic.exe`, starts TaskLyric only when NetEase Cloud Music is running, and stops it after Cloud Music exits.

If you want your existing Cloud Music shortcuts (including pinned Taskbar shortcuts) to always start Cloud Music with a remote debug port, replace those shortcuts only:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_tasklyric_shortcut.ps1 -Desktop -ReplaceCloudMusicShortcut
```

This does not modify `cloudmusic.exe` itself. It rewrites matching `.lnk` shortcuts to launch `cloudmusic.exe --remote-debugging-port=9222`, and keeps backups with a `.tasklyric-backup` suffix. You can restore them with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restore_cloudmusic_shortcuts.ps1
```

The replacement now also includes your pinned Taskbar Cloud Music shortcut under your user profile. If some Start Menu shortcuts are under `C:\ProgramData`, replacing those may require running PowerShell as administrator.

Run the development end-to-end replay flow:

```powershell
python scripts\run_runtime_dev.py
```

Run the visual replay flow and keep the native window on screen for inspection:

```powershell
python scripts\run_runtime_dev.py --step-delay-ms 500 --hold-seconds 8
```

Package local artifacts:

```powershell
powershell -ExecutionPolicy Bypass -File installer\package_tasklyric.ps1
```

## Live Bridge Notes

The current real-world connection path is:

1. If NetEase Cloud Music is started with `--remote-debugging-port`, attach to its Chromium page and subscribe directly to `audioplayer.onLoad`, `audioplayer.onPlayProgress`, `audioplayer.onPlayState`, and `audioplayer.onSeek`.
2. If that path is not available, try reading the current Windows media session through `tools/TaskLyric.MediaSessionHelper`, which uses `Windows.Media.Control` for playback state, timeline, and media commands.
3. If that path does not surface a usable NetEase session, fall back to the older PowerShell SMTC probe.
4. If media sessions are still unavailable, fall back to cloudmusic.exe window metadata and the local NetEase playing list.
5. Resolve the current track through NetEase public interfaces when a direct song ID is not available.
6. Fetch LRC and translated lyrics.
7. Push the current lyric line into `tasklyric_host.dll`.
8. Taskbar buttons send previous, play or pause, and next commands back through the host bridge.

Why the remote-debug path matters: on the current NetEase desktop build used during development, the Chromium renderer starts with `--disable-features=...MediaSessionService,HardwareMediaKeyHandling...`, which means SMTC may not expose a usable playback timeline at all. The direct Chromium bridge avoids that limitation and gives line updates based on the same internal `audioplayer.*` events the client uses.

This means TaskLyric can already follow real NetEase playback without the old BetterNCM dependency, but it does not yet hook directly into the NetEase process itself.

## Development Notes

The development replay flow does two things:

1. Runs `runtime/tasklyric.runtime.js` against local fixture events and fixture API responses.
2. Replays the produced transcript into `tasklyric_host.dll` through `ctypes`.

Useful generated files:

- `state/runtime-dev-transcript.json`
- `state/last-event.json`
- `state/last-native-update.json`
- `logs/tasklyric-host.log`
- `logs/tasklyric-launcher.log`
- `state/launcher-state.json`

On this repo they are usually located at:

- `D:\code\TaskLyric\logs\tasklyric-launcher.log`
- `D:\code\TaskLyric\state\launcher-state.json`

A successful replay should report a native window snapshot similar to:

- `hostState.nativeBridge.window.running = true`
- `hostState.nativeBridge.window.attached = true`
- `hostState.nativeBridge.window.hasHwnd = true`

## Repository Layout

- `host/`: host DLL code and exported API
- `native/`: native taskbar bridge layer and taskbar window implementation
- `runtime/`: runtime logic for lyric parsing and synchronization
- `fixtures/`: local fixture data for development replay
- `scripts/`: smoke tests, replay scripts, and helpers
- `tools/`: auxiliary helper projects, including the Windows media-session bridge
- `installer/`: local packaging scripts
- `docs/`: design and architecture notes
- `betterncm-plugin/`: earlier BetterNCM-based prototype kept for reference
- `src/netease_taskbar_lyrics/`: current live bridge and legacy standalone prototype modules

## Architecture

Design decisions and the rationale for the current self-hosted direction are documented in [docs/architecture.md](docs/architecture.md).

## Disclaimer

This project is for technical research and learning purposes only.

Data is obtained from publicly accessible network interfaces. This project is not affiliated with or endorsed by any official service provider. Any consequences arising from use of this project are the sole responsibility of the user.

This repository does not include account credentials, cookies, or tokens, and it does not encourage bypassing official restrictions.

## License

This project is licensed under the [MIT License](LICENSE).


