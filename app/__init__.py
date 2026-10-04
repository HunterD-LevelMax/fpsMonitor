"""FpsMonitor - FPS / temperature / load overlay for Windows."""

import sys
from pathlib import Path

# psutil ships unpacked in ./libs so the app needs no installation step.
_LIBS = Path(__file__).resolve().parents[1] / "libs"
if _LIBS.is_dir() and str(_LIBS) not in sys.path:
    sys.path.insert(0, str(_LIBS))

__version__ = "1.0.0"
