# -*- coding: utf-8 -*-
"""Worker akis testleri: mutasyon, koruma, dogrulama ve iptal yollari.

Gercek ADB kullanilmaz: motor taklit edilir. QThread.start() cagrilmaz;
worker.run() senkron kosulur ve sinyaller lambda'lara baglanarak yakalanir.
snapshot.take ve history.append_many taklit edilir; diske hicbir sey
yazilmaz.
"""
import pytest

from mibox_app.adb_engine import AdbError
from mibox_app.workers import CancelledError, PackageActionWorker, SmartRemoveWorker


class StubEngine:
    """Worker'larin cagirdigi motor API'sini taklit eder."""

    def __init__(self):
        self.calls = []
        self.disabled = set()
        self.uninstalled = set()
        self.restricted = set()
        self.smart_result = {}
        self.smart_error = {}
        self.full_uninstall_error = {}
        # False: disable_user 'basarili' doner ama durum degismez (yalanci motor).
        self.disable_ok = True

    def connect(self, target, cancel_check=None):
        self.calls.append(('connect', target))

    def invalidate_pkg_cache(self, target):
        self.calls.append(('invalidate_pkg_cache', target))

    def force_stop(self, target, pkg, user_id=0):
        self.calls.append(('force_stop', pkg, user_id))

    def clear_data(self, target, pkg, user_id=0):
        self.calls.append(('clear_data', pkg, user_id))

    def enable(self, target, pkg, user_id=0):
        self.calls.append(('enable', pkg, user_id))
        self.disabled.discard(pkg)

    def disable_user(self, target, pkg, user_id=0):
        self.calls.append(('disable_user', pkg, user_id))
        if self.disable_ok:
            self.disabled.add(pkg)

    def uninstall_user(self, target, pkg, user_id=0):
        self.calls.append(('uninstall_user', pkg, user_id))
        self.uninstalled.add(pkg)

    def uninstall_package_full(self, target, pkg, cancel_check=None):
        self.calls.append(('uninstall_package_full', pkg))
        if cancel_check is not None:
            cancel_check()
        if pkg in self.full_uninstall_error:
            raise self.full_uninstall_error[pkg]

    def install_existing(self, target, pkg, user_id=0):
        self.calls.append(('install_existing', pkg, user_id))
        self.uninstalled.discard(pkg)

    def launch_resolved(self, target, pkg, timeout=15, user_id=0):
        self.calls.append(('launch_resolved', pkg, user_id))

    def restrict(self, target, pkg, user_id=0):
        self.calls.append(('restrict', pkg, user_id))
        self.restricted.add(pkg)

    def unrestrict(self, target, pkg, user_id=0):
        self.calls.append(('unrestrict', pkg, user_id))
        self.restricted.discard(pkg)

    def is_disabled(self, target, pkg, user_id=0):
        return pkg in self.disabled

    def is_uninstalled_for_user(self, target, pkg, user_id=0):
        return pkg in self.uninstalled

    def bulk_restricted(self, target, user_id=0):
        return set(self.restricted)

    def smart_remove(self, target, pkg, user_id=0):
        self.calls.append(('smart_remove', pkg, user_id))
        if pkg in self.smart_error:
            raise self.smart_error[pkg]
        return self.smart_result.get(pkg, ('disable', None))


class OwnerAdapterEngine:
    """Eski Owner adaptoru: user_id parametresi yok; user 0 icin calismali."""

    def __init__(self):
        self.calls = []

    def connect(self, target, cancel_check=None):
        self.calls.append(('connect', target))

    def invalidate_pkg_cache(self, target):
        self.calls.append(('invalidate_pkg_cache', target))

    def disable_user(self, target, pkg):
        self.calls.append(('disable_user', pkg))

    def force_stop(self, target, pkg):
        self.calls.append(('force_stop', pkg))

    def is_disabled(self, target, pkg):
        return True


class OwnerOnlyEngine:
    """user_id parametresi sunmayan motor: user != 0 icin islem reddedilmeli."""

    def disable_user(self, target, pkg):
        raise AssertionError('bu motor icin cagrilmamaliydi')

    def force_stop(self, target, pkg):
        raise AssertionError('bu motor icin cagrilmamaliydi')

    def is_disabled(self, target, pkg):
        return True


def _run(worker):
    """worker.run()'u senkron kosar; (sonuc, hata, loglar, ilerleme) doner."""
    box = {'ok': None, 'fail': None}
    logs = []
    progress = []
    worker.finished_ok.connect(lambda r: box.__setitem__('ok', r))
    worker.failed.connect(lambda e: box.__setitem__('fail', e))
    worker.log.connect(logs.append)
    worker.progress.connect(lambda i, t: progress.append((i, t)))
    worker.run()
    return box['ok'], box['fail'], logs, progress


@pytest.fixture
def snapshots(monkeypatch):
    calls = []

    def take(engine, target, user_id=0, is_cancelled=None):
        calls.append((target, user_id))
        return 'snap-1', 5

    monkeypatch.setattr('mibox_app.snapshot.take', take)
    return calls


@pytest.fixture
def history(monkeypatch):
    calls = []

    def append_many(target, action, details, user_id=0):
        calls.append((target, action, details, user_id))

    monkeypatch.setattr('mibox_app.history.append_many', append_many)
    return calls


# --- PackageActionWorker -----------------------------------------------------

def test_disable_akisi_dogrulanir(snapshots, history):
    engine = StubEngine()
    worker = PackageActionWorker(engine, 'tv-1', ['com.foo'], 'disable', protected=())

    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['ok'] == 1 and ok['fail'] == 0
    assert ok['details'] == [('com.foo', True, 'tamam (dogrulandi)')]
    assert ok['auto_snap'] == 'snap-1'
    assert engine.disabled == {'com.foo'}
    assert snapshots == [('tv-1', 0)]
    assert history == [('tv-1', 'disable', ok['details'], 0)]
    assert progress == [(1, 1)]
    assert any('snapshot' in line for line in logs)


def test_korunan_paket_islem_gorrmez(snapshots, history):
    engine = StubEngine()
    worker = PackageActionWorker(engine, 'tv-1', ['com.foo'], 'disable',
                                 protected={'com.foo'})

    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 0 and ok['fail'] == 1
    assert ok['details'] == [('com.foo', False, 'koruma listesinde')]
    assert engine.disabled == set()
    assert not any(c[0] == 'disable_user' for c in engine.calls)


def test_stop_koruma_listesini_yok_sayar(snapshots, history):
    # 'stop' zararsizdir: korumali paket de durdurulabilir.
    engine = StubEngine()
    worker = PackageActionWorker(engine, 'tv-1', ['com.foo'], 'stop',
                                 protected={'com.foo'})

    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 1
    assert ('force_stop', 'com.foo', 0) in engine.calls


def test_dogrulama_basarisizsa_paket_basarisiz_sayilir(snapshots, history):
    engine = StubEngine()
    engine.disable_ok = False  # motor 'basarili' dedi ama durum degismedi
    worker = PackageActionWorker(engine, 'tv-1', ['com.foo'], 'disable', protected=())

    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 0 and ok['fail'] == 1
    pkg, good, message = ok['details'][0]
    assert not good
    assert 'Doğrulama başarısız' in message


def test_snapshot_alinamazsa_disable_yapilmaz(monkeypatch, history):
    def take(engine, target, user_id=0, is_cancelled=None):
        raise AdbError('snapshot yazilamadi')

    monkeypatch.setattr('mibox_app.snapshot.take', take)
    engine = StubEngine()
    worker = PackageActionWorker(engine, 'tv-1', ['com.foo'], 'disable', protected=())

    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 0 and ok['fail'] == 1
    assert ok['auto_snap'] is None
    assert ok['details'] == [
        ('com.foo', False, "paket durumu snapshot'ı alınamadı; işlem yapılmadı")]
    assert engine.disabled == set()
    assert any('alınamadı' in line for line in logs)


def test_clear_snapshot_almaz(snapshots, history):
    engine = StubEngine()
    worker = PackageActionWorker(engine, 'tv-1', ['com.foo'], 'clear', protected=())

    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 1 and ok['auto_snap'] is None
    assert snapshots == []
    assert ('clear_data', 'com.foo', 0) in engine.calls


def test_coklu_paket_ilerleme_bildirir(snapshots, history):
    engine = StubEngine()
    worker = PackageActionWorker(
        engine, 'tv-1', ['com.a', 'com.b', 'com.c'], 'disable',
        protected={'com.b'})

    ok, fail, logs, progress = _run(worker)

    assert (ok['ok'], ok['fail']) == (2, 1)
    assert progress == [(1, 3), (2, 3), (3, 3)]
    assert engine.disabled == {'com.a', 'com.c'}


def test_iptal_dongude_kalan_paketleri_atlar(snapshots, history):
    engine = StubEngine()
    worker = PackageActionWorker(engine, 'tv-1', ['com.a', 'com.b'], 'disable',
                                 protected=())
    original_disable = engine.disable_user

    def disable_then_cancel(target, pkg, user_id=0):
        original_disable(target, pkg, user_id=user_id)
        if pkg == 'com.a':
            worker.cancel()

    engine.disable_user = disable_then_cancel

    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 1 and ok['fail'] == 1 and ok['cancelled'] == 1
    assert ok['details'][1] == ('com.b', False, 'kullanıcı durdurdu')
    assert any('islenmedi' in line for line in logs)


def test_iptal_edilmis_worker_hic_baslamaz(snapshots, history):
    engine = StubEngine()
    worker = PackageActionWorker(engine, 'tv-1', ['com.a'], 'disable', protected=())
    worker.cancel()

    ok, fail, logs, progress = _run(worker)

    assert ok is None
    assert fail == 'kullanıcı durdurdu'
    assert engine.calls == []
    assert any('durduruldu' in line for line in logs)


def test_user_scope_desteklenmezse_islem_yapilmaz(history):
    engine = OwnerOnlyEngine()
    worker = PackageActionWorker(engine, 'tv-1', ['com.foo'], 'disable',
                                 protected=(), user_id=1)

    ok, fail, logs, progress = _run(worker)

    assert ok is None
    assert 'user_id desteği sunmuyor' in fail


def test_user_0_eski_adaptorlerle_calisir(snapshots, history):
    engine = OwnerAdapterEngine()
    worker = PackageActionWorker(engine, 'tv-1', ['com.foo'], 'disable', protected=())

    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 1
    assert ('disable_user', 'com.foo') in engine.calls


def test_snapshot_iptali_durduruldu_olarak_doner(monkeypatch, history):
    def take(engine, target, user_id=0, is_cancelled=None):
        raise CancelledError('durduruldu')

    monkeypatch.setattr('mibox_app.snapshot.take', take)
    engine = StubEngine()
    worker = PackageActionWorker(engine, 'tv-1', ['com.foo'], 'disable',
                                 protected=())

    ok, fail, logs, progress = _run(worker)

    assert ok is None
    assert fail == 'kullanıcı durdurdu'
    assert engine.disabled == set()


def test_tam_kaldirma_global_api_ve_geri_alinamaz_gecmis(snapshots, history):
    engine = StubEngine()
    worker = PackageActionWorker(
        engine, 'tv-1', ['com.foo'], 'uninstall', protected=(),
        full_uninstall=True)

    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['ok'] == 1 and ok['fail'] == 0
    assert ok['action'] == 'uninstall_full'
    assert ok['details'] == [(
        'com.foo', True,
        'tam kaldırma tamamlandı; tüm Android kullanıcılarının uygulama verisi silindi')]
    assert ('uninstall_package_full', 'com.foo') in engine.calls
    assert not any(call[0] == 'uninstall_user' for call in engine.calls)
    assert snapshots == [('tv-1', 0)]
    assert history == [('tv-1', 'uninstall_full', ok['details'], 0)]


def test_normal_uninstall_user_scope_olarak_kalir(snapshots, history):
    engine = StubEngine()
    worker = PackageActionWorker(
        engine, 'tv-1', ['com.foo'], 'uninstall', protected=())

    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 1 and ok['action'] == 'uninstall'
    assert ('uninstall_user', 'com.foo', 0) in engine.calls
    assert not any(call[0] == 'uninstall_package_full' for call in engine.calls)
    assert history == [('tv-1', 'uninstall', ok['details'], 0)]


def test_tam_kaldirma_korunan_pakete_dokunmaz(snapshots, history):
    engine = StubEngine()
    worker = PackageActionWorker(
        engine, 'tv-1', ['com.foo'], 'uninstall', protected={'com.foo'},
        full_uninstall=True)

    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 0 and ok['fail'] == 1
    assert ok['details'] == [('com.foo', False, 'koruma listesinde')]
    assert not any(call[0] == 'uninstall_package_full' for call in engine.calls)


def test_tam_kaldirma_snapshot_yoksa_mutasyon_yapmaz(monkeypatch, history):
    def take(engine, target, user_id=0, is_cancelled=None):
        raise AdbError('snapshot yazilamadi')

    monkeypatch.setattr('mibox_app.snapshot.take', take)
    engine = StubEngine()
    worker = PackageActionWorker(
        engine, 'tv-1', ['com.foo'], 'uninstall', protected=(),
        full_uninstall=True)

    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 0 and ok['fail'] == 1
    assert ok['auto_snap'] is None
    assert not any(call[0] == 'uninstall_package_full' for call in engine.calls)
    assert history == [('tv-1', 'uninstall_full', ok['details'], 0)]


def test_tam_kaldirma_user0_disinda_connect_etmeden_reddedilir(history):
    engine = StubEngine()
    worker = PackageActionWorker(
        engine, 'tv-1', ['com.foo'], 'uninstall', protected=(), user_id=1,
        full_uninstall=True)

    ok, fail, logs, progress = _run(worker)

    assert ok is None
    assert 'yalnız user 0' in fail
    assert engine.calls == []
    assert history == []


def test_tam_kaldirma_iptal_edilen_paketi_belirsiz_durumla_kaydeder(
        snapshots, history):
    engine = StubEngine()
    engine.full_uninstall_error['com.foo'] = CancelledError('kullanıcı durdurdu')
    worker = PackageActionWorker(
        engine, 'tv-1', ['com.foo'], 'uninstall', protected=(),
        full_uninstall=True)

    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 0 and ok['fail'] == 1 and ok['cancelled'] == 1
    assert fail is None
    assert ok['details'] == [(
        'com.foo', False,
        'işlem iptal edildi; paket durumu değişmiş olabilir')]
    assert history == [('tv-1', 'uninstall_full', ok['details'], 0)]


def test_tam_kaldirma_ikinci_pakette_iptal_kismi_sonucu_kaydeder(
        snapshots, history):
    engine = StubEngine()
    engine.full_uninstall_error['com.b'] = CancelledError('kullanıcı durdurdu')
    worker = PackageActionWorker(
        engine, 'tv-1', ['com.a', 'com.b', 'com.c'], 'uninstall', protected=(),
        full_uninstall=True)

    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['ok'] == 1 and ok['fail'] == 2 and ok['cancelled'] == 2
    assert ok['action'] == 'uninstall_full'
    assert ok['details'] == [
        ('com.a', True,
         'tam kaldırma tamamlandı; tüm Android kullanıcılarının uygulama verisi silindi'),
        ('com.b', False,
         'işlem iptal edildi; paket durumu değişmiş olabilir'),
        ('com.c', False, 'kullanıcı durdurdu'),
    ]
    assert [call[1] for call in engine.calls
            if call[0] == 'uninstall_package_full'] == ['com.a', 'com.b']
    assert history == [('tv-1', 'uninstall_full', ok['details'], 0)]


def test_tam_kaldirma_motor_hatasi_basarisiz_kaydeder(snapshots, history):
    engine = StubEngine()
    engine.full_uninstall_error['com.foo'] = AdbError('global paket kaydi kaldi')
    worker = PackageActionWorker(
        engine, 'tv-1', ['com.foo'], 'uninstall', protected=(),
        full_uninstall=True)

    ok, fail, logs, progress = _run(worker)

    assert fail is None and ok['ok'] == 0 and ok['fail'] == 1
    assert ok['details'] == [('com.foo', False, 'global paket kaydi kaldi')]
    assert history == [('tv-1', 'uninstall_full', ok['details'], 0)]


def test_paket_eylemi_dogru_motor_metodunu_cagirir():
    engine = StubEngine()
    worker = PackageActionWorker(engine, 'tv-1', ['com.foo'], 'enable',
                                 protected=())

    beklenen = {
        'enable': 'enable',
        'uninstall': 'uninstall_user',
        'restore': 'install_existing',
        'launch': 'launch_resolved',
        'restrict': 'restrict',
        'unrestrict': 'unrestrict',
    }
    for action, method in beklenen.items():
        worker._action = action
        worker._do('com.foo')
        assert engine.calls[-1][0] == method

    worker._action = 'hayali'
    with pytest.raises(AdbError) as excinfo:
        worker._do('com.foo')
    assert 'Bilinmeyen paket işlemi: hayali' in str(excinfo.value)


def test_dogrulama_hatalari_detayli_mesaj_verir():
    engine = StubEngine()
    worker = PackageActionWorker(engine, 'tv-1', ['com.foo'], 'uninstall',
                                 protected=())

    worker._action = 'uninstall'
    with pytest.raises(AdbError) as excinfo:
        worker._verify('com.foo')
    assert 'hala kurulu' in str(excinfo.value)

    engine.uninstalled.add('com.foo')
    worker._action = 'restore'
    with pytest.raises(AdbError) as excinfo:
        worker._verify('com.foo')
    assert 'geri gelmedi' in str(excinfo.value)

    engine.disabled.add('com.foo')
    worker._action = 'enable'
    with pytest.raises(AdbError) as excinfo:
        worker._verify('com.foo')
    assert 'hala devre dışı' in str(excinfo.value)


def test_dogrulama_arka_plan_durumu():
    engine = StubEngine()
    worker = PackageActionWorker(engine, 'tv-1', ['com.foo'], 'restrict',
                                 protected=())

    worker._action = 'restrict'
    with pytest.raises(AdbError) as excinfo:
        worker._verify('com.foo')
    assert 'arka plan durumu değişmedi' in str(excinfo.value)

    engine.restricted.add('com.foo')
    worker._action = 'unrestrict'
    with pytest.raises(AdbError) as excinfo:
        worker._verify('com.foo')
    assert 'arka plan durumu değişmedi' in str(excinfo.value)

    class OkunamazEngine(StubEngine):
        def bulk_restricted(self, target, user_id=0):
            return 'liste'

    okunamaz = PackageActionWorker(OkunamazEngine(), 'tv-1', ['com.foo'],
                                   'restrict', protected=())
    okunamaz._action = 'restrict'
    with pytest.raises(AdbError) as excinfo:
        okunamaz._verify('com.foo')
    assert 'okunamadı' in str(excinfo.value)


def test_dogrulama_bilinmeyen_eylem_reddedilir():
    engine = StubEngine()
    worker = PackageActionWorker(engine, 'tv-1', ['com.foo'], 'enable',
                                 protected=())

    worker._action = 'hayali'
    with pytest.raises(AdbError) as excinfo:
        worker._verify('com.foo')
    assert 'Bilinmeyen paket işlemi: hayali' in str(excinfo.value)


def test_bilinmeyen_eylem_insa_sonrasi_reddedilir():
    engine = StubEngine()
    worker = PackageActionWorker(engine, 'tv-1', ['com.foo'], 'hayali',
                                 protected=())

    ok, fail, logs, progress = _run(worker)

    assert ok is None
    assert fail == 'Bilinmeyen paket işlemi: hayali'
    assert engine.calls == []


def test_gecmis_ve_onbellek_hatalari_yutulur(monkeypatch):
    def patlak_gecmis(*args, **kwargs):
        raise OSError('gecmis yazilamadi')

    monkeypatch.setattr('mibox_app.history.append_many', patlak_gecmis)
    engine = StubEngine()

    def patlak_onbellek(target):
        raise RuntimeError('onbellek yok')

    engine.invalidate_pkg_cache = patlak_onbellek
    worker = PackageActionWorker(engine, 'tv-1', ['com.foo'], 'stop',
                                 protected=(), user_id=2)

    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['ok'] == 1
    assert any('User 2 işlem geçmişi kaydedilemedi' in line for line in logs)


# --- SmartRemoveWorker -------------------------------------------------------

def test_smart_disable_ile_kapatir(snapshots, history):
    engine = StubEngine()
    worker = SmartRemoveWorker(engine, 'tv-1', ['com.a'], protected=())

    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 1 and ok['fail'] == 0
    assert ok['details'] == [('com.a', True, 'disable ile kapatildi (güvenli)')]
    assert ok['action'] == 'smart'
    assert history == [('tv-1', 'smart', ok['details'], 0)]


def test_smart_uninstall_yolunu_isaretler(snapshots, history):
    engine = StubEngine()
    engine.smart_result['com.a'] = ('uninstall', None)
    worker = SmartRemoveWorker(engine, 'tv-1', ['com.a'], protected=())

    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 1
    assert ok['details'] == [('com.a', True, 'uninstall ile kaldırıldı')]


def test_smart_hata_detayda_gorunur(snapshots, history):
    engine = StubEngine()
    engine.smart_error['com.a'] = AdbError('cihaz reddetti')
    worker = SmartRemoveWorker(engine, 'tv-1', ['com.a'], protected=())

    ok, fail, logs, progress = _run(worker)

    assert ok['fail'] == 1
    assert ok['details'] == [('com.a', False, 'cihaz reddetti')]


def test_smart_korunan_pakete_dokunmaz(snapshots, history):
    engine = StubEngine()
    worker = SmartRemoveWorker(engine, 'tv-1', ['com.a'], protected={'com.a'})

    ok, fail, logs, progress = _run(worker)

    assert ok['fail'] == 1
    assert ok['details'] == [('com.a', False, 'koruma listesinde')]
    assert not any(c[0] == 'smart_remove' for c in engine.calls)


def test_smart_snapshot_alinamazsa_dokunmaz(monkeypatch, history):
    def take(engine, target, user_id=0, is_cancelled=None):
        raise AdbError('snapshot yok')

    monkeypatch.setattr('mibox_app.snapshot.take', take)
    engine = StubEngine()
    worker = SmartRemoveWorker(engine, 'tv-1', ['com.a'], protected=())

    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 0 and ok['fail'] == 1
    assert not any(c[0] == 'smart_remove' for c in engine.calls)


def test_smart_snapshot_iptali_durduruldu_olarak_doner(monkeypatch, history):
    def take(engine, target, user_id=0, is_cancelled=None):
        raise CancelledError('durduruldu')

    monkeypatch.setattr('mibox_app.snapshot.take', take)
    engine = StubEngine()
    worker = SmartRemoveWorker(engine, 'tv-1', ['com.a'], protected=())

    ok, fail, logs, progress = _run(worker)

    assert ok is None
    assert fail == 'kullanıcı durdurdu'
    assert not any(c[0] == 'smart_remove' for c in engine.calls)


def test_smart_dongu_iptali_kalanlari_isaretler(history):
    engine = StubEngine()
    worker = SmartRemoveWorker(engine, 'tv-1', ['com.a', 'com.b'],
                               protected=(), auto_snapshot=False)
    sayac = {'n': 0}

    def kontrol():
        sayac['n'] += 1
        return sayac['n'] >= 4

    worker.isInterruptionRequested = kontrol
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['ok'] == 0 and ok['fail'] == 2 and ok['cancelled'] == 2
    assert ok['details'] == [('com.a', False, 'kullanıcı durdurdu'),
                             ('com.b', False, 'kullanıcı durdurdu')]
    assert any('islenmedi' in line for line in logs)
    assert progress == [(1, 2), (2, 2)]


def test_smart_gecmis_ve_onbellek_hatalari_yutulur(monkeypatch, snapshots):
    def patlak_gecmis(*args, **kwargs):
        raise OSError('gecmis yazilamadi')

    monkeypatch.setattr('mibox_app.history.append_many', patlak_gecmis)
    engine = StubEngine()

    def patlak_onbellek(target):
        raise RuntimeError('onbellek yok')

    engine.invalidate_pkg_cache = patlak_onbellek
    worker = SmartRemoveWorker(engine, 'tv-1', ['com.a'], protected=(),
                               user_id=2)

    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['ok'] == 1
    assert any('User 2 işlem geçmişi kaydedilemedi' in line for line in logs)
