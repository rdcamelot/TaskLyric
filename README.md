# TaskLyric

`TaskLyric` 是一个面向网易云音乐 PC 端的任务栏歌词项目，目标是把歌词真正嵌入 Windows 任务栏，而不是用透明悬浮窗覆盖。

## 当前路线

当前仓库保留了两条路线：

- `betterncm-plugin/`
  这是主路线，也是最终目标。
  方案是通过 BetterNCM 监听网易云音乐内部播放事件，再由 native DLL 把歌词绘制到任务栏里。

- `main.py` 和 `src/netease_taskbar_lyrics/`
  这是之前做的独立原型。
  它的作用主要是验证歌词获取、歌词同步和基础显示逻辑，不是最终形态。

## 当前进度

BetterNCM 主线已经完成：

- 插件基础骨架
- 歌曲加载事件监听
- 播放进度监听
- 歌词和翻译歌词请求
- LRC 解析
- 配置项同步
- native bridge 接口约定

还未完成的部分：

- native DLL 真正实现
- 任务栏子窗口挂接
- UI Automation 定位任务栏可用区域
- Direct2D / DirectWrite 渲染歌词

## 目录说明

- `betterncm-plugin/manifest.json`
  BetterNCM 插件清单

- `betterncm-plugin/main.js`
  插件主逻辑，负责监听播放事件、拉歌词、解析 LRC、调用 native bridge

- `betterncm-plugin/native/README.md`
  native 层的实现规划

## 使用方式

如果你要继续走最终方案，优先看：

- `betterncm-plugin/README.md`
- `betterncm-plugin/main.js`

把 `betterncm-plugin` 整个目录放进 BetterNCM 的 `plugins_dev` 后，就可以开始在 BetterNCM 里调试 JS 侧逻辑。

等 native DLL 完成后，再把 `native_plugin` 字段补到 `manifest.json` 中。
