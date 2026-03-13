from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DLL_PATH = ROOT / "build" / "host" / "tasklyric_host.dll"
TRANSCRIPT_PATH = ROOT / "state" / "runtime-dev-transcript.json"


def add_mingw_runtime_dir() -> None:
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


def load_dll():
    if not DLL_PATH.exists():
        raise FileNotFoundError(f"missing dll: {DLL_PATH}")

    add_mingw_runtime_dir()
    dll = ctypes.WinDLL(str(DLL_PATH))
    dll.tasklyric_initialize.argtypes = [ctypes.c_wchar_p]
    dll.tasklyric_initialize.restype = ctypes.c_int
    dll.tasklyric_shutdown.argtypes = []
    dll.tasklyric_shutdown.restype = ctypes.c_int
    dll.tasklyric_emit_event.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    dll.tasklyric_emit_event.restype = ctypes.c_int
    dll.tasklyric_call_native.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    dll.tasklyric_call_native.restype = ctypes.c_int
    dll.tasklyric_get_state_json.argtypes = []
    dll.tasklyric_get_state_json.restype = ctypes.c_wchar_p
    return dll


def run_runtime_transcript() -> dict:
    completed = subprocess.run(
        ["node", "scripts/run_runtime_dev.mjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    transcript = json.loads(completed.stdout)
    TRANSCRIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_PATH.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
    return transcript


def replay_into_host(dll, transcript: dict) -> dict:
    init_rc = dll.tasklyric_initialize(str(ROOT))
    if init_rc != 0:
        raise RuntimeError(f"tasklyric_initialize failed: {init_rc}")

    for entry in transcript.get("logs", []):
        dll.tasklyric_emit_event("runtime.log", json.dumps(entry, ensure_ascii=False))

    for event in transcript.get("events", []):
        dll.tasklyric_emit_event(event["name"], json.dumps(event["payload"], ensure_ascii=False))

    for call in transcript.get("nativeCalls", []):
        dll.tasklyric_call_native(call["method"], json.dumps(call["payload"], ensure_ascii=False))

    host_state = json.loads(dll.tasklyric_get_state_json())
    dll.tasklyric_shutdown()
    return host_state


def main() -> int:
    transcript = run_runtime_transcript()
    dll = load_dll()
    host_state = replay_into_host(dll, transcript)

    summary = {
        "runtimeState": transcript.get("runtimeState"),
        "hostState": host_state,
        "logCount": len(transcript.get("logs", [])),
        "eventCount": len(transcript.get("events", [])),
        "nativeCallCount": len(transcript.get("nativeCalls", [])),
        "transcriptPath": str(TRANSCRIPT_PATH),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
