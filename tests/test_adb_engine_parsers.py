# -*- coding: utf-8 -*-
"""AdbEngine cikti ayristiricilari (FakeEngine: gercek ADB cagrilmaz).

Kapsam: paket listeleri + onbellek, ps surec okuma, uygulama etiketleri,
arka plan kisitlama sorgulari, dumpsys ozetleri (app_detail, app_permissions,
health, device_info), dosya listesi, logcat, depolama/kullanici sorgulari
ve ekran goruntusu akisi. Tum ADB etkilesimi sahte shell/run katmaninda
karsilanir; aga veya cihaza hic dokunulmaz.
"""
import struct
import zlib

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
        self._handler = handler

    def _handle(self, call):
        self.calls.append(call)
        result = self._handler(call)
        if result is None:
            raise AssertionError('Beklenmeyen ADB cagrisi: {}'.format(call))
        return result

    def shell(self, target, *cmd, **kwargs):
        return self._handle([str(c) for c in cmd])

    def run(self, args, timeout=30, binary=False, quiet_first=False,
            preserve_output_whitespace=False, cancel_check=None,
            hide_shell_from_trace=False):
        return self._handle([str(a) for a in args])


def _sabit(output='', exit_code=0, error=''):
    """Her cagriya ayni yaniti veren handler."""
    return lambda call: AdbResult(exit_code, output, error)


def _png_bytes():
    """1x1 piksel, gecerli chunk yapisi ve CRC'lerle PNG uretir."""
    def chunk(kind, payload):
        return (struct.pack('>I', len(payload)) + kind + payload
                + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff))

    ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)
    raw = b'\x00' + b'\xff\x00\x00\xff'
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


@pytest.fixture(autouse=True)
def temiz_paket_onbellegi():
    AdbEngine.clear_pkg_cache_for_tests()
    yield
    AdbEngine.clear_pkg_cache_for_tests()


# --- _parse_package_list -----------------------------------------------------

def test_parse_package_list_temel():
    out = 'package:com.a\npackage:com.b\n'
    assert AdbEngine._parse_package_list(out) == ['com.a', 'com.b']


def test_parse_package_list_tekrar_ve_bos():
    assert AdbEngine._parse_package_list('') == []
    assert AdbEngine._parse_package_list(None) == []
    assert AdbEngine._parse_package_list(
        'package:com.a\npackage:com.a\n') == ['com.a']
    assert AdbEngine._parse_package_list('No packages found.\n') == []
    assert AdbEngine._parse_package_list('no packages\n') == []


def test_parse_package_list_bozuk_satir():
    with pytest.raises(AdbError):
        AdbEngine._parse_package_list('package:com.a\nrastgele satir\n')


def test_parse_package_list_gecersiz_paket():
    with pytest.raises(AdbError):
        AdbEngine._parse_package_list('package:gecersiz paket\n')
    with pytest.raises(AdbError):
        AdbEngine._parse_package_list('package:com.a:u0\n')


# --- list_packages -----------------------------------------------------------

def test_list_packages_ucuncu_taraf():
    engine = ShellEngine(_sabit('package:com.a\n'))
    assert engine.list_packages('tv-1') == ['com.a']
    assert engine.calls == [['pm', 'list', 'packages', '-3']]


def test_list_packages_sistem_bos_hata():
    engine = ShellEngine(_sabit(''))
    with pytest.raises(AdbError) as exc:
        engine.list_packages('tv-1', include_system=True)
    assert 'Sistem paket listesi boş' in str(exc.value)
    assert engine.calls == [['pm', 'list', 'packages', '-a']]


def test_list_packages_hata_mesaji():
    engine = ShellEngine(_sabit('', 1, 'adb: device offline'))
    with pytest.raises(AdbError) as exc:
        engine.list_packages('tv-1')
    assert 'device offline' in str(exc.value)


# --- is_installed ------------------------------------------------------------

def test_is_installed_kurulu():
    engine = ShellEngine(_sabit('package:/data/app/com.a/base.apk\n'))
    assert engine.is_installed('tv-1', 'com.a') is True
    assert engine.calls == [['pm', 'path', 'com.a']]


def test_is_installed_kurulu_degil():
    engine = ShellEngine(_sabit('', 1))
    assert engine.is_installed('tv-1', 'com.a') is False

    engine2 = ShellEngine(_sabit('not found\n'))
    assert engine2.is_installed('tv-1', 'com.a') is False


def test_is_installed_user_id():
    engine = ShellEngine(_sabit('package:/x.apk\n'))
    assert engine.is_installed('tv-1', 'com.a', user_id=5) is True
    assert engine.calls == [['pm', 'path', '--user', '5', 'com.a']]


def test_is_installed_gecersiz_paket_ve_istisna():
    engine = ShellEngine(_sabit('package:/x.apk\n'))
    assert engine.is_installed('tv-1', 'gecersiz paket') is False
    assert engine.calls == []

    def patla(call):
        raise AdbError('kopuk')

    engine2 = ShellEngine(patla)
    assert engine2.is_installed('tv-1', 'com.a') is False


# --- list_packages_user0 -----------------------------------------------------

def test_list_packages_user0_set():
    engine = ShellEngine(_sabit('package:com.a\npackage:com.b\n'))
    assert engine.list_packages_user0('tv-1') == {'com.a', 'com.b'}
    assert engine.calls == [['pm', 'list', 'packages', '--user', '0']]


def test_list_packages_user0_bos_gecerli():
    engine = ShellEngine(_sabit('No packages found.\n'))
    assert engine.list_packages_user0('tv-1') == set()


def test_list_packages_user0_basarisiz_none():
    engine = ShellEngine(_sabit('', 1, 'failed'))
    assert engine.list_packages_user0('tv-1') is None

    engine2 = ShellEngine(_sabit('package:com.a\n', 0,
                                 'Security exception: denied'))
    assert engine2.list_packages_user0('tv-1') is None

    def patla(call):
        raise AdbError('kopuk')

    engine3 = ShellEngine(patla)
    assert engine3.list_packages_user0('tv-1') is None


def test_list_packages_user0_cozumlenemezse_none():
    engine = ShellEngine(_sabit('bozuk satir\n'))
    assert engine.list_packages_user0('tv-1') is None


def test_list_packages_bos_satirlar_atlanir():
    engine = ShellEngine(_sabit('package:com.a\n\n \npackage:com.b\n'))
    assert engine.list_packages('tv-1') == ['com.a', 'com.b']


# --- list_packages_detailed + onbellek ---------------------------------------

def _detay_handler(lines, user0=(), disabled=()):
    user0_out = ''.join('package:{}\n'.format(p) for p in user0)
    disabled_out = ''.join('package:{}\n'.format(p) for p in disabled)

    def handler(call):
        if call[:3] != ['pm', 'list', 'packages']:
            return None
        if '-f' in call:
            return AdbResult(0, lines, '')
        if '-d' in call:
            return AdbResult(0, disabled_out, '')
        return AdbResult(0, user0_out, '')

    return handler


def test_list_packages_detailed_ayristirir():
    lines = (
        'package:/data/app/~~abc==/com.a-xyz==/base.apk=com.a\n'
        'package:/system/app/B/B.apk=com.b\n'
        'package:/data/app/com.c/base.apk=com.c\n')
    engine = ShellEngine(_detay_handler(lines, user0=('com.a', 'com.b'),
                                        disabled=('com.c',)))
    out = engine.list_packages_detailed('tv-1')
    assert out == [
        {'package': 'com.a', 'apk': '/data/app/~~abc==/com.a-xyz==/base.apk',
         'enabled': True, 'installed_user0': True},
        {'package': 'com.b', 'apk': '/system/app/B/B.apk',
         'enabled': True, 'installed_user0': True},
        {'package': 'com.c', 'apk': '/data/app/com.c/base.apk',
         'enabled': False, 'installed_user0': False},
    ]
    assert engine.calls[0] == ['pm', 'list', 'packages', '-f', '-3', '-u',
                               '--user', '0']


def test_list_packages_detailed_bozuk_kayit():
    engine = ShellEngine(_detay_handler('package:/x.apk=com.a\nrastgele\n'))
    with pytest.raises(AdbError) as exc:
        engine.list_packages_detailed('tv-1')
    assert 'çözümlenemedi' in str(exc.value)

    engine2 = ShellEngine(_detay_handler('package:ayiricisiz\n'))
    with pytest.raises(AdbError) as exc2:
        engine2.list_packages_detailed('tv-1')
    assert 'bozuk kayıt' in str(exc2.value)


def test_list_packages_detailed_hata():
    engine = ShellEngine(_sabit('', 1, 'pm list packages başarısız'))
    with pytest.raises(AdbError) as exc:
        engine.list_packages_detailed('tv-1')
    assert 'okunamadı' in str(exc.value)


def test_list_packages_detailed_sistem_bos():
    engine = ShellEngine(_detay_handler(''))
    with pytest.raises(AdbError) as exc:
        engine.list_packages_detailed('tv-1', include_system=True)
    assert 'Sistem paket listesi boş' in str(exc.value)
    assert len(engine.calls) == 1


def test_list_packages_detailed_user0_okunamazsa():
    def handler(call):
        if call[:3] != ['pm', 'list', 'packages']:
            return None
        if '-f' in call:
            return AdbResult(0, 'package:/x.apk=com.a\n', '')
        return AdbResult(1, '', 'failed')

    engine = ShellEngine(handler)
    with pytest.raises(PackageStateUnknownError):
        engine.list_packages_detailed('tv-1')


def test_list_packages_detailed_disabled_okunamazsa():
    def handler(call):
        if call[:3] != ['pm', 'list', 'packages']:
            return None
        if '-f' in call:
            return AdbResult(0, 'package:/x.apk=com.a\n', '')
        if '-d' in call:
            return AdbResult(0, 'bozuk satir\n', '')
        return AdbResult(0, 'package:com.a\n', '')

    engine = ShellEngine(handler)
    with pytest.raises(PackageStateUnknownError):
        engine.list_packages_detailed('tv-1')

    def handler2(call):
        if call[:3] != ['pm', 'list', 'packages']:
            return None
        if '-f' in call:
            return AdbResult(0, 'package:/x.apk=com.a\n', '')
        if '-d' in call:
            return AdbResult(0, 'package:com.a\n', 'Security exception')
        return AdbResult(0, 'package:com.a\n', '')

    engine2 = ShellEngine(handler2)
    with pytest.raises(PackageStateUnknownError):
        engine2.list_packages_detailed('tv-1')


def test_list_packages_detailed_no_packages_satiri_atlanir():
    lines = 'no packages found\npackage:/x.apk=com.a\n'
    engine = ShellEngine(_detay_handler(lines, user0=('com.a',)))
    out = engine.list_packages_detailed('tv-1')
    assert [e['package'] for e in out] == ['com.a']


def test_list_packages_detailed_disabled_exit_hatasi():
    def handler(call):
        if call[:3] != ['pm', 'list', 'packages']:
            return None
        if '-f' in call:
            return AdbResult(0, 'package:/x.apk=com.a\n', '')
        if '-d' in call:
            return AdbResult(1, '', 'failed')
        return AdbResult(0, 'package:com.a\n', '')

    engine = ShellEngine(handler)
    with pytest.raises(PackageStateUnknownError) as exc:
        engine.list_packages_detailed('tv-1')
    assert 'Devre dışı paket listesi okunamadı' in str(exc.value)


def test_list_packages_detailed_disabled_istisnasi():
    def handler(call):
        if call[:3] != ['pm', 'list', 'packages']:
            return None
        if '-f' in call:
            return AdbResult(0, 'package:/x.apk=com.a\n', '')
        if '-d' in call:
            raise AdbError('kopuk')
        return AdbResult(0, 'package:com.a\n', '')

    engine = ShellEngine(handler)
    with pytest.raises(PackageStateUnknownError) as exc:
        engine.list_packages_detailed('tv-1')
    assert 'Devre dışı paket listesi okunamadı' in str(exc.value)


def test_list_packages_detailed_onbellek():
    engine = ShellEngine(_detay_handler('package:/x.apk=com.a\n',
                                        user0=('com.a',)))
    first = engine.list_packages_detailed('tv-1')
    ikinci = engine.list_packages_detailed('tv-1')
    assert ikinci == first
    assert ikinci is not first
    assert ikinci[0] is not first[0]
    assert len(engine.calls) == 3  # ikinci okuma cihaza gitmedi

    ikinci[0]['enabled'] = 'BOZUK'  # kopya uzerinde oynama onbellegi etkilemez
    assert engine.list_packages_detailed('tv-1')[0]['enabled'] is True


def test_list_packages_detailed_onbellek_kapatma():
    engine = ShellEngine(_detay_handler('package:/x.apk=com.a\n',
                                        user0=('com.a',)))
    engine.list_packages_detailed('tv-1')
    engine.list_packages_detailed('tv-1', use_cache=False)
    assert len(engine.calls) == 6


def test_invalidate_pkg_cache_hedefli():
    engine = ShellEngine(_detay_handler('package:/x.apk=com.a\n',
                                        user0=('com.a',)))
    engine.list_packages_detailed('tv-1')
    engine.list_packages_detailed('tv-2')
    assert len(engine.calls) == 6

    engine.invalidate_pkg_cache('tv-1')
    engine.list_packages_detailed('tv-1')  # yeniden okur
    engine.list_packages_detailed('tv-2')  # onbellekten gelir
    assert len(engine.calls) == 9


def test_pkg_cache_bayat_nesil_reddedilir():
    engine = ShellEngine(lambda call: None)

    gen = AdbEngine._pkg_cache_gen
    engine.invalidate_pkg_cache()
    assert engine._pkg_cache_put('tv-1', False, [{'a': 1}], gen) is False
    assert engine._pkg_cache_get('tv-1', False)[0] is None

    yeni_gen = AdbEngine._pkg_cache_gen
    assert engine._pkg_cache_put('tv-1', False, [{'a': 1}], yeni_gen) is True
    assert engine._pkg_cache_get('tv-1', False)[0] == [{'a': 1}]

    engine.invalidate_pkg_cache()
    assert engine._pkg_cache_get('tv-1', False)[0] is None


# --- ps / calisan surecler ---------------------------------------------------

@pytest.mark.parametrize('output, beklenen', [
    ('', False),
    (None, False),
    ('ps: unknown option\n', False),
    ('toybox: not found\n', False),
    ('error: device offline\n', False),
    ('USER PID NAME\n', False),
    ('com.a\n', True),
    ('root 1 init\n', True),
])
def test_has_process_rows(output, beklenen):
    assert AdbEngine._has_process_rows(output) is beklenen


def test_parse_running_packages_name_only():
    out = 'com.a\n\n \ncom.b:service\ngecersiz-satir\n'
    assert AdbEngine.parse_running_packages(out) == {'com.a', 'com.b'}


def test_parse_running_packages_known_liste():
    out = 'com.a\ncom.ab\n'
    assert AdbEngine.parse_running_packages(out) == {'com.a', 'com.ab'}
    # Alt-string hatasi olmamali: 'com.a' ile 'com.ab' karismaz.
    assert AdbEngine.parse_running_packages(
        out, known_packages=['com.a']) == {'com.a'}
    assert AdbEngine.parse_running_packages(out, known_packages=[]) == set()


def test_parse_running_packages_tam_tablo():
    out = 'USER PID NAME\nroot 123 com.a\nsystem 456 com.b:svc\n'
    assert AdbEngine.parse_running_packages(out) == {'com.a', 'com.b'}


def test_parse_running_packages_bos():
    assert AdbEngine.parse_running_packages('') == set()
    assert AdbEngine.parse_running_packages(None) == set()


def test_running_processes_ilk_yol():
    engine = ShellEngine(_sabit('com.a\ncom.b\n'))
    assert engine.running_processes('tv-1') == 'com.a\ncom.b\n'
    assert engine.calls == [['ps', '-A', '-o', 'NAME']]


def test_running_processes_fallback():
    def handler(call):
        if call == ['ps', '-A', '-o', 'NAME']:
            return AdbResult(1, '', 'unknown option')
        if call == ['ps', '-A']:
            return AdbResult(0, 'USER PID NAME\nroot 1 init\n', '')
        return None

    engine = ShellEngine(handler)
    assert 'init' in engine.running_processes('tv-1')
    assert engine.calls == [['ps', '-A', '-o', 'NAME'], ['ps', '-A']]


def test_running_processes_okunamazsa():
    engine = ShellEngine(_sabit('', 1, 'ps: not found'))
    with pytest.raises(AdbError) as exc:
        engine.running_processes('tv-1')
    assert 'okunamadı' in str(exc.value)


def test_is_running_durumlar():
    engine = ShellEngine(_sabit('1234\n'))
    assert engine.is_running('tv-1', 'com.a') is True
    assert engine.calls == [['pidof', 'com.a']]

    engine2 = ShellEngine(_sabit('', 1, ''))
    assert engine2.is_running('tv-1', 'com.a') is False

    engine3 = ShellEngine(_sabit('kapatildi\n'))
    assert engine3.is_running('tv-1', 'com.a') is False

    def patla(call):
        raise AdbError('kopuk')

    engine4 = ShellEngine(patla)
    assert engine4.is_running('tv-1', 'com.a') is False


# --- app_labels --------------------------------------------------------------

def test_app_labels_bicimler():
    out = (
        'Package [ com.a ]:\n'
        '  application-label: Dost Uygulama\n'
        'Package [ com.b ]:\n'
        '  application-label-tr: Yerel Ad\n'
        'Package [ com.c ]:\n'
        '  application-label: com.c\n'
        'Package [ com.d ]:\n'
        '  nonLocalizedLabel="Non Lokal"\n'
    )
    engine = ShellEngine(_sabit(out))
    assert engine.app_labels('tv-1') == {
        'com.a': 'Dost Uygulama', 'com.b': 'Yerel Ad', 'com.d': 'Non Lokal'}
    assert engine.calls == [['dumpsys', 'package']]


def test_app_labels_oncelik():
    out = (
        'Package [ com.a ]:\n'
        '  nonLocalizedLabel="Gecici"\n'
        '  application-label-de: Yerel\n'
        '  application-label: Dogru Ad\n'
    )
    engine = ShellEngine(_sabit(out))
    assert engine.app_labels('tv-1') == {'com.a': 'Dogru Ad'}


def test_app_labels_gecersiz_etiketler():
    out = (
        'Package [ com.a ]:\n  application-label: @0x7f0d0001\n'
        'Package [ com.b ]:\n  application-label: com.other.app\n'
        'Package [ com.c ]:\n  application-label: (null)\n'
        'Package [ com.d ]:\n  application-label: "Tirnakli  Ad"\n'
        'Package [ com.e ]:\n  application-label: null\n'
    )
    engine = ShellEngine(_sabit(out))
    assert engine.app_labels('tv-1') == {'com.d': 'Tirnakli Ad'}


def test_app_labels_bilinmeyen_baslik_sifirlar():
    out = (
        'Package [ com.a ]:\n'
        '  application-label: Gecerli\n'
        'Package vendor specific section\n'
        '  application-label: Sizinti\n'
    )
    engine = ShellEngine(_sabit(out))
    assert engine.app_labels('tv-1') == {'com.a': 'Gecerli'}


def test_app_labels_gecersiz_paket_basligi_atlanir():
    out = (
        'Package [ kotu-paket ]:\n'
        '  application-label: Gizli\n'
        'Package [ com.a:remote ]:\n'
        '  application-label: Uzak\n'
        'Package [ com.b ]:\n'
        '  application-label: Gecerli\n'
    )
    engine = ShellEngine(_sabit(out))
    assert engine.app_labels('tv-1') == {'com.b': 'Gecerli'}


def test_app_labels_bos_satirlar_atlanir():
    out = 'Package [ com.a ]:\n\n\n  application-label: Ad\n'
    engine = ShellEngine(_sabit(out))
    assert engine.app_labels('tv-1') == {'com.a': 'Ad'}


def test_app_labels_baslik_varyantlari():
    out = (
        'Package: com.h1\n'
        '  application-label: Bir\n'
        'Package com.h2 {\n'
        '  application-label: Iki\n'
        'Package { 0abc com.h3 }\n'
        '  application-label: Uc\n'
    )
    engine = ShellEngine(_sabit(out))
    assert engine.app_labels('tv-1') == {
        'com.h1': 'Bir', 'com.h2': 'Iki', 'com.h3': 'Uc'}


def test_app_labels_badging_bicimi():
    out = "Package [ com.a ]:\napplication: label='Rozet Ad'\n"
    engine = ShellEngine(_sabit(out))
    assert engine.app_labels('tv-1') == {'com.a': 'Rozet Ad'}


def test_app_labels_istisna_bos():
    def patla(call):
        raise AdbError('kopuk')

    engine = ShellEngine(patla)
    assert engine.app_labels('tv-1') == {}


# --- arka plan kisitlama -----------------------------------------------------

def test_bulk_restricted_toplar():
    def handler(call):
        if call[-1] == 'ignore':
            return AdbResult(0, 'com.a\ncom.b\n', '')
        return AdbResult(0, 'No operations found.\n', '')

    engine = ShellEngine(handler)
    assert engine.bulk_restricted('tv-1') == {'com.a', 'com.b'}
    assert len(engine.calls) == 6
    assert engine.calls[0] == ['cmd', 'appops', 'query-op', '--user', '0',
                               'RUN_IN_BACKGROUND', 'ignore']


def test_bulk_restricted_hata_none():
    engine = ShellEngine(_sabit('', 1, 'error'))
    assert engine.bulk_restricted('tv-1') is None

    engine2 = ShellEngine(_sabit('', 0, 'Unknown operation'))
    assert engine2.bulk_restricted('tv-1') is None


def test_bulk_restricted_bozuk_satir():
    engine = ShellEngine(_sabit('gecersiz satir\n'))
    assert engine.bulk_restricted('tv-1') is None


@pytest.mark.parametrize('modes, beklenen', [
    (['allow', 'allow'], 'Serbest'),
    (['allow', 'default'], 'Serbest'),
    (['ignore', 'allow'], 'Kisitli'),
    (['deny', 'deny'], 'Kisitli'),
    (['foreground', 'allow'], 'Kisitli'),
    (['errored', 'allow'], 'Kisitli'),
    ([None, 'allow'], 'Bilinmiyor'),
    (['allow', None], 'Bilinmiyor'),
    ([None, None], 'Bilinmiyor'),
])
def test_classify_background_modes(modes, beklenen):
    assert AdbEngine._classify_background_modes(modes) == beklenen


def test_background_mode_okuma():
    engine = ShellEngine(_sabit('RUN_IN_BACKGROUND: allow\n'))
    assert engine._background_mode(
        'tv-1', 'com.a', 'RUN_IN_BACKGROUND') == 'allow'
    assert engine.calls == [['cmd', 'appops', 'get', '--user', '0', 'com.a',
                             'RUN_IN_BACKGROUND']]


def test_background_mode_errored_deny():
    engine = ShellEngine(_sabit('RUN_IN_BACKGROUND: errored\n'))
    assert engine._background_mode(
        'tv-1', 'com.a', 'RUN_IN_BACKGROUND') == 'deny'


def test_background_mode_no_operations():
    engine = ShellEngine(_sabit('No operations.\n'))
    assert engine._background_mode(
        'tv-1', 'com.a', 'RUN_IN_BACKGROUND') == 'default'


def test_background_mode_dogrulanamaz():
    engine = ShellEngine(_sabit('alakasiz cikti\n'))
    with pytest.raises(AdbError):
        engine._background_mode('tv-1', 'com.a', 'RUN_IN_BACKGROUND')

    engine2 = ShellEngine(_sabit('RUN_IN_BACKGROUND: allow\n', 0,
                                 'Security exception'))
    with pytest.raises(AdbError):
        engine2._background_mode('tv-1', 'com.a', 'RUN_IN_BACKGROUND')


def test_app_status_fallback_durumlar():
    engine = ShellEngine(
        lambda call: AdbResult(0, '{}: allow\n'.format(call[-1]), ''))
    assert engine.app_status_fallback('tv-1', 'com.a') == 'Serbest'

    engine2 = ShellEngine(
        lambda call: AdbResult(0, '{}: ignore\n'.format(call[-1]), ''))
    assert engine2.app_status_fallback('tv-1', 'com.a') == 'Kisitli'

    def patla(call):
        raise AdbError('kopuk')

    engine3 = ShellEngine(patla)
    assert engine3.app_status_fallback('tv-1', 'com.a') == 'Bilinmiyor'


def test_app_status_statigi():
    assert AdbEngine.app_status(None, 'com.a') == 'Bilinmiyor'
    assert AdbEngine.app_status({'com.a'}, 'com.a') == 'Kisitli'
    assert AdbEngine.app_status(set(), 'com.a') == 'Serbest'


# --- app_detail / app_size ---------------------------------------------------

def test_app_detail_ayristirir():
    out = (
        'Packages:\n'
        '  Package [com.a]:\n'
        '    versionName=1.2.3\n'
        '    versionCode=123\n'
        '    installerPackageName=com.market\n'
        '    firstInstallTime=2020-01-01 00:00:00\n'
        '    lastUpdateTime=2021-02-02 00:00:00\n'
        '    codePath=/data/app/com.a\n'
        '    dataDir=/data/user/0/com.a\n'
        '    runtime permissions:\n'
        '    USER 0: granted=true\n'
        '    runtime permissions:\n'
    )
    engine = ShellEngine(_sabit(out))
    d = engine.app_detail('tv-1', 'com.a')
    assert d['package'] == 'com.a'
    assert d['versionName'] == '1.2.3'
    assert d['versionCode'] == '123'
    assert d['installer'] == 'com.market'
    assert d['firstInstall'] == '2020-01-01 00:00:00'
    assert d['lastUpdate'] == '2021-02-02 00:00:00'
    assert d['codePath'] == '/data/app/com.a'
    assert d['dataDir'] == '/data/user/0/com.a'
    assert d['enabled'] is True
    assert d['perm_blocks'] == 2
    assert d['granted_hint'] == 'true'
    assert d['raw_head'].startswith('Packages:')
    assert engine.calls == [['dumpsys', 'package', 'com.a']]


def test_app_detail_varsayilanlar_ve_disabled():
    engine = ShellEngine(_sabit('Package [com.a]\n'))
    d = engine.app_detail('tv-1', 'com.a')
    assert d['versionName'] == '?'
    assert d['versionCode'] == '?'
    assert d['installer'] == 'bilinmiyor'
    assert d['enabled'] is True
    assert d['granted_hint'] == '?'
    assert d['perm_blocks'] == 0

    engine2 = ShellEngine(_sabit('Package [com.a]\n  enabled=false\n'))
    assert engine2.app_detail('tv-1', 'com.a')['enabled'] is False

    engine3 = ShellEngine(_sabit('Package [com.a]\n  enabledState=DISABLED\n'))
    assert engine3.app_detail('tv-1', 'com.a')['enabled'] is False


def test_app_detail_bulunamazsa_ve_gecersiz():
    engine = ShellEngine(_sabit('Unable to find package com.a\n'))
    with pytest.raises(AdbError) as exc:
        engine.app_detail('tv-1', 'com.a')
    assert 'bulunamadı' in str(exc.value)

    engine2 = ShellEngine(_sabit(''))
    with pytest.raises(AdbError):
        engine2.app_detail('tv-1', 'com.a')

    engine3 = ShellEngine(_sabit('x'))
    with pytest.raises(AdbError) as exc3:
        engine3.app_detail('tv-1', 'gecersiz paket')
    assert 'Geçersiz paket adi' in str(exc3.value)
    assert engine3.calls == []


def test_app_size_kb():
    def handler(call):
        if call[0] == 'dumpsys':
            return AdbResult(0, 'dataDir=/data/user/0/com.a\n', '')
        if call[0] == 'du':
            return AdbResult(0, '1234\t/data/user/0/com.a\n', '')
        return None

    engine = ShellEngine(handler)
    assert engine.app_size('tv-1', 'com.a') == 1234
    assert engine.calls[1][0] == 'du'


def test_app_size_basarisiz_none():
    def handler(call):
        if call[0] == 'dumpsys':
            return AdbResult(1, '', '')
        return AdbResult(1, '', 'du yok')

    engine = ShellEngine(handler)
    assert engine.app_size('tv-1', 'com.a') is None


def test_app_size_du_istisnasi_none():
    def handler(call):
        if call[0] == 'dumpsys':
            return AdbResult(0, 'dataDir=/data/user/0/com.a\n', '')
        raise AdbError('du kopuk')

    engine = ShellEngine(handler)
    assert engine.app_size('tv-1', 'com.a') is None


# --- foreground_package / screenshot ----------------------------------------

def test_foreground_package_activity():
    out = '  topResumedActivity=ActivityRecord{u0 com.a/.Main t123}\n'
    engine = ShellEngine(_sabit(out))
    assert engine.foreground_package('tv-1') == 'com.a'
    assert engine.calls == [['dumpsys', 'activity', 'activities']]


def test_foreground_package_window_fallback():
    def handler(call):
        if call[1] == 'activity':
            return AdbResult(0, 'alakasiz\n', '')
        if call[1] == 'window':
            return AdbResult(0, '  mCurrentFocus=Window{a1b2 u0 com.b/.F}\n', '')
        return None

    engine = ShellEngine(handler)
    assert engine.foreground_package('tv-1') == 'com.b'


def test_foreground_package_bulunamazsa():
    engine = ShellEngine(_sabit('bos\n'))
    assert engine.foreground_package('tv-1') == ''

    def patla(call):
        raise AdbError('kopuk')

    engine2 = ShellEngine(patla)
    assert engine2.foreground_package('tv-1') == ''


def test_screenshot_via_file_indirir_ve_uzak_dosyayi_siler():
    png = _png_bytes()

    def handler(call):
        if call[:2] == ['screencap', '-p']:
            return AdbResult(0, '', '')
        if call[:3] == ['-s', 'tv-1', 'pull']:
            with open(call[4], 'wb') as f:
                f.write(png)
            return AdbResult(0, '', '')
        if call[0] == 'rm':
            return AdbResult(0, '', '')
        return None

    engine = ShellEngine(handler)
    assert engine.screenshot_via_file('tv-1') == png
    assert engine.calls[-1][0] == 'rm'
    assert 'mibox_scr_' in engine.calls[-1][1]


def test_screenshot_via_file_bozuk_png_hata_verir():
    def handler(call):
        if call[:2] == ['screencap', '-p']:
            return AdbResult(0, '', '')
        if call[:3] == ['-s', 'tv-1', 'pull']:
            with open(call[4], 'wb') as f:
                f.write(b'bozuk')
            return AdbResult(0, '', '')
        if call[0] == 'rm':
            return AdbResult(0, '', '')
        return None

    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.screenshot_via_file('tv-1')
    assert 'bozuk indi' in str(exc.value)
    assert engine.calls[-1][0] == 'rm'


def test_screenshot_via_file_screencap_hatasi():
    def handler(call):
        if call[:2] == ['screencap', '-p']:
            return AdbResult(1, '', 'screencap yok')
        if call[0] == 'rm':
            return AdbResult(0, '', '')
        return None

    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.screenshot_via_file('tv-1')
    assert 'screencap başarısız' in str(exc.value)


def test_screenshot_execout_yedegi():
    png = _png_bytes()

    def handler(call):
        if call[:2] == ['screencap', '-p']:
            return AdbResult(1, '', 'yok')
        if call[0] == 'rm':
            return AdbResult(0, '', '')
        if 'exec-out' in call:
            return AdbResult(0, png, '')
        return None

    engine = ShellEngine(handler)
    assert engine.screenshot('tv-1') == png


def test_screenshot_tamamen_basarisiz():
    def handler(call):
        if call[:2] == ['screencap', '-p']:
            return AdbResult(1, '', 'yok')
        if call[0] == 'rm':
            return AdbResult(0, '', '')
        if 'exec-out' in call:
            return AdbResult(1, '', 'yok')
        return None

    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.screenshot('tv-1')
    assert 'Ekran goruntusu alinamadi' in str(exc.value)


# --- logcat / trim -----------------------------------------------------------

def test_logcat_dump_filtreler():
    engine = ShellEngine(_sabit('satir\n'))
    assert engine.logcat_dump('tv-1', lines=50, level='e',
                              tag='MyTag') == 'satir\n'
    assert engine.calls == [['logcat', '-d', '-v', 'brief', '*:E', 'MyTag',
                             '-t', '50']]


def test_logcat_dump_gecersiz_girdi():
    engine = ShellEngine(_sabit('x'))
    with pytest.raises(AdbError):
        engine.logcat_dump('tv-1', level='X')
    with pytest.raises(AdbError):
        engine.logcat_dump('tv-1', tag='kötü etiket')
    assert engine.calls == []


def test_logcat_dump_hata():
    engine = ShellEngine(_sabit('', 1, 'logcat yok'))
    with pytest.raises(AdbError) as exc:
        engine.logcat_dump('tv-1')
    assert 'logcat yok' in str(exc.value)


def test_logcat_crash_argumanlari():
    engine = ShellEngine(_sabit('crash\n'))
    assert engine.logcat_crash('tv-1', lines=10) == 'crash\n'
    assert engine.calls == [['logcat', '-d', '-v', 'brief', '-t', '10',
                             'AndroidRuntime:E', '*:F', '*:S']]


def test_logcat_clear():
    engine = ShellEngine(_sabit('ok'))
    engine.logcat_clear('tv-1')
    assert engine.calls == [['logcat', '-c']]

    engine2 = ShellEngine(_sabit('', 1, 'temizlenemedi'))
    with pytest.raises(AdbError) as exc:
        engine2.logcat_clear('tv-1')
    assert 'temizlenemedi' in str(exc.value)


def test_trim_caches():
    engine = ShellEngine(_sabit('trim ok'))
    result = engine.trim_caches('tv-1')
    assert result.output == 'trim ok'
    assert engine.calls == [['pm', 'trim-caches', '999G']]

    engine2 = ShellEngine(_sabit('', 1, 'trim yok'))
    with pytest.raises(AdbError) as exc:
        engine2.trim_caches('tv-1')
    assert 'trim yok' in str(exc.value)


# --- file_list ---------------------------------------------------------------

def test_file_list_iso_tarih():
    out = (
        'total 8\n'
        'drwxr-xr-x 2 root root 4096 2026-01-02 03:04 Klasor\n'
        '-rw-r--r-- 1 root root 123 2026-01-02 03:04 dosya.txt\n'
        'lrwxrwxrwx 1 root root 5 2026-01-02 03:04 link -> /hedef\n'
    )
    engine = ShellEngine(_sabit(out))
    entries = engine.file_list('tv-1', '/sdcard')
    assert entries == [
        {'name': 'Klasor', 'size': 4096, 'dir': True,
         'perm': 'drwxr-xr-x', 'mtime': '2026-01-02 03:04'},
        {'name': 'dosya.txt', 'size': 123, 'dir': False,
         'perm': '-rw-r--r--', 'mtime': '2026-01-02 03:04'},
        {'name': 'link', 'size': 5, 'dir': False,
         'perm': 'lrwxrwxrwx', 'mtime': '2026-01-02 03:04'},
    ]
    assert engine.calls[0][:2] == ['ls', '-la']
    assert '/sdcard/' in engine.calls[0][2]


def test_file_list_mon_tarih_ve_bosluklu_ad():
    out = (
        '-rw-r--r-- 1 root root 42 Jan  2 03:04 eski.txt\n'
        '-rw-r--r-- 1 root root 1 Jan  2 2025 iki  bosluk.txt\n'
    )
    engine = ShellEngine(_sabit(out))
    entries = engine.file_list('tv-1', '/sdcard')
    assert entries == [
        {'name': 'eski.txt', 'size': 42, 'dir': False,
         'perm': '-rw-r--r--', 'mtime': 'Jan 2 03:04'},
        {'name': 'iki  bosluk.txt', 'size': 1, 'dir': False,
         'perm': '-rw-r--r--', 'mtime': 'Jan 2 2025'},
    ]


def test_file_list_siralama_ve_atlananlar():
    out = (
        'total 4\n'
        'bozuk satir\n'
        'drwxr-xr-x 2 root root 4096 2026-01-02 03:04 zzz_dir\n'
        '-rw-r--r-- 1 root root 1 2026-01-02 03:04 Ada.txt\n'
        '?rw-r--r-- 1 root root 1 2026-01-02 03:04 permbozuk.txt\n'
        '-rw-r--r-- 1 root root 1 tarihsiz.txt\n'
        'drwxr-xr-x 2 root root 4096 2026-01-02 03:04 .\n'
        'drwxr-xr-x 2 root root 4096 2026-01-02 03:04 ..\n'
    )
    engine = ShellEngine(_sabit(out))
    entries = engine.file_list('tv-1', '/sdcard')
    assert [e['name'] for e in entries] == ['zzz_dir', 'Ada.txt']


def test_file_list_hata():
    engine = ShellEngine(_sabit('', 1, 'ls: no such file'))
    with pytest.raises(AdbError) as exc:
        engine.file_list('tv-1', '/sdcard')
    assert 'ls: no such file' in str(exc.value)


# --- kullanicilar / depolama / autorun / izinler / saglik / cihaz ------------

def test_list_users_ayristirir():
    out = 'UserInfo{0:Owner:13} running\nUserInfo{10:Gezgin:13}\n'
    engine = ShellEngine(_sabit(out))
    assert engine.list_users('tv-1') == [
        {'id': 0, 'name': 'Owner', 'running': True},
        {'id': 10, 'name': 'Gezgin', 'running': False}]
    assert engine.calls == [['pm', 'list', 'users']]


def test_list_users_varsayilan():
    engine = ShellEngine(_sabit(''))
    assert engine.list_users('tv-1') == [
        {'id': 0, 'name': 'Owner', 'running': True}]

    def patla(call):
        raise AdbError('kopuk')

    engine2 = ShellEngine(patla)
    assert engine2.list_users('tv-1') == [
        {'id': 0, 'name': 'Owner', 'running': True}]


def test_storage_top_sirala_ve_kirp():
    out = '100\t/sdcard/a\n3000\t/sdcard/b\n200\t/sdcard/c\n'
    engine = ShellEngine(_sabit(out))
    assert engine.storage_top('tv-1', limit=2) == [
        {'path': '/sdcard/b', 'kb': 3000},
        {'path': '/sdcard/c', 'kb': 200}]
    assert engine.calls == [['du', '-sk', '/sdcard/*']]


def test_storage_top_ikinci_kok():
    def handler(call):
        if call[-1] == '/sdcard/*':
            return AdbResult(1, '', 'du yok')
        if call[-1] == '/data/media/0/*':
            return AdbResult(0, '5\t/media/x\n', '')
        return None

    engine = ShellEngine(handler)
    assert engine.storage_top('tv-1') == [{'path': '/media/x', 'kb': 5}]


def test_storage_top_bozuk_cikti():
    engine = ShellEngine(_sabit('bozuk satir\n'))
    with pytest.raises(AdbError) as exc:
        engine.storage_top('tv-1')
    assert 'Depolama taraması tamamlanamadı' in str(exc.value)
    assert len(engine.calls) == 2


def test_storage_top_shell_istisnasi():
    def patla(call):
        raise AdbError('du kopuk')

    engine = ShellEngine(patla)
    with pytest.raises(AdbError) as exc:
        engine.storage_top('tv-1')
    assert 'du kopuk' in str(exc.value)
    assert len(engine.calls) == 2


def test_storage_top_bos_satir_atlanir():
    def handler(call):
        if call[:2] == ['du', '-sk']:
            return AdbResult(0, '1234\t/sdcard/a\n\n', '')
        return None

    engine = ShellEngine(handler)
    assert engine.storage_top('tv-1') == [{'path': '/sdcard/a', 'kb': 1234}]


def test_autorun_receivers_query():
    out = 'com.a/.BootReceiver\ncom.b/.R\nbozuk satir\n'
    engine = ShellEngine(_sabit(out))
    assert engine.autorun_receivers('tv-1') == {
        'com.a': ['com.a/.BootReceiver'], 'com.b': ['com.b/.R']}
    assert engine.calls == [['cmd', 'package', 'query-receivers', '--brief',
                             '-a', 'android.intent.action.BOOT_COMPLETED']]


def test_autorun_receivers_dumpsys_yedegi():
    def handler(call):
        if call[0] == 'cmd':
            raise AdbError('desteklenmiyor')
        if call[:3] == ['dumpsys', 'package', 'receivers']:
            return AdbResult(0,
                             'com.a/.ReceiverOne\n'
                             '  android.intent.action.BOOT_COMPLETED\n'
                             'com.b/.ReceiverTwo\n'
                             '  android.intent.action.OTHER\n', '')
        return None

    engine = ShellEngine(handler)
    assert engine.autorun_receivers('tv-1') == {'com.a': []}


def test_autorun_receivers_son_paket_boot():
    def handler(call):
        if call[0] == 'cmd':
            raise AdbError('desteklenmiyor')
        if call[:3] == ['dumpsys', 'package', 'receivers']:
            return AdbResult(0,
                             'com.a/.ReceiverOne\n'
                             '  android.intent.action.BOOT_COMPLETED\n', '')
        return None

    engine = ShellEngine(handler)
    assert engine.autorun_receivers('tv-1') == {'com.a': []}


def test_autorun_receivers_ikisi_de_okunamazsa():
    def handler(call):
        raise AdbError('kapali')

    engine = ShellEngine(handler)
    assert engine.autorun_receivers('tv-1') == {}


def test_app_permissions_ayristirir():
    out = (
        'install permissions:\n'
        '  android.permission.INTERNET: granted=true\n'
        'runtime permissions:\n'
        '  android.permission.CAMERA: granted=false\n'
        '  android.permission.LOCATION: granted=true\n'
        'SomeSection:\n'
    )
    engine = ShellEngine(_sabit(out))
    res = engine.app_permissions('tv-1', 'com.a')
    assert res['granted'] == ['android.permission.INTERNET',
                              'android.permission.LOCATION']
    assert res['all'] == [
        {'perm': 'android.permission.INTERNET', 'granted': True},
        {'perm': 'android.permission.CAMERA', 'granted': False},
        {'perm': 'android.permission.LOCATION', 'granted': True}]


def test_app_permissions_bos():
    engine = ShellEngine(_sabit(''))
    assert engine.app_permissions('tv-1', 'com.a') == {
        'all': [], 'granted': []}


def test_health_ozet():
    def handler(call):
        if call[:2] == ['df', '/data']:
            return AdbResult(0, '/dev/block/x 1000 200 700 30% /data\n', '')
        if call[:2] == ['cat', '/proc/meminfo']:
            return AdbResult(
                0, 'MemTotal:       2000 kB\nMemAvailable:    500 kB\n', '')
        if call[:3] == ['pm', 'list', 'packages'] and '-f' in call:
            return AdbResult(
                0, 'package:/x.apk=com.a\npackage:/y.apk=com.b\n', '')
        if call == ['pm', 'list', 'packages', '--user', '0']:
            return AdbResult(0, 'package:com.a\n', '')
        if call == ['pm', 'list', 'packages', '--user', '0', '-d']:
            return AdbResult(0, 'package:com.b\n', '')
        return None

    engine = ShellEngine(handler)
    assert engine.health('tv-1') == {
        'disk_total_kb': 1000, 'disk_avail_kb': 700, 'disk_pct': 30,
        'mem_total_kb': 2000, 'mem_avail_kb': 500, 'mem_pct': 75,
        'pkg_total': 2, 'pkg_disabled': 1, 'pkg_removed_u0': 1}


def test_health_kismi_ve_bos():
    def handler(call):
        if call[:2] == ['df', '/data']:
            return AdbResult(0, '/dev/x 100 10 90 10% /data\n', '')
        return AdbResult(1, '', '')

    engine = ShellEngine(handler)
    assert engine.health('tv-1') == {
        'disk_total_kb': 100, 'disk_avail_kb': 90, 'disk_pct': 10}

    engine2 = ShellEngine(_sabit('', 1, 'yok'))
    assert engine2.health('tv-1') == {}


def test_health_df_istisnasi():
    def handler(call):
        if call[:2] == ['df', '/data']:
            raise AdbError('df kopuk')
        return AdbResult(1, '', '')

    engine = ShellEngine(handler)
    assert engine.health('tv-1') == {}


def test_health_meminfo_istisnasi():
    def handler(call):
        if call[:2] == ['df', '/data']:
            return AdbResult(0, '/dev/x 100 10 90 10% /data\n', '')
        raise AdbError('meminfo kopuk')

    engine = ShellEngine(handler)
    assert engine.health('tv-1') == {
        'disk_total_kb': 100, 'disk_avail_kb': 90, 'disk_pct': 10}


def test_device_info_props_ve_ram():
    def handler(call):
        if call[0] == 'getprop':
            return AdbResult(0, 'deger-' + call[1] + '\n', '')
        if call[:2] == ['cat', '/proc/meminfo']:
            return AdbResult(0, 'MemTotal: 4096 kB\n', '')
        return None

    engine = ShellEngine(handler)
    info = engine.device_info('tv-1')
    assert info['ro.product.model'] == 'deger-ro.product.model'
    assert info['ro.build.version.sdk'] == 'deger-ro.build.version.sdk'
    assert info['mem_total_kb'] == '4096'


def test_device_info_hatalarda_bos_ve_soru():
    def handler(call):
        if call[0] == 'getprop' and call[1] == 'ro.product.model':
            raise AdbError('yok')
        if call[0] == 'getprop':
            return AdbResult(0, 'x\n', '')
        if call[:2] == ['cat', '/proc/meminfo']:
            return AdbResult(1, '', '')
        return None

    engine = ShellEngine(handler)
    info = engine.device_info('tv-1')
    assert info['ro.product.model'] == ''
    assert info['ro.product.brand'] == 'x'
    assert info['mem_total_kb'] == '?'


def test_device_info_meminfo_istisnasi():
    def handler(call):
        if call[0] == 'getprop':
            return AdbResult(0, 'x\n', '')
        raise AdbError('meminfo kopuk')

    engine = ShellEngine(handler)
    info = engine.device_info('tv-1')
    assert info['ro.product.model'] == 'x'
    assert info['mem_total_kb'] == '?'


# --- launcher / animasyon ----------------------------------------------------

def test_launcher_apps_filtreler():
    out = 'com.a/.MainActivity\ngecersiz satir\ncom.b\n'
    engine = ShellEngine(_sabit(out))
    assert engine.launcher_apps('tv-1') == ['com.a/.MainActivity']
    assert engine.calls == [['cmd', 'package', 'query-activities', '--brief',
                             '-a', 'android.intent.action.MAIN', '-c',
                             'android.intent.category.HOME']]


def test_launcher_apps_hata_bos():
    def patla(call):
        raise AdbError('kopuk')

    engine = ShellEngine(patla)
    assert engine.launcher_apps('tv-1') == []


def test_animator_scales_okuma():
    degerler = {'window_animation_scale': '1',
                'transition_animation_scale': '0.5',
                'animator_duration_scale': '1.0'}

    def handler(call):
        if call[:3] == ['settings', 'get', 'global']:
            return AdbResult(0, degerler[call[3]] + '\n', '')
        return None

    engine = ShellEngine(handler)
    assert engine.animator_scales('tv-1') == degerler


def test_animator_scales_gecersiz_deger_soru():
    beklenen = {'window_animation_scale': '?',
                'transition_animation_scale': '?',
                'animator_duration_scale': '?'}

    engine = ShellEngine(_sabit('null\n'))
    assert engine.animator_scales('tv-1') == beklenen

    engine2 = ShellEngine(_sabit('1\n', 0, 'error: denied'))
    assert engine2.animator_scales('tv-1') == beklenen

    engine3 = ShellEngine(_sabit('', 1))
    assert engine3.animator_scales('tv-1') == beklenen


def test_animator_scales_istisnasi_soru():
    def patla(call):
        raise AdbError('kopuk')

    engine = ShellEngine(patla)
    assert engine.animator_scales('tv-1') == {
        'window_animation_scale': '?',
        'transition_animation_scale': '?',
        'animator_duration_scale': '?'}
