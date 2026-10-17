# -*- coding: utf-8 -*-
"""Tani/surum bilgisi testleri: paket modu tespiti, ortam listesi, paylasim metni.

Gercek adb aranmaz, diske yazilmaz: adb/selftest yollari taklit edilir.
"""
import sys
import types

import pytest

from mibox_app import APP_NAME, __version__, diagnostics


@pytest.fixture
def yollar(monkeypatch):
    """_adb_yolu/_selftest_yolu deterministik deger dondursun."""
    monkeypatch.setattr(diagnostics, '_adb_yolu',
                        lambda: 'C:\\platform-tools\\adb.exe')
    monkeypatch.setattr(diagnostics, '_selftest_yolu',
                        lambda: 'C:\\log\\selftest.txt')


def test_paket_modu_kaynak(monkeypatch):
    monkeypatch.delattr(sys, 'frozen', raising=False)
    assert diagnostics.paket_modu() == diagnostics.MOD_KAYNAK


def test_paket_modu_onedir(monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', 'C:\\uyg\\MiBoxKonsol.exe',
                        raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', 'C:\\uyg\\_internal', raising=False)
    assert diagnostics.paket_modu() == diagnostics.MOD_ONEDIR


def test_paket_modu_onefile(monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', 'C:\\uyg\\MiBoxKonsol.exe',
                        raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', 'C:\\Temp\\_MEI12345', raising=False)
    assert diagnostics.paket_modu() == diagnostics.MOD_ONEFILE


def test_paket_modu_farkli_surucu_onefile(monkeypatch):
    # commonpath farkli suruculerde ValueError atar; mod tespiti cokmemeli.
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', 'D:\\uyg\\MiBoxKonsol.exe',
                        raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', 'C:\\Temp\\_MEI99', raising=False)
    assert diagnostics.paket_modu() == diagnostics.MOD_ONEFILE


def test_ortam_bilgisi_alanlari(yollar):
    bilgi = dict(diagnostics.ortam_bilgisi())

    assert bilgi['Sürüm'] == '{} v{}'.format(APP_NAME, __version__)
    assert bilgi['Paket modu'] in (diagnostics.MOD_KAYNAK,
                                   diagnostics.MOD_ONEDIR,
                                   diagnostics.MOD_ONEFILE)
    assert bilgi['adb yolu'] == 'C:\\platform-tools\\adb.exe'
    assert bilgi['Selftest işaretçisi'] == 'C:\\log\\selftest.txt'
    assert bilgi['Frozen'] == str(bool(getattr(sys, 'frozen', False)))
    for etiket in ('Ayar dosyası', 'Log klasörü', 'Base dir',
                   'Çalıştırılabilir', 'Qt motoru', 'Python'):
        assert etiket in bilgi


def test_metin_satir_bicimi(yollar):
    satirlar = diagnostics.metin().splitlines()

    assert satirlar
    assert all(':' in satir for satir in satirlar)
    surum_satiri = next(s for s in satirlar if s.startswith('Sürüm'))
    assert APP_NAME in surum_satiri and __version__ in surum_satiri


def test_paylasim_metni_dosya_yollari_icermez(yollar):
    paylasim = diagnostics.paylasim_metni()

    assert 'Sürüm' in paylasim
    for gizli in ('adb yolu', 'Base dir', 'Ayar dosyası', 'Log klasörü',
                  'Çalıştırılabilir', 'MEIPASS', 'Frozen'):
        assert gizli not in paylasim


def test_rapor_metni_metin_ile_ayni(yollar):
    assert diagnostics.rapor_metni() == diagnostics.metin()


def test_adb_yolu_bulunursa(monkeypatch):
    monkeypatch.setattr('mibox_app.adb_engine.AdbEngine.find_adb',
                        staticmethod(lambda: 'C:\\adb\\adb.exe'))
    assert diagnostics._adb_yolu() == 'C:\\adb\\adb.exe'


def test_adb_yolu_bulunamazsa(monkeypatch):
    monkeypatch.setattr('mibox_app.adb_engine.AdbEngine.find_adb',
                        staticmethod(lambda: None))
    assert diagnostics._adb_yolu() == '(bulunamadi)'


def test_adb_yolu_hatada_bulunamadi(monkeypatch):
    def patla():
        raise RuntimeError('arama çöktü')

    monkeypatch.setattr('mibox_app.adb_engine.AdbEngine.find_adb',
                        staticmethod(patla))
    assert diagnostics._adb_yolu() == '(bulunamadi)'


def test_selftest_yolu_okunur(monkeypatch):
    fake = types.ModuleType('mibox_app.main')
    fake._selftest_path = lambda: 'C:\\log\\selftest.txt'
    monkeypatch.setitem(sys.modules, 'mibox_app.main', fake)
    assert diagnostics._selftest_yolu() == 'C:\\log\\selftest.txt'


def test_selftest_yolu_hatada_tire(monkeypatch):
    fake = types.ModuleType('mibox_app.main')

    def patla():
        raise RuntimeError('yok')

    fake._selftest_path = patla
    monkeypatch.setitem(sys.modules, 'mibox_app.main', fake)
    assert diagnostics._selftest_yolu() == '-'
