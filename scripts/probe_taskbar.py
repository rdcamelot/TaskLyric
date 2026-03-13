from __future__ import annotations

import argparse
import ctypes
import json
from ctypes import wintypes


WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
SMTO_ABORTIFHUNG = 0x0002
SMTO_BLOCK = 0x0001


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


user32 = ctypes.WinDLL("user32", use_last_error=True)
EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.EnumChildWindows.argtypes = [wintypes.HWND, EnumChildProc, wintypes.LPARAM]
user32.EnumChildWindows.restype = wintypes.BOOL
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_size_t),
]
user32.SendMessageTimeoutW.restype = wintypes.LPARAM


def safe_get_class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, len(buffer))
    return buffer.value


def safe_get_window_text(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def safe_get_wm_text(hwnd: int) -> str:
    length_result = ctypes.c_size_t(0)
    ok = user32.SendMessageTimeoutW(
        hwnd,
        WM_GETTEXTLENGTH,
        0,
        0,
        SMTO_ABORTIFHUNG | SMTO_BLOCK,
        80,
        ctypes.byref(length_result),
    )
    if not ok:
        return ""

    length = int(length_result.value)
    if length <= 0:
        return ""

    buffer = ctypes.create_unicode_buffer(length + 1)
    copied = ctypes.c_size_t(0)
    ok = user32.SendMessageTimeoutW(
        hwnd,
        WM_GETTEXT,
        length + 1,
        wintypes.LPARAM(ctypes.addressof(buffer)),
        SMTO_ABORTIFHUNG | SMTO_BLOCK,
        120,
        ctypes.byref(copied),
    )
    if not ok:
        return ""
    return buffer.value


def get_window_rect(hwnd: int) -> list[int]:
    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return [0, 0, 0, 0]
    return [rect.left, rect.top, rect.right, rect.bottom]


def get_process_id(hwnd: int) -> int:
    process_id = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    return int(process_id.value)


def enum_children(parent: int, depth: int, max_depth: int, rows: list[dict]) -> None:
    def callback(hwnd: int, lparam: int) -> bool:
        class_name = safe_get_class_name(hwnd)
        title = safe_get_window_text(hwnd)
        wm_text = safe_get_wm_text(hwnd)
        row = {
            "depth": depth,
            "hwnd": hex(hwnd),
            "class": class_name,
            "title": title,
            "wmText": wm_text,
            "visible": bool(user32.IsWindowVisible(hwnd)),
            "rect": get_window_rect(hwnd),
            "pid": get_process_id(hwnd),
        }
        rows.append(row)
        if depth < max_depth:
            enum_children(hwnd, depth + 1, max_depth, rows)
        return True

    user32.EnumChildWindows(parent, EnumChildProc(callback), 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enumerate the Windows taskbar window tree.")
    parser.add_argument("--max-depth", type=int, default=2, help="Recursive depth for child enumeration.")
    parser.add_argument("--include-invisible", action="store_true", help="Include invisible windows in the output.")
    parser.add_argument("--all", action="store_true", help="Print the full tree instead of the filtered view.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    taskbar = user32.FindWindowW("Shell_TrayWnd", None)
    if not taskbar:
        raise SystemExit("Shell_TrayWnd not found")

    rows: list[dict] = []
    root = {
        "depth": 0,
        "hwnd": hex(taskbar),
        "class": safe_get_class_name(taskbar),
        "title": safe_get_window_text(taskbar),
        "wmText": safe_get_wm_text(taskbar),
        "visible": bool(user32.IsWindowVisible(taskbar)),
        "rect": get_window_rect(taskbar),
        "pid": get_process_id(taskbar),
    }
    rows.append(root)
    enum_children(taskbar, 1, max(1, args.max_depth), rows)

    if not args.include_invisible:
        rows = [row for row in rows if row["visible"]]

    if not args.all:
        interesting_classes = {
            "Shell_TrayWnd",
            "Start",
            "TrayNotifyWnd",
            "ReBarWindow32",
            "MSTaskSwWClass",
            "MSTaskListWClass",
            "TaskLyric.TaskbarWindow",
            "Windows.UI.Composition.DesktopWindowContentBridge",
            "Windows.UI.Core.CoreWindow",
        }
        rows = [
            row for row in rows
            if row["class"] in interesting_classes or row["title"] or row["wmText"]
        ]

    print(json.dumps({"count": len(rows), "windows": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

