(function (globalScope) {
  "use strict";

  var DEFAULT_CONFIG = {
    showTranslation: true,
    fontFamily: "Microsoft YaHei UI",
    fontSize: 16,
    color: "#F5F7FA",
    shadowColor: "#14161A",
    align: "center"
  };

  var LOADING_TEXT = "\u6b4c\u8bcd\u52a0\u8f7d\u4e2d";
  var EMPTY_TEXT = "\u6682\u65e0\u6b4c\u8bcd";

  function createRuntime(hostApi) {
    var state = {
      config: loadConfig(hostApi),
      trackId: null,
      title: "",
      artist: "",
      mainTimeline: [],
      subTimeline: [],
      lastSentKey: "",
      lastProgressMs: 0,
      playbackState: "unknown"
    };

    function log(level, message, meta) {
      if (hostApi && typeof hostApi.log === "function") {
        hostApi.log(level, message, meta || null);
      }
    }

    function callNative(method, payload) {
      if (hostApi && typeof hostApi.callNative === "function") {
        return Promise.resolve(hostApi.callNative(method, payload));
      }
      return Promise.resolve();
    }

    function fetchJson(url, init) {
      if (hostApi && typeof hostApi.fetchJson === "function") {
        return Promise.resolve(hostApi.fetchJson(url, init || {}));
      }
      if (typeof fetch === "function") {
        return fetch(url, init || {}).then(function (response) {
          return response.json();
        });
      }
      return Promise.reject(new Error("No fetch implementation available"));
    }

    function registerCall(name, handler) {
      if (hostApi && typeof hostApi.registerCall === "function") {
        hostApi.registerCall(name, handler);
      }
    }

    function start() {
      callNative("tasklyric.config", state.config);

      registerCall("audioplayer.onLoad", function (payload) {
        return handleTrackLoad(payload);
      });
      registerCall("audioplayer.onPlayProgress", function (payload) {
        handleProgress(payload);
      });
      registerCall("audioplayer.onPlayState", function (payload) {
        handlePlayState(payload);
      });

      log("info", "TaskLyric runtime started");
    }

    function handleTrackLoad(payload) {
      var trackId = extractTrackId(payload);
      if (!trackId) {
        log("warn", "failed to extract track id", payload);
        return Promise.resolve();
      }

      state.trackId = trackId;
      state.lastProgressMs = 0;
      state.lastSentKey = "";

      return Promise.all([
        fetchSongDetail(trackId),
        fetchLyricData(trackId)
      ]).then(function (results) {
        var detail = results[0];
        var lyricData = results[1];

        state.title = detail.title;
        state.artist = detail.artist;
        state.mainTimeline = parseLrc(lyricData && lyricData.lrc ? lyricData.lrc.lyric : "");
        state.subTimeline = parseLrc(lyricData && lyricData.tlyric ? lyricData.tlyric.lyric : "");

        return callNative("tasklyric.update", {
          trackId: state.trackId,
          title: state.title,
          artist: state.artist,
          mainText: state.title || LOADING_TEXT,
          subText: state.artist,
          progressMs: 0,
          playbackState: state.playbackState
        });
      }).catch(function (error) {
        log("warn", "handleTrackLoad failed", String(error));
      });
    }

    function handleProgress(payload) {
      var progressMs = extractProgressMs(payload);
      if (progressMs == null) {
        return;
      }

      state.lastProgressMs = progressMs;
      pushCurrentLyric();
    }

    function handlePlayState(payload) {
      var playbackState = extractPlaybackState(payload);
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

      var mainText = lineAt(state.mainTimeline, state.lastProgressMs) || state.title || EMPTY_TEXT;
      var translated = state.config.showTranslation ? lineAt(state.subTimeline, state.lastProgressMs) : "";
      var subText = translated || state.artist || "";
      var dedupeKey = [
        state.trackId,
        mainText,
        subText,
        state.playbackState,
        Math.floor(state.lastProgressMs / 250)
      ].join("::");

      if (dedupeKey === state.lastSentKey) {
        return;
      }

      state.lastSentKey = dedupeKey;
      callNative("tasklyric.update", {
        trackId: state.trackId,
        title: state.title,
        artist: state.artist,
        mainText: mainText,
        subText: subText,
        progressMs: state.lastProgressMs,
        playbackState: state.playbackState
      });
    }

    function fetchSongDetail(trackId) {
      var url = "https://music.163.com/api/song/detail?ids=%5B" + encodeURIComponent(String(trackId)) + "%5D";
      return fetchJson(url, { credentials: "include" }).then(function (data) {
        var song = data && data.songs ? data.songs[0] : null;
        if (!song) {
          return { title: "", artist: "" };
        }

        var artists = song.ar || song.artists || [];
        return {
          title: song.name || "",
          artist: artists.map(function (item) { return item.name; }).filter(Boolean).join(" / ")
        };
      });
    }

    function fetchLyricData(trackId) {
      var params = [
        "id=" + encodeURIComponent(String(trackId)),
        "cp=false",
        "tv=0",
        "lv=0",
        "rv=0",
        "kv=0",
        "yv=0",
        "ytv=0",
        "yrv=0"
      ].join("&");
      return fetchJson("https://music.163.com/api/song/lyric/v1?" + params, { credentials: "include" });
    }

    function updateConfig(patch) {
      state.config = merge(DEFAULT_CONFIG, state.config, patch || {});
      if (hostApi && typeof hostApi.setConfig === "function") {
        hostApi.setConfig("taskLyricConfig", state.config);
      }
      callNative("tasklyric.config", state.config);
      pushCurrentLyric();
      return state.config;
    }

    return {
      start: start,
      updateConfig: updateConfig,
      getState: function () { return merge({}, state); }
    };
  }

  function loadConfig(hostApi) {
    if (hostApi && typeof hostApi.getConfig === "function") {
      return merge(DEFAULT_CONFIG, hostApi.getConfig("taskLyricConfig", DEFAULT_CONFIG) || {});
    }
    return merge({}, DEFAULT_CONFIG);
  }

  function merge() {
    var result = {};
    for (var i = 0; i < arguments.length; i += 1) {
      var source = arguments[i];
      if (!source) {
        continue;
      }
      var keys = Object.keys(source);
      for (var k = 0; k < keys.length; k += 1) {
        result[keys[k]] = source[keys[k]];
      }
    }
    return result;
  }

  function parseLrc(rawLrc) {
    if (!rawLrc) {
      return [];
    }

    var lines = [];
    var rows = String(rawLrc).split(/\r?\n/);
    var pattern = /\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]/g;

    for (var i = 0; i < rows.length; i += 1) {
      var row = rows[i];
      pattern.lastIndex = 0;
      var matches = Array.from(row.matchAll(pattern));
      if (!matches.length) {
        continue;
      }

      var text = row.replace(pattern, "").trim();
      if (!text) {
        continue;
      }

      for (var j = 0; j < matches.length; j += 1) {
        var match = matches[j];
        lines.push({
          timeMs: Number(match[1]) * 60000 + Number(match[2]) * 1000 + toMilliseconds(match[3] || "0"),
          text: text
        });
      }
    }

    lines.sort(function (left, right) { return left.timeMs - right.timeMs; });
    return lines;
  }

  function lineAt(timeline, progressMs) {
    if (!timeline || !timeline.length) {
      return "";
    }

    var left = 0;
    var right = timeline.length - 1;
    var answer = -1;
    while (left <= right) {
      var mid = (left + right) >> 1;
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
    return Number(String(value).slice(0, 3));
  }

  function extractTrackId(payload) {
    return firstNumber([
      payload && payload.id,
      payload && payload.musicId,
      payload && payload.songId,
      payload && payload.trackId,
      payload && payload.data && payload.data.id,
      payload && payload.data && payload.data.musicId,
      payload && payload.data && payload.data.songId,
      payload && payload.data && payload.data.simpleSong && payload.data.simpleSong.id,
      payload && payload.simpleSong && payload.simpleSong.id
    ]);
  }

  function extractProgressMs(payload) {
    var raw = firstNumber([
      payload && payload.progress,
      payload && payload.position,
      payload && payload.currentTime,
      payload && payload.playedTime,
      payload && payload.data && payload.data.progress,
      payload && payload.data && payload.data.position,
      payload && payload.data && payload.data.currentTime
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
    var raw = payload && (payload.state || payload.playState || payload.status || (payload.data && payload.data.state));
    if (raw == null) {
      return "";
    }
    return String(raw).toLowerCase();
  }

  function firstNumber(candidates) {
    for (var i = 0; i < candidates.length; i += 1) {
      var value = Number(candidates[i]);
      if (isFinite(value) && value > 0) {
        return value;
      }
    }
    return null;
  }

  var api = {
    createRuntime: createRuntime
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalScope.TaskLyricRuntime = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
