"""Replay synthetic PresentMon captures through the real parser.

No admin rights and no game needed: the CSV uses the exact v1 header PresentMon
2.6 prints, with known frame times, so every derived number can be checked
against arithmetic.

Two profiles are used:
  * steady  - 10 ms frames, so window metrics have an exact expected value;
  * stutter - 10 ms frames plus a 120 ms hitch every 50th frame, which is what
              exposes 1% low, stutter counting and long-frame survival.

    python tools\\test_frames.py
"""

from __future__ import annotations

import io
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.sources.base import Context  # noqa: E402
from app.sources.presentmon import PresentMonSource  # noqa: E402

HEADER = (
    "Application,ProcessID,SwapChainAddress,PresentRuntime,SyncInterval,PresentFlags,"
    "AllowsTearing,PresentMode,TimeInMs,MsBetweenSimulationStart,MsBetweenPresents,"
    "MsBetweenDisplayChange,MsInPresentAPI,MsRenderPresentLatency,MsUntilDisplayed,"
    "CPUStartTimeInMs,MsBetweenAppStart,MsCPUBusy,MsCPUWait,MsGPULatency,MsGPUTime,"
    "MsGPUBusy,MsGPUWait,MsAnimationError,AnimationTime,MsFlipDelay,"
    "MsAllInputToPhotonLatency,MsClickToPhotonLatency"
)

STEADY_MS = 10.0
STEADY_FRAMES = 600
STUTTER_EVERY = 50
STUTTER_MS = 120.0
STUTTER_FRAMES = 1200
FAST_MS = 5.0
FAST_FRAMES = 400
SIDE_CHAIN_MS = 200.0
SIDE_FRAMES = 30
STUTTER_AVG = ((STUTTER_EVERY - 1) * STEADY_MS + STUTTER_MS) / STUTTER_EVERY

failures = 0


def row(app: str, pid: int, chain: str, stamp: float, frame_ms: float) -> str:
    return (
        f"{app},{pid},{chain},DXGI,0,0,0,Composed: Flip,{stamp:.4f},NA,{frame_ms:.8f},NA,"
        "0.0978,1.2625,8.9120,0.6361,2.2326,2.1348,0.0978,2.0225,1.3748,1.1351,0.2397,"
        "NA,0.6361,NA,NA,NA"
    )


def build_capture(profile: str) -> list[str]:
    lines = [HEADER]
    stamp = 5_000_000.0

    frames = STEADY_FRAMES if profile == "steady" else STUTTER_FRAMES
    for index in range(frames):
        if profile == "stutter" and index % STUTTER_EVERY == 0:
            frame = STUTTER_MS
        else:
            frame = STEADY_MS
        stamp += frame
        lines.append(row("Game.exe", 100, "0xAAA", stamp, frame))

    # same process, second swap chain: slow, must never be chosen
    side_stamp = stamp - SIDE_FRAMES * SIDE_CHAIN_MS
    for _ in range(SIDE_FRAMES):
        side_stamp += SIDE_CHAIN_MS
        lines.append(row("Game.exe", 100, "0xBBB", side_stamp, SIDE_CHAIN_MS))

    # another process, twice as fast - must win the automatic picker
    fast_stamp = stamp - FAST_FRAMES * FAST_MS
    for _ in range(FAST_FRAMES):
        fast_stamp += FAST_MS
        lines.append(row("Fast.exe", 200, "0xCCC", fast_stamp, FAST_MS))

    # a shell process the automatic picker must ignore
    lines.append(row("explorer.exe", 300, "0xDDD", stamp, 16.0))
    return lines


class FakeProc:
    def __init__(self, stream: io.BytesIO) -> None:
        self.stdout = stream
        self.stderr = io.BytesIO()

    def poll(self):
        return None

    def terminate(self) -> None:
        pass

    def wait(self, timeout=None) -> int:
        return 0

    def kill(self) -> None:
        pass


def load_source(profile: str = "stutter", encoding: str = "utf-16") -> PresentMonSource:
    source = PresentMonSource(Context(), pathlib.Path("."))
    payload = "\r\n".join(build_capture(profile)) + "\r\n"
    source._proc = FakeProc(io.BytesIO(payload.encode(encoding)))  # noqa: SLF001
    source._read_stdout()  # noqa: SLF001
    return source


def check(label: str, actual, expected: float, tolerance: float = 0.0) -> None:
    global failures
    if actual is None:
        print(f"  FAIL {label}: no value (expected {expected:.2f})")
        failures += 1
        return
    ok = abs(actual - expected) <= tolerance
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {actual:.2f} (expected {expected:.2f} ±{tolerance:.2f})")
    failures += 0 if ok else 1


def check_true(label: str, condition: bool, detail: str = "") -> None:
    global failures
    print(f"  {'ok  ' if condition else 'FAIL'} {label}{(' — ' + detail) if detail else ''}")
    failures += 0 if condition else 1


def main() -> int:
    print("encoding tolerance (both forms have been seen from PresentMon)")
    for encoding in ("utf-16", "utf-8"):
        probe = load_source("steady", encoding)
        check_true(f"{encoding} parses every swap chain", len(probe._chains) == 4,  # noqa: SLF001
                   f"{len(probe._chains)} chains")  # noqa: SLF001
    print()

    print("steady 10 ms stream (exact expectations)")
    source = load_source("steady")
    source.set_pinned(100)  # otherwise the picker rightly prefers Fast.exe
    time.sleep(0.01)
    values = source.refresh().values
    check("fps", values.get("fps"), 100.0, 0.01)
    check("frametime", values.get("frametime"), STEADY_MS, 0.001)
    check("frames in window", values.get("frames_window"), 100.0, 1.0)
    check("frametime min", values.get("frametime_min"), STEADY_MS, 0.001)
    check("frametime max", values.get("frametime_max"), STEADY_MS, 0.001)
    check("1% low", values.get("fps_low"), 100.0, 0.01)
    check_true("no stutters", values.get("stutters", 0.0) == 0.0)
    check_true("fps and frametime are consistent",
               abs(values["fps"] - 1000.0 / values["frametime"]) < 1e-6)
    print()

    print("stuttery stream (120 ms hitch every 50 frames)")
    source = load_source("stutter")
    source.set_pinned(100)
    values = source.refresh().values
    check("1% low", values.get("fps_low"), 1000.0 / STUTTER_MS, 0.2)
    check("0.1% low", values.get("fps_low01"), 1000.0 / STUTTER_MS, 0.2)
    check("frametime max", values.get("frametime_max"), STUTTER_MS, 0.001)
    check("frametime min", values.get("frametime_min"), STEADY_MS, 0.001)
    check_true("stutters counted", (values.get("stutters") or 0) > 0,
               f"{int(values.get('stutters') or 0)}")

    stats = source.stats(60.0)  # the whole capture: expectations are exact again
    check("mean frametime over the capture", stats.get("avg"), STUTTER_AVG, 0.01)
    check("samples over the capture", stats.get("samples"), float(STUTTER_FRAMES), 0.0)

    series = source.frame_series(10.0)
    if series:
        xs = [x for x, _ in series]
        check_true("newest frame sits at x=0", abs(max(xs)) < 1e-6, f"{max(xs):.4f}")
        check_true("window spans 10 s", min(xs) >= -10.0001, f"{min(xs):.2f} s")
        long_frames = sum(1 for _, frame in series if frame > 100)
        check_true("long frames survive aggregation", long_frames > 0, f"{long_frames} of {len(series)}")
    else:
        check_true("frame series produced", False)

    print()
    print("automatic picker (no foreground window)")
    candidates = source.candidates()
    for pid, name, fps in candidates[:3]:
        print(f"    pid={pid:<5} {name:<14} {fps:6.1f} fps")
    check_true("picks the busiest presenter, not the shell",
               bool(candidates) and candidates[0][1] == "Fast.exe",
               candidates[0][1] if candidates else "none")

    print()
    print("RESULT:", "all checks passed" if failures == 0 else f"{failures} check(s) failed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
