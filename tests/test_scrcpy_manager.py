# -*- coding: utf-8 -*-
"""Scrcpy yoneticisi testleri: indirme dogrulama, kurulum, baslatma, log maskeleme.

Gercek indirme, gercek surec ve gercek ag YOKTUR: urlopen, Popen ve thread
taklit edilir; dosya islemleri gecici klasorde kosar.
"""
import hashlib
import io
import os
import re
import stat
import subprocess
import tempfile
import zipfile
from types import SimpleNamespace

import pytest

from mibox_app import scrcpy_manager

IYI_URL = ('https://github.com/Genymobile/scrcpy/releases/download/'
           'v9.9.9/scrcpy-win64-v9.9.9.zip')


def _run(worker):
    box = {'ok': None, 'fail': None}
    logs = []
    progress = []
    worker.finished_ok.connect(lambda r: box.__setitem__('ok', r))
    worker.failed.connect(lambda e: box.__setitem__('fail', e))
    worker.log.connect(logs.append)
    worker.progress.connect(lambda i, t: progress.append((i, t)))
    worker.run()
    return box['ok'], box['fail'], logs, progress


def _zip_ekle(zf, ad, veri):
    """Duz dosya icin gecerli tur bitleriyle zip uyesi yazar."""
    info = zipfile.ZipInfo(ad)
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    zf.writestr(info, veri)


def _scrcpy_zip(exe=b'taklit-scrcpy', klasor='scrcpy-v9.9.9', ekler=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        _zip_ekle(zf, klasor + '/scrcpy.exe', exe)
        _zip_ekle(zf, klasor + '/lib/SDL2.dll', b'dll')
        for ad, veri in ekler:
            _zip_ekle(zf, ad, veri)
    return buf.getvalue()


def _info(payload, url=IYI_URL):
    return {
        'version': 'v9.9.9',
        'url': url,
        'size': len(payload),
        'sha256': hashlib.sha256(payload).hexdigest(),
        'filename': 'scrcpy-win64-v9.9.9.zip',
    }


class FakeResponse:
    """urlopen taklidi: baytlari parca parca dondurur."""

    def __init__(self, payload, url, headers=None, on_read=None):
        self.payload = payload
        self.pos = 0
        self._url = url
        self.headers = dict(headers or {})
        self.on_read = on_read

    def geturl(self):
        return self._url

    def read(self, n=-1):
        if self.on_read is not None:
            self.on_read()
        chunk = self.payload[self.pos:self.pos + n]
        self.pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


@pytest.fixture
def scrcpy_env(monkeypatch, tmp_path):
    """BASE_DIR/LOG_DIR ve gecici dosyalar tmp_path icinde kalsin."""
    kok = tmp_path / 'kok'
    kok.mkdir()
    monkeypatch.setattr(scrcpy_manager, 'BASE_DIR', str(kok))
    monkeypatch.setattr(scrcpy_manager, 'LOG_DIR', str(tmp_path / 'log'))

    class TempShim:
        @staticmethod
        def mkstemp(prefix='', suffix='', dir=None):
            return tempfile.mkstemp(prefix=prefix, suffix=suffix,
                                    dir=str(tmp_path))

        @staticmethod
        def mkdtemp(prefix='', suffix='', dir=None):
            return tempfile.mkdtemp(prefix=prefix, suffix=suffix,
                                    dir=str(tmp_path))

    monkeypatch.setattr(scrcpy_manager, 'tempfile', TempShim)
    return tmp_path


@pytest.fixture
def sahte_binary(monkeypatch):
    """Gecerli sahte scrcpy.exe icerigi: dogrulama GERCEK SHA-256 ile kosar."""
    icerik = b'gercek-scrcpy-ikilisi'
    monkeypatch.setattr(
        scrcpy_manager, 'SCRCPY_BINARY_SHA256',
        {scrcpy_manager.get_scrcpy_arch_prefix():
         hashlib.sha256(icerik).hexdigest()})
    return icerik


# --- _verify_scrcpy_executable -----------------------------------------------

def test_verify_scrcpy_bilinmeyen_onek_reddedilir(tmp_path, monkeypatch):
    monkeypatch.setattr(scrcpy_manager, 'SCRCPY_BINARY_SHA256', {})
    assert scrcpy_manager._verify_scrcpy_executable(
        str(tmp_path / 'yok.exe')) is False


def test_verify_scrcpy_acilamayan_yol_reddedilir(tmp_path):
    # Klasor yolu open() icinde OSError uretir; dogrulama False donmeli.
    assert scrcpy_manager._verify_scrcpy_executable(str(tmp_path)) is False


# --- Mimari / indirme bilgisi ------------------------------------------------

@pytest.mark.parametrize('machine, beklenen', [
    ('AMD64', 'scrcpy-win64'),
    ('x86', 'scrcpy-win32'),
    ('ARM64', 'scrcpy-winarm64'),
    ('aarch64', 'scrcpy-winarm64'),
])
def test_scrcpy_mimari_oneki(monkeypatch, machine, beklenen):
    monkeypatch.setattr(scrcpy_manager.platform, 'machine', lambda: machine)
    if beklenen == 'scrcpy-win32':
        monkeypatch.setattr(scrcpy_manager.sys, 'maxsize', 2 ** 31)
    else:
        monkeypatch.setattr(scrcpy_manager.sys, 'maxsize', 2 ** 63)
    assert scrcpy_manager.get_scrcpy_arch_prefix() == beklenen


def test_scrcpy_indirme_bilgisi(monkeypatch):
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_arch_prefix',
                        lambda: 'scrcpy-win32')
    info = scrcpy_manager.get_scrcpy_download_info()

    assert info['version'] == scrcpy_manager.SCRCPY_DEFAULT_VERSION
    assert info['url'].startswith(
        'https://github.com/Genymobile/scrcpy/releases/download/')
    assert info['url'].endswith('/scrcpy-win32-v5.0.1.zip')
    assert info['filename'] == 'scrcpy-win32-v5.0.1.zip'
    assert 0 < info['size'] <= 64 * 1024 * 1024
    assert re.fullmatch(r'[a-f0-9]{64}', info['sha256'])


# --- find_scrcpy / tercih isaretcisi ----------------------------------------

def _yaz_exe(path, icerik):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(icerik)
    return path


def test_find_scrcpy_standart_dizin(tmp_path, sahte_binary):
    exe = _yaz_exe(tmp_path / 'scrcpy' / 'scrcpy.exe', sahte_binary)
    sonuc = scrcpy_manager.find_scrcpy(str(tmp_path))
    assert os.path.normcase(sonuc) == os.path.normcase(str(exe))


def test_find_scrcpy_dogrudan_exe(tmp_path, sahte_binary):
    exe = _yaz_exe(tmp_path / 'scrcpy.exe', sahte_binary)
    sonuc = scrcpy_manager.find_scrcpy(str(tmp_path))
    assert os.path.normcase(sonuc) == os.path.normcase(str(exe))


def test_find_scrcpy_scrcpy_klasoru(tmp_path, sahte_binary):
    exe = _yaz_exe(tmp_path / 'scrcpy-9.9' / 'scrcpy.exe', sahte_binary)
    sonuc = scrcpy_manager.find_scrcpy(str(tmp_path))
    assert os.path.normcase(sonuc) == os.path.normcase(str(exe))


def test_find_scrcpy_dogrulanmayan_reddedilir(tmp_path, sahte_binary,
                                              monkeypatch):
    _yaz_exe(tmp_path / 'scrcpy' / 'scrcpy.exe', b'kurcalanmis-dosya')
    monkeypatch.setattr(scrcpy_manager.shutil, 'which', lambda name: None)
    assert scrcpy_manager.find_scrcpy(str(tmp_path)) is None


def test_find_scrcpy_path_fallback(tmp_path, sahte_binary, monkeypatch):
    exe = _yaz_exe(tmp_path / 'baska' / 'scrcpy.exe', sahte_binary)
    monkeypatch.setattr(
        scrcpy_manager.shutil, 'which',
        lambda name: str(exe) if name in ('scrcpy', 'scrcpy.exe') else None)
    bos = tmp_path / 'bos'
    bos.mkdir()
    sonuc = scrcpy_manager.find_scrcpy(str(bos))
    assert os.path.normcase(sonuc) == os.path.normcase(str(exe))


def test_find_scrcpy_tercih_isaretcisi_onceliklidir(tmp_path, sahte_binary):
    _yaz_exe(tmp_path / 'scrcpy' / 'scrcpy.exe', sahte_binary)
    oncelikli = _yaz_exe(tmp_path / 'scrcpy-9.9.9' / 'scrcpy.exe',
                         sahte_binary)
    (tmp_path / '.scrcpy-preferred').write_text('scrcpy-9.9.9\n',
                                                encoding='utf-8')

    sonuc = scrcpy_manager.find_scrcpy(str(tmp_path))
    assert os.path.normcase(sonuc) == os.path.normcase(str(oncelikli))


def test_find_scrcpy_bozuk_tercih_isaretcisi_yok_sayilir(tmp_path,
                                                         sahte_binary):
    standart = _yaz_exe(tmp_path / 'scrcpy' / 'scrcpy.exe', sahte_binary)
    _yaz_exe(tmp_path / 'scrcpy-9.9.9' / 'scrcpy.exe', sahte_binary)
    (tmp_path / '.scrcpy-preferred').write_text('../kacis\n',
                                                encoding='utf-8')

    sonuc = scrcpy_manager.find_scrcpy(str(tmp_path))
    assert os.path.normcase(sonuc) == os.path.normcase(str(standart))


def test_find_scrcpy_listdir_hatasi_yok_sayilir(tmp_path, monkeypatch):
    monkeypatch.setattr(scrcpy_manager.shutil, 'which', lambda name: None)
    gercek_listdir = os.listdir

    def patlak_listdir(path):
        if os.path.normcase(str(path)) == os.path.normcase(str(tmp_path)):
            raise OSError('okunamaz')
        return gercek_listdir(path)

    monkeypatch.setattr(scrcpy_manager.os, 'listdir', patlak_listdir)

    assert scrcpy_manager.find_scrcpy(str(tmp_path)) is None


def test_remember_scrcpy_install_ve_bulma(tmp_path, sahte_binary, monkeypatch):
    monkeypatch.setattr(scrcpy_manager, 'BASE_DIR', str(tmp_path))
    kurulum = _yaz_exe(tmp_path / 'scrcpy-v9' / 'scrcpy.exe', sahte_binary)

    scrcpy_manager._remember_scrcpy_install(str(kurulum.parent))

    isaret = (tmp_path / '.scrcpy-preferred').read_text(encoding='utf-8')
    assert isaret.strip() == 'scrcpy-v9'
    sonuc = scrcpy_manager.find_scrcpy(str(tmp_path))
    assert os.path.normcase(sonuc) == os.path.normcase(str(kurulum))
    assert not list(tmp_path.glob('.scrcpy-preferred-*'))


def test_remember_scrcpy_install_gecersiz_yol(tmp_path, monkeypatch):
    kok = tmp_path / 'kok'
    kok.mkdir()
    monkeypatch.setattr(scrcpy_manager, 'BASE_DIR', str(kok))

    with pytest.raises(RuntimeError):
        scrcpy_manager._remember_scrcpy_install(str(tmp_path / 'disarida'))
    with pytest.raises(RuntimeError):
        scrcpy_manager._remember_scrcpy_install(str(kok / 'bosluk lu'))


def test_remember_scrcpy_install_replace_hatasi_temizler(tmp_path, monkeypatch):
    monkeypatch.setattr(scrcpy_manager, 'BASE_DIR', str(tmp_path))
    hedef = tmp_path / 'scrcpy-v9'

    def patlak_replace(src, dst):
        raise OSError('yerine konulamadi')

    monkeypatch.setattr(scrcpy_manager.os, 'replace', patlak_replace)

    with pytest.raises(OSError):
        scrcpy_manager._remember_scrcpy_install(str(hedef))
    assert not list(tmp_path.glob('.scrcpy-preferred-*'))


# --- ScrcpyDownloader --------------------------------------------------------

def test_scrcpy_cache_hit_ag_kullanmaz(scrcpy_env, monkeypatch):
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_download_info',
                        lambda: _info(b'x'))
    monkeypatch.setattr(scrcpy_manager, '_verify_scrcpy_executable',
                        lambda p: True)
    hedef = scrcpy_env / 'kurulu'
    hedef.mkdir()
    (hedef / 'scrcpy.exe').write_bytes(b'x')

    worker = scrcpy_manager.ScrcpyDownloader(target_dir=str(hedef))
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['scrcpy_path'] == str(hedef / 'scrcpy.exe')
    assert ok['version'] == 'v9.9.9'
    assert ok['target_dir'] == str(hedef)


@pytest.mark.parametrize('mutasyon, beklenen', [
    (lambda i: i.update(url='http://evil.example/x.zip'),
     'indirme adresi doğrulanamadı'),
    (lambda i: i.update(url='https://github.com/other/repo/x.zip'),
     'indirme adresi doğrulanamadı'),
    (lambda i: i.update(size=0), 'boyutu beklenen sınırın dışında'),
    (lambda i: i.update(size=65 * 1024 * 1024),
     'boyutu beklenen sınırın dışında'),
    (lambda i: i.update(sha256='abc'), 'güvenilir SHA-256 özeti bulunamadı'),
])
def test_scrcpy_indirme_bilgisi_dogrulanir(scrcpy_env, monkeypatch,
                                           mutasyon, beklenen):
    info = _info(b'x')
    mutasyon(info)
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_download_info',
                        lambda: info)

    worker = scrcpy_manager.ScrcpyDownloader(
        target_dir=str(scrcpy_env / 'hedef'))
    ok, fail, logs, progress = _run(worker)

    assert ok is None
    assert beklenen in fail


def test_scrcpy_indirme_basarili(scrcpy_env, monkeypatch):
    payload = _scrcpy_zip(exe=b'gercek-exe')
    info = _info(payload)
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_download_info',
                        lambda: info)
    monkeypatch.setattr(
        scrcpy_manager, 'SCRCPY_BINARY_SHA256',
        {scrcpy_manager.get_scrcpy_arch_prefix():
         hashlib.sha256(b'gercek-exe').hexdigest()})
    response = FakeResponse(payload, url=info['url'],
                            headers={'Content-Length': str(len(payload))})
    monkeypatch.setattr('urllib.request.urlopen',
                        lambda req, timeout=None: response)

    hedef = scrcpy_env / 'kok' / 'scrcpy-v9.9.9'
    worker = scrcpy_manager.ScrcpyDownloader()
    statuses = []
    worker.status_text.connect(statuses.append)
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert os.path.normcase(ok['scrcpy_path']) == \
        os.path.normcase(str(hedef / 'scrcpy.exe'))
    assert (hedef / 'scrcpy.exe').read_bytes() == b'gercek-exe'
    assert (hedef / 'lib' / 'SDL2.dll').read_bytes() == b'dll'
    assert any('başarıyla kuruldu' in line for line in logs)
    assert progress[-1] == (len(payload), len(payload))
    assert statuses[-1] == 'Arşiv klasöre çıkartılıyor...'
    # varsayilan hedef isaretlenir ve find_scrcpy ayni dosyayi bulur
    isaret = (scrcpy_env / 'kok' / '.scrcpy-preferred').read_text(
        encoding='utf-8')
    assert isaret.strip() == 'scrcpy-v9.9.9'
    sonuc = scrcpy_manager.find_scrcpy(str(scrcpy_env / 'kok'))
    assert os.path.normcase(sonuc) == \
        os.path.normcase(str(hedef / 'scrcpy.exe'))
    # gecici dosyalar temizlendi
    assert list(scrcpy_env.glob('mibox-scrcpy-*')) == []
    assert list(scrcpy_env.glob('.mibox-scrcpy-*')) == []


def test_scrcpy_force_download_yeni_dizin(scrcpy_env, monkeypatch):
    payload = _scrcpy_zip(exe=b'exe-force')
    info = _info(payload)
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_download_info',
                        lambda: info)
    monkeypatch.setattr(
        scrcpy_manager, 'SCRCPY_BINARY_SHA256',
        {scrcpy_manager.get_scrcpy_arch_prefix():
         hashlib.sha256(b'exe-force').hexdigest()})
    response = FakeResponse(payload, url=info['url'],
                            headers={'Content-Length': str(len(payload))})
    monkeypatch.setattr('urllib.request.urlopen',
                        lambda req, timeout=None: response)

    hedef = scrcpy_env / 'kurulu'
    hedef.mkdir()
    (hedef / 'scrcpy.exe').write_bytes(b'eski-kurulum')
    worker = scrcpy_manager.ScrcpyDownloader(target_dir=str(hedef),
                                             force_download=True)
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['target_dir'].startswith(str(hedef) + '-')
    assert (hedef / 'scrcpy.exe').read_bytes() == b'eski-kurulum'
    assert not (scrcpy_env / 'kok' / '.scrcpy-preferred').exists()


def test_scrcpy_sha_uyusmazligi(scrcpy_env, monkeypatch):
    payload = _scrcpy_zip()
    info = _info(payload)
    info['sha256'] = 'f' * 64
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_download_info',
                        lambda: info)
    response = FakeResponse(payload, url=info['url'],
                            headers={'Content-Length': str(len(payload))})
    monkeypatch.setattr('urllib.request.urlopen',
                        lambda req, timeout=None: response)

    hedef = scrcpy_env / 'hedef'
    worker = scrcpy_manager.ScrcpyDownloader(target_dir=str(hedef))
    ok, fail, logs, progress = _run(worker)

    assert 'SHA-256 doğrulaması başarısız' in fail
    assert not hedef.exists()
    assert list(scrcpy_env.glob('mibox-scrcpy-*')) == []


def test_scrcpy_eksik_indirme_reddedilir(scrcpy_env, monkeypatch):
    payload = _scrcpy_zip()
    info = _info(payload)
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_download_info',
                        lambda: info)
    response = FakeResponse(payload, url=info['url'],
                            headers={'Content-Length': str(len(payload) + 10)})
    monkeypatch.setattr('urllib.request.urlopen',
                        lambda req, timeout=None: response)

    worker = scrcpy_manager.ScrcpyDownloader(
        target_dir=str(scrcpy_env / 'hedef'))
    ok, fail, logs, progress = _run(worker)

    assert 'eksik veya bozuk' in fail
    assert list(scrcpy_env.glob('mibox-scrcpy-*')) == []


def test_scrcpy_supheli_yonlendirme_reddedilir(scrcpy_env, monkeypatch):
    payload = _scrcpy_zip()
    info = _info(payload)
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_download_info',
                        lambda: info)
    response = FakeResponse(payload, url='https://evil.example/x.zip',
                            headers={'Content-Length': str(len(payload))})
    monkeypatch.setattr('urllib.request.urlopen',
                        lambda req, timeout=None: response)

    worker = scrcpy_manager.ScrcpyDownloader(
        target_dir=str(scrcpy_env / 'hedef'))
    ok, fail, logs, progress = _run(worker)

    assert 'indirme kaynağı doğrulanamadı' in fail


def test_scrcpy_guvensiz_arsiv_yolu_reddedilir(scrcpy_env, monkeypatch):
    payload = _scrcpy_zip(ekler=[('../kacis.exe', b'x')])
    info = _info(payload)
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_download_info',
                        lambda: info)
    response = FakeResponse(payload, url=info['url'],
                            headers={'Content-Length': str(len(payload))})
    monkeypatch.setattr('urllib.request.urlopen',
                        lambda req, timeout=None: response)

    worker = scrcpy_manager.ScrcpyDownloader(
        target_dir=str(scrcpy_env / 'hedef'))
    ok, fail, logs, progress = _run(worker)

    assert 'güvenli olmayan dosya yolu' in fail


def test_scrcpy_arsivde_exe_yoksa_reddedilir(scrcpy_env, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        _zip_ekle(zf, 'scrcpy-v9.9.9/readme.txt', b'x')
    payload = buf.getvalue()
    info = _info(payload)
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_download_info',
                        lambda: info)
    response = FakeResponse(payload, url=info['url'],
                            headers={'Content-Length': str(len(payload))})
    monkeypatch.setattr('urllib.request.urlopen',
                        lambda req, timeout=None: response)

    worker = scrcpy_manager.ScrcpyDownloader(
        target_dir=str(scrcpy_env / 'hedef'))
    ok, fail, logs, progress = _run(worker)

    assert 'scrcpy.exe çıkmadı' in fail


def test_scrcpy_ikili_dogrulama_basarisizsa_reddedilir(scrcpy_env,
                                                       monkeypatch):
    payload = _scrcpy_zip(exe=b'baska-ikili')
    info = _info(payload)
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_download_info',
                        lambda: info)
    # SCRCPY_BINARY_SHA256 sabiti degistirilmez: gercek dogrulama basarisiz olur
    response = FakeResponse(payload, url=info['url'],
                            headers={'Content-Length': str(len(payload))})
    monkeypatch.setattr('urllib.request.urlopen',
                        lambda req, timeout=None: response)

    worker = scrcpy_manager.ScrcpyDownloader(
        target_dir=str(scrcpy_env / 'hedef'))
    ok, fail, logs, progress = _run(worker)

    assert 'resmî sürüm SHA-256 doğrulamasını geçemedi' in fail


def test_scrcpy_indirme_iptali(scrcpy_env, monkeypatch):
    payload = _scrcpy_zip()
    info = _info(payload)
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_download_info',
                        lambda: info)

    worker = scrcpy_manager.ScrcpyDownloader(
        target_dir=str(scrcpy_env / 'hedef'))
    response = FakeResponse(payload, url=info['url'],
                            headers={'Content-Length': str(len(payload))},
                            on_read=worker.cancel)
    monkeypatch.setattr('urllib.request.urlopen',
                        lambda req, timeout=None: response)

    ok, fail, logs, progress = _run(worker)

    assert ok is None
    assert fail == 'kullanıcı durdurdu'
    assert list(scrcpy_env.glob('mibox-scrcpy-*')) == []


def test_scrcpy_content_length_gecersiz_reddedilir(scrcpy_env, monkeypatch):
    payload = _scrcpy_zip()
    info = _info(payload)
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_download_info',
                        lambda: info)
    response = FakeResponse(payload, url=info['url'],
                            headers={'Content-Length': '0'})
    monkeypatch.setattr('urllib.request.urlopen',
                        lambda req, timeout=None: response)

    worker = scrcpy_manager.ScrcpyDownloader(
        target_dir=str(scrcpy_env / 'hedef'))
    ok, fail, logs, progress = _run(worker)

    assert 'boyutu geçersiz veya çok büyük' in fail
    assert list(scrcpy_env.glob('mibox-scrcpy-*')) == []


class SismikBayt(bytes):
    """len() gercek boyuttan bagimsiz olarak 64 MB sinirini asar."""

    def __len__(self):
        return 64 * 1024 * 1024 + 1


class SismikCevap(FakeResponse):
    """Ilk okumada sismik parca dondurur; govde hic yazilmaz."""

    def read(self, n=-1):
        return SismikBayt(b'x')


def test_scrcpy_parca_boyutu_siniri_reddedilir(scrcpy_env, monkeypatch):
    payload = _scrcpy_zip()
    info = _info(payload)
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_download_info',
                        lambda: info)
    response = SismikCevap(payload, url=info['url'],
                           headers={'Content-Length': str(len(payload))})
    monkeypatch.setattr('urllib.request.urlopen',
                        lambda req, timeout=None: response)

    worker = scrcpy_manager.ScrcpyDownloader(
        target_dir=str(scrcpy_env / 'hedef'))
    ok, fail, logs, progress = _run(worker)

    assert 'izin verilen boyutu aşıyor' in fail
    assert list(scrcpy_env.glob('mibox-scrcpy-*')) == []


def test_scrcpy_boyut_beklenti_uyusmazligi(scrcpy_env, monkeypatch):
    payload = _scrcpy_zip()
    fazla = payload + b'ABCDE'
    info = _info(payload)
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_download_info',
                        lambda: info)
    response = FakeResponse(fazla, url=info['url'],
                            headers={'Content-Length': str(len(fazla))})
    monkeypatch.setattr('urllib.request.urlopen',
                        lambda req, timeout=None: response)

    worker = scrcpy_manager.ScrcpyDownloader(
        target_dir=str(scrcpy_env / 'hedef'))
    ok, fail, logs, progress = _run(worker)

    assert 'sabitlenmiş beklentiyle eşleşmiyor' in fail
    assert list(scrcpy_env.glob('mibox-scrcpy-*')) == []


def test_scrcpy_arsivde_cok_dosya_reddedilir(scrcpy_env, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for i in range(10001):
            _zip_ekle(zf, 'scrcpy-v9.9.9/dosya{:05d}'.format(i), b'')
    payload = buf.getvalue()
    info = _info(payload)
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_download_info',
                        lambda: info)
    response = FakeResponse(payload, url=info['url'],
                            headers={'Content-Length': str(len(payload))})
    monkeypatch.setattr('urllib.request.urlopen',
                        lambda req, timeout=None: response)

    worker = scrcpy_manager.ScrcpyDownloader(
        target_dir=str(scrcpy_env / 'hedef'))
    ok, fail, logs, progress = _run(worker)

    assert 'beklenenden fazla dosya' in fail


def test_scrcpy_arsivde_baglanti_turu_reddedilir(scrcpy_env, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        bag = zipfile.ZipInfo('scrcpy-v9.9.9/kotu-baglanti')
        bag.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(bag, b'hedef')
    payload = buf.getvalue()
    info = _info(payload)
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_download_info',
                        lambda: info)
    response = FakeResponse(payload, url=info['url'],
                            headers={'Content-Length': str(len(payload))})
    monkeypatch.setattr('urllib.request.urlopen',
                        lambda req, timeout=None: response)

    worker = scrcpy_manager.ScrcpyDownloader(
        target_dir=str(scrcpy_env / 'hedef'))
    ok, fail, logs, progress = _run(worker)

    assert 'desteklenmeyen dosya türü' in fail


def test_scrcpy_acilmis_boyut_siniri_reddedilir(scrcpy_env, monkeypatch):
    payload = _scrcpy_zip()
    info = _info(payload)
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_download_info',
                        lambda: info)
    response = FakeResponse(payload, url=info['url'],
                            headers={'Content-Length': str(len(payload))})
    monkeypatch.setattr('urllib.request.urlopen',
                        lambda req, timeout=None: response)

    sahte_uye = zipfile.ZipInfo('scrcpy-v9.9.9/scrcpy.exe')
    sahte_uye.external_attr = (stat.S_IFREG | 0o644) << 16
    sahte_uye.file_size = 257 * 1024 * 1024
    monkeypatch.setattr(zipfile.ZipFile, 'infolist', lambda self: [sahte_uye])

    worker = scrcpy_manager.ScrcpyDownloader(
        target_dir=str(scrcpy_env / 'hedef'))
    ok, fail, logs, progress = _run(worker)

    assert 'açılmış boyutu' in fail


def test_scrcpy_arsivde_klasor_uyesi_kurulur(scrcpy_env, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        _zip_ekle(zf, 'scrcpy-v9.9.9/scrcpy.exe', b'dizinli-exe')
        klasor = zipfile.ZipInfo('scrcpy-v9.9.9/ekler/')
        klasor.external_attr = (stat.S_IFDIR | 0o755) << 16
        zf.writestr(klasor, b'')
    payload = buf.getvalue()
    info = _info(payload)
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_download_info',
                        lambda: info)
    monkeypatch.setattr(
        scrcpy_manager, 'SCRCPY_BINARY_SHA256',
        {scrcpy_manager.get_scrcpy_arch_prefix():
         hashlib.sha256(b'dizinli-exe').hexdigest()})
    response = FakeResponse(payload, url=info['url'],
                            headers={'Content-Length': str(len(payload))})
    monkeypatch.setattr('urllib.request.urlopen',
                        lambda req, timeout=None: response)

    hedef = scrcpy_env / 'kok' / 'scrcpy-v9.9.9'
    worker = scrcpy_manager.ScrcpyDownloader()
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert (hedef / 'ekler').is_dir()
    assert (hedef / 'scrcpy.exe').read_bytes() == b'dizinli-exe'


def test_scrcpy_arsivde_yinelenen_yol_reddedilir(scrcpy_env, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        _zip_ekle(zf, 'scrcpy-v9.9.9/cakisma.txt', b'bir')
        _zip_ekle(zf, 'cakisma.txt', b'iki')
    payload = buf.getvalue()
    info = _info(payload)
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_download_info',
                        lambda: info)
    response = FakeResponse(payload, url=info['url'],
                            headers={'Content-Length': str(len(payload))})
    monkeypatch.setattr('urllib.request.urlopen',
                        lambda req, timeout=None: response)

    worker = scrcpy_manager.ScrcpyDownloader(
        target_dir=str(scrcpy_env / 'hedef'))
    ok, fail, logs, progress = _run(worker)

    assert 'yinelenen dosya yolu' in fail


def test_scrcpy_temizlik_hatasi_yutulur(scrcpy_env, monkeypatch):
    payload = _scrcpy_zip(ekler=[('../kacis.exe', b'x')])
    info = _info(payload)
    monkeypatch.setattr(scrcpy_manager, 'get_scrcpy_download_info',
                        lambda: info)
    response = FakeResponse(payload, url=info['url'],
                            headers={'Content-Length': str(len(payload))})
    monkeypatch.setattr('urllib.request.urlopen',
                        lambda req, timeout=None: response)

    def patlak_rmtree(path, ignore_errors=False):
        raise OSError('silinemez')

    monkeypatch.setattr(scrcpy_manager.shutil, 'rmtree', patlak_rmtree)

    worker = scrcpy_manager.ScrcpyDownloader(
        target_dir=str(scrcpy_env / 'hedef'))
    ok, fail, logs, progress = _run(worker)

    assert 'güvenli olmayan dosya yolu' in fail
    assert list(scrcpy_env.glob('mibox-scrcpy-*')) == []


# --- launch_scrcpy -----------------------------------------------------------

class FakeStdout:
    def __init__(self, lines):
        self.lines = list(lines)
        self.closed = False

    def __iter__(self):
        return iter(self.lines)

    def close(self):
        self.closed = True


class FakePopen:
    instances = []

    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.stdout = FakeStdout(['baglandi 192.168.1.5:5555\n'])
        self.terminated = False
        FakePopen.instances.append(self)

    def terminate(self):
        self.terminated = True


class FakeThread:
    instances = []

    def __init__(self, target=None, args=(), name=None, daemon=None):
        self.target = target
        self.args = args
        self.name = name
        self.daemon = daemon
        FakeThread.instances.append(self)

    def start(self):
        pass


@pytest.fixture
def scrcpy_dosyalari(tmp_path, monkeypatch):
    """Taklit-dogrulanmis scrcpy.exe + adb.exe + izole LOG_DIR."""
    monkeypatch.setattr(scrcpy_manager, 'LOG_DIR', str(tmp_path / 'log'))
    scrcpy_exe = _yaz_exe(tmp_path / 'scrcpy' / 'scrcpy.exe', b'x')
    adb_exe = tmp_path / 'adb.exe'
    adb_exe.write_bytes(b'y')
    monkeypatch.setattr(scrcpy_manager, '_verify_scrcpy_executable',
                        lambda p: True)
    return scrcpy_exe, adb_exe


def test_launch_scrcpy_temel(scrcpy_dosyalari, monkeypatch, tmp_path):
    scrcpy_exe, adb_exe = scrcpy_dosyalari
    FakePopen.instances.clear()
    FakeThread.instances.clear()
    monkeypatch.setattr(scrcpy_manager, 'threading',
                        SimpleNamespace(Thread=FakeThread))
    monkeypatch.setattr(scrcpy_manager.subprocess, 'Popen', FakePopen)

    process = scrcpy_manager.launch_scrcpy(
        str(scrcpy_exe), '192.168.1.5:5555', adb_path=str(adb_exe),
        extra_args=['--stay-awake'])

    assert isinstance(process, FakePopen)
    assert process.cmd == [
        str(scrcpy_exe), '-s', '192.168.1.5:5555',
        '--window-title',
        'MiBox Canlı Ekran - 192.168.1.5:5555 (Scrcpy 60 FPS)',
        '--stay-awake']
    assert process.kwargs['cwd'] == str(scrcpy_exe.parent)
    env = process.kwargs['env']
    assert env['ADB'] == str(adb_exe)
    assert env['PATH'].startswith(str(adb_exe.parent) + os.pathsep)
    assert process.kwargs['creationflags'] == \
        getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    assert process.kwargs['stdout'] is not subprocess.DEVNULL

    # Log is parcacigi thread baslatmadan senkron kosulur.
    assert len(FakeThread.instances) == 1
    thread = FakeThread.instances[0]
    assert thread.name == 'mibox-scrcpy-log' and thread.daemon is True
    thread.target(*thread.args)

    log_dosyalari = list((tmp_path / 'log').glob('scrcpy-*.log'))
    assert len(log_dosyalari) == 1
    icerik = log_dosyalari[0].read_text(encoding='utf-8')
    assert 'Scrcpy Başlatıldı' in icerik
    assert 'baglandi' in icerik
    assert '192.168.1.5' not in icerik  # cihaz adresi maskelendi
    assert process.stdout.closed is True


def test_launch_scrcpy_ozel_baslik(scrcpy_dosyalari, monkeypatch):
    scrcpy_exe, _adb = scrcpy_dosyalari
    FakePopen.instances.clear()
    FakeThread.instances.clear()
    monkeypatch.setattr(scrcpy_manager, 'threading',
                        SimpleNamespace(Thread=FakeThread))
    monkeypatch.setattr(scrcpy_manager.subprocess, 'Popen', FakePopen)

    process = scrcpy_manager.launch_scrcpy(str(scrcpy_exe), 'tv-seri',
                                           window_title='Özel Başlık')

    assert process.cmd[process.cmd.index('--window-title') + 1] == 'Özel Başlık'


def test_launch_scrcpy_dosya_yok(tmp_path):
    with pytest.raises(FileNotFoundError):
        scrcpy_manager.launch_scrcpy(str(tmp_path / 'yok.exe'), 'tv')


def test_launch_scrcpy_dogrulama_basarisiz(tmp_path, monkeypatch):
    exe = tmp_path / 'scrcpy.exe'
    exe.write_bytes(b'x')
    monkeypatch.setattr(scrcpy_manager, '_verify_scrcpy_executable',
                        lambda p: False)
    with pytest.raises(RuntimeError) as excinfo:
        scrcpy_manager.launch_scrcpy(str(exe), 'tv')
    assert 'SHA-256' in str(excinfo.value)


def test_launch_scrcpy_log_yoksa_devnull(scrcpy_dosyalari, monkeypatch,
                                         tmp_path):
    scrcpy_exe, _adb = scrcpy_dosyalari
    engel = tmp_path / 'log-dosyasi'
    engel.write_text('x', encoding='utf-8')
    monkeypatch.setattr(scrcpy_manager, 'LOG_DIR', str(engel))
    FakePopen.instances.clear()
    FakeThread.instances.clear()
    monkeypatch.setattr(scrcpy_manager, 'threading',
                        SimpleNamespace(Thread=FakeThread))
    monkeypatch.setattr(scrcpy_manager.subprocess, 'Popen', FakePopen)

    process = scrcpy_manager.launch_scrcpy(str(scrcpy_exe), 'tv')

    assert process.kwargs['stdout'] is subprocess.DEVNULL
    assert process.kwargs['text'] is None
    assert FakeThread.instances == []


def test_launch_scrcpy_thread_hatasi_sureci_kapatir(scrcpy_dosyalari,
                                                    monkeypatch):
    scrcpy_exe, _adb = scrcpy_dosyalari

    class KotuThread(FakeThread):
        def start(self):
            raise RuntimeError('thread baslatilamadi')

    FakePopen.instances.clear()
    monkeypatch.setattr(scrcpy_manager, 'threading',
                        SimpleNamespace(Thread=KotuThread))
    monkeypatch.setattr(scrcpy_manager.subprocess, 'Popen', FakePopen)

    with pytest.raises(RuntimeError):
        scrcpy_manager.launch_scrcpy(str(scrcpy_exe), 'tv')

    process = FakePopen.instances[-1]
    assert process.stdout.closed is True
    assert process.terminated is True


def test_launch_scrcpy_terminate_hatasi_yutulur(scrcpy_dosyalari,
                                                monkeypatch):
    scrcpy_exe, _adb = scrcpy_dosyalari

    class KotuThread(FakeThread):
        def start(self):
            raise RuntimeError('thread baslatilamadi')

    class KotuTerminate(FakePopen):
        def terminate(self):
            raise OSError('kapatilamaz')

    FakePopen.instances.clear()
    monkeypatch.setattr(scrcpy_manager, 'threading',
                        SimpleNamespace(Thread=KotuThread))
    monkeypatch.setattr(scrcpy_manager.subprocess, 'Popen', KotuTerminate)

    with pytest.raises(RuntimeError):
        scrcpy_manager.launch_scrcpy(str(scrcpy_exe), 'tv')

    process = FakePopen.instances[-1]
    assert process.stdout.closed is True


# --- _log_scrcpy_output ------------------------------------------------------

class Cikti:
    def __init__(self, lines):
        self.lines = lines
        self.consumed = 0
        self.closed = False

    def __iter__(self):
        for line in self.lines:
            self.consumed += 1
            yield line

    def close(self):
        self.closed = True


def test_log_scrcpy_output_maskeler(tmp_path):
    log_path = tmp_path / 'scrcpy.log'
    output = Cikti(['baglandi 192.168.1.5:5555\n', 'bitti\n'])

    scrcpy_manager._log_scrcpy_output(
        output, str(log_path), ['192.168.1.5:5555', '192.168.1.5'])

    icerik = log_path.read_text(encoding='utf-8')
    assert '192.168.1.5' not in icerik
    assert 'bitti' in icerik
    assert output.consumed == 2
    assert output.closed is True


def test_log_scrcpy_output_yazamazsa_tuketir(tmp_path):
    output = Cikti(['a\n', 'b\n'])

    scrcpy_manager._log_scrcpy_output(output, str(tmp_path), [])

    assert output.consumed == 2
    assert output.closed is True


def test_log_scrcpy_output_tuketim_hatasi_yutulur(tmp_path):
    class TukenemeyenCikti:
        def __init__(self):
            self.closed = False

        def __iter__(self):
            raise OSError('okunamaz')

        def close(self):
            self.closed = True

    output = TukenemeyenCikti()
    scrcpy_manager._log_scrcpy_output(output, str(tmp_path), [])

    assert output.closed is True


@pytest.mark.parametrize('hata', [OSError('kapatilamaz'),
                                  ValueError('kapatilamaz')])
def test_log_scrcpy_output_kapatma_hatasi_yutulur(tmp_path, hata):
    class KapatmaPatlak:
        def __init__(self, hata):
            self.hata = hata

        def __iter__(self):
            return iter(())

        def close(self):
            raise self.hata

    log_path = tmp_path / 'scrcpy.log'
    scrcpy_manager._log_scrcpy_output(KapatmaPatlak(hata), str(log_path), [])

    assert log_path.exists()
