@echo off
setlocal
cd /d "%~dp0"

REM --- Python bul (venv > PATH) ---
set "PY="
if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"
if not defined PY where python >nul 2>nul && set "PY=python"

if not defined PY (
  echo [HATA] Python bulunamadi. Kurun: winget install Python.Python.3.12
  echo Sonra: pip install -r requirements.txt
  pause
  exit /b 1
)

REM --- PySide6 kontrol ---
%PY% -c "import PySide6" >nul 2>nul
if errorlevel 1 (
  echo [UYARI] PySide6 eksik. Kuruluyor: pip install -r requirements.txt
  %PY% -m pip install -r requirements.txt
)

%PY% mibox.py
if errorlevel 1 (
  echo.
  echo [HATA] Konsol kapatildi veya hata verdi.
  pause
)