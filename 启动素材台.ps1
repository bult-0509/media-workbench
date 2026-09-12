$ErrorActionPreference = 'Stop'
$app = $PSScriptRoot
$config = Get-Content -Raw -Encoding UTF8 (Join-Path $app 'config.json') | ConvertFrom-Json
$url = 'http://127.0.0.1:' + $config.port
try { $ok = (Invoke-RestMethod ($url + '/api/health') -TimeoutSec 2).app -eq 'local-media-workbench' } catch { $ok = $false }
if (-not $ok) {
  $data = Join-Path $app 'data'
  New-Item -ItemType Directory -Force -Path $data | Out-Null
  Start-Process $config.python -ArgumentList 'server.py' -WorkingDirectory $app -WindowStyle Hidden
  for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    try { if ((Invoke-RestMethod ($url + '/api/health') -TimeoutSec 1).app -eq 'local-media-workbench') { $ok = $true; break } } catch {}
  }
}
if (-not $ok) { throw '素材台服务未能启动。' }
$electron = Join-Path $app 'desktop\runtime\electron.exe'
if (Test-Path $electron) { Start-Process $electron -ArgumentList (Join-Path $app 'desktop') -WorkingDirectory $app }
else { Start-Process $url }
