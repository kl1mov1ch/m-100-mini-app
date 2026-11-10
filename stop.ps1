$ErrorActionPreference = 'Stop'
$projectPath = $PSScriptRoot
foreach ($serviceName in @('frontend','backend')) {
    $pidPath = Join-Path $projectPath "data\$serviceName.pid"
    if (-not (Test-Path -LiteralPath $pidPath)) { continue }
    $servicePid = [int](Get-Content -LiteralPath $pidPath)
    $serviceProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $servicePid" -ErrorAction SilentlyContinue
    $ownsLocalFrontend = $false
    if ($serviceName -eq 'frontend' -and $serviceProcess -and $serviceProcess.CommandLine -match 'node_modules[/\\]vite[/\\]bin[/\\]vite.js') {
        $ownsLocalFrontend = @((Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue) | Where-Object { $_.OwningProcess -eq $servicePid }).Count -gt 0
    }
    # Validate ownership in case Windows has reused the recorded process ID.
    if ($serviceProcess -and ($serviceProcess.CommandLine -like "*$projectPath*" -or $serviceProcess.ExecutablePath -like "$projectPath\*" -or $ownsLocalFrontend)) {
        $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $servicePid" -ErrorAction SilentlyContinue)
        foreach ($child in $children) {
            if ($child.CommandLine -match 'uvicorn|vite') { Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue }
        }
        Stop-Process -Id $servicePid -Force -ErrorAction SilentlyContinue
    }
}
Write-Host 'M-100 processes stopped. Your reports remain in data/m100.sqlite3.'
