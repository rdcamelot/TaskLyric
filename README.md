# TaskLyric

[中文](README.md) | [English](README.en.md)

TaskLyric 是一个面向 Windows 的网易云音乐任务栏歌词工具。

它的目标不是做一个普通悬浮窗，而是把同步歌词渲染到 Windows 任务栏区域里，并尽量保持接近原生任务栏组件的使用体验。

## 当前状态

项目仍在开发中，但基础功能已经可用：

- 支持 Windows 任务栏歌词渲染
- 支持主歌词和翻译歌词
- 支持网易云音乐真实播放进度同步
- 支持暂停、继续、上一首、下一首控制
- 支持任务栏布局变化后的自动重排
- 支持通过任务栏网易云图标启动带 remote-debug 的网易云
- 支持通过启动项后台跟随网易云启动和关闭

仍未完成或仍需继续打磨：

- 正式安装器和自动更新流程
- 完整设置界面
- 对网易云后续版本更新的长期兼容性
- 更稳定的原生注入方案

## 为什么可能“没有更新到最新版本”

TaskLyric 目前不是传统意义上的“安装到系统目录”的软件。安装脚本主要创建或修改 Windows 快捷方式，让它们指向当前仓库里的启动器和代码。

因此：

- 如果你已经拉取了最新代码，但后台旧的 `pythonw.exe` 还在运行，需要先停止再重新启动。
- 启动项 watcher 默认指向 `pythonw.exe launcher.pyw`，不依赖 `build\launcher\tasklyric_launcher.exe`，所以清理 build 目录后仍然能随 Windows 登录启动。
- 如果你重新构建了 native host，需要确认 `build\host\tasklyric_host.dll` 存在，否则 TaskLyric 主进程会启动失败。
- 如果网易云更新后又出现状态不同步，优先重新执行“安装 / 修复快捷方式”命令，让任务栏网易云重新带 `--remote-debugging-port=9222` 启动。

手动停止当前 TaskLyric：

```powershell
python launcher.pyw --stop
```

## 环境要求

- Windows 11 优先
- 网易云音乐 PC 版
- Python 3.10+
- CMake
- MinGW Makefiles 或兼容的 Windows C++ 构建环境
- .NET SDK，用于构建 Windows media-session helper

## 构建

构建 native host 和 launcher：

```powershell
cmake -S . -B build -G "MinGW Makefiles"
cmake --build build
```

如果使用 MSYS2 / MinGW，构建前建议确保 UCRT 工具链在 `PATH` 中：

```powershell
$env:PATH = "D:\msys64\ucrt64\bin;$env:PATH"
```

构建 Windows media-session helper：

```powershell
dotnet build tools\TaskLyric.MediaSessionHelper\TaskLyric.MediaSessionHelper.csproj
```

冒烟测试 host DLL：

```powershell
python scripts\smoke_test_host.py
```

## 推荐安装方式

推荐同时安装后台 watcher 和任务栏网易云快捷方式修复：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_tasklyric_shortcut.ps1 -Startup -TaskbarPinned
```

这条命令会做两件事：

- 创建 `TaskLyric Background.lnk` 到 Windows 启动项，登录后后台常驻，网易云打开时自动启动 TaskLyric。
- 修改已固定到任务栏的网易云音乐快捷方式，让你点击原来的网易云图标时，以 `--remote-debugging-port=9222` 启动网易云。

启动项会在下次 Windows 登录后自动生效。如果你想在当前会话立即启动后台 watcher，可以额外运行：

```powershell
pythonw launcher.pyw --remote-debug-port 9222
```

默认安装不会强制重启已经打开的网易云。如果你明确希望 watcher 自动把“未带 remote-debug 参数”的网易云重启为正确模式，可以额外加 `-RestartCloudMusicWithDebug`。

注意：`-TaskbarPinned` 不会单独启动 TaskLyric，它只修复任务栏网易云的启动参数。想实现“点击任务栏网易云后自动有任务栏歌词”，需要配合 `-Startup` 的后台 watcher。

如果脚本提示找不到已固定的网易云任务栏快捷方式，请先把网易云音乐固定到任务栏，再重新执行上面的安装命令。

## 重新安装 / 修复

如果更新代码、网易云升级、或清理过 build 目录后 TaskLyric 没有自动启动，按下面流程修复：

```powershell
python launcher.pyw --stop
$env:PATH = "D:\msys64\ucrt64\bin;$env:PATH"
cmake -S . -B build -G "MinGW Makefiles"
cmake --build build --target tasklyric_host
powershell -ExecutionPolicy Bypass -File scripts\install_tasklyric_shortcut.ps1 -Startup -TaskbarPinned
pythonw launcher.pyw --remote-debug-port 9222
```

如果当前网易云不是以 remote-debug 模式启动，再执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\launch_cloudmusic_with_debug.ps1 -Port 9222 -RestartExisting
```

## 可选安装方式

只安装后台 watcher：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_tasklyric_shortcut.ps1 -Startup
```

创建桌面启动器：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_tasklyric_shortcut.ps1 -Desktop
```

只修复任务栏网易云快捷方式：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_tasklyric_shortcut.ps1 -TaskbarPinned
```

手动以 remote-debug 模式启动网易云并运行 TaskLyric：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\launch_cloudmusic_with_debug.ps1 -Port 9222 -RestartExisting
python main.py --remote-debug-port 9222
```

## 卸载和恢复

完整卸载 TaskLyric 集成：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_tasklyric.ps1
```

这会停止 TaskLyric，删除启动项 watcher，删除可选桌面快捷方式，并恢复被 TaskLyric 修改过的任务栏网易云快捷方式。

如果只想恢复任务栏网易云快捷方式：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restore_taskbar_shortcuts.ps1
```

如果还想清理日志和状态文件：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_tasklyric.ps1 -RemoveLogs
```

## 开发运行

直接运行 live bridge：

```powershell
python main.py
```

常用参数：

```powershell
python main.py --no-translation
python main.py --poll-interval 1.0 --tick-ms 120
python main.py --remote-debug-port 9222
python main.py --remote-debug-port 0
```

运行本地回放流程：

```powershell
python scripts\run_runtime_dev.py
```

保留 native 窗口以便观察：

```powershell
python scripts\run_runtime_dev.py --step-delay-ms 500 --hold-seconds 8
```

打包本地产物：

```powershell
powershell -ExecutionPolicy Bypass -File installer\package_tasklyric.ps1
```

## 工作原理

当前连接链路按优先级如下：

1. 如果网易云以 `--remote-debugging-port` 启动，TaskLyric 会连接网易云 Chromium 页面，订阅 `audioplayer.onLoad`、`audioplayer.onPlayProgress`、`audioplayer.onPlayState` 和 `audioplayer.onSeek`。
2. 如果 remote-debug 不可用，则尝试通过 `tools/TaskLyric.MediaSessionHelper` 读取 Windows media session。
3. 如果 helper 不可用，则尝试 PowerShell SMTC 探测。
4. 如果仍无法获取媒体会话，则退回到网易云窗口和本地信息的兜底方案。
5. 获取当前歌曲 ID 后，通过网易云公开接口获取 LRC 和翻译歌词。
6. Python live bridge 将当前歌词行推送到 `tasklyric_host.dll`。
7. native 层使用 DirectComposition / Direct2D / DirectWrite 在任务栏区域渲染歌词。

remote-debug 路径最关键，因为当前网易云桌面版的 Chromium renderer 可能禁用了部分系统媒体能力，SMTC 未必能提供稳定的播放进度和暂停状态。

## 仓库结构

- `host/`：host DLL 导出接口
- `native/`：任务栏窗口、布局探测、native bridge
- `launcher/`：native launcher wrapper
- `runtime/`：早期 runtime 和 fixture 回放逻辑
- `src/netease_taskbar_lyrics/`：当前 live bridge、网易云接入和 Python 启动逻辑
- `scripts/`：安装、卸载、调试和回放脚本
- `tools/`：辅助工具，包括 Windows media-session helper
- `installer/`：本地打包脚本
- `docs/`：架构和设计说明
- `betterncm-plugin/`：早期 BetterNCM 原型，仅作为参考保留

## 日志和诊断

常用诊断文件：

- `logs\tasklyric-host.log`
- `logs\tasklyric-launcher.log`
- `logs\tasklyric-window.log`
- `state\launcher-state.json`
- `state\last-event.json`
- `state\last-native-update.json`

如果网易云更新后出现不同步，优先检查：

- 网易云进程是否带有 `--remote-debugging-port=9222`
- `http://127.0.0.1:9222/json/list` 是否能访问
- `python scripts\verify_media_logic.py --live` 是否显示 `cloudMusicReporterProcessIds` 有值但 `cloudMusicProcessIds` 为空；这通常表示网易云主进程已退出或崩溃，只剩崩溃上报进程，TaskLyric 无法继续精确同步
- 是否存在旧的 `pythonw.exe` TaskLyric 进程
- 是否重新执行过推荐安装命令


快速验证媒体路由和播放状态逻辑：

```powershell
python scripts\verify_media_logic.py
```

查看当前网易云、remote-debug、SMTC 和 TaskLyric 实际选择的媒体源：

```powershell
python scripts\verify_media_logic.py --live
```

持续观察播放/暂停、锁屏恢复后的状态变化：

```powershell
python scripts\verify_media_logic.py --watch-seconds 60 --watch-interval 1
```

正常情况下，`selectedSession.sourceAppUserModelId` 应该是 `cloudmusic.remote-debug`，不应该变成 Chrome、Edge、Bilibili 或其它网页播放器来源。

## 免责声明

本项目仅供技术学习和研究交流使用。

数据来源于网络公开接口。本项目与网易云音乐及任何官方服务提供方无任何关联，也未获得其认可。使用者因使用本项目产生的一切后果由使用者自行承担。

本仓库不包含账号 Cookie、Token、密码或其他私密凭据，也不鼓励绕过官方限制。

## 许可证

本项目基于 [MIT License](LICENSE) 开源。
