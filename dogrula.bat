@echo off
REM MiBox Konsol - tek tikla TAM dogrulama (kaynak tarafi kapi).
REM  1) sozdizimi     : python -m compileall
REM  2) selftest      : pencereyi offscreen kurar
REM  3) offline suite : tests\run_all.py (6 suite)
REM  4) kalite tarama : olu import / cakisan tanim / print / TODO
REM  5) dil kurali    : etiket Turkce diakritikli, veri ve DOSYA ADLARI ASCII
REM Cikis kodu 0 = hepsi yesil. Kirmiziysa teslim yok.
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
set QT_QPA_PLATFORM=offscreen

echo [1/5] Sozdizimi denetimi ^(mibox_app + tests^)...
%PY% -m compileall -q mibox_app tests
if errorlevel 1 goto :fail

echo [2/5] Selftest ^(pencereyi offscreen kurar^)...
%PY% mibox.py --selftest
if errorlevel 1 goto :fail

echo [3/5] Offline test suite'leri ^(Faz2/5/7/8/9/10^)...
%PY% tests\run_all.py
if errorlevel 1 goto :fail

echo [4/5] Kalite taramasi ^(olu import / cakisan tanim / print / TODO^)...
%PY% tools\kalite_tara.py --siki
if errorlevel 1 goto :fail

echo [5/5] Dil kurali ^(etiket diakritikli, veri + dosya adlari ASCII^)...
%PY% tools\diakritik.py
if errorlevel 1 goto :fail

echo.
echo TAMAM: sozdizimi + selftest + 6 suite + kalite + dil kurali gecti.
pause
exit /b 0

:fail
echo.
echo BASARISIZ: yukaridaki hata duzeltilmeden devam etmeyin.
pause
exit /b 1
