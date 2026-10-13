@echo off
REM MiBox Konsol - optimize tek dosya .exe olusturur.
REM Kullanim: build_exe.bat
setlocal
set "MIBOX_DIR_PUSHED=0"
pushd "%~dp0"
if errorlevel 1 goto :fail
set "MIBOX_DIR_PUSHED=1"

where pyinstaller >nul 2>nul
if errorlevel 1 goto :need_pyinstaller
goto :check_upx

:need_pyinstaller
echo PyInstaller bulunamadi. Kuruluyor...
pip install pyinstaller
if errorlevel 1 goto :fail

:check_upx
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
pyinstaller --noconfirm MiBoxKonsol.spec
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
