param([switch]$NoBrowser, [switch]$NoWorker)
$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $appRoot '.venv\Scripts\python.exe'
$logDirectory = Join-Path $appRoot 'instance'
$lock = New-Object System.Threading.Mutex($false, 'Local\FamilyOSLocalLauncher')
$acquired = $false
try {
    $acquired = $lock.WaitOne(0)
    if (-not $acquired) { exit 0 }
    if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'FamilyOS Python environment is missing.' }
    # Read persisted settings on every launch, even from an older Windows session.
    $savedSettings = [Environment]::GetEnvironmentVariables('User')
    foreach ($name in $savedSettings.Keys) {
        if ($name -like 'FAMILYOS_*') {
            [Environment]::SetEnvironmentVariable($name, $savedSettings[$name], 'Process')
        }
    }
    $env:FAMILYOS_ENV = 'development'
    $env:FAMILYOS_DATA_DIR = Join-Path $appRoot 'instance'
    $env:FAMILYOS_GMAIL_CLIENT_FILE = Join-Path $appRoot 'instance\gmail-client.json'
    $env:FAMILYOS_GMAIL_REDIRECT_URI = 'http://localhost:8000/vault/gmail/callback/'
    foreach ($name in @('FAMILYOS_SECRET_KEY', 'FAMILYOS_VAULT_KEY', 'FAMILYOS_VAULT_ROOT', 'FAMILYOS_CLAMD_HOST')) {
        if (-not [Environment]::GetEnvironmentVariable($name, 'Process')) {
            throw "Required saved setting is missing: $name. Restore the original setting; do not replace the Vault key."
        }
    }
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    # Use the installed local scanner and its existing configuration/signatures.
    # A remote scanner remains the operator's responsibility.
    $scannerRoot = Join-Path $env:ProgramFiles 'ClamAV'
    $scannerExe = Join-Path $scannerRoot 'clamd.exe'
    if ($env:FAMILYOS_CLAMD_HOST -in @('localhost', '127.0.0.1') -and (Test-Path -LiteralPath $scannerExe)) {
        $scanner = Get-CimInstance Win32_Process -Filter "name = 'clamd.exe'" | Where-Object { $_.ExecutablePath -eq $scannerExe }
        if (-not $scanner) {
            Start-Process -FilePath $scannerExe -ArgumentList @('--config-file', ('"' + (Join-Path $scannerRoot 'clamd.conf') + '"')) -WorkingDirectory $scannerRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'scanner-output.log') -RedirectStandardError (Join-Path $logDirectory 'scanner-error.log') | Out-Null
        }
    }
    $listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        $processes = Get-CimInstance Win32_Process
        # Windows virtualenv Python delegates to its base interpreter; validate
        # the listener's parent in that case, as well as its server arguments.
        $venvParents = @($processes | Where-Object { $_.ExecutablePath -eq $pythonPath }).ProcessId
        $server = $processes | Where-Object {
            $_.ProcessId -in $listener.OwningProcess -and ($_.ExecutablePath -eq $pythonPath -or $_.ParentProcessId -in $venvParents) -and
            $_.CommandLine -match 'waitress' -and $_.CommandLine -match 'config.wsgi:application'
        }
        if (-not $server -or ($listener | Where-Object { $_.LocalAddress -ne '127.0.0.1' })) {
            throw 'Port 8000 belongs to another application or is not loopback-only.'
        }
    }
    if (-not $listener) {
        Start-Process -FilePath $pythonPath -ArgumentList @('-m', 'waitress', '--listen=127.0.0.1:8000', 'config.wsgi:application') -WorkingDirectory $appRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'server-output.log') -RedirectStandardError (Join-Path $logDirectory 'server-error.log') | Out-Null
    }
    $workerPath = Join-Path $appRoot 'manage.py'
    $worker = Get-CimInstance Win32_Process -Filter "name = 'python.exe'" | Where-Object {
        $_.CommandLine -and $_.CommandLine.Contains($workerPath) -and $_.CommandLine.Contains('sync_gmail')
    }
    if (-not $worker -and -not $NoWorker) {
        Start-Process -FilePath $pythonPath -ArgumentList @(('"' + $workerPath + '"'), 'sync_gmail') -WorkingDirectory $appRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'gmail-worker-output.log') -RedirectStandardError (Join-Path $logDirectory 'gmail-worker-error.log') | Out-Null
    }
    $ready = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        try {
            $response = Invoke-WebRequest 'http://127.0.0.1:8000/login/' -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200 -and $response.Content -match 'FamilyOS') { $ready = $true; break }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw 'FamilyOS did not become ready. Check instance/server-error.log.' }
    if (-not $NoBrowser) { Start-Process 'http://localhost:8000/vault/' }
} catch {
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    Add-Content -LiteralPath (Join-Path $logDirectory 'launcher-error.log') -Value ((Get-Date -Format o) + ' ' + $_.Exception.Message)
    if ($NoBrowser) { exit 1 }
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'FamilyOS startup needs attention') | Out-Null
    exit 1
} finally {
    if ($acquired) { $lock.ReleaseMutex() }
    $lock.Dispose()
}
