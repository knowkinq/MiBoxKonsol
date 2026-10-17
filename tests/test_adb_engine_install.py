# -*- coding: utf-8 -*-
"""AdbEngine APK kurulum yollari testleri (FakeEngine: ADB yok).

Kapsam: install_apk yol dogrulamalari, bayraklar, iptal geri cagrisi ve
Success kontrolu; install_remote_apk uzak yol guvenligi ve pm install
cagrisi. Gercek cihaz, ag veya kurulum yapilmaz; yerel dosya gecici
dizinde olusturulur.
"""
import pytest

from mibox_app.adb_engine import (
    AdbEngine,
    AdbError,
    AdbResult,
    PackageStateUnknownError,
)


class ShellEngine(AdbEngine):
    """shell()/run() yerine kaydeden ve sahte yanit ureten motor."""

    def __init__(self, handler):
        super().__init__(adb_path='fake-adb')
        self.calls = []
        self.shell_options = []
        self._handler = handler

    def _handle(self, call):
        self.calls.append(call)
        result = self._handler(call)
        if result is None:
            raise AssertionError('Beklenmeyen ADB cagrisi: {}'.format(call))
        return result

    def shell(self, target, *cmd, **kwargs):
        self.shell_options.append(dict(kwargs))
        return self._handle([str(c) for c in cmd])

    def run(self, args, timeout=30, binary=False, quiet_first=False,
            preserve_output_whitespace=False, cancel_check=None,
            hide_shell_from_trace=False):
        return self._handle([str(a) for a in args])


@pytest.fixture
def apk(tmp_path):
    path = tmp_path / 'uygulama.apk'
    path.write_bytes(b'fake apk')
    return str(path)


# --- install_apk -------------------------------------------------------------

def test_install_apk_basarili(apk):
    eng = ShellEngine(lambda call: AdbResult(0, 'Success', ''))
    r = eng.install_apk('S', apk)
    assert r.exit_code == 0
    assert eng.calls == [['-s', 'S', 'install', '-r', apk]]


def test_install_apk_bayraklar(apk):
    eng = ShellEngine(lambda call: AdbResult(0, 'Success', ''))
    eng.install_apk('S', apk, reinstall=False, grant_perms=True,
                    allow_downgrade=True)
    assert eng.calls == [['-s', 'S', 'install', '-g', '-d', apk]]


def test_install_apk_uzanti_gecersiz(tmp_path):
    path = tmp_path / 'uygulama.txt'
    path.write_bytes(b'x')
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError) as exc:
        eng.install_apk('S', str(path))
    assert 'uzanti .apk' in str(exc.value)
    assert eng.calls == []


def test_install_apk_yol_kontrol_karakteri(tmp_path):
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError) as exc:
        eng.install_apk('S', 'kotu\n.apk')
    assert 'Geçersiz APK yolu' in str(exc.value)
    assert eng.calls == []


def test_install_apk_dosya_yok(tmp_path):
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError) as exc:
        eng.install_apk('S', str(tmp_path / 'yok.apk'))
    assert 'APK bulunamadı' in str(exc.value)
    assert eng.calls == []


def test_install_apk_basarisiz(apk):
    eng = ShellEngine(lambda call: AdbResult(
        0, 'Failure [INSTALL_FAILED_ALREADY_EXISTS]', ''))
    with pytest.raises(AdbError) as exc:
        eng.install_apk('S', apk)
    assert 'Kurulum başarısız' in str(exc.value)
    assert 'uygulama.apk' in str(exc.value)


def test_install_apk_exit_kodu_hatasi(apk):
    eng = ShellEngine(lambda call: AdbResult(1, '', 'adb: device offline'))
    with pytest.raises(AdbError) as exc:
        eng.install_apk('S', apk)
    assert 'device offline' in str(exc.value)


def test_install_apk_iptal_geri_cagrisi(apk):
    eng = ShellEngine(lambda call: AdbResult(0, 'Success', ''))
    sayac = {'n': 0}

    def iptal():
        sayac['n'] += 1

    eng.install_apk('S', apk, cancel_check=iptal)
    assert sayac['n'] == 1

    def iptal_hata():
        raise AdbError('kullanıcı durdurdu')

    with pytest.raises(AdbError) as exc:
        eng.install_apk('S', apk, cancel_check=iptal_hata)
    assert 'durdurdu' in str(exc.value)


def _orphan_result(call, *, path_missing=True, path_exists=False,
                   active='', retained=None, dump=None,
                   code_path='/data/app/~~install==/ar.tvplayer.tv-abc=='):
    pkg = 'ar.tvplayer.tv'
    if call == ['pm', 'list', 'packages']:
        return AdbResult(0, active, '')
    if call == ['pm', 'list', 'packages', '-u']:
        return AdbResult(0, retained if retained is not None else 'package:' + pkg + '\n', '')
    if call == ['pm', 'path', pkg]:
        return AdbResult(1 if path_missing else 0,
                         '' if path_missing else 'package:' + code_path + '/base.apk\n', '')
    if call == ['dumpsys', 'package', pkg]:
        return AdbResult(0, dump if dump is not None else (
            'Package [{}] (eb7a73d):\n'
            '  codePath={}\n'
            '  pkg=null\n'
            '  User 0: ceDataInode=0 installed=true hidden=false\n'
        ).format(pkg, code_path), '')
    if len(call) == 3 and call[:2] == ['ls', '-ld']:
        requested_path = call[2].strip("'\"")
        return AdbResult(0 if path_exists else 1,
                         '-rw-r--r-- 1 system system 0 {}\n'.format(requested_path)
                         if path_exists else 'ls: {}: No such file or directory\n'.format(
                             requested_path), '')
    return None


def test_orphan_registration_accepts_real_missing_apk_fixture():
    eng = ShellEngine(_orphan_result)
    assert eng.is_orphaned_package_registration('tv-1', 'ar.tvplayer.tv') is True
    assert eng.calls == [
        ['pm', 'list', 'packages'],
        ['pm', 'list', 'packages', '-u'],
        ['pm', 'path', 'ar.tvplayer.tv'],
        ['dumpsys', 'package', 'ar.tvplayer.tv'],
        ['ls', '-ld', "'/data/app/~~install==/ar.tvplayer.tv-abc=='"],
    ]
    assert eng.shell_options[-1]['hide_from_trace'] is True


def test_orphan_registration_does_not_treat_unavailable_adopted_volume_as_orphan():
    eng = ShellEngine(lambda call: _orphan_result(
        call, code_path='/mnt/expand/1234-ABCD/app/ar.tvplayer.tv-abc=='))
    with pytest.raises(PackageStateUnknownError, match='depolama durumu'):
        eng.is_orphaned_package_registration('tv-1', 'ar.tvplayer.tv')
    assert eng.calls == [
        ['pm', 'list', 'packages'],
        ['pm', 'list', 'packages', '-u'],
        ['pm', 'path', 'ar.tvplayer.tv'],
        ['dumpsys', 'package', 'ar.tvplayer.tv'],
    ]


@pytest.mark.parametrize('kwargs', [
    {'active': 'package:ar.tvplayer.tv\n'},
    {'retained': ''},
    {'path_missing': False},
    {'dump': 'Package [ar.tvplayer.tv] (eb7a73d):\n  pkg=Package{}\n'},
    {'dump': 'Package [ar.tvplayer.tv] (eb7a73d):\n  codePath=/data/app/x\n'
             '  pkg=null\n  User 0: installed=true\n', 'path_exists': True},
])
def test_orphan_registration_non_orphan_fails_closed(kwargs):
    eng = ShellEngine(lambda call: _orphan_result(call, **kwargs))
    assert eng.is_orphaned_package_registration('tv-1', 'ar.tvplayer.tv') is False


@pytest.mark.parametrize('call, result', [
    (['pm', 'list', 'packages'], AdbResult(1, '', 'offline')),
    (['pm', 'path', 'ar.tvplayer.tv'], AdbResult(1, '', 'not readable')),
    (['dumpsys', 'package', 'ar.tvplayer.tv'], AdbResult(1, '', 'offline')),
    (['ls', '-ld', "'/data/app/~~install==/ar.tvplayer.tv-abc=='"],
     AdbResult(1, 'ls: permission denied\n', '')),
])
def test_orphan_registration_probe_errors_do_not_authorize(call, result):
    def handler(actual):
        if actual == call:
            return result
        return _orphan_result(actual)

    eng = ShellEngine(handler)
    with pytest.raises(AdbError):
        eng.is_orphaned_package_registration('tv-1', 'ar.tvplayer.tv')


def test_orphan_registration_pm_path_accepts_only_empty_exit_one():
    def handler(call):
        if call == ['pm', 'path', 'ar.tvplayer.tv']:
            return AdbResult(1, 'Error: package missing\n', '')
        return _orphan_result(call)

    with pytest.raises(AdbError):
        ShellEngine(handler).is_orphaned_package_registration('tv-1', 'ar.tvplayer.tv')


def test_orphan_registration_cancel_check_stops_probes():
    eng = ShellEngine(_orphan_result)
    checks = {'count': 0}

    def cancel():
        checks['count'] += 1
        if checks['count'] == 3:
            raise RuntimeError('cancelled')

    with pytest.raises(RuntimeError, match='cancelled'):
        eng.is_orphaned_package_registration(
            'tv-1', 'ar.tvplayer.tv', cancel_check=cancel)
    assert eng.calls == [['pm', 'list', 'packages']]


def test_uninstall_package_full_omits_keep_data_and_verifies_cache():
    eng = ShellEngine(lambda call: (
        AdbResult(0, 'Success\n', '') if call == ['pm', 'uninstall', 'ar.tvplayer.tv']
        else AdbResult(0, '', '') if call == ['pm', 'list', 'packages', '-u']
        else None))
    invalidated = []
    eng.invalidate_pkg_cache = lambda target=None: invalidated.append(target)

    result = eng.uninstall_package_full('tv-1', 'ar.tvplayer.tv')
    assert result.output == 'Success\n'
    assert eng.calls == [
        ['pm', 'uninstall', 'ar.tvplayer.tv'],
        ['pm', 'list', 'packages', '-u'],
    ]
    assert invalidated == ['tv-1']


def test_uninstall_package_full_fails_if_registration_remains_and_invalidates():
    eng = ShellEngine(lambda call: (
        AdbResult(0, 'Success\n', '') if call == ['pm', 'uninstall', 'ar.tvplayer.tv']
        else AdbResult(0, 'package:ar.tvplayer.tv\n', '') if call == ['pm', 'list', 'packages', '-u']
        else None))
    invalidated = []
    eng.invalidate_pkg_cache = lambda target=None: invalidated.append(target)

    with pytest.raises(AdbError, match='paket listesinde kaldı'):
        eng.uninstall_package_full('tv-1', 'ar.tvplayer.tv')
    assert invalidated == ['tv-1']


# --- install_remote_apk ------------------------------------------------------

def test_install_remote_apk_basarili():
    eng = ShellEngine(lambda call: AdbResult(0, 'Success', ''))
    r = eng.install_remote_apk('S', '/sdcard/uygulama.apk')
    assert r.exit_code == 0
    assert eng.calls == [['pm', 'install', '-r', '/sdcard/uygulama.apk']]


def test_install_remote_apk_bayraklar():
    eng = ShellEngine(lambda call: AdbResult(0, 'Success', ''))
    eng.install_remote_apk('S', '/sdcard/a.apk', reinstall=False,
                           grant_perms=True, allow_downgrade=True)
    assert eng.calls == [['pm', 'install', '-g', '-d', '/sdcard/a.apk']]


def test_install_remote_apk_uzanti_gecersiz():
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError) as exc:
        eng.install_remote_apk('S', '/sdcard/uygulama.zip')
    assert 'uzak APK yolu' in str(exc.value)
    assert eng.calls == []


def test_install_remote_apk_ust_dizin_reddedilir():
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError) as exc:
        eng.install_remote_apk('S', '/sdcard/../data/x.apk')
    assert 'üst dizine' in str(exc.value)
    assert eng.calls == []


def test_install_remote_apk_basarisiz():
    eng = ShellEngine(lambda call: AdbResult(
        0, 'Failure [INSTALL_FAILED_INVALID_APK]', ''))
    with pytest.raises(AdbError) as exc:
        eng.install_remote_apk('S', '/sdcard/uygulama.apk')
    assert 'Cihazda kurulum başarısız' in str(exc.value)
    assert 'uygulama.apk' in str(exc.value)


def test_install_remote_apk_tirnakli_yol():
    eng = ShellEngine(lambda call: AdbResult(0, 'Success', ''))
    eng.install_remote_apk('S', '/sdcard/boşluklu ad.apk')
    assert eng.calls == [['pm', 'install', '-r', "'/sdcard/boşluklu ad.apk'"]]
