# -*- coding: utf-8 -*-
"""Stage/snapshot/yedek/tarama worker akislari: iptal, dogrulama, atomik yazma.

Gercek ADB ve gercek ag kullanilmaz: motor, snapshot modulu, gecmis kaydi ve
socket katmani taklit edilir; QThread.start() cagrilmaz, worker.run() senkron
kosulur.
"""
import io
import os
import shutil
import socket
import zipfile

import pytest

from mibox_app.adb_engine import AdbError
from mibox_app.workers import (
    ApkBackupWorker,
    CancelledError,
    NetworkScanWorker,
    SnapshotWorker,
    StageWorker,
)


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
def snapshot_mod(monkeypatch):
    """snapshot modulu take/apply/load cagrilarini kaydeder (validate gercek)."""
    state = {
        'take': lambda engine, target, user_id=0, is_cancelled=None: ('snap-1', 5),
        'take_calls': [],
        'apply': lambda engine, target, snap, **kw: {
            'ok': 0, 'fail': 0, 'cancelled': False, 'details': []},
        'apply_calls': [],
        'load': lambda name: None,
        'load_calls': [],
    }

    def take(engine, target, user_id=0, is_cancelled=None):
        state['take_calls'].append((target, user_id))
        return state['take'](engine, target, user_id=user_id,
                             is_cancelled=is_cancelled)

    def apply(engine, target, snap, protected=(), log=None, progress=None,
              is_cancelled=None):
        state['apply_calls'].append((target, snap, frozenset(protected)))
        return state['apply'](engine, target, snap, protected=protected,
                              log=log, progress=progress,
                              is_cancelled=is_cancelled)

    def load(name):
        state['load_calls'].append(name)
        return state['load'](name)

    monkeypatch.setattr('mibox_app.snapshot.take', take)
    monkeypatch.setattr('mibox_app.snapshot.apply', apply)
    monkeypatch.setattr('mibox_app.snapshot.load', load)
    return state


@pytest.fixture
def history(monkeypatch):
    calls = []

    def append_many(target, action, details, user_id=0):
        calls.append((target, action, details, user_id))
        return True

    monkeypatch.setattr('mibox_app.history.append_many', append_many)
    return calls


def _snap_verisi(user_id=0):
    return {
        'created': '2026-01-01 00:00:00',
        'target': 'tv-1',
        'user_id': user_id,
        'packages': {
            'com.a': {'enabled': True, 'installed_user0': True,
                      'restricted': False},
        },
    }


class StageEngine:
    """StageWorker'in user kapsamli motor API'sini taklit eder."""

    def __init__(self):
        self.calls = []
        self.disabled = set()
        self.uninstalled = set()
        self.smart_result = ('disable', None)

    def connect(self, target, cancel_check=None):
        self.calls.append(('connect', target))

    def invalidate_pkg_cache(self, target):
        self.calls.append(('invalidate_pkg_cache', target))

    def disable_user(self, target, pkg, user_id=0):
        self.calls.append(('disable_user', pkg, user_id))
        self.disabled.add(pkg)

    def enable(self, target, pkg, user_id=0):
        self.calls.append(('enable', pkg, user_id))
        self.disabled.discard(pkg)

    def uninstall_user(self, target, pkg, user_id=0):
        self.calls.append(('uninstall_user', pkg, user_id))
        self.uninstalled.add(pkg)

    def install_existing(self, target, pkg, user_id=0):
        self.calls.append(('install_existing', pkg, user_id))
        self.uninstalled.discard(pkg)

    def force_stop(self, target, pkg, user_id=0):
        self.calls.append(('force_stop', pkg, user_id))

    def clear_data(self, target, pkg, user_id=0):
        self.calls.append(('clear_data', pkg, user_id))

    def restrict(self, target, pkg, user_id=0):
        self.calls.append(('restrict', pkg, user_id))

    def unrestrict(self, target, pkg, user_id=0):
        self.calls.append(('unrestrict', pkg, user_id))

    def smart_remove(self, target, pkg, user_id=0):
        self.calls.append(('smart_remove', pkg, user_id))
        return self.smart_result

    def is_disabled(self, target, pkg, user_id=0):
        return pkg in self.disabled

    def is_uninstalled_for_user(self, target, pkg, user_id=0):
        return pkg in self.uninstalled


# --- SnapshotWorker ----------------------------------------------------------

def test_snapshot_take_modu(snapshot_mod):
    worker = SnapshotWorker(StageEngine(), 'tv-1', 'take')
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok == {'name': 'snap-1', 'count': 5, 'user_id': 0}
    assert snapshot_mod['take_calls'] == [('tv-1', 0)]


def test_snapshot_apply_gecmis_kaydeder(snapshot_mod, history):
    data = _snap_verisi()
    snapshot_mod['apply'] = lambda engine, target, snap, **kw: {
        'ok': 1, 'fail': 0, 'cancelled': False,
        'details': [('com.a', True, 'enable uygulandı')]}
    worker = SnapshotWorker(StageEngine(), 'tv-1', 'apply',
                            snapshot_data=data, protected=('com.x',))
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['ok'] == 1 and ok['user_id'] == 0
    assert history == [('tv-1', 'snapshot',
                        [('com.a', True, 'enable uygulandı')], 0)]
    assert snapshot_mod['apply_calls'][0][0] == 'tv-1'
    assert snapshot_mod['apply_calls'][0][2] == frozenset({'com.x'})


def test_snapshot_apply_addan_yukler(snapshot_mod, history):
    snapshot_mod['load'] = lambda name: _snap_verisi()
    worker = SnapshotWorker(StageEngine(), 'tv-1', 'apply',
                            snapshot_name='mibox-snapshot-a.json')
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert snapshot_mod['load_calls'] == ['mibox-snapshot-a.json']
    assert snapshot_mod['apply_calls'][0][1]['packages']


def test_snapshot_apply_user_uyusmazligi(snapshot_mod, history):
    worker = SnapshotWorker(StageEngine(), 'tv-1', 'apply',
                            snapshot_data=_snap_verisi(user_id=1), user_id=0)
    ok, fail, logs, progress = _run(worker)

    assert ok is None
    assert 'uygulanmadı' in fail
    assert snapshot_mod['apply_calls'] == []


def test_snapshot_apply_iptal_logu(snapshot_mod, history):
    snapshot_mod['apply'] = lambda engine, target, snap, **kw: {
        'ok': 1, 'fail': 0, 'cancelled': True,
        'details': [('com.a', True, 'enable uygulandı')]}
    worker = SnapshotWorker(StageEngine(), 'tv-1', 'apply',
                            snapshot_data=_snap_verisi())
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['cancelled'] is True
    assert any('tamamlanan ayrıntıların geçmişi kaydedildi' in line
               for line in logs)


def test_snapshot_apply_gecmis_kaydedilemezse_log(snapshot_mod, monkeypatch):
    monkeypatch.setattr('mibox_app.history.append_many', lambda *a, **k: False)
    worker = SnapshotWorker(StageEngine(), 'tv-1', 'apply',
                            snapshot_data=_snap_verisi())
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert any('geçmişi kaydedilemedi' in line for line in logs)


def test_snapshot_apply_gecmis_hatasi_loglanir(snapshot_mod, monkeypatch):
    def patla(*a, **k):
        raise OSError('gecmis dosyasi kilitli')

    monkeypatch.setattr('mibox_app.history.append_many', patla)
    worker = SnapshotWorker(StageEngine(), 'tv-1', 'apply',
                            snapshot_data=_snap_verisi())
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert any('işlem geçmişi kaydedilemedi: gecmis dosyasi kilitli' in line
               for line in logs)


def test_snapshot_bilinmeyen_mod(snapshot_mod):
    worker = SnapshotWorker(StageEngine(), 'tv-1', 'foo')
    ok, fail, logs, progress = _run(worker)

    assert ok is None
    assert fail == 'Bilinmeyen snapshot işlemi: foo'


def test_snapshot_gecersiz_veri_insada_reddedilir(snapshot_mod):
    with pytest.raises(ValueError):
        SnapshotWorker(StageEngine(), 'tv-1', 'apply',
                       snapshot_data={'bozuk': True})


def test_snapshot_verisi_kopyalanir(snapshot_mod, history):
    data = _snap_verisi()
    worker = SnapshotWorker(StageEngine(), 'tv-1', 'apply', snapshot_data=data)
    data['packages'].clear()
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert 'com.a' in snapshot_mod['apply_calls'][0][1]['packages']


# --- StageWorker -------------------------------------------------------------

def test_stage_user0_run_stage_kullanir(monkeypatch):
    captured = {}

    def fake_run_stage(engine, target, stage, protected=(), log=None,
                       progress=None, is_cancelled=None):
        captured['items'] = stage.items()
        captured['target'] = target
        captured['protected'] = protected
        captured['is_cancelled'] = is_cancelled
        return {'ok': 2, 'fail': 0, 'details': [], 'failed_items': [],
                'action': 'stage', 'auto_snap': 'snap-0'}

    monkeypatch.setattr('mibox_app.stage.run_stage', fake_run_stage)
    worker = StageWorker(StageEngine(), 'tv-1',
                         [('disable', 'com.a'), ('stop', 'com.b')],
                         protected=('com.z',))
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['ok'] == 2 and ok['user_id'] == 0
    assert captured['items'] == [('disable', 'com.a'), ('stop', 'com.b')]
    assert captured['target'] == 'tv-1'
    assert captured['protected'] == ('com.z',)
    assert callable(captured['is_cancelled'])


def test_stage_userN_akisi(snapshot_mod, history):
    snapshot_mod['take'] = lambda engine, target, user_id=0, is_cancelled=None: \
        ('snap-u', 3)
    engine = StageEngine()
    worker = StageWorker(engine, 'tv-1',
                         [('disable', 'com.a'), ('stop', 'com.b')], user_id=2)
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['ok'] == 2 and ok['fail'] == 0
    assert ok['auto_snap'] == 'snap-u'
    assert ok['user_id'] == 2
    assert ok['failed_items'] == []
    assert ok['details'][0][0] == 'com.a' and ok['details'][0][1] is True
    assert 'doğrulandı' in ok['details'][0][2]
    assert ok['details'][1][1] is True
    assert ('disable_user', 'com.a', 2) in engine.calls
    assert ('force_stop', 'com.b', 2) in engine.calls
    assert history == [('tv-1', 'stage',
                        [('disable', 'com.a', True, ok['details'][0][2]),
                         ('stop', 'com.b', True, ok['details'][1][2])], 2)]
    assert snapshot_mod['take_calls'] == [('tv-1', 2)]
    assert any('User 2 için paket durumu snapshot' in line for line in logs)
    assert progress == [(1, 2), (2, 2)]


def test_stage_userN_smart_aksiyonu(snapshot_mod, history):
    engine = StageEngine()
    engine.smart_result = ('disable', None)
    worker = StageWorker(engine, 'tv-1', [('smart', 'com.a')], user_id=3)
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['ok'] == 1
    assert ok['details'][0][2] == \
        'Akıllı kaldırma: devre dışı bırakıldı ve doğrulandı'
    assert history[0][2] == [('disable', 'com.a', True, ok['details'][0][2])]


def test_stage_userN_snapshot_alinamazsa_riskli_islem_yapilmaz(snapshot_mod,
                                                              history):
    def patla(engine, target, user_id=0, is_cancelled=None):
        raise AdbError('snapshot yok')

    snapshot_mod['take'] = patla
    engine = StageEngine()
    worker = StageWorker(engine, 'tv-1',
                         [('disable', 'com.a'), ('stop', 'com.b')], user_id=2)
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['ok'] == 1 and ok['fail'] == 1
    assert ok['details'][0][1] is False
    assert 'snapshot' in ok['details'][0][2]
    assert ok['details'][1][1] is True  # stop snapshot gerektirmez
    assert any('alınamadı' in line for line in logs)
    assert ('disable_user', 'com.a', 2) not in engine.calls


def test_stage_userN_korunan_paket(snapshot_mod, history):
    engine = StageEngine()
    worker = StageWorker(engine, 'tv-1', [('disable', 'com.a')],
                         protected={'com.a'}, user_id=1)
    ok, fail, logs, progress = _run(worker)

    assert ok['details'][0] == ('com.a', False, 'koruma listesinde')
    assert ('disable_user', 'com.a', 1) not in engine.calls


def test_stage_userN_dogrulama_basarisiz(snapshot_mod, history):
    engine = StageEngine()

    def noop(target, pkg, user_id=0):
        engine.calls.append(('disable_user', pkg, user_id))

    engine.disable_user = noop
    worker = StageWorker(engine, 'tv-1', [('disable', 'com.a')], user_id=1)
    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 0 and ok['fail'] == 1
    assert 'doğrulama başarısız: hala aktif' in ok['details'][0][2]
    assert ok['failed_items'] == [('disable', 'com.a')]
    assert any('com.a disable:' in line for line in logs)


def test_stage_userN_bilinmeyen_aksiyon(snapshot_mod, history):
    engine = StageEngine()
    worker = StageWorker(engine, 'tv-1', [('foo', 'com.a')], user_id=1)
    ok, fail, logs, progress = _run(worker)

    assert ok['details'][0] == ('com.a', False, 'bilinmeyen aksiyon: foo')


def test_stage_userN_iptal(snapshot_mod, history):
    engine = StageEngine()
    worker = StageWorker(engine, 'tv-1',
                         [('stop', 'com.a'), ('stop', 'com.b')], user_id=1)
    original = engine.force_stop

    def stop(target, pkg, user_id=0):
        original(target, pkg, user_id=user_id)
        worker.cancel()

    engine.force_stop = stop
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['ok'] == 1 and ok['fail'] == 1
    assert ok['details'][1] == ('com.b', False, 'kullanıcı durdurdu')


def test_stage_userN_baglanti_hatasi_erken_doner(snapshot_mod, history):
    engine = StageEngine()

    def kotu_connect(target, cancel_check=None):
        raise AdbError('cihaz bagli degil')

    engine.connect = kotu_connect
    worker = StageWorker(engine, 'tv-1', [('disable', 'com.a')], user_id=1)
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['ok'] == 0 and ok['fail'] == 1
    assert ok['details'] == [('com.a', False, 'cihaz bagli degil')]
    assert ok['failed_items'] == [('disable', 'com.a')]
    assert ok['auto_snap'] is None and ok['user_id'] == 1
    assert history == []
    assert snapshot_mod['take_calls'] == []


def test_stage_userN_snapshot_iptali_durduruldu(snapshot_mod, history):
    def patla(engine, target, user_id=0, is_cancelled=None):
        raise CancelledError('durduruldu')

    snapshot_mod['take'] = patla
    engine = StageEngine()
    worker = StageWorker(engine, 'tv-1', [('disable', 'com.a')], user_id=2)

    ok, fail, logs, progress = _run(worker)

    assert ok is None
    assert fail == 'kullanıcı durdurdu'
    assert ('disable_user', 'com.a', 2) not in engine.calls


def test_stage_userN_uninstall_dogrulama_basarisiz(snapshot_mod, history):
    engine = StageEngine()

    def noop_uninstall(target, pkg, user_id=0):
        engine.calls.append(('uninstall_user', pkg, user_id))

    engine.uninstall_user = noop_uninstall
    worker = StageWorker(engine, 'tv-1', [('uninstall', 'com.a')], user_id=1)
    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 0 and ok['fail'] == 1
    assert 'doğrulama başarısız: hala kurulu' in ok['details'][0][2]
    assert ok['failed_items'] == [('uninstall', 'com.a')]


def test_stage_userN_eylem_yollari(snapshot_mod, history):
    engine = StageEngine()
    items = [('enable', 'com.a'), ('restore', 'com.b'), ('restrict', 'com.c'),
             ('unrestrict', 'com.d'), ('clear', 'com.e')]
    worker = StageWorker(engine, 'tv-1', items, user_id=1)
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['ok'] == 5 and ok['fail'] == 0
    assert ('enable', 'com.a', 1) in engine.calls
    assert ('install_existing', 'com.b', 1) in engine.calls
    assert ('restrict', 'com.c', 1) in engine.calls
    assert ('unrestrict', 'com.d', 1) in engine.calls
    assert ('clear_data', 'com.e', 1) in engine.calls


def test_stage_userN_smart_uninstall_ve_beklenmeyen(snapshot_mod, history):
    engine = StageEngine()
    engine.smart_result = ('uninstall', None)
    worker = StageWorker(engine, 'tv-1', [('smart', 'com.a')], user_id=3)
    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 1
    assert ok['details'][0][2] == \
        'Akıllı kaldırma: kullanıcı için kaldırıldı ve doğrulandı'
    assert history[0][2] == [('uninstall', 'com.a', True,
                              ok['details'][0][2])]

    engine.smart_result = ('weird', None)
    worker2 = StageWorker(engine, 'tv-1', [('smart', 'com.b')], user_id=3)
    ok2, fail2, logs2, progress2 = _run(worker2)

    assert ok2['ok'] == 0 and ok2['fail'] == 1
    assert 'beklenmeyen yöntem' in ok2['details'][0][2]


def test_stage_userN_gecmis_hatasi_loglanir(snapshot_mod, monkeypatch):
    def patla(*args, **kwargs):
        raise OSError('gecmis yazilamadi')

    monkeypatch.setattr('mibox_app.history.append_many', patla)
    engine = StageEngine()
    worker = StageWorker(engine, 'tv-1', [('stop', 'com.a')], user_id=1)
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert any('User 1 işlem geçmişi kaydedilemedi' in line for line in logs)


def test_stage_userN_onbellek_hatasi_yutulur(snapshot_mod, history):
    engine = StageEngine()

    def patlak_onbellek(target):
        raise RuntimeError('onbellek yok')

    engine.invalidate_pkg_cache = patlak_onbellek
    worker = StageWorker(engine, 'tv-1', [('stop', 'com.a')], user_id=1)
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['ok'] == 1


# --- ApkBackupWorker ---------------------------------------------------------

class BackupEngine:
    """pm_paths/pull API'sini taklit eder; pull gecici dosyaya bayt yazar."""

    def __init__(self):
        self.calls = []
        self.paths = {}
        self.blob = b''
        self.pull_error = {}

    def connect(self, target, cancel_check=None):
        self.calls.append(('connect', target))

    def pm_paths(self, target, pkg):
        self.calls.append(('pm_paths', pkg))
        return list(self.paths.get(pkg, []))

    def pull(self, target, remote, local, cancel_check=None):
        self.calls.append(('pull', remote, local))
        if remote in self.pull_error:
            raise self.pull_error[remote]
        with open(local, 'wb') as f:
            f.write(self.blob)


def _apk_bytes(entries=('AndroidManifest.xml',)):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name in entries:
            z.writestr(name, b'<manifest/>')
    return buf.getvalue()


def _gecici_artik(dest):
    return [n for n in os.listdir(dest) if n.startswith('.mibox-')]


def test_apk_yedek_tek_dosya(tmp_path):
    engine = BackupEngine()
    engine.blob = _apk_bytes()
    engine.paths = {'com.a': ['/data/app/~~x/com.a/base.apk']}
    dest = str(tmp_path / 'yedek')
    worker = ApkBackupWorker(engine, 'tv-1', ['com.a'], dest)
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok == {'ok': 1, 'fail': 0, 'cancelled': 0,
                  'details': [('com.a', True, 'yedeklendi')]}
    target = os.path.join(dest, 'com.a.apk')
    assert os.path.isfile(target)
    with open(target, 'rb') as f:
        assert f.read() == engine.blob
    assert _gecici_artik(dest) == []


def test_apk_yedek_split_set(tmp_path):
    engine = BackupEngine()
    engine.blob = _apk_bytes()
    engine.paths = {'com.a': ['/data/app/~~x/com.a/base.apk',
                              '/data/app/~~x/com.a/split_config.arm64_v8a.apk',
                              '/data/app/~~x/com.a/split_config.xxhdpi.apk']}
    dest = str(tmp_path / 'yedek')
    worker = ApkBackupWorker(engine, 'tv-1', ['com.a'], dest)
    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 1
    pkgdir = os.path.join(dest, 'com.a')
    assert sorted(os.listdir(pkgdir)) == ['base.apk', 'split_001.apk',
                                          'split_002.apk']
    assert _gecici_artik(dest) == []


def test_apk_yedek_eski_split_dizini_degistirilir(tmp_path):
    engine = BackupEngine()
    engine.blob = _apk_bytes()
    engine.paths = {'com.a': ['/data/app/~~x/com.a/base.apk',
                              '/data/app/~~x/com.a/split_config.arm64_v8a.apk']}
    dest = tmp_path / 'yedek'
    pkgdir = dest / 'com.a'
    pkgdir.mkdir(parents=True)
    (pkgdir / 'eski.apk').write_bytes(b'eski')
    worker = ApkBackupWorker(engine, 'tv-1', ['com.a'], str(dest))
    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 1
    assert sorted(os.listdir(pkgdir)) == ['base.apk', 'split_001.apk']
    assert _gecici_artik(str(dest)) == []


def test_apk_dogrulama_bos_manifest(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('AndroidManifest.xml', b'')
    apk = tmp_path / 'bos.apk'
    apk.write_bytes(buf.getvalue())
    worker = ApkBackupWorker(BackupEngine(), 'tv-1', [], str(tmp_path))

    with pytest.raises(AdbError) as excinfo:
        worker._validate_staged_apk(str(apk))

    assert 'boş bir AndroidManifest.xml' in str(excinfo.value)


def test_apk_dogrulama_klasor_uyesi_atlanir(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('AndroidManifest.xml', b'<manifest/>')
        z.writestr('META-INF/', b'')
        z.writestr('classes.dex', b'dex')
    apk = tmp_path / 'tam.apk'
    apk.write_bytes(buf.getvalue())
    worker = ApkBackupWorker(BackupEngine(), 'tv-1', [], str(tmp_path))

    worker._validate_staged_apk(str(apk))  # klasor uyesi atlanir; hata yok


def test_apk_yedek_mevcut_dosya_uzerine_yazmaz(tmp_path):
    engine = BackupEngine()
    engine.blob = _apk_bytes()
    dest = tmp_path / 'yedek'
    dest.mkdir()
    pkgdir = dest / 'com.a'
    pkgdir.write_bytes(b'eski dosya')  # dizin beklenirken dosya
    worker = ApkBackupWorker(engine, 'tv-1', [], str(dest))

    with pytest.raises(AdbError) as excinfo:
        worker._pull_split_set(['/data/app/~~x/com.a/base.apk'],
                               str(pkgdir), 'com.a')

    assert 'güvenli biçimde değiştirilemiyor' in str(excinfo.value)
    assert pkgdir.read_bytes() == b'eski dosya'
    assert _gecici_artik(str(dest)) == []


def test_apk_yedek_replace_hatasinda_eski_dizin_geri_gelir(tmp_path,
                                                           monkeypatch):
    engine = BackupEngine()
    engine.blob = _apk_bytes()
    engine.paths = {'com.a': ['/data/app/~~x/com.a/base.apk',
                              '/data/app/~~x/com.a/split_config.arm64_v8a.apk']}
    dest = tmp_path / 'yedek'
    pkgdir = dest / 'com.a'
    pkgdir.mkdir(parents=True)
    (pkgdir / 'eski.apk').write_bytes(b'eski')

    gercek_replace = os.replace
    sayac = {'n': 0}

    def sahte_replace(src, dst):
        sayac['n'] += 1
        if sayac['n'] == 2:
            raise OSError('yerleştirilemedi')
        return gercek_replace(src, dst)

    monkeypatch.setattr(os, 'replace', sahte_replace)
    worker = ApkBackupWorker(engine, 'tv-1', ['com.a'], str(dest))
    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 0 and ok['fail'] == 1
    assert ok['details'][0] == ('com.a', False, 'yerleştirilemedi')
    assert (pkgdir / 'eski.apk').read_bytes() == b'eski'
    assert _gecici_artik(str(dest)) == []


def test_apk_yedek_geri_alma_da_basarisizsa_eski_yedek_korunur(tmp_path,
                                                               monkeypatch):
    engine = BackupEngine()
    engine.blob = _apk_bytes()
    engine.paths = {'com.a': ['/data/app/~~x/com.a/base.apk',
                              '/data/app/~~x/com.a/split_config.arm64_v8a.apk']}
    dest = tmp_path / 'yedek'
    pkgdir = dest / 'com.a'
    pkgdir.mkdir(parents=True)
    (pkgdir / 'eski.apk').write_bytes(b'eski')

    gercek_replace = os.replace
    sayac = {'n': 0}

    def sahte_replace(src, dst):
        sayac['n'] += 1
        if sayac['n'] >= 2:
            raise OSError('yerleştirilemedi')
        return gercek_replace(src, dst)

    monkeypatch.setattr(os, 'replace', sahte_replace)
    worker = ApkBackupWorker(engine, 'tv-1', ['com.a'], str(dest))
    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 0 and ok['fail'] == 1
    assert 'korundu' in ok['details'][0][2]
    artiklar = _gecici_artik(str(dest))
    assert len(artiklar) == 1 and artiklar[0].startswith('.mibox-old-')
    assert (dest / artiklar[0] / 'eski.apk').read_bytes() == b'eski'


def test_apk_yedek_eski_dizin_temizlenemezse_loglanir(tmp_path, monkeypatch):
    engine = BackupEngine()
    engine.blob = _apk_bytes()
    engine.paths = {'com.a': ['/data/app/~~x/com.a/base.apk',
                              '/data/app/~~x/com.a/split_config.arm64_v8a.apk']}
    dest = tmp_path / 'yedek'
    pkgdir = dest / 'com.a'
    pkgdir.mkdir(parents=True)
    (pkgdir / 'eski.apk').write_bytes(b'eski')

    gercek_rmtree = shutil.rmtree

    def sahte_rmtree(path, ignore_errors=False):
        if '.mibox-old-' in str(path):
            raise OSError('silinemez')
        return gercek_rmtree(path, ignore_errors=ignore_errors)

    monkeypatch.setattr(shutil, 'rmtree', sahte_rmtree)
    worker = ApkBackupWorker(engine, 'tv-1', ['com.a'], str(dest))
    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 1
    assert sorted(os.listdir(pkgdir)) == ['base.apk', 'split_001.apk']
    assert any('temizlenemedi' in line for line in logs)


def test_apk_yedek_dongu_iptali_kalanlari_isaretler(tmp_path):
    engine = BackupEngine()
    engine.blob = _apk_bytes()
    engine.paths = {'com.a': ['/data/app/com.a/base.apk'],
                    'com.b': ['/data/app/com.b/base.apk']}
    worker = ApkBackupWorker(engine, 'tv-1', ['com.a', 'com.b'],
                             str(tmp_path / 'y'))
    sayac = {'n': 0}

    def kontrol():
        sayac['n'] += 1
        return sayac['n'] >= 4

    worker.isInterruptionRequested = kontrol
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['ok'] == 0 and ok['cancelled'] == 2
    assert ok['details'] == [('com.a', False, 'kullanıcı durdurdu'),
                             ('com.b', False, 'kullanıcı durdurdu')]
    assert any('yedeklenmedi (kullanıcı durdurdu)' in line for line in logs)
    assert progress == [(1, 2), (2, 2)]


def test_apk_yedek_hata_iptalle_kesisirse_durduruldu(tmp_path):
    engine = BackupEngine()
    worker = ApkBackupWorker(engine, 'tv-1', ['com.a b'], str(tmp_path / 'y'))
    sayac = {'n': 0}

    def kontrol():
        sayac['n'] += 1
        return sayac['n'] >= 5

    worker.isInterruptionRequested = kontrol
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['ok'] == 0 and ok['cancelled'] == 1
    assert ok['details'] == [('com.a b', False, 'kullanıcı durdurdu')]
    assert ('pm_paths', 'com.a b') not in engine.calls


def test_apk_yedek_bozuk_zip_reddedilir(tmp_path):
    engine = BackupEngine()
    engine.blob = b'bu bir apk degil'
    engine.paths = {'com.a': ['/data/app/com.a/base.apk']}
    dest = str(tmp_path / 'yedek')
    worker = ApkBackupWorker(engine, 'tv-1', ['com.a'], dest)
    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 0 and ok['fail'] == 1
    assert 'ZIP arşivi değil' in ok['details'][0][2]
    assert not os.path.exists(os.path.join(dest, 'com.a.apk'))
    assert _gecici_artik(dest) == []


def test_apk_yedek_bos_dosya_reddedilir(tmp_path):
    engine = BackupEngine()
    engine.blob = b''
    engine.paths = {'com.a': ['/data/app/com.a/base.apk']}
    dest = str(tmp_path / 'yedek')
    worker = ApkBackupWorker(engine, 'tv-1', ['com.a'], dest)
    ok, fail, logs, progress = _run(worker)

    assert 'boş veya geçersiz' in ok['details'][0][2]
    assert not os.path.exists(os.path.join(dest, 'com.a.apk'))


def test_apk_yedek_manifest_yoksa_reddedilir(tmp_path):
    engine = BackupEngine()
    engine.blob = _apk_bytes(entries=('classes.dex',))
    engine.paths = {'com.a': ['/data/app/com.a/base.apk']}
    worker = ApkBackupWorker(engine, 'tv-1', ['com.a'], str(tmp_path / 'y'))
    ok, fail, logs, progress = _run(worker)

    assert 'AndroidManifest.xml bulunamadı' in ok['details'][0][2]


def test_apk_yedek_yol_yoksa_atlanir(tmp_path):
    engine = BackupEngine()
    engine.paths = {'com.a': []}
    worker = ApkBackupWorker(engine, 'tv-1', ['com.a'], str(tmp_path / 'y'))
    ok, fail, logs, progress = _run(worker)

    assert ok['fail'] == 1
    assert ok['details'][0] == ('com.a', False, 'APK yolu bulunamadı.')
    assert any('APK yolu bulunamadı' in line for line in logs)


def test_apk_yedek_tekrarli_yol_reddedilir(tmp_path):
    engine = BackupEngine()
    engine.paths = {'com.a': ['/data/app/com.a/base.apk',
                              '/data/app/com.a/base.apk']}
    worker = ApkBackupWorker(engine, 'tv-1', ['com.a'], str(tmp_path / 'y'))
    ok, fail, logs, progress = _run(worker)

    assert 'tekrarlanan APK yolları' in ok['details'][0][2]


def test_apk_yedek_gecersiz_paket_adi(tmp_path):
    engine = BackupEngine()
    worker = ApkBackupWorker(engine, 'tv-1', ['com.a b'], str(tmp_path / 'y'))
    ok, fail, logs, progress = _run(worker)

    assert ok['details'][0] == ('com.a b', False,
                                "Geçersiz paket adı: 'com.a b'")
    assert ('pm_paths', 'com.a b') not in engine.calls


def test_apk_yolu_dogrulama_gecer():
    path = ApkBackupWorker._validated_remote_apk_path(
        '/data/app/~~x/com.a/base.apk')
    assert path == '/data/app/~~x/com.a/base.apk'


@pytest.mark.parametrize('raw', [
    'data/app/com.a/base.apk',      # mutlak degil
    'C:\\data\\com.a\\base.apk',    # ters bolu
    '/data/app/com.a/base',         # .apk degil
    '/data/app/com.a/.apk',         # yalniz uzanti
    '/data/app/com.a/ba:d.apk',     # yasak karakter
])
def test_apk_yolu_dogrulama_reddeder(raw):
    with pytest.raises(AdbError):
        ApkBackupWorker._validated_remote_apk_path(raw)


def test_apk_yedek_pull_hatasi(tmp_path):
    engine = BackupEngine()
    engine.paths = {'com.a': ['/data/app/com.a/base.apk']}
    engine.pull_error = {'/data/app/com.a/base.apk': OSError('disk dolu')}
    worker = ApkBackupWorker(engine, 'tv-1', ['com.a'], str(tmp_path / 'y'))
    ok, fail, logs, progress = _run(worker)

    assert ok['details'][0] == ('com.a', False, 'disk dolu')
    assert any('com.a: disk dolu' in line for line in logs)


def test_apk_yedek_pull_iptali(tmp_path):
    engine = BackupEngine()
    engine.paths = {'com.a': ['/data/app/com.a/base.apk']}
    worker = ApkBackupWorker(engine, 'tv-1', ['com.a'], str(tmp_path / 'y'))

    def pull(target, remote, local, cancel_check=None):
        worker.cancel()
        with open(local, 'wb') as f:
            f.write(_apk_bytes())

    engine.pull = pull
    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 0 and ok['cancelled'] == 1
    assert ok['details'][0] == ('com.a', False, 'kullanıcı durdurdu')
    assert any('yedekleme kullanıcı tarafından durduruldu' in line
               for line in logs)


def test_apk_yedek_iptal_kalanlari_isaretler(tmp_path):
    engine = BackupEngine()
    engine.blob = _apk_bytes()
    engine.paths = {'com.a': ['/data/app/com.a/base.apk'],
                    'com.b': ['/data/app/com.b/base.apk']}
    worker = ApkBackupWorker(engine, 'tv-1', ['com.a', 'com.b'],
                             str(tmp_path / 'y'))
    original = engine.pm_paths

    def pm_paths(target, pkg):
        if pkg == 'com.b':
            worker.cancel()
        return original(target, pkg)

    engine.pm_paths = pm_paths
    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 1 and ok['cancelled'] == 1
    assert ok['details'][1] == ('com.b', False, 'kullanıcı durdurdu')
    assert any('yedeklenmedi (kullanıcı durdurdu)' in line for line in logs)


# --- NetworkScanWorker -------------------------------------------------------

class _FakeSocket:
    """Gercek ag kullanilmaz: connect_ex yalniz secili adres icin 0 doner."""

    acik = {('192.168.1.5', 5555)}

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def settimeout(self, timeout):
        pass

    def connect_ex(self, addr):
        return 0 if addr in self.acik else 111


def test_network_scan_gecerli_kurulum():
    worker = NetworkScanWorker('192.168.1.', 10, 20, 5555, max_workers=8)
    assert (worker.prefix, worker.start_ip, worker.end_ip,
            worker.port, worker.total) == ('192.168.1.', 10, 20, 5555, 11)
    assert worker.max_workers == 8


def test_network_scan_worker_sayisi_sinirlanir():
    assert NetworkScanWorker('192.168.1.', 1, 2, 5555,
                             max_workers=0).max_workers == 1
    assert NetworkScanWorker('192.168.1.', 1, 2, 5555,
                             max_workers=999).max_workers == 128


@pytest.mark.parametrize('kwargs', [
    dict(prefix='192.168.1', start=1, end=10, port=5555),    # nokta yok
    dict(prefix='abc.', start=1, end=10, port=5555),         # harf
    dict(prefix='999.1.1.', start=1, end=10, port=5555),     # gecersiz IP
    dict(prefix='192.168.1.', start=0, end=10, port=5555),   # baslangic 0
    dict(prefix='192.168.1.', start=1, end=255, port=5555),  # bitis 255
    dict(prefix='192.168.1.', start=20, end=10, port=5555),  # ters aralik
    dict(prefix='192.168.1.', start=1, end=10, port=0),      # port 0
    dict(prefix='192.168.1.', start=1, end=10, port=70000),  # port sinir
])
def test_network_scan_gecersiz_kurulum(kwargs):
    with pytest.raises(ValueError):
        NetworkScanWorker(**kwargs)


def test_network_scan_acik_cihazi_bulur(monkeypatch):
    monkeypatch.setattr(socket, 'socket', _FakeSocket)
    worker = NetworkScanWorker('192.168.1.', 1, 6, 5555, max_workers=2)
    signals = []
    worker.device_found.connect(
        lambda ip, durum, gecikme: signals.append((ip, durum, gecikme)))
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert len(ok) == 1
    ip, durum, gecikme = ok[0]
    assert (ip, durum) == ('192.168.1.5', 'Açık')
    assert gecikme.isdigit()
    assert signals == ok
    assert len(progress) == 6
    assert progress[-1] == (6, 6)


def test_network_scan_kapali_ag_bos_doner(monkeypatch):
    class _Kapali(_FakeSocket):
        acik = set()

    monkeypatch.setattr(socket, 'socket', _Kapali)
    worker = NetworkScanWorker('192.168.1.', 1, 4, 5555)
    ok, fail, logs, progress = _run(worker)

    assert fail is None and ok == []
    assert progress[-1] == (4, 4)


def test_network_scan_tarama_sirasinda_iptal(monkeypatch):
    kutu = {}

    class _Iptal(_FakeSocket):
        acik = set()

        def connect_ex(self, addr):
            kutu['worker'].cancel()
            return 111

    monkeypatch.setattr(socket, 'socket', _Iptal)
    worker = NetworkScanWorker('192.168.1.', 1, 6, 5555, max_workers=1)
    kutu['worker'] = worker
    ok, fail, logs, progress = _run(worker)

    assert ok is None
    assert fail == 'kullanıcı durdurdu'


def test_network_scan_iptal_probe_atlar():
    worker = NetworkScanWorker('192.168.1.', 1, 2, 5555)
    worker.isInterruptionRequested = lambda: True

    with pytest.raises(CancelledError):
        worker._work()


def test_network_scan_soket_hatasi_yutulur(monkeypatch):
    class _PatlakSocket:
        def __init__(self, *args, **kwargs):
            raise OSError('soket yok')

    monkeypatch.setattr(socket, 'socket', _PatlakSocket)
    worker = NetworkScanWorker('192.168.1.', 1, 3, 5555)
    ok, fail, logs, progress = _run(worker)

    assert fail is None and ok == []
    assert progress[-1] == (3, 3)
