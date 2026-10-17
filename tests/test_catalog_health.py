# -*- coding: utf-8 -*-
"""Katalog saglik kontrolu testleri (ag erisimi yok: urlopen taklit edilir)."""
import hashlib
import io
import urllib.error
import urllib.request

import pytest

from mibox_app import catalog_health
from mibox_app.catalog_health import check_catalog, check_entry, main, update_hash

APK_URL = 'https://example.com/app.apk'


class FakeHeaders:
    def __init__(self, values):
        self._values = {k.lower(): v for k, v in values.items()}

    def get(self, key, default=None):
        return self._values.get(key.lower(), default)


class FakeResponse:
    def __init__(self, status=200, body=b'', final_url=APK_URL,
                 content_length=None):
        self.status = status
        self._body = body
        self._pos = 0
        self._final_url = final_url
        headers = {}
        if content_length is not None:
            headers['content-length'] = str(content_length)
        self.headers = FakeHeaders(headers)

    def getcode(self):
        return self.status

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

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code, reason='hata'):
    return urllib.error.HTTPError(APK_URL, code, reason, None, None)


def _patch(monkeypatch, handler):
    calls = []

    def urlopen(req, timeout=None):
        calls.append(req)
        result = handler(req)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(urllib.request, 'urlopen', urlopen)
    return calls


def _item(**overrides):
    base = {'id': 'test_app', 'url': APK_URL}
    base.update(overrides)
    return base


# --- check_entry ------------------------------------------------------------

def test_erisilebilir_kayit_saglikli(monkeypatch):
    calls = _patch(monkeypatch, lambda req: FakeResponse(
        status=200, content_length=1234))

    ok, detail = check_entry(_item())

    assert ok
    assert 'HTTP 200' in detail
    assert len(calls) == 1
    assert calls[0].get_method() == 'HEAD'


def test_head_reddedilirse_range_ile_yeniden_denenir(monkeypatch):
    def handler(req):
        if req.get_method() == 'HEAD':
            return _http_error(403, 'Forbidden')
        return FakeResponse(status=206, body=b'x')

    calls = _patch(monkeypatch, handler)

    ok, detail = check_entry(_item())

    assert ok
    assert 'Range' in detail
    assert len(calls) == 2
    assert calls[1].get_header('Range') == 'bytes=0-0'


def test_bozuk_content_length_yok_sayilir(monkeypatch):
    _patch(monkeypatch, lambda req: FakeResponse(status=200,
                                                 content_length='abc'))

    ok, detail = check_entry(_item())

    assert ok
    assert 'HTTP 200' in detail


def test_head_ve_range_reddedilirse_hata(monkeypatch):
    calls = _patch(monkeypatch,
                   lambda req: _http_error(405, 'Method Not Allowed'))

    ok, detail = check_entry(_item())

    assert not ok
    assert '403/405/501' in detail
    assert len(calls) == 2


@pytest.mark.parametrize('code', [404, 410, 500])
def test_http_durum_kodu_hata_bildirir(monkeypatch, code):
    _patch(monkeypatch, lambda req: _http_error(code))

    ok, detail = check_entry(_item())

    assert not ok
    assert detail == 'HTTP {}'.format(code)


def test_ag_hatasi_hata_bildirir(monkeypatch):
    _patch(monkeypatch, lambda req: urllib.error.URLError('baglanti yok'))

    ok, detail = check_entry(_item())

    assert not ok
    assert 'baglanti yok' in detail


def test_https_disi_yonlendirme_reddedilir(monkeypatch):
    _patch(monkeypatch, lambda req: FakeResponse(
        status=200, final_url='http://mirror.example.com/app.apk'))

    ok, detail = check_entry(_item())

    assert not ok
    assert 'güvenli' in detail


def test_http_adresli_kayit_aga_cikmadan_reddedilir(monkeypatch):
    calls = _patch(monkeypatch, lambda req: FakeResponse())

    ok, detail = check_entry(_item(url='http://example.com/app.apk'))

    assert not ok
    assert 'HTTPS' in detail
    assert calls == []


def test_magaza_kaydi_store_url_ile_denetlenir(monkeypatch):
    calls = _patch(monkeypatch, lambda req: FakeResponse(
        status=200, content_length=10))
    item = {'id': 'sftv', 'type': 'store',
            'store_url': 'https://play.google.com/store/apps/details?id=com.a.a'}

    ok, detail = check_entry(item)

    assert ok
    assert 'mağaza kaydı' in detail
    assert len(calls) == 1
    assert calls[0].full_url.startswith('https://play.google.com/')


def test_magaza_kaydi_ozet_dogrulamasi_yapmaz(monkeypatch):
    calls = _patch(monkeypatch, lambda req: FakeResponse(
        status=200, content_length=10))
    item = {'id': 'sftv', 'type': 'store',
            'store_url': 'https://play.google.com/store/apps/details?id=com.a.a',
            'sha256': '0' * 64}

    ok, detail = check_entry(item, verify_hash=True)

    assert ok
    assert len(calls) == 1, 'mağaza kaydı için indirme yapılmamalı'


def test_magaza_kaydi_https_disi_adresle_reddedilir(monkeypatch):
    calls = _patch(monkeypatch, lambda req: FakeResponse())
    item = {'id': 'sftv', 'type': 'store',
            'store_url': 'http://play.google.com/store/apps/details?id=com.a.a'}

    ok, detail = check_entry(item)

    assert not ok
    assert 'HTTPS' in detail
    assert calls == []


def test_sha256_dogrulanir(monkeypatch):
    body = b'apk-icerigi'
    sha = hashlib.sha256(body).hexdigest()

    def handler(req):
        if req.get_method() == 'HEAD':
            return FakeResponse(status=200, content_length=len(body))
        return FakeResponse(status=200, body=body)

    calls = _patch(monkeypatch, handler)

    ok, detail = check_entry(_item(sha256=sha), verify_hash=True)

    assert ok, detail
    assert 'sha256 doğrulandı' in detail
    assert len(calls) == 2
    assert calls[1].get_method() == 'GET'


def test_sha256_uyusmazsa_hata(monkeypatch):
    body = b'apk-icerigi'

    def handler(req):
        if req.get_method() == 'HEAD':
            return FakeResponse(status=200, content_length=len(body))
        return FakeResponse(status=200, body=body)

    _patch(monkeypatch, handler)

    ok, detail = check_entry(_item(sha256='0' * 64), verify_hash=True)

    assert not ok
    assert 'uyuşmuyor' in detail


def test_verify_hash_kapaliyken_indirilmez(monkeypatch):
    calls = _patch(monkeypatch, lambda req: FakeResponse(
        status=200, content_length=10))

    ok, detail = check_entry(_item(sha256='0' * 64))

    assert ok
    assert 'sınanmadı' in detail
    assert len(calls) == 1, 'özet sınanmadan indirme yapılmamalı'


def test_boyut_siniri_asilirsa_hata(monkeypatch):
    _patch(monkeypatch, lambda req: FakeResponse(
        status=200, content_length=512 * 1024 * 1024 + 1))

    ok, detail = check_entry(_item())

    assert not ok
    assert 'boyut sınırı' in detail


class SismikBayt(bytes):
    """len() gercek boyuttan bagimsiz olarak 512 MB sinirini asar."""

    def __len__(self):
        return 512 * 1024 * 1024 + 1


def test_ozet_indirmesi_boyut_sinirinda_hata(monkeypatch):
    class SismikCevap(FakeResponse):
        def read(self, n=-1):
            return SismikBayt(b'x')

    _patch(monkeypatch, lambda req: SismikCevap(status=200))

    with pytest.raises(ValueError):
        catalog_health._download_digest(APK_URL)


def test_ozet_indirmesi_hatasinda_reddedilir(monkeypatch):
    def handler(req):
        if req.get_method() == 'HEAD':
            return FakeResponse(status=200, content_length=10)
        return urllib.error.URLError('indirme koptu')

    _patch(monkeypatch, handler)

    ok, detail = check_entry(_item(sha256='0' * 64), verify_hash=True)

    assert not ok
    assert 'indirme başarısız' in detail


# --- check_catalog / main ----------------------------------------------------

def test_check_catalog_tum_kayitlari_raporlar(monkeypatch):
    def handler(req):
        if 'kirik' in req.full_url:
            return _http_error(404)
        return FakeResponse(status=200, content_length=10)

    _patch(monkeypatch, handler)
    entries = [
        _item(id='saglam', url=APK_URL),
        _item(id='kirik', url='https://example.com/kirik.apk'),
    ]

    results = check_catalog(entries=entries)

    assert [r[0] for r in results] == ['saglam', 'kirik']
    assert results[0][1] is True
    assert results[1][1] is False
    assert results[1][2] == 'HTTP 404'


def test_main_basariyla_0_doner(monkeypatch):
    monkeypatch.setattr(catalog_health, 'check_catalog',
                        lambda verify_hash=False: [('a', True, 'HTTP 200')])
    stream = io.StringIO()

    code = main(argv=['mibox.py', '--check-catalog'], stream=stream)

    assert code == 0
    text = stream.getvalue()
    assert 'TAMAM' in text and 'a' in text
    assert '1/1 kayıt sağlıklı' in text
    assert 'HATA' not in text


def test_main_hatada_1_doner(monkeypatch):
    monkeypatch.setattr(catalog_health, 'check_catalog',
                        lambda verify_hash=False: [
                            ('a', True, 'HTTP 200'),
                            ('b', False, 'HTTP 404'),
                        ])
    stream = io.StringIO()

    code = main(argv=['mibox.py', '--check-catalog', '--verify-hash'],
                stream=stream)

    assert code == 1
    text = stream.getvalue()
    assert 'HATA' in text and 'b' in text
    assert '1/2 kayıt sağlıklı (--verify-hash)' in text


# --- update_hash -------------------------------------------------------------

def test_update_hash_ozet_hesaplar(monkeypatch):
    body = b'apk-yeni'
    sha = hashlib.sha256(body).hexdigest()
    _patch(monkeypatch, lambda req: FakeResponse(status=200, body=body))

    ok, detail, snippet = update_hash('test_app', entries=[_item()])

    assert ok
    assert 'özet yok' in detail
    assert snippet == "'sha256': '{}',".format(sha)


def test_update_hash_degisimi_bildirir(monkeypatch):
    body = b'apk-yeni'
    sha = hashlib.sha256(body).hexdigest()
    _patch(monkeypatch, lambda req: FakeResponse(status=200, body=body))

    ok, detail, _snippet = update_hash(
        'test_app', entries=[_item(sha256='0' * 64)])

    assert ok
    assert 'DEĞİŞTİ' in detail
    assert sha in detail and '0' * 64 in detail


def test_update_hash_degismediyse_bildirir(monkeypatch):
    body = b'apk-ayni'
    sha = hashlib.sha256(body).hexdigest()
    _patch(monkeypatch, lambda req: FakeResponse(status=200, body=body))

    ok, detail, _snippet = update_hash('test_app', entries=[_item(sha256=sha)])

    assert ok
    assert 'değişmedi' in detail


def test_update_hash_bilinmeyen_kayit(monkeypatch):
    calls = _patch(monkeypatch, lambda req: FakeResponse())

    ok, detail, snippet = update_hash('yok', entries=[_item()])

    assert not ok and snippet is None
    assert 'bulunamadı' in detail
    assert calls == []


def test_update_hash_https_disi_adresi_reddeder(monkeypatch):
    calls = _patch(monkeypatch, lambda req: FakeResponse())

    ok, detail, snippet = update_hash(
        'test_app', entries=[_item(url='http://example.com/x.apk')])

    assert not ok and snippet is None
    assert 'HTTPS' in detail
    assert calls == []


def test_update_hash_magaza_kaydini_reddeder(monkeypatch):
    calls = _patch(monkeypatch, lambda req: FakeResponse())
    item = {'id': 'sftv', 'type': 'store',
            'store_url': 'https://play.google.com/store/apps/details?id=com.a.a'}

    ok, detail, snippet = update_hash('sftv', entries=[item])

    assert not ok and snippet is None
    assert 'mağaza kaydı' in detail
    assert calls == []


def test_update_hash_indirme_hatasi(monkeypatch):
    _patch(monkeypatch, lambda req: urllib.error.URLError('baglanti yok'))

    ok, detail, snippet = update_hash('test_app', entries=[_item()])

    assert not ok and snippet is None
    assert 'indirme başarısız' in detail


# --- main: --update-hash -----------------------------------------------------

def test_main_update_hash_yonlendirir(monkeypatch):
    monkeypatch.setattr(
        catalog_health, 'update_hash',
        lambda item_id: (True, 'özet değişmedi', "'sha256': 'abc',"))
    stream = io.StringIO()

    code = main(argv=['mibox.py', '--update-hash', 'projectivy_launcher'],
                stream=stream)

    assert code == 0
    text = stream.getvalue()
    assert 'TAMAM' in text and "'sha256': 'abc'," in text


def test_main_update_hash_kimlik_ister():
    stream = io.StringIO()

    code = main(argv=['mibox.py', '--update-hash'], stream=stream)

    assert code == 2
    assert 'Kullanım' in stream.getvalue()


def test_main_update_hash_bayrakla_karismaz():
    stream = io.StringIO()

    code = main(argv=['mibox.py', '--update-hash', '--verify-hash'], stream=stream)

    assert code == 2
    assert 'Kullanım' in stream.getvalue()


def test_main_update_hash_hatada_1_doner(monkeypatch):
    monkeypatch.setattr(catalog_health, 'update_hash',
                        lambda item_id: (False, 'kayıt bulunamadı: x', None))
    stream = io.StringIO()

    code = main(argv=['mibox.py', '--update-hash', 'x'], stream=stream)

    assert code == 1
    assert 'HATA' in stream.getvalue()
