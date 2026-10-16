@echo off
python -m pip install -r requirements.txt pyinstaller || exit /b 1
python -m PyInstaller G4Speak.spec || exit /b 1
echo Build complete: dist\G4Speak.exe
