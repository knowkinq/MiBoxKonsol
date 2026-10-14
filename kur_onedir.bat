@echo off
REM MiBox Konsol - ONEDIR paketini kurar (kalici konum + kisayol).
REM Kullanim: kur_onedir.bat
REM Onedir paket gecici klasor ACMAZ; bu yuzden %TEMP% kisitlamasi olan
REM makinelerde onefile yerine bunu kullanin.
setlocal
cd /d "%~dp0"

if exist "dist-onedir\MiBoxKonsol\MiBoxKonsol.exe" goto :install

echo Onedir paket yok, derleniyor...
set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo [HATA] Python bulunamadi.
  pause
  exit /b 1
)
REM --- Mimari tespiti (32-bit x86 veya 64-bit x64) ---
set "PY_BITS=64"
for /f "tokens=*" %%a in ('"%PY%" -c "import struct; print(struct.calcsize('P')*8)" 2^>nul') do set "PY_BITS=%%a"

if "%PY_BITS%"=="32" goto :deps_32
goto :deps_64

:deps_32
"%PY%" -c "import PyQt5" >nul 2>nul
if errorlevel 1 (
  echo 32-bit Qt5 bileseni [PyQt5] bulunamadi. Kuruluyor...
  "%PY%" -m pip install "PyQt5>=5.15"
  if errorlevel 1 (
    echo [HATA] 32-bit bagimliliklar kurulamadi.
    pause
    exit /b 1
  )
)
goto :check_pyinstaller

:deps_64
"%PY%" -c "import PySide6" >nul 2>nul
if errorlevel 1 (
  echo PySide6 bulunamadi. Bagimliliklar kuruluyor...
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [HATA] Bagimliliklar kurulamadi.
    pause
    exit /b 1
  )
)
goto :check_pyinstaller

:check_pyinstaller
"%PY%" -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
  echo PyInstaller bulunamadi. Kuruluyor...
  "%PY%" -m pip install pyinstaller
  if errorlevel 1 (
    echo [HATA] PyInstaller kurulamadi.
    pause
    exit /b 1
  )
)
"%PY%" tools\build_onedir.py
if errorlevel 1 (
  echo [HATA] Derleme basarisiz.
  pause
  exit /b 1
)

:install
if not exist "dist-onedir\MiBoxKonsol\MiBoxKonsol.exe" (
  echo [HATA] Paket bulunamadi.
  pause
  exit /b 1
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
