from __future__ import annotations

from dataclasses import dataclass
import queue
import threading
import time

from .lrc import LyricTimeline
from .netease_api import NeteaseLyricClient
from .overlay import TaskbarLyricWindow
from .smtc import MediaSessionProvider, MediaSessionSnapshot


POLL_INTERVAL_SECONDS = 1.2
TICK_INTERVAL_MS = 150
REPOSITION_INTERVAL_MS = 1500
WAITING_TEXT = "\u7b49\u5f85\u7f51\u6613\u4e91\u97f3\u4e50\u5f00\u59cb\u64ad\u653e"
LOADING_PREFIX = "\u6b63\u5728\u52a0\u8f7d\u6b4c\u8bcd: "


@dataclass(frozen=True)
class LyricResult:
    track_key: str
    timeline: LyricTimeline | None


class TaskbarLyricsApp:
    def __init__(self) -> None:
        self.provider = MediaSessionProvider()
        self.lyric_client = NeteaseLyricClient()
        self.overlay = TaskbarLyricWindow()

        self._session_queue: queue.Queue[MediaSessionSnapshot | None] = queue.Queue()
        self._lyric_queue: queue.Queue[LyricResult] = queue.Queue()
        self._stop_event = threading.Event()

        self._active_session: MediaSessionSnapshot | None = None
        self._active_track_key = ""
        self._pending_track_key = ""
        self._timeline: LyricTimeline | None = None
        self._last_visible_text = ""
        self._last_reposition_at = 0.0

    def start(self) -> None:
        thread = threading.Thread(target=self._poll_session_loop, daemon=True)
        thread.start()
        self.overlay.after(TICK_INTERVAL_MS, self._tick)
        self.overlay.run()

    def stop(self) -> None:
        self._stop_event.set()
        self.overlay.destroy()

    def _tick(self) -> None:
        self._drain_session_queue()
        self._drain_lyric_queue()
        self._refresh_display()

        now = time.monotonic()
        if now - self._last_reposition_at >= REPOSITION_INTERVAL_MS / 1000:
            self.overlay.reposition()
            self._last_reposition_at = now

        self.overlay.after(TICK_INTERVAL_MS, self._tick)

    def _poll_session_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                session = self.provider.get_current_session()
            except Exception:
                session = None

            self._session_queue.put(session)
            self._stop_event.wait(POLL_INTERVAL_SECONDS)

    def _drain_session_queue(self) -> None:
        has_update = False
        latest_session: MediaSessionSnapshot | None = None
        while True:
            try:
                latest_session = self._session_queue.get_nowait()
                has_update = True
            except queue.Empty:
                break

        if not has_update:
            return

        if latest_session is None:
            self._active_session = None
            self._active_track_key = ""
            self._pending_track_key = ""
            self._timeline = None
            return

        previous_track = self._active_track_key
        self._active_session = latest_session
        self._active_track_key = _track_key(latest_session)

        if self._active_track_key != previous_track:
            self._timeline = None
            self._pending_track_key = self._active_track_key
            self._start_lyric_fetch(latest_session)

    def _drain_lyric_queue(self) -> None:
        while True:
            try:
                result = self._lyric_queue.get_nowait()
            except queue.Empty:
                break

            if result.track_key != self._active_track_key:
                continue

            self._timeline = result.timeline
            if result.track_key == self._pending_track_key:
                self._pending_track_key = ""

    def _start_lyric_fetch(self, session: MediaSessionSnapshot) -> None:
        thread = threading.Thread(
            target=self._fetch_lyrics_worker,
            args=(self._active_track_key, session.title, session.artist),
            daemon=True,
        )
        thread.start()

    def _fetch_lyrics_worker(self, track_key: str, title: str, artist: str) -> None:
        try:
            timeline = self.lyric_client.get_timeline(title, artist)
        except Exception:
            timeline = None
        self._lyric_queue.put(LyricResult(track_key=track_key, timeline=timeline))

    def _refresh_display(self) -> None:
        if not self._active_session:
            self._show_text(WAITING_TEXT)
            return

        if self._timeline:
            position_ms = self._active_session.estimated_position_ms()
            line = self._timeline.line_at(position_ms)
            if line:
                self._show_text(line)
                return

        artist_suffix = f" - {self._active_session.artist}" if self._active_session.artist else ""
        if self._pending_track_key:
            self._show_text(f"{LOADING_PREFIX}{self._active_session.title}{artist_suffix}")
            return

        self._show_text(f"{self._active_session.title}{artist_suffix}")

    def _show_text(self, text: str) -> None:
        if text == self._last_visible_text:
            return
        self.overlay.set_text(text)
        self._last_visible_text = text


def _track_key(session: MediaSessionSnapshot) -> str:
    return f"{session.title.strip().lower()}::{session.artist.strip().lower()}"


def run() -> None:
    app = TaskbarLyricsApp()
    try:
        app.start()
    except KeyboardInterrupt:
        app.stop()
