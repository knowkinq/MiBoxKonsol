@echo off
REM MiBox Konsol - DONMUS .exe dogrulamasi (paketi test eder, kaynagi degil).
REM Kullanim: dogrula_exe.bat
setlocal
cd /d "%~dp0"

if not exist "dist\MiBoxKonsol.exe" (
  echo [HATA] dist\MiBoxKonsol.exe yok. Once build_exe.bat calistirin.
  pause
  exit /b 1
)

set "SURUM=%TEMP%\mibox-surum.txt"

echo [1/2] Surum + ortam bilgisi ^(--version^)...
"dist\MiBoxKonsol.exe" --version > "%SURUM%" 2>&1
type "%SURUM%"
findstr /C:"MiBox Konsol v" "%SURUM%" >nul
if errorlevel 1 goto :fail

echo.
echo [2/2] Selftest ^(--selftest, offscreen^)...
set QT_QPA_PLATFORM=offscreen
del /q "dist\mibox-selftest-ok.txt" 2>nul
"dist\MiBoxKonsol.exe" --selftest
if not exist "dist\mibox-selftest-ok.txt" goto :fail
type "dist\mibox-selftest-ok.txt"

echo.
echo TAMAM: exe surum bilgisini verdi ve selftest isaretcisini yazdi.
pause
exit /b 0

:fail
echo.
echo BASARISIZ: exe calismadi ya da isaretci yazilmadi.
echo.
echo Not: "Could not create temporary directory" hatasi UYGULAMADAN degil,
echo PyInstaller tek-dosya paketleyicisinden gelir: Windows gecici klasorune
echo (%%TEMP%%) yazamiyor demektir. Cozum: exe'yi baska bir klasore kopyalayip
echo deneyin, antivirus istisnasi ekleyin ya da kaynaktan calistirin:
echo   MiBox_Konsol.bat
pause
exit /b 1
