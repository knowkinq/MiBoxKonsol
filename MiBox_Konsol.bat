@echo off
setlocal
cd /d "%~dp0"

REM --- Python bul (.venv > venv > PATH) ---
set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)

if not defined PY (
  echo [HATA] Python bulunamadi.
  echo 64-bit icin: winget install Python.Python.3.12
  echo 32-bit icin: winget install Python.Python.3.12 --architecture x86
  echo Sonra: pip install -r requirements.txt
  pause
  exit /b 1
)

REM --- Mimari tespiti (32-bit x86 veya 64-bit x64) ---
set "PY_BITS=64"
for /f "tokens=*" %%a in ('"%PY%" -c "import struct; print(struct.calcsize('P')*8)" 2^>nul') do set "PY_BITS=%%a"

echo [BILGI] Python %PY_BITS%-bit tespit edildi.

if "%PY_BITS%"=="32" goto :env_32
goto :env_64

:env_32
REM --- 32-bit ortam: PyQt5 kontrolu ---
"%PY%" -c "import PyQt5" >nul 2>nul
if errorlevel 1 (
  echo [UYARI] 32-bit Qt5 bileseni [PyQt5] eksik. Kuruluyor...
  "%PY%" -m pip install "PyQt5>=5.15"
  if errorlevel 1 (
    echo [HATA] 32-bit bagimliliklar kurulamadi.
    pause
    exit /b 1
  )
)
goto :launch

:env_64
REM --- 64-bit ortam: PySide6 kontrolu ---
"%PY%" -c "import PySide6" >nul 2>nul
if errorlevel 1 (
  echo [UYARI] PySide6 eksik. Kuruluyor: pip install -r requirements.txt
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [HATA] Bagimliliklar kurulamadi.
    pause
    exit /b 1
  )
)
goto :launch

:launch
"%PY%" mibox.py %*
if errorlevel 1 (
  echo.
  echo [HATA] Konsol kapatildi veya hata verdi.
  pause
)
