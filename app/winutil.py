"""Thin ctypes helpers: foreground window, click-through, DPI, global hotkeys."""

from __future__ import annotations

import ctypes
import os
import queue
import threading
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

_MODIFIERS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
}

_GetWindowLongPtr = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
_SetWindowLongPtr = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
_GetWindowLongPtr.restype = ctypes.c_ssize_t
_GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
_SetWindowLongPtr.restype = ctypes.c_ssize_t
_SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]


# --------------------------------------------------------------------- #
# foreground window
# --------------------------------------------------------------------- #
def foreground_process() -> tuple[int, str, str]:
    """(pid, exe_name, window_title) of the window in the foreground."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return 0, "", ""

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 2)
    user32.GetWindowTextW(hwnd, buffer, length + 2)
    title = buffer.value

    return int(pid.value), _process_name(int(pid.value)), title


def _process_name(pid: int) -> str:
    if not pid:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return os.path.basename(buffer.value)
    finally:
        kernel32.CloseHandle(handle)
    return ""


def is_own_process(pid: int) -> bool:
    return pid == os.getpid()


# --------------------------------------------------------------------- #
# window styles
# --------------------------------------------------------------------- #
def set_click_through(hwnd: int, enabled: bool) -> None:
    style = _GetWindowLongPtr(wintypes.HWND(hwnd), GWL_EXSTYLE)
    if enabled:
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
    else:
        style &= ~(WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
        style |= WS_EX_LAYERED | WS_EX_TOOLWINDOW
    _SetWindowLongPtr(wintypes.HWND(hwnd), GWL_EXSTYLE, style)


def make_tool_window(hwnd: int) -> None:
    """Keep the HUD out of the alt-tab list and the taskbar."""
    style = _GetWindowLongPtr(wintypes.HWND(hwnd), GWL_EXSTYLE)
    style |= WS_EX_TOOLWINDOW | WS_EX_LAYERED
    _SetWindowLongPtr(wintypes.HWND(hwnd), GWL_EXSTYLE, style)


def set_dpi_awareness() -> None:
    """Crisp HUD text on scaled displays."""
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def virtual_screen_size() -> tuple[int, int]:
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


# --------------------------------------------------------------------- #
# global hotkeys
# --------------------------------------------------------------------- #
def parse_hotkey(spec: str) -> tuple[int, int] | None:
    """'ctrl+alt+o' -> (modifiers, virtual key code)."""
    if not spec:
        return None
    parts = [p.strip().lower() for p in spec.replace(" ", "").split("+") if p.strip()]
    if not parts:
        return None
    key = parts[-1]
    mods = 0
    for part in parts[:-1]:
        mods |= _MODIFIERS.get(part, 0)
    if len(key) == 1:
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit():
        vk = 0x70 + int(key[1:]) - 1  # VK_F1
    else:
        vk = {"insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23}.get(key, 0)
    if not vk:
        return None
    return mods | MOD_NOREPEAT, vk


class HotkeyManager:
    """Registers global hotkeys and hands their ids to the UI thread."""

    def __init__(self) -> None:
        self.events: queue.Queue[str] = queue.Queue()
        self._bindings: dict[int, str] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.errors: list[str] = []

    def start(self, bindings: dict[str, str]) -> None:
        """bindings: {name: hotkey_spec}"""
        parsed: dict[int, str] = {}
        for name, spec in bindings.items():
            combo = parse_hotkey(spec)
            if combo is None:
                continue
            mods, vk = combo
            parsed[(mods << 16) | vk] = name
        self._bindings = {ident: name for ident, name in parsed.items()}
        self._thread = threading.Thread(target=self._pump, args=(parsed,), daemon=True)
        self._thread.start()

    def _pump(self, parsed: dict[int, str]) -> None:
        registered: list[int] = []
        for index, (ident, name) in enumerate(parsed.items(), start=1):
            mods, vk = ident >> 16, ident & 0xFFFF
            if user32.RegisterHotKey(None, index, mods, vk):
                registered.append(index)
            else:
                self.errors.append(f"{name} ({mods:#x}+{vk}) already taken")
        self._ids = {index: parsed[ident] for index, ident in enumerate(parsed, start=1)}

        msg = wintypes.MSG()
        while not self._stop.is_set():
            # PeekMessage keeps the thread responsive to the stop flag.
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                if msg.message == WM_HOTKEY:
                    name = self._ids.get(int(msg.wParam))
                    if name:
                        self.events.put(name)
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.03)

        for index in registered:
            user32.UnregisterHotKey(None, index)

    def poll(self) -> list[str]:
        fired: list[str] = []
        while True:
            try:
                fired.append(self.events.get_nowait())
            except queue.Empty:
                return fired

    def stop(self) -> None:
        self._stop.set()
