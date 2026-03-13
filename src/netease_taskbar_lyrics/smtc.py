from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import time


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "get_media_sessions.ps1"
NETEASE_KEYWORDS = ("cloudmusic", "netease")


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

    def estimated_position_ms(self) -> int:
        position = max(self.position_ms, self.start_time_ms)
        if self.playback_status.lower() == "playing":
            position += int((time.monotonic() - self.fetched_at) * 1000)
        if self.duration_ms > 0:
            position = min(position, self.duration_ms)
        return position


class MediaSessionProvider:
    def get_current_session(self) -> MediaSessionSnapshot | None:
        sessions = self.get_sessions()
        if not sessions:
            return None

        netease_sessions = [
            session
            for session in sessions
            if any(keyword in session.source_app_user_model_id.lower() for keyword in NETEASE_KEYWORDS)
        ]
        if netease_sessions:
            sessions = netease_sessions
        elif len(sessions) != 1:
            return None

        return max(sessions, key=self._session_score)

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
                )
            )

        return sessions

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


