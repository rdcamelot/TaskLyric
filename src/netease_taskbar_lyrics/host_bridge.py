from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DLL_PATH = ROOT / "build" / "host" / "tasklyric_host.dll"

DEFAULT_CONFIG: dict[str, Any] = {
    "showTranslation": True,
    "fontFamily": "Segoe UI Variable Text",
    "fontSize": 18,
    "color": "#F8FAFC",
    "subColor": "#AEB8C5",
    "shadowColor": "#05070B",
    "themeMode": "auto",
    "align": "center",
}


class HostTaskbarBridge:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.root = ROOT
        self.config = dict(DEFAULT_CONFIG)
        if config:
            self.config.update(config)
        self._dll = self._load_dll()
        self._bind_signatures()
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        rc = int(self._dll.tasklyric_initialize(str(self.root)))
        if rc != 0:
            raise RuntimeError(f"tasklyric_initialize failed: {rc}")
        self._started = True
        self.call_native("tasklyric.config", self.config)

    def shutdown(self) -> None:
        if not self._started:
            return
        self._dll.tasklyric_shutdown()
        self._started = False

    def set_config(self, patch: dict[str, Any]) -> None:
        self.config.update(patch)
        self.call_native("tasklyric.config", self.config)

    def update_lyric(
        self,
        *,
        title: str,
        artist: str,
        main_text: str,
        sub_text: str,
        progress_ms: int,
        playback_state: str,
        track_id: int = 0,
    ) -> int:
        payload = {
            "trackId": int(track_id or 0),
            "title": title,
            "artist": artist,
            "mainText": main_text,
            "subText": sub_text,
            "progressMs": max(0, int(progress_ms or 0)),
            "playbackState": playback_state or "unknown",
        }
        return self.call_native("tasklyric.update", payload)

    def emit_event(self, name: str, payload: Any) -> int:
        if not self._started:
            return 0
        raw = json.dumps(payload, ensure_ascii=False)
        return int(self._dll.tasklyric_emit_event(name, raw))

    def call_native(self, method: str, payload: Any) -> int:
        if not self._started:
            return 0
        raw = json.dumps(payload, ensure_ascii=False)
        return int(self._dll.tasklyric_call_native(method, raw))

    def take_pending_command(self) -> dict[str, Any] | None:
        if not self._started:
            return None
        raw = self._dll.tasklyric_take_pending_command_json()
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def state(self) -> dict[str, Any]:
        if not self._started:
            return {}
        return json.loads(self._dll.tasklyric_get_state_json())

    def _load_dll(self):
        if not DLL_PATH.exists():
            raise FileNotFoundError(f"missing dll: {DLL_PATH}")
        self._add_mingw_runtime_dir()
        return ctypes.WinDLL(str(DLL_PATH))

    def _bind_signatures(self) -> None:
        self._dll.tasklyric_initialize.argtypes = [ctypes.c_wchar_p]
        self._dll.tasklyric_initialize.restype = ctypes.c_int
        self._dll.tasklyric_shutdown.argtypes = []
        self._dll.tasklyric_shutdown.restype = ctypes.c_int
        self._dll.tasklyric_emit_event.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        self._dll.tasklyric_emit_event.restype = ctypes.c_int
        self._dll.tasklyric_call_native.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        self._dll.tasklyric_call_native.restype = ctypes.c_int
        self._dll.tasklyric_get_state_json.argtypes = []
        self._dll.tasklyric_get_state_json.restype = ctypes.c_wchar_p
        self._dll.tasklyric_take_pending_command_json.argtypes = []
        self._dll.tasklyric_take_pending_command_json.restype = ctypes.c_wchar_p

    @staticmethod
    def _add_mingw_runtime_dir() -> None:
        try:
            result = subprocess.run(
                ["where", "g++"],
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return

        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            return

        runtime_dir = Path(lines[0]).resolve().parent
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(runtime_dir))
