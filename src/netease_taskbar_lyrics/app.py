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
WAITING_TEXT = "等待网易云音乐开始播放"
LOADING_PREFIX = "正在加载歌词"
STOPPED_SUBTEXT = "TaskLyric"


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
    ) -> None:
        self.provider = MediaSessionProvider()
        self.lyric_client = NeteaseLyricClient()
        self.bridge = HostTaskbarBridge(config={"showTranslation": show_translation})

        self.poll_interval_seconds = max(0.4, float(poll_interval_seconds))
        self.tick_interval_ms = max(60, int(tick_interval_ms))
        self.show_translation = show_translation

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

    def start(self) -> None:
        self.bridge.start()
        self.bridge.emit_event(
            "tasklyric.live.started",
            {
                "pollIntervalSeconds": self.poll_interval_seconds,
                "tickIntervalMs": self.tick_interval_ms,
                "showTranslation": self.show_translation,
            },
        )

        thread = threading.Thread(target=self._poll_session_loop, daemon=True)
        thread.start()

        try:
            while not self._stop_event.is_set():
                self._drain_session_queue()
                self._drain_lyric_queue()
                self._drain_control_queue()
                self._refresh_display()
                self._stop_event.wait(self.tick_interval_ms / 1000)
        finally:
            self.stop()

    def stop(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
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
            if self._active_session is not None:
                self.bridge.emit_event("tasklyric.live.session_cleared", {})
            self._active_session = None
            self._active_track_key = ""
            self._pending_track_key = ""
            self._main_timeline = None
            self._translation_timeline = None
            self._resolved_song_id = 0
            return

        previous_track = self._active_track_key
        self._active_session = latest_session
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

    def _apply_control_hint(self, action: str) -> None:
        session = self._active_session
        if session is None:
            return

        progress_ms = session.estimated_position_ms()
        now = time.monotonic()
        if action == "pause":
            self._active_session = replace(session, playback_status="Paused", position_ms=progress_ms, fetched_at=now)
            self._last_payload_key = None
            return
        if action == "play":
            self._active_session = replace(session, playback_status="Playing", position_ms=progress_ms, fetched_at=now)
            self._last_payload_key = None
            return
        if action in {"next", "previous"}:
            self._pending_track_key = self._active_track_key
            self._main_timeline = None
            self._translation_timeline = None
            self._resolved_song_id = 0
            self._last_payload_key = None

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

        if self._main_timeline:
            current_line = self._main_timeline.line_at(progress_ms)
            if current_line:
                main_text = current_line

        if self.show_translation and self._translation_timeline:
            translated_line = self._translation_timeline.line_at(progress_ms)
            if translated_line:
                sub_text = translated_line

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
    args = parser.parse_args(argv)

    app = TaskbarLyricsApp(
        show_translation=not args.no_translation,
        poll_interval_seconds=args.poll_interval,
        tick_interval_ms=args.tick_ms,
    )
    try:
        app.start()
    except KeyboardInterrupt:
        app.stop()
