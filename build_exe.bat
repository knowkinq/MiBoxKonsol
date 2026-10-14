@echo off
REM MiBox Konsol - optimize .exe olusturur (64-bit ve 32-bit x86 otomatik algilar).
REM Kullanim: build_exe.bat
setlocal
set "MIBOX_DIR_PUSHED=0"
pushd "%~dp0"
if errorlevel 1 goto :fail
set "MIBOX_DIR_PUSHED=1"

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo Python bulunamadi. README'deki kurulum adimlarini izleyin.
  goto :fail
)

REM --- Mimari tespiti (32-bit x86 / 64-bit x64) ---
set "PY_BITS=64"
for /f "tokens=*" %%a in ('"%PY%" -c "import struct; print(struct.calcsize('P')*8)" 2^>nul') do set "PY_BITS=%%a"

echo ========================================================
echo   MiBox Konsol Derleyici - %PY_BITS%-bit mimari algilandi
echo ========================================================

if "%PY_BITS%"=="32" goto :setup_32
goto :setup_64

:setup_32
echo [BILGI] 32-bit [x86] Windows icin derleme baslatiliyor.
"%PY%" -c "import PyQt5" >nul 2>nul
if errorlevel 1 (
  echo PyQt5 bulunamadi. 32-bit Qt5 bagimliliklari kuruluyor...
  "%PY%" -m pip install "PyQt5>=5.15"
  if errorlevel 1 goto :fail
)
goto :check_pyinstaller

:setup_64
echo [BILGI] 64-bit [x64] Windows icin derleme baslatiliyor.
"%PY%" -c "import PySide6" >nul 2>nul
if errorlevel 1 (
  echo PySide6 bulunamadi. Bagimliliklar kuruluyor...
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 goto :fail
)
goto :check_pyinstaller

:check_pyinstaller

"%PY%" -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
  echo PyInstaller bulunamadi. Kuruluyor...
  "%PY%" -m pip install pyinstaller
  if errorlevel 1 goto :fail
)

where upx >nul 2>nul
if errorlevel 1 goto :no_upx
goto :build

:no_upx
echo Not: UPX bulunamadi, UPX siz derlenecek.
echo UPX istersen su komutu calistir: winget install upx.upx

:build
echo Temizlik: eski build kalintilari siliniyor...
if exist build rmdir /s /q build

echo PyInstaller ile derleniyor (%PY_BITS%-bit)...
"%PY%" -m PyInstaller --noconfirm MiBoxKonsol.spec
if errorlevel 1 goto :fail

echo Temizlik: dist icine sizmis kisisel ayarlar siliniyor...
if exist dist\mibox-ayarlar.json del /q dist\mibox-ayarlar.json
if exist dist\MiBox-ayarlar.json del /q dist\MiBox-ayarlar.json
if exist dist\mibox-bilinen-uygulamalar.json del /q dist\mibox-bilinen-uygulamalar.json
if exist dist\MiBox-bilinen-uygulamalar.json del /q dist\MiBox-bilinen-uygulamalar.json

if "%PY_BITS%"=="32" (
  if exist dist\MiBoxKonsol_x86.exe (
    copy /y dist\MiBoxKonsol_x86.exe dist\MiBoxKonsol.exe >nul 2>nul
  )
) else (
  if exist dist\MiBoxKonsol.exe (
    copy /y dist\MiBoxKonsol.exe dist\MiBoxKonsol_x64.exe >nul 2>nul
  )
)

echo.
for %%F in (dist\MiBoxKonsol*.exe) do echo Uretildi: %%~nxF (%%~zF bayt)
echo.
echo TAMAM: %PY_BITS%-bit calistirilabilir dosya basariyla olusturuldu.
if "%MIBOX_DIR_PUSHED%"=="1" popd
exit /b 0

:fail
echo.
echo [HATA] Derleme basarisiz oldu.
if "%MIBOX_DIR_PUSHED%"=="1" popd
exit /b 1
