@echo off
REM MiBox Konsol - optimize tek dosya .exe olusturur.
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

"%PY%" -c "import PySide6" >nul 2>nul
if errorlevel 1 (
  echo PySide6 bulunamadi. Bagimliliklar kuruluyor...
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 goto :fail
)

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

echo PyInstaller ile derleniyor...
"%PY%" -m PyInstaller --noconfirm MiBoxKonsol.spec
if errorlevel 1 goto :fail

echo Temizlik: dist icine sizmis kisisel ayarlar siliniyor...
if exist dist\mibox-ayarlar.json del /q dist\mibox-ayarlar.json
if exist dist\MiBox-ayarlar.json del /q dist\MiBox-ayarlar.json
if exist dist\mibox-bilinen-uygulamalar.json del /q dist\mibox-bilinen-uygulamalar.json
if exist dist\MiBox-bilinen-uygulamalar.json del /q dist\MiBox-bilinen-uygulamalar.json

echo.
for %%F in (dist\MiBoxKonsol.exe) do echo Boyut: %%~zF bayt
echo TAMAM: dist\MiBoxKonsol.exe
echo Not: adb.exe dosyasini exe yanina kopyalayin.
pause
popd
exit /b 0

:fail
echo Derleme basarisiz.
pause
if "%MIBOX_DIR_PUSHED%"=="1" popd
exit /b 1
