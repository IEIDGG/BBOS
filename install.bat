@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "UV_EXE=uv"
where uv >nul 2>nul
if errorlevel 1 (
  echo uv not found, installing it now
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  if errorlevel 1 (
    echo Could not install uv. Check your internet connection and try again.
    pause
    exit /b 1
  )
  set "UV_EXE=%USERPROFILE%\.local\bin\uv.exe"
  if not exist "!UV_EXE!" (
    echo uv was installed but could not be found at the expected location.
    echo Please close this window, open a new one, and run install.bat again.
    pause
    exit /b 1
  )
)

echo Setting up Python and installing required packages
"!UV_EXE!" sync
if errorlevel 1 (
  echo Setup failed. Check the error messages above.
  pause
  exit /b 1
)

echo.
echo Installation completed successfully.
echo You can now run the program by double-clicking run.bat
pause
endlocal
