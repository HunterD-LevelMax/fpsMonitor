@echo off
rem ===================================================================
rem  FPS Monitor launcher.
rem  Relaunches itself elevated, because PresentMon (FPS) and the
rem  LibreHardwareMonitor driver (CPU temperature) both need admin.
rem ===================================================================
setlocal
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% equ 0 goto :run

echo Zaprashivaem prava administratora / requesting administrator rights...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b

:run
set "PYW="
if exist "%~dp0.venv\Scripts\pythonw.exe" set "PYW=%~dp0.venv\Scripts\pythonw.exe"
if not defined PYW if exist "C:\Python314\pythonw.exe" set "PYW=C:\Python314\pythonw.exe"
if not defined PYW for %%P in (pythonw.exe) do if not "%%~$PATH:P"=="" set "PYW=%%~$PATH:P"

if not defined PYW (
    echo.
    echo Python ne nayden / Python was not found.
    echo Ustanovite Python 3.10+ i povtorite zapusk.
    pause
    exit /b 1
)

start "" "%PYW%" "%~dp0app\main.py" %*
exit /b 0
