# BBOS

BBOS is a Python program that works with order and email data.  
This guide is written for people who have never used Python before.

---

## 1. What you need before starting

- A Windows computer
- An internet connection
- Permission to install programs on your computer

You do not need to know any programming.

---

## 2. Install Python

1. Open your web browser.
2. Go to the official Python website: `https://www.python.org/downloads/windows/`.
3. Download the latest stable Python 3 release for Windows.
4. Run the installer.
5. On the first screen, make sure you check the box that says:
   - `Add Python to PATH`
6. Click `Install Now` and wait for it to finish.

To confirm Python is installed:

1. Press the Windows key on your keyboard.
2. Type `cmd` and press Enter.
3. In the black window that opens, type:
   - `py --version`
4. Press Enter.

If you see a version number (for example `Python 3.11.x`), Python is installed correctly.

---

## 3. Download or get this project

If you already have the project folder on your computer, you can skip to section 4.

Otherwise:

1. Go to the project’s page where it is stored (for example GitHub).
2. Download it as a ZIP file.
3. Right-click the ZIP file and choose `Extract All`.
4. Choose a location you can find easily, such as `C:\Python_Programs\`.

After extracting, you should see a folder similar to:

- `BBOS Enhanced 2\BBOS`

The folder that contains files like `main.py` and `requirements.txt` is the project folder.

---

## 4. One-time setup using install.bat

Inside the project folder, there is a file named:

- `install.bat`

This file will:

- Create a Python virtual environment in a folder named `venv`
- Install all required Python packages from `requirements.txt`

To run it:

1. Open File Explorer.
2. Go to the project folder that contains `install.bat`, `main.py`, and `requirements.txt`.
3. Double-click `install.bat`.
4. A black window will open and show messages such as:
   - Creating a virtual environment
   - Installing packages
5. Wait until it says the installation is complete.
6. Press any key if it asks you to.

You only need to do this once, or again if something goes wrong with your Python setup.

---

## 5. Starting the program

After the installation has finished, you can run the program.

### 5.1 Open PowerShell in the project folder

1. Open File Explorer and go to the project folder (the one with `main.py`).
2. Click inside the address bar at the top.
3. Type `powershell` and press Enter.

PowerShell will open already in the correct folder.

### 5.2 Activate the virtual environment

In the PowerShell window, type:

- `.\venv\Scripts\Activate.ps1`

Press Enter.

If it works, you will see `(venv)` at the beginning of the line in PowerShell.  
This means the project’s Python environment is active.

If you get an error about scripts being disabled, you may need to allow running local scripts:

1. Close PowerShell.
2. Open a new PowerShell window **as Administrator**.
3. Type:
   - `Set-ExecutionPolicy RemoteSigned`
4. Press Enter and choose `Y` to confirm.
5. Close that window.
6. Open PowerShell again in the project folder and try:
   - `.\venv\Scripts\Activate.ps1`

### 5.3 Run the main program

With `(venv)` showing in PowerShell, type:

- `python main.py`

Press Enter.

The program will start. Follow any instructions shown on the screen.

Each time you want to use the program later:

1. Open PowerShell in the project folder.
2. Activate the virtual environment:
   - `.\venv\Scripts\Activate.ps1`
3. Run:
   - `python main.py`

---

## 6. Updating the project

If you download a new version of this project in the future:

1. Replace the old project folder with the new one, or extract the new version into a different folder.
2. Run `install.bat` again in the new project folder.

This will make sure your Python packages match the version of the code you are using.

---

## 7. Common problems and quick checks

- If `install.bat` closes immediately:
  - Open a Command Prompt window manually.
  - Use `cd` to go to the project folder.
  - Type `install.bat` and press Enter to see any error messages.

- If you see a message saying Python is not found:
  - Make sure you installed Python and checked `Add Python to PATH`.
  - Close all Command Prompt and PowerShell windows and open a new one.
  - Run `py --version` to verify it works.

- If packages fail to install:
  - Check that your internet connection is working.
  - Run `install.bat` again.

If you are stuck, take a screenshot of the error message and share it with someone who can help. The messages shown by `install.bat` and the program are designed to make it easier to understand what went wrong.


