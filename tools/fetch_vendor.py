"""Download the third-party binaries FpsMonitor needs.

Everything lands in FpsMonitor/vendor/ so the app is self-contained:
  * PresentMon             - real FPS / frametime via the DxgKrnl ETW provider
  * LibreHardwareMonitor   - CPU temperature via its kernel driver + WMI namespace
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"
UA = {"User-Agent": "FpsMonitor-setup/1.0"}

SOURCES = [
    {
        "name": "PresentMon",
        "repo": "GameTechDev/PresentMon",
        "pick": re.compile(r"^PresentMon-[\d.]+-x64\.exe$", re.I),
        "kind": "file",
        "target": "PresentMon",
    },
    {
        "name": "LibreHardwareMonitor",
        "repo": "LibreHardwareMonitor/LibreHardwareMonitor",
        "pick": re.compile(r"^LibreHardwareMonitor\.zip$", re.I),
        "kind": "zip",
        "target": "LibreHardwareMonitor",
    },
]


def fetch_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                print(f"\r  {dest.name}: {pct}% ({done // 1024} KiB)", end="", flush=True)
    print(f"\r  {dest.name}: {dest.stat().st_size // 1024} KiB downloaded")


def main() -> int:
    VENDOR.mkdir(parents=True, exist_ok=True)
    failures = []

    for src in SOURCES:
        print(f"== {src['name']} ({src['repo']})")
        try:
            release = fetch_json(f"https://api.github.com/repos/{src['repo']}/releases/latest")
        except Exception as exc:  # pragma: no cover - network dependent
            print(f"  !! cannot read release info: {exc}")
            failures.append(src["name"])
            continue

        tag = release.get("tag_name", "?")
        asset = next(
            (a for a in release.get("assets", []) if src["pick"].match(a["name"])),
            None,
        )
        if asset is None:
            names = ", ".join(a["name"] for a in release.get("assets", []))
            print(f"  !! no asset matching {src['pick'].pattern} in {tag}. Assets: {names}")
            failures.append(src["name"])
            continue

        print(f"  release {tag} -> {asset['name']}")
        blob = VENDOR / asset["name"]
        try:
            download(asset["browser_download_url"], blob)
        except Exception as exc:
            print(f"  !! download failed: {exc}")
            failures.append(src["name"])
            continue

        target = VENDOR / src["target"]
        if src["kind"] == "file":
            target.mkdir(parents=True, exist_ok=True)
            final = target / asset["name"]
            if final.exists():
                final.unlink()
            blob.replace(final)
            print(f"  -> {final.relative_to(ROOT)}")
        else:
            if target.exists():
                for old in target.rglob("*"):
                    if old.is_file():
                        old.unlink()
            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(blob) as zf:
                zf.extractall(target)
            blob.unlink()
            print(f"  -> {target.relative_to(ROOT)}/")

    print()
    if failures:
        print("FAILED: " + ", ".join(failures))
        return 1
    print("All vendor binaries are in place.")
    return 0


if __name__ == "__main__":
    os.chdir(ROOT)
    sys.exit(main())
