from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import time

from .cloudmusic import CloudMusicWindowProbe


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "get_media_sessions.ps1"
NETEASE_KEYWORDS = ("cloudmusic", "netease")
WINDOW_FALLBACK_SOURCE = "cloudmusic.window"


@dataclass(frozen=True)
class MediaSessionSnapshot:
    source_app_user_model_id: str
    title: str
    artist: str
    album_title: str
    position_ms: int
    duration_ms: int
    start_time_ms: int
    playback_status: str
    fetched_at: float
    song_id: int = 0
    detection_source: str = "smtc"

    def estimated_position_ms(self) -> int:
        position = max(self.position_ms, self.start_time_ms)
        if self.playback_status.lower() == "playing":
            position += int((time.monotonic() - self.fetched_at) * 1000)
        if self.duration_ms > 0:
            position = min(position, self.duration_ms)
        return position


class MediaSessionProvider:
    def __init__(self) -> None:
        self._window_probe = CloudMusicWindowProbe()
        self._fallback_track_key = ""
        self._fallback_position_ms = 0
        self._fallback_anchor = time.monotonic()

    def get_current_session(self) -> MediaSessionSnapshot | None:
        sessions = self.get_sessions()
        if sessions:
            netease_sessions = [
                session
                for session in sessions
                if any(keyword in session.source_app_user_model_id.lower() for keyword in NETEASE_KEYWORDS)
            ]
            if netease_sessions:
                sessions = netease_sessions
            elif len(sessions) != 1:
                sessions = []

            if sessions:
                self._reset_fallback_progress()
                return max(sessions, key=self._session_score)

        return self._get_window_fallback_session()

    def get_sessions(self) -> list[MediaSessionSnapshot]:
        try:
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(SCRIPT_PATH),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=6,
            )
        except (OSError, subprocess.SubprocessError):
            return []

        payload = completed.stdout.strip()
        if not payload:
            return []

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return []
        if isinstance(data, dict) and data.get("error"):
            return []
        if isinstance(data, dict):
            data = [data]

        now = time.monotonic()
        sessions: list[MediaSessionSnapshot] = []
        for item in data:
            title = str(item.get("title") or "").strip()
            artist = str(item.get("artist") or "").strip()
            if not title:
                continue

            sessions.append(
                MediaSessionSnapshot(
                    source_app_user_model_id=str(item.get("sourceAppUserModelId") or ""),
                    title=title,
                    artist=artist,
                    album_title=str(item.get("albumTitle") or ""),
                    position_ms=int(item.get("positionMs") or 0),
                    duration_ms=int(item.get("durationMs") or 0),
                    start_time_ms=int(item.get("startTimeMs") or 0),
                    playback_status=str(item.get("playbackStatus") or "Unknown"),
                    fetched_at=now,
                    detection_source="smtc",
                )
            )

        return sessions

    def _get_window_fallback_session(self) -> MediaSessionSnapshot | None:
        track = self._window_probe.get_current_track()
        if track is None:
            self._reset_fallback_progress()
            return None

        now = time.monotonic()
        track_key = self._fallback_key(track.title, track.artist, track.song_id)
        if track_key != self._fallback_track_key:
            self._fallback_track_key = track_key
            self._fallback_position_ms = 0
            self._fallback_anchor = now
        else:
            elapsed_ms = max(0, int((now - self._fallback_anchor) * 1000))
            self._fallback_position_ms += elapsed_ms
            self._fallback_anchor = now
            if track.duration_ms > 0:
                self._fallback_position_ms = min(self._fallback_position_ms, track.duration_ms)

        return MediaSessionSnapshot(
            source_app_user_model_id=WINDOW_FALLBACK_SOURCE,
            title=track.title,
            artist=track.artist,
            album_title="",
            position_ms=self._fallback_position_ms,
            duration_ms=track.duration_ms,
            start_time_ms=0,
            playback_status="Playing",
            fetched_at=now,
            song_id=track.song_id,
            detection_source="window",
        )

    def _reset_fallback_progress(self) -> None:
        self._fallback_track_key = ""
        self._fallback_position_ms = 0
        self._fallback_anchor = time.monotonic()

    @staticmethod
    def _fallback_key(title: str, artist: str, song_id: int) -> str:
        return f"{song_id}:{title.strip().lower()}:{artist.strip().lower()}"

    @staticmethod
    def _session_score(session: MediaSessionSnapshot) -> tuple[int, int, int]:
        source = session.source_app_user_model_id.lower()
        is_netease = any(keyword in source for keyword in NETEASE_KEYWORDS)
        is_playing = session.playback_status.lower() == "playing"
        return (
            1 if is_netease else 0,
            1 if is_playing else 0,
            len(session.title),
        )
