param([switch]$Restart)
$ErrorActionPreference = 'Stop'
$projectPath = $PSScriptRoot
Set-Location -LiteralPath $projectPath
$pythonPath = Join-Path $projectPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Install Python dependencies first. See README.md.' }
if (-not (Test-Path -LiteralPath 'frontend\node_modules\vite\bin\vite.js')) { throw 'Install frontend dependencies first. See README.md.' }
New-Item -ItemType Directory -Path 'data' -Force | Out-Null
if ($Restart) { & (Join-Path $projectPath 'stop.ps1') }
function Test-LocalService([string]$url) {
    try { return (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { return $false }
}
if (-not (Test-LocalService 'http://127.0.0.1:8000/api/bootstrap')) {
    $backendProcess = Start-Process -FilePath $pythonPath -ArgumentList '-m','uvicorn','backend.app:app','--host','127.0.0.1','--port','8000' -WorkingDirectory $projectPath -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectPath 'data\backend.log') -RedirectStandardError (Join-Path $projectPath 'data\backend-error.log') -PassThru
    $backendProcess.Id | Set-Content -LiteralPath 'data\backend.pid'
}
if (-not (Test-LocalService 'http://127.0.0.1:5173/')) {
    $nodePath = (Get-Command node -ErrorAction Stop).Source
    $viteScript = '"' + (Join-Path $projectPath 'frontend\node_modules\vite\bin\vite.js') + '"'
    $frontendProcess = Start-Process -FilePath $nodePath -ArgumentList $viteScript,'--host','127.0.0.1','--port','5173','--strictPort','--force' -WorkingDirectory (Join-Path $projectPath 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectPath 'data\frontend.log') -RedirectStandardError (Join-Path $projectPath 'data\frontend-error.log') -PassThru
    $frontendProcess.Id | Set-Content -LiteralPath 'data\frontend.pid'
}
$ready = $false
for ($attempt = 0; $attempt -lt 15; $attempt++) {
    if ((Test-LocalService 'http://127.0.0.1:8000/api/bootstrap') -and (Test-LocalService 'http://127.0.0.1:5173/')) { $ready = $true; break }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) { throw 'Could not start the app. Check data/backend-error.log and data/frontend-error.log.' }
Write-Host 'M-100 is ready: http://127.0.0.1:5173/'
Write-Host 'Mobile view: http://127.0.0.1:5173/?phone=1'
Write-Host 'Run stop.ps1 to stop the app. Source edits appear automatically in the frontend.'
