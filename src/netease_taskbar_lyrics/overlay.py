from __future__ import annotations

import ctypes
from ctypes import wintypes
import tkinter as tk
import tkinter.font as tkfont


MAGIC_TRANSPARENT = "#010203"
TEXT_COLOR = "#F5F7FA"
SHADOW_COLOR = "#14161A"
MIN_WIDTH = 260
MAX_WIDTH = 760
PADDING_X = 16
PADDING_Y = 6

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000


user32 = ctypes.windll.user32


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class TaskbarLyricWindow:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", MAGIC_TRANSPARENT)
        self.root.configure(bg=MAGIC_TRANSPARENT)

        self.canvas = tk.Canvas(
            self.root,
            bg=MAGIC_TRANSPARENT,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)

        self.font = tkfont.Font(family="Microsoft YaHei UI", size=16, weight="bold")
        self._shadow_item = self.canvas.create_text(
            0,
            0,
            anchor="nw",
            fill=SHADOW_COLOR,
            font=self.font,
            text="",
        )
        self._text_item = self.canvas.create_text(
            0,
            0,
            anchor="nw",
            fill=TEXT_COLOR,
            font=self.font,
            text="",
        )

        self._width = MIN_WIDTH
        self._height = self.font.metrics("linespace") + PADDING_Y * 2
        self._visible_text = ""
        self._taskbar_signature: tuple[int, int, int, int] | None = None

        self.root.update_idletasks()
        self._enable_click_through()

    def after(self, delay_ms: int, callback) -> None:
        self.root.after(delay_ms, callback)

    def run(self) -> None:
        self.root.mainloop()

    def destroy(self) -> None:
        self.root.destroy()

    def set_text(self, text: str) -> None:
        text = text.strip()
        if not text:
            self.root.withdraw()
            self._visible_text = ""
            return

        display_text = self._fit_text(text)
        if display_text == self._visible_text:
            return

        text_width = self.font.measure(display_text)
        self._width = max(MIN_WIDTH, min(MAX_WIDTH, text_width + PADDING_X * 2))
        self._height = self.font.metrics("linespace") + PADDING_Y * 2

        self.canvas.configure(width=self._width, height=self._height)
        self.canvas.coords(self._shadow_item, PADDING_X + 1, PADDING_Y + 1)
        self.canvas.coords(self._text_item, PADDING_X, PADDING_Y)
        self.canvas.itemconfigure(self._shadow_item, text=display_text)
        self.canvas.itemconfigure(self._text_item, text=display_text)

        self.root.geometry(f"{self._width}x{self._height}+0+0")
        self.reposition(force=True)
        self.root.deiconify()
        self._visible_text = display_text

    def reposition(self, force: bool = False) -> None:
        rect = self._get_taskbar_rect()
        signature = (rect.left, rect.top, rect.right, rect.bottom)
        if not force and signature == self._taskbar_signature:
            return

        x, y = self._compute_window_position(rect)
        self.root.geometry(f"{self._width}x{self._height}+{x}+{y}")
        self._taskbar_signature = signature

    def _fit_text(self, text: str) -> str:
        if self.font.measure(text) <= MAX_WIDTH - PADDING_X * 2:
            return text

        trimmed = text
        while trimmed and self.font.measure(trimmed + "...") > MAX_WIDTH - PADDING_X * 2:
            trimmed = trimmed[:-1]
        return (trimmed + "...") if trimmed else text[:24]

    def _enable_click_through(self) -> None:
        hwnd = self.root.winfo_id()
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

    def _compute_window_position(self, rect: RECT) -> tuple[int, int]:
        screen_width = user32.GetSystemMetrics(0)
        screen_height = user32.GetSystemMetrics(1)

        taskbar_width = rect.right - rect.left
        taskbar_height = rect.bottom - rect.top

        if rect.top >= screen_height // 2:
            x = rect.left + max((taskbar_width - self._width) // 2, 8)
            y = rect.top + max((taskbar_height - self._height) // 2, 0)
            return x, y

        if rect.bottom <= screen_height // 2:
            x = rect.left + max((taskbar_width - self._width) // 2, 8)
            y = rect.top + max((taskbar_height - self._height) // 2, 0)
            return x, y

        if rect.left >= screen_width // 2:
            x = rect.left + max((taskbar_width - self._width) // 2, 0)
            y = rect.top + max((taskbar_height - self._height) // 2, 8)
            return x, y

        x = rect.left + max((taskbar_width - self._width) // 2, 0)
        y = rect.top + max((taskbar_height - self._height) // 2, 8)
        return x, y

    @staticmethod
    def _get_taskbar_rect() -> RECT:
        hwnd = user32.FindWindowW("Shell_TrayWnd", None)
        if not hwnd:
            width = user32.GetSystemMetrics(0)
            height = user32.GetSystemMetrics(1)
            return RECT(0, height - 48, width, height)

        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        return rect
