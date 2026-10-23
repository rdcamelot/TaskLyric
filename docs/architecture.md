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

## SMTC as a future generic media layer

Windows SMTC is useful beyond NetEase Cloud Music because it exposes the active system media session for browsers and many players. TaskLyric should keep that capability behind an explicit generic-media mode instead of using it as an unconditional NetEase control fallback.

The reason is routing: global SMTC/media-key commands go to Windows' current active media session. If a browser video is active, a fallback play/pause/next command can control the browser instead of NetEase Cloud Music. The NetEase-specific path should prefer the remote-debug bridge and direct CloudMusic window commands; SMTC can later be extracted into a separate universal media widget if the project needs that broader behavior.

## Taskbar glass material

The Direct2D renderer uses a low-contrast translucent fill, one broad radial reflection,
a subdued directional rim, and a light contact shadow. Strong opposing highlights
and a second inner outline are deliberately avoided at taskbar scale. This borrows the edge definition and
restrained layering described in Apple's [Meet Liquid Glass](https://developer.apple.com/videos/play/wwdc2025/219/),
not its platform implementation. It does not capture, blur, or refract desktop
pixels; the existing taskbar composition remains the backdrop.

Material brushes are cached per device and theme, released on renderer teardown,
and repositioned when the surface dimensions change. There is no additional timer,
screen capture, or dependency. Text layout, marquee timing, control hit areas, and
taskbar attachment are independent of this treatment. Manual color mode retains
its transparent surface, and debug fill still bypasses the material.

A standalone preview exercises the production renderer without attaching to the
taskbar, reading music sessions, or writing the user's configuration:

```powershell
cmake -S . -B build-glass -G "MinGW Makefiles" -DTASKLYRIC_BUILD_MATERIAL_PREVIEW=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build-glass --target tasklyric_material_preview
.\build-glass\native\tasklyric_material_preview.exe
.\build-glass\native\tasklyric_material_preview.exe --smoke
```

The backgrounds and lyrics in the preview are synthetic. `--smoke` exits after
eight cycles covering renderer recreation, width changes, theme switches,
manual/debug modes, and playing/paused samples. It reports rendering failures
with a nonzero exit code; visual quality still requires inspecting the preview
and the actual taskbar.
