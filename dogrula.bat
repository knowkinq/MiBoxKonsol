@echo off
REM MiBox Konsol - tek tikla dogrulama: sozdizimi + selftest + offline testler.
REM Kullanim: dogrula.bat   (cikis kodu 0 = her sey yesil)
setlocal
cd /d "%~dp0"

set "PY="
if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"
if not defined PY where python >nul 2>nul && set "PY=python"

if not defined PY (
  echo [HATA] Python bulunamadi. Kurun: winget install Python.Python.3
  pause
  exit /b 1
)

echo [1/3] Sozdizimi denetimi ^(mibox_app^)...
%PY% -m compileall -q mibox_app
if errorlevel 1 goto :fail

echo [2/3] Selftest ^(pencereyi offscreen kurar^)...
set QT_QPA_PLATFORM=offscreen
%PY% mibox.py --selftest
if errorlevel 1 goto :fail

echo [3/3] Offline test suite'leri ^(Faz2/Faz5/Faz7^)...
%PY% tests\run_all.py
if errorlevel 1 goto :fail

echo.
echo TAMAM: sozdizimi + selftest + tum offline testler gecti.
pause
exit /b 0

:fail
echo.
echo BASARISIZ: yukaridaki hata duzeltilmeden devam etmeyin.
pause
exit /b 1
