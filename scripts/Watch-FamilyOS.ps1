# Per-user logon supervisor. Recheck both processes after crashes; never opens a browser.
$ErrorActionPreference = 'Stop'
$mutex = New-Object System.Threading.Mutex($false, 'Local\FamilyOSLocalSupervisor')
$held = $false
try {
    $held = $mutex.WaitOne(0)
    if (-not $held) { exit 0 }
    while ($true) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'Start-FamilyOS.ps1') -NoBrowser
        Start-Sleep -Seconds 30
    }
} finally {
    if ($held) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
