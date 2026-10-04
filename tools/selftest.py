r"""Headless check of every metric source - run this when something looks wrong.

    python tools\selftest.py [seconds]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Config  # noqa: E402
from app.metrics import METRICS, format_value  # noqa: E402
from app.sampler import Sampler  # noqa: E402
from app.sources.lhm import is_elevated  # noqa: E402
from app.state import State  # noqa: E402


def main() -> int:
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    config = Config()
    state = State()
    sampler = Sampler(config, state)

    print(f"elevated        : {is_elevated()}")
    print(f"poll interval   : {config.poll_interval_ms} ms")
    print(f"vendor          : {(ROOT / 'vendor')}")
    print()

    sampler.start()
    try:
        for step in range(seconds):
            time.sleep(1)
            values, text, _ = state.snapshot()
            print(f"--- t={step + 1}s " + "-" * 46)
            for metric in METRICS:
                rendered = format_value(metric.key, values, text)
                if rendered is not None:
                    print(f"  {metric.label:<14} {rendered}")
            for key in ("gpu_hotspot", "gpu_clock_lhm", "cpu_load_lhm", "gpu_name"):
                if values.get(key) is not None:
                    print(f"  {key:<14} {values[key]}")
            if text.get("gpu_name"):
                print(f"  {'GPU name':<14} {text['gpu_name']}")
    finally:
        print()
        print("=== sources " + "=" * 50)
        for title, status, message in sampler.status_rows():
            print(f"  {title:<28} {status:<12} {message}")
        pm = sampler.source("presentmon")
        if pm is not None and hasattr(pm, "candidates"):
            print("=== presenters seen " + "=" * 42)
            for pid, name, fps in pm.candidates()[:8]:
                print(f"  {name:<28} pid={pid:<7} {fps:.1f} fps")
        sampler.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
