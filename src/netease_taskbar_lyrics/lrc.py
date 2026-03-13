from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import re


TIMESTAMP_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]")
OFFSET_RE = re.compile(r"\[offset:([+-]?\d+)\]", re.IGNORECASE)


@dataclass(frozen=True)
class LyricLine:
    timestamp_ms: int
    text: str


class LyricTimeline:
    def __init__(self, lines: list[LyricLine]) -> None:
        self.lines = sorted(lines, key=lambda item: item.timestamp_ms)
        self._timestamps = [line.timestamp_ms for line in self.lines]

    @classmethod
    def from_lrc(cls, raw_lrc: str | None) -> "LyricTimeline | None":
        if not raw_lrc:
            return None

        offset_ms = 0
        lines: list[LyricLine] = []

        for raw_line in raw_lrc.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            offset_match = OFFSET_RE.fullmatch(raw_line)
            if offset_match:
                offset_ms = int(offset_match.group(1))
                continue

            timestamps = list(TIMESTAMP_RE.finditer(raw_line))
            if not timestamps:
                continue

            text = TIMESTAMP_RE.sub("", raw_line).strip()
            if not text:
                continue

            for match in timestamps:
                minute = int(match.group(1))
                second = int(match.group(2))
                fraction = match.group(3) or "0"
                fraction_ms = _fraction_to_milliseconds(fraction)
                timestamp_ms = minute * 60_000 + second * 1_000 + fraction_ms + offset_ms
                lines.append(LyricLine(max(timestamp_ms, 0), text))

        if not lines:
            return None
        return cls(lines)

    def line_at(self, position_ms: int) -> str | None:
        if not self.lines:
            return None

        index = bisect_right(self._timestamps, max(position_ms, 0)) - 1
        if index < 0:
            return None
        return self.lines[index].text


def _fraction_to_milliseconds(value: str) -> int:
    if len(value) == 1:
        return int(value) * 100
    if len(value) == 2:
        return int(value) * 10
    return int(value[:3])
