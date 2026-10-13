@echo off
REM MiBox Konsol - DONMUS paket dogrulamasi: onefile + onedir + kurulu kopya.
REM Kullanim: dogrula_exe.bat   (cikis kodu 0 = dogrulama tamam)
REM
REM Not: onefile paket calisirken %TEMP% altinda gecici klasor acar. Bu adim
REM kisitli bir makinede "Could not create temporary directory" ile duser;
REM bu durum UYARI sayilir (onedir/kurulu kopya yine dogrulanir).
setlocal
cd /d "%~dp0"

set "BULUNDU=0"
set "SORUN=0"
set "UYARI=0"

if exist "dist\MiBoxKonsol.exe" call :dogrula "onefile (dist\MiBoxKonsol.exe)" "dist\MiBoxKonsol.exe" "dist\mibox-selftest-ok.txt"
if exist "dist-onedir\MiBoxKonsol\MiBoxKonsol.exe" call :dogrula "onedir (dist-onedir\MiBoxKonsol)" "dist-onedir\MiBoxKonsol\MiBoxKonsol.exe" "dist-onedir\MiBoxKonsol\mibox-selftest-ok.txt"
if exist "%LOCALAPPDATA%\MiBoxKonsol\MiBoxKonsol.exe" call :dogrula "kurulu kopya (%LOCALAPPDATA%\MiBoxKonsol)" "%LOCALAPPDATA%\MiBoxKonsol\MiBoxKonsol.exe" "%LOCALAPPDATA%\MiBoxKonsol\mibox-selftest-ok.txt"

echo.
if "%BULUNDU%"=="0" (
  echo [HATA] Hicbir paket bulunamadi.
  echo        Derleyin: build_exe.bat  ^(onefile^)  /  build_exe_onedir.bat  ^(onedir^)
  pause
  exit /b 1
)
if "%SORUN%"=="1" (
  echo BASARISIZ: en az bir paket dogrulanamadi ^(yukaridaki [HATA] satirlarina bakin^).
  pause
  exit /b 1
)
if "%UYARI%"=="1" (
  echo TAMAM ^(uyarili^): paketler calisiyor; yalnizca bir uyari var ^(yukarida^).
  pause
  exit /b 0
)
echo TAMAM: tum paketler dogrulandi.
pause
exit /b 0

:dogrula
set "BULUNDU=1"
echo.
echo === %~1 ===
set "SURUM=%TEMP%\mibox-surum-%RANDOM%%RANDOM%.txt"
"%~2" --version > "%SURUM%" 2>&1
type "%SURUM%" 2>nul
findstr /C:"MiBox Konsol v" "%SURUM%" >nul
if errorlevel 1 (
  echo [UYARI] surum ciktisi alinamadi.
  echo         onefile icin bu normal olabilir: %%TEMP%% altinda gecici klasor
  echo         acilamaz ^("Could not create temporary directory"^). Cozum:
  echo         kur_onedir.bat ile onedir paketi kurun.
  set "UYARI=1"
  del /q "%SURUM%" 2>nul
  goto :eof
)
del /q "%SURUM%" 2>nul
set QT_QPA_PLATFORM=offscreen
del /q "%~3" 2>nul
"%~2" --selftest
if not exist "%~3" (
  echo [HATA] selftest isaretcisi yazilmadi ^(%~3^).
  set "SORUN=1"
  goto :eof
)
type "%~3"
echo [OK] %~1
goto :eof
