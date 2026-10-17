# -*- coding: utf-8 -*-
"""history.py: JSONL işlem geçmişi testleri.

Gerçek kullanıcı geçmişine dokunulmaz: config.BASE_DIR geçici klasöre
yönlendirilir (history._path() BASE_DIR'i çağrı anında okur).
"""
import json

import pytest

from mibox_app import config, history


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'BASE_DIR', str(tmp_path))
    return tmp_path


def _kayitlar(base):
    yol = base / 'mibox-islem-gecmisi.jsonl'
    return [json.loads(satir)
            for satir in yol.read_text(encoding='utf-8').splitlines() if satir]


# --- append ------------------------------------------------------------------

def test_full_uninstall_history_cannot_be_undone(base):
    from mibox_app.ui.history_tab import HistoryTab

    history.append_many('tv-1', 'uninstall_full', [('com.foo', True, 'veriler silindi')])
    record = _kayitlar(base)[0]
    assert record['action'] == 'uninstall_full'
    assert history.inverse_of(record['action']) is None
    assert HistoryTab._inverse_for_record(history, record) is None


def test_append_kaydi_yazar(base):
    ok = history.append('tv-1', 'disable', 'com.foo', 'disable', True, user_id=2)
    assert ok is True
    kayitlar = _kayitlar(base)
    assert len(kayitlar) == 1
    kayit = kayitlar[0]
    assert kayit['target'] == 'tv-1'
    assert kayit['action'] == 'disable'
    assert kayit['package'] == 'com.foo'
    assert kayit['method'] == 'disable'
    assert kayit['ok'] is True
    assert kayit['user_id'] == 2
    assert kayit['ts']


def test_append_varsayilanlar_ve_ok_normallestirme(base):
    history.append('tv-1', 'enable', 'com.foo', ok=1)
    kayit = _kayitlar(base)[0]
    assert kayit['method'] == ''
    assert kayit['ok'] is True
    assert kayit['user_id'] == 0


def test_append_turkce_karakterler_kacirilmaz(base):
    history.append('TV Üst Kat', 'disable', 'com.foo')
    ham = (base / 'mibox-islem-gecmisi.jsonl').read_text(encoding='utf-8')
    assert 'TV Üst Kat' in ham
    assert '\\u00dc' not in ham


@pytest.mark.parametrize('kotu', [-1, 21475, '0', True, None, 1.5])
def test_append_gecersiz_kullanici_kimligi(base, kotu):
    with pytest.raises(ValueError):
        history.append('tv-1', 'disable', 'com.foo', user_id=kotu)


def test_append_sinir_kullanici_kimlikleri_gecer(base):
    assert history.append('tv-1', 'disable', 'com.a', user_id=0) is True
    assert history.append('tv-1', 'disable', 'com.b', user_id=21474) is True
    assert len(_kayitlar(base)) == 2


def test_append_yazilamazsa_false(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'BASE_DIR', str(tmp_path / 'yok'))
    assert history.append('tv-1', 'disable', 'com.foo') is False


# --- read_all ----------------------------------------------------------------

def test_read_all_yeniden_eskiye_siralar(base):
    history.append('tv-1', 'disable', 'com.a')
    history.append('tv-1', 'enable', 'com.b')
    history.append('tv-1', 'uninstall', 'com.c')
    kayitlar = history.read_all()
    assert [k['package'] for k in kayitlar] == ['com.c', 'com.b', 'com.a']


def test_read_all_limit_uygular(base):
    for i in range(5):
        history.append('tv-1', 'disable', 'com.{}'.format(i))
    kayitlar = history.read_all(limit=2)
    assert [k['package'] for k in kayitlar] == ['com.4', 'com.3']


def test_read_all_dosya_yoksa_bos(base):
    assert history.read_all() == []


def test_read_all_bozuk_satirlari_atlar(base):
    yol = base / 'mibox-islem-gecmisi.jsonl'
    yol.write_text(
        '{"ts":"t","target":"tv","action":"disable","package":"com.a",'
        '"method":"","ok":true,"user_id":0}\n'
        'bozuk json\n'
        '\n'
        '["liste"]\n'
        '{"ts":"t","target":"tv","action":"disable","package":"",'
        '"method":"","ok":true,"user_id":0}\n',
        encoding='utf-8')
    kayitlar = history.read_all()
    assert [k['package'] for k in kayitlar] == ['com.a']


def test_read_all_okuma_hatasinda_bos(monkeypatch):
    def patlak():
        raise OSError('yol yok')

    monkeypatch.setattr(history, '_path', patlak)

    assert history.read_all() == []


# --- clear / inverse_of ------------------------------------------------------

def test_clear_dosyayi_siler(base):
    history.append('tv-1', 'disable', 'com.a')
    assert (base / 'mibox-islem-gecmisi.jsonl').exists()
    history.clear()
    assert not (base / 'mibox-islem-gecmisi.jsonl').exists()
    history.clear()  # ikinci çağrı hata vermez


def test_inverse_of_eslemeleri():
    assert history.inverse_of('uninstall') == 'restore'
    assert history.inverse_of('disable') == 'enable'
    assert history.inverse_of('restrict') == 'unrestrict'
    assert history.inverse_of('enable') == 'disable'
    assert history.inverse_of('restore') == 'smart'
    assert history.inverse_of('unrestrict') == 'restrict'


@pytest.mark.parametrize('aksiyon', ['clear', 'stop', 'launch', 'bilinmeyen'])
def test_inverse_of_geri_alinamazlar_none(aksiyon):
    assert history.inverse_of(aksiyon) is None


# --- append_many -------------------------------------------------------------

def test_append_many_uc_demet_ortak_aksiyon(base):
    ok = history.append_many('tv-1', 'uninstall', [
        ('com.a', True, 'tamam'),
        ('com.b', False, 'hata'),
    ])
    assert ok is True
    kayitlar = _kayitlar(base)
    assert [(k['action'], k['package'], k['ok'], k['method']) for k in kayitlar] == [
        ('uninstall', 'com.a', True, 'uninstall'),
        ('uninstall', 'com.b', False, 'uninstall'),
    ]


def test_append_many_dort_demet_paket_basina_aksiyon(base):
    history.append_many('tv-1', 'toplu', [
        ('disable', 'com.a', True, 'disable ile kapatildi'),
        ('uninstall', 'com.b', True, 'uninstall ile kaldirildi'),
    ])
    kayitlar = _kayitlar(base)
    assert [(k['action'], k['method']) for k in kayitlar] == [
        ('disable', 'disable'), ('uninstall', 'uninstall')]


def test_append_many_method_oneki_aksiyondan_once_gelir(base):
    history.append_many('tv-1', 'toplu', [
        ('uninstall', 'com.a', True, 'disable ile kapatildi'),
    ])
    assert _kayitlar(base)[0]['method'] == 'disable'


def test_append_many_diger_aksiyonlarda_method_bos(base):
    history.append_many('tv-1', 'enable', [('com.a', True, 'tamam')])
    assert _kayitlar(base)[0]['method'] == ''


def test_append_many_kullanici_kimligini_tasir(base):
    history.append_many('tv-1', 'disable', [('com.a', True, 'tamam')], user_id=3)
    assert _kayitlar(base)[0]['user_id'] == 3


def test_append_many_yazilamazsa_false(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'BASE_DIR', str(tmp_path / 'yok'))
    assert history.append_many('tv-1', 'disable', [('com.a', True, 'tamam')]) is False
