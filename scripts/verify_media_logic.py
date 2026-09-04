from __future__ import annotations

import argparse
import json
import queue
import threading
import time
from pathlib import Path
import sys
from urllib import error as urllib_error
from urllib import request as urllib_request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.netease_taskbar_lyrics.app import TaskbarLyricsApp, _freeze_session_after_resume  # noqa: E402
from src.netease_taskbar_lyrics.cloudmusic import CloudMusicTrack, CloudMusicWindowProbe  # noqa: E402
from src.netease_taskbar_lyrics.cloudmusic_remote import (  # noqa: E402
    CloudMusicRemoteBridge,
    CloudMusicRemoteState,
    _normalize_playback_state,
    _normalize_snapshot_playback_state,
)
from src.netease_taskbar_lyrics.launcher import (  # noqa: E402
    TaskLyricBackgroundLauncher,
    cloudmusic_has_remote_debug_port,
    cloudmusic_process_ids,
    cloudmusic_reporter_process_ids,
    remote_debug_available,
    repair_pinned_cloudmusic_shortcuts,
)
from src.netease_taskbar_lyrics.smtc import MediaSessionProvider, MediaSessionSnapshot  # noqa: E402


def snapshot(source: str, title: str = "Browser Video", artist: str = "Web", status: str = "Playing") -> MediaSessionSnapshot:
    return MediaSessionSnapshot(
        source_app_user_model_id=source,
        title=title,
        artist=artist,
        album_title="",
        position_ms=1000,
        duration_ms=100000,
        start_time_ms=0,
        playback_status=status,
        fetched_at=time.monotonic(),
        detection_source="test",
    )


class FakeRemote:
    def __init__(self, *, has_target: bool = False, control_ok: bool = False, state: CloudMusicRemoteState | None = None) -> None:
        self.has_target_value = has_target
        self.control_ok = control_ok
        self.state = state

    def get_state(self):
        return self.state

    def has_target(self) -> bool:
        return self.has_target_value

    def send_control(self, action: str) -> bool:
        return self.control_ok

    def shutdown(self) -> None:
        pass


class FakeHelper:
    def __init__(self, session: MediaSessionSnapshot | None = None) -> None:
        self.session = session
        self.control_called = False

    def get_current_session(self) -> MediaSessionSnapshot | None:
        return self.session

    def send_control(self, action: str) -> bool:
        self.control_called = True
        return True

    def shutdown(self) -> None:
        pass


class FakeWindow:
    def __init__(self, *, command_ok: bool = False, match: bool = False) -> None:
        self.command_ok = command_ok
        self.match = match

    def has_player_window(self) -> bool:
        return True

    def send_media_command(self, action: str, *, allow_global_fallback: bool = True) -> bool:
        assert allow_global_fallback is False
        return self.command_ok

    def matches_current_track(self, title: str, artist: str) -> bool:
        return self.match

    def get_current_track(self):
        return None


class FakeWindowWithTrack(FakeWindow):
    def get_current_track(self):
        return CloudMusicTrack(
            title="Song",
            artist="Artist",
            song_id=123,
            duration_ms=180000,
            source_window_class="OrpheusBrowserHost",
            source_window_title="Song - Artist",
        )


class FakeRecoverProvider:
    def __init__(self) -> None:
        self.recover_count = 0
        self.control_called = False

    def recover_after_system_resume(self) -> None:
        self.recover_count += 1

    def control(self, action: str) -> bool:
        self.control_called = True
        return False


class FakeControlProvider:
    def __init__(self) -> None:
        self.control_actions: list[str] = []
        self.get_current_session_called = False

    def control(self, action: str) -> bool:
        self.control_actions.append(action)
        return True

    def get_current_session(self) -> MediaSessionSnapshot | None:
        self.get_current_session_called = True
        return None


class FakeBridge:
    def __init__(self, commands: list[dict[str, object]] | None = None) -> None:
        self.commands = list(commands or [])
        self.events: list[tuple[str, dict[str, object]]] = []

    def take_pending_command(self) -> dict[str, object] | None:
        return self.commands.pop(0) if self.commands else None

    def emit_event(self, name: str, payload: object) -> int:
        self.events.append((name, payload if isinstance(payload, dict) else {}))
        return 0


def provider() -> MediaSessionProvider:
    instance = MediaSessionProvider(remote_debug_port=0)
    instance._remote = FakeRemote()
    return instance


def verify_playback_state_mapping() -> None:
    assert _normalize_playback_state(0) == "Stopped"
    assert _normalize_playback_state(1) == "Paused"
    assert _normalize_playback_state(2) == "Playing"
    assert _normalize_playback_state("1") == "Paused"
    assert _normalize_playback_state("2") == "Playing"
    assert _normalize_snapshot_playback_state(1) == "Paused"
    assert _normalize_snapshot_playback_state(2) == "Playing"


def verify_browser_smtc_is_rejected() -> None:
    instance = provider()
    instance._helper = FakeHelper(None)
    instance._window_probe = FakeWindow(match=False)
    instance.get_sessions = lambda: [snapshot("Chrome")]
    assert instance.get_current_session() is None
    instance.shutdown()


def verify_stale_helper_browser_session_is_rejected() -> None:
    instance = provider()
    instance._helper = FakeHelper(snapshot("Chrome"))
    instance._window_probe = FakeWindow(match=True)
    instance.get_sessions = lambda: []
    assert instance.get_current_session() is None
    instance.shutdown()


def verify_explicit_netease_session_is_accepted() -> None:
    instance = provider()
    instance._helper = FakeHelper(snapshot("NetEase.CloudMusic", "Song", "Artist"))
    instance._window_probe = FakeWindow(match=False)
    instance.get_sessions = lambda: []
    selected = instance.get_current_session()
    assert selected is not None
    assert selected.source_app_user_model_id == "NetEase.CloudMusic"
    instance.shutdown()


def verify_window_fallback_does_not_autoplay() -> None:
    instance = provider()
    instance._helper = FakeHelper(None)
    instance._window_probe = FakeWindowWithTrack()
    instance.get_sessions = lambda: []
    first = instance.get_current_session()
    time.sleep(0.02)
    second = instance.get_current_session()
    assert first is not None
    assert second is not None
    assert first.detection_source == "window"
    assert first.playback_status == "Paused"
    assert second.playback_status == "Paused"
    assert first.estimated_position_ms() == 0
    assert second.estimated_position_ms() == 0
    instance.shutdown()


def verify_local_cached_track_clears_stale_online_identity() -> None:
    bridge = object.__new__(CloudMusicRemoteBridge)
    bridge._lock = threading.Lock()
    bridge._state = CloudMusicRemoteState(
        connected=True,
        play_id="1939837729_online",
        song_id=1939837729,
        title="Previous Song",
        artist="Previous Artist",
        duration_ms=231000,
        position_ms=162000,
        playback_status="Playing",
        fetched_at=time.monotonic() - 1,
    )
    bridge._call_cdp = lambda method, params, timeout: {
        "result": {
            "result": {
                "value": {
                    "ok": True,
                    "songId": 0,
                    "title": "Local Track",
                    "artist": "Local Artist",
                    "playId": "LOCAL_CACHE_HASH",
                    "positionMs": 5000,
                    "durationMs": 180000,
                    "playbackStatus": 2,
                }
            }
        }
    }

    assert bridge._apply_player_snapshot() is True
    state = bridge._state
    assert state.play_id == "LOCAL_CACHE_HASH"
    assert state.song_id == 0
    assert state.title == "Local Track"
    assert state.artist == "Local Artist"
    assert state.position_ms == 5000

    provider_instance = provider()
    provider_instance._remote = FakeRemote(
        state=CloudMusicRemoteState(
            connected=True,
            play_id="LOCAL_CACHE_HASH",
            song_id=0,
            title="Song",
            artist="Artist",
            duration_ms=180000,
            playback_status="Playing",
            fetched_at=time.monotonic(),
        )
    )
    provider_instance._window_probe = FakeWindowWithTrack()
    session = provider_instance.get_current_session()
    assert session is not None
    assert session.song_id == 0
    provider_instance.shutdown()


def verify_resume_freeze_does_not_jump_progress() -> None:
    original = snapshot("NetEase.CloudMusic", "Song", "Artist")
    original = MediaSessionSnapshot(
        source_app_user_model_id=original.source_app_user_model_id,
        title=original.title,
        artist=original.artist,
        album_title=original.album_title,
        position_ms=42000,
        duration_ms=180000,
        start_time_ms=original.start_time_ms,
        playback_status="Playing",
        fetched_at=time.monotonic() - 3600,
        song_id=123,
        detection_source=original.detection_source,
    )
    frozen = _freeze_session_after_resume(original, time.monotonic())
    assert frozen.playback_status == "Paused"
    assert frozen.position_ms == 42000
    assert frozen.estimated_position_ms() == 42000


def verify_provider_recovery_rebuilds_watchers() -> None:
    instance = MediaSessionProvider(remote_debug_port=0)
    old_remote = instance._remote
    old_helper = instance._helper
    instance._fallback_track_key = "stale"
    instance._fallback_position_ms = 999
    instance.recover_after_system_resume()
    assert instance._remote is not old_remote
    assert instance._helper is not old_helper
    assert instance._fallback_track_key == ""
    assert instance._fallback_position_ms == 0
    instance.shutdown()


def verify_control_fails_closed() -> None:
    helper = FakeHelper(snapshot("NetEase.CloudMusic"))
    instance = provider()
    instance._helper = helper
    instance._window_probe = FakeWindow(command_ok=False)
    assert instance.control("pause") is False
    assert helper.control_called is False
    instance.shutdown()


def verify_play_pause_control_does_not_optimistically_flip_state() -> None:
    app = object.__new__(TaskbarLyricsApp)
    app.provider = FakeControlProvider()
    app.bridge = FakeBridge([{"action": "pause", "source": "taskbar-control"}])
    app._stop_event = threading.Event()
    app._stop_event.set()
    app._session_queue = queue.Queue()
    app._active_track_key = "track"
    app._pending_track_key = ""
    app._main_timeline = object()
    app._translation_timeline = object()
    app._resolved_song_id = 123
    app._last_payload_key = ("stale",)
    app._active_session = MediaSessionSnapshot(
        source_app_user_model_id="NetEase.CloudMusic",
        title="Song",
        artist="Artist",
        album_title="",
        position_ms=33000,
        duration_ms=180000,
        start_time_ms=0,
        playback_status="Playing",
        fetched_at=time.monotonic() - 1,
        song_id=123,
        detection_source="test",
    )

    app._drain_control_queue()

    assert app.provider.control_actions == ["pause"]
    assert app._active_session.playback_status == "Playing"
    assert app._last_payload_key is None
    assert app._main_timeline is not None
    assert app._translation_timeline is not None


def verify_system_resume_command_recovers_provider() -> None:
    app = object.__new__(TaskbarLyricsApp)
    app.provider = FakeRecoverProvider()
    app.bridge = FakeBridge([
        {"action": "system-resume", "source": "windows-session", "reason": "session-unlock"}
    ])
    app._session_queue = queue.Queue()
    app._session_queue.put(snapshot("Chrome"))
    app._active_session = MediaSessionSnapshot(
        source_app_user_model_id="NetEase.CloudMusic",
        title="Song",
        artist="Artist",
        album_title="",
        position_ms=33000,
        duration_ms=180000,
        start_time_ms=0,
        playback_status="Playing",
        fetched_at=time.monotonic() - 120,
        song_id=123,
        detection_source="test",
    )
    app._session_missing_since = time.monotonic() - 10
    app._missing_cloudmusic_since = time.monotonic() - 10
    app._last_loop_tick = time.monotonic() - 10
    app._last_payload_key = ("stale",)

    app._drain_control_queue()

    assert app.provider.recover_count == 1
    assert app.provider.control_called is False
    assert app._session_queue.empty()
    assert app._session_missing_since == 0.0
    assert app._missing_cloudmusic_since == 0.0
    assert app._active_session.playback_status == "Paused"
    assert app._active_session.position_ms == 33000
    assert app._active_session.estimated_position_ms() == 33000
    assert app._last_payload_key is None
    assert app.bridge.events[-1] == (
        "tasklyric.live.system_resume",
        {"reason": "session-unlock", "source": "windows-session"},
    )


def verify_headless_cloudmusic_process_does_not_keep_tasklyric_running() -> None:
    now = time.monotonic()
    # A stale cloudmusic.exe may retain the remote-debug argument after its UI
    # exits. Once its one-time startup grace has elapsed, it is not usable.
    assert not TaskLyricBackgroundLauncher._cloudmusic_is_usable(
        process_running=True,
        remote_ready=False,
        window_ready=False,
        startup_grace_until=now - 0.1,
        now=now,
    )
    assert TaskLyricBackgroundLauncher._cloudmusic_is_usable(
        process_running=True,
        remote_ready=False,
        window_ready=False,
        startup_grace_until=now + 0.1,
        now=now,
    )
    assert TaskLyricBackgroundLauncher._cloudmusic_is_usable(
        process_running=True,
        remote_ready=True,
        window_ready=False,
        startup_grace_until=now - 0.1,
        now=now,
    )

    launcher = TaskLyricBackgroundLauncher()
    launcher._startup_grace_until = now - 0.1
    launcher._remote_debug_process_signature = (50132,)
    # A temporary command-line probe failure must not make the same zombie PID
    # eligible for another startup grace when the probe recovers.
    launcher._observe_remote_debug_process(
        process_ids=[50132],
        remote_debug_process=False,
        remote_ready=False,
        now=now,
    )
    launcher._observe_remote_debug_process(
        process_ids=[50132],
        remote_debug_process=True,
        remote_ready=False,
        now=now,
    )
    assert launcher._startup_grace_until < now


def run_static_verification() -> None:
    verify_playback_state_mapping()
    verify_browser_smtc_is_rejected()
    verify_stale_helper_browser_session_is_rejected()
    verify_explicit_netease_session_is_accepted()
    verify_window_fallback_does_not_autoplay()
    verify_local_cached_track_clears_stale_online_identity()
    verify_resume_freeze_does_not_jump_progress()
    verify_provider_recovery_rebuilds_watchers()
    verify_control_fails_closed()
    verify_play_pause_control_does_not_optimistically_flip_state()
    verify_system_resume_command_recovers_provider()
    verify_headless_cloudmusic_process_does_not_keep_tasklyric_running()


def snapshot_to_dict(session: MediaSessionSnapshot | None) -> dict[str, object] | None:
    if session is None:
        return None
    return {
        "sourceAppUserModelId": session.source_app_user_model_id,
        "detectionSource": session.detection_source,
        "title": session.title,
        "artist": session.artist,
        "playbackStatus": session.playback_status,
        "positionMs": session.position_ms,
        "estimatedPositionMs": session.estimated_position_ms(),
        "durationMs": session.duration_ms,
        "songId": session.song_id,
    }


def remote_target_diagnostics(port: int) -> list[dict[str, object]]:
    url = f"http://127.0.0.1:{int(port)}/json/list"
    try:
        with urllib_request.urlopen(url, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib_error.URLError, TimeoutError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    targets = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        targets.append({
            "id": str(item.get("id") or ""),
            "type": str(item.get("type") or ""),
            "title": str(item.get("title") or ""),
            "url": str(item.get("url") or ""),
            "hasWebSocket": bool(item.get("webSocketDebuggerUrl")),
        })
    return targets


def remote_state_to_dict(state: CloudMusicRemoteState | None) -> dict[str, object] | None:
    if state is None:
        return None
    return {
        "connected": state.connected,
        "songId": state.song_id,
        "title": state.title,
        "artist": state.artist,
        "playbackStatus": state.playback_status,
        "positionMs": state.position_ms,
        "durationMs": state.duration_ms,
        "playIdPresent": bool(state.play_id),
        "resumeOrPauseIdPresent": bool(state.resume_or_pause_id),
        "pageTitle": state.page_title,
        "debuggerUrlPresent": bool(state.debugger_url),
    }


def read_remote_state(port: int, timeout_seconds: float = 3.0) -> dict[str, object] | None:
    bridge = CloudMusicRemoteBridge(port=port)
    try:
        deadline = time.monotonic() + timeout_seconds
        state = None
        while time.monotonic() < deadline:
            state = bridge.get_state()
            if state is not None:
                return remote_state_to_dict(state)
            time.sleep(0.15)
        return remote_state_to_dict(state)
    finally:
        bridge.shutdown()


def window_track_to_dict(track: CloudMusicTrack | None) -> dict[str, object] | None:
    if track is None:
        return None
    return {
        "title": track.title,
        "artist": track.artist,
        "songId": track.song_id,
        "durationMs": track.duration_ms,
        "sourceWindowClass": track.source_window_class,
        "sourceWindowTitle": track.source_window_title,
    }


def read_selected_session(provider: MediaSessionProvider, timeout_seconds: float = 3.0) -> dict[str, object] | None:
    deadline = time.monotonic() + timeout_seconds
    latest = None
    while time.monotonic() < deadline:
        latest = snapshot_to_dict(provider.get_current_session())
        if latest is not None:
            return latest
        time.sleep(0.15)
    return latest


def live_diagnostics(port: int, probe_timeout: float = 3.0) -> dict[str, object]:
    provider = MediaSessionProvider(remote_debug_port=port)
    try:
        raw_smtc_sessions = [snapshot_to_dict(session) for session in provider.get_sessions()]
        selected_session = read_selected_session(provider, timeout_seconds=probe_timeout)
    finally:
        provider.shutdown()

    window_probe = CloudMusicWindowProbe()
    return {
        "cloudMusicProcessIds": cloudmusic_process_ids(),
        "cloudMusicReporterProcessIds": cloudmusic_reporter_process_ids(),
        "cloudMusicHasRemoteDebugArg": cloudmusic_has_remote_debug_port(port),
        "remoteDebugAvailable": remote_debug_available(port),
        "remoteTargets": remote_target_diagnostics(port),
        "remoteState": read_remote_state(port, timeout_seconds=probe_timeout),
        "windowTrack": window_track_to_dict(window_probe.get_current_track()),
        "launcherState": read_launcher_state(),
        "shortcutRepair": repair_pinned_cloudmusic_shortcuts(port),
        "rawSmtcSessions": raw_smtc_sessions,
        "selectedSession": selected_session,
    }


def read_launcher_state() -> dict[str, object] | None:
    path = ROOT / "state" / "launcher-state.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def watch_live_diagnostics(port: int, seconds: float, interval: float, probe_timeout: float) -> None:
    deadline = time.monotonic() + max(0.0, seconds)
    sample_index = 0
    provider = MediaSessionProvider(remote_debug_port=port)
    window_probe = CloudMusicWindowProbe()
    try:
        while time.monotonic() <= deadline:
            selected_session = read_selected_session(provider, timeout_seconds=probe_timeout)
            remote_state = remote_state_to_dict(provider._remote.get_state())
            payload = {
                "mode": "watch-fast",
                "remoteDebugAvailable": remote_debug_available(port),
                "remoteTargets": remote_target_diagnostics(port),
                "remoteState": remote_state,
                "windowTrack": window_track_to_dict(window_probe.get_current_track()),
                "selectedSession": selected_session,
                "sampleIndex": sample_index,
                "sampleTime": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)
            sample_index += 1
            time.sleep(max(0.2, interval))
    finally:
        provider.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify TaskLyric media routing safety invariants.")
    parser.add_argument("--live", action="store_true", help="Also print current CloudMusic/SMTC/remote-debug diagnostics.")
    parser.add_argument("--watch-seconds", type=float, default=0.0, help="Continuously print live diagnostics for this many seconds.")
    parser.add_argument("--watch-interval", type=float, default=1.0, help="Seconds between --watch-seconds samples.")
    parser.add_argument("--probe-timeout", type=float, default=3.0, help="Seconds to wait for remote-debug/session state in live diagnostics.")
    parser.add_argument("--port", type=int, default=9222, help="CloudMusic remote-debug port.")
    args = parser.parse_args(argv)

    run_static_verification()
    if args.watch_seconds > 0:
        watch_live_diagnostics(args.port, args.watch_seconds, args.watch_interval, min(args.probe_timeout, 0.8))
    elif args.live:
        print(json.dumps(live_diagnostics(args.port, probe_timeout=args.probe_timeout), ensure_ascii=False, indent=2))
    else:
        print("media logic verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
