from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import queue
import threading
import time

from .host_bridge import HostTaskbarBridge
from .lrc import LyricTimeline
from .netease_api import LyricBundle, NeteaseLyricClient
from .smtc import MediaSessionProvider, MediaSessionSnapshot


DEFAULT_POLL_INTERVAL_SECONDS = 1.2
DEFAULT_TICK_INTERVAL_MS = 150
AUTO_STOP_ABSENCE_SECONDS = 5.0
SESSION_MISSING_GRACE_SECONDS = 3.5
SYSTEM_RESUME_GAP_SECONDS = 8.0
WAITING_TEXT = "等待网易云音乐开始播放"
LOADING_PREFIX = "正在加载歌词"
STOPPED_SUBTEXT = "TaskLyric"
WINDOW_FALLBACK_SUBTEXT = "等待精确同步"


@dataclass(frozen=True)
class LyricResult:
    track_key: str
    bundle: LyricBundle | None


class TaskbarLyricsApp:
    def __init__(
        self,
        *,
        show_translation: bool = True,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        tick_interval_ms: int = DEFAULT_TICK_INTERVAL_MS,
        remote_debug_port: int | None = 9222,
    ) -> None:
        self.provider = MediaSessionProvider(remote_debug_port=remote_debug_port)
        self.lyric_client = NeteaseLyricClient()
        self.bridge = HostTaskbarBridge(config={"showTranslation": show_translation})

        self.poll_interval_seconds = max(0.4, float(poll_interval_seconds))
        self.tick_interval_ms = max(60, int(tick_interval_ms))
        self.show_translation = show_translation
        self.remote_debug_port = int(remote_debug_port or 0) if remote_debug_port else 0

        self._session_queue: queue.Queue[MediaSessionSnapshot | None] = queue.Queue()
        self._lyric_queue: queue.Queue[LyricResult] = queue.Queue()
        self._stop_event = threading.Event()

        self._active_session: MediaSessionSnapshot | None = None
        self._active_track_key = ""
        self._pending_track_key = ""
        self._main_timeline: LyricTimeline | None = None
        self._translation_timeline: LyricTimeline | None = None
        self._resolved_song_id = 0
        self._last_payload_key: tuple[str, ...] | None = None
        self._has_seen_cloudmusic = False
        self._missing_cloudmusic_since = 0.0
        self._session_missing_since = 0.0
        self._last_loop_tick = time.monotonic()
        self._shutdown_complete = False

    def start(self) -> None:
        self.bridge.start()
        self.bridge.emit_event(
            "tasklyric.live.started",
            {
                "pollIntervalSeconds": self.poll_interval_seconds,
                "tickIntervalMs": self.tick_interval_ms,
                "showTranslation": self.show_translation,
                "remoteDebugPort": self.remote_debug_port,
            },
        )

        thread = threading.Thread(target=self._poll_session_loop, daemon=True)
        thread.start()

        try:
            while not self._stop_event.is_set():
                self._handle_possible_system_resume()
                self._drain_session_queue()
                self._drain_lyric_queue()
                self._drain_control_queue()
                self._refresh_display()
                self._maybe_auto_stop_after_cloudmusic_exit()
                self._stop_event.wait(self.tick_interval_ms / 1000)
        finally:
            self.stop()

    def stop(self) -> None:
        if not self._stop_event.is_set():
            self._stop_event.set()
        if self._shutdown_complete:
            return
        self._shutdown_complete = True
        self.provider.shutdown()
        self.bridge.emit_event("tasklyric.live.stopped", {})
        self.bridge.shutdown()

    def _poll_session_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                session = self.provider.get_current_session()
            except Exception as exc:
                self.bridge.emit_event("tasklyric.live.session_error", {"message": str(exc)})
                session = None

            self._session_queue.put(session)
            self._stop_event.wait(self.poll_interval_seconds)

    def _handle_possible_system_resume(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_loop_tick
        self._last_loop_tick = now
        if elapsed < SYSTEM_RESUME_GAP_SECONDS:
            return

        self._recover_after_system_event(reason="loop-gap", source="main-loop", gap_seconds=elapsed)

    def _recover_after_system_event(self, *, reason: str, source: str, gap_seconds: float | None = None) -> None:
        now = time.monotonic()
        self._last_loop_tick = now
        self._clear_session_queue()
        self._session_missing_since = 0.0
        self._missing_cloudmusic_since = 0.0
        try:
            self.provider.recover_after_system_resume()
        except Exception as exc:
            payload = {"message": str(exc), "reason": reason, "source": source}
            if gap_seconds is not None:
                payload["gapSeconds"] = gap_seconds
            self.bridge.emit_event("tasklyric.live.resume_recover_error", payload)

        if self._active_session is not None:
            self._active_session = _freeze_session_after_resume(self._active_session, now)
            self._last_payload_key = None

        payload = {"reason": reason, "source": source}
        if gap_seconds is not None:
            payload["gapSeconds"] = gap_seconds
        self.bridge.emit_event("tasklyric.live.system_resume", payload)

    def _clear_session_queue(self) -> None:
        while True:
            try:
                self._session_queue.get_nowait()
            except queue.Empty:
                return

    def _drain_session_queue(self) -> None:
        latest_session: MediaSessionSnapshot | None = None
        has_update = False
        while True:
            try:
                latest_session = self._session_queue.get_nowait()
                has_update = True
            except queue.Empty:
                break

        if not has_update:
            return

        if latest_session is None:
            if self._active_session is not None and self.provider.has_cloudmusic_activity():
                now = time.monotonic()
                if self._session_missing_since <= 0:
                    self._session_missing_since = now
                if now - self._session_missing_since < SESSION_MISSING_GRACE_SECONDS:
                    return
            if self._active_session is not None:
                self.bridge.emit_event("tasklyric.live.session_cleared", {})
            self._active_session = None
            self._active_track_key = ""
            self._pending_track_key = ""
            self._main_timeline = None
            self._translation_timeline = None
            self._resolved_song_id = 0
            self._session_missing_since = 0.0
            return
        previous_track = self._active_track_key
        self._session_missing_since = 0.0
        self._active_session = latest_session
        self._has_seen_cloudmusic = True
        self._missing_cloudmusic_since = 0.0
        self._active_track_key = _track_key(latest_session)

        if self._active_track_key != previous_track:
            self._main_timeline = None
            self._translation_timeline = None
            self._resolved_song_id = 0
            self._pending_track_key = self._active_track_key
            self._last_payload_key = None
            self.bridge.emit_event(
                "audioplayer.onLoad",
                {
                    "title": latest_session.title,
                    "artist": latest_session.artist,
                    "trackKey": self._active_track_key,
                    "playbackStatus": latest_session.playback_status,
                    "detectionSource": latest_session.detection_source,
                    "songId": latest_session.song_id,
                },
            )
            self._start_lyric_fetch(latest_session)

    def _drain_lyric_queue(self) -> None:
        while True:
            try:
                result = self._lyric_queue.get_nowait()
            except queue.Empty:
                break

            if result.track_key != self._active_track_key:
                continue

            self._pending_track_key = ""
            if result.bundle is None:
                self._main_timeline = None
                self._translation_timeline = None
                self._resolved_song_id = 0
                continue

            self._main_timeline = result.bundle.main_timeline
            self._translation_timeline = result.bundle.translation_timeline
            self._resolved_song_id = result.bundle.song_id

    def _drain_control_queue(self) -> None:
        while True:
            payload = self.bridge.take_pending_command()
            if not payload:
                return

            action = str(payload.get("action") or "").strip().lower()
            if not action:
                continue

            if action == "system-resume":
                self._recover_after_system_event(
                    reason=str(payload.get("reason") or "native-system-event"),
                    source=str(payload.get("source") or "native"),
                )
                continue

            ok = False
            try:
                ok = self.provider.control(action)
            except Exception as exc:
                self.bridge.emit_event(
                    "tasklyric.live.control_error",
                    {"action": action, "message": str(exc)},
                )
                continue

            self.bridge.emit_event(
                "tasklyric.live.control",
                {
                    "action": action,
                    "ok": ok,
                    "source": str(payload.get("source") or "taskbar"),
                },
            )
            if ok:
                self._apply_control_hint(action)

    def _schedule_control_refresh(self, action: str) -> None:
        thread = threading.Thread(target=self._control_refresh_worker, args=(action,), daemon=True)
        thread.start()

    def _control_refresh_worker(self, action: str) -> None:
        for delay_seconds in (0.25, 0.8):
            if self._stop_event.wait(delay_seconds):
                return
            try:
                session = self.provider.get_current_session()
            except Exception as exc:
                self.bridge.emit_event(
                    "tasklyric.live.control_refresh_error",
                    {"action": action, "message": str(exc)},
                )
                continue
            self._session_queue.put(session)

    def _apply_control_hint(self, action: str) -> None:
        session = self._active_session
        if session is None:
            return

        if action in {"pause", "play", "toggle-play-pause"}:
            # Do not mirror a local play/pause state optimistically. The remote
            # click can be delayed or ignored by NetEase, and a local hint would
            # make TaskLyric briefly show the opposite of the real player state.
            self._last_payload_key = None
            self._schedule_control_refresh(action)
            return
        if action in {"next", "previous"}:
            self._pending_track_key = self._active_track_key
            self._main_timeline = None
            self._translation_timeline = None
            self._resolved_song_id = 0
            self._last_payload_key = None
            self._schedule_control_refresh(action)

    def _start_lyric_fetch(self, session: MediaSessionSnapshot) -> None:
        thread = threading.Thread(
            target=self._fetch_lyrics_worker,
            args=(self._active_track_key, session),
            daemon=True,
        )
        thread.start()

    def _fetch_lyrics_worker(self, track_key: str, session: MediaSessionSnapshot) -> None:
        try:
            bundle = None
            if session.song_id > 0:
                bundle = self.lyric_client.get_bundle_by_song_id(
                    session.song_id,
                    title_hint=session.title,
                    artist_hint=session.artist,
                )
            if bundle is None:
                bundle = self.lyric_client.get_bundle(session.title, session.artist)
        except Exception as exc:
            self.bridge.emit_event(
                "tasklyric.live.lyric_error",
                {"title": session.title, "artist": session.artist, "message": str(exc)},
            )
            bundle = None
        self._lyric_queue.put(LyricResult(track_key=track_key, bundle=bundle))

    def _refresh_display(self) -> None:
        if not self._active_session:
            self._publish_display(
                title="",
                artist="",
                main_text=WAITING_TEXT,
                sub_text=STOPPED_SUBTEXT,
                progress_ms=0,
                playback_state="stopped",
                track_id=0,
            )
            return

        session = self._active_session
        progress_ms = session.estimated_position_ms()
        playback_state = session.playback_status.lower() or "unknown"
        artist = session.artist.strip()
        title = session.title.strip()

        main_text = title or WAITING_TEXT
        sub_text = artist or STOPPED_SUBTEXT
        exact_sync_available = session.detection_source != "window"

        if exact_sync_available and self._main_timeline:
            current_line = self._main_timeline.line_at(progress_ms)
            if current_line:
                main_text = current_line

        if exact_sync_available and self.show_translation and self._translation_timeline:
            translated_line = self._translation_timeline.line_at(progress_ms)
            if translated_line:
                sub_text = translated_line

        if not exact_sync_available:
            sub_text = artist or WINDOW_FALLBACK_SUBTEXT

        if self._pending_track_key:
            main_text = f"{LOADING_PREFIX}: {title}" if title else LOADING_PREFIX
            sub_text = artist or STOPPED_SUBTEXT

        self._publish_display(
            title=title,
            artist=artist,
            main_text=main_text,
            sub_text=sub_text,
            progress_ms=progress_ms,
            playback_state=playback_state,
            track_id=self._resolved_song_id or session.song_id,
        )

    def _maybe_auto_stop_after_cloudmusic_exit(self) -> None:
        if self.provider.has_cloudmusic_activity():
            self._has_seen_cloudmusic = True
            self._missing_cloudmusic_since = 0.0
            return
        if not self._has_seen_cloudmusic:
            return

        now = time.monotonic()
        if self._missing_cloudmusic_since <= 0:
            self._missing_cloudmusic_since = now
            return
        if now - self._missing_cloudmusic_since < AUTO_STOP_ABSENCE_SECONDS:
            return

        self.bridge.emit_event(
            "tasklyric.live.auto_stop",
            {"reason": "cloudmusic-inactive", "graceSeconds": AUTO_STOP_ABSENCE_SECONDS},
        )
        self._stop_event.set()

    def _publish_display(
        self,
        *,
        title: str,
        artist: str,
        main_text: str,
        sub_text: str,
        progress_ms: int,
        playback_state: str,
        track_id: int,
    ) -> None:
        payload_key = (
            title,
            artist,
            main_text,
            sub_text,
            str(track_id),
            str(progress_ms // 200),
            playback_state,
        )
        if payload_key == self._last_payload_key:
            return

        self._last_payload_key = payload_key
        self.bridge.update_lyric(
            title=title,
            artist=artist,
            main_text=main_text,
            sub_text=sub_text,
            progress_ms=progress_ms,
            playback_state=playback_state,
            track_id=track_id,
        )


def _freeze_session_after_resume(session: MediaSessionSnapshot, now: float) -> MediaSessionSnapshot:
    # After system sleep/lock, elapsed monotonic time may be large while playback
    # state is unknown. Freeze at the last confirmed position until a fresh
    # NetEase remote-debug state arrives.
    return replace(session, playback_status="Paused", position_ms=max(0, int(session.position_ms)), fetched_at=now)


def _track_key(session: MediaSessionSnapshot) -> str:
    return (
        f"{session.source_app_user_model_id.strip().lower()}::"
        f"{session.song_id}::"
        f"{session.title.strip().lower()}::"
        f"{session.artist.strip().lower()}"
    )


def run(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the TaskLyric live bridge for NetEase Cloud Music.")
    parser.add_argument("--no-translation", action="store_true", help="Hide translated lyric lines when available.")
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS, help="Seconds between playback-source polls.")
    parser.add_argument("--tick-ms", type=int, default=DEFAULT_TICK_INTERVAL_MS, help="Milliseconds between host updates.")
    parser.add_argument("--remote-debug-port", type=int, default=9222, help="Chromium remote debugging port for exact NetEase playback events. Set 0 to disable.")
    args = parser.parse_args(argv)

    app = TaskbarLyricsApp(
        show_translation=not args.no_translation,
        poll_interval_seconds=args.poll_interval,
        tick_interval_ms=args.tick_ms,
        remote_debug_port=args.remote_debug_port,
    )
    try:
        app.start()
    except KeyboardInterrupt:
        app.stop()
