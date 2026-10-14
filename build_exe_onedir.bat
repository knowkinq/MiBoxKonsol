@echo off
REM MiBox Konsol - ONEDIR (klasor) paket uretir (64-bit ve 32-bit x86 otomatik algilar).
REM Kullanim: build_exe_onedir.bat
setlocal
cd /d "%~dp0"

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)

if not defined PY (
  echo [HATA] Python bulunamadi. Kurun: winget install Python.Python.3
  pause
  exit /b 1
)

REM --- Mimari tespiti (32-bit x86 / 64-bit x64) ---
set "PY_BITS=64"
for /f "tokens=*" %%a in ('"%PY%" -c "import struct; print(struct.calcsize('P')*8)" 2^>nul') do set "PY_BITS=%%a"

echo ========================================================
echo   MiBox Konsol ONEDIR - %PY_BITS%-bit mimari algilandi
echo ========================================================

if "%PY_BITS%"=="32" goto :setup_32
goto :setup_64

:setup_32
echo [BILGI] 32-bit [x86] Windows icin bagimliliklar denetleniyor...
"%PY%" -c "import PyQt5" >nul 2>nul
if errorlevel 1 (
  echo PyQt5 kuruluyor...
  "%PY%" -m pip install "PyQt5>=5.15"
  if errorlevel 1 goto :build_failed
)
goto :check_pyinstaller

:setup_64
echo [BILGI] 64-bit [x64] Windows icin bagimliliklar denetleniyor...
"%PY%" -c "import PySide6" >nul 2>nul
if errorlevel 1 (
  echo PySide6 kuruluyor...
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 goto :build_failed
)
goto :check_pyinstaller

:check_pyinstaller

"%PY%" -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
  echo PyInstaller bulunamadi. Kuruluyor...
  "%PY%" -m pip install pyinstaller
  if errorlevel 1 goto :build_failed
)

"%PY%" tools\build_onedir.py
if errorlevel 1 (
  goto :build_failed
)

echo.
echo TAMAM: dist-onedir\MiBoxKonsol\MiBoxKonsol.exe
echo Not: adb.exe dosyasini bu klasore de kopyalayin.
pause
exit /b 0

:build_failed
echo.
echo Derleme basarisiz.
pause
exit /b 1
