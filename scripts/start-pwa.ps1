param([switch]$UseGoogle, [switch]$WithTraining, [switch]$Production, [ValidateRange(0,65535)][int]$Port=0)
$ErrorActionPreference = 'Stop'
$pwaRoot = Split-Path -Parent $PSScriptRoot
$pwaDirectory = Join-Path $pwaRoot 'pwa'
$pwaPython = Join-Path $pwaRoot '.venv-pwa/Scripts/python.exe'
$pwaLogs = Join-Path $pwaRoot 'data/pwa/logs'
$pwaRegistry = Join-Path $pwaRoot 'data/pwa/processes.json'
New-Item -ItemType Directory -Path $pwaLogs -Force | Out-Null
$pwaProcesses = @()
$pwaPort = if ($Port -gt 0) { $Port } elseif ($Production) { 3001 } else { 3000 }
if ($pwaPort -lt 1024) { throw 'Choose a port between 1024 and 65535.' }
if ($Production) { $pwaDistDir = '.next-performance' }
if (Test-Path -LiteralPath $pwaRegistry) {
    $pwaProcesses = @(Get-Content -LiteralPath $pwaRegistry -Raw | ConvertFrom-Json)
}
function Save-PwaRegistry {
    ConvertTo-Json -InputObject @($pwaProcesses) | Set-Content -LiteralPath $pwaRegistry -Encoding utf8
}
if (-not (Test-Path -LiteralPath $pwaPython)) { throw 'Create .venv-pwa and install backend/requirements.txt first. See pwa/README.md.' }
$pwaNode = (Get-Command node).Source
$pwaNext = Join-Path $pwaDirectory 'node_modules/next/dist/bin/next'
if (-not (Test-Path -LiteralPath $pwaNext)) { throw 'Run npm ci in pwa first.' }
& $pwaNode (Join-Path $pwaDirectory 'scripts/prepare-avatar.mjs')
if ($LASTEXITCODE -ne 0) { throw 'Avatar asset preparation failed.' }
$pwaProcesses = @()
try {
    $pwaHealth = Invoke-RestMethod 'http://127.0.0.1:8765/health' -TimeoutSec 2
    if (-not $pwaHealth.ok -or $pwaHealth.service -ne 'dosym-pwa-backend') { throw 'Port 8765 is occupied by another service.' }
    Write-Host 'Backend is already running; reusing it.'
} catch {
    if ($_.Exception.Message -like '*another service*') { throw }
    $pwaArguments = @('-m', 'backend.run')
    if (-not $UseGoogle) { $pwaArguments += '--local-demo' }
    $pwaProcess = Start-Process -FilePath $pwaPython -ArgumentList $pwaArguments -WorkingDirectory $pwaRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $pwaLogs 'backend.out.log') -RedirectStandardError (Join-Path $pwaLogs 'backend.err.log')
    $pwaProcesses += @{ id=$pwaProcess.Id; kind='backend.run' }
    Save-PwaRegistry
}
try {
    $pwaPage = Invoke-WebRequest "http://127.0.0.1:$pwaPort" -TimeoutSec 2
    if ($pwaPage.Content -notmatch 'DosYm') { throw "Port $pwaPort is occupied by another application." }
    Write-Host "PWA is already running on port $pwaPort; reusing it."
} catch {
    if ($_.Exception.Message -like '*another application*') { throw }
    if ($Production) {
        $pwaPreviousDist = $env:DOSYM_NEXT_DIST_DIR
        $env:DOSYM_NEXT_DIST_DIR = $pwaDistDir
        try {
            Push-Location $pwaDirectory
            & npm run build
            if ($LASTEXITCODE -ne 0) { throw 'Production build failed; the server was not started.' }
        } finally {
            Pop-Location
            if ($null -eq $pwaPreviousDist) { Remove-Item Env:DOSYM_NEXT_DIST_DIR -ErrorAction SilentlyContinue }
            else { $env:DOSYM_NEXT_DIST_DIR = $pwaPreviousDist }
        }
        $pwaPreviousDist = $env:DOSYM_NEXT_DIST_DIR
        $env:DOSYM_NEXT_DIST_DIR = $pwaDistDir
        try {
            $pwaProcess = Start-Process -FilePath $pwaNode -ArgumentList @("`"$pwaNext`"", 'start', '--hostname', '127.0.0.1', '--port', [string]$pwaPort) -WorkingDirectory $pwaDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $pwaLogs 'web-production.out.log') -RedirectStandardError (Join-Path $pwaLogs 'web-production.err.log')
        } finally {
            if ($null -eq $pwaPreviousDist) { Remove-Item Env:DOSYM_NEXT_DIST_DIR -ErrorAction SilentlyContinue }
            else { $env:DOSYM_NEXT_DIST_DIR = $pwaPreviousDist }
        }
        $pwaKind = 'next-production'
    } else {
        $pwaProcess = Start-Process -FilePath $pwaNode -ArgumentList @("`"$pwaNext`"", 'dev', '--hostname', '127.0.0.1', '--port', [string]$pwaPort) -WorkingDirectory $pwaDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $pwaLogs 'web.out.log') -RedirectStandardError (Join-Path $pwaLogs 'web.err.log')
        $pwaKind = 'next-dev'
    }
    $pwaProcesses += @{ id=$pwaProcess.Id; kind=$pwaKind; port=$pwaPort }
    Save-PwaRegistry
}
if ($WithTraining) {
    $pwaTrainer = Join-Path $pwaRoot '.venv-train/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $pwaTrainer)) { throw 'Create the separate TensorFlow environment first.' }
    $pwaProcess = Start-Process -FilePath $pwaTrainer -ArgumentList @('-m','backend.training') -WorkingDirectory $pwaRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $pwaLogs 'training.out.log') -RedirectStandardError (Join-Path $pwaLogs 'training.err.log')
    $pwaProcesses += @{ id=$pwaProcess.Id; kind='backend.training' }
    Save-PwaRegistry
}
Write-Host "Open http://127.0.0.1:$pwaPort . Services bind only to this computer."
if ($Production) { Write-Host 'Production mode uses .next-performance; the development server and .next directory are left untouched.' }
if (-not $UseGoogle) { Write-Host 'Local test identities enabled; this is not Google sign-in and not cloud Drive.' }
