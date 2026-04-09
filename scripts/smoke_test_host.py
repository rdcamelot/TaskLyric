from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
DLL_CANDIDATES = (
    ROOT / "build-tasklyric" / "host" / "tasklyric_host.dll",
    ROOT / "build" / "host" / "tasklyric_host.dll",
)


def resolve_dll_path() -> Path | None:
    for candidate in DLL_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


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


def main() -> int:
    dll_path = resolve_dll_path()
    if dll_path is None:
        joined = ", ".join(str(path) for path in DLL_CANDIDATES)
        print(f"missing dll: {joined}")
        return 1

    add_mingw_runtime_dir()
    dll = ctypes.WinDLL(str(dll_path))

    dll.tasklyric_initialize.argtypes = [ctypes.c_wchar_p]
    dll.tasklyric_initialize.restype = ctypes.c_int
    dll.tasklyric_shutdown.argtypes = []
    dll.tasklyric_shutdown.restype = ctypes.c_int
    dll.tasklyric_call_native.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    dll.tasklyric_call_native.restype = ctypes.c_int
    dll.tasklyric_get_state_json.argtypes = []
    dll.tasklyric_get_state_json.restype = ctypes.c_wchar_p

    rc = dll.tasklyric_initialize(str(ROOT))
    print(f"initialize={rc}")
    print(
        f"config={dll.tasklyric_call_native('tasklyric.config', '{\"fontSize\":18,\"align\":\"center\",\"themeMode\":\"auto\"}') }"
    )
    print(f"update={dll.tasklyric_call_native('tasklyric.update', '{\"mainText\":\"hello\"}')}")
    print(dll.tasklyric_get_state_json())
    print(f"shutdown={dll.tasklyric_shutdown()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
