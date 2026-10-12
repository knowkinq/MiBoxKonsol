@echo off
REM MiBox Konsol - ONEDIR (klasor) paket uretir.
REM Neden: onefile paket %TEMP% altinda _MEI... klasoru acar; kisitli
REM makinede "Could not create temporary directory" hatasi verebilir.
REM onedir paket gecici klasor ACMAZ.
REM Kullanim: build_exe_onedir.bat
setlocal
cd /d "%~dp0"

set "PY="
if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"
if not defined PY where python >nul 2>nul && set "PY=python"

if not defined PY (
  echo [HATA] Python bulunamadi. Kurun: winget install Python.Python.3
  pause
  exit /b 1
)

%PY% tools\build_onedir.py
if errorlevel 1 (
  echo.
  echo Derleme basarisiz.
  pause
  exit /b 1
)

echo.
echo TAMAM: dist-onedir\MiBoxKonsol\MiBoxKonsol.exe
echo Not: adb.exe dosyasini bu klasore de kopyalayin.
pause
exit /b 0
