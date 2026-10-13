# MiBox Konsol - ONEDIR paketini kalici konuma kurar + kisayol olusturur.
#
# Neden onedir: tek-dosya (onefile) paket calisirken %TEMP% altinda gecici
# klasor acar; kisitli makinede "Could not create temporary directory" hatasi
# verebilir. onedir paket gecici klasor acmaz.
#
# Kullanim:  kur_onedir.bat   (veya dogrudan: powershell -File tools\kur_onedir.ps1)
#
# ONEMLI: Hedef klasordeki KULLANICI VERISI korunur (ayar, log, gecmis,
# snapshot, favori dosyalari uzerine YAZILMAZ).

[CmdletBinding()]
param(
    [string]$Kaynak = '',
    [string]$Hedef = '',
    [switch]$KisayolYok
)

$ErrorActionPreference = 'Stop'
$kok = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $Kaynak) { $Kaynak = Join-Path $kok 'dist-onedir\MiBoxKonsol' }
if (-not $Hedef)  { $Hedef  = Join-Path $env:LOCALAPPDATA 'MiBoxKonsol' }

# Kullanici verisi: kurulum sirasinda DOKUNULMAZ
$veriDosyalari = @('mibox-ayarlar.json', 'MiBox-ayarlar.json',
                   'mibox-islem-gecmisi.jsonl', 'debloat-kullanici.json',
                   'mibox-bilinen-uygulamalar.json')
$veriKlasorleri = @('logs', 'snapshots', 'ekran-goruntuleri', 'apk-yedekleri')

function Yaz($metin) { Write-Host $metin }

if (-not (Test-Path (Join-Path $Kaynak 'MiBoxKonsol.exe'))) {
    Yaz "[HATA] Paket bulunamadi: $Kaynak"
    Yaz "       Once derleyin: build_exe_onedir.bat"
    exit 1
}

Yaz "Kaynak : $Kaynak"
Yaz "Hedef  : $Hedef"

if (-not (Test-Path $Hedef)) {
    New-Item -ItemType Directory -Path $Hedef -Force | Out-Null
    Yaz "Hedef klasor olusturuldu."
}

# 1) Dosyalari kopyala (kullanici verisi haric; mevcut veri korunur)
$kopyalanan = 0
Get-ChildItem -Path $Kaynak -Force | ForEach-Object {
    $ad = $_.Name
    if ($veriDosyalari -contains $ad) { return }
    if ($veriKlasorleri -contains $ad) { return }
    $hedefYol = Join-Path $Hedef $ad
    Copy-Item -Path $_.FullName -Destination $hedefYol -Recurse -Force
    $kopyalanan++
}
Yaz "Kopyalanan oge sayisi: $kopyalanan (kullanici verisi korundu)"

# 2) adb.exe bulunursa paket yanina kopyala (motor PATH'ten de bulabilir)
$adb = $null
$yerelAdb = Join-Path $kok 'adb.exe'
if (Test-Path $yerelAdb) {
    $adb = $yerelAdb
} else {
    $cmd = Get-Command adb.exe -ErrorAction SilentlyContinue
    if ($cmd) { $adb = $cmd.Source }
}
if ($adb) {
    Copy-Item -Path $adb -Destination (Join-Path $Hedef 'adb.exe') -Force
    Yaz "adb.exe kopyalandi: $adb"
} else {
    Yaz "uyari: adb.exe bulunamadi (motor PATH'ten arayacak)"
}

$exeYolu = Join-Path $Hedef 'MiBoxKonsol.exe'

# 3) Kisayollar (masaustu + baslat menusu)
$kisayollar = @()
if (-not $KisayolYok) {
    $hedefler = @(
        (Join-Path ([Environment]::GetFolderPath('Desktop')) 'MiBox Konsol.lnk'),
        (Join-Path ([Environment]::GetFolderPath('Programs')) 'MiBox Konsol.lnk')
    )
    try {
        $ws = New-Object -ComObject WScript.Shell
        foreach ($lnk in $hedefler) {
            $k = $ws.CreateShortcut($lnk)
            $k.TargetPath = $exeYolu
            $k.WorkingDirectory = $Hedef
            $k.IconLocation = "$exeYolu,0"
            $k.Description = 'MiBox Konsol - Android TV yonetim araci'
            $k.Save()
            $kisayollar += $lnk
        }
        Yaz "Kisayollar olusturuldu:"
        $kisayollar | ForEach-Object { Yaz "  $_" }
    } catch {
        Yaz "uyari: kisayol olusturulamadi ($($_.Exception.Message))"
        Yaz "       Masaustune 'MiBox Konsol.bat' birakiliyor."
        $bat = Join-Path ([Environment]::GetFolderPath('Desktop')) 'MiBox Konsol.bat'
        "start `"`" `"$exeYolu`"" | Set-Content -Path $bat -Encoding ASCII
        $kisayollar += $bat
    }
}

# 4) Kaldirma betigi (kisayollari siler; veriyi istege bagli temizler)
$kaldir = Join-Path $Hedef 'kaldir.bat'
@"
@echo off
REM MiBox Konsol kaldirma: kisayollari siler. Veriyi silmek icin /veri ekleyin.
setlocal
set "HEDEF=$Hedef"
del "%USERPROFILE%\Desktop\MiBox Konsol.lnk" 2>nul
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\MiBox Konsol.lnk" 2>nul
del "%USERPROFILE%\Desktop\MiBox Konsol.bat" 2>nul
if /I "%~1"=="/veri" (
  echo Kullanici verisi de siliniyor...
  rmdir /s /q "%HEDEF%"
) else (
  echo Kisayollar silindi. Program klasoru ve veriler korundu:
  echo   %HEDEF%
  echo Veriyi de silmek icin: kaldir.bat /veri
)
pause
"@ | Set-Content -Path $kaldir -Encoding ASCII
Yaz "Kaldirma betigi: $kaldir"

# 5) Dogrulama: kurulan kopya surum + selftest
Yaz ""
Yaz "--- dogrulama ---"
# Dogrulama uygulamayi calistirir; olusan dosyalar TEMIZ kurulumda geri
# alinir, mevcut kullanimda DOKUNULMAZ.
$onceVardi = @{}
foreach ($ad in @('mibox-ayarlar.json', 'logs', 'snapshots', 'mibox-selftest-ok.txt')) {
    $onceVardi[$ad] = Test-Path (Join-Path $Hedef $ad)
}
$env:QT_QPA_PLATFORM = 'offscreen'
$surumDosya = Join-Path $env:TEMP ('mibox-kurulum-' + [guid]::NewGuid().ToString('N') + '.txt')
$p = Start-Process -FilePath $exeYolu -ArgumentList '--version' -RedirectStandardOutput $surumDosya -PassThru
$p.WaitForExit(120000) | Out-Null
$surum = (Get-Content $surumDosya -ErrorAction SilentlyContinue | Select-Object -First 1)
$surumKod = if ($p.HasExited) { $p.ExitCode } else { 'zaman asimi' }
Remove-Item $surumDosya -ErrorAction SilentlyContinue
Yaz ("--version : {0} (exit {1})" -f $surum, $surumKod)

$isaret = Join-Path $Hedef 'mibox-selftest-ok.txt'
Remove-Item $isaret -ErrorAction SilentlyContinue
$p2 = Start-Process -FilePath $exeYolu -ArgumentList '--selftest' -PassThru
if (-not $p2.WaitForExit(180000)) { Stop-Process -Id $p2.Id -Force; $p2 = $null }
$selftestOk = [bool]($p2 -and (Test-Path $isaret))
if ($selftestOk) {
    Yaz ("--selftest: {0} (exit {1})" -f (Get-Content $isaret), $p2.ExitCode)
} else {
    Yaz "[UYARI] selftest isaretcisi yazilmadi; exe'yi elle deneyin:"
    Yaz "        $exeYolu"
}

# Temiz kurulumda dogrulama artiklarini sil (mevcut ayarlara dokunma).
# mibox-selftest-ok.txt HER ZAMAN test artefaktidir -> kosulsuz silinir.
$silinen = @()
$marker = Join-Path $Hedef 'mibox-selftest-ok.txt'
if (Test-Path $marker) {
    Remove-Item $marker -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path $marker)) { $silinen += 'mibox-selftest-ok.txt' }
}
foreach ($ad in @('mibox-ayarlar.json', 'logs', 'snapshots')) {
    if (-not $onceVardi[$ad]) {
        $yol = Join-Path $Hedef $ad
        if (Test-Path $yol) {
            Remove-Item $yol -Recurse -Force -ErrorAction SilentlyContinue
            if (-not (Test-Path $yol)) { $silinen += $ad }
        }
    }
}
if ($silinen.Count -gt 0) {
    Yaz ("Temizlenen dogrulama artiklari: {0}" -f ($silinen -join ', '))
}
Yaz ""
if ($selftestOk) {
    Yaz "TAMAM: MiBox Konsol kuruldu."
} else {
    Yaz "KURULUM TAMAM (selftest uyarisi var)."
}
