$ErrorActionPreference = 'Stop'
$app = $PSScriptRoot
$download = Join-Path $app 'tools\downloads'
New-Item -ItemType Directory -Force -Path $download | Out-Null

if (Get-Command py -ErrorAction SilentlyContinue) { $py = 'py'; $pyArgs = @('-3') }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $py = (Get-Command python).Source; $pyArgs = @() }
else { throw '请先安装 Python 3，并勾选 Add Python to PATH。' }

$venv = Join-Path $app '.venv'
if (-not (Test-Path (Join-Path $venv 'Scripts\python.exe'))) { & $py @pyArgs -m venv $venv }
$python = Join-Path $venv 'Scripts\python.exe'
& $python -m pip install --disable-pip-version-check --upgrade pip
& $python -m pip install --disable-pip-version-check -r (Join-Path $app 'requirements.txt')

$electron = Join-Path $app 'desktop\runtime\electron.exe'
if (-not (Test-Path $electron)) {
  $zip = Join-Path $download 'electron-v44.3.0-win32-x64.zip'
  if (-not (Test-Path $zip)) { Invoke-WebRequest 'https://github.com/electron/electron/releases/download/v44.3.0/electron-v44.3.0-win32-x64.zip' -OutFile $zip }
  $expanded = Join-Path $download 'electron'
  if (-not (Test-Path $expanded)) { Expand-Archive $zip -DestinationPath $expanded -Force }
  $folder = Get-ChildItem $expanded -Directory | Select-Object -First 1
  if (-not $folder) { throw 'Electron 安装包内容无效。' }
  New-Item -ItemType Directory -Force -Path (Split-Path $electron) | Out-Null
  Copy-Item (Join-Path $folder.FullName '*') (Split-Path $electron) -Recurse -Force
}

$ffmpeg = Join-Path $app 'tools\ffmpeg\bin\ffmpeg.exe'
if (-not (Test-Path $ffmpeg)) {
  $zip = Join-Path $download 'ffmpeg-release-essentials.zip'
  if (-not (Test-Path $zip)) { Invoke-WebRequest 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $zip }
  $expanded = Join-Path $download 'ffmpeg'
  if (-not (Test-Path $expanded)) { Expand-Archive $zip -DestinationPath $expanded -Force }
  $file = Get-ChildItem $expanded -Recurse -Filter ffmpeg.exe | Select-Object -First 1
  if (-not $file) { throw 'FFmpeg 安装包内容无效。' }
  New-Item -ItemType Directory -Force -Path (Split-Path $ffmpeg) | Out-Null
  Copy-Item $file.FullName $ffmpeg -Force
  $probe = Join-Path $file.DirectoryName 'ffprobe.exe'
  if (Test-Path $probe) { Copy-Item $probe (Join-Path (Split-Path $ffmpeg) 'ffprobe.exe') -Force }
}

$bbdown = Join-Path $app 'tools\BBDown\BBDown.exe'
if (-not (Test-Path $bbdown)) {
  $release = Invoke-RestMethod 'https://api.github.com/repos/nilaoda/BBDown/releases/latest'
  $asset = $release.assets | Where-Object { $_.name -match '(?i)win.*x64.*zip|x64.*win.*zip' } | Select-Object -First 1
  if (-not $asset) { throw '未找到 BBDown Windows x64 安装包。' }
  $zip = Join-Path $download $asset.name
  if (-not (Test-Path $zip)) { Invoke-WebRequest $asset.browser_download_url -OutFile $zip }
  $expanded = Join-Path $download 'BBDown'
  if (-not (Test-Path $expanded)) { Expand-Archive $zip -DestinationPath $expanded -Force }
  $file = Get-ChildItem $expanded -Recurse -Filter BBDown.exe | Select-Object -First 1
  if (-not $file) { throw 'BBDown 安装包内容无效。' }
  New-Item -ItemType Directory -Force -Path (Split-Path $bbdown) | Out-Null
  Copy-Item $file.FullName $bbdown -Force
}

& $python (Join-Path $app 'setup_portable.py') --python $python --ffmpeg $ffmpeg --bbdown $bbdown
Write-Host '安装完成。' -ForegroundColor Green
