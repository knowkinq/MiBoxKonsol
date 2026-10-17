# -*- coding: utf-8 -*-
"""Core testleri: motor tembel kurulumu, hedef/bağlantı sinyalleri, iz aktarımı.

Gerçek ADB ve ayar dosyası kullanılmaz: AdbEngine ve Config taklit edilir.
"""
import pytest

from mibox_app.adb_engine import AdbError
from mibox_app.core import Core


class FakeConfig:
    def __init__(self, on_persistence_error=None):
        self.on_persistence_error = on_persistence_error
        self.last_target = 'tv-eski'
        self.saved = 0

    def save(self):
        self.saved += 1


class FakeEngine:
    def __init__(self, trace_cb=None):
        self.trace_cb = trace_cb
        self.adb_path = 'C:\\platform-tools\\adb.exe'
        self.calls = []

    def connect(self, target, timeout=30):
        self.calls.append(('connect', target, timeout))

    def disconnect(self, target):
        self.calls.append(('disconnect', target))


@pytest.fixture
def core(monkeypatch):
    monkeypatch.setattr('mibox_app.core.Config', FakeConfig)
    monkeypatch.setattr('mibox_app.core.AdbEngine', FakeEngine)
    return Core()


def test_core_baslangic(core):
    assert core.target == 'tv-eski'
    assert core.connected is False
    assert core.engine_error is None
    assert core.adb_path == 'C:\\platform-tools\\adb.exe'
    assert core.engine is not None
    assert core.engine.trace_cb == core._on_adb_trace


def test_core_engine_sonradan_kurulur(monkeypatch):
    class KotuEngine:
        def __init__(self, trace_cb=None):
            raise AdbError('adb yok')

    monkeypatch.setattr('mibox_app.core.Config', FakeConfig)
    monkeypatch.setattr('mibox_app.core.AdbEngine', KotuEngine)
    core = Core()

    assert core.engine_error == 'adb yok'
    assert core.adb_path is None
    with pytest.raises(AdbError):
        core.engine

    # ADB sonradan kuruldu: ilk erisimde yeniden denenir ve hata temizlenir.
    monkeypatch.setattr('mibox_app.core.AdbEngine', FakeEngine)
    engine = core.engine
    assert isinstance(engine, FakeEngine)
    assert core.engine_error is None
    assert core.engine is engine


def test_core_engine_trace_onarilir(core):
    engine = core.engine
    engine.trace_cb = None
    assert core.engine is engine
    assert engine.trace_cb == core._on_adb_trace


def test_core_trace_onarimi_hatasi_yutulur(core, monkeypatch):
    class SessizEngine:
        @property
        def trace_cb(self):
            return None

        @trace_cb.setter
        def trace_cb(self, value):
            raise RuntimeError('atama yasak')

    fake = SessizEngine()
    monkeypatch.setattr(core, '_engine', fake)

    assert core.engine is fake


def test_core_adb_trace_donusum_hatasi_yutulur(core):
    # Sinyal argumani hazirlanamazsa iz aktarimi sessizce yutulmali.
    class KotuKomut:
        def __iter__(self):
            raise RuntimeError('komut bozuk')

    core._on_adb_trace(KotuKomut(), True, 5, '')


def test_core_set_target_sinyal_ve_kayit(core):
    signals = []
    core.connection_changed.connect(lambda ok, t: signals.append((ok, t)))
    core.connected = True

    core.set_target('tv-yeni')
    assert core.target == 'tv-yeni'
    assert core.config.last_target == 'tv-yeni'
    assert core.config.saved == 1
    assert core.connected is False
    assert signals == [(False, 'tv-yeni')]

    core.set_target('tv-yeni')  # ayni hedef: sinyal yok, kayit surer
    assert signals == [(False, 'tv-yeni')]
    assert core.config.saved == 2


def test_core_connect_ve_disconnect(core):
    signals = []
    logs = []
    core.connection_changed.connect(lambda ok, t: signals.append((ok, t)))
    core.log.connect(lambda m, lvl: logs.append((m, lvl)))

    core.connect()
    engine = core.engine
    assert core.connected is True
    assert engine.calls[-1] == ('connect', 'tv-eski', 30)
    assert signals == [(True, 'tv-eski')]

    core.connect('tv-hedef', timeout=5)
    assert engine.calls[-1] == ('connect', 'tv-hedef', 5)

    core.disconnect()
    assert core.connected is False
    assert engine.calls[-1] == ('disconnect', 'tv-eski')
    assert signals[-1] == (False, 'tv-eski')
    assert logs[-2][0] == 'Baglanti kuruldu'
    assert logs[-1][0] == 'Bağlantı kesildi'


def test_core_disconnect_hedef_degistiyse_sinyal_yok(core):
    core.connect()
    engine = core.engine
    signals = []
    core.connection_changed.connect(lambda ok, t: signals.append((ok, t)))

    def dis(target):
        engine.calls.append(('disconnect', target))
        core.set_target('tv-baska')  # yeniden giris: hedef arada degisti

    engine.disconnect = dis
    core.disconnect()

    assert engine.calls[-1] == ('disconnect', 'tv-eski')
    assert core.connected is False
    assert signals == [(False, 'tv-baska')]  # yalniz set_target sinyali


def test_core_adb_trace_sinyali(core):
    events = []
    core.adb_trace.connect(
        lambda cmd, ok, ms, err, probe: events.append((cmd, ok, ms, err, probe)))

    core._on_adb_trace(('shell', 'getprop'), 1, 12.7, 'hata', True)

    assert events == [(['shell', 'getprop'], True, 12, 'hata', True)]


def test_core_log_msg_seviyesi(core):
    logs = []
    core.log.connect(lambda m, lvl: logs.append((m, lvl)))

    core.log_msg('deneme')
    core.log_msg('uyarı', 'WARN')

    assert logs == [('deneme', 'INFO'), ('uyarı', 'WARN')]


def test_core_persistence_error_sinyali(core):
    errors = []
    core.persistence_error.connect(errors.append)

    core.config.on_persistence_error('diske yazilamadi')

    assert errors == ['diske yazilamadi']
