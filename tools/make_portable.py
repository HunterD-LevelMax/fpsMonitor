"""Build a portable, no-install ZIP of FpsMonitor.

The archive carries its own Python (the official embeddable distribution plus
the Tcl/Tk bits the embeddable build leaves out), so the receiving machine
needs nothing preinstalled:

    FpsMonitor-portable/
        Запуск.cmd          <- double-click this
        python/             <- embedded CPython + tkinter + tcl/tk
        app/ libs/ vendor/  <- the application
        ПРОЧТИ_МЕНЯ.txt

    python tools\\make_portable.py
"""

from __future__ import annotations

import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
CACHE = DIST / "_cache"
STAGE = DIST / "FpsMonitor-portable"

VERSION = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
EMBED_URL = f"https://www.python.org/ftp/python/{VERSION}/python-{VERSION}-embed-amd64.zip"
TAG = f"python{sys.version_info.major}{sys.version_info.minor}"

APP_ITEMS = ["app", "libs", "vendor", "docs"]
SKIP_DIRS = {"__pycache__", ".venv", "dist"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".pdb"}

LAUNCHER = """@echo off
rem ============================================================
rem  FPS Monitor (portable) - nothing to install.
rem  Asks for administrator rights: the FPS capture and the CPU
rem  temperature sensor driver both need them.
rem ============================================================
setlocal
cd /d "%~dp0"

set "TCL_LIBRARY=%~dp0python\\tcl\\{tcl}"
set "TK_LIBRARY=%~dp0python\\tcl\\{tk}"
set "PYTHONHOME=%~dp0python"
set "PYTHONUTF8=1"

net session >nul 2>&1
if %errorlevel% equ 0 goto run

echo Requesting administrator rights...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b

:run
if not exist "%~dp0python\\pythonw.exe" (
    echo ERROR: python\\pythonw.exe is missing - unpack the whole archive.
    pause
    exit /b 1
)
start "" "%~dp0python\\pythonw.exe" "%~dp0app\\main.py"
exit /b 0
"""

README_TXT = """FPS Monitor - портативная версия (ничего устанавливать не нужно)
=================================================================

ЗАПУСК
------
1. Распакуйте архив целиком в обычную папку, например C:\\FpsMonitor
   (не запускайте прямо из архива и не кладите в Program Files - приложению
   нужно писать рядом с собой настройки и логи).

   ВАЖНО: если архив скачан из интернета, сначала снимите с него блокировку -
   правый клик по ZIP-файлу -> "Свойства" -> галочка "Разблокировать" -> ОК,
   и только потом распаковывайте. Иначе Windows пометит все файлы как
   "скачанные из интернета" и часть датчиков может не заработать.

2. Дважды щёлкните "Запуск.cmd" (если имя файла отобразилось нечитаемо -
   используйте "Start.cmd", это то же самое).
3. Windows спросит права администратора - нажмите "Да".
   Без этого не будет FPS игр и температуры процессора.

ЧТО ПОЯВИТСЯ
------------
* Оверлей в левом верхнем углу экрана - FPS, время кадра, загрузка и
  температура CPU/GPU, память.
* Окно с графиками и настройками.
* Значок в трее (рядом с часами, в "скрытых значках").

ЗНАЧОК В ТРЕЕ - ЭТО ГЛАВНОЕ
---------------------------
Левый клик по значку  - открыть окно.
Правый клик           - меню: показать окно, включить/выключить оверлей,
                        клики сквозь оверлей, ВЫХОД.
Наведение курсора     - подсказка с текущим FPS, игрой и температурой CPU.

Крестик в окне НЕ закрывает программу, а только прячет окно. Полностью
закрыть - "Выход" в меню значка (или кнопка в правом верхнем углу окна).

ГОРЯЧИЕ КЛАВИШИ
---------------
Ctrl+Alt+O - показать/скрыть оверлей
Ctrl+Alt+L - разрешить перетаскивание оверлея мышью
Ctrl+Alt+M - показать/скрыть окно с графиками

ЕСЛИ НЕТ ТЕМПЕРАТУРЫ ПРОЦЕССОРА
-------------------------------
Современная Windows блокирует драйвер WinRing0 (он в списке уязвимых драйверов),
поэтому датчики CPU молчат. Откройте вкладку "Диагностика" и нажмите
"Установить драйвер датчиков (PawnIO)" - приложение поставит подписанный
драйвер само (он встроен в комплект, интернет не нужен).

ЕСЛИ НЕТ FPS
------------
* Проверьте, что запускали через "Запуск.cmd" и подтвердили запрос UAC -
  без прав администратора захват кадров невозможен.
* Вкладка "Диагностика" показывает состояние каждого источника данных.

ЕСЛИ НЕТ ДАННЫХ ВИДЕОКАРТЫ
--------------------------
Метрики NVIDIA (температура, мощность, VRAM) читаются через nvidia-smi из
драйвера NVIDIA. На картах AMD/Intel этих строк не будет, остальное работает.

СОСТАВ
------
app/     - сама программа (Python)
libs/    - psutil
vendor/  - PresentMon 2.6.0 (Intel, MIT) и LibreHardwareMonitor 0.9.6 (MPL-2.0)
python/  - встроенный Python 3.14.5 (python.org), включая tkinter
docs/    - пример оверлея
Настройки и логи пишутся в config.json и logs\\ рядом с программой.

УДАЛЕНИЕ
--------
Просто удалите папку. Если ставили драйвер PawnIO и он больше не нужен -
"Параметры" -> "Приложения" -> PawnIO -> Удалить.
"""


def human(size: float) -> str:
    return f"{size / 1048576:.1f} MB"


def ignore(directory: str, names: list[str]) -> set[str]:
    skipped = set()
    for name in names:
        path = Path(directory) / name
        if name in SKIP_DIRS:
            skipped.add(name)
        elif path.suffix.lower() in SKIP_SUFFIXES:
            skipped.add(name)
    return skipped


def _library_dir(root: Path, marker: str, fallback: str) -> str:
    """Name of the sub directory that actually holds the Tcl/Tk scripts."""
    candidates = [
        child.name
        for child in sorted(root.iterdir())
        if child.is_dir() and (child / marker).is_file()
    ]
    if candidates:
        return max(candidates, key=len)  # tcl8.6 beats tcl8
    return fallback


def _prune_tcl(root: Path) -> None:
    """Drop development files that Tcl/Tk does not need at runtime."""
    for child in list(root.iterdir()):
        if child.is_dir() and child.name == "nmake":
            shutil.rmtree(child, ignore_errors=True)
        elif child.is_file() and child.suffix.lower() in {".lib", ".sh", ".exp", ".pdb"}:
            child.unlink(missing_ok=True)


def download_embed() -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / Path(EMBED_URL).name
    if target.is_file() and target.stat().st_size > 5_000_000:
        print(f"  cached: {target.name} ({human(target.stat().st_size)})")
        return target
    print(f"  downloading {EMBED_URL}")
    request = urllib.request.Request(EMBED_URL, headers={"User-Agent": "FpsMonitor-build"})
    with urllib.request.urlopen(request, timeout=600) as response, open(target, "wb") as handle:
        shutil.copyfileobj(response, handle)
    print(f"  saved: {target.name} ({human(target.stat().st_size)})")
    return target


def build_python() -> tuple[str, str]:
    """Unpack the embedded runtime and add the missing Tk pieces."""
    python_dir = STAGE / "python"
    if python_dir.exists():
        shutil.rmtree(python_dir)
    python_dir.mkdir(parents=True)

    with zipfile.ZipFile(download_embed()) as archive:
        archive.extractall(python_dir)
        names = archive.namelist()
    print(f"  embedded runtime: {len(names)} files")

    home = Path(sys.base_prefix)
    shutil.copytree(home / "Lib" / "tkinter", python_dir / "Lib" / "tkinter",
                    ignore=ignore, dirs_exist_ok=True)

    dll_dir = python_dir / "DLLs"
    dll_dir.mkdir(exist_ok=True)
    for name in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "zlib1.dll"):
        source = home / "DLLs" / name
        if source.is_file():
            shutil.copy2(source, dll_dir / name)
        else:
            print(f"  !! missing {name}")

    tcl_root = home / "tcl"
    shutil.copytree(tcl_root, python_dir / "tcl", ignore=ignore, dirs_exist_ok=True)
    # C:\Python314\tcl holds both "tcl8" and "tcl8.6" - pick the real library
    # by locating its init script instead of trusting the name.
    tcl = _library_dir(python_dir / "tcl", "init.tcl", "tcl8")
    tk = _library_dir(python_dir / "tcl", "tk.tcl", "tk8.6")
    _prune_tcl(python_dir / "tcl")
    print(f"  tcl/tk: {tcl}, {tk}")
    if not (python_dir / "tcl" / tcl / "init.tcl").is_file():
        print("  !! tcl library directory looks wrong")

    # keep the embedded interpreter isolated but able to import tkinter from Lib/
    pth = python_dir / f"{TAG}._pth"
    pth.write_text(f"{TAG}.zip\n.\nLib\nDLLs\n", encoding="ascii")
    print(f"  wrote {pth.name}")
    return tcl, tk


def copy_app() -> None:
    for item in APP_ITEMS:
        source = ROOT / item
        if not source.exists():
            print(f"  !! missing {item}")
            continue
        target = STAGE / item
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target, ignore=ignore)
        size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
        print(f"  + {item}/ ({human(size)})")
    shutil.copy2(ROOT / "README.md", STAGE / "README.md")


def write_docs(tcl: str, tk: str) -> None:
    launcher = LAUNCHER.format(tcl=tcl, tk=tk).replace("\n", "\r\n")
    # ASCII alias as well: some unpackers or mail relays mangle Cyrillic names.
    for name in ("Запуск.cmd", "Start.cmd"):
        (STAGE / name).write_text(launcher, encoding="ascii")
    (STAGE / "ПРОЧТИ_МЕНЯ.txt").write_text(README_TXT.replace("\n", "\r\n"), encoding="utf-8-sig")
    print("  + Запуск.cmd, Start.cmd, ПРОЧТИ_МЕНЯ.txt")


def make_zip() -> Path:
    archive = DIST / "FpsMonitor-portable.zip"
    if archive.exists():
        archive.unlink()
    count = 0
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(STAGE.rglob("*")):
            if path.is_file():
                zf.write(path, Path("FpsMonitor-portable") / path.relative_to(STAGE))
                count += 1
    print(f"  {count} files -> {archive} ({human(archive.stat().st_size)})")
    return archive


def main() -> int:
    if "--zip-only" in sys.argv:
        archive = make_zip()
        print(f"\nArchive rebuilt: {archive} ({human(archive.stat().st_size)})")
        return 0

    print(f"Building portable FpsMonitor (Python {VERSION}, {sys.base_prefix})")
    DIST.mkdir(parents=True, exist_ok=True)
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    print("Python runtime:")
    tcl, tk = build_python()
    print("Application:")
    copy_app()
    write_docs(tcl, tk)

    print("Archive:")
    archive = make_zip()

    unpacked = sum(f.stat().st_size for f in STAGE.rglob("*") if f.is_file())
    print(f"\nUnpacked: {human(unpacked)}   Archive: {human(archive.stat().st_size)}")
    print(f"Give this file away: {archive}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
