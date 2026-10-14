@echo off
REM MiBox Konsol - 32-bit (x86) Windows icin ozel EXE olusturucu.
REM Kullanim: build_exe_x86.bat
setlocal
pushd "%~dp0"

echo ========================================================
echo   MiBox Konsol - 32-bit (x86) Windows EXE Derleyici
echo ========================================================

REM 1. 32-bit Python ara
set "PY="
REM Python Launcher ile 32-bit Python dene:
py -3.10-32 --version >nul 2>nul && set "PY=py -3.10-32"
if not defined PY py -3.11-32 --version >nul 2>nul && set "PY=py -3.11-32"
if not defined PY py -3.12-32 --version >nul 2>nul && set "PY=py -3.12-32"
if not defined PY py -3-32 --version >nul 2>nul && set "PY=py -3-32"

REM Klasör içi venv32 dene:
if not defined PY if exist "%~dp0venv32\Scripts\python.exe" set "PY=%~dp0venv32\Scripts\python.exe"
if not defined PY if exist "%~dp0.venv32\Scripts\python.exe" set "PY=%~dp0.venv32\Scripts\python.exe"

REM Varsayilan python'in bitness'ini kontrol et:
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 (
    for /f "tokens=*" %%a in ('python -c "import struct; print(struct.calcsize('P')*8)" 2^>nul') do (
      if "%%a"=="32" set "PY=python"
    )
  )
)

if not defined PY (
  echo [HATA] 32-bit (x86) Python bulunamadi.
  echo.
  echo 32-bit Windows EXE derlemek icin 32-bit Python gereklidir:
  echo   winget install Python.Python.3.11 --architecture x86
  echo   veya https://www.python.org/downloads/windows/ adresinden "Windows installer (32-bit)" indirin.
  echo.
  pause
  popd
  exit /b 1
)

echo Secilen Python: %PY%
%PY% -c "import struct, platform; print('Derleme Mimarisi: ' + str(struct.calcsize('P')*8) + '-bit ' + platform.machine())"

REM Bağımlılık kontrolü
%PY% -c "import PyQt5" >nul 2>nul
if errorlevel 1 (
  echo 32-bit Qt5 bagimliliklari kuruluyor (PyQt5)...
  %PY% -m pip install -r requirements-x86.txt
  if errorlevel 1 goto :fail
)

%PY% -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
  echo PyInstaller kuruluyor...
  %PY% -m pip install pyinstaller
  if errorlevel 1 goto :fail
)

echo Eski derleme kalintilari temizleniyor...
if exist build rmdir /s /q build

echo PyInstaller ile 32-bit derleniyor...
%PY% -m PyInstaller --noconfirm MiBoxKonsol.spec
if errorlevel 1 goto :fail

if exist dist\MiBoxKonsol_x86.exe (
  copy /y dist\MiBoxKonsol_x86.exe dist\MiBoxKonsol-32bit.exe >nul 2>nul
  echo.
  echo TAMAM: 32-bit EXE basariyla uretildi:
  for %%F in (dist\MiBoxKonsol_x86.exe dist\MiBoxKonsol-32bit.exe) do echo   - %%F (%%~zF bayt)
)

popd
exit /b 0

:fail
echo.
echo [HATA] 32-bit derleme basarisiz oldu.
popd
exit /b 1
