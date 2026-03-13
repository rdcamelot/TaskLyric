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
- a live bridge that follows real NetEase playback through SMTC first, with a cloudmusic.exe window fallback when SMTC is unavailable
- lyric lookup through NetEase public interfaces with main lyric and translated lyric support
- local development fixtures and replay scripts
- packaging scripts for local development builds

What is not finished yet:

- in-process NetEase Cloud Music injection
- direct hooking of NetEase client events and the desktop-lyrics toggle button
- a production-grade installer and automatic update flow
- a full settings UI for themes and typography

## Quick Start

Build:

```powershell
cmake -S . -B build -G "MinGW Makefiles"
cmake --build build
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
```

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

1. Try reading the current Windows media session via SMTC.
2. If SMTC is unavailable, fall back to cloudmusic.exe window metadata and the local NetEase playing list.
3. Prefer NetEase Cloud Music playback metadata.
4. Resolve the current track through NetEase public interfaces when a direct song ID is not available.
5. Fetch LRC and translated lyrics.
6. Push the current lyric line into `tasklyric_host.dll`.

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


