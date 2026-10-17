# -*- coding: utf-8 -*-
"""Ekran goruntusu, logcat/cokme ve file_list dogrulama dallari testleri.

Kapsam: screenshot oncelik sirasi (dosya yolu once, exec-out yedek),
screenshot_via_file pull/unlink/temizlik hata dallari,
screenshot_hd_with_info fiziksel ekran yakalama ve yedek yollari,
logcat_crash hata dali, file_list tarih/isim dogrulamalari ve belirsiz
symlink cozumlemesi (_ls_symlink_name). Gercek cihaz veya ag yoktur.
"""
import os
import struct
import zlib

import pytest

from mibox_app.adb_engine import AdbEngine, AdbError, AdbResult


class ShellEngine(AdbEngine):
    """shell()/run() yerine kaydeden ve sahte yanit ureten motor."""

    def __init__(self, handler):
        super().__init__(adb_path='fake-adb')
        self.calls = []
        self._handler = handler

    def _handle(self, call):
        self.calls.append(call)
        result = self._handler(call)
        if result is None:
            raise AssertionError('Beklenmeyen ADB cagrisi: {}'.format(call))
        return result

    def shell(self, target, *cmd, **kwargs):
        return self._handle([str(c) for c in cmd])

    def run(self, args, timeout=30, binary=False, quiet_first=False,
            preserve_output_whitespace=False, cancel_check=None,
            hide_shell_from_trace=False):
        return self._handle([str(a) for a in args])


def _png_bytes():
    """1x1 piksel, gecerli chunk yapisi ve CRC'lerle PNG uretir."""
    def chunk(kind, payload):
        return (struct.pack('>I', len(payload)) + kind + payload
                + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff))

    ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)
    raw = b'\x00' + b'\xff\x00\x00\xff'
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def _hd_handler(display_output, execout_result, png):
    """HD sorgu + exec-out + dosya yolu akisini birlikte karsilar."""
    def handler(call):
        if call == ['dumpsys', 'SurfaceFlinger', '--display-id']:
            return AdbResult(0, display_output, '')
        if 'exec-out' in call:
            return execout_result
        if call[:2] == ['screencap', '-p']:
            return AdbResult(0, '', '')
        if call[:3] == ['-s', 'tv-1', 'pull']:
            with open(call[4], 'wb') as dosya:
                dosya.write(png)
            return AdbResult(0, '', '')
        if call[0] == 'rm':
            return AdbResult(0, '', '')
        return None

    return handler


# --- screenshot oncelik sirasi -----------------------------------------------

def test_screenshot_via_file_gecerli_ise_dogrudan_dondurur():
    png = _png_bytes()

    def handler(call):
        if call[:2] == ['screencap', '-p']:
            return AdbResult(0, '', '')
        if call[:3] == ['-s', 'tv-1', 'pull']:
            with open(call[4], 'wb') as dosya:
                dosya.write(png)
            return AdbResult(0, '', '')
        if call[0] == 'rm':
            return AdbResult(0, '', '')
        return None

    engine = ShellEngine(handler)
    assert engine.screenshot('tv-1') == png
    assert all('exec-out' not in call for call in engine.calls)


def test_screenshot_execout_istisnasi_yutulur():
    def handler(call):
        if call[:2] == ['screencap', '-p']:
            return AdbResult(1, '', 'yok')
        if call[0] == 'rm':
            return AdbResult(0, '', '')
        if 'exec-out' in call:
            raise AdbError('exec-out kopuk')
        return None

    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.screenshot('tv-1')
    assert 'Ekran goruntusu alinamadi' in str(exc.value)


def test_screenshot_via_file_pull_hatasi():
    def handler(call):
        if call[:2] == ['screencap', '-p']:
            return AdbResult(0, '', '')
        if call[0] == 'rm':
            return AdbResult(0, '', '')
        return None

    engine = ShellEngine(handler)
    # pull gercek kodda hatada yukseltir; savunma dalini dogrudan kur.
    engine.pull = lambda target, remote, local, timeout=30: AdbResult(
        1, '', 'pull yok')
    with pytest.raises(AdbError) as exc:
        engine.screenshot_via_file('tv-1')
    assert 'Ekran dosyası indirilemedi' in str(exc.value)
    assert engine.calls[-1][0] == 'rm'


def test_screenshot_via_file_unlink_hatasi_yutulur(monkeypatch):
    png = _png_bytes()

    def handler(call):
        if call[:2] == ['screencap', '-p']:
            return AdbResult(0, '', '')
        if call[:3] == ['-s', 'tv-1', 'pull']:
            with open(call[4], 'wb') as dosya:
                dosya.write(png)
            return AdbResult(0, '', '')
        if call[0] == 'rm':
            return AdbResult(0, '', '')
        return None

    def patla(path):
        raise OSError('kilitli')

    monkeypatch.setattr(os, 'unlink', patla)
    engine = ShellEngine(handler)
    assert engine.screenshot_via_file('tv-1') == png


def test_screenshot_via_file_temizlik_hatasi_yutulur():
    png = _png_bytes()

    def handler(call):
        if call[:2] == ['screencap', '-p']:
            return AdbResult(0, '', '')
        if call[:3] == ['-s', 'tv-1', 'pull']:
            with open(call[4], 'wb') as dosya:
                dosya.write(png)
            return AdbResult(0, '', '')
        if call[0] == 'rm':
            raise AdbError('rm yok')
        return None

    engine = ShellEngine(handler)
    assert engine.screenshot_via_file('tv-1') == png


# --- screenshot_hd -----------------------------------------------------------

def test_screenshot_hd_devreder():
    engine = ShellEngine(lambda call: None)
    engine.screenshot_hd_with_info = (
        lambda target, timeout=45, check_cancel=None: (b'veri', True))
    assert engine.screenshot_hd('tv-1') == b'veri'


def test_screenshot_hd_fiziksel_display_kullanilir():
    png = _png_bytes()
    engine = ShellEngine(_hd_handler(
        '  Display 0 (HWC display 0): port=0\n', AdbResult(0, png, ''), png))
    iptal = []
    veri, hd = engine.screenshot_hd_with_info(
        'tv-1', check_cancel=lambda: iptal.append(1))
    assert veri == png
    assert hd is True
    assert iptal == [1]
    execout = [call for call in engine.calls if 'exec-out' in call][0]
    assert execout == ['-s', 'tv-1', 'exec-out', 'screencap', '-d', '0', '-p']


def test_screenshot_hd_display_bulunamazsa_yedek():
    png = _png_bytes()
    engine = ShellEngine(_hd_handler('alakasiz\n', AdbResult(0, png, ''), png))
    sayac = []
    veri, hd = engine.screenshot_hd_with_info(
        'tv-1', check_cancel=lambda: sayac.append(1))
    assert veri == png
    assert hd is False
    assert len(sayac) == 2
    assert all('exec-out' not in call for call in engine.calls)


def test_screenshot_hd_execout_gecersiz_yedek():
    png = _png_bytes()
    engine = ShellEngine(_hd_handler(
        '  Display 0 (HWC display 0): port=0\n', AdbResult(1, b'', ''), png))
    veri, hd = engine.screenshot_hd_with_info('tv-1')
    assert veri == png
    assert hd is False


def test_screenshot_hd_dumpsys_istisnasi_yedek():
    png = _png_bytes()
    yedek = _hd_handler('', AdbResult(0, png, ''), png)

    def handler(call):
        if call == ['dumpsys', 'SurfaceFlinger', '--display-id']:
            raise AdbError('dumpsys yok')
        return yedek(call)

    engine = ShellEngine(handler)
    veri, hd = engine.screenshot_hd_with_info('tv-1')
    assert veri == png
    assert hd is False


def test_screenshot_hd_iptal_edilirse_durdurur():
    engine = ShellEngine(lambda call: None)

    def iptal():
        raise AdbError('kullanıcı durdurdu')

    with pytest.raises(AdbError) as exc:
        engine.screenshot_hd_with_info('tv-1', check_cancel=iptal)
    assert 'durdurdu' in str(exc.value)
    assert engine.calls == []


def test_screenshot_hd_istisna_sonrasi_iptal_kontrolu():
    png = _png_bytes()
    yedek = _hd_handler('', AdbResult(0, png, ''), png)

    def handler(call):
        if call == ['dumpsys', 'SurfaceFlinger', '--display-id']:
            raise AdbError('dumpsys yok')
        return yedek(call)

    engine = ShellEngine(handler)
    sayac = []
    veri, hd = engine.screenshot_hd_with_info(
        'tv-1', check_cancel=lambda: sayac.append(1))
    assert veri == png
    assert hd is False
    assert len(sayac) == 2


# --- logcat_crash ------------------------------------------------------------

def test_logcat_crash_hata():
    engine = ShellEngine(lambda call: AdbResult(1, '', ''))
    with pytest.raises(AdbError) as exc:
        engine.logcat_crash('tv-1')
    assert 'Çökme kayıtları okunamadı' in str(exc.value)


# --- file_list dogrulamalari -------------------------------------------------

def test_file_list_iso_saat_bozuk_atlanir():
    satir = ('-rw-r--r-- 1 u g 10 2024-01-01 12x45 veri.txt\n'
             '-rw-r--r-- 1 u g 20 2024-01-02 12:00 iyi.txt\n')
    engine = ShellEngine(lambda call: AdbResult(0, satir, ''))
    kayitlar = engine.file_list('tv-1', '/sdcard')
    assert [kayit['name'] for kayit in kayitlar] == ['iyi.txt']


def test_file_list_ay_adi_saat_bozuk_atlanir():
    satir = ('-rw-r--r-- 1 u g 10 Jan 1 xyz veri.txt\n'
             '-rw-r--r-- 1 u g 20 Jan 2 2024 iyi.txt\n')
    engine = ShellEngine(lambda call: AdbResult(0, satir, ''))
    kayitlar = engine.file_list('tv-1', '/sdcard')
    assert [kayit['name'] for kayit in kayitlar] == ['iyi.txt']


def test_file_list_isimsiz_satir_atlanir():
    satir = ('-rw-r--r-- 1 u g 10 2024-01-01 12:00\n'
             '-rw-r--r-- 1 u g 20 2024-01-02 12:00 dolu.txt\n')
    engine = ShellEngine(lambda call: AdbResult(0, satir, ''))
    kayitlar = engine.file_list('tv-1', '/sdcard')
    assert [kayit['name'] for kayit in kayitlar] == ['dolu.txt']


def test_file_list_symlink_benzersiz_cozulur():
    satir = 'lrwxrwxrwx 1 u g 10 2024-01-01 12:00 a -> b -> c\n'

    def handler(call):
        if call[0] == 'ls':
            return AdbResult(0, satir, '')
        if call[0] == 'readlink':
            if 'a -> b' in call[1]:
                return AdbResult(0, 'zzz\n', '')
            return AdbResult(0, 'b -> c\n', '')
        return None

    engine = ShellEngine(handler)
    kayitlar = engine.file_list('tv-1', '/sdcard')
    assert [kayit['name'] for kayit in kayitlar] == ['a']


def test_file_list_symlink_belirsiz_atlanir():
    satir = 'lrwxrwxrwx 1 u g 10 2024-01-01 12:00 a -> b -> c\n'

    def handler(call):
        if call[0] == 'ls':
            return AdbResult(0, satir, '')
        if call[0] == 'readlink':
            if 'a -> b' in call[1]:
                return AdbResult(0, 'c\n', '')
            return AdbResult(0, 'b -> c\n', '')
        return None

    engine = ShellEngine(handler)
    assert engine.file_list('tv-1', '/sdcard') == []


def test_file_list_symlink_readlink_hatasi_atlanir():
    satir = 'lrwxrwxrwx 1 u g 10 2024-01-01 12:00 a -> b -> c\n'

    def handler(call):
        if call[0] == 'ls':
            return AdbResult(0, satir, '')
        if call[0] == 'readlink':
            raise AdbError('readlink yok')
        return None

    engine = ShellEngine(handler)
    assert engine.file_list('tv-1', '/sdcard') == []


def test_file_list_symlink_bos_ad_atlanir():
    satir = 'lrwxrwxrwx 1 u g 10 2024-01-01 12:00  -> a -> b\n'

    def handler(call):
        if call[0] == 'ls':
            return AdbResult(0, satir, '')
        if call[0] == 'readlink':
            return AdbResult(0, 'zzz\n', '')
        return None

    engine = ShellEngine(handler)
    assert engine.file_list('tv-1', '/sdcard') == []
