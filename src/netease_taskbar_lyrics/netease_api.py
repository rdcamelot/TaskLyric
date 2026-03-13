from __future__ import annotations

from dataclasses import dataclass
import json
from threading import Lock
from typing import Any
from urllib import parse, request

from .lrc import LyricTimeline


SEARCH_ENDPOINTS = (
    "https://music.163.com/api/search/get/web",
    "https://music.163.com/api/cloudsearch/pc",
)
LYRIC_ENDPOINT = "https://music.163.com/api/song/lyric"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/133.0.0.0 Safari/537.36"
    ),
    "Referer": "https://music.163.com/",
    "Origin": "https://music.163.com",
    "Accept": "application/json, text/plain, */*",
}


@dataclass(frozen=True)
class TrackCandidate:
    song_id: int
    name: str
    artists: tuple[str, ...]


class NeteaseLyricClient:
    def __init__(self) -> None:
        self._timeline_cache: dict[tuple[str, str], LyricTimeline | None] = {}
        self._lock = Lock()

    def get_timeline(self, title: str, artist: str) -> LyricTimeline | None:
        cache_key = (_normalize(title), _normalize(artist))

        with self._lock:
            if cache_key in self._timeline_cache:
                return self._timeline_cache[cache_key]

        candidate = self._search_best_match(title, artist)
        timeline = self._fetch_timeline(candidate.song_id) if candidate else None

        with self._lock:
            self._timeline_cache[cache_key] = timeline

        return timeline

    def _search_best_match(self, title: str, artist: str) -> TrackCandidate | None:
        payload = {
            "s": f"{title} {artist}".strip(),
            "type": "1",
            "offset": "0",
            "limit": "10",
        }

        for endpoint in SEARCH_ENDPOINTS:
            try:
                data = _post_json(endpoint, payload)
            except Exception:
                continue

            songs = data.get("result", {}).get("songs", [])
            if not songs:
                continue

            ranked = sorted(
                (_to_candidate(song) for song in songs),
                key=lambda item: self._score_candidate(item, title, artist),
                reverse=True,
            )
            return ranked[0] if ranked else None

        return None

    def _fetch_timeline(self, song_id: int) -> LyricTimeline | None:
        query = parse.urlencode({"id": song_id, "lv": 1, "kv": 1, "tv": -1})
        url = f"{LYRIC_ENDPOINT}?{query}"
        data = _get_json(url)
        raw_lrc = data.get("lrc", {}).get("lyric")
        return LyricTimeline.from_lrc(raw_lrc)

    @staticmethod
    def _score_candidate(candidate: TrackCandidate, title: str, artist: str) -> int:
        expected_title = _normalize(title)
        expected_artist = _normalize(artist)
        song_name = _normalize(candidate.name)
        artists = [_normalize(name) for name in candidate.artists]

        score = 0
        if song_name == expected_title:
            score += 12
        elif expected_title and expected_title in song_name:
            score += 6

        if expected_artist:
            if expected_artist in artists:
                score += 12
            elif any(expected_artist in name or name in expected_artist for name in artists):
                score += 7

        if len(candidate.artists) == 1:
            score += 1

        return score


def _to_candidate(song: dict[str, Any]) -> TrackCandidate:
    artists = song.get("artists") or song.get("ar") or []
    artist_names = tuple(item.get("name", "") for item in artists if item.get("name"))
    return TrackCandidate(
        song_id=int(song["id"]),
        name=str(song.get("name", "")),
        artists=artist_names,
    )


def _post_json(url: str, data: dict[str, Any]) -> dict[str, Any]:
    body = parse.urlencode(data).encode("utf-8")
    req = request.Request(url, data=body, headers=DEFAULT_HEADERS, method="POST")
    with request.urlopen(req, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str) -> dict[str, Any]:
    req = request.Request(url, headers=DEFAULT_HEADERS, method="GET")
    with request.urlopen(req, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def _normalize(value: str) -> str:
    keep = []
    for char in value.lower():
        if char.isalnum():
            keep.append(char)
    return "".join(keep)
