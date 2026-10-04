# FpsMonitor <-> LibreHardwareMonitor bridge.
#
# LibreHardwareMonitor dropped its WMI provider, and the GUI needs a manual
# click to start its web server, so the app drives LibreHardwareMonitorLib.dll
# directly instead. Windows PowerShell 5.1 runs on .NET Framework 4.x, exactly
# what this assembly targets, so no extra runtime is required.
#
# Protocol: one request line on stdin -> one JSON line on stdout.
#   ""  poll sensors      "q"  quit
#
# Requires an elevated host: LibreHardwareMonitorLib loads a kernel driver to
# read CPU MSRs.

param(
    [Parameter(Mandatory = $true)][string]$LibDir,
    [int]$Motherboard = 1,
    [int]$Memory = 1,
    [int]$Storage = 0,
    [int]$Network = 0,
    [int]$Controller = 0,
    [int]$Psu = 0
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Write-Line([string]$text) {
    [Console]::Out.WriteLine($text)
    [Console]::Out.Flush()
}

function Send-Error([string]$message) {
    $payload = [pscustomobject]@{
        Ok      = $false
        Error   = $message
        Sensors = @()
    }
    Write-Line (ConvertTo-Json -InputObject $payload -Compress -Depth 6)
}

# --- load the library and every dependency sitting next to it ----------------
try {
    Get-ChildItem -Path $LibDir -Filter *.dll -ErrorAction SilentlyContinue | ForEach-Object {
        try { [void][System.Reflection.Assembly]::LoadFrom($_.FullName) } catch { }
    }
    Add-Type -Path (Join-Path $LibDir 'LibreHardwareMonitorLib.dll')
}
catch {
    Send-Error "cannot load LibreHardwareMonitorLib: $($_.Exception.Message)"
    exit 1
}

# --- open the hardware tree ---------------------------------------------------
$computer = $null
try {
    $computer = New-Object LibreHardwareMonitor.Hardware.Computer
    $computer.IsCpuEnabled = $true
    $computer.IsGpuEnabled = $true
    $computer.IsMotherboardEnabled = [bool]$Motherboard
    $computer.IsMemoryEnabled = [bool]$Memory
    $computer.IsStorageEnabled = [bool]$Storage
    $computer.IsNetworkEnabled = [bool]$Network
    $computer.IsControllerEnabled = [bool]$Controller
    $computer.IsPsuEnabled = [bool]$Psu
    $computer.Open()
}
catch {
    Send-Error "cannot open hardware tree: $($_.Exception.Message)"
    exit 1
}

function Update-Tree($hardware) {
    try { $hardware.Update() } catch { }
    foreach ($sub in $hardware.SubHardware) { Update-Tree $sub }
}

function Collect-Sensors($hardware, $bag) {
    foreach ($sensor in $hardware.Sensors) {
        $value = $null
        if ($null -ne $sensor.Value) {
            $value = [math]::Round([double]$sensor.Value, 3)
        }
        $item = [pscustomobject]@{
            Hardware     = $hardware.Name
            HardwareType = $hardware.HardwareType.ToString()
            Identifier   = $hardware.Identifier.ToString()
            Name         = $sensor.Name
            SensorType   = $sensor.SensorType.ToString()
            Value        = $value
        }
        [void]$bag.Add($item)
    }
    foreach ($sub in $hardware.SubHardware) { Collect-Sensors $sub $bag }
}

# --- request loop -------------------------------------------------------------
while ($true) {
    $request = [Console]::In.ReadLine()
    if ($null -eq $request) { break }
    if ($request -eq 'q') { break }

    try {
        foreach ($hardware in $computer.Hardware) { Update-Tree $hardware }

        $bag = New-Object System.Collections.ArrayList
        foreach ($hardware in $computer.Hardware) { Collect-Sensors $hardware $bag }

        $payload = [pscustomobject]@{
            Ok      = $true
            Error   = $null
            Sensors = $bag.ToArray()
        }
        Write-Line (ConvertTo-Json -InputObject $payload -Compress -Depth 6)
    }
    catch {
        Send-Error "poll failed: $($_.Exception.Message)"
    }
}

try { $computer.Close() } catch { }
