@echo off
REM MiBox Konsol - ONEDIR paketini kurar (kalici konum + kisayol).
REM Kullanim: kur_onedir.bat
REM Onedir paket gecici klasor ACMAZ; bu yuzden %TEMP% kisitlamasi olan
REM makinelerde onefile yerine bunu kullanin.
setlocal
cd /d "%~dp0"

if not exist "dist-onedir\MiBoxKonsol\MiBoxKonsol.exe" (
  echo Onedir paket yok, derleniyor...
  set "PY="
  if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"
  if not defined PY where python >nul 2>nul && set "PY=python"
  if not defined PY (
    echo [HATA] Python bulunamadi.
    pause
    exit /b 1
  )
  %PY% tools\build_onedir.py
  if errorlevel 1 (
    echo [HATA] Derleme basarisiz.
    pause
    exit /b 1
  )
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\kur_onedir.ps1"
if errorlevel 1 (
  echo.
  echo [HATA] Kurulum tamamlanmadi.
  pause
  exit /b 1
)
pause
exit /b 0
