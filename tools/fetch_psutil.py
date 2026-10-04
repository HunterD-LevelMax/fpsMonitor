"""Install psutil into FpsMonitor/libs by unpacking its wheel.

pip insists on temp directories the DSH sandbox partially blocks, and a venv is
overkill for a single pure helper - so the wheel is unpacked straight into the
project. The app also works without it (ctypes fallback), this is only better.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / "libs"
UA = {"User-Agent": "FpsMonitor-setup/1.0"}


def main() -> int:
    tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    with urllib.request.urlopen(
        urllib.request.Request("https://pypi.org/pypi/psutil/json", headers=UA), timeout=60
    ) as resp:
        data = json.load(resp)

    version = data["info"]["version"]
    files = data["releases"][version]
    candidates = [f for f in files if f["filename"].endswith("win_amd64.whl")]
    if not candidates:
        print("no win_amd64 wheel published")
        return 1

    # free-threaded builds (cp314t) are ABI-incompatible with a normal CPython,
    # so prefer the stable-ABI wheel and never pick a "*t" one.
    candidates = [
        f
        for f in candidates
        if not re.search(r"cp3\d+t-", f["filename"])
    ]
    if not candidates:
        print("no compatible win_amd64 wheel published")
        return 1

    exact = [f for f in candidates if f["filename"].startswith(f"psutil-{version}-{tag}-")]
    abi3 = [f for f in candidates if "abi3" in f["filename"]]
    chosen = (abi3 or exact or candidates)[0]

    print(f"psutil {version} for {tag}: {chosen['filename']}")
    blob = ROOT / chosen["filename"]
    with urllib.request.urlopen(
        urllib.request.Request(chosen["url"], headers=UA), timeout=300
    ) as resp, open(blob, "wb") as out:
        out.write(resp.read())

    LIBS.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(blob) as zf:
        zf.extractall(LIBS)
    blob.unlink()

    sys.path.insert(0, str(LIBS))
    import psutil  # noqa: PLC0415 - deliberate post-install check

    print(f"ok: psutil {psutil.__version__} -> {LIBS}")
    print(f"cpu_count={psutil.cpu_count(logical=True)} ram={psutil.virtual_memory().total / 2**30:.1f} GiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
