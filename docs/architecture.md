# Architecture Notes

## Why TaskLyric is moving away from BetterNCM / chromatic as a runtime dependency

TaskLyric originally explored a BetterNCM-style plugin path because that route already proved two important things:

- NetEase Cloud Music playback events can be observed reliably from inside the client.
- A taskbar-native lyric renderer is a practical target.

However, the project is being positioned as a standalone open source product rather than a plugin that requires users to install and maintain a separate host framework.

The current self-hosted direction is based on these tradeoffs:

- The end goal is a directly usable taskbar lyrics tool, not a generic plugin.
- Requiring an external host increases installation complexity and splits debugging across multiple projects.
- TaskLyric only needs a relatively small runtime surface:
  playback events, config storage, a native bridge, and taskbar rendering.
- Owning that minimal runtime makes it easier to optimize specifically for NetEase Cloud Music and reduce unrelated dependency surface.

## Current architectural layers

- `host/`
  Owns initialization, state export, event intake, config persistence, and forwarding calls into the native layer.

- `runtime/`
  Owns lyric fetch logic, LRC parsing, playback progress handling, and lyric state transitions.

- `native/`
  Will own taskbar window attachment, taskbar layout probing, and text rendering.

## Development strategy

The implementation is being built in stages:

1. Build a stable host/native/runtime contract.
2. Validate runtime behavior locally with fixture-driven replay.
3. Add real client injection and event capture.
4. Replace the native bridge stub with actual taskbar rendering.

## Reference projects

The project still borrows ideas from earlier work:

- BetterNCM / chromatic for historical injection and event-model ideas
- Taskbar-Lyrics for taskbar-native lyric rendering direction

These references inform the design, but TaskLyric is being implemented as its own runtime and host stack.
