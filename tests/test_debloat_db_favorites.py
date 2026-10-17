# -*- coding: utf-8 -*-
"""Debloat favori (kullanici girdisi) kalicilik testleri.

Gercek kullanici dosyasina dokunulmaz: _user_entries_path gecici dizine
yonlendirilir ve modul onbellegi her testte sifirlanir.
"""
import json

import pytest

from mibox_app import debloat_db


@pytest.fixture
def favorites(tmp_path, monkeypatch):
    path = tmp_path / 'debloat-kullanici.json'
    monkeypatch.setattr(debloat_db, '_user_entries_path', lambda: str(path))
    monkeypatch.setattr(debloat_db, '_FAVORITES', [])
    monkeypatch.setattr(debloat_db, '_user_entries_loaded', False)
    monkeypatch.setattr(debloat_db, '_user_entries_load_error', '')
    return path


def test_favori_eklenir_ve_dosyaya_yazilir(favorites):
    assert debloat_db.add_user_entry('com.ornek.uygulama', 'Örnek', 'Açıklama') is True

    assert debloat_db.user_entries() == [
        ('com.ornek.uygulama', 'Örnek', 'Açıklama')]
    data = json.loads(favorites.read_text(encoding='utf-8'))
    assert data == [['com.ornek.uygulama', 'Örnek', 'Açıklama']]


def test_ayni_paket_ikinci_kez_eklenmez(favorites):
    assert debloat_db.add_user_entry('com.ornek.uygulama', 'Örnek', '') is True
    assert debloat_db.add_user_entry('com.ornek.uygulama', 'Örnek 2', '') is False
    assert len(debloat_db.user_entries()) == 1


def test_db_de_olan_paket_favoriye_eklenmez(favorites):
    existing = next(iter(debloat_db.DEBLOAT_DB.values()))[0][0]

    assert debloat_db.add_user_entry(existing, 'Kopya', '') is False
    assert debloat_db.user_entries() == []


def test_gecersiz_paket_reddedilir(favorites):
    with pytest.raises(ValueError):
        debloat_db.add_user_entry('gecersiz paket', 'X', '')
    with pytest.raises(ValueError):
        debloat_db.add_user_entry('com.foo:u5', 'X', '')
    with pytest.raises(ValueError):
        debloat_db.add_user_entry(None, 'X', '')

    assert not favorites.exists(), 'gecersiz girdi icin dosya olusmamali'


def test_kayit_silme_tek_seferde_yazilir(favorites):
    debloat_db.add_user_entry('com.a.a', 'A', '')
    debloat_db.add_user_entry('com.b.b', 'B', '')

    assert debloat_db.remove_user_entries(['com.a.a']) is True
    assert [entry[0] for entry in debloat_db.user_entries()] == ['com.b.b']
    assert debloat_db.remove_user_entries(['com.a.a']) is False


def test_ekleme_kayit_hatasi_geri_alir(favorites, monkeypatch):
    def patlak_kayit():
        raise OSError('kaydedilemez')

    monkeypatch.setattr(debloat_db, '_save_user_entries', patlak_kayit)

    with pytest.raises(OSError):
        debloat_db.add_user_entry('com.yeni.paket', 'Yeni', 'Aciklama')

    assert debloat_db.user_entries() == []


def test_silme_kayit_hatasi_geri_alir(favorites, monkeypatch):
    assert debloat_db.add_user_entry('com.a.a', 'A', '') is True

    def patlak_kayit():
        raise OSError('kaydedilemez')

    monkeypatch.setattr(debloat_db, '_save_user_entries', patlak_kayit)

    with pytest.raises(OSError):
        debloat_db.remove_user_entries(['com.a.a'])

    assert debloat_db.user_entries() == [('com.a.a', 'A', '')]


def test_yeniden_yukleme_diskten_okur(favorites, monkeypatch):
    debloat_db.add_user_entry('com.a.a', 'A', '')
    # Onbellegi sifirla: yeni surec gibi davran.
    monkeypatch.setattr(debloat_db, '_FAVORITES', [])
    monkeypatch.setattr(debloat_db, '_user_entries_loaded', False)

    assert debloat_db.user_entries() == [('com.a.a', 'A', '')]


def test_bozuk_dosya_uzerine_yazilmaz(favorites):
    favorites.write_text('{"beklenen": "liste"}', encoding='utf-8')

    assert debloat_db.user_entries() == []
    with pytest.raises(OSError):
        debloat_db.add_user_entry('com.a.a', 'A', '')
    with pytest.raises(OSError):
        debloat_db.remove_user_entries(['com.a.a'])

    assert favorites.read_text(encoding='utf-8') == '{"beklenen": "liste"}'


def test_bozuk_kayit_icerigi_reddedilir(favorites):
    favorites.write_text(json.dumps([['gecersiz paket', 'X', 'Y']]),
                         encoding='utf-8')

    with pytest.raises(OSError):
        debloat_db.add_user_entry('com.a.a', 'A', '')

    assert favorites.read_text(encoding='utf-8') == json.dumps(
        [['gecersiz paket', 'X', 'Y']])


def test_bozuk_kayit_yapisi_reddedilir(favorites):
    favorites.write_text(json.dumps([[1, 2, 3]]), encoding='utf-8')

    assert debloat_db.user_entries() == []
    with pytest.raises(OSError):
        debloat_db.add_user_entry('com.a.a', 'A', '')


def test_yol_hatasinda_mesaj_yedegi(favorites, monkeypatch):
    def patlak_yol():
        raise OSError('yol yok')

    monkeypatch.setattr(debloat_db, '_user_entries_path', patlak_yol)

    debloat_db._load_user_entries()

    assert debloat_db._user_entries_load_error == (
        'Kullanıcı favori dosyası okunamadı; üzerine yazılmayacak.')


def test_ad_ve_aciklama_uzunlugu_sinirlanir(favorites):
    assert debloat_db.add_user_entry('com.a.a', 'N' * 200, 'D' * 600) is True

    pkg, name, desc = debloat_db.user_entries()[0]
    assert pkg == 'com.a.a'
    assert len(name) == 128
    assert len(desc) == 512


def test_kayit_temizlik_hatalari_yutulur(favorites, monkeypatch):
    def patlak_fdopen(fd, *args, **kwargs):
        raise OSError('fdopen yok')

    def patlak_kapat(fd):
        raise OSError('kapanmaz')

    def patlak_sil(path):
        raise OSError('silinemez')

    monkeypatch.setattr(debloat_db.os, 'fdopen', patlak_fdopen)
    monkeypatch.setattr(debloat_db.os, 'close', patlak_kapat)
    monkeypatch.setattr(debloat_db.os, 'remove', patlak_sil)

    with pytest.raises(OSError):
        debloat_db._save_user_entries()
