from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import threading
import time

from .cloudmusic import CloudMusicWindowProbe


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "get_media_sessions.ps1"
HELPER_PROJECT_PATH = Path(__file__).resolve().parents[2] / "tools" / "TaskLyric.MediaSessionHelper" / "TaskLyric.MediaSessionHelper.csproj"
HELPER_DLL_PATH = HELPER_PROJECT_PATH.parent / "bin" / "Debug" / "net9.0-windows10.0.19041.0" / "TaskLyric.MediaSessionHelper.dll"
NETEASE_KEYWORDS = ("cloudmusic", "netease")
WINDOW_FALLBACK_SOURCE = "cloudmusic.window"
DOTNET_HELPER_SOURCE = "dotnet-smtc"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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
    can_pause: bool = False
    can_play: bool = False
    can_go_next: bool = False
    can_go_previous: bool = False
    can_seek: bool = False
    can_toggle_play_pause: bool = False

    def estimated_position_ms(self) -> int:
        position = max(self.position_ms, self.start_time_ms)
        if self.playback_status.lower() == "playing":
            position += int((time.monotonic() - self.fetched_at) * 1000)
        if self.duration_ms > 0:
            position = min(position, self.duration_ms)
        return position


class _DotNetMediaSessionWatcher:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._latest_session: MediaSessionSnapshot | None = None
        self._latest_error = ""
        self._build_attempted = False

    def get_current_session(self) -> MediaSessionSnapshot | None:
        if not self._ensure_started():
            return None
        with self._lock:
            return self._latest_session

    def send_control(self, action: str) -> bool:
        if not self._ensure_built():
            return False

        try:
            completed = subprocess.run(
                self._helper_command("control", "--action", action),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=8,
                creationflags=CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            return False

        payload = _parse_json_lines(completed.stdout)
        return bool(isinstance(payload, dict) and payload.get("type") == "control" and payload.get("ok"))

    def shutdown(self) -> None:
        process = None
        with self._lock:
            process = self._process
            self._process = None
            self._latest_session = None
        if process and process.poll() is None:
            process.kill()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.5)
        if self._stderr_thread and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=1.5)

    def _ensure_started(self) -> bool:
        with self._lock:
            if self._process and self._process.poll() is None:
                return True
            self._process = None

        if not self._ensure_built():
            return False

        try:
            process = subprocess.Popen(
                self._helper_command("watch", "--interval-ms", "220"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
            )
        except OSError:
            return False

        reader_thread = threading.Thread(target=self._pump_stdout, args=(process,), daemon=True)
        stderr_thread = threading.Thread(target=self._pump_stderr, args=(process,), daemon=True)
        reader_thread.start()
        stderr_thread.start()

        with self._lock:
            self._process = process
            self._reader_thread = reader_thread
            self._stderr_thread = stderr_thread
        return True

    def _ensure_built(self) -> bool:
        if HELPER_DLL_PATH.exists():
            return True
        if self._build_attempted or not HELPER_PROJECT_PATH.exists():
            return HELPER_DLL_PATH.exists()

        self._build_attempted = True
        try:
            completed = subprocess.run(
                ["dotnet", "build", str(HELPER_PROJECT_PATH), "-nologo", "-clp:ErrorsOnly"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
                creationflags=CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0 and HELPER_DLL_PATH.exists()

    def _helper_command(self, *args: str) -> list[str]:
        if HELPER_DLL_PATH.exists():
            return ["dotnet", str(HELPER_DLL_PATH), *args]
        return ["dotnet", "run", "--project", str(HELPER_PROJECT_PATH), "--", *args]

    def _pump_stdout(self, process: subprocess.Popen[str]) -> None:
        stream = process.stdout
        if stream is None:
            return
        for raw_line in stream:
            payload = _parse_json_line(raw_line)
            if not isinstance(payload, dict):
                continue
            payload_type = str(payload.get("type") or "")
            if payload_type == "state":
                session = _snapshot_from_helper(payload.get("session"))
                with self._lock:
                    self._latest_session = session
            elif payload_type == "error":
                with self._lock:
                    self._latest_error = str(payload.get("message") or "")
        with self._lock:
            if self._process is process:
                self._process = None

    def _pump_stderr(self, process: subprocess.Popen[str]) -> None:
        stream = process.stderr
        if stream is None:
            return
        for raw_line in stream:
            line = raw_line.strip()
            if not line:
                continue
            with self._lock:
                self._latest_error = line


class MediaSessionProvider:
    def __init__(self) -> None:
        self._window_probe = CloudMusicWindowProbe()
        self._helper = _DotNetMediaSessionWatcher()
        self._fallback_track_key = ""
        self._fallback_position_ms = 0
        self._fallback_anchor = time.monotonic()

    def shutdown(self) -> None:
        self._helper.shutdown()

    def get_current_session(self) -> MediaSessionSnapshot | None:
        helper_session = self._helper.get_current_session()
        if helper_session and self._looks_like_netease_session(helper_session):
            self._reset_fallback_progress()
            return helper_session

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

    def control(self, action: str) -> bool:
        normalized = action.strip().lower()
        if not normalized:
            return False
        if self._helper.send_control(normalized):
            return True
        return self._window_probe.send_media_command(normalized)

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
                creationflags=CREATE_NO_WINDOW,
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
                    detection_source="powershell-smtc",
                )
            )

        return sessions

    def _looks_like_netease_session(self, session: MediaSessionSnapshot) -> bool:
        source = session.source_app_user_model_id.lower()
        if any(keyword in source for keyword in NETEASE_KEYWORDS):
            return True
        return self._window_probe.matches_current_track(session.title, session.artist)

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


def _snapshot_from_helper(payload: object) -> MediaSessionSnapshot | None:
    if not isinstance(payload, dict):
        return None
    title = str(payload.get("title") or "").strip()
    if not title:
        return None
    now = time.monotonic()
    return MediaSessionSnapshot(
        source_app_user_model_id=str(payload.get("sourceAppUserModelId") or ""),
        title=title,
        artist=str(payload.get("artist") or "").strip(),
        album_title=str(payload.get("albumTitle") or "").strip(),
        position_ms=int(payload.get("positionMs") or 0),
        duration_ms=int(payload.get("durationMs") or 0),
        start_time_ms=int(payload.get("startTimeMs") or 0),
        playback_status=str(payload.get("playbackStatus") or "Unknown"),
        fetched_at=now,
        detection_source=DOTNET_HELPER_SOURCE,
        can_pause=bool(payload.get("canPause")),
        can_play=bool(payload.get("canPlay")),
        can_go_next=bool(payload.get("canGoNext")),
        can_go_previous=bool(payload.get("canGoPrevious")),
        can_seek=bool(payload.get("canSeek")),
        can_toggle_play_pause=bool(payload.get("canTogglePlayPause")),
    )


def _parse_json_lines(output: str) -> dict[str, object] | None:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for raw_line in reversed(lines):
        payload = _parse_json_line(raw_line)
        if isinstance(payload, dict):
            return payload
    return None


def _parse_json_line(raw_line: str) -> dict[str, object] | None:
    try:
        payload = json.loads(raw_line)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
