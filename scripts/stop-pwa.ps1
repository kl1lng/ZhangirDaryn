$ErrorActionPreference = 'Stop'
$pwaRoot = Split-Path -Parent $PSScriptRoot
$pwaFile = Join-Path $pwaRoot 'data/pwa/processes.json'
if (-not (Test-Path -LiteralPath $pwaFile)) { Write-Host 'No processes recorded by start-pwa.ps1.'; exit }
$pwaSnapshot = @(Get-CimInstance Win32_Process)
foreach ($pwaEntry in @(Get-Content -LiteralPath $pwaFile -Raw | ConvertFrom-Json)) {
    $pwaProcess = $pwaSnapshot | Where-Object ProcessId -eq ([int]$pwaEntry.id) | Select-Object -First 1
    if (-not $pwaProcess) { continue }
    $pwaCommand = [string]$pwaProcess.CommandLine
    $pwaExpected = switch ($pwaEntry.kind) {
        'backend.run' { $pwaCommand -match [regex]::Escape($pwaRoot) -and $pwaCommand -match 'backend\.run' }
        'backend.training' { $pwaCommand -match [regex]::Escape($pwaRoot) -and $pwaCommand -match 'backend\.training' }
        'next' { $pwaCommand -match [regex]::Escape($pwaRoot) -and $pwaCommand -match 'next.*dev.*127\.0\.0\.1' }
        'next-dev' { $pwaCommand -match [regex]::Escape($pwaRoot) -and $pwaCommand -match 'next.*dev.*127\.0\.0\.1' }
        'next-production' { $pwaCommand -match [regex]::Escape($pwaRoot) -and $pwaCommand -match 'next.*start.*127\.0\.0\.1' }
        default { $false }
    }
    if (-not $pwaExpected) { Write-Warning "Not stopping PID $($pwaEntry.id); its command no longer matches the recorded DosYm service."; continue }
    $pwaTree = [System.Collections.Generic.HashSet[int]]::new()
    [void]$pwaTree.Add([int]$pwaEntry.id)
    do {
        $pwaAdded = $false
        foreach ($pwaChild in $pwaSnapshot) {
            if ($pwaTree.Contains([int]$pwaChild.ParentProcessId) -and $pwaTree.Add([int]$pwaChild.ProcessId)) { $pwaAdded = $true }
        }
    } while ($pwaAdded)
    foreach ($pwaPid in @($pwaTree | Where-Object { $_ -ne [int]$pwaEntry.id } | Sort-Object -Descending)) {
        Stop-Process -Id $pwaPid -ErrorAction SilentlyContinue
    }
    Stop-Process -Id ([int]$pwaEntry.id) -ErrorAction SilentlyContinue
    Write-Host "Stopped $($pwaEntry.kind)."
}
Remove-Item -LiteralPath $pwaFile
