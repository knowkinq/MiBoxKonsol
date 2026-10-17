# -*- coding: utf-8 -*-
"""Katalog testleri: yapi degismezleri ve indirme dogrulama akisi.

Ag erisimi YOK: urllib.request.urlopen sahte yanitla degistirilir.
Indirme testleri gercek ZIP (AndroidManifest.xml iceren) govdesi uretir.
"""
import hashlib
import io
import os
import re
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from mibox_app.catalog import TV_CATALOG, TV_CATEGORIES, download_apk, get_catalog

APK_ZORUNLU_ANAHTARLAR = ('id', 'name', 'category', 'icon', 'package',
                          'description', 'url', 'website')
MAGAZA_ZORUNLU_ANAHTARLAR = ('id', 'name', 'category', 'icon', 'package',
                             'description', 'store_url', 'website')


def _magaza_mi(item):
    return str(item.get('type') or '').strip().lower() == 'store'


def _zorunlu_anahtarlar(item):
    return MAGAZA_ZORUNLU_ANAHTARLAR if _magaza_mi(item) else APK_ZORUNLU_ANAHTARLAR


# --- yapi degismezleri ------------------------------------------------------

def test_katalog_kayitlari_zorunlu_anahtarlari_icerir():
    for item in TV_CATALOG:
        for key in _zorunlu_anahtarlar(item):
            assert item.get(key), '{}: eksik/boş alan: {}'.format(item.get('id'), key)


def test_katalog_turleri_gecerli():
    for item in TV_CATALOG:
        tur = str(item.get('type') or 'apk').strip().lower()
        assert tur in ('apk', 'store'), item['id']


def test_magaza_ve_apk_kayitlari_tutarli():
    for item in TV_CATALOG:
        if _magaza_mi(item):
            assert 'url' not in item, '{}: mağaza kaydında APK adresi olmamalı'.format(
                item['id'])
            assert not item.get('sha256'), '{}: mağaza kaydı sabitlenmez'.format(
                item['id'])
        else:
            assert 'store_url' not in item, '{}: APK kaydında store_url olmamalı'.format(
                item['id'])


def test_katalog_id_leri_tekil():
    ids = [item['id'] for item in TV_CATALOG]
    assert len(ids) == len(set(ids))


def test_katalog_paket_adlari_tekil():
    packages = [item['package'] for item in TV_CATALOG]
    assert len(packages) == len(set(packages))


def test_katalog_kategorileri_gecerli():
    for item in TV_CATALOG:
        assert item['category'] in TV_CATEGORIES, item['id']


def test_katalog_adresleri_https():
    for item in TV_CATALOG:
        adres = item['store_url'] if _magaza_mi(item) else item['url']
        parsed = urlsplit(adres)
        assert parsed.scheme == 'https' and parsed.hostname, item['id']
        web = urlsplit(item['website'])
        assert web.scheme == 'https' and web.hostname, item['id']


def test_katalog_sha256_bicimi():
    for item in TV_CATALOG:
        sha = item.get('sha256')
        if sha is None:
            continue
        assert re.fullmatch(r'[0-9a-f]{64}', sha), item['id']


def test_katalog_paket_adlari_adb_dogrulamasindan_gecer():
    from mibox_app.adb_engine import is_valid_package

    for item in TV_CATALOG:
        assert is_valid_package(item['package']), item['id']
        for alt in item.get('alt_packages', []):
            assert is_valid_package(alt), '{}/{}'.format(item['id'], alt)


def test_get_catalog_filtreleri():
    assert get_catalog() == TV_CATALOG
    medya = get_catalog(category='Medya & Video')
    assert medya and all(x['category'] == 'Medya & Video' for x in medya)
    assert get_catalog(category='Tümü') == TV_CATALOG
    arama = get_catalog(search='smarttube')
    assert arama and all('smarttube' in x['name'].lower()
                         or 'smarttube' in x['description'].lower()
                         or 'smarttube' in x['package'].lower() for x in arama)


# --- download_apk ------------------------------------------------------------

class FakeHeaders:
    def __init__(self, values):
        self._values = {k.lower(): v for k, v in values.items()}

    def get(self, key, default=None):
        return self._values.get(key.lower(), default)


class FakeResponse:
    def __init__(self, body, final_url='https://example.com/app.apk',
                 content_length=None):
        self._body = body
        self._pos = 0
        self._final_url = final_url
        length = len(body) if content_length is None else content_length
        self.headers = FakeHeaders({'content-length': str(length)})

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def geturl(self):
        return self._final_url

    def read(self, n=-1):
        if n is None or n < 0:
            data = self._body[self._pos:]
            self._pos = len(self._body)
            return data
        data = self._body[self._pos:self._pos + n]
        self._pos += len(data)
        return data


def _apk_bytes(with_manifest=True):
    """Gercek ZIP govdesi; APK dogrulamasi AndroidManifest.xml arar."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        if with_manifest:
            zf.writestr('AndroidManifest.xml', b'\x03\x00\x08\x00manifest')
        zf.writestr('classes.dex', b'dex\n035\x00')
    return buf.getvalue()


def _item(**overrides):
    base = {'id': 'test_app', 'name': 'Test', 'url': 'https://example.com/app.apk'}
    base.update(overrides)
    return base


def _patch_urlopen(monkeypatch, response):
    calls = []

    def urlopen(req, timeout=None):
        calls.append(req)
        return response

    monkeypatch.setattr(urllib.request, 'urlopen', urlopen)
    return calls


def test_indirme_gecerli_zip_ile_basarili(tmp_path, monkeypatch):
    body = _apk_bytes()
    _patch_urlopen(monkeypatch, FakeResponse(body))

    result = download_apk(_item(), dest_dir=str(tmp_path))

    assert result.endswith('.apk')
    assert Path(result).read_bytes() == body
    assert not list(tmp_path.glob('*.part'))


def test_indirme_sha256_dogruysa_kabul_edilir(tmp_path, monkeypatch):
    body = _apk_bytes()
    sha = hashlib.sha256(body).hexdigest()
    _patch_urlopen(monkeypatch, FakeResponse(body))

    result = download_apk(_item(sha256=sha), dest_dir=str(tmp_path))

    assert Path(result).exists()


def test_indirme_sha256_uyusmazsa_reddedilir_ve_dosya_kalmaz(tmp_path, monkeypatch):
    body = _apk_bytes()
    _patch_urlopen(monkeypatch, FakeResponse(body))

    with pytest.raises(ValueError, match='SHA-256'):
        download_apk(_item(sha256='0' * 64), dest_dir=str(tmp_path))

    assert list(tmp_path.iterdir()) == []


def test_indirme_manifest_yoksa_reddedilir(tmp_path, monkeypatch):
    _patch_urlopen(monkeypatch, FakeResponse(_apk_bytes(with_manifest=False)))

    with pytest.raises(ValueError, match='AndroidManifest.xml'):
        download_apk(_item(), dest_dir=str(tmp_path))

    assert list(tmp_path.iterdir()) == []


def test_indirme_bos_manifest_reddedilir(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('AndroidManifest.xml', b'')
    _patch_urlopen(monkeypatch, FakeResponse(buf.getvalue()))

    with pytest.raises(ValueError, match='boş bir AndroidManifest.xml'):
        download_apk(_item(), dest_dir=str(tmp_path))

    assert list(tmp_path.iterdir()) == []


def test_indirme_zip_degilse_reddedilir(tmp_path, monkeypatch):
    _patch_urlopen(monkeypatch, FakeResponse(b'bu bir zip degil'))

    with pytest.raises(ValueError, match='ZIP'):
        download_apk(_item(), dest_dir=str(tmp_path))

    assert list(tmp_path.iterdir()) == []


def test_indirme_https_disi_adresi_reddeder(tmp_path, monkeypatch):
    calls = _patch_urlopen(monkeypatch, FakeResponse(_apk_bytes()))

    with pytest.raises(ValueError, match='HTTPS'):
        download_apk(_item(url='http://example.com/app.apk'), dest_dir=str(tmp_path))

    assert calls == [], 'guvensiz adres icin aga hic cikilmamali'


def test_indirme_https_disi_yonlendirmeyi_reddeder(tmp_path, monkeypatch):
    _patch_urlopen(monkeypatch, FakeResponse(
        _apk_bytes(), final_url='http://mirror.example.com/app.apk'))

    with pytest.raises(ValueError, match='güvenli bağlantıda kalmadı'):
        download_apk(_item(), dest_dir=str(tmp_path))

    assert list(tmp_path.iterdir()) == []


def test_indirme_eksik_govde_reddedilir(tmp_path, monkeypatch):
    body = _apk_bytes()
    _patch_urlopen(monkeypatch, FakeResponse(body, content_length=len(body) + 10))

    with pytest.raises(ValueError, match='eksik kaldı'):
        download_apk(_item(), dest_dir=str(tmp_path))

    assert list(tmp_path.iterdir()) == []


def test_indirme_asiri_buyuk_bildirimi_reddedilir(tmp_path, monkeypatch):
    _patch_urlopen(monkeypatch, FakeResponse(
        _apk_bytes(), content_length=512 * 1024 * 1024 + 1))

    with pytest.raises(ValueError, match='boyut sınırını'):
        download_apk(_item(), dest_dir=str(tmp_path))

    assert list(tmp_path.iterdir()) == []


class SismikBayt(bytes):
    """len() gercek boyuttan bagimsiz olarak 512 MB sinirini asar."""

    def __len__(self):
        return 512 * 1024 * 1024 + 1


def test_indirme_akis_siniri_asarsa_reddedilir(tmp_path, monkeypatch):
    class SismikCevap(FakeResponse):
        def read(self, n=-1):
            return SismikBayt(b'x')

    _patch_urlopen(monkeypatch, SismikCevap(_apk_bytes()))

    with pytest.raises(ValueError, match='boyut sınırını'):
        download_apk(_item(), dest_dir=str(tmp_path))

    assert list(tmp_path.iterdir()) == []


def test_indirme_ilerleme_bildirir(tmp_path, monkeypatch):
    body = _apk_bytes()
    _patch_urlopen(monkeypatch, FakeResponse(body))
    events = []

    result = download_apk(_item(), dest_dir=str(tmp_path),
                          progress_cb=lambda done, total: events.append((done, total)))

    assert events, 'ilerleme geri cagrisi hic cagrilmadi'
    assert events[-1] == (len(body), len(body))
    assert Path(result).exists()


def test_indirme_iptal_edilirse_aga_cikilmaz(tmp_path, monkeypatch):
    calls = _patch_urlopen(monkeypatch, FakeResponse(_apk_bytes()))

    def iptal():
        raise RuntimeError('kullanıcı iptal etti')

    with pytest.raises(RuntimeError):
        download_apk(_item(), dest_dir=str(tmp_path), check_cancel=iptal)

    assert calls == []
    assert list(tmp_path.iterdir()) == []


def _iptal_sayaci(patlama):
    """n. cagrida hata atan bir check_cancel geri cagrisi uretir."""
    sayac = {'n': 0}

    def iptal():
        sayac['n'] += 1
        if sayac['n'] == patlama:
            raise RuntimeError('kullanıcı iptal etti')

    return sayac, iptal


def test_indirme_acilis_sonrasi_iptal_reddedilir(tmp_path, monkeypatch):
    _patch_urlopen(monkeypatch, FakeResponse(_apk_bytes()))
    sayac, iptal = _iptal_sayaci(2)

    with pytest.raises(RuntimeError):
        download_apk(_item(), dest_dir=str(tmp_path), check_cancel=iptal)

    assert sayac['n'] == 2
    assert list(tmp_path.iterdir()) == []


def test_indirme_okuma_dongusunda_iptal_reddedilir(tmp_path, monkeypatch):
    _patch_urlopen(monkeypatch, FakeResponse(_apk_bytes()))
    sayac, iptal = _iptal_sayaci(3)

    with pytest.raises(RuntimeError):
        download_apk(_item(), dest_dir=str(tmp_path), check_cancel=iptal)

    assert sayac['n'] == 3
    assert list(tmp_path.iterdir()) == []


def test_indirme_dogrulama_oncesi_iptal_reddedilir(tmp_path, monkeypatch):
    _patch_urlopen(monkeypatch, FakeResponse(_apk_bytes()))
    sayac, iptal = _iptal_sayaci(5)

    with pytest.raises(RuntimeError):
        download_apk(_item(), dest_dir=str(tmp_path), check_cancel=iptal)

    assert sayac['n'] == 5
    assert list(tmp_path.iterdir()) == []


def test_indirme_degistirme_oncesi_iptal_reddedilir(tmp_path, monkeypatch):
    _patch_urlopen(monkeypatch, FakeResponse(_apk_bytes()))
    sayac, iptal = _iptal_sayaci(6)

    with pytest.raises(RuntimeError):
        download_apk(_item(), dest_dir=str(tmp_path), check_cancel=iptal)

    assert sayac['n'] == 6
    assert list(tmp_path.iterdir()) == []


def test_magaza_kaydi_indirilmez(tmp_path, monkeypatch):
    calls = _patch_urlopen(monkeypatch, FakeResponse(_apk_bytes()))
    item = {'id': 'magaza', 'name': 'X', 'type': 'store',
            'store_url': 'https://play.google.com/store/apps/details?id=com.a.a'}

    with pytest.raises(ValueError, match='mağaza kaydı'):
        download_apk(item, dest_dir=str(tmp_path))

    assert calls == [], 'mağaza kaydı için ağa çıkılmamalı'
    assert list(tmp_path.iterdir()) == []


def test_indirme_temizlik_hatasi_yutulur(tmp_path, monkeypatch):
    _patch_urlopen(monkeypatch, FakeResponse(_apk_bytes()))

    def patlak_remove(path):
        raise OSError('silinemez')

    monkeypatch.setattr(os, 'remove', patlak_remove)

    with pytest.raises(ValueError, match='SHA-256'):
        download_apk(_item(sha256='0' * 64), dest_dir=str(tmp_path))

    assert list(tmp_path.glob('*.part')) != []
