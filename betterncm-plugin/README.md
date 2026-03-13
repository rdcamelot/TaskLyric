# TaskLyric

这个目录是 `TaskLyric` 的 BetterNCM 插件骨架。

目标是：

- BetterNCM 负责接入网易云音乐内部播放事件
- native DLL 负责把歌词真正嵌入 Windows 任务栏

当前状态：

- `manifest.json` 已经是可安装的 BetterNCM 插件骨架
- `main.js` 已经完成播放事件监听、歌词请求、LRC 解析、配置同步和 native bridge 调用
- native 层还没有落成真正的任务栏子窗口实现

## 安装方式

1. 打开 BetterNCM 的插件开发目录，通常是 `plugins_dev`
2. 把整个 `betterncm-plugin` 文件夹放进去
3. 重启网易云音乐和 BetterNCM
4. 在 BetterNCM 插件列表中启用 `TaskLyric`

## 当前已实现

插件会监听：

- `audioplayer.onLoad`
- `audioplayer.onPlayProgress`
- `audioplayer.onPlayState`

并且会完成这些工作：

- 获取当前歌曲 ID
- 请求歌曲详情
- 请求原文歌词和翻译歌词
- 解析 LRC
- 根据播放进度计算当前歌词行
- 通过 native bridge 调用 `tasklyric.config` 和 `tasklyric.update`

## Native Bridge 约定

JS 层当前会调用两个 native 方法。

### `tasklyric.config`

参数是 JSON 字符串，字段示例：

```json
{
  "showTranslation": true,
  "fontFamily": "Microsoft YaHei UI",
  "fontSize": 16,
  "color": "#F5F7FA",
  "shadowColor": "#14161A",
  "align": "center"
}
```

### `tasklyric.update`

参数是 JSON 字符串，字段示例：

```json
{
  "trackId": 123456,
  "title": "Song Name",
  "artist": "Artist",
  "mainText": "当前主歌词",
  "subText": "当前翻译歌词或歌手名",
  "progressMs": 12345,
  "playbackState": "playing"
}
```

## 下一步

你要的“真正嵌入任务栏”必须在 native 层完成。建议按下面的分层实现：

1. DLL 被 BetterNCM 加载
2. 在 DLL 内找到 `Shell_TrayWnd`
3. 用 `CreateWindowEx` 创建任务栏子窗口
4. 用 UI Automation 识别开始按钮、任务列表、系统托盘等区域
5. 计算可用于歌词显示的任务栏区域
6. 用 Direct2D / DirectWrite 渲染双行歌词
7. 响应 `tasklyric.config` 和 `tasklyric.update`

## 说明

仓库顶层仍然保留了一套 Python 独立原型，但它只是早期验证版本。

如果你的目标已经确定为 BetterNCM 原生方案，可以优先只关注这个目录。
