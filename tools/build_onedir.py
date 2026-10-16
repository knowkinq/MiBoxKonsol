# -*- coding: utf-8 -*-
"""MiBoxKonsol.spec'ten ONEDIR (klasor) paket uretir ve derler.

Neden: tek-dosya (onefile) paket calisirken %TEMP% altinda `_MEI...` klasoru
acar; kisitli token / antivirus / kilitli temp olan makinelerde bu adim
"Could not create temporary directory!" ile duser. onedir paket hic gecici
klasor acmaz: exe + DLL'ler + Qt eklentileri ayni klasorden calisir.

Tek kaynak: exclude/filtre mantigi MiBoxKonsol.spec'ten gelir; bu arac
yalnizca EXE(...) blogunu EXE+COLLECT (onedir) bloguna cevirir. Boylece
iki spec'in zamanla ayrismasi (drift) olmaz.

Kullanim:
    python tools/build_onedir.py
Cikti:
    dist-onedir/MiBoxKonsol/MiBoxKonsol.exe
"""
import os
import re
import glob
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KAYNAK_SPEC = os.path.join(ROOT, 'MiBoxKonsol.spec')
URETILEN_SPEC = os.path.join(ROOT, 'build', 'MiBoxKonsol-onedir.spec')
DIST = os.path.join(ROOT, 'dist-onedir')
WORK = os.path.join(ROOT, 'build', 'onedir-work')

EXE_BLOGU = re.compile(r'\nexe = EXE\(.*?\n\)\n', re.S)

ONEDIR_BLOGU = '''
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MiBoxKonsol',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MiBoxKonsol',
)
'''


def _temizle(paket_dir):
    """Pakete sizmasi istenmeyen calisma zamani dosyalarini sil.

    build_exe.bat ile ayni disiplin: kisisel ayarlar ve test izleri dagitilan
    pakete girmesin.
    """
    dist_root = os.path.realpath(DIST)
    paket_dir = os.path.realpath(paket_dir)
    if os.path.dirname(paket_dir) != dist_root or os.path.basename(paket_dir) != 'MiBoxKonsol':
        raise ValueError('Paket temizleme yolu dist-onedir/MiBoxKonsol dışında olamaz.')

    gereksiz = ('mibox-ayarlar.json', 'MiBox-ayarlar.json',
                'mibox-bilinen-uygulamalar.json', 'MiBox-bilinen-uygulamalar.json',
                'mibox-islem-gecmisi.jsonl', 'mibox-işlem-geçmişi.jsonl',
                'mibox-gecmis.csv', 'mibox-geçmiş.csv',
                'debloat-kullanici.json', 'debloat-kullanıcı.json',
                'mibox-selftest-ok.txt', 'mibox-logcat.txt', 'surum.txt',
                'ortam-bilgisi.txt', 'mibox-version.txt', 'scrcpy.exe')
    silinen = []
    silinemeyen = []

    def _sil(yol, ad):
        try:
            if os.path.islink(yol) or os.path.isfile(yol):
                os.remove(yol)
            elif os.path.isdir(yol):
                shutil.rmtree(yol)
            else:
                raise OSError('Desteklenmeyen dosya türü')
            silinen.append(ad)
        except OSError as e:
            silinemeyen.append((ad, e.strerror or type(e).__name__))

    for ad in gereksiz:
        yol = os.path.join(paket_dir, ad)
        if os.path.lexists(yol):
            _sil(yol, ad)

    for ad in ('logs', 'snapshots', 'ekran-goruntuleri', 'ekran-videolari',
               'indirilen-apklar', 'apk-yedekleri', '_arsiv', 'scrcpy'):
        yol = os.path.join(paket_dir, ad)
        if os.path.lexists(yol):
            _sil(yol, ad)

    for pattern in ('scrcpy-*', '.mibox-scrcpy-*'):
        paths = glob.glob(os.path.join(glob.escape(paket_dir), pattern))
        for yol in paths:
            _sil(yol, os.path.basename(yol))

    for pattern in (
            'mibox-ayarlar.json.*', 'MiBox-ayarlar.json.*',
            'mibox-ayar-yedek*.json*', '.mibox-ayar-yedek*.tmp',
            '.mibox-debloat-favorites-*.tmp',
            'mibox-snapshot-*.json', '.mibox-snapshot-*.tmp',
            '.mibox-download-*.part', '*.apk', '*.apks', '*.xapk',
            '*.log', '*.jsonl', '*.csv', '.scrcpy-preferred*',
            '.scrcpy_download.tmp.zip', '.mibox-kurulum-devam'):
        for yol in glob.glob(os.path.join(glob.escape(paket_dir), pattern)):
            _sil(yol, os.path.basename(yol))
    if silinemeyen:
        details = ', '.join('{} ({})'.format(ad, error)
                            for ad, error in silinemeyen)
        raise OSError('Kullanıcı/çalışma zamanı dosyaları temizlenemedi: ' + details)
    if silinen:
        print('temizlenen dosyalar:', ', '.join(silinen))


def main():
    if sys.argv[1:] == ['--clean-package']:
        paket_dir = os.path.join(DIST, 'MiBoxKonsol')
        if not os.path.isdir(paket_dir):
            print('HATA: temizlenecek paket bulunamadi: {}'.format(paket_dir))
            return 1
        _temizle(paket_dir)
        return 0
    if len(sys.argv) > 1:
        print('Kullanim: python tools/build_onedir.py [--clean-package]')
        return 2
    if not os.path.exists(KAYNAK_SPEC):
        print('HATA: spec bulunamadi: {}'.format(KAYNAK_SPEC))
        return 1
    with open(KAYNAK_SPEC, 'r', encoding='utf-8') as f:
        spec = f.read()
    yeni, sayi = EXE_BLOGU.subn(ONEDIR_BLOGU, spec, count=1)
    if sayi != 1:
        print('HATA: MiBoxKonsol.spec icinde EXE(...) blogu bulunamadi '
              '(spec degismis olabilir).')
        return 1
    # Uretilen spec build/ altina yazildigi icin giris betigi MUTLAK yol olmali.
    giris = os.path.join(ROOT, 'mibox.py').replace('\\', '/')
    yeni = yeni.replace("['mibox.py']", "['" + giris + "']")
    if giris not in yeni:
        print('HATA: Analysis giris betigi yolu degistirilemedi.')
        return 1
    os.makedirs(os.path.dirname(URETILEN_SPEC), exist_ok=True)
    with open(URETILEN_SPEC, 'w', encoding='utf-8') as f:
        f.write(yeni)
    print('uretilen spec :', URETILEN_SPEC)
    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
           '--distpath', DIST, '--workpath', WORK, URETILEN_SPEC]
    print('derleniyor    :', ' '.join(cmd))
    kod = subprocess.call(cmd, cwd=ROOT)
    if kod == 0:
        _temizle(os.path.join(DIST, 'MiBoxKonsol'))
    return kod


if __name__ == '__main__':
    sys.exit(main())
