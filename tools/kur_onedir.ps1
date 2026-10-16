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
                   'mibox-bilinen-uygulamalar.json', 'mibox-selftest-ok.txt',
                   'mibox-logcat.txt', 'surum.txt', 'ortam-bilgisi.txt',
                   'mibox-version.txt', 'scrcpy.exe', '.mibox-kurulum-devam')
$veriKlasorleri = @('logs', 'snapshots', 'ekran-goruntuleri', 'ekran-videolari',
                    'indirilen-apklar', 'apk-yedekleri', 'scrcpy', '_arsiv')
$veriDesenleri = @(
    'mibox-ayarlar.json.*', 'MiBox-ayarlar.json.*',
    'mibox-ayar-yedek*.json*', '.mibox-ayar-yedek*.tmp',
    '.mibox-debloat-favorites-*.tmp',
    'mibox-snapshot-*.json', '.mibox-snapshot-*.tmp',
    '.mibox-download-*.part', 'mibox-*.csv', '*.apk', '*.apks', '*.xapk',
    'scrcpy-*', '.mibox-scrcpy-*', '.scrcpy-preferred*',
    '.scrcpy_download.tmp.zip')

function Test-MiBoxRuntimeItem($item) {
    if (($veriDosyalari -contains $item.Name) -or
        ($veriKlasorleri -contains $item.Name)) { return $true }
    foreach ($pattern in $veriDesenleri) {
        if ($item.Name -like $pattern) { return $true }
    }
    return $false
}

function Copy-DirectoryContents([string]$source, [string]$destination) {
    foreach ($entry in Get-ChildItem -LiteralPath $source -Force) {
        $targetPath = Join-Path $destination $entry.Name
        if ($entry.PSIsContainer) {
            if (Test-Path -LiteralPath $targetPath -PathType Leaf) {
                throw "Dosya/klasor turu cakismasi: $($entry.Name)"
            }
            [IO.Directory]::CreateDirectory($targetPath) | Out-Null
            Copy-DirectoryContents $entry.FullName $targetPath
        } else {
            if (Test-Path -LiteralPath $targetPath -PathType Container) {
                throw "Dosya/klasor turu cakismasi: $($entry.Name)"
            }
            [IO.File]::Copy($entry.FullName, $targetPath, $true)
        }
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $Kaynak 'MiBoxKonsol.exe') -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $Kaynak '_internal') -PathType Container)) {
    Yaz "[HATA] Paket bulunamadi: $Kaynak"
    Yaz "       Once derleyin: build_exe_onedir.bat"
    exit 1
}

# Paket kaynagindan yalniz PyInstaller onedir ciktilarini al. Taninmayan bir
# oge varsa kopyalamaya baslamadan dur; kaynaktaki kullanici dosyalari hedefe
# tasinmasin. Bilinen calisma zamani verileri eski yerel derlemelerde gorunebilir
# ve kurulum paketinin parcasi olmadiklari icin atlanir.
$izinliPaketOgeleri = @('MiBoxKonsol.exe', '_internal', 'adb.exe')
$bilinmeyenOgeler = @(
    Get-ChildItem -LiteralPath $Kaynak -Force | Where-Object {
        $ad = $_.Name
        $kullaniciVerisi = Test-MiBoxRuntimeItem $_
        if ($kullaniciVerisi) { return $false }

        if ($izinliPaketOgeleri -notcontains $ad) { return $true }
        if (($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { return $true }
        if ($ad -eq '_internal') { return -not $_.PSIsContainer }
        return $_.PSIsContainer
    }
)
if ($bilinmeyenOgeler.Count -gt 0) {
    $adlar = ($bilinmeyenOgeler | ForEach-Object { $_.Name }) -join ', '
    Yaz "[HATA] Paket kaynaginda beklenmeyen oge(ler) var; kopyalama durduruldu: $adlar"
    Yaz "       Yalniz MiBoxKonsol.exe, _internal ve istege bagli adb.exe beklenir."
    exit 1
}

foreach ($kopyaYolu in @(
    (Join-Path $Kaynak 'MiBoxKonsol.exe'),
    (Join-Path $Kaynak '_internal'),
    (Join-Path $Kaynak 'adb.exe'),
    (Join-Path $Hedef 'MiBoxKonsol.exe'),
    (Join-Path $Hedef '_internal'),
    (Join-Path $Hedef 'adb.exe')
)) {
    if (Test-Path -LiteralPath $kopyaYolu) {
        $entry = Get-Item -LiteralPath $kopyaYolu -Force
        if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            Yaz "[HATA] Kopyalama hedefi/kaynagi baglanti iceriyor: $($entry.Name)"
            exit 1
        }
    }
}
foreach ($kokYolu in @($Kaynak, $Hedef)) {
    $dahili = Join-Path $kokYolu '_internal'
    if (-not (Test-Path -LiteralPath $dahili -PathType Container)) { continue }
    $bagliOge = Get-ChildItem -LiteralPath $dahili -Force -Recurse |
        Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 } |
        Select-Object -First 1
    if ($bagliOge) {
        Yaz "[HATA] _internal icinde junction/symlink bulundu: $($bagliOge.Name)"
        exit 1
    }
}

if (Test-Path -LiteralPath $Hedef -PathType Container) {
    $hedefExeVar = Test-Path -LiteralPath (Join-Path $Hedef 'MiBoxKonsol.exe') -PathType Leaf
    $hedefDahiliVar = Test-Path -LiteralPath (Join-Path $Hedef '_internal') -PathType Container
    $marker = Join-Path $Hedef '.mibox-kurulum-devam'
    $isPartialInstall = (Test-Path -LiteralPath $marker -PathType Leaf) -and
        ((Get-Content -LiteralPath $marker -Raw -ErrorAction SilentlyContinue).Trim() -eq
            'MiBoxKonsol ONEDIR install in progress')
    if (($hedefExeVar -ne $hedefDahiliVar) -and -not $isPartialInstall) {
        Yaz '[HATA] Hedefte yarim kalmis veya taninmayan bir kurulum var; veriyi korumak icin kopyalama durduruldu.'
        exit 1
    }
    if (-not $hedefExeVar -and -not $isPartialInstall) {
        $hedefOgeleri = @(Get-ChildItem -LiteralPath $Hedef -Force)
        if ($hedefOgeleri.Count -gt 0) {
            $adlar = ($hedefOgeleri | ForEach-Object { $_.Name }) -join ', '
            Yaz "[HATA] Kurulum hedefi baska dosyalar iceriyor: $adlar"
            Yaz '       Mevcut dosyalari korumak icin bos bir hedef klasor secin.'
            exit 1
        }
    }
}

Yaz "Kaynak : $Kaynak"
Yaz "Hedef  : $Hedef"

$exeYolu = Join-Path $Hedef 'MiBoxKonsol.exe'
$uygulamaCalisiyor = $false
foreach ($ad in @('MiBoxKonsol', 'MiBoxKonsol_x86')) {
    foreach ($process in @(Get-Process -Name $ad -ErrorAction SilentlyContinue)) {
        try {
            $processPath = $process.Path
            if ([string]::IsNullOrWhiteSpace($processPath)) {
                $uygulamaCalisiyor = $true
                break
            }
            if (Test-PathWithin (Normalize-Path $processPath) $Hedef) {
                $uygulamaCalisiyor = $true
                break
            }
        } catch {
            # Yolu okunamayan MiBox surecinde karisik surum kopyalama riski alma.
            $uygulamaCalisiyor = $true
            break
        }
    }
    if ($uygulamaCalisiyor) { break }
}
if ($uygulamaCalisiyor) {
    Yaz "[HATA] MiBox Konsol kurulum klasorunden calisiyor. Uygulamayi kapatip yeniden deneyin."
    exit 1
}

if (-not (Test-Path -LiteralPath $Hedef)) {
    [IO.Directory]::CreateDirectory($Hedef) | Out-Null
    Yaz "Hedef klasor olusturuldu."
}

$installMarker = Join-Path $Hedef '.mibox-kurulum-devam'
if (-not (Test-Path -LiteralPath $installMarker)) {
    $markerContent = 'MiBoxKonsol ONEDIR install in progress'
    Set-Content -LiteralPath $installMarker -Value $markerContent -Encoding ASCII
}

# 1) Dosyalari kopyala (kullanici verisi haric; mevcut veri korunur)
$kopyalanan = 0
Get-ChildItem -LiteralPath $Kaynak -Force | ForEach-Object {
    $ad = $_.Name
    if (Test-MiBoxRuntimeItem $_) { return }
    $hedefYol = Join-Path $Hedef $ad
    if ($ad -eq '_internal') {
        if (Test-Path -LiteralPath $hedefYol -PathType Leaf) {
            throw 'Paket hedefinde _internal dosya olarak bulunuyor.'
        }
        [IO.Directory]::CreateDirectory($hedefYol) | Out-Null
        Copy-DirectoryContents $_.FullName $hedefYol
    } else {
        if (Test-Path -LiteralPath $hedefYol -PathType Container) {
            throw "Dosya/klasor turu cakismasi: $ad"
        }
        [IO.File]::Copy($_.FullName, $hedefYol, $true)
    }
    $kopyalanan++
}
Yaz "Kopyalanan oge sayisi: $kopyalanan (kullanici verisi korundu)"

# 2) adb.exe bulunursa paket yanina kopyala (motor PATH'ten de bulabilir)
$adb = $null
$paketAdb = Join-Path $Kaynak 'adb.exe'
$yerelAdb = Join-Path $kok 'adb.exe'
if (Test-Path -LiteralPath $paketAdb -PathType Leaf) {
    $adb = $paketAdb
} elseif (Test-Path -LiteralPath $yerelAdb -PathType Leaf) {
    $adb = $yerelAdb
} else {
    $cmd = Get-Command adb.exe -ErrorAction SilentlyContinue
    if ($cmd) { $adb = $cmd.Source }
}
if ($adb) {
    $hedefAdb = Join-Path $Hedef 'adb.exe'
    if ([string]::Equals((Normalize-Path $adb), (Normalize-Path $hedefAdb),
            [StringComparison]::OrdinalIgnoreCase)) {
        Yaz 'adb.exe zaten kurulum hedefinde.'
    } else {
        [IO.File]::Copy($adb, $hedefAdb, $true)
        Yaz "adb.exe kopyalandi: $adb"
    }
} else {
    Yaz "uyari: adb.exe bulunamadi (motor PATH'ten arayacak)"
}

# 3) Kisayollar (masaustu + baslat menusu)
$kisayollar = @()
if (-not $KisayolYok) {
    $hedefler = @(
        (Join-Path ([Environment]::GetFolderPath('Desktop')) 'MiBox Konsol.lnk'),
        (Join-Path ([Environment]::GetFolderPath('Programs')) 'MiBox Konsol.lnk')
    )
    try {
        $ws = New-Object -ComObject WScript.Shell
        foreach ($temelLnk in $hedefler) {
            $lnk = $temelLnk
            $sira = 1
            while (Test-Path -LiteralPath $lnk) {
                $mevcutHedef = ''
                try {
                    $mevcut = $ws.CreateShortcut($lnk)
                    if ($mevcut.TargetPath) {
                        $mevcutHedef = Normalize-Path $mevcut.TargetPath
                    }
                } catch { }
                if ([string]::Equals($mevcutHedef, $exeYolu,
                        [StringComparison]::OrdinalIgnoreCase)) {
                    $kisayollar += $lnk
                    $lnk = $null
                    break
                }
                $sira++
                if ($sira -gt 1000) { throw 'Kisayol icin bos ad bulunamadi.' }
                $klasor = Split-Path -Parent $temelLnk
                $lnk = Join-Path $klasor ("MiBox Konsol ({0}).lnk" -f $sira)
            }
            if (-not $lnk) { continue }
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
        Yaz "       Uygulamayi kurulum klasorundeki MiBoxKonsol.exe dosyasindan acin."
    }
}

# 4) Kaldirma betigi (kisayollari siler; veriyi istege bagli temizler)
$kaldir = Join-Path $Hedef 'kaldir.bat'
$hedefBase64 = [Convert]::ToBase64String(
    [Text.Encoding]::Unicode.GetBytes($Hedef))
$kisayolJson = '[]'
if ($kisayollar.Count -gt 0) {
    $kisayolJson = ConvertTo-Json -InputObject $kisayollar -Compress
}
$kisayolBase64 = [Convert]::ToBase64String(
    [Text.Encoding]::Unicode.GetBytes($kisayolJson))
$kisayolScript = @'
$target = [IO.Path]::GetFullPath([Text.Encoding]::Unicode.GetString(
    [Convert]::FromBase64String('__TARGET__')))
$targetExe = Join-Path $target 'MiBoxKonsol.exe'
$linksJson = [Text.Encoding]::Unicode.GetString(
    [Convert]::FromBase64String('__LINKS__'))
$parsedLinks = ConvertFrom-Json -InputObject $linksJson
$links = if ($null -eq $parsedLinks) { @() } else { @($parsedLinks) }
foreach ($linkPath in $links) {
    if (-not (Test-Path -LiteralPath $linkPath -PathType Leaf)) { continue }
    try {
        $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($linkPath)
        if ($shortcut.TargetPath -and
            [string]::Equals([IO.Path]::GetFullPath($shortcut.TargetPath),
                $targetExe, [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $linkPath -Force -ErrorAction Stop
        }
    } catch {
        Write-Warning ("Kisayol kaldirilamadi: {0}" -f (Split-Path -Leaf $linkPath))
    }
}

# Eski surumun ASCII .bat kisayolunu yalniz icerigi MiBox baslatma satiriyla
# eslesiyorsa kaldir; ayni adli kullanici betigine dokunma.
$desktop = [Environment]::GetFolderPath('Desktop')
if ($desktop) {
    $legacyBat = Join-Path $desktop 'MiBox Konsol.bat'
    if (Test-Path -LiteralPath $legacyBat -PathType Leaf) {
        $expected = 'start "" "' + $targetExe + '"'
        $expectedAscii = [Text.Encoding]::ASCII.GetString(
            [Text.Encoding]::ASCII.GetBytes($expected))
        $content = (Get-Content -LiteralPath $legacyBat -Raw).Trim()
        if ($content -eq $expected -or $content -eq $expectedAscii) {
            Remove-Item -LiteralPath $legacyBat -Force
        }
    }
}
'@.Replace('__TARGET__', $hedefBase64).Replace('__LINKS__', $kisayolBase64)
$kisayolKomutu = [Convert]::ToBase64String(
    [Text.Encoding]::Unicode.GetBytes($kisayolScript))

$silmeScript = @'
param([switch]$RemoveData)
$ErrorActionPreference = 'Stop'
if (-not $RemoveData) { exit 2 }
try {
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

$exePath = Join-Path $target 'MiBoxKonsol.exe'
$internalPath = Join-Path $target '_internal'
if ((-not (Test-Path -LiteralPath $exePath -PathType Leaf) -and
     -not (Test-Path -LiteralPath $internalPath -PathType Container)) -or
    -not (Test-Path -LiteralPath (Join-Path $target 'kaldir.bat') -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $target 'MiBoxKonsol-Kaldir.ps1') -PathType Leaf)) {
    throw 'MiBox kurulum dosyalari dogrulanamadi; silme iptal edildi.'
}

# Uygulama kapanana kadar bekle; zaman asiminda hicbir dosyayi silme.
$deadline = (Get-Date).AddMinutes(2)
$running = $false
do {
    $running = $false
    foreach ($name in @('MiBoxKonsol', 'MiBoxKonsol_x86')) {
        foreach ($process in @(Get-Process -Name $name -ErrorAction SilentlyContinue)) {
            try {
                $processPath = $process.Path
                if ([string]::IsNullOrWhiteSpace($processPath)) {
                    $running = $true
                    break
                }
                $processPath = [IO.Path]::GetFullPath($processPath)
                $prefix = $target.TrimEnd([char]'\', [char]'/') + '\'
                if ($processPath.StartsWith($prefix,
                        [StringComparison]::OrdinalIgnoreCase)) {
                    $running = $true
                    break
                }
            } catch {
                $running = $true
                break
            }
        }
        if ($running) { break }
    }
    if ($running) { Start-Sleep -Milliseconds 500 }
} while ($running -and (Get-Date) -lt $deadline)
if ($running) {
    throw 'MiBox Konsol acik. Uygulamayi kapatip kaldirma betigini yeniden calistirin.'
}

# Yalniz uygulama dosyalarini ve bilinen MiBox verilerini kaldir; hedefteki
# diger kullanici dosyalari korunur.
if (Test-Path -LiteralPath $internalPath -PathType Container) {
    $internalEntry = Get-Item -LiteralPath $internalPath -Force
    if (($internalEntry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'Uygulama klasoru bir junction/symlink; silme iptal edildi.'
    }
    $reparse = Get-ChildItem -LiteralPath $internalPath -Force -Recurse |
        Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 } |
        Select-Object -First 1
    if ($reparse) {
        throw 'Uygulama klasorunde junction/symlink var; silme iptal edildi.'
    }
}
$files = @(
    'mibox-ayarlar.json', 'MiBox-ayarlar.json',
    'mibox-bilinen-uygulamalar.json', 'MiBox-bilinen-uygulamalar.json',
    'mibox-islem-gecmisi.jsonl', 'mibox-işlem-geçmişi.jsonl',
    'mibox-gecmis.csv', 'mibox-geçmiş.csv',
    'debloat-kullanici.json', 'debloat-kullanıcı.json',
    'mibox-selftest-ok.txt', 'mibox-logcat.txt', 'surum.txt',
    'ortam-bilgisi.txt', 'mibox-version.txt', 'scrcpy.exe',
    '.mibox-kurulum-devam')
foreach ($name in $files) {
    $path = Join-Path $target $name
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force -ErrorAction Stop
    }
}
$directories = @(
    'logs', 'snapshots', 'ekran-goruntuleri', 'ekran-videolari',
    'indirilen-apklar', 'apk-yedekleri', '_arsiv', 'scrcpy')
foreach ($name in $directories) {
    $path = Join-Path $target $name
    if (Test-Path -LiteralPath $path) {
        $entry = Get-Item -LiteralPath $path -Force
        if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            Remove-Item -LiteralPath $path -Force -ErrorAction Stop
        } else {
            Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop
        }
    }
}
$patterns = @(
    'mibox-ayarlar.json.*', 'MiBox-ayarlar.json.*',
    'mibox-ayar-yedek*.json*', '.mibox-ayar-yedek*.tmp',
    '.mibox-debloat-favorites-*.tmp',
    'mibox-snapshot-*.json', '.mibox-snapshot-*.tmp',
    '.mibox-download-*.part',
    '.scrcpy-preferred*', '.scrcpy_download.tmp.zip')
foreach ($pattern in $patterns) {
    Get-ChildItem -LiteralPath $target -Filter $pattern -File -Force -ErrorAction SilentlyContinue |
        ForEach-Object {
            if (($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop
            } else {
                Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
            }
        }
}
$internalPath = Join-Path $target '_internal'
if (Test-Path -LiteralPath $internalPath) {
    Remove-Item -LiteralPath $internalPath -Recurse -Force -ErrorAction Stop
}
foreach ($name in @('adb.exe', 'MiBoxKonsol_x86.exe', 'MiBoxKonsol.exe')) {
    $path = Join-Path $target $name
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force -ErrorAction Stop
    }
}
$remaining = @(Get-ChildItem -LiteralPath $target -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notin @('kaldir.bat', 'MiBoxKonsol-Kaldir.ps1') })
if ($remaining.Count -gt 0) {
    $names = ($remaining | ForEach-Object { $_.Name }) -join ', '
    Write-Host ("Diger dosyalar korundu: {0}" -f $names)
}
Write-Host 'MiBox uygulama dosyalari ve bilinen verileri kaldirildi.'
} catch {
    Write-Host ("[HATA] {0}" -f $_.Exception.Message)
    Read-Host 'Bu pencereyi kapatmak icin Enter tusuna basin'
    exit 1
}
'@.Replace('__TARGET__', $hedefBase64)
$kaldirPs1 = Join-Path $Hedef 'MiBoxKonsol-Kaldir.ps1'
$silmeScript | Set-Content -LiteralPath $kaldirPs1 -Encoding UTF8
$kaldirIcerik = @"
@echo off
REM MiBox Konsol kaldirma: kisayollari siler. Veriyi silmek icin /veri ekleyin.
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand $kisayolKomutu
if /I "%~1"=="/veri" (
  echo Bilinen MiBox verileri siliniyor; diger dosyalar korunacak...
  cd /d "%TEMP%"
  start "" /wait powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0MiBoxKonsol-Kaldir.ps1" -RemoveData
  if errorlevel 1 (
    echo [HATA] Uygulama veya dosyalar kaldirilamadi. Veriler korunmus olabilir.
    pause
    exit /b 1
  )
  del /f /q "%~dp0MiBoxKonsol-Kaldir.ps1" 2>nul
  del /f /q "%~f0" 2>nul
  rmdir "%~dp0" 2>nul
  exit /b 0
) else (
  echo Kisayollar kaldirildi. Program klasoru ve veriler korundu:
  echo Veriyi de silmek icin: kaldir.bat /veri
)
pause
"@
[IO.File]::WriteAllText($kaldir, $kaldirIcerik, [Text.Encoding]::ASCII)
Yaz "Kaldirma betigi: $kaldir"

# 5) Dogrulama: kurulan kopya surum + selftest
Yaz ""
Yaz "--- dogrulama ---"
# Dogrulama uygulamayi calistirir; olusan dosyalar TEMIZ kurulumda geri
# alinir, mevcut kullanimda DOKUNULMAZ.
$onceVardi = @{}
foreach ($ad in @('mibox-ayarlar.json', 'logs', 'snapshots', 'mibox-selftest-ok.txt')) {
    $onceVardi[$ad] = Test-Path -LiteralPath (Join-Path $Hedef $ad)
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
$satirlar = Get-Content -LiteralPath $surumDosya -ErrorAction SilentlyContinue
$surum = $satirlar | Select-Object -First 1
$mod = $satirlar | Where-Object { $_ -match '^Paket modu' } | Select-Object -First 1
Remove-Item -LiteralPath $surumDosya -ErrorAction SilentlyContinue
Yaz ("--version : {0} (exit {1})" -f $surum, $surumKod)
if ($mod) { Yaz ("            {0}" -f $mod.Trim()) }
if (-not $versionOk) { Yaz "[HATA] --version dogrulamasi basarisiz." }

$isaret = Join-Path $Hedef 'mibox-selftest-ok.txt'
Remove-Item -LiteralPath $isaret -ErrorAction SilentlyContinue
$markerReady = -not (Test-Path -LiteralPath $isaret)
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
if ($markerReady -and (Test-Path -LiteralPath $isaret)) {
    $markerContent = Get-Content -LiteralPath $isaret -Raw -ErrorAction SilentlyContinue
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
        $selftestKod, $(if (Test-Path -LiteralPath $isaret) { $markerContent } else { 'yok' }))
    Yaz "        exe'yi elle deneyin:"
    Yaz "        $exeYolu"
}

# Temiz kurulumda dogrulama artiklarini sil (mevcut ayarlara dokunma).
# mibox-selftest-ok.txt HER ZAMAN test artefaktidir -> kosulsuz silinir.
$silinen = @()
$marker = Join-Path $Hedef 'mibox-selftest-ok.txt'
if (Test-Path -LiteralPath $marker) {
    Remove-Item -LiteralPath $marker -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $marker)) { $silinen += 'mibox-selftest-ok.txt' }
}
foreach ($ad in @('mibox-ayarlar.json', 'logs', 'snapshots')) {
    if (-not $onceVardi[$ad]) {
        $yol = Join-Path $Hedef $ad
        if (Test-Path -LiteralPath $yol) {
            Remove-Item -LiteralPath $yol -Recurse -Force -ErrorAction SilentlyContinue
            if (-not (Test-Path -LiteralPath $yol)) { $silinen += $ad }
        }
    }
}
if ($silinen.Count -gt 0) {
    Yaz ("Temizlenen dogrulama artiklari: {0}" -f ($silinen -join ', '))
}
Yaz ""
if ($versionOk -and $selftestOk) {
    Remove-Item -LiteralPath $installMarker -Force -ErrorAction SilentlyContinue
    Yaz "TAMAM: MiBox Konsol kuruldu."
} else {
    Yaz "KURULUM BASARISIZ: dogrulama tamamlanmadi."
    exit 1
}
