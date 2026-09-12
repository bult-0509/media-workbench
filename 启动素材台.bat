@echo off
chcp 65001 >nul
if not exist "%~dp0.venv\Scripts\python.exe" call "%~dp0安装环境和依赖.bat"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0启动素材台.ps1"
if errorlevel 1 pause
