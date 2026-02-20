@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0"

if not exist ".venv" (
  py -3 -m venv .venv
)

call .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

if exist "app.ico" (
  pyinstaller -F -c workshop_downloader.py --name FanWorkshopDL --icon app.ico --version-file version.txt
) else (
  pyinstaller -F -c workshop_downloader.py --name FanWorkshopDL --version-file version.txt
)

echo.
echo Build done: dist\FanWorkshopDL.exe
pause

