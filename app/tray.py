"""System tray icon, implemented directly on Shell_NotifyIcon.

Why not pystray: the portable build must stay dependency-free (no pip, no
Pillow), and the tray needs very little - an icon, a tooltip and a context
menu. The icon window lives on its own thread with its own message loop and
communicates with the Tk main loop through a queue, mirroring HotkeyManager.
"""

from __future__ import annotations

import ctypes
import queue
import threading
from ctypes import wintypes
from pathlib import Path
from typing import Callable

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1
WM_TIMER = 0x0113
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_NULL = 0x0000
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010

NIIF_INFO = 0x00000001
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
SM_CXSMICON = 49
SM_CYSMICON = 50

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_CHECKED = 0x00000008
MF_GRAYED = 0x00000001
TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002
TPM_NONOTIFY = 0x0080

IDI_APPLICATION = 32512

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_byte * 8),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


user32.CreatePopupMenu.restype = wintypes.HMENU
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.LoadImageW.restype = wintypes.HANDLE
user32.LoadImageW.argtypes = [
    wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
user32.LoadIconW.restype = wintypes.HICON
user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
user32.RegisterClassExW.restype = wintypes.ATOM
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.AppendMenuW.restype = wintypes.BOOL
user32.TrackPopupMenu.restype = wintypes.BOOL
user32.TrackPopupMenu.argtypes = [
    wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, wintypes.HWND, wintypes.LPVOID,
]
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID]
user32.SetTimer.restype = ctypes.c_size_t
user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.RegisterWindowMessageW.restype = wintypes.UINT
user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]

# MAKEINTRESOURCE: LoadIconW wants a pointer, the low word carries the id.
IDI_APPLICATION_PTR = ctypes.cast(ctypes.c_void_p(IDI_APPLICATION), wintypes.LPCWSTR)

CLASS_NAME = "FpsMonitorTrayWindow"

# Menu item id -> action name. Passed straight through to the UI thread.
ACTION_SHOW = 1
ACTION_OVERLAY = 2
ACTION_CLICKS = 3
ACTION_QUIT = 4


class TrayIcon:
    """Tray icon with a context menu; actions are polled by the Tk main loop."""

    def __init__(
        self,
        icon_path: Path,
        tooltip: str = "FPS Monitor",
        menu_provider: Callable[[], list[tuple[int, str, bool]]] | None = None,
    ) -> None:
        self.icon_path = Path(icon_path)
        self.tooltip = tooltip[:127]
        self.menu_provider = menu_provider
        self.actions: dict[int, str] = {
            ACTION_SHOW: "show",
            ACTION_OVERLAY: "toggle_overlay",
            ACTION_CLICKS: "toggle_clicks",
            ACTION_QUIT: "quit",
        }
        self.events: queue.Queue[str] = queue.Queue()
        self.available = False
        self.error = ""

        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pending_tip: str | None = None
        self._pending_balloon: tuple[str, str] | None = None
        self._hwnd: int = 0
        self._hicon: int = 0
        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")

    # ------------------------------------------------------------------ #
    # public API (called from the UI thread)
    # ------------------------------------------------------------------ #
    def start(self) -> bool:
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()
        self._ready.wait(6.0)
        return self.available

    def stop(self) -> None:
        self._stop.set()
        if self._hwnd:
            self._post(WM_CLOSE)
        if self._thread is not None:
            self._thread.join(timeout=4.0)

    def set_tooltip(self, text: str) -> None:
        with self._lock:
            self._pending_tip = text[:127]

    def notify(self, title: str, message: str) -> None:
        with self._lock:
            self._pending_balloon = (title[:63], message[:255])

    def poll(self) -> list[str]:
        fired: list[str] = []
        while True:
            try:
                fired.append(self.events.get_nowait())
            except queue.Empty:
                return fired

    # ------------------------------------------------------------------ #
    # tray thread
    # ------------------------------------------------------------------ #
    def _run(self) -> None:
        try:
            self._create_window()
        except Exception as exc:  # never take the app down because of the tray
            self.error = f"{type(exc).__name__}: {exc}"
            self.available = False
            self._ready.set()
            return

        self._ready.set()
        msg = wintypes.MSG()
        while not self._stop.is_set():
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result in (0, -1):
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        self._remove_icon()
        if self._hicon:
            user32.DestroyIcon(wintypes.HICON(self._hicon))
        self.available = False

    def _create_window(self) -> None:
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        instance = kernel32.GetModuleHandleW(None)

        self._wndproc = WNDPROC(self._handle_message)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = instance
        wc.lpszClassName = CLASS_NAME
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            # already registered by an earlier instance in this process
            if ctypes.get_last_error() not in (0, 1410):
                raise ctypes.WinError(ctypes.get_last_error())

        self._hwnd = user32.CreateWindowExW(
            0, CLASS_NAME, "FPS Monitor", 0, 0, 0, 0, 0, None, None, instance, None
        )
        if not self._hwnd:
            raise ctypes.WinError(ctypes.get_last_error())

        self._hicon = self._load_icon(instance)
        self._add_icon()
        user32.SetTimer(wintypes.HWND(self._hwnd), 1, 1000, None)
        self.available = True

    def _load_icon(self, instance) -> int:
        if self.icon_path.is_file():
            handle = user32.LoadImageW(
                None,
                str(self.icon_path),
                IMAGE_ICON,
                user32.GetSystemMetrics(SM_CXSMICON),
                user32.GetSystemMetrics(SM_CYSMICON),
                LR_LOADFROMFILE,
            )
            if handle:
                return int(handle)
        return int(user32.LoadIconW(None, IDI_APPLICATION_PTR) or 0)

    def _icon_data(self, flags: int) -> NOTIFYICONDATAW:
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = wintypes.HWND(self._hwnd)
        data.uID = 1
        data.uFlags = flags
        data.uCallbackMessage = WM_TRAYICON
        data.hIcon = wintypes.HICON(self._hicon)
        data.szTip = self.tooltip
        return data

    def _add_icon(self) -> None:
        data = self._icon_data(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)):
            raise ctypes.WinError(ctypes.get_last_error())

    def _remove_icon(self) -> None:
        if not self._hwnd:
            return
        data = self._icon_data(NIF_MESSAGE)
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))

    def _apply_pending(self) -> None:
        with self._lock:
            tip, self._pending_tip = self._pending_tip, None
            balloon, self._pending_balloon = self._pending_balloon, None
        if tip is not None:
            self.tooltip = tip
            data = self._icon_data(NIF_TIP)
            data.szTip = tip
            shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))
        if balloon is not None:
            title, message = balloon
            data = self._icon_data(NIF_INFO)
            data.szInfoTitle = title
            data.szInfo = message
            data.dwInfoFlags = NIIF_INFO
            data.uVersion = 0
            shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))

    def _post(self, message: int) -> None:
        if self._hwnd:
            user32.PostMessageW(wintypes.HWND(self._hwnd), message, 0, 0)

    # ------------------------------------------------------------------ #
    def _show_menu(self) -> None:
        items = self.menu_provider() if self.menu_provider else [
            (ACTION_SHOW, "Открыть окно", False),
            (ACTION_QUIT, "Выход", False),
        ]
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        try:
            for index, (ident, label, checked) in enumerate(items):
                if label == "-":
                    user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                    continue
                flags = MF_STRING | (MF_CHECKED if checked else 0)
                user32.AppendMenuW(menu, flags, ident, label)
                del index
            point = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(point))
            # required so the menu closes when clicking elsewhere
            user32.SetForegroundWindow(wintypes.HWND(self._hwnd))
            command = user32.TrackPopupMenu(
                menu,
                TPM_RETURNCMD | TPM_RIGHTBUTTON | TPM_NONOTIFY,
                point.x,
                point.y,
                0,
                wintypes.HWND(self._hwnd),
                None,
            )
            user32.PostMessageW(wintypes.HWND(self._hwnd), WM_NULL, 0, 0)
            if command:
                self._emit(int(command))
        finally:
            user32.DestroyMenu(menu)

    def _emit(self, command: int) -> None:
        action = self.actions.get(command)
        if action:
            self.events.put(action)

    def _handle_message(self, hwnd, message, wparam, lparam) -> int:
        try:
            if message == WM_TRAYICON:
                if lparam in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    self._emit(ACTION_SHOW)
                elif lparam in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._show_menu()
                return 0
            if message == WM_TIMER:
                self._apply_pending()
                return 0
            if message == self._taskbar_created:
                # Explorer restarted: the icon has to be added again
                try:
                    self._add_icon()
                except Exception:
                    pass
                return 0
            if message == WM_CLOSE:
                user32.DestroyWindow(wintypes.HWND(hwnd))
                return 0
            if message == WM_DESTROY:
                user32.KillTimer(wintypes.HWND(hwnd), 1)
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)
