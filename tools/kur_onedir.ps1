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
function Yaz($metin) { Write-Host $metin }

function Normalize-Path([string]$path) {
    $full = [IO.Path]::GetFullPath($path)
    $root = [IO.Path]::GetPathRoot($full)
    if ($full.Length -gt $root.Length) {
        $full = $full.TrimEnd([char]'\', [char]'/')
    }
    return $full
}

function Test-PathWithin([string]$path, [string]$base) {
    $candidate = Normalize-Path $path
    $parent = Normalize-Path $base
    if ([string]::Equals($candidate, $parent,
            [StringComparison]::OrdinalIgnoreCase)) { return $true }
    $prefix = $parent.TrimEnd([char]'\', [char]'/') + '\'
    return $candidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
}

try {
    $Kaynak = Normalize-Path $Kaynak
    $Hedef = Normalize-Path $Hedef
} catch {
    Yaz "[HATA] Kaynak/hedef yolu gecersiz: $($_.Exception.Message)"
    exit 1
}

# /veri kaldirma hedef klasorunun tamamini siler. Disk kokleri, kullanici ve
# sistem klasorleri hedef olamaz; kaynak/hedefin ic ice gecmesi de kopyalamayi
# kendi kendine yinelemeye ve veri kaybina yol acar.
$kokYolu = [IO.Path]::GetPathRoot($Hedef)
if ([string]::Equals((Normalize-Path $Hedef), (Normalize-Path $kokYolu),
        [StringComparison]::OrdinalIgnoreCase)) {
    Yaz "[HATA] Disk kok dizini kurulum hedefi olamaz: $Hedef"
    exit 1
}
if ($env:WINDIR -and (Test-PathWithin $Hedef $env:WINDIR)) {
    Yaz "[HATA] Windows klasorune kurulum yapilamaz: $Hedef"
    exit 1
}
$korunanYollar = @(
    $env:USERPROFILE, $env:LOCALAPPDATA, $env:APPDATA, $env:WINDIR,
    $env:ProgramFiles, ${env:ProgramFiles(x86)},
    [Environment]::GetFolderPath('Desktop'),
    [Environment]::GetFolderPath('MyDocuments')
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
$kaynakKok = [IO.Path]::GetPathRoot($Kaynak)
if ([string]::Equals((Normalize-Path $Kaynak), (Normalize-Path $kaynakKok),
        [StringComparison]::OrdinalIgnoreCase)) {
    Yaz "[HATA] Disk kok dizini paket kaynagi olamaz: $Kaynak"
    exit 1
}
foreach ($korunan in $korunanYollar) {
    if (Test-PathWithin $korunan $Kaynak) {
        Yaz "[HATA] Kullanici/sistem agacinin tamami paket kaynagi olamaz: $Kaynak"
        exit 1
    }
}
if ($env:WINDIR -and (Test-PathWithin $Kaynak $env:WINDIR)) {
    Yaz "[HATA] Windows klasoru paket kaynagi olamaz: $Kaynak"
    exit 1
}
foreach ($korunan in $korunanYollar) {
    if (Test-PathWithin $korunan $Hedef) {
        Yaz "[HATA] Korunan bir kullanici/sistem klasoru kurulum hedefi olamaz: $Hedef"
        exit 1
    }
}
$kaynakIcinde = Test-PathWithin $Kaynak $Hedef
$hedefIcinde = Test-PathWithin $Hedef $Kaynak
if ($kaynakIcinde -or $hedefIcinde) {
    Yaz "[HATA] Kaynak ve hedef klasorleri birbiriyle ic ice olamaz."
    exit 1
}
if (Test-Path -LiteralPath $Hedef -PathType Leaf) {
    Yaz "[HATA] Kurulum hedefi bir dosya: $Hedef"
    exit 1
}

# Var olan bir junction/symlink uzerinden kopyalama veya /veri silme yapma.
$probe = $Hedef
while ($probe) {
    if (Test-Path -LiteralPath $probe) {
        $entry = Get-Item -LiteralPath $probe -Force
        if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            Yaz "[HATA] Kurulum yolu baglantili (junction/symlink) klasor iceriyor: $probe"
            exit 1
        }
    }
    $parent = Split-Path -Parent $probe
    if (-not $parent -or [string]::Equals($parent, $probe,
            [StringComparison]::OrdinalIgnoreCase)) { break }
    $probe = $parent
}

# Kullanici verisi: kurulum sirasinda DOKUNULMAZ
$veriDosyalari = @('mibox-ayarlar.json', 'MiBox-ayarlar.json',
                   'mibox-islem-gecmisi.jsonl', 'debloat-kullanici.json',
                   'mibox-bilinen-uygulamalar.json')
$veriKlasorleri = @('logs', 'snapshots', 'ekran-goruntuleri', 'apk-yedekleri')

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
$hedefBase64 = [Convert]::ToBase64String(
    [Text.Encoding]::Unicode.GetBytes($Hedef))
$silmeScript = @'
$ErrorActionPreference = 'Stop'
$target = [IO.Path]::GetFullPath([Text.Encoding]::Unicode.GetString(
    [Convert]::FromBase64String('__TARGET__')))
$root = [IO.Path]::GetPathRoot($target)
$target = $target.TrimEnd([char]'\', [char]'/')
$root = $root.TrimEnd([char]'\', [char]'/')
if ([string]::Equals($target, $root, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Disk kok dizini silinemez.'
}
$protected = @($env:USERPROFILE, $env:LOCALAPPDATA, $env:APPDATA,
    $env:WINDIR, $env:ProgramFiles, ${env:ProgramFiles(x86)},
    [Environment]::GetFolderPath('Desktop'),
    [Environment]::GetFolderPath('MyDocuments')) |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
foreach ($path in $protected) {
    $base = [IO.Path]::GetFullPath($path).TrimEnd([char]'\', [char]'/')
    if ([string]::Equals($target, $base, [StringComparison]::OrdinalIgnoreCase) -or
        $base.StartsWith($target.TrimEnd([char]'\', [char]'/') + '\',
            [StringComparison]::OrdinalIgnoreCase)) {
        throw "Korunan klasor silinemez: $target"
    }
}
if ($env:WINDIR -and $target.StartsWith(
        [IO.Path]::GetFullPath($env:WINDIR).TrimEnd([char]'\', [char]'/') + '\',
        [StringComparison]::OrdinalIgnoreCase)) {
    throw "Windows klasoru silinemez: $target"
}
$probe = $target
while ($probe) {
    if (Test-Path -LiteralPath $probe) {
        $entry = Get-Item -LiteralPath $probe -Force
        if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Baglantili klasor silinemez: $probe"
        }
    }
    $parent = Split-Path -Parent $probe
    if (-not $parent -or [string]::Equals($parent, $probe,
            [StringComparison]::OrdinalIgnoreCase)) { break }
    $probe = $parent
}
Start-Sleep -Seconds 2
if (Test-Path -LiteralPath $target) {
    Remove-Item -LiteralPath $target -Recurse -Force
}
'@.Replace('__TARGET__', $hedefBase64)
$silmeKomutu = [Convert]::ToBase64String(
    [Text.Encoding]::Unicode.GetBytes($silmeScript))
@"
@echo off
REM MiBox Konsol kaldirma: kisayollari siler. Veriyi silmek icin /veri ekleyin.
setlocal
del "%USERPROFILE%\Desktop\MiBox Konsol.lnk" 2>nul
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\MiBox Konsol.lnk" 2>nul
del "%USERPROFILE%\Desktop\MiBox Konsol.bat" 2>nul
if /I "%~1"=="/veri" (
  echo Kullanici verisi de siliniyor...
  cd /d "%TEMP%"
  start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand $silmeKomutu
  echo Program klasoru ve veriler kapandiktan sonra silinecek.
  exit /b 0
) else (
  echo Kisayollar silindi. Program klasoru ve veriler korundu:
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
$versionOk = $false
$surumKod = 'baslatma hatasi'
$p = $null
try {
    $p = Start-Process -FilePath $exeYolu -ArgumentList '--version' `
        -RedirectStandardOutput $surumDosya -PassThru -ErrorAction Stop
    if ($p.WaitForExit(120000)) {
        $surumKod = $p.ExitCode
        $versionOk = ($p.ExitCode -eq 0)
    } else {
        $surumKod = 'zaman asimi'
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        $p.WaitForExit(5000) | Out-Null
    }
} catch {
    Yaz ("--version hata: {0}" -f $_.Exception.Message)
}
$satirlar = Get-Content $surumDosya -ErrorAction SilentlyContinue
$surum = $satirlar | Select-Object -First 1
$mod = $satirlar | Where-Object { $_ -match '^Paket modu' } | Select-Object -First 1
Remove-Item $surumDosya -ErrorAction SilentlyContinue
Yaz ("--version : {0} (exit {1})" -f $surum, $surumKod)
if ($mod) { Yaz ("            {0}" -f $mod.Trim()) }
if (-not $versionOk) { Yaz "[HATA] --version dogrulamasi basarisiz." }

$isaret = Join-Path $Hedef 'mibox-selftest-ok.txt'
Remove-Item $isaret -ErrorAction SilentlyContinue
$markerReady = -not (Test-Path $isaret)
$selftestCompleted = $false
$selftestTimeout = $false
$p2 = $null
try {
    $p2 = Start-Process -FilePath $exeYolu -ArgumentList '--selftest' `
        -PassThru -ErrorAction Stop
    $selftestCompleted = [bool]$p2.WaitForExit(180000)
    if (-not $selftestCompleted) {
        $selftestTimeout = $true
        Stop-Process -Id $p2.Id -Force -ErrorAction SilentlyContinue
        $p2.WaitForExit(5000) | Out-Null
    }
} catch {
    Yaz ("--selftest hata: {0}" -f $_.Exception.Message)
}
$markerContent = ''
if ($markerReady -and (Test-Path $isaret)) {
    $markerContent = Get-Content $isaret -Raw -ErrorAction SilentlyContinue
    if ($null -ne $markerContent) { $markerContent = $markerContent.Trim() }
}
$selftestKod = if ($selftestCompleted -and $p2) {
    $p2.ExitCode
} elseif ($selftestTimeout) {
    'zaman asimi'
} else {
    'baslatma hatasi'
}
$selftestOk = [bool]($selftestCompleted -and $p2 -and $p2.HasExited `
    -and $p2.ExitCode -eq 0 -and $markerReady -and $markerContent -eq 'SELFTEST_OK')
if ($selftestOk) {
    Yaz ("--selftest: {0} (exit {1})" -f $markerContent, $selftestKod)
} else {
    Yaz ("[HATA] --selftest basarisiz (exit {0}, isaretci: {1})." -f `
        $selftestKod, $(if (Test-Path $isaret) { $markerContent } else { 'yok' }))
    Yaz "        exe'yi elle deneyin:"
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
if ($versionOk -and $selftestOk) {
    Yaz "TAMAM: MiBox Konsol kuruldu."
} else {
    Yaz "KURULUM BASARISIZ: dogrulama tamamlanmadi."
    exit 1
}
