# TaskLyric

`TaskLyric` 是一个面向网易云音乐 PC 端的任务栏歌词项目，目标是把歌词真正嵌入 Windows 任务栏，而不是用透明悬浮窗覆盖。

## 为什么不再直接依赖 BetterNCM / chromatic

当前决定改成 `TaskLyric` 自带宿主，而不是要求用户额外安装 BetterNCM 或 chromatic。原因是：

- `TaskLyric` 的最终目标不是“做一个插件”，而是“交付一个可直接使用的网易云任务栏歌词产品”
- 如果继续依赖外部宿主，用户安装链路会变长，问题定位也会更分散
- 你需要的核心能力其实很集中：播放事件、配置存取、native bridge、任务栏绘制
- 为了这几个能力去引入整个通用插件框架，依赖面偏大，也不利于后续只针对网易云做兼容

所以当前路线是：

- 借鉴 BetterNCM / chromatic 过去的注入思路和事件模型
- 借鉴 `Taskbar-Lyrics` 的任务栏歌词渲染思路
- 但由 `TaskLyric` 自己提供最小宿主，只服务这个项目本身

## 当前仓库结构

- `host/`
  自带宿主 DLL。负责初始化、事件接入、配置文件落盘、native bridge 调用和状态导出。

- `native/`
  任务栏原生层。目前先实现了一个可编译的 bridge 骨架，用来接收 `tasklyric.config` 和 `tasklyric.update`。

- `runtime/`
  未来由宿主加载的 JS 运行时代码。这里放歌词同步、LRC 解析、配置更新等逻辑，不再假设 BetterNCM 存在。

- `installer/`
  目前只做打包，不直接写入网易云安装目录。

- `betterncm-plugin/`
  早期的 BetterNCM 方向原型，保留作参考，不再是主路线。

- `main.py` 和 `src/netease_taskbar_lyrics/`
  更早期的独立覆盖窗原型，也只保留作参考。

## 当前实现状态

已经落下来的部分：

- `host` DLL 可编译骨架
- `host` 导出接口：
  `tasklyric_initialize`
  `tasklyric_shutdown`
  `tasklyric_emit_event`
  `tasklyric_call_native`
  `tasklyric_get_state_json`
  `tasklyric_get_runtime_script_path`
- `native` bridge 骨架，可接收 `tasklyric.config` / `tasklyric.update`
- 通用 `runtime/tasklyric.runtime.js`
- 打包脚本 `installer/package_tasklyric.ps1`
- 本地验证脚本 `scripts/smoke_test_host.py`

还没完成的关键部分：

- 注入网易云并挂接事件
- 真正的 JS 引擎承载
- 任务栏子窗口挂接到 `Shell_TrayWnd`
- UI Automation 定位任务栏可用区域
- Direct2D / DirectWrite 渲染歌词

## 现在怎么测试

当前可以测试的是“宿主骨架能否构建、导出是否存在、打包链路是否正常”，还不能测试最终的任务栏歌词效果。

### 构建

```powershell
cmake -S . -B build -G "MinGW Makefiles"
cmake --build build
```

### 本地 Smoke Test

```powershell
python scripts\smoke_test_host.py
```

这个脚本会加载 `tasklyric_host.dll`，调用初始化和两个 bridge 方法，再把当前状态 JSON 打印出来。

### 打包

```powershell
powershell -ExecutionPolicy Bypass -File installer\package_tasklyric.ps1
```

### 现阶段测试重点

- `build/host/tasklyric_host.dll` 能否生成
- `tasklyric_get_state_json` 是否能返回初始化状态
- `runtime/tasklyric.runtime.js` 是否可被后续宿主加载
- 打包结果是否落到 `dist/TaskLyric/`

## 下一步

后续实现顺序会按这个方向推进：

1. 给 `host` 增加最小事件总线和运行时装载入口
2. 实现网易云注入 / 挂钩链路
3. 把 `runtime` 真正跑起来
4. 实现原生任务栏窗口与文本渲染
