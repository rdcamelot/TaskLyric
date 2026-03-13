# BetterNCM 浠诲姟鏍忔瓕璇嶉鏋?
杩欎釜鐩綍鏄綘鐪熸鐩爣瀵瑰簲鐨勮矾绾匡細BetterNCM 鎻掍欢璐熻矗璇荤綉鏄撲簯鍐呴儴鎾斁浜嬩欢锛宯ative DLL 璐熻矗鎶婃瓕璇嶅祵鍒?Windows 浠诲姟鏍忛噷銆?
褰撳墠鐘舵€侊細

- `manifest.json` 宸茬粡鏄彲瀹夎鐨?BetterNCM 鎻掍欢楠ㄦ灦
- `main.js` 宸茬粡鎺ヤ笂鎾斁浜嬩欢銆佹瓕璇嶈姹傘€丩RC 瑙ｆ瀽銆侀厤缃悓姝ュ拰 native bridge 璋冪敤
- native 渚ц繕娌℃湁钀芥垚鐪熸鐨勪换鍔℃爮瀛愮獥鍙ｅ疄鐜帮紝鎵€浠ュ綋鍓嶇洰褰曟槸鈥淛S 渚у畬鏁达紝native 渚у緟鎺モ€?
## 瀹夎鏂瑰紡

1. 鎵撳紑 BetterNCM 鐨勬彃浠跺紑鍙戠洰褰曪紝涓€鑸槸 `plugins_dev`
2. 鎶婃暣涓?`betterncm-plugin` 鏂囦欢澶规斁杩涘幓
3. 閲嶅惎缃戞槗浜戦煶涔?/ BetterNCM
4. 鍦?BetterNCM 鎻掍欢鍒楄〃閲屽惎鐢ㄨ繖涓彃浠?
## 鐜板湪宸茬粡鍋氬ソ鐨勪簨

鎻掍欢浼氱洃鍚細

- `audioplayer.onLoad`
- `audioplayer.onPlayProgress`
- `audioplayer.onPlayState`

骞朵笖浼氾細

- 鎷垮埌褰撳墠姝屾洸 ID
- 璇锋眰姝屾洸璇︽儏
- 璇锋眰鍘熸枃姝岃瘝鍜岀炕璇戞瓕璇?- 瑙ｆ瀽 LRC
- 鏍规嵁鎾斁杩涘害鎵惧嚭褰撳墠姝岃瘝琛?- 閫氳繃 native bridge 璋冪敤 `tasklyric.config` 鍜?`tasklyric.update`

## native bridge 绾﹀畾

JS 灞備細璋冪敤杩欎袱涓柟娉曪細

### `tasklyric.config`

鍙傛暟鏄?JSON 瀛楃涓诧紝瀛楁鍖呮嫭锛?
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

鍙傛暟鏄?JSON 瀛楃涓诧紝瀛楁鍖呮嫭锛?
```json
{
  "trackId": 123456,
  "title": "Song Name",
  "artist": "Artist",
  "mainText": "褰撳墠涓绘瓕璇?,
  "subText": "褰撳墠缈昏瘧姝岃瘝鎴栨瓕鎵嬪悕",
  "progressMs": 12345,
  "playbackState": "playing"
}
```

## 涓嬩竴姝ユ渶鍏抽敭鐨?native 瀹炵幇

浣犺鐨勨€滅湡姝ｅ祵鍏ヤ换鍔℃爮鈥濆繀椤诲湪 native 灞傚畬鎴愩€傛帹鑽愮洿鎺ユ寜杩欐潯璺疄鐜帮細

1. DLL 琚?BetterNCM 鍔犺浇
2. 鍦?DLL 閲屾壘鍒?`Shell_TrayWnd`
3. 鐢?`CreateWindowEx` 鍒涘缓浠诲姟鏍忓瓙绐楀彛
4. 閫氳繃 UI Automation 璇嗗埆寮€濮嬫寜閽€佷换鍔″垪琛ㄣ€佺郴缁熸墭鐩橈紝姹傚嚭涓棿鍙敤鍖哄煙
5. 鐢?Direct2D / DirectWrite 缁樺埗鍙岃姝岃瘝
6. 鍝嶅簲 `tasklyric.config` 鍜?`tasklyric.update`锛屾洿鏂扮粯鍒跺唴瀹?
## 璇存槑

椤跺眰鐩綍鐜版湁閭ｅ Python 瀹炵幇鏄箣鍓嶇殑鐙珛瑕嗙洊绐楀師鍨嬶紱濡傛灉浣犵殑鐩爣宸茬粡纭畾涓?BetterNCM 鍘熺敓璺嚎锛屽彲浠ュ彧鍏虫敞杩欎釜鐩綍銆?
