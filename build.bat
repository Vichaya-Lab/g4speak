@echo off
python -m pip install -r requirements.txt pyinstaller || exit /b 1
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build-release.ps1 || exit /b 1
echo Build complete: dist\G4Speak.exe and dist\G4Speak-Setup-1.2.1.exe
