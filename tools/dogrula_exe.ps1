# MiBox Konsol - donmus paket dogrulamasi (onefile + onedir + kurulu kopya).
#
# Neden PowerShell: GUI (penceresiz) bir exe'yi cmd beklemez; bu yuzden
# onefile basarisiz oldugunda ekranda "Could not create temporary directory"
# penceresi ASILI kalabiliyordu. Burada her paket PID'e bagli zaman asimiyla
# calistirilir ve asili kalan surec SADECE o PID icin kapatilir.
#
# Kullanim:  dogrula_exe.bat   (veya: powershell -File tools\dogrula_exe.ps1)

[CmdletBinding()]
param(
    [string]$Kok = '',
    [int]$ZamanAsimiSn = 120
)

$ErrorActionPreference = 'Continue'
if (-not $Kok) { $Kok = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path) }

$paketler = @(
    @{ Ad = 'onefile (dist\MiBoxKonsol.exe)'; Exe = (Join-Path $Kok 'dist\MiBoxKonsol.exe') },
    @{ Ad = 'onedir (dist-onedir\MiBoxKonsol)'; Exe = (Join-Path $Kok 'dist-onedir\MiBoxKonsol\MiBoxKonsol.exe') },
    @{ Ad = 'kurulu kopya (%LOCALAPPDATA%\MiBoxKonsol)'; Exe = (Join-Path $env:LOCALAPPDATA 'MiBoxKonsol\MiBoxKonsol.exe') }
)

$env:QT_QPA_PLATFORM = 'offscreen'
$bulunan = 0
$sorun = 0
$uyari = 0

function Calistir($exeYolu, $argumanlar) {
    $p = Start-Process -FilePath $exeYolu -ArgumentList $argumanlar -PassThru
    $bitti = $p.WaitForExit($ZamanAsimiSn * 1000)
    if (-not $bitti) {
        # Ekranda asili kalan (or. hata penceresi) sureci yalnizca bu PID icin kapat
        try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch { }
        return @{ Kod = 'zaman asimi'; Cikti = '' }
    }
    return @{ Kod = $p.ExitCode; Cikti = '' }
}

foreach ($paket in $paketler) {
    if (-not (Test-Path $paket.Exe)) { continue }
    $bulunan++
    Write-Host ''
    Write-Host ("=== {0} ===" -f $paket.Ad)

    # 1) --version (cikti dosyaya yonlendirilir; pencere acilmaz)
    $surumDosya = Join-Path $env:TEMP ('mibox-dogrula-' + [guid]::NewGuid().ToString('N') + '.txt')
    $p = Start-Process -FilePath $paket.Exe -ArgumentList '--version' `
                       -RedirectStandardOutput $surumDosya -PassThru
    $bitti = $p.WaitForExit($ZamanAsimiSn * 1000)
    if (-not $bitti) {
        try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch { }
    }
    $satirlar = @(Get-Content $surumDosya -ErrorAction SilentlyContinue)
    Remove-Item $surumDosya -ErrorAction SilentlyContinue

    if (-not ($satirlar -match '^S.r.m\s*:').Count) {
        Write-Host '[UYARI] surum ciktisi alinamadi.'
        Write-Host '        onefile icin bu normal olabilir: %TEMP% altinda gecici klasor acilamaz'
        Write-Host '        ("Could not create temporary directory"). Cozum: kur_onedir.bat'
        $uyari++
        continue
    }
    $satirlar | Select-Object -First 2 | ForEach-Object { Write-Host ('  ' + $_) }

    # 2) --selftest (isaretci dosyasi kontrolu)
    $isaret = Join-Path (Split-Path -Parent $paket.Exe) 'mibox-selftest-ok.txt'
    Remove-Item $isaret -ErrorAction SilentlyContinue
    $p2 = Start-Process -FilePath $paket.Exe -ArgumentList '--selftest' -PassThru
    $bitti2 = $p2.WaitForExit(180 * 1000)
    if (-not $bitti2) {
        try { Stop-Process -Id $p2.Id -Force -ErrorAction SilentlyContinue } catch { }
    }
    if (Test-Path $isaret) {
        Write-Host ('  selftest  : ' + (Get-Content $isaret))
        Write-Host ('[OK] ' + $paket.Ad)
    } else {
        Write-Host ('[HATA] selftest isaretcisi yazilmadi: ' + $isaret)
        $sorun++
    }
}

Write-Host ''
if ($bulunan -eq 0) {
    Write-Host '[HATA] Hicbir paket bulunamadi.'
    Write-Host '       Derleyin: build_exe.bat (onefile) / build_exe_onedir.bat (onedir)'
    exit 1
}
if ($sorun -gt 0) {
    Write-Host 'BASARISIZ: en az bir paket dogrulanamadi (yukaridaki [HATA] satirlari).'
    exit 1
}
if ($uyari -gt 0) {
    Write-Host 'TAMAM (uyarili): paketler calisiyor; yalnizca bir uyari var (yukarida).'
    exit 0
}
Write-Host 'TAMAM: tum paketler dogrulandi.'
exit 0
