<#
    FPS Monitor - installer.

    Copies the application to %LOCALAPPDATA%\FpsMonitor and creates shortcuts.
    No administrator rights are needed to install; the app asks for elevation
    itself when it starts (PresentMon and the CPU temperature driver need it).

    Usage:
        powershell -ExecutionPolicy Bypass -File install.ps1
        powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall
#>

[CmdletBinding()]
param(
    [switch]$Uninstall,
    [switch]$NoShortcuts
)

$ErrorActionPreference = 'Stop'

$source = $PSScriptRoot
$target = Join-Path $env:LOCALAPPDATA 'FpsMonitor'
$launcher = Join-Path $target 'FpsMonitor.cmd'
$shortcutName = 'FPS Monitor.lnk'
$items = @('app', 'libs', 'vendor', 'tools', 'docs', 'FpsMonitor.cmd', 'README.md', 'config.json')

function New-Shortcut([string]$path) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $launcher
    $link.WorkingDirectory = $target
    $link.Description = 'FPS Monitor - FPS, temperatures and load overlay'
    $ownIcon = Join-Path $target 'app\fpsmonitor.ico'
    if (Test-Path -LiteralPath $ownIcon) {
        $link.IconLocation = $ownIcon
    } else {
        $link.IconLocation = "$env:SystemRoot\System32\imageres.dll,97"
    }
    $link.Save()
}

function Remove-Shortcut([string]$path) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
}

if ($Uninstall) {
    Remove-Shortcut (Join-Path ([Environment]::GetFolderPath('Desktop')) $shortcutName)
    Remove-Shortcut (Join-Path ([Environment]::GetFolderPath('Programs')) $shortcutName)
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
        Write-Host "Removed $target"
    }
    Get-Process FpsMonitor -ErrorAction SilentlyContinue | Stop-Process -Force
    Write-Host 'FPS Monitor uninstalled.'
    exit 0
}

if (-not (Test-Path -LiteralPath (Join-Path $source 'FpsMonitor.cmd'))) {
    throw "FpsMonitor.cmd not found next to install.ps1 - run the installer from the application folder."
}

Write-Host "Installing to $target"
New-Item -ItemType Directory -Force -Path $target | Out-Null

# vendor/ and libs/ are not kept in the repository, they are downloaded.
foreach ($needed in @('vendor', 'libs')) {
    if (-not (Test-Path -LiteralPath (Join-Path $source $needed))) {
        Write-Warning ("нет папки {0} — сначала выполните: python tools\fetch_vendor.py " +
                       "и python tools\fetch_psutil.py" -f $needed)
    }
}

foreach ($item in $items) {
    $from = Join-Path $source $item
    if (-not (Test-Path -LiteralPath $from)) {
        if ($item -eq 'config.json') { continue }   # no settings yet, that is fine
        Write-Warning "missing: $item"
        continue
    }
    $to = Join-Path $target $item
    if (Test-Path -LiteralPath $to) { Remove-Item -LiteralPath $to -Recurse -Force }
    Copy-Item -LiteralPath $from -Destination $to -Recurse -Force
    Write-Host "  + $item"
}

New-Item -ItemType Directory -Force -Path (Join-Path $target 'logs') | Out-Null

if (-not $NoShortcuts) {
    $desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) $shortcutName
    $startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) $shortcutName
    New-Shortcut $desktop
    New-Shortcut $startMenu
    Write-Host "  + shortcut: $desktop"
    Write-Host "  + shortcut: $startMenu"
}

# The app loads LibreHardwareMonitorLib.dll through .NET, which refuses
# assemblies that Windows marks as downloaded from the internet.
Get-ChildItem -Path $target -Recurse -File -Include *.dll, *.exe |
    ForEach-Object { try { Unblock-File -LiteralPath $_.FullName } catch { } }

Write-Host ''
Write-Host 'Done. Start it from the desktop shortcut, or run:'
Write-Host "    $launcher"
Write-Host 'Windows will ask for administrator rights - that is required for FPS'
Write-Host 'capture and for the CPU temperature sensor driver.'
