# -*- coding: utf-8 -*-
"""AdbEngine yazma yollari ve guvenlik kontrolleri (FakeEngine: ADB yok).

Kapsam: korunan yol mantigi, dosya silme/olusturma/yeniden adlandirma,
paket yazma komutlari (force-stop, clear, enable yolu), girdi komutlari
(keyevent, input text, tap, swipe), arka plan kisitlama yazimi ve geri
alma, animasyon olcegi dogrulama/geri alma, ekran bilgisi ayristirma,
URL acma, eslestirme/baglanti dogrulamalari. Ag veya cihaz kullanilmaz.
"""
import shlex

import pytest

from mibox_app.adb_engine import AdbEngine, AdbError, AdbResult


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
    return lambda call: AdbResult(exit_code, output, error)


# --- korunan yol / hedef tanima (saf) ---------------------------------------

@pytest.mark.parametrize('path, beklenen', [
    ('/', True),
    ('/sdcard', True),
    ('/storage/emulated/0', True),
    ('/storage/emulated/10', True),
    ('/data/media/0', True),
    ('/mnt/user/0', True),
    ('/mnt/user/5/primary', True),
    ('/mnt/runtime/read/emulated/0', True),
    ('/mnt/shell/emulated/0', True),
    ('/storage/ABCD-1234', True),
    ('/mnt/expand/ABCD', True),
    ('/sdcard/DCIM', False),
    ('/storage/emulated/0/Android/data', False),
    ('/data/media/0/Movies', False),
    ('/mnt/user/0/primary/Download', False),
])
def test_protected_file_path(path, beklenen):
    assert AdbEngine._is_protected_file_path(path) is beklenen


@pytest.mark.parametrize('target, beklenen', [
    ('192.168.1.5:5555', True),
    ('host:1', True),
    ('emulator-5554', False),
    ('R58M12345', False),
    ('192.168.1.5', False),
    ('host:', False),
    ('host:abc', False),
    ('a b:5555', False),
])
def test_is_network_target(target, beklenen):
    assert AdbEngine._is_network_target(target) is beklenen


# --- dosya islemleri ---------------------------------------------------------

def test_file_remove_korunan_kok_reddedilir():
    engine = ShellEngine(_sabit('x'))
    with pytest.raises(AdbError) as exc:
        engine.file_remove('tv-1', '/sdcard')
    assert 'silinemez' in str(exc.value)
    assert engine.calls == []


def test_file_remove_ust_dizin_dogrulanamazsa():
    engine = ShellEngine(_sabit('', 1, 'readlink yok'))
    with pytest.raises(AdbError) as exc:
        engine.file_remove('tv-1', '/sdcard/DCIM/IMG.jpg')
    assert 'üst dizini doğrulanamadı' in str(exc.value)


def test_file_remove_basarili():
    def handler(call):
        if call[:3] == ['readlink', '-f', '/sdcard/DCIM']:
            return AdbResult(0, '/sdcard/DCIM\n', '')
        if call[0] == 'rm':
            return AdbResult(0, '', '')
        return None

    engine = ShellEngine(handler)
    engine.file_remove('tv-1', '/sdcard/DCIM/IMG.jpg')
    assert engine.calls[-1] == ['rm', '-rf', '/sdcard/DCIM/IMG.jpg']


def test_file_remove_korunan_kanonik_reddedilir():
    def handler(call):
        if call[:3] == ['readlink', '-f', '/sdcard/emulated']:
            return AdbResult(0, '/storage/emulated\n', '')
        return None

    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.file_remove('tv-1', '/sdcard/emulated/0')
    assert 'Korunan kok dizin' in str(exc.value)
    assert not any(c[0] == 'rm' for c in engine.calls)


def test_file_remove_rm_hatasi():
    def handler(call):
        if call[0] == 'readlink':
            return AdbResult(0, '/sdcard/DCIM\n', '')
        if call[0] == 'rm':
            return AdbResult(1, '', 'Read-only file system')
        return None

    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.file_remove('tv-1', '/sdcard/DCIM/IMG.jpg')
    assert 'Read-only file system' in str(exc.value)


def test_file_mkdir():
    engine = ShellEngine(_sabit(''))
    engine.file_mkdir('tv-1', '/sdcard/Yeni Klasor')
    assert engine.calls == [['mkdir', '-p', "'/sdcard/Yeni Klasor'"]]

    engine2 = ShellEngine(_sabit('', 0, 'mkdir: permission denied'))
    with pytest.raises(AdbError) as exc:
        engine2.file_mkdir('tv-1', '/sdcard/x')
    assert 'permission denied' in str(exc.value)


def test_rename_file_korunan_ve_ayni_yol():
    engine = ShellEngine(_sabit('x'))
    with pytest.raises(AdbError):
        engine.rename_file('tv-1', '/sdcard', '/sdcard/yeni')
    with pytest.raises(AdbError):
        engine.rename_file('tv-1', '/sdcard/DCIM/a', '/sdcard/DCIM/a')
    assert engine.calls == []


def test_rename_file_hedef_var():
    engine = ShellEngine(_sabit('', 0))
    with pytest.raises(AdbError) as exc:
        engine.rename_file('tv-1', '/sdcard/a', '/sdcard/b')
    assert 'zaten var' in str(exc.value)


def test_rename_file_dogrulanamayan_test():
    engine = ShellEngine(_sabit('', 2, 'x'))
    with pytest.raises(AdbError) as exc:
        engine.rename_file('tv-1', '/sdcard/a', '/sdcard/b')
    assert 'güvenlik' in str(exc.value)


def test_rename_file_basarili():
    durum = {'paths': {'/sdcard/a'}}

    def handler(call):
        if call[0] == 'test':
            return AdbResult(0 if call[2] in durum['paths'] else 1, '', '')
        if call[0] == 'mv':
            durum['paths'].discard(call[2])
            durum['paths'].add(call[3])
            return AdbResult(0, '', '')
        return None

    engine = ShellEngine(handler)
    assert engine.rename_file('tv-1', '/sdcard/a', '/sdcard/b') is True
    assert durum['paths'] == {'/sdcard/b'}


def test_rename_file_kaynak_kalirsa():
    def handler(call):
        if call[0] == 'test':
            return AdbResult(0 if call[2] == '/sdcard/a' else 1, '', '')
        if call[0] == 'mv':
            return AdbResult(0, '', '')
        return None

    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.rename_file('tv-1', '/sdcard/a', '/sdcard/b')
    assert 'yapılmadı' in str(exc.value)


def test_rename_file_mv_reddedilirse():
    def handler(call):
        if call[0] == 'test':
            return AdbResult(1, '', '')
        if call[0] == 'mv':
            return AdbResult(1, '', 'izin yok')
        return None

    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.rename_file('tv-1', '/sdcard/a', '/sdcard/b')
    assert 'Yeniden adlandırılamadı' in str(exc.value)


def test_rename_file_hedef_dogrulanamazsa():
    def handler(call):
        if call[0] == 'test':
            return AdbResult(1, '', '')
        if call[0] == 'mv':
            return AdbResult(0, '', '')
        return None

    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.rename_file('tv-1', '/sdcard/a', '/sdcard/b')
    assert 'hedefi doğrulanamadı' in str(exc.value)


# --- paket yazma komutlari ---------------------------------------------------

def test_force_stop():
    engine = ShellEngine(_sabit(''))
    engine.force_stop('tv-1', 'com.a')
    assert engine.calls == [['am', 'force-stop', '--user', '0', 'com.a']]

    engine2 = ShellEngine(_sabit(''))
    engine2.force_stop('tv-1', 'com.a', user_id=3)
    assert engine2.calls == [['am', 'force-stop', '--user', '3', 'com.a']]

    engine3 = ShellEngine(_sabit('Error: activity not found'))
    with pytest.raises(AdbError):
        engine3.force_stop('tv-1', 'com.a')

    engine4 = ShellEngine(_sabit('x'))
    with pytest.raises(AdbError):
        engine4.force_stop('tv-1', 'gecersiz paket')
    assert engine4.calls == []


def test_clear_data():
    engine = ShellEngine(_sabit('Success\n'))
    engine.clear_data('tv-1', 'com.a')
    assert engine.calls == [['pm', 'clear', '--user', '0', 'com.a']]

    engine2 = ShellEngine(_sabit(''))
    with pytest.raises(AdbError) as exc:
        engine2.clear_data('tv-1', 'com.a')
    assert 'Veri silinemedi' in str(exc.value)

    engine3 = ShellEngine(_sabit('Success\nFailed'))
    with pytest.raises(AdbError):
        engine3.clear_data('tv-1', 'com.a')

    engine4 = ShellEngine(lambda call: None)
    with pytest.raises(AdbError) as exc4:
        engine4.clear_data('tv-1', 'kötü!')
    assert 'Geçersiz paket adi' in str(exc4.value)
    assert engine4.calls == []


# --- girdi komutlari ---------------------------------------------------------

def test_keyevent_gecerli():
    engine = ShellEngine(_sabit(''))
    engine.keyevent('tv-1', 26)
    engine.keyevent('tv-1', '26', longpress=True)
    assert engine.calls == [['input', 'keyevent', '26'],
                            ['input', 'keyevent', '--longpress', '26']]


def test_keyevent_sinirlar_ve_gecersiz():
    engine = ShellEngine(_sabit(''))
    engine.keyevent('tv-1', 0)
    engine.keyevent('tv-1', 300)
    assert engine.calls == [['input', 'keyevent', '0'],
                            ['input', 'keyevent', '300']]

    for bad in (-1, 301, 'abc', None):
        with pytest.raises(AdbError):
            engine.keyevent('tv-1', bad)
    assert len(engine.calls) == 2


def test_input_text_translit():
    engine = ShellEngine(_sabit(''))
    engine.input_text('tv-1', 'Çok iyi!')
    assert engine.calls == [['input', 'text', 'Cok%siyi']]


@pytest.mark.parametrize('url', [
    'http://example.com/list?channel=playlist.m3u',
    "https://example.com/list?user=a&password=b%20c#part[1]!*'();$()",
    'https://example.com/list?token=%secret%s&next=one',
])
def test_input_url_preserves_query_as_literal_shell_argument(url):
    engine = ShellEngine(_sabit(''))
    engine.input_text('tv-1', url)
    chunks = []
    for call in engine.calls:
        assert call[:2] == ['input', 'text']
        parsed = shlex.split(' '.join(call))
        assert len(parsed) == 3
        # Model Android input's literal %s-to-space replacement.
        chunks.append(parsed[2].replace('%s', ' '))
    assert ''.join(chunks) == url


def test_input_text_bos_kalicosa_hata():
    engine = ShellEngine(_sabit(''))
    with pytest.raises(AdbError) as exc:
        engine.input_text('tv-1', '★☺')
    assert 'geçerli karakter' in str(exc.value)
    assert engine.calls == []


def test_tap_ve_swipe():
    engine = ShellEngine(_sabit(''))
    engine.tap('tv-1', 100, 200)
    engine.swipe('tv-1', 10, 20, 30, 40, duration_ms=500)
    assert engine.calls == [
        ['input', 'tap', '100', '200'],
        ['input', 'swipe', '10', '20', '30', '40', '500']]


def test_tap_swipe_gecersiz():
    engine = ShellEngine(_sabit(''))
    for args in (('x', 1), (1, None), (-1, 5)):
        with pytest.raises(AdbError):
            engine.tap('tv-1', *args)
    with pytest.raises(AdbError):
        engine.swipe('tv-1', 0, 0, 0, 0, duration_ms=-1)
    with pytest.raises(AdbError):
        engine.swipe('tv-1', 'a', 0, 0, 0)
    assert engine.calls == []


def test_reboot_varyantlari():
    engine = ShellEngine(lambda call: AdbResult(0, '', ''))
    engine.reboot('tv-1')
    engine.reboot_recovery('tv-1')
    engine.reboot_bootloader('tv-1')
    assert engine.calls == [
        ['-s', 'tv-1', 'reboot'],
        ['-s', 'tv-1', 'reboot', 'recovery'],
        ['-s', 'tv-1', 'reboot', 'bootloader']]


def test_sleep_wakeup():
    engine = ShellEngine(_sabit(''))
    engine.sleep('tv-1')
    engine.wakeup('tv-1')
    assert engine.calls == [['input', 'keyevent', '223'],
                            ['input', 'keyevent', '224']]


def test_set_volume_mute_ve_soft_reboot():
    engine = ShellEngine(_sabit(''))
    engine.set_volume_mute('tv-1')
    engine.soft_reboot('tv-1')
    assert engine.calls == [['input', 'keyevent', '164'],
                            ['setprop', 'ctl.restart', 'zygote']]

    engine2 = ShellEngine(_sabit('', 1, 'reddedildi'))
    with pytest.raises(AdbError):
        engine2.set_volume_mute('tv-1')

    engine3 = ShellEngine(_sabit('', 1, 'izin reddedildi'))
    with pytest.raises(AdbError):
        engine3.soft_reboot('tv-1')


# --- arka plan kisitlama yazimi ---------------------------------------------

def _arka_plan_handler(api='30', modes=None, bucket='10'):
    durum = {
        'modes': dict(modes or {'RUN_IN_BACKGROUND': 'allow',
                                'RUN_ANY_IN_BACKGROUND': 'allow'}),
        'bucket': bucket,
        'hata_op': None,
        'hata_kullanildi': False,
        'yut': False,  # True: set komutu basarili doner ama durum degismez
    }

    def handler(call):
        if call == ['getprop', 'ro.build.version.sdk']:
            return AdbResult(0, api + '\n', '')
        if call[:4] == ['cmd', 'appops', 'get', '--user']:
            op = call[-1]
            return AdbResult(0, '{}: {}\n'.format(op, durum['modes'][op]), '')
        if call[:4] == ['cmd', 'appops', 'set', '--user']:
            op, mode = call[-2], call[-1]
            if durum['yut']:
                return AdbResult(0, '', '')
            durum['modes'][op] = mode
            if durum['hata_op'] == op and not durum['hata_kullanildi']:
                # Tek seferlik ariza: geri alma yazimi basarili olabilmeli.
                durum['hata_kullanildi'] = True
                return AdbResult(1, '', 'error: denied')
            return AdbResult(0, '', '')
        if call[:3] == ['am', 'get-standby-bucket', '--user']:
            return AdbResult(0, durum['bucket'] + '\n', '')
        if call[:3] == ['am', 'set-standby-bucket', '--user']:
            durum['bucket'] = {'restricted': '45', 'active': '10'}.get(
                call[-1], call[-1])
            return AdbResult(0, '', '')
        return None

    return handler, durum


def test_restrict_basarili_bucket_akisi():
    handler, durum = _arka_plan_handler(api='30')
    engine = ShellEngine(handler)
    assert engine.restrict('tv-1', 'com.a') is True
    assert durum['modes'] == {'RUN_IN_BACKGROUND': 'ignore',
                              'RUN_ANY_IN_BACKGROUND': 'ignore'}
    assert durum['bucket'] == '45'
    assert ['cmd', 'appops', 'set', '--user', '0', 'com.a',
            'RUN_IN_BACKGROUND', 'ignore'] in engine.calls


def test_unrestrict_basarili():
    handler, durum = _arka_plan_handler(
        api='30',
        modes={'RUN_IN_BACKGROUND': 'ignore', 'RUN_ANY_IN_BACKGROUND': 'deny'},
        bucket='45')
    engine = ShellEngine(handler)
    assert engine.unrestrict('tv-1', 'com.a') is True
    assert durum['modes'] == {'RUN_IN_BACKGROUND': 'allow',
                              'RUN_ANY_IN_BACKGROUND': 'allow'}
    assert durum['bucket'] == '10'


def test_restrict_api28_bucket_atlanir():
    handler, durum = _arka_plan_handler(api='28')
    engine = ShellEngine(handler)
    assert engine.restrict('tv-1', 'com.a') is True
    assert durum['bucket'] == '10'
    assert not any(c[0] == 'am' for c in engine.calls)


def test_restrict_gecersiz_paket():
    engine = ShellEngine(_sabit('x'))
    with pytest.raises(AdbError) as exc:
        engine.restrict('tv-1', 'gecersiz paket')
    assert 'Geçersiz paket adi' in str(exc.value)
    assert engine.calls == []


def test_restrict_hata_geri_alir():
    handler, durum = _arka_plan_handler(api='30')
    durum['hata_op'] = 'RUN_IN_BACKGROUND'
    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.restrict('tv-1', 'com.a')
    assert 'geri yüklendi' in str(exc.value)
    assert durum['modes'] == {'RUN_IN_BACKGROUND': 'allow',
                              'RUN_ANY_IN_BACKGROUND': 'allow'}
    assert durum['bucket'] == '10'


def test_restrict_dogrulama_basarisizsa_bucket_de_geri_alir():
    handler, durum = _arka_plan_handler(api='30')
    durum['yut'] = True
    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.restrict('tv-1', 'com.a')
    assert 'AppOps ve standby bucket' in str(exc.value)
    assert durum['modes'] == {'RUN_IN_BACKGROUND': 'allow',
                              'RUN_ANY_IN_BACKGROUND': 'allow'}
    assert durum['bucket'] == '10'


def _bucket_handler(appops_set_davranis=None, bucket_set_davranis=None,
                    bucket_get_listesi=None):
    """Arka plan akisinda bucket ve appops yazimlarini yonlendiren sahte katman."""
    durum = {
        'modes': {'RUN_IN_BACKGROUND': 'allow',
                  'RUN_ANY_IN_BACKGROUND': 'allow'},
        'bucket': '10',
        'get_sayaci': 0,
        'set_sayaci': 0,
    }

    def handler(call):
        if call == ['getprop', 'ro.build.version.sdk']:
            return AdbResult(0, '30\n', '')
        if call[:4] == ['cmd', 'appops', 'get', '--user']:
            return AdbResult(0, '{}: {}\n'.format(
                call[-1], durum['modes'][call[-1]]), '')
        if call[:4] == ['cmd', 'appops', 'set', '--user']:
            op, mode = call[-2], call[-1]
            if appops_set_davranis is not None:
                return appops_set_davranis(durum, op, mode)
            durum['modes'][op] = mode
            return AdbResult(0, '', '')
        if call[:3] == ['am', 'get-standby-bucket', '--user']:
            durum['get_sayaci'] += 1
            if bucket_get_listesi is not None:
                deger = bucket_get_listesi(durum['get_sayaci'])
                return AdbResult(0, deger + '\n', '')
            return AdbResult(0, durum['bucket'] + '\n', '')
        if call[:3] == ['am', 'set-standby-bucket', '--user']:
            durum['set_sayaci'] += 1
            if bucket_set_davranis is not None:
                return bucket_set_davranis(durum, call[-1], durum['set_sayaci'])
            durum['bucket'] = call[-1]
            return AdbResult(0, '', '')
        return None

    return handler, durum


def test_restrict_bucket_yazimi_ve_geri_alma_reddedilirse():
    # Ana yazim da geri alma yazimi da reddedilir.
    def bucket_set(durum, bucket, sayi):
        return AdbResult(1, '', 'error: denied')

    handler, durum = _bucket_handler(bucket_set_davranis=bucket_set)
    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.restrict('tv-1', 'com.a')
    mesaj = str(exc.value)
    assert 'AppOps geri alma başarısız' in mesaj
    assert 'standby bucket' in mesaj
    # AppOps yazimlari geri alinip dogrulandi.
    assert durum['modes'] == {'RUN_IN_BACKGROUND': 'allow',
                              'RUN_ANY_IN_BACKGROUND': 'allow'}


def test_restrict_bucket_dogrulanamazsa_geri_alir():
    # set-standby-bucket komutu hatasiz doner ama bucket degismez.
    def bucket_set(durum, bucket, sayi):
        return AdbResult(0, '', '')

    handler, durum = _bucket_handler(bucket_set_davranis=bucket_set)
    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.restrict('tv-1', 'com.a')
    mesaj = str(exc.value)
    assert 'Standby bucket istenen duruma geçmedi' in mesaj
    # Geri alma sonrasi dogrulama basarili; mesaj geri yuklendigini soyler.
    assert 'Önceki AppOps ve standby bucket durumları geri yüklendi' in mesaj
    assert durum['modes'] == {'RUN_IN_BACKGROUND': 'allow',
                              'RUN_ANY_IN_BACKGROUND': 'allow'}


def test_restrict_bucket_geri_alma_dogrulanamazsa():
    # Ana yazim reddedilir; geri alma komutu basarili doner ama etkisizdir.
    def bucket_set(durum, bucket, sayi):
        if sayi == 1:
            return AdbResult(1, '', 'error: denied')
        return AdbResult(0, '', '')

    # Ilk okuma '10' (onceki), geri alma dogrulamasi '99' dondurur.
    def bucket_get(sayi):
        return '10' if sayi == 1 else '99'

    handler, durum = _bucket_handler(bucket_set_davranis=bucket_set,
                                     bucket_get_listesi=bucket_get)
    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.restrict('tv-1', 'com.a')
    assert 'AppOps geri alma başarısız' in str(exc.value)
    assert 'geri yüklemesi doğrulanamadı' in str(exc.value)


def test_restrict_appops_geri_alma_reddedilirse():
    def appops_set(durum, op, mode):
        if op == 'RUN_IN_BACKGROUND':
            return AdbResult(1, '', 'error: denied')
        durum['modes'][op] = mode
        return AdbResult(0, '', '')

    handler, durum = _bucket_handler(appops_set_davranis=appops_set)
    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.restrict('tv-1', 'com.a')
    assert 'AppOps geri alma başarısız' in str(exc.value)
    assert 'RUN_IN_BACKGROUND' in str(exc.value)


def test_restrict_appops_geri_alma_dogrulanamazsa():
    def appops_set(durum, op, mode):
        if op == 'RUN_IN_BACKGROUND' and mode == 'ignore':
            # Komut hata doner ama durum degismis olabilir.
            durum['modes'][op] = 'ignore'
            return AdbResult(1, '', 'error: denied')
        if op == 'RUN_IN_BACKGROUND' and mode == 'allow':
            # Geri alma yazimi komutu basarili doner ama durum duzelmez.
            return AdbResult(0, '', '')
        durum['modes'][op] = mode
        return AdbResult(0, '', '')

    handler, durum = _bucket_handler(appops_set_davranis=appops_set)
    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.restrict('tv-1', 'com.a')
    assert 'AppOps geri alma başarısız' in str(exc.value)
    assert 'Geri yükleme doğrulanamadı' in str(exc.value)


def test_android_api_level():
    engine = ShellEngine(_sabit('31\n'))
    assert engine._android_api_level('tv-1') == 31

    engine2 = ShellEngine(_sabit('upside down cake\n'))
    with pytest.raises(AdbError) as exc:
        engine2._android_api_level('tv-1')
    assert 'API' in str(exc.value)

    engine3 = ShellEngine(_sabit('', 1, 'yok'))
    with pytest.raises(AdbError):
        engine3._android_api_level('tv-1')


def test_standby_bucket():
    engine = ShellEngine(_sabit('45\n'))
    assert engine._standby_bucket('tv-1', 'com.a') == '45'

    for out in ('abc\n', '101\n', '9999\n', ''):
        engine2 = ShellEngine(_sabit(out))
        with pytest.raises(AdbError):
            engine2._standby_bucket('tv-1', 'com.a')


# --- animasyon olcegi --------------------------------------------------------

def _anim_handler(degerler=None, hata_key=None, yut=False):
    durum = {
        'vals': dict(degerler or {'window_animation_scale': '1',
                                  'transition_animation_scale': '1',
                                  'animator_duration_scale': '1'}),
        'hata_key': hata_key,
        'yut': yut,
    }

    def handler(call):
        if call[:3] == ['settings', 'get', 'global']:
            return AdbResult(0, durum['vals'][call[3]] + '\n', '')
        if call[:3] == ['settings', 'put', 'global']:
            key, val = call[3], call[4]
            if durum['hata_key'] == key:
                return AdbResult(1, '', 'error: denied')
            if not durum['yut']:
                durum['vals'][key] = val
            return AdbResult(0, '', '')
        return None

    return handler, durum


def test_set_animator_scales_basarili():
    handler, durum = _anim_handler()
    engine = ShellEngine(handler)
    assert engine.set_animator_scales('tv-1', '0.5') is None
    assert durum['vals'] == {'window_animation_scale': '0.5',
                             'transition_animation_scale': '0.5',
                             'animator_duration_scale': '0.5'}


def test_set_animator_scales_normalize():
    handler, durum = _anim_handler()
    engine = ShellEngine(handler)
    engine.set_animator_scales('tv-1', '1.0')
    assert durum['vals']['window_animation_scale'] == '1'


def test_set_animator_scales_gecersiz_ve_onceki_okunamazsa():
    engine = ShellEngine(_sabit('x'))
    with pytest.raises(AdbError) as exc:
        engine.set_animator_scales('tv-1', '2')
    assert 'Geçersiz' in str(exc.value)
    assert engine.calls == []

    handler, _durum = _anim_handler(
        {'window_animation_scale': 'null', 'transition_animation_scale': '1',
         'animator_duration_scale': '1'})
    engine2 = ShellEngine(handler)
    with pytest.raises(AdbError) as exc2:
        engine2.set_animator_scales('tv-1', '0')
    assert 'okunamadı' in str(exc2.value)
    assert not any(c[:3] == ['settings', 'put', 'global']
                   for c in engine2.calls)


def test_set_animator_scales_hata_geri_alir():
    handler, durum = _anim_handler(hata_key='transition_animation_scale')
    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.set_animator_scales('tv-1', '0')
    assert 'başarısız' in str(exc.value)
    assert durum['vals'] == {'window_animation_scale': '1',
                             'transition_animation_scale': '1',
                             'animator_duration_scale': '1'}


def test_set_animator_scales_dogrulama_basarisizsa():
    handler, durum = _anim_handler(yut=True)
    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.set_animator_scales('tv-1', '0')
    assert 'Doğrulama başarısız' in str(exc.value)
    assert durum['vals'] == {'window_animation_scale': '1',
                             'transition_animation_scale': '1',
                             'animator_duration_scale': '1'}


def test_set_animator_scales_geri_alma_istisnasi():
    durum = {'vals': {'window_animation_scale': '1',
                      'transition_animation_scale': '1',
                      'animator_duration_scale': '1'}}

    def handler(call):
        if call[:3] == ['settings', 'get', 'global']:
            return AdbResult(0, durum['vals'][call[3]] + '\n', '')
        if call[:3] == ['settings', 'put', 'global']:
            key, val = call[3], call[4]
            if key == 'transition_animation_scale' and val == '0':
                return AdbResult(1, '', 'error: denied')
            if key == 'window_animation_scale' and val == '1':
                # Geri alma komutu hata doner ama durum duzelmis olabilir.
                durum['vals'][key] = val
                raise AdbError('kopuk')
            durum['vals'][key] = val
            return AdbResult(0, '', '')
        return None

    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.set_animator_scales('tv-1', '0')
    mesaj = str(exc.value)
    assert 'geri alma hataları' in mesaj
    assert 'kopuk' in mesaj
    assert durum['vals'] == {'window_animation_scale': '1',
                             'transition_animation_scale': '1',
                             'animator_duration_scale': '1'}


def test_set_animator_scales_geri_alma_dogrulanamazsa():
    durum = {'vals': {'window_animation_scale': '1',
                      'transition_animation_scale': '1',
                      'animator_duration_scale': '1'}}

    def handler(call):
        if call[:3] == ['settings', 'get', 'global']:
            return AdbResult(0, durum['vals'][call[3]] + '\n', '')
        if call[:3] == ['settings', 'put', 'global']:
            key, val = call[3], call[4]
            if key == 'transition_animation_scale' and val == '0':
                return AdbResult(1, '', 'error: denied')
            if key == 'window_animation_scale' and val == '1':
                # Geri alma komutu basarili doner ama deger duzelmez.
                return AdbResult(0, '', '')
            durum['vals'][key] = val
            return AdbResult(0, '', '')
        return None

    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.set_animator_scales('tv-1', '0')
    mesaj = str(exc.value)
    assert 'geri alma doğrulaması başarısız' in mesaj
    assert 'window_animation_scale' in mesaj


def test_set_animator_scales_geri_alma_okunamazsa():
    durum = {'vals': {'window_animation_scale': '1',
                      'transition_animation_scale': '1',
                      'animator_duration_scale': '1'},
             'get_sayaci': 0}

    def handler(call):
        if call[:3] == ['settings', 'get', 'global']:
            durum['get_sayaci'] += 1
            if durum['get_sayaci'] > 3:
                # animator_scales yalnizca AdbError'i yutar; beklenmedik
                # bir hata geri alma dogrulamasini okunamaz hale getirir.
                raise RuntimeError('okuma kopuk')
            return AdbResult(0, durum['vals'][call[3]] + '\n', '')
        if call[:3] == ['settings', 'put', 'global']:
            key, val = call[3], call[4]
            if key == 'transition_animation_scale' and val == '0':
                return AdbResult(1, '', 'error: denied')
            durum['vals'][key] = val
            return AdbResult(0, '', '')
        return None

    engine = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.set_animator_scales('tv-1', '0')
    mesaj = str(exc.value)
    assert 'geri alma doğrulaması okunamadı' in mesaj
    assert 'okuma kopuk' in mesaj


# --- ekran bilgisi -----------------------------------------------------------

def _display_handler(size_out=None, density_out=None, overscan_out='',
                     display_out=''):
    def handler(call):
        if call[:2] == ['wm', 'size']:
            return AdbResult(
                0, size_out if size_out is not None
                else 'Physical size: 1920x1080\n', '')
        if call[:2] == ['wm', 'density']:
            return AdbResult(
                0, density_out if density_out is not None
                else 'Physical density: 320\n', '')
        if call[:2] == ['wm', 'overscan']:
            return AdbResult(0, overscan_out, '')
        if call[:2] == ['dumpsys', 'display']:
            return AdbResult(0, display_out, '')
        return None

    return handler


def test_display_details_override_ve_overscan():
    handler = _display_handler(
        size_out='Physical size: 1920x1080\nOverride size: 1280x720\n',
        density_out='Physical density: 320\nOverride density: 240\n',
        overscan_out='overscan: 10,20,30,40\n',
        display_out='renderFrameRate 50.0\n'
                    'DeviceProductInfo{name=Mi TV, vendorId=1}\n')
    engine = ShellEngine(handler)
    d = engine.display_details('tv-1')
    assert d['physical_width'] == 1920
    assert d['physical_height'] == 1080
    assert d['width'] == 1280
    assert d['height'] == 720
    assert d['override_width'] == 1280
    assert d['physical_density'] == 320
    assert d['density'] == 240
    assert d['overscan'] == [10, 20, 30, 40]
    assert d['fps'] == 50.0
    assert d['sink_name'] == 'Mi TV'
    assert d['read_errors'] == []
    assert d['screen_str'] == '1280x720 @ 50Hz (240 DPI) (Özel Ölçek) · Mi TV'


def test_display_details_okunamayan_alanlar():
    def handler(call):
        if call[:2] == ['wm', 'size']:
            return AdbResult(1, '', 'hata')
        if call[:2] == ['wm', 'density']:
            return AdbResult(0, 'alakasiz\n', '')
        if call[:2] == ['wm', 'overscan']:
            return AdbResult(1, '', '')
        if call[:2] == ['dumpsys', 'display']:
            raise AdbError('kopuk')
        return None

    engine = ShellEngine(handler)
    d = engine.display_details('tv-1')
    assert d['read_errors'] == ['size', 'density']
    assert d['width'] == 1920
    assert d['density'] == 320
    assert d['overscan'] is None
    assert d['fps'] == 60.0


def test_set_display_size_gecersiz():
    engine = ShellEngine(_sabit('x'))
    with pytest.raises(AdbError):
        engine.set_display_size('tv-1', 100, 720)
    with pytest.raises(AdbError):
        engine.set_display_size('tv-1', 1280, 100)
    with pytest.raises(AdbError):
        engine.set_display_size('tv-1', '1280', 720)
    assert engine.calls == []


# --- URL acma ----------------------------------------------------------------

def test_open_url_quote_ve_sema():
    engine = ShellEngine(_sabit('Starting: Intent'))
    engine.open_url('tv-1', 'HTTPS://Example.com/watch?v=1')
    assert engine.calls == [['am', 'start', '-a', 'android.intent.action.VIEW',
                             '-d', shlex.quote('https://Example.com/watch?v=1')]]


def test_open_url_gecersiz_adresler():
    engine = ShellEngine(_sabit('x'))
    for url in ('ftp://example.com', 'https://', 'file:///etc/passwd',
                'javascript:alert(1)', ''):
        with pytest.raises(AdbError):
            engine.open_url('tv-1', url)
    assert engine.calls == []


def test_open_url_ayristirilamayan_adres():
    engine = ShellEngine(_sabit('x'))
    with pytest.raises(AdbError) as exc:
        engine.open_url('tv-1', 'http://[bozuk')
    assert 'Geçersiz bağlantı adresi' in str(exc.value)
    assert engine.calls == []


def test_open_url_hata():
    engine = ShellEngine(_sabit('Error: Activity not started\n'))
    with pytest.raises(AdbError):
        engine.open_url('tv-1', 'https://example.com')

    engine2 = ShellEngine(_sabit('', 1, 'hata'))
    with pytest.raises(AdbError):
        engine2.open_url('tv-1', 'https://example.com')


# --- eslestirme / baglanti ---------------------------------------------------

def test_pair_gecersiz_adresler():
    engine = ShellEngine(_sabit('x'))
    for addr in ('192.168.1.5', 'host:port', 'host:0', 'host:65536',
                 '-host:5555', 'a b:5555', ':5555'):
        with pytest.raises(AdbError):
            engine.pair(addr, '123456')
    assert engine.calls == []


def test_pair_gecersiz_kod():
    engine = ShellEngine(_sabit('x'))
    for code in ('12345', '1234567', 'abcdef', '', 123456):
        with pytest.raises(AdbError):
            engine.pair('192.168.1.5:37000', code)
    assert engine.calls == []


def test_pair_basarili_maskeleme():
    engine = ShellEngine(_sabit(
        'Successfully paired to 192.168.1.5:37000\n'))
    sonuc = engine.pair('192.168.1.5:37000', '123456')
    assert '******' in sonuc
    assert '192.168.1.5' not in sonuc
    assert '123456' not in sonuc


def test_pair_ipv6_basarili():
    engine = ShellEngine(_sabit('Successfully paired to [fe80::1]:37000\n'))
    sonuc = engine.pair('[fe80::1]:37000', '654321')
    assert 'fe80' not in sonuc
    assert '******' in sonuc


def test_pair_basarisiz():
    engine = ShellEngine(_sabit('', 1, 'Failed to pair'))
    with pytest.raises(AdbError) as exc:
        engine.pair('192.168.1.5:37000', '123456')
    assert 'başarısız' in str(exc.value)

    engine2 = ShellEngine(_sabit(
        'Successfully paired to 1.2.3.4:5 but failed later\n'))
    with pytest.raises(AdbError):
        engine2.pair('1.2.3.4:5', '123456')


def test_connect_ag_hedefi():
    def handler(call):
        if call == ['connect', '192.168.1.5:5555']:
            return AdbResult(0, 'connected to 192.168.1.5:5555\n', '')
        if call == ['-s', '192.168.1.5:5555', 'get-state']:
            return AdbResult(0, 'device', '')
        return None

    engine = ShellEngine(handler)
    assert engine.connect('192.168.1.5:5555') == '192.168.1.5:5555'


def test_connect_hata_ve_hazir_degil():
    engine = ShellEngine(_sabit('failed to connect to 192.168.1.5:5555\n'))
    with pytest.raises(AdbError) as exc:
        engine.connect('192.168.1.5:5555')
    assert 'Bağlantı başarısız' in str(exc.value)

    def handler(call):
        if call[0] == 'connect':
            return AdbResult(0, 'connected\n', '')
        if call[-1] == 'get-state':
            return AdbResult(0, 'offline\n', '')
        return None

    engine2 = ShellEngine(handler)
    with pytest.raises(AdbError) as exc2:
        engine2.connect('192.168.1.5:5555')
    assert 'hazır değil' in str(exc2.value)


def test_connect_iptal():
    engine = ShellEngine(_sabit('x'))
    with pytest.raises(AdbError) as exc:
        engine.connect('192.168.1.5:5555', cancel_check=lambda: True)
    assert 'durduruldu' in str(exc.value)
    assert engine.calls == []


def test_disconnect_ag_ve_usb():
    engine = ShellEngine(_sabit('x'))
    assert engine.disconnect('emulator-5554') is None
    assert engine.calls == []

    engine2 = ShellEngine(_sabit('disconnected 192.168.1.5:5555\n'))
    engine2.disconnect('192.168.1.5:5555')
    assert engine2.calls == [['disconnect', '192.168.1.5:5555']]

    engine3 = ShellEngine(_sabit('', 1, 'error'))
    with pytest.raises(AdbError):
        engine3.disconnect('192.168.1.5:5555')
