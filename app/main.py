"""FpsMonitor entry point.

    pythonw app\\main.py            (or FpsMonitor.cmd, which elevates first)
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wintypes
import sys
import time
import traceback
from pathlib import Path
from tkinter import messagebox
import tkinter as tk
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import winutil  # noqa: E402
from app.config import LOG_DIR, Config  # noqa: E402
from app.sampler import Sampler  # noqa: E402
from app.sources.lhm import is_elevated  # noqa: E402
from app.state import State  # noqa: E402
from app.tray import (  # noqa: E402
    ACTION_CLICKS,
    ACTION_OVERLAY,
    ACTION_QUIT,
    ACTION_SHOW,
    TrayIcon,
)
from app.ui import theme  # noqa: E402
from app.ui.dashboard import Dashboard  # noqa: E402
from app.ui.overlay import Overlay  # noqa: E402

ICON_PATH = Path(__file__).resolve().parent / "fpsmonitor.ico"

MUTEX_NAME = "Global\\FpsMonitorSingleInstance"
# A standard user cannot create an object in the Global\ namespace, so the
# session-local name is used as a fallback - otherwise two unelevated copies
# would happily run side by side and stack their overlays.
MUTEX_FALLBACK = "Local\\FpsMonitorSingleInstance"
ERROR_ALREADY_EXISTS = 183
TICK_MS = 250


def _single_instance() -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.LPCWSTR]
    handles = []
    for name in (MUTEX_NAME, MUTEX_FALLBACK):
        ctypes.set_last_error(0)
        try:
            handle = kernel32.CreateMutexW(None, 0, name)
        except OSError:
            continue
        if not handle:
            continue
        # keep the handle open for the lifetime of the process
        handles.append(handle)
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            return False
    return True


def _crash_log(exc: BaseException) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_DIR / "crash.log", "a", encoding="utf-8") as handle:
            handle.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            handle.write("".join(traceback.format_exception(exc)))
    except OSError:
        pass


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="FpsMonitor", description="FPS / temperature overlay")
    parser.add_argument("--no-overlay", action="store_true", help="не показывать оверлей")
    parser.add_argument("--hidden", action="store_true", help="запустить только оверлей")
    parser.add_argument("--page", default="monitor",
                        choices=["monitor", "frames", "sensors", "overlay", "settings",
                                 "diagnostics"],
                        help="страница, которую открыть при запуске")
    args = parser.parse_args(argv)

    if not _single_instance():
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.lift()
        messagebox.showinfo(
            "FPS Monitor",
            "FPS Monitor уже запущен.\n\n"
            "Значок в трее рядом с часами: левый клик — открыть окно, "
            "правый — меню, там же «Выход».",
        )
        root.destroy()
        return 0

    winutil.set_dpi_awareness()
    config = Config.load()
    if args.no_overlay:
        config.overlay_enabled = False

    state = State(history_seconds=max(900.0, config.graph_window_s * 3.0))
    sampler = Sampler(config, state)
    sampler.start()

    root = tk.Tk()
    root.title("FPS Monitor")
    root.geometry("1280x780")
    root.minsize(1140, 700)
    root.configure(bg=theme.BG)
    try:
        root.iconbitmap(default=str(ICON_PATH))
    except tk.TclError:
        pass

    def frame_series(seconds: float) -> list[tuple[float, float]]:
        source = sampler.source("presentmon")
        if source is None or not hasattr(source, "frame_series"):
            return []
        try:
            return source.frame_series(seconds)
        except Exception:
            return []

    overlay = Overlay(root, config, state, series_provider=frame_series)
    flags = {"closing": False}

    def tray_menu() -> list[tuple[int, str, bool]]:
        return [
            (ACTION_SHOW, "Показать окно", False),
            (ACTION_OVERLAY, "Оверлей поверх игр", config.overlay_enabled),
            (ACTION_CLICKS, "Пропускать клики сквозь оверлей", config.overlay_click_through),
            (0, "-", False),
            (ACTION_QUIT, "Выход", False),
        ]

    tray = TrayIcon(ICON_PATH, "FPS Monitor", tray_menu)
    tray_ok = tray.start()

    def shutdown() -> None:
        if flags["closing"]:
            return
        flags["closing"] = True
        try:
            sampler.stop()
            hotkeys.stop()
            if tray_ok:
                tray.stop()
        finally:
            root.destroy()

    def show_window() -> None:
        root.deiconify()
        root.lift()
        root.focus_force()

    dashboard = Dashboard(root, config, state, sampler, overlay, on_quit=shutdown,
                          tray=tray if tray_ok else None)
    # dragging the HUD switches it to "custom corner" - keep the settings in sync
    overlay.on_change = dashboard.sync_overlay_controls
    if args.page != "monitor":
        dashboard.show_page(args.page)
    if args.hidden:
        root.withdraw()

    hotkeys = winutil.HotkeyManager()
    hotkeys.start(
        {
            "overlay": config.hotkey_toggle_overlay,
            "clicks": config.hotkey_toggle_click_through,
            "window": config.hotkey_toggle_window,
        }
    )

    def toggle_window() -> None:
        if root.state() == "withdrawn":
            show_window()
        else:
            root.withdraw()

    last_tip = [0.0]

    def update_tray_tooltip() -> None:
        now = time.monotonic()
        if not tray_ok or now - last_tip[0] < 5.0:
            return
        last_tip[0] = now
        values, text, _ = state.snapshot()
        fps = values.get("fps")
        parts = [f"{fps:.0f} FPS" if fps is not None else "FPS: нет данных"]
        if text.get("proc_text"):
            parts.append(text["proc_text"])
        if values.get("cpu_temp") is not None:
            parts.append(f"CPU {values['cpu_temp']:.0f} °C")
        tray.set_tooltip("FPS Monitor — " + " · ".join(parts))

    def tick() -> None:
        try:
            for name in hotkeys.poll():
                if name == "overlay":
                    overlay.toggle()
                    dashboard.sync_overlay_controls()
                elif name == "clicks":
                    overlay.toggle_click_through()
                    dashboard.sync_overlay_controls()
                elif name == "window":
                    toggle_window()
            if tray_ok:
                for action in tray.poll():
                    if action == "show":
                        show_window()
                    elif action == "toggle_overlay":
                        overlay.toggle()
                        dashboard.sync_overlay_controls()
                    elif action == "toggle_clicks":
                        overlay.toggle_click_through()
                        dashboard.sync_overlay_controls()
                    elif action == "quit":
                        shutdown()
                        return
            overlay.refresh()
            if root.state() != "withdrawn":
                dashboard.refresh()
            update_tray_tooltip()
        except Exception as exc:  # keep the HUD alive no matter what
            _crash_log(exc)
        finally:
            if not flags["closing"]:
                root.after(TICK_MS, tick)

    # The X button hides the window: a monitoring overlay that quits when its
    # settings window is closed would look like "it just stopped working".
    root.protocol("WM_DELETE_WINDOW", dashboard.hide_window)
    root.after(TICK_MS, tick)

    if not is_elevated():
        # a single, non-blocking hint - the dashboard shows the full warning
        root.title("FPS Monitor — без прав администратора: FPS и температура CPU недоступны")

    root.mainloop()
    return 0


def main() -> int:
    try:
        return run()
    except BaseException as exc:  # noqa: BLE001 - last-resort logging
        _crash_log(exc)
        raise


if __name__ == "__main__":
    sys.exit(main())
