# -*- coding: utf-8 -*-
"""snapshot.py: şema doğrulama, atomik kayıt ve motor akışları testleri.

Gerçek ADB yok: take/diff/apply sahte motorlarla koşulur. Dosyalar geçici
klasörde tutulur (config.BASE_DIR monkeypatch); kullanıcı verisine
dokunulmaz.
"""
import json

import pytest

from mibox_app import config, snapshot
from mibox_app.adb_engine import AdbError
from mibox_app.workers import CancelledError


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'BASE_DIR', str(tmp_path))
    return tmp_path


def _durum(enabled=True, installed_user0=True, restricted=False):
    return {'enabled': enabled, 'installed_user0': installed_user0,
            'restricted': restricted}


def _snap(packages, created='2026-01-01 00:00:00', target='tv-1', user_id=None):
    data = {'created': created, 'target': target, 'packages': packages}
    if user_id is not None:
        data['user_id'] = user_id
    return data


def _girdi(pkg, enabled=True, installed_user0=True):
    return {'package': pkg, 'enabled': enabled, 'installed_user0': installed_user0}


class SnapEngine:
    """take/diff_current'in kullandığı eski (user'sız) motor API'si."""

    def __init__(self, detailed, restricted=()):
        self.detailed = detailed
        self.restricted = set(restricted)
        self.calls = []

    def connect(self, target, cancel_check=None):
        self.calls.append(('connect', target))

    def list_packages_detailed(self, target, include_system=True, use_cache=True):
        self.calls.append(('list_packages_detailed', include_system, use_cache))
        return list(self.detailed)

    def bulk_restricted(self, target):
        self.calls.append(('bulk_restricted', target))
        return set(self.restricted)


class UserEngine:
    """user_id parametrelerini (ve **kwargs yolunu) sunan motor."""

    def __init__(self, detailed, restricted=()):
        self.detailed = detailed
        self.restricted = set(restricted)
        self.calls = []

    def connect(self, target, cancel_check=None):
        self.calls.append(('connect', target))

    def list_packages_detailed_for_user_id(self, target, include_system=True,
                                           use_cache=True, user_id=0, **kwargs):
        self.calls.append(('list', include_system, use_cache, user_id))
        return list(self.detailed)

    def bulk_restricted_for_user_id(self, target, user_id=0):
        self.calls.append(('bulk', user_id))
        return set(self.restricted)


class DurumMotoru:
    """apply akışı için durum tutan sahte motor (user 0, eski API)."""

    def __init__(self, durumlar, restricted=()):
        # durumlar: {pkg: {'enabled': bool, 'installed_user0': bool}}
        self.durumlar = {p: dict(d) for p, d in durumlar.items()}
        self.restricted = set(restricted)
        self.calls = []

    def connect(self, target, cancel_check=None):
        self.calls.append(('connect', target))

    def list_packages_detailed(self, target, include_system=True, use_cache=True):
        return [{'package': p, 'enabled': d['enabled'],
                 'installed_user0': d['installed_user0']}
                for p, d in self.durumlar.items()]

    def bulk_restricted(self, target):
        return set(self.restricted)

    def enable(self, target, pkg, user_id=0):
        self.calls.append(('enable', pkg))
        self.durumlar[pkg]['enabled'] = True

    def disable_user(self, target, pkg, user_id=0):
        self.calls.append(('disable', pkg))
        self.durumlar[pkg]['enabled'] = False

    def uninstall_user(self, target, pkg, user_id=0):
        self.calls.append(('uninstall', pkg))
        self.durumlar[pkg]['installed_user0'] = False

    def install_existing(self, target, pkg, user_id=0):
        self.calls.append(('install_existing', pkg))
        self.durumlar[pkg]['installed_user0'] = True

    def restrict(self, target, pkg, user_id=0):
        self.calls.append(('restrict', pkg))
        self.restricted.add(pkg)

    def unrestrict(self, target, pkg, user_id=0):
        self.calls.append(('unrestrict', pkg))
        self.restricted.discard(pkg)


# --- validate ----------------------------------------------------------------

def test_validate_temel_sema_gecer():
    data = _snap({'com.a': _durum()})
    assert snapshot.validate(data) is data


def test_validate_user_id_ile_gecer():
    data = _snap({'com.a': _durum()}, user_id=2)
    assert snapshot.validate(data) is data


def test_validate_fazla_alan_reddedilir():
    data = _snap({'com.a': _durum()})
    data['ekstra'] = 1
    with pytest.raises(ValueError):
        snapshot.validate(data)


def test_validate_eksik_alan_reddedilir():
    with pytest.raises(ValueError):
        snapshot.validate({'created': 'x', 'packages': {'com.a': _durum()}})


@pytest.mark.parametrize('alan,deger', [
    ('created', 5),
    ('target', None),
    ('created', 'x' * 129),
    ('target', 'y' * 513),
])
def test_validate_metadata_tur_ve_uzunluk(alan, deger):
    data = _snap({'com.a': _durum()})
    data[alan] = deger
    with pytest.raises(ValueError):
        snapshot.validate(data)


@pytest.mark.parametrize('kotu_user', [-1, 21475, True, '0', 1.5])
def test_validate_user_id_reddedilir(kotu_user):
    data = _snap({'com.a': _durum()}, user_id=kotu_user)
    with pytest.raises(ValueError):
        snapshot.validate(data)


def test_validate_user_id_sinirlari():
    snapshot.validate(_snap({'com.a': _durum()}, user_id=0))
    snapshot.validate(_snap({'com.a': _durum()}, user_id=21474))


@pytest.mark.parametrize('paketler', [{}, [], 'liste', None])
def test_validate_paketler_sozluk_olmali(paketler):
    data = _snap({'com.a': _durum()})
    data['packages'] = paketler
    with pytest.raises(ValueError):
        snapshot.validate(data)


def test_validate_paket_sayisi_siniri(monkeypatch):
    monkeypatch.setattr(snapshot, '_MAX_SNAPSHOT_PACKAGES', 2)
    data = _snap({'com.a': _durum(), 'com.b': _durum(), 'com.c': _durum()})
    with pytest.raises(ValueError):
        snapshot.validate(data)


@pytest.mark.parametrize('kotu_ad', [
    '', ' com.a', 'com.a ', 'com:a', 'com.a b', '.com.a', 'com..a',
    '9com.a', 'com.9a?',
])
def test_validate_paket_adi_reddedilir(kotu_ad):
    with pytest.raises(ValueError):
        snapshot.validate(_snap({kotu_ad: _durum()}))


@pytest.mark.parametrize('bozuk', [
    {'enabled': True, 'installed_user0': True},
    {'enabled': True, 'installed_user0': True, 'restricted': False, 'ekstra': 1},
    {'enabled': 1, 'installed_user0': True, 'restricted': False},
    {'enabled': True, 'installed_user0': 'evet', 'restricted': False},
    'durum', None, [],
])
def test_validate_paket_durumu_bozuksa_reddedilir(bozuk):
    with pytest.raises(ValueError):
        snapshot.validate(_snap({'com.a': bozuk}))


# --- snapshot_path / _safe_label / list_snapshots ----------------------------

def test_snapshot_path_gecerli_ad(base):
    yol = snapshot.snapshot_path('mibox-snapshot-abc.json')
    assert yol == str(base / 'snapshots' / 'mibox-snapshot-abc.json')


@pytest.mark.parametrize('kotu_ad', [
    'abc.json', 'mibox-snapshot-abc.txt', 'mibox-snapshot-../x.json',
    'mibox-snapshot-a\\b.json', 123, None,
])
def test_snapshot_path_gecersiz_ad(base, kotu_ad):
    with pytest.raises(ValueError):
        snapshot.snapshot_path(kotu_ad)


@pytest.mark.parametrize('etiket,beklenen', [
    ('Kanal 5!', 'Kanal5'),
    ('', 'adsiz'),
    (None, 'adsiz'),
    ('   ', 'adsiz'),
    ('a' * 100, 'a' * 40),
    ('üöç-_-', 'üöç-_-'),
    ('tv-1:5555', 'tv-15555'),
])
def test_safe_label(etiket, beklenen):
    assert snapshot._safe_label(etiket) == beklenen


def test_list_snapshots_dizin_yoksa_bos(base):
    assert snapshot.list_snapshots() == []


def test_list_snapshots_yalniz_desenli_dosyalar(base):
    d = base / 'snapshots'
    d.mkdir()
    for ad in ('mibox-snapshot-b.json', 'mibox-snapshot-a.json',
               'baska.json', 'mibox-snapshot-c.txt'):
        (d / ad).write_text('{}', encoding='utf-8')
    assert snapshot.list_snapshots() == ['mibox-snapshot-a.json',
                                         'mibox-snapshot-b.json']


def test_list_snapshots_dizin_hatasinda_bos(monkeypatch):
    def patla():
        raise OSError('dizin olusturulamadi')

    monkeypatch.setattr(snapshot, '_dir', patla)
    assert snapshot.list_snapshots() == []


def test_accepts_user_id_imza_okunamazsa_false(monkeypatch):
    def patlak_signature(method):
        raise TypeError('imza yok')

    monkeypatch.setattr(snapshot.inspect, 'signature', patlak_signature)
    assert snapshot._accepts_user_id(lambda: None) is False


def test_call_user_api_ikinci_imza_okunamazsa_kwargs_suzulur(monkeypatch):
    cagrilar = []

    class Motor:
        def dene(self, **kwargs):
            cagrilar.append(kwargs)

    gercek_signature = snapshot.inspect.signature
    sayac = {'n': 0}

    def sahte_signature(method):
        sayac['n'] += 1
        if sayac['n'] == 1:
            return gercek_signature(method)
        raise ValueError('imza yok')

    monkeypatch.setattr(snapshot.inspect, 'signature', sahte_signature)
    snapshot._call_user_api(Motor(), ('dene',), {'target': 'tv-1'}, 0,
                            'Açıklama')

    assert cagrilar == [{}]


# --- _save_unique ------------------------------------------------------------

def test_save_unique_dosyayi_yazar(base):
    ad = snapshot._save_unique('mibox-snapshot-test.json', _snap({'com.a': _durum()}))
    assert ad == 'mibox-snapshot-test.json'
    yol = base / 'snapshots' / ad
    assert json.loads(yol.read_text(encoding='utf-8'))['packages'] == {'com.a': _durum()}
    assert [p.name for p in (base / 'snapshots').iterdir()
            if p.name.endswith('.tmp')] == []


def test_save_unique_ad_cakismasinda_numara_verir(base):
    ilk = snapshot._save_unique('mibox-snapshot-test.json', _snap({'com.a': _durum()}))
    ikinci = snapshot._save_unique('mibox-snapshot-test.json', _snap({'com.b': _durum()}))
    ucuncu = snapshot._save_unique('mibox-snapshot-test.json', _snap({'com.c': _durum()}))
    assert (ilk, ikinci, ucuncu) == (
        'mibox-snapshot-test.json', 'mibox-snapshot-test-2.json',
        'mibox-snapshot-test-3.json')
    # İlk dosyanın içeriği korunur.
    yol = base / 'snapshots' / ilk
    assert list(json.loads(yol.read_text(encoding='utf-8'))['packages']) == ['com.a']


def test_save_unique_gecersiz_veri_reddedilir(base):
    with pytest.raises(ValueError):
        snapshot._save_unique('mibox-snapshot-test.json', {'created': 'x'})
    assert snapshot.list_snapshots() == []


def test_save_unique_boyut_siniri(base, monkeypatch):
    monkeypatch.setattr(snapshot, '_MAX_SNAPSHOT_BYTES', 60)
    with pytest.raises(ValueError):
        snapshot._save_unique('mibox-snapshot-buyuk.json',
                              _snap({'com.uzun': _durum()}))
    assert snapshot.list_snapshots() == []
    assert [p.name for p in (base / 'snapshots').iterdir()
            if p.name.endswith('.tmp')] == []


def test_save_unique_fsync_hatasi_yutulur(base, monkeypatch):
    def patla(fd):
        raise OSError('fsync yok')

    monkeypatch.setattr(snapshot.os, 'fsync', patla)
    ad = snapshot._save_unique('mibox-snapshot-test.json',
                               _snap({'com.a': _durum()}))

    assert ad == 'mibox-snapshot-test.json'
    assert snapshot.load(ad)['packages']['com.a'] == _durum()


def test_save_unique_temizlik_hatasi_yutulur(base, monkeypatch):
    def patlak_remove(path):
        raise OSError('silinemez')

    monkeypatch.setattr(snapshot.os, 'remove', patlak_remove)
    ad = snapshot._save_unique('mibox-snapshot-test.json',
                               _snap({'com.a': _durum()}))

    assert ad == 'mibox-snapshot-test.json'
    assert snapshot.load(ad)['packages']['com.a'] == _durum()


# --- load / delete / export / import -----------------------------------------

def test_load_kaydedileni_dogrular(base):
    ad = snapshot._save_unique('mibox-snapshot-test.json',
                               _snap({'com.a': _durum()}, user_id=2))
    veri = snapshot.load(ad)
    assert veri['user_id'] == 2
    assert veri['packages']['com.a'] == _durum()


def test_load_gecersiz_ad_reddedilir(base):
    with pytest.raises(ValueError):
        snapshot.load('kotu.json')


def test_load_bozuk_dosya_reddedilir(base):
    d = base / 'snapshots'
    d.mkdir()
    (d / 'mibox-snapshot-bozuk.json').write_text('{"created": 1}', encoding='utf-8')
    with pytest.raises(ValueError):
        snapshot.load('mibox-snapshot-bozuk.json')


def test_load_yinelenen_alan_reddedilir(base):
    d = base / 'snapshots'
    d.mkdir()
    ham = ('{"created": "x", "created": "y", "target": "tv", "packages": '
           '{"com.a": {"enabled": true, "installed_user0": true, "restricted": false}}}')
    (d / 'mibox-snapshot-dup.json').write_text(ham, encoding='utf-8')
    with pytest.raises(ValueError):
        snapshot.load('mibox-snapshot-dup.json')


def test_load_boyut_siniri(base, monkeypatch):
    d = base / 'snapshots'
    d.mkdir()
    (d / 'mibox-snapshot-buyuk.json').write_text('x' * 200, encoding='utf-8')
    monkeypatch.setattr(snapshot, '_MAX_SNAPSHOT_BYTES', 100)
    with pytest.raises(ValueError):
        snapshot.load('mibox-snapshot-buyuk.json')


def test_delete_siler_ve_eksikte_false(base):
    ad = snapshot._save_unique('mibox-snapshot-test.json', _snap({'com.a': _durum()}))
    assert snapshot.delete(ad) is True
    assert snapshot.list_snapshots() == []
    assert snapshot.delete(ad) is False
    assert snapshot.delete('kotu.json') is False


def test_export_snapshot_disa_yazar(base):
    ad = snapshot._save_unique('mibox-snapshot-test.json', _snap({'com.a': _durum()}))
    hedef = base / 'disa' / 'yedek.json'
    hedef.parent.mkdir()
    assert snapshot.export_snapshot(ad, str(hedef)) == 1
    assert json.loads(hedef.read_text(encoding='utf-8')) == snapshot.load(ad)


def test_export_snapshot_gecersiz_ad(base):
    hedef = base / 'yedek.json'
    with pytest.raises(ValueError):
        snapshot.export_snapshot('kotu.json', str(hedef))
    assert not hedef.exists()


def test_export_snapshot_boyut_siniri(base, monkeypatch):
    ad = snapshot._save_unique('mibox-snapshot-test.json',
                               _snap({'com.a': _durum()}))
    hedef = base / 'disa' / 'yedek.json'
    hedef.parent.mkdir()

    gercek_getsize = snapshot.os.path.getsize

    def sahte_getsize(path):
        if 'export' in str(path):
            return snapshot._MAX_SNAPSHOT_BYTES + 1
        return gercek_getsize(path)

    monkeypatch.setattr(snapshot.os.path, 'getsize', sahte_getsize)
    with pytest.raises(ValueError) as excinfo:
        snapshot.export_snapshot(ad, str(hedef))

    assert 'boyutu aşıyor' in str(excinfo.value)
    assert not hedef.exists()
    assert list(hedef.parent.iterdir()) == []


def test_export_snapshot_fdopen_hatasinda_fd_kapatilir(base, monkeypatch):
    ad = snapshot._save_unique('mibox-snapshot-test.json',
                               _snap({'com.a': _durum()}))
    hedef = base / 'disa' / 'yedek.json'
    hedef.parent.mkdir()

    def patlak_fdopen(fd, *args, **kwargs):
        raise OSError('fdopen yok')

    gercek_close = snapshot.os.close

    def patlak_close(fd):
        gercek_close(fd)  # Windows'ta dosya kilidi kalmasin
        raise OSError('kapatilamaz')

    monkeypatch.setattr(snapshot.os, 'fdopen', patlak_fdopen)
    monkeypatch.setattr(snapshot.os, 'close', patlak_close)
    with pytest.raises(OSError):
        snapshot.export_snapshot(ad, str(hedef))

    assert not hedef.exists()
    assert list(hedef.parent.iterdir()) == []


def test_export_snapshot_temizlik_hatasi_yutulur(base, monkeypatch):
    ad = snapshot._save_unique('mibox-snapshot-test.json',
                               _snap({'com.a': _durum()}))
    hedef = base / 'disa' / 'yedek.json'
    hedef.parent.mkdir()

    def patlak_remove(path):
        raise OSError('silinemez')

    def sahte_getsize(path):
        return snapshot._MAX_SNAPSHOT_BYTES + 1

    monkeypatch.setattr(snapshot.os, 'remove', patlak_remove)
    monkeypatch.setattr(snapshot.os.path, 'getsize', sahte_getsize)
    with pytest.raises(ValueError):
        snapshot.export_snapshot(ad, str(hedef))

    assert not hedef.exists()


def test_import_snapshot_klon_olarak_kaydeder(base):
    kaynak = base / 'disaridan.json'
    kaynak.write_text(json.dumps(_snap({'com.a': _durum()})), encoding='utf-8')
    ad, adet = snapshot.import_snapshot(str(kaynak))
    assert adet == 1
    assert ad.startswith('mibox-snapshot-klon-')
    assert snapshot.load(ad)['packages']['com.a'] == _durum()


def test_import_snapshot_mevcut_dosyanin_ustune_yazmaz(base):
    kaynak = base / 'disaridan.json'
    kaynak.write_text(json.dumps(_snap({'com.a': _durum()})), encoding='utf-8')
    ilk, _ = snapshot.import_snapshot(str(kaynak))
    ikinci, _ = snapshot.import_snapshot(str(kaynak))
    assert ilk != ikinci
    assert len(snapshot.list_snapshots()) == 2


def test_import_snapshot_bozuk_dosyayi_reddeder(base):
    kaynak = base / 'bozuk.json'
    kaynak.write_text('{"created": 1}', encoding='utf-8')
    with pytest.raises(ValueError):
        snapshot.import_snapshot(str(kaynak))
    assert snapshot.list_snapshots() == []


def test_validated_entries_paket_siniri(monkeypatch):
    monkeypatch.setattr(snapshot, '_MAX_SNAPSHOT_PACKAGES', 2)
    with pytest.raises(AdbError):
        snapshot._validated_entries(
            [_girdi('com.a'), _girdi('com.b'), _girdi('com.c')])


def test_validated_entries_bozuk_kayit():
    with pytest.raises(AdbError):
        snapshot._validated_entries(['com.a'])


# --- take --------------------------------------------------------------------

def test_take_snapshot_kaydeder(base):
    engine = SnapEngine([_girdi('com.a'), _girdi('com.b', enabled=False)], {'com.b'})
    ad, adet = snapshot.take(engine, 'tv-1')
    assert adet == 2
    assert ad.startswith('mibox-snapshot-tv-1-')
    veri = snapshot.load(ad)
    assert veri['target'] == 'tv-1'
    assert veri['user_id'] == 0
    assert veri['packages'] == {
        'com.a': _durum(),
        'com.b': _durum(enabled=False, restricted=True),
    }
    # Snapshot her zaman gerçeği görmeli: önbellek atlanır.
    assert ('list_packages_detailed', True, False) in engine.calls


def test_take_hedef_nokta_iceriyorsa_etiket_temizlenir(base):
    engine = SnapEngine([_girdi('com.a')], set())
    ad, _ = snapshot.take(engine, 'tv:5555')
    assert ':' not in ad
    assert 'tv-5555' in ad


def test_take_user_id_motoru_kullanir(base):
    engine = UserEngine([_girdi('com.a')], set())
    ad, _ = snapshot.take(engine, 'tv-1', user_id=2)
    assert ('list', True, False, 2) in engine.calls
    assert ('bulk', 2) in engine.calls
    assert snapshot.load(ad)['user_id'] == 2


def test_take_user_1_eski_motorla_reddedilir(base):
    engine = SnapEngine([_girdi('com.a')], set())
    with pytest.raises(AdbError):
        snapshot.take(engine, 'tv-1', user_id=1)
    assert snapshot.list_snapshots() == []


def test_take_kisitlama_okunamazsa_kaydetmez(base):
    class NullEngine(SnapEngine):
        def bulk_restricted(self, target):
            return None

    engine = NullEngine([_girdi('com.a')], set())
    with pytest.raises(AdbError):
        snapshot.take(engine, 'tv-1')
    assert snapshot.list_snapshots() == []


def test_take_bozuk_kisitlama_listesi_kaydetmez(base):
    engine = SnapEngine([_girdi('com.a')], {'com:bozuk'})
    with pytest.raises(AdbError):
        snapshot.take(engine, 'tv-1')
    assert snapshot.list_snapshots() == []


def test_take_bozuk_paket_listesi_kaydetmez(base):
    engine = SnapEngine([{'package': 'com.a', 'enabled': True}], set())
    with pytest.raises(AdbError):
        snapshot.take(engine, 'tv-1')
    assert snapshot.list_snapshots() == []


def test_take_bos_paket_listesi_kaydetmez(base):
    engine = SnapEngine([], set())
    with pytest.raises(AdbError):
        snapshot.take(engine, 'tv-1')


def test_take_iptal_edilirse_kaydetmez(base):
    engine = SnapEngine([_girdi('com.a')], set())
    with pytest.raises(CancelledError):
        snapshot.take(engine, 'tv-1', is_cancelled=lambda: True)
    assert engine.calls == []
    assert snapshot.list_snapshots() == []


def test_take_arada_iptal_kaydetmez(base):
    engine = SnapEngine([_girdi('com.a')], set())
    durum = {'sayi': 0}

    def iptal():
        durum['sayi'] += 1
        return durum['sayi'] > 1

    with pytest.raises(CancelledError):
        snapshot.take(engine, 'tv-1', is_cancelled=iptal)
    assert engine.calls and engine.calls[0][0] == 'connect'
    assert snapshot.list_snapshots() == []


# --- diff_current ------------------------------------------------------------

def test_diff_ayni_durumda_bos(base):
    engine = SnapEngine([_girdi('com.a')], set())
    assert snapshot.diff_current(engine, 'tv-1', _snap({'com.a': _durum()})) == []


def test_diff_restore_enable_unrestrict_sirasi(base):
    engine = SnapEngine([_girdi('com.a', enabled=False, installed_user0=False)],
                        {'com.a'})
    snap = _snap({'com.a': _durum(enabled=True, installed_user0=True,
                                  restricted=False)})
    farklar = snapshot.diff_current(engine, 'tv-1', snap)
    assert len(farklar) == 1
    pkg, _want, _have, aksiyonlar = farklar[0]
    assert pkg == 'com.a'
    assert aksiyonlar == ('restore', 'enable', 'unrestrict')


def test_diff_kaldirilmis_paket_uninstall_uretir(base):
    engine = SnapEngine([_girdi('com.a')], set())
    snap = _snap({'com.a': _durum(installed_user0=False)})
    (pkg, _want, _have, aksiyon), = snapshot.diff_current(engine, 'tv-1', snap)
    assert (pkg, aksiyon) == ('com.a', ('uninstall',))


def test_diff_cihazda_olmayan_paket_bilinmiyor(base):
    engine = SnapEngine([_girdi('com.b')], set())
    snap = _snap({'com.a': _durum()})
    (pkg, _want, have, aksiyon), = snapshot.diff_current(engine, 'tv-1', snap)
    assert pkg == 'com.a'
    assert have is None
    assert aksiyon == 'bilinmiyor (cihazda yok)'


def test_diff_yalniz_cakisan_durum_aksiyon_uretir(base):
    engine = SnapEngine([_girdi('com.a', enabled=True)], set())
    snap = _snap({'com.a': _durum(enabled=False)})
    (pkg, _want, _have, aksiyon), = snapshot.diff_current(engine, 'tv-1', snap)
    assert (pkg, aksiyon) == ('com.a', ('disable',))


def test_diff_snapta_olmayan_cihaz_paketi_yok_sayilir(base):
    engine = SnapEngine([_girdi('com.a'), _girdi('com.fazla')], set())
    assert snapshot.diff_current(engine, 'tv-1', _snap({'com.a': _durum()})) == []


def test_diff_snapshot_user_id_kullanir(base):
    engine = UserEngine([_girdi('com.a')], set())
    snap = _snap({'com.a': _durum()}, user_id=2)
    assert snapshot.diff_current(engine, 'tv-1', snap) == []
    assert ('list', True, False, 2) in engine.calls


def test_diff_kisitlama_okunamazsa_hata(base):
    class NullEngine(SnapEngine):
        def bulk_restricted(self, target):
            return None

    engine = NullEngine([_girdi('com.a')], set())
    with pytest.raises(AdbError):
        snapshot.diff_current(engine, 'tv-1', _snap({'com.a': _durum()}))


def test_diff_bozuk_kisitlama_listesi_hata(base):
    engine = SnapEngine([_girdi('com.a')], {'com:bozuk'})
    with pytest.raises(AdbError):
        snapshot.diff_current(engine, 'tv-1', _snap({'com.a': _durum()}))


# --- apply -------------------------------------------------------------------

def test_apply_farklari_uygular(base):
    engine = DurumMotoru({'com.a': {'enabled': False, 'installed_user0': True}})
    snap = _snap({'com.a': _durum(enabled=True)})
    sonuc = snapshot.apply(engine, 'tv-1', snap)
    assert (sonuc['ok'], sonuc['fail'], sonuc['cancelled']) == (1, 0, False)
    assert sonuc['details'] == [('com.a', True, 'enable uygulandı')]
    assert engine.durumlar['com.a']['enabled'] is True


def test_apply_korunan_pakete_dokunmaz(base):
    engine = DurumMotoru({'com.a': {'enabled': False, 'installed_user0': True}})
    snap = _snap({'com.a': _durum(enabled=True)})
    sonuc = snapshot.apply(engine, 'tv-1', snap, protected=('com.a',))
    assert (sonuc['ok'], sonuc['fail']) == (0, 1)
    assert sonuc['details'] == [('com.a', False, 'koruma listesinde')]
    assert engine.durumlar['com.a']['enabled'] is False


def test_apply_cihazda_olmayani_bildirir(base):
    engine = DurumMotoru({'com.b': {'enabled': True, 'installed_user0': True}})
    snap = _snap({'com.a': _durum()})
    sonuc = snapshot.apply(engine, 'tv-1', snap)
    assert (sonuc['ok'], sonuc['fail']) == (0, 1)
    assert sonuc['details'] == [('com.a', False, 'bilinmiyor (cihazda yok)')]


def test_apply_dogrulama_yalanci_motoru_yakalar(base):
    class YalanciMotor(DurumMotoru):
        def enable(self, target, pkg, user_id=0):
            self.calls.append(('enable', pkg))  # durum değişmez

    engine = YalanciMotor({'com.a': {'enabled': False, 'installed_user0': True}})
    snap = _snap({'com.a': _durum(enabled=True)})
    sonuc = snapshot.apply(engine, 'tv-1', snap)
    assert (sonuc['ok'], sonuc['fail']) == (0, 1)
    assert sonuc['details'][0][0] == 'com.a'
    assert sonuc['details'][0][1] is False
    assert sonuc['details'][0][2].startswith('Snapshot son durumu eşleşmedi')


def test_apply_user_2_eski_motorla_reddedilir(base):
    engine = DurumMotoru({'com.a': {'enabled': False, 'installed_user0': True}})
    snap = _snap({'com.a': _durum(enabled=True)}, user_id=2)
    with pytest.raises(AdbError):
        snapshot.apply(engine, 'tv-1', snap)


def test_apply_basta_iptal_edilirse_islem_yapmaz(base):
    engine = DurumMotoru({'com.a': {'enabled': False, 'installed_user0': True}})
    snap = _snap({'com.a': _durum(enabled=True)})
    sonuc = snapshot.apply(engine, 'tv-1', snap, is_cancelled=lambda: True)
    assert sonuc == {'ok': 0, 'fail': 0, 'details': [], 'action': 'snapshot',
                     'cancelled': True}
    assert engine.calls == []


def test_apply_arada_iptal_kalanlari_bildirir(base):
    engine = DurumMotoru({
        'com.a': {'enabled': False, 'installed_user0': True},
        'com.b': {'enabled': False, 'installed_user0': True},
    })
    snap = _snap({'com.a': _durum(enabled=True), 'com.b': _durum(enabled=True)})
    durum = {'sayi': 0}

    def iptal():
        durum['sayi'] += 1
        return durum['sayi'] > 2

    sonuc = snapshot.apply(engine, 'tv-1', snap, is_cancelled=iptal)
    assert sonuc['cancelled'] is True
    assert sonuc['ok'] == 0
    assert all(detay[1] is False for detay in sonuc['details'])


def test_apply_ilerleme_bildirir(base):
    engine = DurumMotoru({'com.a': {'enabled': False, 'installed_user0': True}})
    snap = _snap({'com.a': _durum(enabled=True)})
    adimlar = []
    snapshot.apply(engine, 'tv-1', snap, progress=lambda i, t: adimlar.append((i, t)))
    assert adimlar == [(1, 1)]


def test_apply_diff_sonrasi_iptal_tum_farklari_isaretler(base):
    engine = DurumMotoru({'com.a': {'enabled': False, 'installed_user0': True}})
    snap = _snap({'com.a': _durum(enabled=True)})
    durum = {'sayi': 0}

    def iptal():
        durum['sayi'] += 1
        return durum['sayi'] > 1

    sonuc = snapshot.apply(engine, 'tv-1', snap, is_cancelled=iptal)

    assert sonuc['cancelled'] is True
    assert (sonuc['ok'], sonuc['fail']) == (0, 1)
    assert sonuc['details'] == [('com.a', False, 'kullanıcı durdurdu')]
    assert engine.durumlar['com.a']['enabled'] is False


def test_apply_ilerleme_hatasi_yutulur(base):
    engine = DurumMotoru({'com.a': {'enabled': False, 'installed_user0': True}})
    snap = _snap({'com.a': _durum(enabled=True)})

    def patlak_ilerleme(i, t):
        raise RuntimeError('ilerleme yok')

    sonuc = snapshot.apply(engine, 'tv-1', snap, progress=patlak_ilerleme)

    assert (sonuc['ok'], sonuc['fail']) == (1, 0)
    assert engine.durumlar['com.a']['enabled'] is True


def test_apply_bilinmeyen_islem_reddedilir(base, monkeypatch):
    engine = DurumMotoru({'com.a': {'enabled': True, 'installed_user0': True}})
    snap = _snap({'com.a': _durum()})
    monkeypatch.setattr(
        snapshot, 'diff_current',
        lambda e, t, s: [('com.a', _durum(), _durum(), 'hayali')])

    sonuc = snapshot.apply(engine, 'tv-1', snap)

    assert (sonuc['ok'], sonuc['fail']) == (0, 1)
    assert sonuc['details'] == [
        ('com.a', False, 'Bilinmeyen snapshot işlemi: hayali')]


def test_apply_islem_ortasinda_iptal(base):
    engine = DurumMotoru({
        'com.a': {'enabled': False, 'installed_user0': True},
        'com.b': {'enabled': False, 'installed_user0': True},
    })
    snap = _snap({'com.a': _durum(enabled=True), 'com.b': _durum(enabled=True)})
    durum = {'sayi': 0}

    def iptal():
        durum['sayi'] += 1
        return durum['sayi'] > 3

    sonuc = snapshot.apply(engine, 'tv-1', snap, is_cancelled=iptal)

    assert sonuc['cancelled'] is True
    assert (sonuc['ok'], sonuc['fail']) == (0, 2)
    assert sonuc['details'] == [('com.a', False, 'kullanıcı durdurdu'),
                                ('com.b', False, 'kullanıcı durdurdu')]
    assert engine.durumlar['com.a']['enabled'] is False
    assert engine.durumlar['com.b']['enabled'] is False


def test_apply_islem_hatasi_log_hatasiyla_birlikte(base):
    class HataliMotor(DurumMotoru):
        def enable(self, target, pkg, user_id=0):
            raise AdbError('enable reddedildi')

    engine = HataliMotor({'com.a': {'enabled': False, 'installed_user0': True}})
    snap = _snap({'com.a': _durum(enabled=True)})

    def patlak_log(mesaj):
        raise RuntimeError('log yok')

    sonuc = snapshot.apply(engine, 'tv-1', snap, log=patlak_log)

    assert (sonuc['ok'], sonuc['fail']) == (0, 1)
    assert sonuc['details'] == [('com.a', False, 'enable reddedildi')]


def test_apply_son_dogrulama_iptalinde_kismi_sonuc(base):
    engine = DurumMotoru({'com.a': {'enabled': False, 'installed_user0': True}})
    snap = _snap({'com.a': _durum(enabled=True)})
    durum = {'sayi': 0}

    def iptal():
        durum['sayi'] += 1
        return durum['sayi'] > 4

    sonuc = snapshot.apply(engine, 'tv-1', snap, is_cancelled=iptal)

    assert sonuc['cancelled'] is True
    assert (sonuc['ok'], sonuc['fail']) == (0, 1)
    assert sonuc['details'][0][2] == \
        'Snapshot son durumu eşleşmedi: son durum doğrulanamadı; kullanıcı durdurdu'


def test_apply_son_dogrulama_hatasinda_mesaj(base, monkeypatch):
    engine = DurumMotoru({'com.a': {'enabled': False, 'installed_user0': True}})
    snap = _snap({'com.a': _durum(enabled=True)})
    gercek_diff = snapshot.diff_current
    sayac = {'n': 0}

    def sahte_diff(e, t, s):
        sayac['n'] += 1
        if sayac['n'] == 2:
            raise RuntimeError('okuma çöktü')
        return gercek_diff(e, t, s)

    monkeypatch.setattr(snapshot, 'diff_current', sahte_diff)

    sonuc = snapshot.apply(engine, 'tv-1', snap)

    assert (sonuc['ok'], sonuc['fail']) == (0, 1)
    assert 'son durum doğrulanamadı: okuma çöktü' in sonuc['details'][0][2]
