# -*- coding: utf-8 -*-
"""AdbEngine cekirdek yollari testleri (gercek ADB yok).

Kapsam: AdbResult yardimcilari, _safe_trace_args maskeleme dallari,
_has_opaque_shell_command, __init__ ve find_adb, _trace geri cagrisi
(eski imza ve yutulan hatalar dahil) ve run() alt surec dongusu
(cikti/binary/timeout/iptal/OSError/trace).

run() testlerinde adb_path yerine yerel python yorumlayicisi kullanilir:
alt surecler yalnizca yerel yorumlayicidir; cihaz veya ag yoktur.
"""
import os
import subprocess
import sys
import time

import pytest

from mibox_app.adb_engine import AdbEngine, AdbError, AdbResult


def _py_engine(trace_cb=None):
    return AdbEngine(adb_path=sys.executable, trace_cb=trace_cb)


# --- AdbResult ---------------------------------------------------------------

def test_adb_result_ozellikleri():
    sonuc = AdbResult(0, 'cikti', 'hata')
    assert sonuc.returncode == 0
    assert sonuc.ok is True
    assert str(sonuc) == 'cikti'


def test_adb_result_hata_metni_one_cikar():
    sonuc = AdbResult(1, '', 'hata')
    assert sonuc.ok is False
    assert str(sonuc) == 'hata'


def test_adb_result_bos_str():
    assert str(AdbResult(1, '', '')) == ''


# --- _safe_trace_args --------------------------------------------------------

def test_safe_trace_args_serial_maskelenir():
    eng = AdbEngine(adb_path='fake-adb')
    shown, private = eng._safe_trace_args(['-s', 'R58M12345', 'get-state'])
    assert shown == ['-s', '******', 'get-state']
    assert 'R58M12345' in private


def test_safe_trace_args_host_maskelenir():
    eng = AdbEngine(adb_path='fake-adb')
    shown, private = eng._safe_trace_args(
        ['-H', '10.0.0.9', '-P', '5037', 'devices'])
    assert shown == ['-H', '******', '-P', '5037', 'devices']
    assert '10.0.0.9' in private


def test_safe_trace_args_t_degeri_eklenmez():
    eng = AdbEngine(adb_path='fake-adb')
    shown, private = eng._safe_trace_args(['-t', '1', 'devices'])
    assert shown == ['-t', '******', 'devices']
    assert private == ['1']


def test_safe_trace_args_pair():
    eng = AdbEngine(adb_path='fake-adb')
    shown, private = eng._safe_trace_args(
        ['pair', '192.168.1.5:5555', '123456'])
    assert shown == ['pair', '******', '******']
    assert '192.168.1.5:5555' in private
    assert '192.168.1.5' in private
    assert '123456' in private


def test_safe_trace_args_connect_ve_disconnect():
    eng = AdbEngine(adb_path='fake-adb')
    shown, private = eng._safe_trace_args(['connect', '10.0.0.9:5555'])
    assert shown == ['connect', '******']
    assert '10.0.0.9:5555' in private

    shown2, _ = eng._safe_trace_args(['disconnect', '10.0.0.9:5555'])
    assert shown2 == ['disconnect', '******']


def test_safe_trace_args_kisa_shell_komutu():
    eng = AdbEngine(adb_path='fake-adb')
    shown, _ = eng._safe_trace_args(['shell', 'id'])
    assert shown == ['shell', '******']


def test_safe_trace_args_uzun_shell_komutu_gorunur():
    eng = AdbEngine(adb_path='fake-adb')
    shown, _ = eng._safe_trace_args(['shell', 'getprop', 'ro.x'])
    assert shown == ['shell', 'getprop', 'ro.x']


def test_safe_trace_args_shell_gizle_bayragi():
    eng = AdbEngine(adb_path='fake-adb')
    shown, _ = eng._safe_trace_args(
        ['shell', 'am', 'start', 'x'], hide_shell=True)
    assert shown == ['shell', '******', '******', '******']


def test_safe_trace_args_input_text():
    eng = AdbEngine(adb_path='fake-adb')
    shown, _ = eng._safe_trace_args(
        ['shell', 'input', 'text', 'gizli', 'veri'])
    assert shown == ['shell', 'input', 'text', '******', '******']


def test_safe_trace_args_push_pull():
    eng = AdbEngine(adb_path='fake-adb')
    shown, _ = eng._safe_trace_args(['push', 'yerel.txt', 'uzak'])
    assert shown == ['push', '******', '******']

    shown2, _ = eng._safe_trace_args(['pull', '-a', '/sdcard/x'])
    assert shown2 == ['pull', '-a', '******']


def test_safe_trace_args_install():
    eng = AdbEngine(adb_path='fake-adb')
    shown, _ = eng._safe_trace_args(
        ['install', '-r', r'C:\x\uygulama.apk'])
    assert shown == ['install', '-r', '******']

    shown2, _ = eng._safe_trace_args(
        ['install-multiple', 'a.apk', 'b.apks'])
    assert shown2 == ['install-multiple', '******', '******']


def test_safe_trace_args_url_ve_yol():
    eng = AdbEngine(adb_path='fake-adb')
    shown, private = eng._safe_trace_args(['open', 'http://ornek.com/yol'])
    assert shown == ['open', '******']
    assert 'http://ornek.com/yol' in private

    shown2, _ = eng._safe_trace_args(['shell', 'cat', '/sdcard/a.txt'])
    assert shown2 == ['shell', 'cat', '******']

    shown3, _ = eng._safe_trace_args(['exec-out', "'C:/temp/a.txt'"])
    assert shown3 == ['exec-out', '******']


def test_safe_trace_args_zaten_maskeli_atlanir():
    eng = AdbEngine(adb_path='fake-adb')
    shown, private = eng._safe_trace_args(['-s', '******', 'devices'])
    assert shown == ['-s', '******', 'devices']
    # -s dali hedef degerini kosulsuz ozel degerlere ekler; maske zararsizdir.
    assert private == ['******']


# --- _has_opaque_shell_command ----------------------------------------------

def test_opaque_shell_komutu():
    assert AdbEngine._has_opaque_shell_command(['shell', 'x']) is True
    assert AdbEngine._has_opaque_shell_command(
        ['shell', 'x'], hide_shell=True) is True
    assert AdbEngine._has_opaque_shell_command(['shell', 'a', 'b']) is False
    assert AdbEngine._has_opaque_shell_command(['get-state']) is False


# --- __init__ ve find_adb ----------------------------------------------------

def test_init_verilen_yolu_kullanir():
    eng = AdbEngine(adb_path='C:/fake/adb.exe')
    assert eng.adb_path == 'C:/fake/adb.exe'
    assert eng.trace_cb is None
    assert eng.last_home_notes == []


def test_init_adb_bulunamazsa(monkeypatch):
    monkeypatch.setattr(AdbEngine, 'find_adb', staticmethod(lambda: None))
    with pytest.raises(AdbError) as exc:
        AdbEngine()
    assert 'ADB bulunamadı' in str(exc.value)


def test_init_bulunan_yolu_kullanir(monkeypatch):
    monkeypatch.setattr(
        AdbEngine, 'find_adb', staticmethod(lambda: 'C:/bulundu/adb.exe'))
    eng = AdbEngine()
    assert eng.adb_path == 'C:/bulundu/adb.exe'


def test_find_adb_platform_tools(monkeypatch, tmp_path):
    klasor = tmp_path / 'platform-tools'
    klasor.mkdir()
    adb = klasor / 'adb.exe'
    adb.write_bytes(b'x')
    monkeypatch.setattr('mibox_app.adb_engine._base_dir', lambda: str(tmp_path))
    assert AdbEngine.find_adb() == str(adb)


def test_find_adb_platform_tools_posix_adi(monkeypatch, tmp_path):
    klasor = tmp_path / 'platform-tools'
    klasor.mkdir()
    adb = klasor / 'adb'
    adb.write_bytes(b'x')
    monkeypatch.setattr('mibox_app.adb_engine._base_dir', lambda: str(tmp_path))
    assert AdbEngine.find_adb() == str(adb)


def test_find_adb_kok_dizin(monkeypatch, tmp_path):
    adb = tmp_path / 'adb.exe'
    adb.write_bytes(b'x')
    monkeypatch.setattr('mibox_app.adb_engine._base_dir', lambda: str(tmp_path))
    assert AdbEngine.find_adb() == str(adb)


def test_find_adb_path_yedegi(monkeypatch, tmp_path):
    monkeypatch.setattr('mibox_app.adb_engine._base_dir', lambda: str(tmp_path))
    monkeypatch.setattr(
        'shutil.which',
        lambda name: r'C:\pt\adb.exe' if name == 'adb' else None)
    assert AdbEngine.find_adb() == r'C:\pt\adb.exe'


def test_find_adb_bulunamazsa(monkeypatch, tmp_path):
    monkeypatch.setattr('mibox_app.adb_engine._base_dir', lambda: str(tmp_path))
    monkeypatch.setattr('shutil.which', lambda name: None)
    assert AdbEngine.find_adb() is None


# --- _trace ------------------------------------------------------------------

def test_trace_callback_yoksa_sessiz():
    eng = AdbEngine(adb_path='fake-adb')
    eng._trace(['devices'], True, 5)


def test_trace_maskeler_ve_probe_iletir():
    kayit = []
    eng = AdbEngine(adb_path='fake-adb', trace_cb=lambda *a: kayit.append(a))
    eng._trace(['-s', 'SER1', 'get-state'], False, 7, 'SER1 hata', probe=True)
    cmd, ok, ms, err, probe = kayit[0]
    assert cmd == ['-s', '******', 'get-state']
    assert ok is False
    assert ms == 7
    assert err == '****** hata'
    assert probe is True


def test_trace_shell_hatasi_gizlenir():
    kayit = []
    eng = AdbEngine(adb_path='fake-adb', trace_cb=lambda *a: kayit.append(a))
    eng._trace(['shell', 'rm'], False, 3, 'rm: /data/gizli hata',
               hide_shell=True)
    assert kayit[0][3] == 'ADB shell komutu başarısız; içerik gizlendi.'


def test_trace_shell_basarili_bos_mesaj():
    kayit = []
    eng = AdbEngine(adb_path='fake-adb', trace_cb=lambda *a: kayit.append(a))
    eng._trace(['shell', 'id'], True, 3, '', hide_shell=True)
    assert kayit[0][3] == ''


def test_trace_eski_imza_uyumlu():
    kayit = []

    def cb(cmd, ok, ms, err):
        kayit.append((cmd, ok, ms, err))

    eng = AdbEngine(adb_path='fake-adb', trace_cb=cb)
    eng._trace(['devices'], True, 1)
    assert kayit == [(['devices'], True, 1, '')]


def test_trace_callback_hatasi_yutulur():
    def cb(*a):
        raise RuntimeError('trace patladi')

    eng = AdbEngine(adb_path='fake-adb', trace_cb=cb)
    eng._trace(['devices'], True, 1)


# --- run ---------------------------------------------------------------------

def test_run_basarili():
    eng = _py_engine()
    sonuc = eng.run(['-c', 'print("merhaba")'])
    assert sonuc.exit_code == 0
    assert sonuc.output == 'merhaba'
    assert sonuc.error == ''


def test_run_metin_temizligi():
    eng = _py_engine()
    komut = ['-c', 'import sys; sys.stdout.write("  a  ")']
    assert eng.run(komut).output == 'a'
    assert eng.run(komut, preserve_output_whitespace=True).output == '  a  '


def test_run_binary_mod():
    eng = _py_engine()
    komut = ['-c', 'import sys; sys.stdout.buffer.write(bytes([65, 66, 0, '
                  '255])); sys.stderr.write("x")']
    sonuc = eng.run(komut, binary=True)
    assert sonuc.output == b'AB\x00\xff'
    assert sonuc.error == 'x'

    metin = eng.run(komut)
    assert metin.output == 'AB\x00\ufffd'


def test_run_hata_cikis_kodu():
    eng = _py_engine()
    sonuc = eng.run(['-c',
                     'import sys; sys.stderr.write("hata mesaji"); sys.exit(3)'])
    assert sonuc.exit_code == 3
    assert sonuc.error == 'hata mesaji'
    assert sonuc.output == ''


def test_run_zaman_asimi():
    kayit = []
    eng = _py_engine(lambda *a: kayit.append(a))
    baslangic = time.monotonic()
    with pytest.raises(AdbError) as exc:
        eng.run(['-c', 'import time; time.sleep(30)'], timeout=0.5)
    assert 'zaman aşımı' in str(exc.value)
    assert kayit[-1][3] == 'zaman aşımı'
    assert time.monotonic() - baslangic < 15


def test_run_zaman_asimi_cancel_ile():
    eng = _py_engine()
    baslangic = time.monotonic()
    with pytest.raises(AdbError) as exc:
        eng.run(['-c', 'import time; time.sleep(30)'], timeout=0.5,
                cancel_check=lambda: False)
    assert 'zaman aşımı' in str(exc.value)
    assert time.monotonic() - baslangic < 15


def test_run_iptal_baslamadan():
    kayit = []
    eng = _py_engine(lambda *a: kayit.append(a))
    with pytest.raises(AdbError) as exc:
        eng.run(['-c', 'print("x")'], cancel_check=lambda: True)
    assert 'durduruldu' in str(exc.value)
    assert kayit[0][3] == 'kullanıcı durdurdu'


def test_run_iptal_surec_icinde():
    sayac = {'n': 0}

    def iptal():
        sayac['n'] += 1
        return sayac['n'] >= 2

    kayit = []
    eng = _py_engine(lambda *a: kayit.append(a))
    with pytest.raises(AdbError) as exc:
        eng.run(['-c', 'import time; time.sleep(30)'], timeout=30,
                cancel_check=iptal)
    assert 'durduruldu' in str(exc.value)
    assert kayit[-1][3] == 'kullanıcı durdurdu'


def test_run_cancel_ile_basari():
    eng = _py_engine()
    assert eng.run(['-c', 'print("x")'], cancel_check=lambda: False).output \
        == 'x'


def test_run_calistirilamazsa(tmp_path):
    eng = AdbEngine(adb_path=os.path.join(str(tmp_path), 'yok-adb.exe'))
    with pytest.raises(AdbError) as exc:
        eng.run(['devices'])
    assert 'calistirilamadi' in str(exc.value)


def test_run_shell_baslatilamazsa_gizlenir(tmp_path):
    eng = AdbEngine(adb_path=os.path.join(str(tmp_path), 'yok-adb.exe'))
    with pytest.raises(AdbError) as exc:
        eng.run(['shell', 'echo'])
    assert 'içerik gizlendi' in str(exc.value)


def test_run_trace_kaydi():
    kayit = []
    eng = _py_engine(lambda *a: kayit.append(a))
    eng.run(['-c', 'print("merhaba")'])
    cmd, ok, ms, err, probe = kayit[0]
    assert cmd == ['-c', 'print("merhaba")']
    assert ok is True
    assert err == ''
    assert probe is False
    assert isinstance(ms, int)

    eng.run(['-c', 'import sys; sys.exit(2)'])
    assert kayit[-1][1] is False

    eng.run(['-c', 'import sys; sys.exit(2)'], quiet_first=True)
    assert kayit[-1][1] is True
    assert kayit[-1][4] is True
    assert kayit[-1][3] == ''


def test_run_hata_cikti_maskelenir():
    script = 'import sys; sys.stdout.write(sys.argv[1]); sys.exit(1)'
    kayit = []
    eng = _py_engine(lambda *a: kayit.append(a))
    sonuc = eng.run(['-c', script, 'http://gizli.example.com/yol'])
    assert sonuc.output == '******'
    assert kayit[0][0][2] == '******'
    assert kayit[0][3] == '******'


def test_run_basari_cikti_maskelenmez():
    script = 'import sys; sys.stdout.write(sys.argv[1])'
    eng = _py_engine()
    sonuc = eng.run(['-c', script, 'http://gizli.example.com/yol'])
    assert sonuc.output == 'http://gizli.example.com/yol'


def test_run_legacy_trace_imzasi():
    kayit = []

    def cb(cmd, ok, ms, err):
        kayit.append((cmd, ok, ms, err))

    eng = AdbEngine(adb_path=sys.executable, trace_cb=cb)
    eng.run(['-c', 'print("x")'])
    assert kayit[0][1] is True


def test_run_trace_callback_hatasi_yutulur():
    def cb(*a):
        raise RuntimeError('trace patladi')

    eng = AdbEngine(adb_path=sys.executable, trace_cb=cb)
    assert eng.run(['-c', 'print("x")']).exit_code == 0


# --- shell secenekleri --------------------------------------------------------

def test_shell_secenekleri_run_a_iletilir():
    eng = AdbEngine(adb_path='fake-adb')
    kayit = {}

    def sahte_run(args, **kwargs):
        kayit['args'] = args
        kayit['kwargs'] = kwargs
        return AdbResult(0, 'x', '')

    def iptal():
        return False

    eng.run = sahte_run
    eng.shell('tv-1', 'ls', preserve_output_whitespace=True,
              hide_from_trace=True, cancel_check=iptal)
    assert kayit['args'] == ['-s', 'tv-1', 'shell', 'ls']
    assert kayit['kwargs']['preserve_output_whitespace'] is True
    assert kayit['kwargs']['hide_shell_from_trace'] is True
    assert kayit['kwargs']['cancel_check'] is iptal
    assert kayit['kwargs']['quiet_first'] is False

    eng.shell('tv-1', 'getprop', 'ro.x', quiet=True)
    assert kayit['kwargs']['quiet_first'] is True
    assert 'preserve_output_whitespace' not in kayit['kwargs']
    assert 'hide_shell_from_trace' not in kayit['kwargs']
    assert 'cancel_check' not in kayit['kwargs']


# --- run hata yollari (sahte Popen) -------------------------------------------

@pytest.mark.parametrize('slow_termination', [False, True])
def test_run_raising_cancellation_reaps_process(monkeypatch, slow_termination):
    from mibox_app.workers import CancelledError

    calls = []

    class FakeProc:
        def __init__(self, *args, **kwargs):
            calls.append('started')

        def poll(self):
            return None

        def terminate(self):
            calls.append('terminate')

        def kill(self):
            calls.append('kill')

        def communicate(self, timeout=None):
            calls.append(('communicate', timeout))
            if timeout is not None and slow_termination:
                raise subprocess.TimeoutExpired('adb', timeout)
            return b'', b''

    monkeypatch.setattr('mibox_app.adb_engine.subprocess.Popen', FakeProc)
    cancelled = CancelledError('hedef değişti')

    def check_cancel():
        if 'started' in calls:
            raise cancelled

    eng = AdbEngine(adb_path='fake-adb')
    with pytest.raises(CancelledError) as exc:
        eng.run(['shell', 'pm', 'uninstall', 'com.example.app'],
                cancel_check=check_cancel)
    assert exc.value is cancelled
    assert calls[:3] == ['started', 'terminate', ('communicate', 2)]
    if slow_termination:
        assert calls[3:] == ['kill', ('communicate', None)]


def _sahte_popen(monkeypatch, terminate_hata=False, kill_hata=False,
                 communicate_zaman_asimi=False):
    """Popen yerine gecen sahte surec; yalnizca hata dallarini tetikler."""

    class FakeProc:
        def __init__(self, cmd, stdout=None, stderr=None, **kwargs):
            self.cmd = cmd

        def poll(self):
            return None

        def terminate(self):
            if terminate_hata:
                raise OSError('terminate yok')

        def kill(self):
            if kill_hata:
                raise OSError('kill yok')

        def communicate(self, timeout=None):
            if timeout is not None and communicate_zaman_asimi:
                raise subprocess.TimeoutExpired(self.cmd, timeout)
            return b'cikti', b''

    monkeypatch.setattr('mibox_app.adb_engine.subprocess.Popen', FakeProc)


def test_run_iptal_terminate_ve_kill_hata(monkeypatch):
    _sahte_popen(monkeypatch, terminate_hata=True, kill_hata=True)
    sayac = {'n': 0}

    def iptal():
        sayac['n'] += 1
        return sayac['n'] >= 2

    eng = AdbEngine(adb_path='fake-adb')
    with pytest.raises(AdbError) as exc:
        eng.run(['shell', 'ls'], timeout=30, cancel_check=iptal)
    assert 'durduruldu' in str(exc.value)


def test_run_iptal_communicate_zaman_asimi(monkeypatch):
    _sahte_popen(monkeypatch, kill_hata=True, communicate_zaman_asimi=True)
    sayac = {'n': 0}

    def iptal():
        sayac['n'] += 1
        return sayac['n'] >= 2

    eng = AdbEngine(adb_path='fake-adb')
    with pytest.raises(AdbError) as exc:
        eng.run(['shell', 'ls'], timeout=30, cancel_check=iptal)
    assert 'durduruldu' in str(exc.value)


def test_run_zaman_asimi_kill_hata(monkeypatch):
    _sahte_popen(monkeypatch, kill_hata=True, communicate_zaman_asimi=True)
    eng = AdbEngine(adb_path='fake-adb')
    with pytest.raises(AdbError) as exc:
        eng.run(['shell', 'ls'], timeout=0.05, cancel_check=lambda: False)
    assert 'zaman aşımı' in str(exc.value)
