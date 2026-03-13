from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import json
import os
from pathlib import Path
import time


IGNORED_WINDOW_TITLES = {"", "桌面歌词", "迷你播放器", "网易云音乐"}
TRACK_TITLE_SEPARATORS = (" - ", " — ", " – ")
LOCAL_PLAYING_LIST_PATH = Path(os.environ.get("LOCALAPPDATA", "")) / "NetEase" / "CloudMusic" / "webdata" / "file" / "playingList"


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
user32.keybd_event.restype = None

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WM_APPCOMMAND = 0x0319
KEYEVENTF_KEYUP = 0x0002
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3
APPCOMMAND_MEDIA_NEXTTRACK = 11
APPCOMMAND_MEDIA_PREVIOUSTRACK = 12
APPCOMMAND_MEDIA_PLAY_PAUSE = 14
APPCOMMAND_MEDIA_PLAY = 46
APPCOMMAND_MEDIA_PAUSE = 47

ACTION_TO_APPCOMMAND = {
    "next": APPCOMMAND_MEDIA_NEXTTRACK,
    "previous": APPCOMMAND_MEDIA_PREVIOUSTRACK,
    "toggle-play-pause": APPCOMMAND_MEDIA_PLAY_PAUSE,
    "play": APPCOMMAND_MEDIA_PLAY,
    "pause": APPCOMMAND_MEDIA_PAUSE,
}

ACTION_TO_MEDIA_KEY = {
    "next": VK_MEDIA_NEXT_TRACK,
    "previous": VK_MEDIA_PREV_TRACK,
    "toggle-play-pause": VK_MEDIA_PLAY_PAUSE,
    "play": VK_MEDIA_PLAY_PAUSE,
    "pause": VK_MEDIA_PLAY_PAUSE,
}

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
QueryFullProcessImageNameW = kernel32.QueryFullProcessImageNameW
QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
QueryFullProcessImageNameW.restype = wintypes.BOOL


@dataclass(frozen=True)
class CloudMusicTrack:
    title: str
    artist: str
    song_id: int
    duration_ms: int
    source_window_class: str
    source_window_title: str


@dataclass(frozen=True)
class _WindowInfo:
    hwnd: int
    process_id: int
    visible: bool
    class_name: str
    title: str


@dataclass(frozen=True)
class _PlaylistTrack:
    song_id: int
    title: str
    artist: str
    duration_ms: int


class CloudMusicWindowProbe:
    def __init__(self) -> None:
        self._playlist_mtime_ns = -1
        self._playlist_cache: list[_PlaylistTrack] = []

    def get_current_track(self) -> CloudMusicTrack | None:
        windows = self._enumerate_cloudmusic_windows()
        candidate = self._pick_title_window(windows)
        if candidate is None:
            return None

        parsed = _parse_track_title(candidate.title)
        if parsed is None:
            return None
        title, artist = parsed

        playlist_track = self._match_playing_list(title, artist)
        song_id = playlist_track.song_id if playlist_track else 0
        duration_ms = playlist_track.duration_ms if playlist_track else 0
        if playlist_track and playlist_track.title:
            title = playlist_track.title
        if playlist_track and playlist_track.artist:
            artist = playlist_track.artist

        return CloudMusicTrack(
            title=title,
            artist=artist,
            song_id=song_id,
            duration_ms=duration_ms,
            source_window_class=candidate.class_name,
            source_window_title=candidate.title,
        )

    def matches_current_track(self, title: str, artist: str) -> bool:
        track = self.get_current_track()
        if track is None:
            return False

        expected_title = _normalize(title)
        expected_artist = _normalize(artist)
        track_title = _normalize(track.title)
        track_artist = _normalize(track.artist)
        if not expected_title or track_title != expected_title:
            return False
        if expected_artist and track_artist and track_artist != expected_artist:
            return expected_artist in track_artist or track_artist in expected_artist
        return True

    def send_media_command(self, action: str) -> bool:
        normalized = action.strip().lower()
        app_command = ACTION_TO_APPCOMMAND.get(normalized)
        target_window = self._pick_control_window(self._enumerate_cloudmusic_windows())

        if app_command is not None and target_window is not None:
            lparam = app_command << 16
            user32.SendMessageW(target_window.hwnd, WM_APPCOMMAND, target_window.hwnd, lparam)
            return True

        media_key = ACTION_TO_MEDIA_KEY.get(normalized)
        if media_key is None:
            return False

        user32.keybd_event(media_key, 0, 0, 0)
        time.sleep(0.02)
        user32.keybd_event(media_key, 0, KEYEVENTF_KEYUP, 0)
        return True

    def _enumerate_cloudmusic_windows(self) -> list[_WindowInfo]:
        rows: list[_WindowInfo] = []
        exe_cache: dict[int, str] = {}

        @EnumWindowsProc
        def callback(hwnd: int, lparam: int) -> bool:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            process_id = int(pid.value)
            if process_id <= 0:
                return True

            process_name = exe_cache.get(process_id)
            if process_name is None:
                process_name = _query_process_name(process_id)
                exe_cache[process_id] = process_name
            if process_name != "cloudmusic.exe":
                return True

            rows.append(
                _WindowInfo(
                    hwnd=int(hwnd),
                    process_id=process_id,
                    visible=bool(user32.IsWindowVisible(hwnd)),
                    class_name=_window_class_name(hwnd),
                    title=_window_text(hwnd),
                )
            )
            return True

        user32.EnumWindows(callback, 0)
        return rows

    @staticmethod
    def _pick_title_window(windows: list[_WindowInfo]) -> _WindowInfo | None:
        scored: list[tuple[int, _WindowInfo]] = []
        for window in windows:
            title = window.title.strip()
            if title in IGNORED_WINDOW_TITLES:
                continue
            score = 0
            if window.class_name == "OrpheusBrowserHost":
                score += 50
            elif window.class_name == "icon":
                score += 30
            elif window.class_name == "MiniPlayer":
                score += 10
            if window.visible:
                score += 10
            if " - " in title or " — " in title or " – " in title:
                score += 6
            score += min(len(title), 40)
            scored.append((score, window))

        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]

    @staticmethod
    def _pick_control_window(windows: list[_WindowInfo]) -> _WindowInfo | None:
        visible_windows = [window for window in windows if window.visible]
        for class_name in ("OrpheusBrowserHost", "MiniPlayer", "icon"):
            for window in visible_windows:
                if window.class_name == class_name:
                    return window
        return CloudMusicWindowProbe._pick_title_window(windows)

    def _match_playing_list(self, title: str, artist: str) -> _PlaylistTrack | None:
        tracks = self._load_playing_list()
        if not tracks:
            return None

        expected_title = _normalize(title)
        expected_artist = _normalize(artist)
        ranked = sorted(
            tracks,
            key=lambda item: _score_playlist_track(item, expected_title, expected_artist),
            reverse=True,
        )
        best = ranked[0]
        if _score_playlist_track(best, expected_title, expected_artist) <= 0:
            return None
        return best

    def _load_playing_list(self) -> list[_PlaylistTrack]:
        path = LOCAL_PLAYING_LIST_PATH
        try:
            stat = path.stat()
        except OSError:
            self._playlist_cache = []
            self._playlist_mtime_ns = -1
            return []

        if stat.st_mtime_ns == self._playlist_mtime_ns:
            return self._playlist_cache

        data = None
        for encoding in ("utf-8", "utf-8-sig"):
            try:
                data = json.loads(path.read_text(encoding=encoding))
                break
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
        if not isinstance(data, dict):
            self._playlist_cache = []
            self._playlist_mtime_ns = stat.st_mtime_ns
            return []

        parsed: list[_PlaylistTrack] = []
        for item in data.get("list", []):
            track = item.get("track") or {}
            title = str(track.get("name") or "").strip()
            artists = track.get("artists") or track.get("ar") or []
            artist_names = [str(artist.get("name") or "").strip() for artist in artists if artist.get("name")]
            if not title:
                continue
            parsed.append(
                _PlaylistTrack(
                    song_id=int(track.get("id") or item.get("id") or 0),
                    title=title,
                    artist=" / ".join(name for name in artist_names if name),
                    duration_ms=int(track.get("duration") or track.get("dt") or 0),
                )
            )

        self._playlist_cache = parsed
        self._playlist_mtime_ns = stat.st_mtime_ns
        return parsed


def _query_process_name(process_id: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return buffer.value.rsplit("\\", 1)[-1].lower()
    finally:
        kernel32.CloseHandle(handle)


def _window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(max(length + 2, 512))
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value.strip()


def _window_class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, len(buffer))
    return buffer.value.strip()


def _parse_track_title(raw: str) -> tuple[str, str] | None:
    value = raw.strip()
    if not value or value in IGNORED_WINDOW_TITLES:
        return None
    for separator in TRACK_TITLE_SEPARATORS:
        if separator in value:
            title, artist = value.rsplit(separator, 1)
            title = title.strip()
            artist = artist.strip()
            if title:
                return title, artist
    return value, ""


def _score_playlist_track(track: _PlaylistTrack, expected_title: str, expected_artist: str) -> int:
    if not expected_title:
        return 0

    title = _normalize(track.title)
    artist = _normalize(track.artist)
    score = 0
    if title == expected_title:
        score += 20
    elif expected_title in title or title in expected_title:
        score += 10

    if expected_artist:
        if artist == expected_artist:
            score += 20
        elif expected_artist in artist or artist in expected_artist:
            score += 9
    return score


def _normalize(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())
