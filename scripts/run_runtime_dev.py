from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time


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


def replay_into_host(dll, transcript: dict, step_delay_ms: int = 0, hold_seconds: float = 0.0) -> dict:
    init_rc = dll.tasklyric_initialize(str(ROOT))
    if init_rc != 0:
        raise RuntimeError(f"tasklyric_initialize failed: {init_rc}")

    step_delay = max(0, step_delay_ms) / 1000.0

    for entry in transcript.get("logs", []):
        dll.tasklyric_emit_event("runtime.log", json.dumps(entry, ensure_ascii=False))
        if step_delay:
            time.sleep(step_delay)

    for event in transcript.get("events", []):
        dll.tasklyric_emit_event(event["name"], json.dumps(event["payload"], ensure_ascii=False))
        if step_delay:
            time.sleep(step_delay)

    for call in transcript.get("nativeCalls", []):
        dll.tasklyric_call_native(call["method"], json.dumps(call["payload"], ensure_ascii=False))
        if step_delay:
            time.sleep(step_delay)

    if hold_seconds > 0:
        time.sleep(hold_seconds)

    host_state = json.loads(dll.tasklyric_get_state_json())
    dll.tasklyric_shutdown()
    return host_state


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay the TaskLyric runtime transcript into the host DLL.")
    parser.add_argument("--step-delay-ms", type=int, default=0, help="Delay between replayed events and native calls.")
    parser.add_argument("--hold-seconds", type=float, default=0.0, help="Keep the native window visible before shutdown.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    transcript = run_runtime_transcript()
    dll = load_dll()
    host_state = replay_into_host(
        dll,
        transcript,
        step_delay_ms=args.step_delay_ms,
        hold_seconds=args.hold_seconds,
    )

    summary = {
        "runtimeState": transcript.get("runtimeState"),
        "hostState": host_state,
        "logCount": len(transcript.get("logs", [])),
        "eventCount": len(transcript.get("events", [])),
        "nativeCallCount": len(transcript.get("nativeCalls", [])),
        "transcriptPath": str(TRANSCRIPT_PATH),
        "stepDelayMs": args.step_delay_ms,
        "holdSeconds": args.hold_seconds,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
