# TaskLyric

TaskLyric is a Windows taskbar lyrics project for NetEase Cloud Music PC.

The goal is to render synchronized lyrics into the taskbar area in a native way, instead of using a floating overlay window.

## Status

This project is in active development.

What is already available:

- a buildable host DLL skeleton
- a native bridge for `tasklyric.config` and `tasklyric.update`
- a first-pass native taskbar window attached to `Shell_TrayWnd`
- GDI-based lyric rendering for the current main and secondary lyric lines
- a runtime script for lyric parsing and lyric state updates
- local development fixtures and end-to-end replay scripts
- packaging scripts for local development builds

What is not finished yet:

- NetEase Cloud Music injection and event hooking
- in-host JavaScript runtime integration
- taskbar layout probing via UI Automation
- Direct2D / DirectWrite rendering
- production-grade installer and automatic update flow

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

## Development Notes

The current development replay flow does two things:

1. Runs `runtime/tasklyric.runtime.js` against local fixture events and fixture API responses.
2. Replays the produced transcript into `tasklyric_host.dll` through `ctypes`.

The native window currently uses a simple taskbar child window plus Win32/GDI drawing. This is enough to validate the host-to-native update path before moving on to more fragile work such as NetEase injection, UI Automation-based layout probing, and Direct2D / DirectWrite rendering.

Useful generated files:

- `state/runtime-dev-transcript.json`
- `state/last-event.json`
- `state/last-native-update.json`
- `logs/tasklyric-host.log`

A successful replay should also report a native window snapshot similar to:

- `hostState.nativeBridge.window.running = true`
- `hostState.nativeBridge.window.attached = true`
- `hostState.nativeBridge.window.hasHwnd = true`

## Repository Layout

- `host/`: host DLL code and exported API
- `native/`: native taskbar bridge layer and taskbar window implementation
- `runtime/`: runtime logic for lyric state and synchronization
- `fixtures/`: local fixture data for development replay
- `scripts/`: smoke tests, replay scripts, and helpers
- `installer/`: local packaging scripts
- `docs/`: design and architecture notes
- `betterncm-plugin/`: earlier BetterNCM-based prototype kept for reference
- `src/netease_taskbar_lyrics/`: earlier standalone overlay prototype kept for reference

## Architecture

Design decisions and the rationale for the current self-hosted direction are documented in [docs/architecture.md](docs/architecture.md).

## Disclaimer

This project is for technical research and learning purposes only.

Data is obtained from publicly accessible network interfaces. This project is not affiliated with or endorsed by any official service provider. Any consequences arising from use of this project are the sole responsibility of the user.

This repository does not include account credentials, cookies, or tokens, and it does not encourage bypassing official restrictions.

## License

This project is licensed under the [MIT License](LICENSE).
