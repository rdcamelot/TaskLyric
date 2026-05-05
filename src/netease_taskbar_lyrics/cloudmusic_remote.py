from __future__ import annotations

from dataclasses import dataclass
import json
import threading
import time
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

import websocket


REMOTE_DEBUG_SOURCE = "cloudmusic.remote-debug"
BINDING_NAME = "tasklyricDispatch"
_TARGET_URL_KEYWORDS = ("orpheus", "cloudmusic", "app.html", "subapp.html")
_REMOTE_BOOTSTRAP_GRACE_SECONDS = 4.0
_REMOTE_PLAYING_STALE_SECONDS = 4.5


@dataclass(frozen=True)
class CloudMusicRemoteState:
    connected: bool = False
    play_id: str = ""
    resume_or_pause_id: str = ""
    song_id: int = 0
    title: str = ""
    artist: str = ""
    duration_ms: int = 0
    position_ms: int = 0
    playback_status: str = "Unknown"
    fetched_at: float = 0.0
    debugger_url: str = ""
    page_title: str = ""
    connected_at: float = 0.0


class CloudMusicRemoteBridge:
    def __init__(self, *, port: int | None = 9222) -> None:
        self._port = int(port or 0)
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[int, dict[str, Any]] = {}
        self._message_id = 0
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._ws: websocket.WebSocket | None = None
        self._state = CloudMusicRemoteState()

    def get_state(self) -> CloudMusicRemoteState | None:
        if self._port <= 0:
            return None
        self._ensure_started()
        with self._lock:
            state = self._state
        if not state.connected:
            return None

        now = time.monotonic()
        if state.debugger_url and not self._debugger_target_available(state.debugger_url):
            self._invalidate_connection()
            return None

        snapshot_has_reliable_status = self._apply_player_snapshot()
        with self._lock:
            state = self._state

        if not state.connected:
            return None

        if not self._has_meaningful_state(state):
            if state.connected_at > 0 and now - state.connected_at >= _REMOTE_BOOTSTRAP_GRACE_SECONDS:
                self._invalidate_connection()
            return None

        if not snapshot_has_reliable_status:
            dom_status = self._query_player_playback_status()
            if dom_status != "Unknown" and dom_status != state.playback_status:
                with self._lock:
                    current = self._state
                    self._state = CloudMusicRemoteState(
                        connected=current.connected,
                        play_id=current.play_id,
                        resume_or_pause_id=current.resume_or_pause_id,
                        song_id=current.song_id,
                        title=current.title,
                        artist=current.artist,
                        duration_ms=current.duration_ms,
                        position_ms=current.position_ms,
                        playback_status=dom_status,
                        fetched_at=now if dom_status == "Playing" else current.fetched_at,
                        debugger_url=current.debugger_url,
                        page_title=current.page_title,
                        connected_at=current.connected_at,
                    )
                    state = self._state
        if not snapshot_has_reliable_status and _is_playing_state(state.playback_status) and state.fetched_at > 0 and now - state.fetched_at >= _REMOTE_PLAYING_STALE_SECONDS:
            self._invalidate_connection()
            return None

        return state

    def has_target(self) -> bool:
        if self._port <= 0:
            return False
        return bool(self._load_targets())

    def send_control(self, action: str) -> bool:
        normalized = action.strip().lower()
        if not normalized or self._port <= 0:
            return False
        state = self._wait_for_connected_state(timeout=2.0)
        if state is None:
            return False

        self._apply_player_snapshot()
        with self._lock:
            state = self._state

        if not state.connected:
            state = self._wait_for_connected_state(timeout=3.0)
            if state is None:
                return False
            self._apply_player_snapshot()
            with self._lock:
                state = self._state
            if not state.connected:
                return False

        if normalized == "play" and state.playback_status == "Playing":
            return True
        if normalized == "pause" and state.playback_status in {"Paused", "Stopped"}:
            return True

        if normalized in {"play", "pause", "toggle-play-pause", "next", "previous"} and self._click_player_control(normalized):
            time.sleep(0.25)
            self._apply_player_snapshot()
            return True

        if normalized in {"play", "pause"} and state.play_id and state.resume_or_pause_id:
            result = self._window_channel_call(f"audioplayer.{normalized}", state.play_id, state.resume_or_pause_id)
            return bool(result.get("ok"))

        return False

    def shutdown(self) -> None:
        self._stop_event.set()
        with self._lock:
            ws = self._ws
            self._ws = None
        if ws is not None:
            try:
                ws.close()
            except OSError:
                pass
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)

    def _ensure_started(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def _wait_for_connected_state(self, timeout: float) -> CloudMusicRemoteState | None:
        self._ensure_started()
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            with self._lock:
                state = self._state
            if state.connected:
                return state
            if time.monotonic() >= deadline or self._stop_event.is_set():
                return None
            time.sleep(0.05)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            target = self._discover_target()
            if not target:
                self._set_disconnected()
                self._stop_event.wait(1.5)
                continue

            ws_url = str(target.get("webSocketDebuggerUrl") or "").strip()
            if not ws_url:
                self._set_disconnected()
                self._stop_event.wait(1.5)
                continue

            try:
                ws = websocket.create_connection(ws_url, timeout=3, enable_multithread=True)
                ws.settimeout(1.0)
            except OSError:
                self._set_disconnected()
                self._stop_event.wait(1.5)
                continue

            with self._lock:
                self._ws = ws
                self._state = CloudMusicRemoteState(
                    connected=True,
                    debugger_url=ws_url,
                    page_title=str(target.get("title") or ""),
                    connected_at=time.monotonic(),
                )

            try:
                self._configure_runtime(ws)
                while not self._stop_event.is_set():
                    try:
                        raw_message = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    except websocket.WebSocketConnectionClosedException:
                        break
                    if not raw_message:
                        continue
                    self._handle_ws_message(raw_message)
            except (OSError, TimeoutError, RuntimeError, websocket.WebSocketException):
                pass
            finally:
                try:
                    ws.close()
                except OSError:
                    pass
                with self._lock:
                    if self._ws is ws:
                        self._ws = None
                self._clear_pending(RuntimeError("remote bridge disconnected"))
                self._set_disconnected()
                self._stop_event.wait(1.0)

    def _configure_runtime(self, ws: websocket.WebSocket) -> None:
        self._call_cdp_direct(ws, "Runtime.enable")
        self._call_cdp_direct(ws, "Page.enable")
        self._call_cdp_direct(ws, "Runtime.addBinding", {"name": BINDING_NAME})
        self._call_cdp_direct(
            ws,
            "Runtime.evaluate",
            {
                "expression": _install_script(BINDING_NAME),
                "awaitPromise": True,
                "returnByValue": True,
            },
        )

    def _handle_ws_message(self, raw_message: str) -> None:
        try:
            payload = json.loads(raw_message)
        except json.JSONDecodeError:
            return

        response_id = payload.get("id")
        if isinstance(response_id, int):
            pending = None
            with self._pending_lock:
                pending = self._pending.pop(response_id, None)
            if pending is not None:
                pending["response"] = payload
                pending["event"].set()
            return

        method = str(payload.get("method") or "")
        if method == "Runtime.bindingCalled":
            params = payload.get("params") or {}
            if str(params.get("name") or "") != BINDING_NAME:
                return
            try:
                event_payload = json.loads(str(params.get("payload") or ""))
            except json.JSONDecodeError:
                return
            if isinstance(event_payload, dict):
                self._handle_bridge_event(event_payload)

    def _handle_bridge_event(self, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("type") or "")
        args = payload.get("args") or []
        if not isinstance(args, list):
            args = [args]

        if event_type == "onLoad":
            play_id = str(args[0] or "") if len(args) >= 1 else ""
            song_id = _extract_song_id(play_id)
            now = time.monotonic()
            with self._lock:
                state = self._state
                playback_status = state.playback_status
                if play_id and play_id != state.play_id:
                    playback_status = "Paused"
                self._state = CloudMusicRemoteState(
                    connected=state.connected,
                    play_id=play_id or state.play_id,
                    resume_or_pause_id=state.resume_or_pause_id,
                    song_id=song_id or state.song_id,
                    title=state.title,
                    artist=state.artist,
                    duration_ms=state.duration_ms,
                    position_ms=0 if play_id and play_id != state.play_id else state.position_ms,
                    playback_status=playback_status,
                    fetched_at=now,
                    debugger_url=state.debugger_url,
                    page_title=state.page_title,
                    connected_at=state.connected_at,
                )
            return

        if event_type == "onPlayProgress":
            play_id = str(args[0] or "") if len(args) >= 1 else ""
            position_ms = _normalize_progress_value(args[1] if len(args) >= 2 else 0)
            song_id = _extract_song_id(play_id)
            now = time.monotonic()
            with self._lock:
                state = self._state
                playback_status = state.playback_status
                same_track = not play_id or not state.play_id or play_id == state.play_id
                new_track = bool(play_id and state.play_id and play_id != state.play_id)
                progressed = same_track and position_ms > state.position_ms + 350
                new_track_progressed = new_track and position_ms > 750
                normalized_status = playback_status.strip().lower()
                if normalized_status == "playing":
                    playback_status = "Playing"
                elif progressed or new_track_progressed:
                    playback_status = "Playing"
                elif normalized_status not in {"paused", "stopped"}:
                    playback_status = "Paused"
                self._state = CloudMusicRemoteState(
                    connected=state.connected,
                    play_id=play_id or state.play_id,
                    resume_or_pause_id=state.resume_or_pause_id,
                    song_id=song_id or state.song_id,
                    title=state.title,
                    artist=state.artist,
                    duration_ms=state.duration_ms,
                    position_ms=position_ms,
                    playback_status=playback_status,
                    fetched_at=now,
                    debugger_url=state.debugger_url,
                    page_title=state.page_title,
                    connected_at=state.connected_at,
                )
            return

        if event_type == "onPlayState":
            play_id = str(args[0] or "") if len(args) >= 1 else ""
            resume_id = str(args[1] or "") if len(args) >= 2 else ""
            playback_status = _normalize_playback_state(args[2] if len(args) >= 3 else None)
            song_id = _extract_song_id(play_id)
            now = time.monotonic()
            with self._lock:
                state = self._state
                self._state = CloudMusicRemoteState(
                    connected=state.connected,
                    play_id=play_id or state.play_id,
                    resume_or_pause_id=resume_id or state.resume_or_pause_id,
                    song_id=song_id or state.song_id,
                    title=state.title,
                    artist=state.artist,
                    duration_ms=state.duration_ms,
                    position_ms=state.position_ms,
                    playback_status=playback_status,
                    fetched_at=now if playback_status != state.playback_status else state.fetched_at,
                    debugger_url=state.debugger_url,
                    page_title=state.page_title,
                    connected_at=state.connected_at,
                )
            return

        if event_type == "onSeek":
            play_id = str(args[0] or "") if len(args) >= 1 else ""
            position_ms = _extract_seek_position_ms(args[1:])
            song_id = _extract_song_id(play_id)
            now = time.monotonic()
            with self._lock:
                state = self._state
                playback_status = state.playback_status
                if playback_status == "Unknown" and position_ms > 0:
                    playback_status = "Paused"
                self._state = CloudMusicRemoteState(
                    connected=state.connected,
                    play_id=play_id or state.play_id,
                    resume_or_pause_id=state.resume_or_pause_id,
                    song_id=song_id or state.song_id,
                    title=state.title,
                    artist=state.artist,
                    duration_ms=state.duration_ms,
                    position_ms=position_ms,
                    playback_status=playback_status,
                    fetched_at=now,
                    debugger_url=state.debugger_url,
                    page_title=state.page_title,
                    connected_at=state.connected_at,
                )
            return

        if event_type == "onEnd":
            play_id = str(args[0] or "") if len(args) >= 1 else ""
            song_id = _extract_song_id(play_id)
            with self._lock:
                state = self._state
                self._state = CloudMusicRemoteState(
                    connected=state.connected,
                    play_id=play_id or state.play_id,
                    resume_or_pause_id=state.resume_or_pause_id,
                    song_id=song_id or state.song_id,
                    title=state.title,
                    artist=state.artist,
                    duration_ms=state.duration_ms,
                    position_ms=state.position_ms,
                    playback_status="Stopped",
                    fetched_at=state.fetched_at,
                    debugger_url=state.debugger_url,
                    page_title=state.page_title,
                    connected_at=state.connected_at,
                )

    def _load_targets(self) -> list[dict[str, Any]]:
        if self._port <= 0:
            return []
        url = f"http://127.0.0.1:{self._port}/json/list"
        try:
            with urllib_request.urlopen(url, timeout=1.5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib_error.URLError, TimeoutError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def _discover_target(self) -> dict[str, Any] | None:
        candidates: list[tuple[int, dict[str, Any]]] = []
        for item in self._load_targets():
            ws_url = str(item.get("webSocketDebuggerUrl") or "").strip()
            if not ws_url:
                continue
            title = str(item.get("title") or "")
            page_url = str(item.get("url") or "")
            text = f"{title} {page_url}".lower()
            score = 0
            if item.get("type") == "page":
                score += 10
            if any(keyword in text for keyword in _TARGET_URL_KEYWORDS):
                score += 20
            if "orpheus" in page_url.lower():
                score += 20
            if score > 0:
                candidates.append((score, item))

        if not candidates:
            return None
        candidates.sort(key=lambda row: row[0], reverse=True)
        return candidates[0][1]

    @staticmethod
    def _has_meaningful_state(state: CloudMusicRemoteState) -> bool:
        if state.play_id or state.song_id > 0 or state.position_ms > 0:
            return True
        if state.title.strip() or state.artist.strip():
            return True
        return state.playback_status.strip().lower() not in {"", "unknown"}

    def _debugger_target_available(self, debugger_url: str) -> bool:
        if not debugger_url:
            return False
        for item in self._load_targets():
            ws_url = str(item.get("webSocketDebuggerUrl") or "").strip()
            if ws_url == debugger_url:
                return True
        return False

    def _invalidate_connection(self) -> None:
        with self._lock:
            ws = self._ws
            self._ws = None
        self._set_disconnected()
        if ws is not None:
            try:
                ws.close()
            except OSError:
                pass

    def _window_channel_call(self, command: str, *args: Any) -> dict[str, Any]:
        expression = _channel_call_expression(command, list(args))
        try:
            response = self._call_cdp(
                "Runtime.evaluate",
                {
                    "expression": expression,
                    "awaitPromise": True,
                    "returnByValue": True,
                },
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        result = ((response.get("result") or {}).get("result") or {}).get("value")
        return result if isinstance(result, dict) else {"ok": False, "error": "no-result"}

    def _call_cdp(self, method: str, params: dict[str, Any] | None = None, timeout: float = 5.0) -> dict[str, Any]:
        with self._lock:
            ws = self._ws
        if ws is None:
            raise RuntimeError("remote bridge is disconnected")

        with self._pending_lock:
            self._message_id += 1
            message_id = self._message_id
            slot = {"event": threading.Event(), "response": None}
            self._pending[message_id] = slot

        packet = {"id": message_id, "method": method}
        if params:
            packet["params"] = params

        try:
            with self._send_lock:
                ws.send(json.dumps(packet, ensure_ascii=False))
            if not slot["event"].wait(timeout):
                raise TimeoutError(f"Timed out waiting for CDP response: {method}")
            response = slot["response"] or {}
            if isinstance(response, dict) and response.get("error"):
                raise RuntimeError(str(response.get("error")))
            return response if isinstance(response, dict) else {}
        except (OSError, TimeoutError, RuntimeError, websocket.WebSocketException):
            self._invalidate_connection()
            raise
        finally:
            with self._pending_lock:
                self._pending.pop(message_id, None)

    def _call_cdp_direct(self, ws: websocket.WebSocket, method: str, params: dict[str, Any] | None = None, timeout: float = 5.0) -> dict[str, Any]:
        with self._pending_lock:
            self._message_id += 1
            message_id = self._message_id

        packet = {"id": message_id, "method": method}
        if params:
            packet["params"] = params

        deadline = time.monotonic() + timeout
        original_timeout = None
        try:
            original_timeout = ws.gettimeout()
        except OSError:
            original_timeout = None

        with self._send_lock:
            ws.send(json.dumps(packet, ensure_ascii=False))

        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Timed out waiting for CDP response: {method}")
                ws.settimeout(min(max(remaining, 0.05), 1.0))
                raw_message = ws.recv()
                try:
                    payload = json.loads(raw_message)
                except json.JSONDecodeError:
                    continue
                if payload.get("id") == message_id:
                    if isinstance(payload, dict) and payload.get("error"):
                        raise RuntimeError(str(payload.get("error")))
                    return payload if isinstance(payload, dict) else {}
                self._handle_ws_message(raw_message)
        finally:
            try:
                if original_timeout is not None:
                    ws.settimeout(original_timeout)
            except OSError:
                pass

    def _apply_player_snapshot(self) -> bool:
        try:
            response = self._call_cdp(
                "Runtime.evaluate",
                {
                    "expression": _player_snapshot_expression(),
                    "awaitPromise": True,
                    "returnByValue": True,
                },
                timeout=1.5,
            )
        except Exception:
            return False

        result = ((response.get("result") or {}).get("result") or {}).get("value")
        if not isinstance(result, dict) or not result.get("ok"):
            return False

        playback_status = _normalize_snapshot_playback_state(result.get("playbackStatus"))
        has_reliable_status = playback_status != "Unknown"
        song_id = _coerce_int(result.get("songId"))
        title = str(result.get("title") or "").strip()
        artist = str(result.get("artist") or "").strip()
        play_id = str(result.get("playId") or "").strip()
        position_ms = _normalize_progress_value(result.get("positionMs") or result.get("position") or 0)
        duration_ms = _normalize_progress_value(result.get("durationMs") or result.get("duration") or 0)
        now = time.monotonic()

        with self._lock:
            state = self._state
            same_track = not song_id or not state.song_id or song_id == state.song_id
            if playback_status == "Unknown":
                playback_status = state.playback_status

            if position_ms <= 0 and same_track:
                position_ms = state.position_ms

            fetched_at = state.fetched_at or now
            if playback_status == "Playing":
                if same_track and state.playback_status == "Playing" and state.fetched_at > 0:
                    estimated_ms = state.position_ms + int((now - state.fetched_at) * 1000)
                    if position_ms <= 0 or abs(position_ms - estimated_ms) <= 2500:
                        position_ms = state.position_ms
                        fetched_at = state.fetched_at
                    else:
                        fetched_at = now
                else:
                    fetched_at = now
            elif playback_status in {"Paused", "Stopped"}:
                if same_track and state.playback_status == playback_status and state.position_ms > 0 and abs(position_ms - state.position_ms) <= 2500:
                    position_ms = state.position_ms
                fetched_at = now

            self._state = CloudMusicRemoteState(
                connected=state.connected,
                play_id=play_id or state.play_id,
                resume_or_pause_id=state.resume_or_pause_id,
                song_id=song_id or state.song_id,
                title=title or state.title,
                artist=artist or state.artist,
                duration_ms=duration_ms or state.duration_ms,
                position_ms=position_ms,
                playback_status=playback_status,
                fetched_at=fetched_at,
                debugger_url=state.debugger_url,
                page_title=state.page_title,
                connected_at=state.connected_at,
            )
        return has_reliable_status

    def _query_player_playback_status(self) -> str:
        try:
            response = self._call_cdp(
                "Runtime.evaluate",
                {
                    "expression": _player_status_expression(),
                    "awaitPromise": True,
                    "returnByValue": True,
                },
                timeout=1.0,
            )
        except Exception:
            return "Unknown"
        result = ((response.get("result") or {}).get("result") or {}).get("value")
        if not isinstance(result, dict):
            return "Unknown"
        return _normalize_playback_state(result.get("playbackStatus"))

    def _click_player_control(self, action: str) -> bool:
        try:
            response = self._call_cdp(
                "Runtime.evaluate",
                {
                    "expression": _player_control_expression(action),
                    "awaitPromise": True,
                    "returnByValue": True,
                },
                timeout=3.0,
            )
        except Exception:
            return False
        result = ((response.get("result") or {}).get("result") or {}).get("value")
        if not isinstance(result, dict) or not result.get("ok"):
            return False

        playback_status = _normalize_snapshot_playback_state(result.get("playbackStatus"))
        if playback_status != "Unknown":
            with self._lock:
                state = self._state
                self._state = CloudMusicRemoteState(
                    connected=state.connected,
                    play_id=state.play_id,
                    resume_or_pause_id=state.resume_or_pause_id,
                    song_id=state.song_id,
                    title=state.title,
                    artist=state.artist,
                    duration_ms=state.duration_ms,
                    position_ms=state.position_ms,
                    playback_status=playback_status,
                    fetched_at=time.monotonic(),
                    debugger_url=state.debugger_url,
                    page_title=state.page_title,
                    connected_at=state.connected_at,
                )
        return True

    def _clear_pending(self, error: Exception) -> None:
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for slot in pending:
            slot["response"] = {"error": str(error)}
            slot["event"].set()

    def _set_disconnected(self) -> None:
        with self._lock:
            state = self._state
            self._state = CloudMusicRemoteState(
                connected=False,
                play_id=state.play_id,
                resume_or_pause_id=state.resume_or_pause_id,
                song_id=state.song_id,
                title=state.title,
                artist=state.artist,
                duration_ms=state.duration_ms,
                position_ms=state.position_ms,
                playback_status=state.playback_status,
                fetched_at=state.fetched_at,
                debugger_url=state.debugger_url,
                page_title=state.page_title,
            )


def _channel_call_expression(command: str, args: list[Any]) -> str:
    command_json = json.dumps(command, ensure_ascii=False)
    args_json = json.dumps(args, ensure_ascii=False)
    return f"""
(async () => {{
  try {{
    if (!window.channel || typeof window.channel.call !== 'function') {{
      return {{ ok: false, error: 'channel-missing' }};
    }}
    const payload = {args_json};
    return await new Promise((resolve) => {{
      try {{
        window.channel.call({command_json}, (...cbArgs) => resolve({{ ok: true, args: Array.from(cbArgs) }}), payload);
      }} catch (error) {{
        resolve({{ ok: false, error: String(error && error.message || error) }});
      }}
    }});
  }} catch (error) {{
    return {{ ok: false, error: String(error && error.message || error) }};
  }}
}})();
"""


def _install_script(binding_name: str) -> str:
    binding_name_json = json.dumps(binding_name, ensure_ascii=False)
    return f"""
(() => {{
  const bindingName = {binding_name_json};
  const state = window.__tasklyricBridgeState || (window.__tasklyricBridgeState = {{
    installed: false,
    bindingName: bindingName,
  }});
  state.bindingName = bindingName;
  const emit = (type, args = []) => {{
    try {{
      const activeBindingName = state.bindingName || bindingName;
      const binding = window[activeBindingName];
      if (typeof binding === 'function') {{
        binding(JSON.stringify({{ type, args: Array.from(args) }}));
      }}
    }} catch (error) {{
    }}
  }};
  const install = () => {{
    if (!window.channel || typeof window.channel.registerCall !== 'function') {{
      return false;
    }}
    if (!state.installed) {{
      window.channel.registerCall('audioplayer.onLoad', (...args) => emit('onLoad', args));
      window.channel.registerCall('audioplayer.onPlayProgress', (...args) => emit('onPlayProgress', args));
      window.channel.registerCall('audioplayer.onPlayState', (...args) => emit('onPlayState', args));
      window.channel.registerCall('audioplayer.onSeek', (...args) => emit('onSeek', args));
      window.channel.registerCall('audioplayer.onEnd', (...args) => emit('onEnd', args));
      state.installed = true;
    }}
    emit('bridgeReady', []);
    return true;
  }};
  if (install()) {{
    return {{ ok: true, installed: state.installed, rebound: true }};
  }}
  if (!window.__tasklyricBridgeInstallTimer) {{
    window.__tasklyricBridgeInstallTimer = setInterval(() => {{
      if (install()) {{
        clearInterval(window.__tasklyricBridgeInstallTimer);
        window.__tasklyricBridgeInstallTimer = 0;
      }}
    }}, 500);
  }}
  return {{ ok: true, waiting: true }};
}})();
"""


def _player_snapshot_expression() -> str:
    return """
(() => {
  const decode = (key) => {
    try {
      if (!window.channel || typeof window.channel.deData !== 'function') {
        return null;
      }
      const raw = window.localStorage ? window.localStorage.getItem(key) : null;
      if (!raw) {
        return null;
      }
      const decoded = window.channel.deData(raw);
      return decoded ? JSON.parse(decoded) : null;
    } catch (error) {
      return null;
    }
  };
  const toNumber = (value) => {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : 0;
  };
  const artistText = (artists) => {
    if (!Array.isArray(artists)) {
      return '';
    }
    return artists.map((artist) => artist && artist.name).filter(Boolean).join(' / ');
  };
  const playing = decode('playingInfo') || {};
  const last = decode('lastPlaying') || {};
  const track = playing.curTrack || {};
  const curPlaying = playing.curPlaying || {};
  const songId = toNumber(
    playing.resourceTrackId ||
    playing.onlineResourceId ||
    track.id ||
    curPlaying.id ||
    last.trackId ||
    last.resourceId
  );
  const title = String(playing.resourceName || track.name || curPlaying.name || '').trim();
  const artist = artistText(playing.resourceArtists || track.artists || track.ar || curPlaying.artists || curPlaying.ar);
  const position = toNumber(last.current || last.position || playing.current || playing.loadingSeekDuration);
  const duration = toNumber(playing.resourceDuration || last.resourceDuration || track.duration || track.dt || curPlaying.duration || curPlaying.dt);
  const playId = String(playing.playId || '').trim();
  return {
    ok: Boolean(songId || title || position || playId),
    songId,
    title,
    artist,
    playId,
    position,
    duration,
    playbackStatus: playing.playingState,
  };
})();
"""

def _player_status_expression() -> str:
    return """
(() => {
  const isVisible = (element) => {
    if (!element) {
      return false;
    }
    const rect = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const controlGroups = Array.from(document.querySelectorAll('div')).filter((element) =>
    isVisible(element) &&
    String(element.className || '').includes('btns') &&
    element.querySelector('.cmd-icon-pre') &&
    element.querySelector('.cmd-icon-next') &&
    Array.from(element.querySelectorAll('button')).some((button) => button.querySelector('.cmd-icon-pause, .cmd-icon-play'))
  );
  const controlGroup = controlGroups.sort((left, right) => right.getBoundingClientRect().y - left.getBoundingClientRect().y)[0] || null;
  if (!controlGroup) {
    return { ok: false, playbackStatus: 'Unknown' };
  }
  const toggleButton = Array.from(controlGroup.querySelectorAll('button')).find((button) => button.querySelector('.cmd-icon-pause, .cmd-icon-play')) || null;
  if (!toggleButton) {
    return { ok: false, playbackStatus: 'Unknown' };
  }
  if (toggleButton.querySelector('.cmd-icon-pause')) {
    return { ok: true, playbackStatus: 'Playing' };
  }
  if (toggleButton.querySelector('.cmd-icon-play')) {
    return { ok: true, playbackStatus: 'Paused' };
  }
  return { ok: false, playbackStatus: 'Unknown' };
})();
"""


def _player_control_expression(action: str) -> str:
    action_json = json.dumps(action, ensure_ascii=False)
    return f"""
(() => {{
  const requestedAction = {action_json};
  const isVisible = (element) => {{
    if (!element) {{
      return false;
    }}
    const rect = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  }};
  const controlGroups = Array.from(document.querySelectorAll('div')).filter((element) =>
    isVisible(element) &&
    String(element.className || '').includes('btns') &&
    element.querySelector('.cmd-icon-pre') &&
    element.querySelector('.cmd-icon-next') &&
    Array.from(element.querySelectorAll('button')).some((button) => button.querySelector('.cmd-icon-pause, .cmd-icon-play'))
  );
  const controlGroup = controlGroups.sort((left, right) => right.getBoundingClientRect().y - left.getBoundingClientRect().y)[0] || null;
  if (!controlGroup) {{
    return {{ ok: false, error: 'control-group-not-found', action: requestedAction }};
  }}
  const toggleButton = Array.from(controlGroup.querySelectorAll('button')).find((button) => button.querySelector('.cmd-icon-pause, .cmd-icon-play')) || null;
  const previousButton = Array.from(controlGroup.querySelectorAll('button')).find((button) => button.querySelector('.cmd-icon-pre')) || null;
  const nextButton = Array.from(controlGroup.querySelectorAll('button')).find((button) => button.querySelector('.cmd-icon-next')) || null;
  const playbackStatus = () => {{
    if (!toggleButton) {{
      return 'Unknown';
    }}
    if (toggleButton.querySelector('.cmd-icon-pause')) {{
      return 'Playing';
    }}
    if (toggleButton.querySelector('.cmd-icon-play')) {{
      return 'Paused';
    }}
    return 'Unknown';
  }};
  let button = null;
  if (requestedAction === 'play' || requestedAction === 'pause' || requestedAction === 'toggle-play-pause') {{
    button = toggleButton;
  }} else if (requestedAction === 'previous') {{
    button = previousButton;
  }} else if (requestedAction === 'next') {{
    button = nextButton;
  }}
  if (!button || !isVisible(button)) {{
    return {{ ok: false, error: 'control-not-found', action: requestedAction }};
  }}
  const stateBefore = playbackStatus();
  if (typeof button.click === 'function') {{
    button.click();
  }} else {{
    button.dispatchEvent(new MouseEvent('click', {{ bubbles: true, cancelable: true, view: window }}));
  }}
  return {{ ok: true, action: requestedAction, playbackStatus: playbackStatus(), stateBefore }};
}})();
"""


def _coerce_int(raw: Any) -> int:
    try:
        return max(0, int(float(raw)))
    except (TypeError, ValueError):
        return 0


def _extract_song_id(raw: Any) -> int:
    if isinstance(raw, int):
        return max(raw, 0)
    if isinstance(raw, str):
        head = raw.split("_", 1)[0].strip()
        if head.isdigit():
            return int(head)
    return 0


def _extract_seek_position_ms(values: list[Any]) -> int:
    numeric_values: list[float] = []
    for value in values:
        try:
            numeric_values.append(float(value))
        except (TypeError, ValueError):
            continue
    if not numeric_values:
        return 0

    # NetEase seek payloads can vary; the target position is consistently the last numeric value.
    return _normalize_progress_value(numeric_values[-1])


def _normalize_progress_value(raw: Any) -> int:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0
    if value <= 0:
        return 0
    if value < 10000:
        return int(round(value * 1000))
    return int(round(value))


def _normalize_snapshot_playback_state(raw: Any) -> str:
    if isinstance(raw, (int, float)):
        numeric = int(raw)
        if numeric == 1:
            return "Paused"
        if numeric == 2:
            return "Playing"
        if numeric == 0:
            return "Stopped"
    return _normalize_playback_state(raw)

def _normalize_playback_state(raw: Any) -> str:
    if isinstance(raw, str):
        value = raw.strip().lower()
        if not value:
            return "Unknown"
        if value in {"play", "playing", "resume", "resumed"}:
            return "Playing"
        if value in {"pause", "paused"}:
            return "Paused"
        if value in {"stop", "stopped", "end", "ended"}:
            return "Stopped"
        if value.isdigit():
            return _normalize_playback_state(int(value))
        return raw.strip().title()
    if isinstance(raw, (int, float)):
        numeric = int(raw)
        if numeric == 1:
            return "Playing"
        if numeric == 2:
            return "Paused"
        if numeric == 0:
            return "Stopped"
    return "Unknown"


def _is_playing_state(playback_status: str) -> bool:
    return playback_status.strip().lower() == "playing"
