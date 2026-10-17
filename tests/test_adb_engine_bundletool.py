# -*- coding: utf-8 -*-
"""Bundletool ve arsiv kurulum yollari testleri (ADB cihazi yok).

Kapsam: _bundletool_command kesfi, _run_bundletool yerel alt surec dongusu
(gercek python sureci; ag/cihaz yok), is nesnesi yardimcilari, _copy_archive_entry,
_install_apks_archive ve _install_universal_apks yonlendirmeleri,
install_multiple (.apkm/.xapk, liste, dizin) ve install_apks devri.
Alt surecler yalnizca yerel python yorumlayicisidir.
"""
import io
import os
import signal
import subprocess
import sys
import time
import zipfile
from types import SimpleNamespace

import pytest

from mibox_app.adb_engine import AdbEngine, AdbError, AdbResult

# --- _bundletool_command -----------------------------------------------------

def test_bundletool_command_path_uzerinden(monkeypatch):
    monkeypatch.setattr(
        'shutil.which',
        lambda name: r'C:\tools\bundletool.exe' if name == 'bundletool.exe'
        else None)
    eng = AdbEngine(adb_path='fake-adb')
    assert eng._bundletool_command() == [r'C:\tools\bundletool.exe']


def test_bundletool_command_cmd_atlanir(monkeypatch):
    monkeypatch.setattr(
        'shutil.which',
        lambda name: r'C:\tools\bundletool.cmd' if name == 'bundletool'
        else None)
    eng = AdbEngine(adb_path='fake-adb')
    assert eng._bundletool_command() is None


def test_bundletool_command_yoksa_none(monkeypatch):
    monkeypatch.setattr('shutil.which', lambda name: None)
    eng = AdbEngine(adb_path='fake-adb')
    assert eng._bundletool_command() is None


def test_bundletool_command_jar_ile(monkeypatch, tmp_path):
    base = tmp_path / 'kok'
    base.mkdir()
    eski = base / 'bundletool-all-1.0.jar'
    eski.write_bytes(b'x')
    adb_dir = tmp_path / 'tools'
    adb_dir.mkdir()
    yeni = adb_dir / 'bundletool-1.1.jar'
    yeni.write_bytes(b'y')
    os.utime(str(eski), (1000, 1000))
    os.utime(str(yeni), (2000, 2000))

    monkeypatch.setattr(
        'shutil.which',
        lambda name: r'C:\java\bin\java.exe'
        if name in ('java', 'java.exe') else None)
    monkeypatch.setattr('mibox_app.adb_engine._base_dir', lambda: str(base))
    eng = AdbEngine(adb_path=str(adb_dir / 'adb.exe'))
    assert eng._bundletool_command() == [
        r'C:\java\bin\java.exe', '-jar', str(yeni)]


# --- _run_bundletool (gercek yerel alt surec) --------------------------------

def test_run_bundletool_basarili():
    komut = [sys.executable, '-c', 'print("merhaba")']
    result = AdbEngine._run_bundletool(komut, 30, 'test')
    assert result.returncode == 0
    assert 'merhaba' in result.stdout
    assert result.args == komut


def test_run_bundletool_cikis_kodu_ve_stderr():
    komut = [sys.executable, '-c',
             'import sys; sys.stderr.write("hata mesaji"); sys.exit(3)']
    result = AdbEngine._run_bundletool(komut, 30, 'test')
    assert result.returncode == 3
    assert 'hata mesaji' in result.stderr


def test_run_bundletool_cikti_kirpilir():
    komut = [sys.executable, '-c', 'import sys; sys.stdout.write("x" * 200000)']
    result = AdbEngine._run_bundletool(komut, 30, 'test')
    assert result.returncode == 0
    assert len(result.stdout) == 131072
    assert set(result.stdout) == {'x'}


def test_run_bundletool_zaman_asimi():
    baslangic = time.monotonic()
    with pytest.raises(AdbError) as exc:
        AdbEngine._run_bundletool(
            [sys.executable, '-c', 'import time; time.sleep(30)'], 0.6, 'kurulum')
    assert 'zaman aşımına uğradı' in str(exc.value)
    assert 'kurulum' in str(exc.value)
    assert time.monotonic() - baslangic < 15


def test_run_bundletool_baslamadan_iptal():
    def iptal():
        raise AdbError('kullanıcı durdurdu')

    with pytest.raises(AdbError) as exc:
        AdbEngine._run_bundletool(
            [sys.executable, '-c', 'pass'], 5, 'test', iptal)
    assert 'durdurdu' in str(exc.value)


def test_run_bundletool_surec_icinde_iptal():
    cagri = {'n': 0}

    def iptal():
        cagri['n'] += 1
        if cagri['n'] >= 2:
            raise AdbError('kullanıcı durdurdu')

    with pytest.raises(AdbError) as exc:
        AdbEngine._run_bundletool(
            [sys.executable, '-c', 'import time; time.sleep(30)'], 30,
            'test', iptal)
    assert 'durdurdu' in str(exc.value)


def test_run_bundletool_zaman_asimi_yok():
    komut = [sys.executable, '-c', 'print("tamam")']
    result = AdbEngine._run_bundletool(komut, None, 'test')
    assert result.returncode == 0
    assert 'tamam' in result.stdout


def test_run_bundletool_calistirilamazsa():
    with pytest.raises(AdbError) as exc:
        AdbEngine._run_bundletool(
            ['bu-binary-kesinlikle-yok-xyz'], 5, 'test')
    assert 'çalıştırılamadı' in str(exc.value)


def test_run_bundletool_temizlik_zaman_asimi(monkeypatch):
    """Temizlikte wait() iki kez de zaman asimina ugrarsa yutulur."""
    class FakeProc:
        pid = 4242
        returncode = None
        _handle = 0

        def __init__(self, *args, **kwargs):
            pass

        def poll(self):
            return None

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired('bundletool', timeout or 2)

        def kill(self):
            pass

        def terminate(self):
            pass

    sayac = {'n': 0}

    def iptal():
        sayac['n'] += 1
        if sayac['n'] >= 2:
            raise RuntimeError('iptal')

    monkeypatch.setattr('mibox_app.adb_engine.subprocess.Popen', FakeProc)
    monkeypatch.setattr(
        'mibox_app.adb_engine.AdbEngine._create_bundletool_job',
        staticmethod(lambda process: None))
    monkeypatch.setattr(
        'mibox_app.adb_engine.AdbEngine._resume_bundletool_process',
        staticmethod(lambda process: None))
    monkeypatch.setattr('mibox_app.adb_engine.subprocess.run',
                        lambda *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setattr('mibox_app.adb_engine.shutil.which', lambda ad: None)

    with pytest.raises(RuntimeError):
        AdbEngine._run_bundletool(
            [sys.executable, '-c', 'pass'], 5, 'test', iptal)


def test_run_bundletool_posix_oturumda_baslar(monkeypatch):
    kayit = {}

    class FakeProc:
        pid = 1
        returncode = 0
        _handle = 0

        def __init__(self, command, **kwargs):
            kayit['kwargs'] = kwargs

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(os, 'name', 'posix')
    monkeypatch.setattr('mibox_app.adb_engine.subprocess.Popen', FakeProc)
    result = AdbEngine._run_bundletool(
        [sys.executable, '-c', 'pass'], 5, 'test')
    assert kayit['kwargs'].get('start_new_session') is True
    assert 'creationflags' not in kayit['kwargs']
    assert result.returncode == 0


def test_job_yardimcilari_none_ile_guvenli():
    assert AdbEngine._bundletool_job_process_count(None) is None
    AdbEngine._close_bundletool_job(None)


# --- Windows is nesnesi (sahte kernel32) -------------------------------------

class _SahteFonksiyon:
    """ctypes fonksiyon nesnesi gibi davranan sarici (argtypes/restype alir)."""

    def __init__(self, fn):
        self._fn = fn
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self._fn(*args)


def _sahte_kernel32(job_handle=1, set_info_ok=True, assign_ok=True,
                    snapshot=1, thread_first=0, thread_next=0,
                    query_ok=True, terminate_raises=False):
    """ctypes.WinDLL yerine gecen sahte kernel32 katmani."""
    durum = {'close_calls': []}

    def terminate(*a):
        if terminate_raises:
            raise OSError('job yok')
        return 1

    def close(handle):
        durum['close_calls'].append(handle)
        return 1

    kernel32 = SimpleNamespace(
        CreateJobObjectW=_SahteFonksiyon(lambda *a: job_handle),
        SetInformationJobObject=_SahteFonksiyon(
            lambda *a: 1 if set_info_ok else 0),
        AssignProcessToJobObject=_SahteFonksiyon(
            lambda *a: 1 if assign_ok else 0),
        CreateToolhelp32Snapshot=_SahteFonksiyon(lambda *a: snapshot),
        Thread32First=_SahteFonksiyon(lambda *a: thread_first),
        Thread32Next=_SahteFonksiyon(lambda *a: thread_next),
        OpenThread=_SahteFonksiyon(lambda *a: 0),
        ResumeThread=_SahteFonksiyon(lambda *a: 0),
        QueryInformationJobObject=_SahteFonksiyon(
            lambda *a: 1 if query_ok else 0),
        TerminateJobObject=_SahteFonksiyon(terminate),
        CloseHandle=_SahteFonksiyon(close),
    )
    return kernel32, durum


@pytest.mark.skipif(os.name != 'nt', reason='Windows is nesnesi')
def test_create_bundletool_job_olusturulamazsa(monkeypatch):
    kernel32, _ = _sahte_kernel32(job_handle=0)
    monkeypatch.setattr('ctypes.WinDLL', lambda *a, **k: kernel32)
    with pytest.raises(OSError) as exc:
        AdbEngine._create_bundletool_job(SimpleNamespace(_handle=1))
    assert 'oluşturulamadı' in str(exc.value)


@pytest.mark.skipif(os.name != 'nt', reason='Windows is nesnesi')
def test_create_bundletool_job_yapilandirilamazsa(monkeypatch):
    kernel32, durum = _sahte_kernel32(set_info_ok=False)
    monkeypatch.setattr('ctypes.WinDLL', lambda *a, **k: kernel32)
    with pytest.raises(OSError) as exc:
        AdbEngine._create_bundletool_job(SimpleNamespace(_handle=1))
    assert 'yapılandırılamadı' in str(exc.value)
    assert durum['close_calls'] == [1]


@pytest.mark.skipif(os.name != 'nt', reason='Windows is nesnesi')
def test_create_bundletool_job_atanamazsa(monkeypatch):
    kernel32, durum = _sahte_kernel32(assign_ok=False)
    monkeypatch.setattr('ctypes.WinDLL', lambda *a, **k: kernel32)
    with pytest.raises(OSError) as exc:
        AdbEngine._create_bundletool_job(SimpleNamespace(_handle=7))
    assert 'atanamadı' in str(exc.value)
    assert durum['close_calls'] == [1]


@pytest.mark.skipif(os.name != 'nt', reason='Windows is nesnesi')
def test_create_bundletool_job_basarili(monkeypatch):
    kernel32, _ = _sahte_kernel32()
    monkeypatch.setattr('ctypes.WinDLL', lambda *a, **k: kernel32)
    job = AdbEngine._create_bundletool_job(SimpleNamespace(_handle=7))
    assert job[0] is kernel32
    assert job[1] == 1


@pytest.mark.skipif(os.name != 'nt', reason='Windows is nesnesi')
def test_resume_bundletool_process_snapshot_yoksa(monkeypatch):
    kernel32, _ = _sahte_kernel32(snapshot=0)
    monkeypatch.setattr('ctypes.WinDLL', lambda *a, **k: kernel32)
    with pytest.raises(OSError) as exc:
        AdbEngine._resume_bundletool_process(SimpleNamespace(pid=1))
    assert 'bulunamadı' in str(exc.value)


@pytest.mark.skipif(os.name != 'nt', reason='Windows is nesnesi')
def test_resume_bundletool_process_thread_yoksa(monkeypatch):
    kernel32, durum = _sahte_kernel32(thread_first=1, thread_next=0)
    monkeypatch.setattr('ctypes.WinDLL', lambda *a, **k: kernel32)
    with pytest.raises(OSError) as exc:
        AdbEngine._resume_bundletool_process(SimpleNamespace(pid=123))
    assert 'sürdürülemedi' in str(exc.value)
    assert durum['close_calls'] == [1]


def test_bundletool_job_process_count_okunamazsa():
    import ctypes

    kernel32, _ = _sahte_kernel32(query_ok=False)
    with pytest.raises(OSError) as exc:
        AdbEngine._bundletool_job_process_count((kernel32, 1, ctypes.c_int))
    assert 'okunamadı' in str(exc.value)


@pytest.mark.skipif(os.name != 'nt', reason='Windows is nesnesi')
def test_stop_bundletool_process_tree_job_hata_taskkill(monkeypatch):
    kernel32, _ = _sahte_kernel32(terminate_raises=True)
    cagri = []

    def sahte_run(cmd, **kwargs):
        cagri.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr('mibox_app.adb_engine.subprocess.run', sahte_run)
    monkeypatch.setattr('mibox_app.adb_engine.shutil.which',
                        lambda ad: sys.executable)

    class SahteProc:
        pid = 4321

        def poll(self):
            return None

        def terminate(self):
            raise OSError('terminate yok')

    AdbEngine._stop_bundletool_process_tree(SahteProc(), job=(kernel32, 1))
    assert cagri and cagri[0][1] == '/PID'


@pytest.mark.skipif(os.name != 'nt', reason='Windows taskkill')
def test_stop_bundletool_process_tree_taskkill_hatasi(monkeypatch):
    def sahte_run(cmd, **kwargs):
        raise OSError('taskkill yok')

    class SahteProc:
        pid = 4321

        def poll(self):
            return 0

    monkeypatch.setattr('mibox_app.adb_engine.subprocess.run', sahte_run)
    monkeypatch.setattr('mibox_app.adb_engine.shutil.which',
                        lambda ad: sys.executable)

    # taskkill calistirilamazsa hata yutulur; poll 0 oldugu icin terminate
    # denenmez.
    AdbEngine._stop_bundletool_process_tree(SahteProc())


def test_stop_bundletool_process_tree_posix_killpg(monkeypatch):
    cagrilar = []

    def sahte_killpg(pid, sig):
        cagrilar.append((pid, sig))
        raise OSError('killpg yok')

    class SahteProc:
        pid = 777

        def poll(self):
            return None

        def terminate(self):
            pass

    monkeypatch.setattr(os, 'name', 'posix')
    monkeypatch.setattr(os, 'killpg', sahte_killpg, raising=False)
    AdbEngine._stop_bundletool_process_tree(SahteProc())
    assert cagrilar == [(777, signal.SIGTERM)]


def test_create_bundletool_job_posix_none(monkeypatch):
    monkeypatch.setattr(os, 'name', 'posix')
    assert AdbEngine._create_bundletool_job(SimpleNamespace(_handle=1)) is None


def test_resume_bundletool_process_posix_none(monkeypatch):
    monkeypatch.setattr(os, 'name', 'posix')
    assert AdbEngine._resume_bundletool_process(SimpleNamespace(pid=1)) is None


# --- _copy_archive_entry -----------------------------------------------------

def test_copy_archive_entry_kopyalar():
    kaynak = io.BytesIO(b'veri' * 100)
    hedef = io.BytesIO()
    AdbEngine._copy_archive_entry(kaynak, hedef)
    assert hedef.getvalue() == b'veri' * 100


def test_copy_archive_entry_iptal():
    def iptal():
        raise AdbError('durduruldu')

    with pytest.raises(AdbError) as exc:
        AdbEngine._copy_archive_entry(io.BytesIO(b'x' * 10), io.BytesIO(),
                                      iptal)
    assert 'durduruldu' in str(exc.value)


# --- ortak sahte motorlar ----------------------------------------------------

class SahteKurulum(AdbEngine):
    """install_apk/install_multiple cagrilarini kaydeden motor."""

    def __init__(self, adb_path='fake-adb'):
        super().__init__(adb_path=adb_path)
        self.install_calls = []
        self.multiple_calls = []
        self.bundletool_calls = []

    def install_apk(self, target, local_path, reinstall=True, grant_perms=False,
                    allow_downgrade=False, timeout=120, cancel_check=None):
        self.install_calls.append((target, local_path, reinstall, grant_perms,
                                   allow_downgrade, timeout, cancel_check))
        return 'tek-sonuc'

    def install_multiple(self, target, apk_path, reinstall=True,
                         grant_perms=False, allow_downgrade=False, timeout=180,
                         cancel_check=None):
        self.multiple_calls.append((target, apk_path, reinstall, grant_perms,
                                    allow_downgrade, timeout, cancel_check))
        return 'coklu-sonuc'

    def _run_bundletool(self, command, timeout, operation, cancel_check=None):
        self.bundletool_calls.append((command, timeout, operation, cancel_check))
        return SimpleNamespace(returncode=0, stdout='', stderr='')


class SpecYazanKurulum(SahteKurulum):
    """_run_bundletool yerine spec/selected dosyalarini yazan sahte motor."""

    def __init__(self):
        super().__init__()
        self.spec_rc = 0
        self.spec_yaz = True
        self.extract_rc = 0
        self.selected = ['base.apk']

    def _run_bundletool(self, command, timeout, operation, cancel_check=None):
        self.bundletool_calls.append((command, timeout, operation, cancel_check))
        if 'get-device-spec' in command:
            if self.spec_yaz:
                for arg in command:
                    if arg.startswith('--output='):
                        with open(arg.split('=', 1)[1], 'w') as dosya:
                            dosya.write('{}')
            return SimpleNamespace(returncode=self.spec_rc, stdout='',
                                   stderr='spec hata')
        for arg in command:
            if arg.startswith('--output-dir='):
                klasor = arg.split('=', 1)[1]
                for name in self.selected:
                    with open(os.path.join(klasor, name), 'w') as dosya:
                        dosya.write('apk')
        return SimpleNamespace(returncode=self.extract_rc, stdout='',
                               stderr='extract hata')


class KayitliRun(AdbEngine):
    """run() cagrilarini kaydeden, sabit yanit donen motor."""

    def __init__(self, yanit=None):
        super().__init__(adb_path='fake-adb')
        self.calls = []
        self.yanit = yanit or AdbResult(0, 'Success', '')

    def run(self, args, timeout=30, binary=False, quiet_first=False,
            preserve_output_whitespace=False, cancel_check=None,
            hide_shell_from_trace=False):
        self.calls.append([str(a) for a in args])
        return self.yanit


def _apks_yaz(path, uyeler):
    with zipfile.ZipFile(str(path), 'w') as arsiv:
        for name, data in uyeler:
            arsiv.writestr(name, data)


# --- _install_apks_archive ---------------------------------------------------

def test_install_apks_archive_bundletool_yoksa_none():
    eng = SahteKurulum()
    eng._bundletool_command = lambda: None
    assert eng._install_apks_archive('S', 'a.apks', 30) is None


def test_install_apks_archive_adb_yolu_yoksa_none():
    eng = SahteKurulum()
    eng.adb_path = None
    eng._bundletool_command = lambda: ['fake']
    assert eng._install_apks_archive('S', 'a.apks', 30) is None


def test_install_apks_archive_gecersiz_hedef():
    eng = SahteKurulum()
    eng._bundletool_command = lambda: ['fake']
    with pytest.raises(AdbError) as exc:
        eng._install_apks_archive('kotu\nhedef', 'a.apks', 30)
    assert 'geçersiz' in str(exc.value)
    assert eng.bundletool_calls == []


def test_install_apks_archive_tek_apk():
    eng = SpecYazanKurulum()
    eng._bundletool_command = lambda: ['fake-bundletool']
    sonuc = eng._install_apks_archive('S', 'a.apks', 30)
    assert sonuc == 'tek-sonuc'
    assert len(eng.install_calls) == 1
    assert eng.install_calls[0][1].endswith('base.apk')
    assert eng.bundletool_calls[0][0][1] == 'get-device-spec'
    assert eng.bundletool_calls[1][0][1] == 'extract-apks'


def test_install_apks_archive_coklu_apk():
    eng = SpecYazanKurulum()
    eng.selected = ['base.apk', 'split_config.arm64.apk']
    eng._bundletool_command = lambda: ['fake']
    assert eng._install_apks_archive('S', 'a.apks', 30) == 'coklu-sonuc'
    assert len(eng.multiple_calls) == 1
    secilen = eng.multiple_calls[0][1]
    assert len(secilen) == 2
    assert secilen[0].endswith('base.apk')
    assert secilen[1].endswith('split_config.arm64.apk')


def test_install_apks_archive_spec_hatasi():
    eng = SpecYazanKurulum()
    eng.spec_rc = 1
    eng._bundletool_command = lambda: ['fake']
    with pytest.raises(AdbError) as exc:
        eng._install_apks_archive('S', 'a.apks', 30)
    assert 'yapılandırmasını okuyamadı' in str(exc.value)


def test_install_apks_archive_spec_dosyasi_yok():
    eng = SpecYazanKurulum()
    eng.spec_yaz = False
    eng._bundletool_command = lambda: ['fake']
    with pytest.raises(AdbError) as exc:
        eng._install_apks_archive('S', 'a.apks', 30)
    assert 'yapılandırmasını okuyamadı' in str(exc.value)


def test_install_apks_archive_extract_hatasi():
    eng = SpecYazanKurulum()
    eng.extract_rc = 1
    eng._bundletool_command = lambda: ['fake']
    with pytest.raises(AdbError) as exc:
        eng._install_apks_archive('S', 'a.apks', 30)
    assert 'uyumlu APK seçemedi' in str(exc.value)


def test_install_apks_archive_apk_bulunamazsa():
    eng = SpecYazanKurulum()
    eng.selected = []
    eng._bundletool_command = lambda: ['fake']
    with pytest.raises(AdbError) as exc:
        eng._install_apks_archive('S', 'a.apks', 30)
    assert 'uyumlu APK bulamadı' in str(exc.value)


def test_install_apks_archive_iptal():
    eng = SpecYazanKurulum()
    eng._bundletool_command = lambda: ['fake']

    def iptal():
        raise AdbError('durduruldu')

    with pytest.raises(AdbError) as exc:
        eng._install_apks_archive('S', 'a.apks', 30, cancel_check=iptal)
    assert 'durduruldu' in str(exc.value)
    assert eng.install_calls == []


# --- _install_universal_apks -------------------------------------------------

def test_universal_apks_kurulur(tmp_path):
    arsiv = tmp_path / 'uygulama.apks'
    _apks_yaz(arsiv, [('universal.apk', b'universal-icerik'),
                      ('splits/base-master.apk', b'baska')])
    eng = SahteKurulum()
    sonuc = eng._install_universal_apks('S', str(arsiv), 30)
    assert sonuc == 'tek-sonuc'
    assert len(eng.install_calls) == 1
    assert eng.install_calls[0][1].endswith('universal.apk')


def test_universal_apks_birden_fazla_uygun(tmp_path):
    arsiv = tmp_path / 'u.apks'
    _apks_yaz(arsiv, [('universal.apk', b'a'), ('x/universal.apk', b'b')])
    eng = SahteKurulum()
    with pytest.raises(AdbError) as exc:
        eng._install_universal_apks('S', str(arsiv), 30)
    assert 'Bundletool gerekli' in str(exc.value)


def test_universal_apks_yoksa(tmp_path):
    arsiv = tmp_path / 'u.apks'
    _apks_yaz(arsiv, [('base.apk', b'a')])
    eng = SahteKurulum()
    with pytest.raises(AdbError) as exc:
        eng._install_universal_apks('S', str(arsiv), 30)
    assert 'Bundletool gerekli' in str(exc.value)


def test_universal_apks_bozuk_arsiv(tmp_path):
    arsiv = tmp_path / 'u.apks'
    arsiv.write_bytes(b'zip degil')
    eng = SahteKurulum()
    with pytest.raises(AdbError) as exc:
        eng._install_universal_apks('S', str(arsiv), 30)
    assert 'arşivi açılamadı' in str(exc.value)


def test_universal_apks_iptal(tmp_path):
    arsiv = tmp_path / 'u.apks'
    _apks_yaz(arsiv, [('universal.apk', b'x' * 100)])
    eng = SahteKurulum()
    sayac = {'n': 0}

    def iptal():
        sayac['n'] += 1
        if sayac['n'] >= 2:
            raise AdbError('durduruldu')

    with pytest.raises(AdbError) as exc:
        eng._install_universal_apks('S', str(arsiv), 30, cancel_check=iptal)
    assert 'durduruldu' in str(exc.value)


def test_universal_apks_boyut_gecersiz(tmp_path):
    arsiv = tmp_path / 'u.apks'
    _apks_yaz(arsiv, [('universal.apk', b'')])
    eng = SahteKurulum()
    with pytest.raises(AdbError) as exc:
        eng._install_universal_apks('S', str(arsiv), 30)
    assert 'güvenli sınırların dışında' in str(exc.value)
    assert eng.install_calls == []


def test_universal_apks_son_iptal(tmp_path, monkeypatch):
    arsiv = tmp_path / 'u.apks'
    _apks_yaz(arsiv, [('universal.apk', b'x' * 100)])
    monkeypatch.setattr(
        'mibox_app.adb_engine.AdbEngine._copy_archive_entry',
        staticmethod(lambda source, destination, cancel_check=None: None))
    eng = SahteKurulum()
    sayac = {'n': 0}

    def iptal():
        sayac['n'] += 1
        if sayac['n'] >= 2:
            raise AdbError('durduruldu')

    with pytest.raises(AdbError) as exc:
        eng._install_universal_apks('S', str(arsiv), 30, cancel_check=iptal)
    assert 'durduruldu' in str(exc.value)
    assert eng.install_calls == []


# --- install_multiple --------------------------------------------------------

def test_install_multiple_liste_temizlenir(tmp_path):
    iyi = tmp_path / 'iyi.apk'
    iyi.write_bytes(b'x')
    eng = KayitliRun()
    r = eng.install_multiple('S', [
        str(iyi), 'kotu.txt', str(tmp_path / 'yok.apk'),
        'satir\n.apk', str(iyi)])
    assert r.exit_code == 0
    assert eng.calls == [['-s', 'S', 'install-multiple', '-r', str(iyi)]]


def test_install_multiple_bayraklar(tmp_path):
    iyi = tmp_path / 'iyi.apk'
    iyi.write_bytes(b'x')
    eng = KayitliRun()
    eng.install_multiple('S', [str(iyi)], reinstall=False, grant_perms=True,
                         allow_downgrade=True)
    assert eng.calls == [['-s', 'S', 'install-multiple', '-g', '-d', str(iyi)]]


def test_install_multiple_dizin_icerigini_alfabetik_alir(tmp_path):
    (tmp_path / 'b.apk').write_bytes(b'b')
    (tmp_path / 'a.apk').write_bytes(b'a')
    (tmp_path / 'not.txt').write_bytes(b'n')
    eng = KayitliRun()
    eng.install_multiple('S', str(tmp_path))
    assert eng.calls == [[
        '-s', 'S', 'install-multiple', '-r',
        str(tmp_path / 'a.apk'), str(tmp_path / 'b.apk')]]


def test_install_multiple_tek_dosya(tmp_path):
    tek = tmp_path / 'tek.apk'
    tek.write_bytes(b'x')
    eng = KayitliRun()
    eng.install_multiple('S', str(tek))
    assert eng.calls == [['-s', 'S', 'install-multiple', '-r', str(tek)]]


def test_install_multiple_bos_liste_hata():
    eng = KayitliRun()
    with pytest.raises(AdbError) as exc:
        eng.install_multiple('S', [])
    assert 'Kurulacak APK bulunamadı' in str(exc.value)
    assert eng.calls == []


def test_install_multiple_basarisiz(tmp_path):
    iyi = tmp_path / 'iyi.apk'
    iyi.write_bytes(b'x')
    eng = KayitliRun(AdbResult(0, 'Failure [INSTALL_FAILED_OLDER_SDK]', ''))
    with pytest.raises(AdbError) as exc:
        eng.install_multiple('S', [str(iyi)])
    assert 'Toplu kurulum başarısız' in str(exc.value)


def test_install_multiple_baslamadan_iptal(tmp_path):
    iyi = tmp_path / 'iyi.apk'
    iyi.write_bytes(b'x')

    def iptal():
        raise AdbError('durduruldu')

    eng = KayitliRun()
    with pytest.raises(AdbError) as exc:
        eng.install_multiple('S', [str(iyi)], cancel_check=iptal)
    assert 'durduruldu' in str(exc.value)
    assert eng.calls == []


def test_install_multiple_apks_dosyasi_yok():
    eng = KayitliRun()
    with pytest.raises(AdbError) as exc:
        eng.install_multiple('S', 'yok.apks')
    assert '.apks arşivi bulunamadı' in str(exc.value)


class ApksYonlendirme(AdbEngine):
    def __init__(self, archive_sonuc):
        super().__init__(adb_path='fake-adb')
        self.archive_sonuc = archive_sonuc
        self.archive_calls = []
        self.universal_calls = []

    def _install_apks_archive(self, target, archive_path, timeout,
                              reinstall=True, grant_perms=False,
                              allow_downgrade=False, cancel_check=None):
        self.archive_calls.append(archive_path)
        return self.archive_sonuc

    def _install_universal_apks(self, target, archive_path, timeout,
                                reinstall=True, grant_perms=False,
                                allow_downgrade=False, cancel_check=None):
        self.universal_calls.append(archive_path)
        return 'universal-sonuc'


def test_install_multiple_apks_bundletool_sonucu_dondurur(tmp_path):
    arsiv = tmp_path / 'u.apks'
    arsiv.write_bytes(b'x')
    eng = ApksYonlendirme('arsiv-sonuc')
    assert eng.install_multiple('S', str(arsiv)) == 'arsiv-sonuc'
    assert eng.archive_calls == [str(arsiv)]
    assert eng.universal_calls == []


def test_install_multiple_apks_universal_yedegi(tmp_path):
    arsiv = tmp_path / 'u.apks'
    arsiv.write_bytes(b'x')
    eng = ApksYonlendirme(None)
    assert eng.install_multiple('S', str(arsiv)) == 'universal-sonuc'
    assert eng.universal_calls == [str(arsiv)]


def test_install_multiple_apkm_cozer(tmp_path):
    arsiv = tmp_path / 'uygulama.apkm'
    _apks_yaz(arsiv, [('base.apk', b'a'), ('config.arm64.apk', b'b')])
    eng = KayitliRun()
    r = eng.install_multiple('S', str(arsiv))
    assert r.exit_code == 0
    assert len(eng.calls) == 1
    call = eng.calls[0]
    assert call[:4] == ['-s', 'S', 'install-multiple', '-r']
    assert len(call) == 6
    assert call[4].endswith('split-0000.apk')
    assert call[5].endswith('split-0001.apk')


def test_install_multiple_apkm_bos_arsiv(tmp_path):
    arsiv = tmp_path / 'u.apkm'
    _apks_yaz(arsiv, [('notlar.txt', b'a')])
    eng = KayitliRun()
    with pytest.raises(AdbError) as exc:
        eng.install_multiple('S', str(arsiv))
    assert 'Arşivde kurulacak APK bulunamadı' in str(exc.value)


def test_install_multiple_apkm_dosya_siniri(tmp_path):
    arsiv = tmp_path / 'u.apkm'
    _apks_yaz(arsiv, [('p{}.apk'.format(i), b'') for i in range(513)])
    eng = KayitliRun()
    with pytest.raises(AdbError) as exc:
        eng.install_multiple('S', str(arsiv))
    assert 'sınırını aşıyor' in str(exc.value)


def test_install_multiple_apkm_bozuk_arsiv(tmp_path):
    arsiv = tmp_path / 'u.apkm'
    arsiv.write_bytes(b'zip degil')
    eng = KayitliRun()
    with pytest.raises(AdbError) as exc:
        eng.install_multiple('S', str(arsiv))
    assert 'arşivi açılamadı' in str(exc.value)


def test_install_multiple_apkm_iptal(tmp_path):
    arsiv = tmp_path / 'u.apkm'
    _apks_yaz(arsiv, [('a.apk', b'a'), ('b.apk', b'b')])
    sayac = {'n': 0}

    def iptal():
        sayac['n'] += 1
        if sayac['n'] >= 3:
            raise AdbError('durduruldu')

    eng = KayitliRun()
    with pytest.raises(AdbError) as exc:
        eng.install_multiple('S', str(arsiv), cancel_check=iptal)
    assert 'durduruldu' in str(exc.value)
    assert eng.calls == []


def test_install_multiple_apkm_son_iptal(tmp_path, monkeypatch):
    arsiv = tmp_path / 'u.apkm'
    _apks_yaz(arsiv, [('a.apk', b'a')])
    monkeypatch.setattr(
        'mibox_app.adb_engine.AdbEngine._copy_archive_entry',
        staticmethod(lambda source, destination, cancel_check=None: None))
    sayac = {'n': 0}

    def iptal():
        sayac['n'] += 1
        if sayac['n'] >= 3:
            raise AdbError('durduruldu')

    eng = KayitliRun()
    with pytest.raises(AdbError) as exc:
        eng.install_multiple('S', str(arsiv), cancel_check=iptal)
    assert 'durduruldu' in str(exc.value)
    assert eng.calls == []


def test_install_multiple_liste_son_iptal(tmp_path):
    iyi = tmp_path / 'iyi.apk'
    iyi.write_bytes(b'x')
    sayac = {'n': 0}

    def iptal():
        sayac['n'] += 1
        if sayac['n'] >= 2:
            raise AdbError('durduruldu')

    eng = KayitliRun()
    with pytest.raises(AdbError) as exc:
        eng.install_multiple('S', [str(iyi)], cancel_check=iptal)
    assert 'durduruldu' in str(exc.value)
    assert eng.calls == []


# --- install_apks (devir) ----------------------------------------------------

def test_install_apks_install_multiple_devreder():
    class DevirEngine(AdbEngine):
        def __init__(self):
            super().__init__(adb_path='fake-adb')
            self.cagrilar = []

        def install_multiple(self, target, apk_path, **kwargs):
            self.cagrilar.append((target, apk_path, kwargs))
            return 'sonuc'

    eng = DevirEngine()
    assert eng.install_apks('S', ['a.apk', 'b.apk'], timeout=99) == 'sonuc'
    assert eng.cagrilar == [('S', ['a.apk', 'b.apk'], {'timeout': 99})]
