@echo off
REM MiBox Konsol - DONMUS paket dogrulamasi (onefile + onedir + kurulu kopya).
REM Kullanim: dogrula_exe.bat   (cikis kodu 0 = dogrulama tamam)
REM
REM Not: GUI exe'ler cmd tarafindan beklenmez; bu yuzden dogrulama
REM tools\dogrula_exe.ps1 ile yapilir (PID'e bagli zaman asimi + asili
REM surec temizligi; onefile'in %TEMP% hatasi UYARI olarak raporlanir).
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\dogrula_exe.ps1"
set "KOD=%ERRORLEVEL%"
echo.
if not "%KOD%"=="0" (
  echo BASARISIZ: dogrulama tamamlanmadi ^(cikis %KOD%^).
) else (
  echo Dogrulama tamam ^(cikis 0^).
)
pause
exit /b %KOD%
