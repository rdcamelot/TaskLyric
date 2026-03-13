# Native Layer Plan

这个目录暂时只放 native 层实现规划，不直接放一个假的 DLL。

原因很简单：

- BetterNCM 的 `native_plugin` 需要真实可加载的实现
- 如果先在 `manifest.json` 里声明一个不存在或不可用的 DLL，插件加载阶段就可能失败

所以当前策略是：

- 先把 JS 侧歌词监听、歌词同步和配置面板稳定下来
- 再补 native DLL

## 建议目录结构

```text
native/
  CMakeLists.txt
  include/
    bridge.hpp
    taskbar_window.hpp
  src/
    bridge.cpp
    plugin_entry.cpp
    taskbar_window.cpp
    layout_probe.cpp
    text_renderer.cpp
```

## 建议分层

### `plugin_entry.cpp`

- BetterNCM native 插件入口
- 接收 `tasklyric.config`
- 接收 `tasklyric.update`
- 转发给窗口控制器

### `layout_probe.cpp`

- 查找 `Shell_TrayWnd`
- 用 UI Automation 识别开始按钮、任务列表、系统托盘等区域
- 计算歌词显示区域

### `taskbar_window.cpp`

- 创建 `WS_CHILD | WS_VISIBLE` 子窗口
- 把窗口挂到任务栏窗口上
- 处理重布局和生命周期

### `text_renderer.cpp`

- 用 Direct2D / DirectWrite 渲染双行歌词
- 处理字体、阴影、颜色、对齐等样式

## 后续 manifest 配置

等 DLL 真正写好之后，再把 `manifest.json` 增加类似字段：

```json
{
  "native_plugin": "native/tasklyric_native.dll"
}
```
