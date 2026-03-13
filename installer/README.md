# Installer Notes

当前 `installer/` 目录先只负责打包，不直接向网易云音乐安装。

原因：

- 自带宿主的注入链路还没实现完
- 现在直接写安装器，只会把“如何复制文件”提前固化，反而不利于后续调整

当前可用脚本：

- `package_tasklyric.ps1`

它会把已构建的 `tasklyric_host.dll` 和 `runtime/tasklyric.runtime.js` 打包到 `dist/TaskLyric/`。
