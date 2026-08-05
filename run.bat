@echo off
setlocal
cd /d "%~dp0"

set "UV_EXE=uv"
where uv >nul 2>nul
if errorlevel 1 (
  set "UV_EXE=%USERPROFILE%\.local\bin\uv.exe"
  if not exist "%UV_EXE%" (
    echo uv was not found. Please run install.bat first.
    pause
    exit /b 1
  )
)

"%UV_EXE%" run python main.py
pause
endlocal
