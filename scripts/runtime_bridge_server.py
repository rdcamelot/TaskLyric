from __future__ import annotations

import argparse
import atexit
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
from urllib import parse, request


ROOT = Path(__file__).resolve().parents[1]
DLL_PATH = ROOT / "build" / "host" / "tasklyric_host.dll"
FIXTURE_SONG_DETAIL = ROOT / "fixtures" / "sample_song_detail.json"
FIXTURE_LYRIC = ROOT / "fixtures" / "sample_lyric.json"


class HostBridge:
    def __init__(self, use_fixtures: bool) -> None:
        self.use_fixtures = use_fixtures
        self._config_store: dict[str, Any] = {}
        self._dll = self._load_dll()
        self._bind_signatures()
        rc = self._dll.tasklyric_initialize(str(ROOT))
        if rc != 0:
            raise RuntimeError(f"tasklyric_initialize failed: {rc}")
        atexit.register(self._shutdown)

    def dispatch(self, method: str, params: dict[str, Any]) -> Any:
        if method == "call_native":
            return self._call_native(params["method"], params["payload"])
        if method == "emit_event":
            return self._emit_event(params["name"], params["payload"])
        if method == "get_state":
            return json.loads(self._dll.tasklyric_get_state_json())
        if method == "fetch_json":
            return self._fetch_json(params["url"], params.get("init") or {})
        if method == "get_config":
            return self._config_store.get(params["key"], params.get("default"))
        if method == "set_config":
            self._config_store[params["key"]] = params["value"]
            return self._config_store[params["key"]]
        if method == "log":
            return self._log(params["level"], params["message"], params.get("meta"))
        raise ValueError(f"unknown method: {method}")

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

    def _add_mingw_runtime_dir(self) -> None:
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

    def _call_native(self, method: str, payload: Any) -> int:
        raw = json.dumps(payload, ensure_ascii=False)
        return int(self._dll.tasklyric_call_native(method, raw))

    def _emit_event(self, name: str, payload: Any) -> int:
        raw = json.dumps(payload, ensure_ascii=False)
        return int(self._dll.tasklyric_emit_event(name, raw))

    def _fetch_json(self, url: str, init: dict[str, Any]) -> Any:
        if self.use_fixtures:
            return self._fetch_fixture(url)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/133.0.0.0 Safari/537.36"
            )
        }
        headers.update(init.get("headers") or {})
        req = request.Request(url, headers=headers, method=init.get("method") or "GET")
        with request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _fetch_fixture(self, url: str) -> Any:
        parsed = parse.urlparse(url)
        if parsed.path.endswith("/api/song/detail"):
            return json.loads(FIXTURE_SONG_DETAIL.read_text(encoding="utf-8"))
        if parsed.path.endswith("/api/song/lyric/v1"):
            return json.loads(FIXTURE_LYRIC.read_text(encoding="utf-8"))
        raise ValueError(f"no fixture for url: {url}")

    def _log(self, level: str, message: str, meta: Any) -> int:
        payload = {
            "level": level,
            "message": message,
            "meta": meta,
        }
        return self._emit_event("runtime.log", payload)

    def _shutdown(self) -> None:
        try:
            self._dll.tasklyric_shutdown()
        except Exception:
            return


def serve(use_fixtures: bool) -> int:
    bridge = HostBridge(use_fixtures=use_fixtures)
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        request_obj: dict[str, Any] | None = None
        try:
            request_obj = json.loads(raw_line)
            response_obj = {
                "id": request_obj.get("id"),
                "ok": True,
                "result": bridge.dispatch(request_obj["method"], request_obj.get("params") or {}),
            }
        except Exception as exc:
            response_obj = {
                "id": request_obj.get("id") if request_obj else None,
                "ok": False,
                "error": str(exc),
            }

        sys.stdout.write(json.dumps(response_obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="use real network requests instead of local fixtures")
    args = parser.parse_args()
    return serve(use_fixtures=not args.live)


if __name__ == "__main__":
    raise SystemExit(main())
