const DEFAULT_CONFIG = {
  showTranslation: true,
  fontFamily: "Microsoft YaHei UI",
  fontSize: 16,
  color: "#F5F7FA",
  shadowColor: "#14161A",
  align: "center",
};

const STORAGE_KEY = "tasklyric:config";
const LYRIC_ENDPOINT = "https://music.163.com/api/song/lyric/v1";
const DETAIL_ENDPOINT = "https://music.163.com/api/song/detail";
const LOADING_LYRIC_TEXT = "\u6b4c\u8bcd\u52a0\u8f7d\u4e2d";
const EMPTY_LYRIC_TEXT = "\u6682\u65e0\u6b4c\u8bcd";
const CONFIG_LABELS = {
  showTranslation: "\u663e\u793a\u7ffb\u8bd1\u6b4c\u8bcd",
  fontFamily: "\u5b57\u4f53",
  fontSize: "\u5b57\u53f7",
  color: "\u4e3b\u6587\u5b57\u989c\u8272",
  shadowColor: "\u9634\u5f71\u989c\u8272",
  align: "\u5bf9\u9f50",
  alignCenter: "\u5c45\u4e2d",
  alignLeft: "\u5c45\u5de6",
  alignRight: "\u5c45\u53f3",
};

const state = {
  config: loadConfig(),
  trackId: null,
  title: "",
  artist: "",
  mainTimeline: [],
  subTimeline: [],
  lastSentKey: "",
  lastProgressMs: 0,
  playbackState: "unknown",
};

function boot() {
  syncConfigToNative();
  registerPlayerHooks();
  console.log("[TaskLyric] loaded");
}

function registerPlayerHooks() {
  if (!globalThis.channel || typeof channel.registerCall !== "function") {
    console.warn("[TaskLyric] channel.registerCall is unavailable");
    return;
  }

  channel.registerCall("audioplayer.onLoad", async (...args) => {
    const payload = args[args.length - 1];
    await handleTrackLoad(payload);
  });

  channel.registerCall("audioplayer.onPlayProgress", (...args) => {
    const payload = args[args.length - 1];
    handleProgress(payload);
  });

  channel.registerCall("audioplayer.onPlayState", (...args) => {
    const payload = args[args.length - 1];
    handlePlayState(payload);
  });
}

async function handleTrackLoad(payload) {
  const trackId = extractTrackId(payload);
  if (!trackId) {
    console.warn("[TaskLyric] failed to extract track id", payload);
    return;
  }

  state.trackId = trackId;
  state.lastProgressMs = 0;
  state.lastSentKey = "";

  const [detail, lyricData] = await Promise.all([
    fetchSongDetail(trackId),
    fetchLyricData(trackId),
  ]);

  state.title = detail.title;
  state.artist = detail.artist;
  state.mainTimeline = parseLrc(lyricData.lrc?.lyric || "");
  state.subTimeline = parseLrc(lyricData.tlyric?.lyric || "");

  await callNative("tasklyric.update", {
    trackId: state.trackId,
    title: state.title,
    artist: state.artist,
    mainText: state.title || LOADING_LYRIC_TEXT,
    subText: state.artist,
    progressMs: 0,
    playbackState: state.playbackState,
  });
}

function handleProgress(payload) {
  const progressMs = extractProgressMs(payload);
  if (progressMs == null) {
    return;
  }

  state.lastProgressMs = progressMs;
  pushCurrentLyric();
}

function handlePlayState(payload) {
  const playbackState = extractPlaybackState(payload);
  if (!playbackState) {
    return;
  }

  state.playbackState = playbackState;
  pushCurrentLyric();
}

function pushCurrentLyric() {
  if (!state.trackId) {
    return;
  }

  const mainText = lineAt(state.mainTimeline, state.lastProgressMs) || state.title || EMPTY_LYRIC_TEXT;
  const translated = state.config.showTranslation
    ? lineAt(state.subTimeline, state.lastProgressMs)
    : "";
  const subText = translated || state.artist || "";
  const dedupeKey = [
    state.trackId,
    mainText,
    subText,
    state.playbackState,
    Math.floor(state.lastProgressMs / 250),
  ].join("::");

  if (dedupeKey === state.lastSentKey) {
    return;
  }

  state.lastSentKey = dedupeKey;
  callNative("tasklyric.update", {
    trackId: state.trackId,
    title: state.title,
    artist: state.artist,
    mainText,
    subText,
    progressMs: state.lastProgressMs,
    playbackState: state.playbackState,
  });
}

async function fetchSongDetail(trackId) {
  try {
    const query = new URLSearchParams({ ids: `[${trackId}]` });
    const response = await fetch(`${DETAIL_ENDPOINT}?${query.toString()}`, {
      credentials: "include",
    });
    const data = await response.json();
    const song = data.songs?.[0];
    if (!song) {
      return { title: "", artist: "" };
    }

    return {
      title: song.name || "",
      artist: (song.ar || song.artists || []).map((item) => item.name).filter(Boolean).join(" / "),
    };
  } catch (error) {
    console.warn("[TaskLyric] song detail request failed", error);
    return { title: "", artist: "" };
  }
}

async function fetchLyricData(trackId) {
  try {
    const query = new URLSearchParams({
      id: String(trackId),
      cp: "false",
      tv: "0",
      lv: "0",
      rv: "0",
      kv: "0",
      yv: "0",
      ytv: "0",
      yrv: "0",
    });
    const response = await fetch(`${LYRIC_ENDPOINT}?${query.toString()}`, {
      credentials: "include",
    });
    return await response.json();
  } catch (error) {
    console.warn("[TaskLyric] lyric request failed", error);
    return {};
  }
}

function parseLrc(rawLrc) {
  if (!rawLrc) {
    return [];
  }

  const lines = [];
  const rows = rawLrc.split(/\r?\n/);
  for (const row of rows) {
    const matches = [...row.matchAll(/\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]/g)];
    if (!matches.length) {
      continue;
    }

    const text = row.replace(/\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]/g, "").trim();
    if (!text) {
      continue;
    }

    for (const match of matches) {
      const minute = Number(match[1]);
      const second = Number(match[2]);
      const fraction = toMilliseconds(match[3] || "0");
      lines.push({
        timeMs: minute * 60000 + second * 1000 + fraction,
        text,
      });
    }
  }

  return lines.sort((left, right) => left.timeMs - right.timeMs);
}

function lineAt(timeline, progressMs) {
  if (!timeline.length) {
    return "";
  }

  let left = 0;
  let right = timeline.length - 1;
  let answer = -1;
  while (left <= right) {
    const mid = (left + right) >> 1;
    if (timeline[mid].timeMs <= progressMs) {
      answer = mid;
      left = mid + 1;
    } else {
      right = mid - 1;
    }
  }

  return answer >= 0 ? timeline[answer].text : "";
}

function toMilliseconds(value) {
  if (!value) {
    return 0;
  }
  if (value.length === 1) {
    return Number(value) * 100;
  }
  if (value.length === 2) {
    return Number(value) * 10;
  }
  return Number(value.slice(0, 3));
}

function extractTrackId(payload) {
  return firstNumber([
    payload?.id,
    payload?.musicId,
    payload?.songId,
    payload?.trackId,
    payload?.data?.id,
    payload?.data?.musicId,
    payload?.data?.songId,
    payload?.data?.simpleSong?.id,
    payload?.simpleSong?.id,
  ]);
}

function extractProgressMs(payload) {
  const raw = firstNumber([
    payload?.progress,
    payload?.position,
    payload?.currentTime,
    payload?.playedTime,
    payload?.data?.progress,
    payload?.data?.position,
    payload?.data?.currentTime,
  ]);

  if (raw == null) {
    return null;
  }
  if (raw < 1000) {
    return Math.round(raw * 1000);
  }
  return Math.round(raw);
}

function extractPlaybackState(payload) {
  const raw = payload?.state ?? payload?.playState ?? payload?.status ?? payload?.data?.state;
  if (raw == null) {
    return "";
  }
  return String(raw).toLowerCase();
}

function firstNumber(candidates) {
  for (const candidate of candidates) {
    const value = Number(candidate);
    if (Number.isFinite(value) && value > 0) {
      return value;
    }
  }
  return null;
}

async function syncConfigToNative() {
  await callNative("tasklyric.config", state.config);
}

async function callNative(method, payload) {
  const bridge = globalThis.betterncm_native?.native_plugin;
  if (!bridge || typeof bridge.call !== "function") {
    return;
  }

  try {
    await bridge.call(method, JSON.stringify(payload));
  } catch (error) {
    console.warn(`[TaskLyric] native call failed: ${method}`, error);
  }
}

function loadConfig() {
  try {
    if (globalThis.plugin?.getConfig) {
      return {
        ...DEFAULT_CONFIG,
        ...(plugin.getConfig("taskLyricConfig", DEFAULT_CONFIG) || {}),
      };
    }
  } catch (error) {
    console.warn("[TaskLyric] plugin.getConfig failed", error);
  }

  try {
    return {
      ...DEFAULT_CONFIG,
      ...(JSON.parse(localStorage.getItem(STORAGE_KEY) || "null") || {}),
    };
  } catch (error) {
    return { ...DEFAULT_CONFIG };
  }
}

function saveConfig(nextConfig) {
  state.config = {
    ...DEFAULT_CONFIG,
    ...nextConfig,
  };

  try {
    if (globalThis.plugin?.setConfig) {
      plugin.setConfig("taskLyricConfig", state.config);
    }
  } catch (error) {
    console.warn("[TaskLyric] plugin.setConfig failed", error);
  }

  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.config));
  syncConfigToNative();
  pushCurrentLyric();
}

function renderConfigPanel() {
  const root = document.createElement("div");
  root.style.cssText = "padding: 16px; display: grid; gap: 12px; max-width: 420px;";

  root.appendChild(makeCheckbox(CONFIG_LABELS.showTranslation, "showTranslation"));
  root.appendChild(makeTextInput(CONFIG_LABELS.fontFamily, "fontFamily"));
  root.appendChild(makeNumberInput(CONFIG_LABELS.fontSize, "fontSize", 10, 48));
  root.appendChild(makeTextInput(CONFIG_LABELS.color, "color"));
  root.appendChild(makeTextInput(CONFIG_LABELS.shadowColor, "shadowColor"));
  root.appendChild(makeSelect(CONFIG_LABELS.align, "align", [
    { label: CONFIG_LABELS.alignCenter, value: "center" },
    { label: CONFIG_LABELS.alignLeft, value: "left" },
    { label: CONFIG_LABELS.alignRight, value: "right" },
  ]));

  return root;
}

function makeCheckbox(labelText, key) {
  const label = document.createElement("label");
  label.style.cssText = "display:flex; align-items:center; gap:8px;";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = Boolean(state.config[key]);
  input.addEventListener("change", () => saveConfig({ [key]: input.checked }));
  label.append(input, document.createTextNode(labelText));
  return label;
}

function makeTextInput(labelText, key) {
  const wrapper = document.createElement("label");
  wrapper.style.cssText = "display:grid; gap:6px;";
  const text = document.createElement("span");
  text.textContent = labelText;
  const input = document.createElement("input");
  input.type = "text";
  input.value = state.config[key] ?? "";
  input.style.cssText = "padding:6px 8px;";
  input.addEventListener("change", () => saveConfig({ [key]: input.value.trim() }));
  wrapper.append(text, input);
  return wrapper;
}

function makeNumberInput(labelText, key, min, max) {
  const wrapper = document.createElement("label");
  wrapper.style.cssText = "display:grid; gap:6px;";
  const text = document.createElement("span");
  text.textContent = labelText;
  const input = document.createElement("input");
  input.type = "number";
  input.min = String(min);
  input.max = String(max);
  input.value = String(state.config[key] ?? DEFAULT_CONFIG[key]);
  input.style.cssText = "padding:6px 8px;";
  input.addEventListener("change", () => {
    const value = Number(input.value);
    if (!Number.isFinite(value)) {
      input.value = String(state.config[key] ?? DEFAULT_CONFIG[key]);
      return;
    }
    saveConfig({ [key]: Math.max(min, Math.min(max, Math.round(value))) });
  });
  wrapper.append(text, input);
  return wrapper;
}

function makeSelect(labelText, key, options) {
  const wrapper = document.createElement("label");
  wrapper.style.cssText = "display:grid; gap:6px;";
  const text = document.createElement("span");
  text.textContent = labelText;
  const select = document.createElement("select");
  select.style.cssText = "padding:6px 8px;";

  for (const option of options) {
    const node = document.createElement("option");
    node.value = option.value;
    node.textContent = option.label;
    node.selected = state.config[key] === option.value;
    select.appendChild(node);
  }

  select.addEventListener("change", () => saveConfig({ [key]: select.value }));
  wrapper.append(text, select);
  return wrapper;
}

if (globalThis.plugin?.onLoad) {
  plugin.onLoad(boot);
} else {
  boot();
}

if (globalThis.plugin?.onConfig) {
  plugin.onConfig(() => renderConfigPanel());
}

