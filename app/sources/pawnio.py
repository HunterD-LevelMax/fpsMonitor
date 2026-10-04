"""Optional PawnIO driver install - the fix for CPU temperature on Windows 11.

Reading CPU MSRs used to work through WinRing0, which is embedded in
LibreHardwareMonitor. Microsoft added WinRing0 to the vulnerable driver
blocklist, so on an up-to-date Windows 11 the driver silently fails to load and
every CPU temperature/power/clock sensor reports 0.

LibreHardwareMonitor 0.9.6 ships an alternative backend for exactly this case:
PawnIO, a signed scriptable kernel driver. Its setup is embedded inside
LibreHardwareMonitor.exe (resource: LibreHardwareMonitor.Resources.PawnIO_setup.exe),
so the driver can be installed offline from the files we already have.

Installing a kernel driver is a deliberate user action - the app only exposes
this through a button in the diagnostics tab.
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import tempfile
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
UNINSTALL_KEYS = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO",
    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO",
)
PAWNIO_DEVICE = "\\\\.\\PawnIO"


def is_installed() -> bool:
    """True when the PawnIO driver package is registered."""
    import winreg

    for hive in (winreg.HKEY_LOCAL_MACHINE,):
        for path in UNINSTALL_KEYS:
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    key = winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view)
                    key.Close()
                    return True
                except OSError:
                    continue
    return _device_present()


def _device_present() -> bool:
    handle = ctypes.windll.kernel32.CreateFileW(
        PAWNIO_DEVICE, 0x80000000, 3, None, 3, 0, None
    )
    if handle == -1:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def blocked_driver_reason() -> str:
    """Whether Windows is blocking WinRing0, phrased for the user."""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\CI\Config"
        ) as key:
            enabled = winreg.QueryValueEx(key, "VulnerableDriverBlocklistEnable")[0]
        if enabled:
            return (
                "Windows блокирует драйвер WinRing0 (он в списке уязвимых драйверов "
                "Microsoft), поэтому датчики CPU молчат."
            )
    except OSError:
        pass
    return "драйвер датчиков CPU не загрузился."


def install(lhm_exe: Path, timeout: float = 180.0) -> tuple[bool, str]:
    """Extract the bundled PawnIO setup and install it silently."""
    if not lhm_exe.is_file():
        return False, f"не найден {lhm_exe}"
    if not ctypes.windll.shell32.IsUserAnAdmin():
        return False, "нужны права администратора: закройте приложение и запустите FpsMonitor.cmd"

    workdir = Path(tempfile.mkdtemp(prefix="FpsMonitor_PawnIO_"))
    setup = workdir / "PawnIO_setup.exe"

    extract = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            (
                "$ErrorActionPreference='Stop';"
                f"$a=[Reflection.Assembly]::LoadFrom('{lhm_exe}');"
                "$s=$a.GetManifestResourceStream('LibreHardwareMonitor.Resources.PawnIO_setup.exe');"
                "if(-not $s){throw 'resource not found'};"
                f"$f=[IO.File]::Create('{setup}');$s.CopyTo($f);$f.Close();"
                f"Write-Output ('extracted ' + (Get-Item '{setup}').Length)"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )
    if extract.returncode != 0 or not setup.is_file():
        return False, f"не удалось извлечь установщик: {extract.stderr.strip()[:200]}"

    result = subprocess.run(
        [str(setup), "-install", "-silent"],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
        cwd=str(workdir),
    )
    output = (result.stdout or "") + (result.stderr or "")
    ok = is_installed()
    if ok:
        return True, "PawnIO установлен"
    return False, f"установщик завершился с кодом {result.returncode}: {output.strip()[:200]}"


def summary() -> dict:
    return {"installed": is_installed(), "hint": blocked_driver_reason()}


if __name__ == "__main__":  # tiny CLI: python -m app.sources.pawnio [install]
    import sys

    root = Path(__file__).resolve().parents[2]
    exe = root / "vendor" / "LibreHardwareMonitor" / "LibreHardwareMonitor.exe"
    if len(sys.argv) > 1 and sys.argv[1] == "install":
        ok, message = install(exe)
        print(json.dumps({"ok": ok, "message": message}, ensure_ascii=False))
    else:
        print(json.dumps(summary(), ensure_ascii=False))
