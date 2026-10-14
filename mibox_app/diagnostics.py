# -*- coding: utf-8 -*-
"""Surum + ortam/kurulum bilgisi (TEK KAYNAK).

Nerede kullanilir:
  - `mibox.py --version` (pencere acmadan, cikti dosyaya yonlendirilebilir)
  - Ayarlar sekmesi -> "Surum / Kurulum Bilgisi" paneli (panoya kopyalanabilir)

Boylece iki yerde farkli bilgi gosterilmez; destek icin istenen "hangi surum,
hangi paket modu, adb nerede, log nerede" sorularinin yaniti tektir.
"""
import os
import platform
import sys

from . import APP_NAME, __version__

MOD_KAYNAK = 'kaynak'
MOD_ONEFILE = 'onefile'
MOD_ONEDIR = 'onedir'


def paket_modu():
    """Calisma bicimi: 'kaynak' | 'onedir' | 'onefile'.

    onefile: her acilista %TEMP%\\_MEIxxxx klasorune acar (kisitli makinede
             "Could not create temporary directory" hatasi verebilir).
    onedir : exe + _internal ayni klasorden calisir, gecici klasor ACMAZ.
    """
    if not getattr(sys, 'frozen', False):
        return MOD_KAYNAK
    meipass = os.path.abspath(getattr(sys, '_MEIPASS', '') or '')
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    try:
        if meipass and os.path.commonpath([meipass, exe_dir]) == exe_dir:
            return MOD_ONEDIR
    except (ValueError, OSError):
        pass
    return MOD_ONEFILE


def _adb_yolu():
    try:
        from .adb_engine import AdbEngine
        return AdbEngine.find_adb() or '(bulunamadi)'
    except Exception:  # noqa: BLE001
        return '(bulunamadi)'


def _selftest_yolu():
    try:
        from .main import _selftest_path
        return _selftest_path()
    except Exception:  # noqa: BLE001
        return '-'


def ortam_bilgisi():
    """[(etiket, deger)] — sirali; arayuz ve CLI ayni listeyi kullanir."""
    from .config import BASE_DIR, CONFIG_PATH, LOG_DIR
    from .qt_compat import get_qt_info
    qt_info = get_qt_info()
    return [
        ('Sürüm', '{} v{}'.format(APP_NAME, __version__)),
        ('Mimari', qt_info['arch']),
        ('Paket modu', paket_modu()),
        ('Qt motoru', '{} (Qt {})'.format(qt_info['api'], qt_info['version'])),
        ('Python', '{} ({})'.format(platform.python_version(), qt_info['arch'])),
        ('İşletim sistemi', '{} {} ({})'.format(platform.system(), platform.release(), platform.machine())),
        ('Frozen', str(bool(getattr(sys, 'frozen', False)))),
        ('MEIPASS', getattr(sys, '_MEIPASS', '-') or '-'),
        ('Çalıştırılabilir', sys.executable),
        ('Base dir', BASE_DIR),
        ('Ayar dosyası', CONFIG_PATH),
        ('Log klasörü', LOG_DIR),
        ('adb yolu', _adb_yolu()),
        ('Selftest işaretçisi', _selftest_yolu()),
        ('Çalışma dizini', os.getcwd()),
    ]


def metin():
    """Insan-okur cok satirli metin (CLI ciktisi / panoya kopyalama)."""
    return '\n'.join('{:<20}: {}'.format(k, v) for k, v in ortam_bilgisi())


rapor_metni = metin
