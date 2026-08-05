# BBOS

BBOS is a Python program that works with order and email data.  
This guide is written for people who have never used Python before.

---

## 1. What you need before starting

- A Windows computer
- An internet connection
- Permission to install programs on your computer

You do not need to know any programming, and you do not need to install Python yourself — `install.bat` takes care of that for you.

---

## 2. Download or get this project

If you already have the project folder on your computer, you can skip to section 3.

Otherwise:

1. Go to the project’s page where it is stored (for example GitHub).
2. Download it as a ZIP file.
3. Right-click the ZIP file and choose `Extract All`.
4. Choose a location you can find easily, such as `C:\Python_Programs\`.

After extracting, you should see a folder similar to:

- `BBOS Enhanced 2\BBOS`

The folder that contains files like `main.py` and `install.bat` is the project folder.

---

## 3. One-time setup using install.bat

Inside the project folder, there is a file named:

- `install.bat`

This file will:

- Install a small tool called `uv` if it isn't already on your computer (this is what sets up Python and the program's packages for you)
- Install the correct version of Python automatically
- Install all the packages the program needs

To run it:

1. Open File Explorer.
2. Go to the project folder that contains `install.bat` and `main.py`.
3. Double-click `install.bat`.
4. A black window will open and show messages such as:
   - Installing uv (only the first time, on this computer)
   - Setting up Python and installing required packages
5. Wait until it says the installation is complete.
6. Press any key if it asks you to.

You only need to do this once, or again if something goes wrong with your setup.

If this is the very first time `uv` has been installed on this computer, `install.bat` may ask you to close the window and run it again — this lets Windows pick up the change. Just double-click `install.bat` a second time if that happens.

---

## 4. Starting the program

After the installation has finished, you can run the program.

1. Open File Explorer and go to the project folder (the one with `main.py`).
2. Double-click `run.bat`.

The program will start. Follow any instructions shown on the screen.

Each time you want to use the program later, just double-click `run.bat` again.

---

## 5. Updating the project

If you download a new version of this project in the future:

1. Replace the old project folder with the new one, or extract the new version into a different folder.
2. Run `install.bat` again in the new project folder.

This will make sure your packages match the version of the code you are using.

---

## 6. Common problems and quick checks

- If `install.bat` closes immediately:
  - Open a Command Prompt window manually.
  - Use `cd` to go to the project folder.
  - Type `install.bat` and press Enter to see any error messages.

- If `install.bat` says it installed `uv` but then can't find it:
  - Close the black window.
  - Double-click `install.bat` again — this lets Windows pick up the change from installing `uv`.

- If packages fail to install:
  - Check that your internet connection is working.
  - Run `install.bat` again.

If you are stuck, take a screenshot of the error message and share it with someone who can help. The messages shown by `install.bat` and the program are designed to make it easier to understand what went wrong.
