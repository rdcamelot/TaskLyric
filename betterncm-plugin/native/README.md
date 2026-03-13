# Native 灞傚疄鐜拌鏄?
杩欎釜鐩綍鏆傛椂鍙斁瀹炵幇璇存槑锛屼笉鐩存帴鏀句竴涓亣鐨?DLL銆?
鍘熷洜寰堢洿鎺ワ細

- BetterNCM 鐨?`native_plugin` 涓嶆槸鏅€?Win32 DLL 鍚嶅瓧瀵逛笂灏辫兘宸ヤ綔
- 濡傛灉鍦?`manifest.json` 閲屽０鏄庝竴涓繕娌″疄鐜板ソ鐨?DLL锛屾彃浠跺姞杞介樁娈靛氨鍙兘鐩存帴澶辫触

鎵€浠ュ綋鍓嶅仛娉曟槸锛?
- 鍏堟妸 JS 渚ф帴鍙ｃ€佹瓕璇嶅悓姝ュ拰閰嶇疆闈㈡澘璺戦€?- native DLL 鐪熸鍐欏ソ鍚庯紝鍐嶆妸 `manifest.json` 澧炲姞 `native_plugin`

## 寤鸿鐨?native 鐩綍缁撴瀯

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

## 寤鸿鐨勫疄鐜板垎灞?
### `plugin_entry.cpp`

- BetterNCM native 鎻掍欢鍏ュ彛
- 鎺ユ敹 `tasklyric.config`
- 鎺ユ敹 `tasklyric.update`
- 杞彂鍒板崟渚嬬獥鍙ｆ帶鍒跺櫒

### `layout_probe.cpp`

- 鏌ユ壘 `Shell_TrayWnd`
- 鐢?UI Automation 璇嗗埆寮€濮嬫寜閽€佷换鍔″垪琛ㄣ€佺郴缁熸墭鐩樼瓑鍖哄煙
- 璁＄畻姝岃瘝鍖哄煙

### `taskbar_window.cpp`

- 鍒涘缓 `WS_CHILD | WS_VISIBLE` 瀛愮獥鍙?- 鎸傚埌浠诲姟鏍忕獥鍙?- 澶勭悊绐楀彛鐢熷懡鍛ㄦ湡鍜岄噸甯冨眬

### `text_renderer.cpp`

- Direct2D / DirectWrite 娓叉煋鍙岃姝岃瘝
- 瀛椾綋銆侀槾褰便€佸榻愩€侀鑹茬瓑鏍峰紡鎺у埗

## 鎶?native 鎺ヤ笂鍚庣殑 manifest 绀轰緥

绛?DLL 鐪熷啓濂戒箣鍚庯紝鍐嶆妸 `manifest.json` 鏀规垚锛?
```json
{
  "native_plugin": "native/tasklyric_native.dll"
}
```

瀛楁鍚堝苟鍒扮幇鏈?manifest 鍗冲彲銆?
