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


@dataclass(frozen=True)
class LyricBundle:
    song_id: int
    title: str
    artist: str
    main_timeline: LyricTimeline | None
    translation_timeline: LyricTimeline | None


class NeteaseLyricClient:
    def __init__(self) -> None:
        self._bundle_cache: dict[tuple[str, str], LyricBundle | None] = {}
        self._lock = Lock()

    def get_bundle(self, title: str, artist: str) -> LyricBundle | None:
        cache_key = ("track", f"{_normalize(title)}::{_normalize(artist)}")

        with self._lock:
            if cache_key in self._bundle_cache:
                return self._bundle_cache[cache_key]

        candidate = self._search_best_match(title, artist)
        bundle = self._fetch_bundle(candidate) if candidate else None

        with self._lock:
            self._bundle_cache[cache_key] = bundle

        return bundle

    def get_bundle_by_song_id(self, song_id: int, *, title_hint: str = "", artist_hint: str = "") -> LyricBundle | None:
        if song_id <= 0:
            return None

        cache_key = ("song_id", str(int(song_id)))
        with self._lock:
            if cache_key in self._bundle_cache:
                return self._bundle_cache[cache_key]

        bundle = self._fetch_bundle_by_song_id(song_id, title_hint=title_hint, artist_hint=artist_hint)
        with self._lock:
            self._bundle_cache[cache_key] = bundle
        return bundle

    def get_timeline(self, title: str, artist: str) -> LyricTimeline | None:
        bundle = self.get_bundle(title, artist)
        return bundle.main_timeline if bundle else None

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

    def _fetch_bundle(self, candidate: TrackCandidate) -> LyricBundle | None:
        query = parse.urlencode({"id": candidate.song_id, "lv": 1, "kv": 1, "tv": -1})
        url = f"{LYRIC_ENDPOINT}?{query}"
        data = _get_json(url)
        return _bundle_from_lyric_payload(
            data,
            song_id=candidate.song_id,
            title_hint=candidate.name,
            artist_hint=" / ".join(candidate.artists),
        )

    def _fetch_bundle_by_song_id(self, song_id: int, *, title_hint: str, artist_hint: str) -> LyricBundle | None:
        query = parse.urlencode({"id": int(song_id), "lv": 1, "kv": 1, "tv": -1})
        url = f"{LYRIC_ENDPOINT}?{query}"
        data = _get_json(url)
        return _bundle_from_lyric_payload(
            data,
            song_id=int(song_id),
            title_hint=title_hint,
            artist_hint=artist_hint,
        )

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


def _bundle_from_lyric_payload(
    data: dict[str, Any],
    *,
    song_id: int,
    title_hint: str,
    artist_hint: str,
) -> LyricBundle | None:
    raw_lrc = data.get("lrc", {}).get("lyric")
    raw_tlrc = data.get("tlyric", {}).get("lyric")
    main_timeline = LyricTimeline.from_lrc(raw_lrc)
    translation_timeline = LyricTimeline.from_lrc(raw_tlrc)
    if not main_timeline and not translation_timeline:
        return None

    return LyricBundle(
        song_id=int(song_id),
        title=title_hint,
        artist=artist_hint,
        main_timeline=main_timeline,
        translation_timeline=translation_timeline,
    )


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
