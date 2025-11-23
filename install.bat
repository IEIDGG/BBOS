@echo off
setlocal
cd /d "%~dp0"
echo Checking for virtual environment
if exist venv (
  echo Virtual environment already exists
) else (
  echo Creating virtual environment
  py -3 -m venv venv
  if errorlevel 1 (
    echo py command failed, trying python
    python -m venv venv
    if errorlevel 1 (
      echo Could not create a virtual environment. Make sure Python 3 is installed and added to PATH.
      pause
      exit /b 1
    )
  )
)
echo Installing or updating pip
venv\Scripts\python -m pip install --upgrade pip
if errorlevel 1 (
  echo Pip upgrade failed inside the virtual environment.
  pause
  exit /b 1
)
echo Installing required packages from requirements.txt
venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Package installation failed. Check the error messages above.
  pause
  exit /b 1
)
echo Installation completed successfully.
echo You can now run the program by activating the virtual environment and running python main.py
pause
endlocal


