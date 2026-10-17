# -*- coding: utf-8 -*-
"""AdbEngine paket durumu ve cihaz yonetimi testleri (FakeEngine: ADB yok).

Kapsam: devices/get-state ayristirma, enable/disable/uninstall/install-existing
dogrulama zincirleri, smart_remove siralama ve belirsizlik davranisi,
is_disabled/is_uninstalled belirsizlik hatalari, pm path okuma, pull/push
komutlari ve yol guvenligi, launch fallback zinciri, home_activity,
kurulum sihirbazi islemleri, user_id sarmalayicilari.
Gercek cihaz, ag veya disk kullanilmaz.
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


def _paket_listesi(*paketler):
    return ''.join('package:{}\n'.format(p) for p in paketler)


class PaketDurumHandler:
    """pm list/pm yazma komutlarina durum tutarak yanit veren sahte katman."""

    def __init__(self, kurulu=(), devre_disi=()):
        self.kurulu = list(kurulu)
        self.devre_disi = list(devre_disi)
        self.list_istisna = False
        self.list_hata_metni = ''
        self.hata_listesi = False
        self.force_stop_hata = False
        self.enable_hata = ''
        self.disable_hata = ''
        self.disable_mutasyon = True
        self.uninstall_cikti = 'Success'
        self.uninstall_mutasyon = True
        self.cmd_install_hata = ''
        self.pm_install_hata = ''

    def __call__(self, call):
        if call[:2] == ['pm', 'list']:
            if self.list_istisna:
                raise AdbError('baglanti koptu')
            if self.hata_listesi:
                return AdbResult(1, '', 'error: closed')
            if self.list_hata_metni:
                return AdbResult(0, _paket_listesi(*self.kurulu),
                                 self.list_hata_metni)
            if '-d' in call:
                return AdbResult(0, _paket_listesi(*self.devre_disi), '')
            return AdbResult(0, _paket_listesi(*self.kurulu), '')
        if call[:2] == ['am', 'force-stop']:
            if self.force_stop_hata:
                return AdbResult(1, 'Error: not found', '')
            return AdbResult(0, '', '')
        if call[:2] == ['pm', 'enable']:
            return AdbResult(
                0, self.enable_hata or
                'Package {} new state: enabled'.format(call[-1]), '')
        if call[:2] == ['pm', 'disable-user']:
            if self.disable_hata:
                return AdbResult(1, self.disable_hata, '')
            if self.disable_mutasyon and call[-1] not in self.devre_disi:
                self.devre_disi.append(call[-1])
            return AdbResult(
                0, 'Package {} new state: disabled-user'.format(call[-1]), '')
        if call[:2] == ['pm', 'uninstall']:
            if self.uninstall_mutasyon and call[-1] in self.kurulu:
                self.kurulu.remove(call[-1])
            return AdbResult(0, self.uninstall_cikti, '')
        if call[:3] == ['cmd', 'package', 'install-existing']:
            if self.cmd_install_hata:
                return AdbResult(1, self.cmd_install_hata, '')
            return AdbResult(
                0, 'Package {} installed for user: 0'.format(call[-1]), '')
        if call[:2] == ['pm', 'install-existing']:
            if self.pm_install_hata:
                return AdbResult(1, self.pm_install_hata, '')
            return AdbResult(0, 'Success', '')
        return None


# --- cihaz listesi -----------------------------------------------------------

def test_devices_ayristirir():
    cikti = (
        'List of devices attached\n'
        'R58M12345\tdevice product:mi_box model:Mi_Box\n'
        '192.168.1.5:5555\tdevice\n'
        '[fe80::1%wlan0]:5555\toffline\n'
        'ABC\tunauthorized\n'
        'XYZ\tbootloader\n'
        'DEF\trecovery\n'
        'GHI\tsideload\n'
        'JKL\trescue\n'
        'MNO\tno permissions (user in plugdev group)\n'
        'QQQ\tweird\n'
        'bozuk-satir\n'
        '!gecersiz!\tdevice\n'
        '\n')
    eng = ShellEngine(_sabit(cikti))
    devs = eng.devices()
    assert [(d['id'], d['state']) for d in devs] == [
        ('R58M12345', 'device'),
        ('192.168.1.5:5555', 'device'),
        ('[fe80::1%wlan0]:5555', 'offline'),
        ('ABC', 'unauthorized'),
        ('XYZ', 'bootloader'),
        ('DEF', 'recovery'),
        ('GHI', 'sideload'),
        ('JKL', 'rescue'),
        ('MNO', 'no permissions'),
    ]
    assert eng.calls == [['devices', '-l']]


def test_devices_bos_liste():
    eng = ShellEngine(_sabit('List of devices attached\n'))
    assert eng.devices() == []


def test_devices_hata_mesaji():
    eng = ShellEngine(_sabit('adb server is out of date', exit_code=1,
                             error='boom'))
    with pytest.raises(AdbError) as exc:
        eng.devices()
    assert 'ADB cihaz listesi alınamadı' in str(exc.value)

    eng2 = ShellEngine(_sabit(exit_code=1))
    with pytest.raises(AdbError) as exc2:
        eng2.devices()
    assert 'bilinmeyen hata' in str(exc2.value)


def test_get_state_ham_cikti_dondurur():
    eng = ShellEngine(_sabit('device\n'))
    assert eng.get_state('S') == 'device\n'
    assert eng.calls == [['-s', 'S', 'get-state']]


# --- enable ------------------------------------------------------------------

def test_enable_basarili():
    handler = PaketDurumHandler(kurulu=['com.hedef'])
    eng = ShellEngine(handler)
    r = eng.enable('S', 'com.hedef')
    assert r.exit_code == 0
    assert eng.calls[0] == ['pm', 'enable', '--user', '0', 'com.hedef']


def test_enable_gecersiz_paket():
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError):
        eng.enable('S', 'kotu paket!')
    assert eng.calls == []


def test_enable_hata_metni():
    handler = PaketDurumHandler(kurulu=['com.hedef'])
    handler.enable_hata = 'Error: no such package'
    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.enable('S', 'com.hedef')
    assert 'Aktif edilemedi' in str(exc.value)


def test_enable_kurulu_degilse():
    eng = ShellEngine(PaketDurumHandler(kurulu=['com.diger']))
    with pytest.raises(AdbError) as exc:
        eng.enable('S', 'com.hedef')
    assert 'kurulu değil' in str(exc.value)


def test_enable_hala_devre_disi():
    handler = PaketDurumHandler(kurulu=['com.hedef'],
                                devre_disi=['com.hedef'])
    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.enable('S', 'com.hedef')
    assert 'hâlâ devre dışı' in str(exc.value)


# --- disable_user ------------------------------------------------------------

def test_disable_user_basarili():
    eng = ShellEngine(PaketDurumHandler(kurulu=['com.hedef']))
    r = eng.disable_user('S', 'com.hedef')
    assert r.exit_code == 0
    assert eng.calls[0] == ['am', 'force-stop', '--user', '0', 'com.hedef']
    assert eng.calls[1] == ['pm', 'disable-user', '--user', '0', 'com.hedef']


def test_disable_user_force_stop_hatasi_yutulur():
    handler = PaketDurumHandler(kurulu=['com.hedef'])
    handler.force_stop_hata = True
    eng = ShellEngine(handler)
    assert eng.disable_user('S', 'com.hedef').exit_code == 0


def test_disable_user_hata_metni():
    handler = PaketDurumHandler(kurulu=['com.hedef'])
    handler.disable_hata = 'Failure [not allowed]'
    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.disable_user('S', 'com.hedef')
    assert 'Devre dışı birakilamadi' in str(exc.value)


def test_disable_user_hala_aktif():
    handler = PaketDurumHandler(kurulu=['com.hedef'])
    handler.disable_mutasyon = False
    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.disable_user('S', 'com.hedef')
    assert 'hala aktif' in str(exc.value)


def test_disable_user_gecersiz_paket():
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError):
        eng.disable_user('S', '')
    assert eng.calls == []


# --- uninstall_user ----------------------------------------------------------

def test_uninstall_user_basarili():
    eng = ShellEngine(PaketDurumHandler(kurulu=['com.hedef']))
    r = eng.uninstall_user('S', 'com.hedef')
    assert r.exit_code == 0
    assert ['pm', 'uninstall', '-k', '--user', '0', 'com.hedef'] in eng.calls


def test_uninstall_user_zaten_kaldirilmis():
    eng = ShellEngine(PaketDurumHandler(kurulu=[]))
    assert eng.uninstall_user('S', 'com.hedef') is None
    assert eng.calls == [['pm', 'list', 'packages', '--user', '0']]


def test_uninstall_user_dogrulanamazsa_hata():
    handler = PaketDurumHandler(kurulu=['com.hedef'])
    handler.uninstall_mutasyon = False
    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.uninstall_user('S', 'com.hedef')
    assert 'hâlâ kurulu' in str(exc.value)


def test_uninstall_user_yaris_durumu_basari_sayilir():
    handler = PaketDurumHandler(kurulu=['com.hedef'])
    handler.uninstall_cikti = 'Failure [not installed for 0]'
    eng = ShellEngine(handler)
    assert eng.uninstall_user('S', 'com.hedef').exit_code == 0


def test_uninstall_user_gecersiz_paket():
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError):
        eng.uninstall_user('S', 'kötü!')
    assert eng.calls == []


def test_uninstall_user_force_stop_hatasi_yutulur():
    handler = PaketDurumHandler(kurulu=['com.hedef'])
    handler.force_stop_hata = True
    eng = ShellEngine(handler)
    assert eng.uninstall_user('S', 'com.hedef').exit_code == 0
    assert ['pm', 'uninstall', '-k', '--user', '0', 'com.hedef'] in eng.calls


# --- install_existing --------------------------------------------------------

def test_install_existing_basarili_ve_aktif_edilir():
    handler = PaketDurumHandler(kurulu=['com.hedef'])
    eng = ShellEngine(handler)
    r = eng.install_existing('S', 'com.hedef')
    assert r.exit_code == 0
    assert eng.calls[0][:3] == ['cmd', 'package', 'install-existing']
    assert ['pm', 'enable', '--user', '0', 'com.hedef'] in eng.calls


def test_install_existing_pm_yedegine_duser():
    handler = PaketDurumHandler(kurulu=['com.hedef'])
    handler.cmd_install_hata = 'Failure [unknown package]'
    eng = ShellEngine(handler)
    assert eng.install_existing('S', 'com.hedef').exit_code == 0
    assert eng.calls[1][:2] == ['pm', 'install-existing']


def test_install_existing_dogrulanamazsa_hata():
    eng = ShellEngine(PaketDurumHandler(kurulu=[]))
    with pytest.raises(AdbError) as exc:
        eng.install_existing('S', 'com.hedef')
    assert 'Geri yuklenemedi' in str(exc.value)


def test_install_existing_gecersiz_paket():
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError):
        eng.install_existing('S', '')
    assert eng.calls == []


# --- smart_remove ------------------------------------------------------------

def test_smart_remove_disable_ile():
    eng = ShellEngine(PaketDurumHandler(kurulu=['com.hedef']))
    yontem, r = eng.smart_remove('S', 'com.hedef')
    assert yontem == 'disable'
    assert r.exit_code == 0


def test_smart_remove_uninstall_yedegi():
    handler = PaketDurumHandler(kurulu=['com.hedef'])
    handler.disable_hata = 'Failure [not allowed]'
    eng = ShellEngine(handler)
    yontem, r = eng.smart_remove('S', 'com.hedef')
    assert yontem == 'uninstall'
    assert ['pm', 'uninstall', '-k', '--user', '0', 'com.hedef'] in eng.calls


def test_smart_remove_ikisi_de_basarisiz():
    handler = PaketDurumHandler(kurulu=['com.hedef'])
    handler.disable_hata = 'Failure [not allowed]'
    handler.uninstall_cikti = 'Failure [not installed for 0]'
    handler.uninstall_mutasyon = False
    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.smart_remove('S', 'com.hedef')
    assert 'kaldirilamadi' in str(exc.value)
    assert 'disable:' in str(exc.value)
    assert 'uninstall:' in str(exc.value)


def test_smart_remove_belirsiz_durumda_kaldirmaz():
    handler = PaketDurumHandler(kurulu=['com.hedef'])
    handler.hata_listesi = True
    eng = ShellEngine(handler)
    with pytest.raises(PackageStateUnknownError):
        eng.smart_remove('S', 'com.hedef')
    assert ['pm', 'uninstall', '-k', '--user', '0', 'com.hedef'] not in eng.calls


# --- is_uninstalled_for_user / is_disabled -----------------------------------

def test_is_uninstalled_for_user():
    eng = ShellEngine(PaketDurumHandler(kurulu=['com.hedef']))
    assert eng.is_uninstalled_for_user('S', 'com.hedef') is False
    assert eng.is_uninstalled_for_user('S', 'com.yok') is True


def test_is_uninstalled_belirsizse_hata():
    handler = PaketDurumHandler(kurulu=['com.hedef'])
    handler.hata_listesi = True
    eng = ShellEngine(handler)
    with pytest.raises(PackageStateUnknownError) as exc:
        eng.is_uninstalled_for_user('S', 'com.hedef')
    assert 'doğrulanamadı' in str(exc.value)


def test_is_uninstalled_gecersiz_paket():
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError):
        eng.is_uninstalled_for_user('S', '')
    assert eng.calls == []


def test_is_disabled():
    handler = PaketDurumHandler(kurulu=['com.hedef'],
                                devre_disi=['com.hedef'])
    eng = ShellEngine(handler)
    assert eng.is_disabled('S', 'com.hedef') is True
    assert eng.is_disabled('S', 'com.diger') is False


def test_is_disabled_belirsizlik_varyantlari():
    handler = PaketDurumHandler()
    handler.list_istisna = True
    with pytest.raises(PackageStateUnknownError):
        ShellEngine(handler).is_disabled('S', 'com.hedef')

    handler2 = PaketDurumHandler()
    handler2.hata_listesi = True
    with pytest.raises(PackageStateUnknownError):
        ShellEngine(handler2).is_disabled('S', 'com.hedef')

    handler3 = PaketDurumHandler()
    handler3.list_hata_metni = 'Failure: denied'
    with pytest.raises(PackageStateUnknownError):
        ShellEngine(handler3).is_disabled('S', 'com.hedef')

    handler4 = PaketDurumHandler()
    handler4.list_hata_metni = ''
    handler4.kurulu = []
    eng4 = ShellEngine(handler4)
    eng4._handler = lambda call: (
        AdbResult(0, 'bozuk satir', '')
        if call[:2] == ['pm', 'list'] else None)
    with pytest.raises(PackageStateUnknownError) as exc:
        eng4.is_disabled('S', 'com.hedef')
    assert 'çözümlenemedi' in str(exc.value)


def test_is_disabled_gecersiz_paket():
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError):
        eng.is_disabled('S', '')
    assert eng.calls == []


# --- pm path -----------------------------------------------------------------

def test_pm_path_ve_paths():
    cikti = ('package:/data/app/com.x/base.apk\n'
             'package:/data/app/com.x/split_1.apk\n'
             'package:/data/app/com.x/base.apk\n')
    eng = ShellEngine(_sabit(cikti))
    assert eng.pm_path('S', 'com.x') == '/data/app/com.x/base.apk'
    assert eng.pm_paths('S', 'com.x') == [
        '/data/app/com.x/base.apk', '/data/app/com.x/split_1.apk']


def test_pm_path_eslesme_yoksa():
    eng = ShellEngine(_sabit(''))
    assert eng.pm_path('S', 'com.x') is None
    assert eng.pm_paths('S', 'com.x') == []


def test_pm_path_gecersiz_paket():
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError):
        eng.pm_path('S', 'kötü!')
    with pytest.raises(AdbError):
        eng.pm_paths('S', '')
    assert eng.calls == []


# --- pull / push -------------------------------------------------------------

def test_pull_basarili():
    eng = ShellEngine(_sabit('1 file pulled'))
    r = eng.pull('S', '/sdcard/a.txt', 'C:/tmp/a.txt')
    assert r.exit_code == 0
    assert eng.calls == [['-s', 'S', 'pull', '/sdcard/a.txt', 'C:/tmp/a.txt']]


def test_pull_hata():
    eng = ShellEngine(_sabit(exit_code=1, error='device offline'))
    with pytest.raises(AdbError) as exc:
        eng.pull('S', '/sdcard/a.txt', 'a.txt')
    assert 'Indirilemedi' in str(exc.value)
    assert 'device offline' in str(exc.value)


def test_push_basarili_ve_yol_kirpilir():
    eng = ShellEngine(_sabit('1 file pushed'))
    r = eng.push('S', 'C:/tmp/a.txt', '/sdcard/')
    assert r.exit_code == 0
    assert eng.calls == [['-s', 'S', 'push', 'C:/tmp/a.txt', '/sdcard']]


def test_push_hata_metni():
    eng = ShellEngine(_sabit('adb: failed to push some files'))
    with pytest.raises(AdbError) as exc:
        eng.push('S', 'a.txt', '/sdcard/a.txt')
    assert 'Yüklenemedi' in str(exc.value)


def test_push_ust_dizin_reddedilir():
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError) as exc:
        eng.push('S', 'a.txt', '/sdcard/../data/x')
    assert 'üst dizine' in str(exc.value)
    assert eng.calls == []


def test_pull_push_secenekleri_iletilir():
    class OptionEngine(ShellEngine):
        def __init__(self):
            super().__init__(lambda call: AdbResult(0, 'ok', ''))
            self.secenekler = []

        def run(self, args, timeout=30, binary=False, quiet_first=False,
                preserve_output_whitespace=False, cancel_check=None,
                hide_shell_from_trace=False):
            self.secenekler.append({'args': [str(a) for a in args],
                                    'timeout': timeout,
                                    'cancel_check': cancel_check})
            return AdbResult(0, 'ok', '')

    eng = OptionEngine()
    isaret = object()
    eng.pull('S', '/a', 'b', timeout=42, cancel_check=isaret)
    eng.push('S', 'b', '/a', timeout=43, cancel_check=isaret)
    assert eng.secenekler[0]['timeout'] == 42
    assert eng.secenekler[0]['cancel_check'] is isaret
    assert eng.secenekler[1]['timeout'] == 43
    assert eng.secenekler[1]['cancel_check'] is isaret


# --- launch zinciri ----------------------------------------------------------

def test_launch_leanback_ile():
    eng = ShellEngine(lambda call: (
        AdbResult(0, 'Events injected: 1', '')
        if call[:2] == ['monkey', '--user'] and '-c' in call else None))
    r = eng.launch('S', 'com.hedef')
    assert r.output == 'Events injected: 1'
    assert eng.calls == [[
        'monkey', '--user', '0', '-p', 'com.hedef', '-c',
        'android.intent.category.LEANBACK_LAUNCHER', '1']]


def test_launch_launcher_kategorisine_duser():
    def handler(call):
        if call[:2] == ['monkey', '--user'] and '-c' in call:
            if call[-2] == 'android.intent.category.LAUNCHER':
                return AdbResult(0, 'Events injected: 1', '')
            return AdbResult(0, 'No activities found', '')
        return None

    eng = ShellEngine(handler)
    assert eng.launch('S', 'com.hedef').exit_code == 0
    assert len(eng.calls) == 2


def test_launch_genel_monkey_yedegi():
    def handler(call):
        if call[:2] == ['monkey', '--user']:
            if '-c' in call:
                return AdbResult(0, 'No activities found', '')
            return AdbResult(0, 'Events injected: 1', '')
        return None

    eng = ShellEngine(handler)
    assert eng.launch('S', 'com.hedef').exit_code == 0
    assert eng.calls[-1] == ['monkey', '--user', '0', '-p', 'com.hedef', '1']


def test_launch_basarisiz():
    eng = ShellEngine(lambda call: (
        AdbResult(1, 'error: no activities', '')
        if call[:2] == ['monkey', '--user'] else None))
    with pytest.raises(AdbError) as exc:
        eng.launch('S', 'com.hedef')
    assert 'başlatılamadı' in str(exc.value)


def test_launch_gecersiz_paket():
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError):
        eng.launch('S', 'kötü!')
    assert eng.calls == []


def test_launch_app_temsilci():
    class TemsilciEngine(ShellEngine):
        def __init__(self):
            super().__init__(lambda call: None)
            self.resolved_calls = []

        def launch_resolved(self, target, pkg, timeout=15, user_id=0):
            self.resolved_calls.append((target, pkg, timeout, user_id))
            return 'sonuc'

    eng = TemsilciEngine()
    assert eng.launch_app('S', 'com.x', timeout=5, user_id=2) == 'sonuc'
    assert eng.resolved_calls == [('S', 'com.x', 5, 2)]


# --- home_activity -----------------------------------------------------------

def test_home_activity_ok():
    def handler(call):
        if call[:3] == ['cmd', 'package', 'resolve-activity']:
            return AdbResult(0, 'priority=0\ncom.hedef/.MainActivity\n', '')
        return None

    eng = ShellEngine(handler)
    assert eng.home_activity('S') == 'com.hedef/.MainActivity'


def test_home_activity_bulunamazsa_soru_isareti():
    eng = ShellEngine(_sabit('No activity found\nfoo/bar\n'))
    assert eng.home_activity('S') == '?'

    def handler(call):
        raise AdbError('kapali')

    eng2 = ShellEngine(handler)
    assert eng2.home_activity('S') == '?'


# --- kurulum sihirbazi -------------------------------------------------------

def test_mark_device_provisioned():
    eng = ShellEngine(lambda call: (
        AdbResult(0, '', '') if call[:2] == ['settings', 'put'] else None))
    assert eng.mark_device_provisioned('S') == [
        'global.device_provisioned', 'secure.user_setup_complete']


def test_mark_device_provisioned_kismi_basari():
    def handler(call):
        if call[:2] == ['settings', 'put']:
            return AdbResult(1 if call[2] == 'secure' else 0, '', '')
        return None

    eng = ShellEngine(handler)
    assert eng.mark_device_provisioned('S') == ['global.device_provisioned']


def test_mark_device_provisioned_istisna_yutulur():
    def handler(call):
        if call[:2] == ['settings', 'put']:
            if call[2] == 'global':
                raise AdbError('yetki yok')
            return AdbResult(0, '', '')
        return None

    eng = ShellEngine(handler)
    assert eng.mark_device_provisioned('S') == ['secure.user_setup_complete']


def test_disable_setup_blocker_basarili():
    def handler(call):
        if call[:2] == ['am', 'force-stop']:
            return AdbResult(0, '', '')
        if call[:2] == ['pm', 'disable-user']:
            return AdbResult(
                0, 'Package {} new state: disabled-user'.format(call[-1]), '')
        return None

    eng = ShellEngine(handler)
    r = eng.disable_setup_blocker('S', 'com.google.android.tvsetup')
    assert r.exit_code == 0
    assert eng.calls[-1] == [
        'pm', 'disable-user', '--user', '0', 'com.google.android.tvsetup']


def test_disable_setup_blocker_force_stop_hatasi_yutulur():
    def handler(call):
        if call[:2] == ['am', 'force-stop']:
            return AdbResult(1, 'Error: not found', '')
        if call[:2] == ['pm', 'disable-user']:
            return AdbResult(0, '', '')
        return None

    eng = ShellEngine(handler)
    assert eng.disable_setup_blocker('S', 'com.android.provision').exit_code == 0


def test_disable_setup_blocker_sihirbaz_degilse():
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError) as exc:
        eng.disable_setup_blocker('S', 'com.hedef.app')
    assert 'sihirbazi degil' in str(exc.value)
    assert eng.calls == []


def test_disable_setup_blocker_gecersiz_paket():
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError):
        eng.disable_setup_blocker('S', '')
    assert eng.calls == []


def test_disable_setup_blocker_hata_metni():
    def handler(call):
        if call[:2] == ['am', 'force-stop']:
            return AdbResult(0, '', '')
        if call[:2] == ['pm', 'disable-user']:
            return AdbResult(1, 'Failure [not allowed]', '')
        return None

    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.disable_setup_blocker('S', 'com.google.android.tvsetup')
    assert 'devre dışı birakilamadi' in str(exc.value)


# --- user_id sarmalayicilari -------------------------------------------------

def test_uninstall_user_id_temsilci():
    class KayitEngine(ShellEngine):
        def __init__(self):
            super().__init__(lambda call: None)
            self.kayit = []

        def uninstall_user(self, target, pkg, user_id=0):
            self.kayit.append(('uninstall', target, pkg, user_id))
            return 'u'

        def is_uninstalled_for_user(self, target, pkg, timeout=10, user_id=0):
            self.kayit.append(('kontrol', target, pkg, timeout, user_id))
            return True

    eng = KayitEngine()
    assert eng.uninstall_user_id('S', 'com.x', 5) == 'u'
    assert eng.is_uninstalled_for_user_id('S', 'com.x', 7, timeout=3) is True
    assert eng.kayit == [
        ('uninstall', 'S', 'com.x', 5),
        ('kontrol', 'S', 'com.x', 3, 7),
    ]
