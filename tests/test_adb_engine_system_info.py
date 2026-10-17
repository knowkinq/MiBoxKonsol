# -*- coding: utf-8 -*-
"""AdbEngine sistem bilgisi ve teshis testleri (FakeEngine: ADB yok).

Kapsam: network_diagnostics (rota/IP/WiFi/ping/tavsiye zinciri), cpu_info
(termal + sysfs yedegi), usb_storages, private_dns_get/set (dogrulama dahil),
quick_boost adim/iptal/bellek farki, start_screensaver yedegi ve
device_info_full alanlari. Gercek cihaz, ag veya disk kullanilmaz.
"""
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


# --- network_diagnostics -----------------------------------------------------

def _wifi_handler(rssi=-55, ping_avg=3.4, loss=0, freq=5180, ssid='TestNetwork'):
    def handler(call):
        if call == ['ip', 'route']:
            return AdbResult(0, 'default via 192.168.1.1 dev wlan0\n', '')
        if call[:3] == ['ip', '-o', '-4']:
            return AdbResult(0, 'inet 192.168.1.50/24 brd 192.168.1.255\n', '')
        if call[:2] == ['dumpsys', 'wifi']:
            return AdbResult(
                0,
                'mWifiInfo SSID: "{}", RSSI: {}, Link speed: 433Mbps\n'
                'Frequency: {} MHz\n'.format(ssid, rssi, freq), '')
        if call and call[0] == 'ping':
            return AdbResult(
                0,
                '3 packets transmitted, 3 received, {}% packet loss\n'
                'rtt min/avg/max/mdev = 1.0/{}/2.0/0.5 ms\n'.format(
                    loss, ping_avg), '')
        return None
    return handler


def test_network_diagnostics_wifi_tam_akis():
    eng = ShellEngine(_wifi_handler())
    diag = eng.network_diagnostics('S')
    assert diag['target'] == 'S'
    assert diag['interface'] == 'wlan0'
    assert diag['gateway'] == '192.168.1.1'
    assert diag['ip'] == '192.168.1.50'
    assert diag['ssid'] == 'TestNetwork'
    assert diag['rssi'] == -55
    assert diag['signal_pct'] == 90
    assert diag['signal_label'] == 'Mükemmel (-55 dBm)'
    assert diag['link_speed'] == '433 Mbps'
    assert diag['frequency'] == '5 GHz (5180 MHz)'
    assert diag['gateway_ping_ms'] == 3.4
    assert diag['packet_loss_pct'] == 0
    assert diag['health_rating'] == 'Mükemmel'
    assert 'gayet iyi' in diag['advice']
    assert ['ip', 'route'] in eng.calls
    assert ['dumpsys', 'wifi'] in eng.calls


@pytest.mark.parametrize('rssi, etiket', [
    (-55, 'Mükemmel (-55 dBm)'),
    (-65, 'İyi (-65 dBm)'),
    (-75, 'Orta / Zayıf (-75 dBm)'),
    (-85, 'Çok Zayıf (-85 dBm)'),
])
def test_network_diagnostics_sinyal_etiketleri(rssi, etiket):
    eng = ShellEngine(_wifi_handler(rssi=rssi))
    diag = eng.network_diagnostics('S')
    assert diag['signal_label'] == etiket
    assert diag['signal_pct'] == max(0, min(100, 2 * (rssi + 100)))


@pytest.mark.parametrize('freq, beklenen', [
    (2437, '2.4 GHz (2437 MHz)'),
    (5180, '5 GHz (5180 MHz)'),
])
def test_network_diagnostics_frekans_bandi(freq, beklenen):
    eng = ShellEngine(_wifi_handler(freq=freq))
    assert eng.network_diagnostics('S')['frequency'] == beklenen


def test_network_diagnostics_zayif_sinyal_tavsiyesi():
    eng = ShellEngine(_wifi_handler(rssi=-85))
    diag = eng.network_diagnostics('S')
    assert diag['health_rating'] == 'Zayıf Sinyal'
    assert 'çok zayıf' in diag['advice']


def test_network_diagnostics_paket_kaybi_tavsiyesi():
    eng = ShellEngine(_wifi_handler(loss=100))
    diag = eng.network_diagnostics('S')
    assert diag['packet_loss_pct'] == 100
    assert diag['health_rating'] == 'Kritik / Paket Kaybı Var'
    assert '%100 paket kaybı' in diag['advice']


def test_network_diagnostics_yuksek_gecikme_tavsiyesi():
    eng = ShellEngine(_wifi_handler(ping_avg=42.5))
    diag = eng.network_diagnostics('S')
    assert diag['gateway_ping_ms'] == 42.5
    assert diag['health_rating'] == 'Yüksek Gecikme'
    assert '42.5 ms' in diag['advice']


def test_network_diagnostics_ethernet_dali():
    def handler(call):
        if call == ['ip', 'route']:
            return AdbResult(0, 'default via 10.0.0.1 dev eth0\n', '')
        if call[:3] == ['ip', '-o', '-4']:
            return AdbResult(0, 'inet 10.0.0.7/24\n', '')
        if call and call[0] == 'ping':
            return AdbResult(0, '0% packet loss\nrtt min/avg/max/mdev = 1/2/3/1 ms\n', '')
        return None

    eng = ShellEngine(handler)
    diag = eng.network_diagnostics('S')
    assert diag['interface'] == 'eth0'
    assert diag['ssid'] == 'Kablolu Bağlantı (Ethernet)'
    assert diag['signal_pct'] == 100
    assert diag['signal_label'] == 'Kablolu (Mükemmel)'
    assert ['dumpsys', 'wifi'] not in eng.calls


def test_network_diagnostics_ping_istisnasi():
    def handler(call):
        if call == ['ip', 'route']:
            return AdbResult(0, 'default via 192.168.1.1 dev wlan0\n', '')
        if call[:3] == ['ip', '-o', '-4']:
            return AdbResult(0, 'inet 192.168.1.50/24\n', '')
        if call[:2] == ['dumpsys', 'wifi']:
            return AdbResult(0, 'SSID: "TestNetwork"\n', '')
        if call and call[0] == 'ping':
            raise AdbError('ping kopuk')
        return None

    eng = ShellEngine(handler)
    diag = eng.network_diagnostics('S')
    assert diag['gateway'] == '192.168.1.1'
    assert diag['gateway_ping_ms'] is None
    assert diag['packet_loss_pct'] == 0
    assert diag['health_rating'] == 'Mükemmel'


def test_network_diagnostics_politika_tablosu_yedegi():
    def handler(call):
        if call == ['ip', 'route']:
            return AdbResult(0, '', '')
        if call == ['ip', 'route', 'show', 'table', 'all']:
            return AdbResult(0, 'default via 192.168.1.9 dev wlan0\n', '')
        if call[:3] == ['ip', '-o', '-4']:
            return AdbResult(0, '', '')
        if call[:2] == ['dumpsys', 'wifi']:
            return AdbResult(0, '', '')
        if call and call[0] == 'ping':
            return AdbResult(0, '', '')
        return None

    eng = ShellEngine(handler)
    diag = eng.network_diagnostics('S')
    assert diag['gateway'] == '192.168.1.9'
    assert ['ip', 'route', 'show', 'table', 'all'] in eng.calls


def test_network_diagnostics_tum_sorgular_hatali():
    def handler(call):
        raise AdbError('baglanti yok')

    eng = ShellEngine(handler)
    diag = eng.network_diagnostics('S')
    assert diag['ip'] == '—'
    assert diag['gateway'] == '—'
    assert diag['ssid'] == '—'
    assert diag['rssi'] is None
    assert diag['gateway_ping_ms'] is None
    assert diag['health_rating'] == 'Mükemmel'


# --- cpu_info ----------------------------------------------------------------

def test_cpu_info_thermalservice_ile():
    def handler(call):
        if call[:2] == ['getprop', 'ro.product.cpu.abi']:
            return AdbResult(0, 'arm64-v8a\n', '')
        if call[:2] == ['getprop', 'ro.soc.model']:
            return AdbResult(0, 'Amlogic S905X4\n', '')
        if call[:2] == ['cat', '/proc/cpuinfo']:
            return AdbResult(0, 'processor\t: 0\n' * 8 + 'Hardware\t: Amlogic\n', '')
        if call[:2] == ['dumpsys', 'thermalservice']:
            return AdbResult(0, 'Temperature{mValue=42.5, mType=1}\n', '')
        return None

    eng = ShellEngine(handler)
    out = eng.cpu_info('S')
    assert out == {'abi': 'arm64-v8a', 'soc': 'Amlogic S905X4',
                   'cores': 8, 'temp': '42.5°C'}


def test_cpu_info_sysfs_yedegi():
    def handler(call):
        if call[:2] == ['getprop', 'ro.product.cpu.abi']:
            return AdbResult(0, 'armeabi-v7a\n', '')
        if call[:2] == ['getprop', 'ro.soc.model']:
            return AdbResult(0, '', '')
        if call[:2] == ['getprop', 'ro.board.platform']:
            return AdbResult(0, 'amlogic\n', '')
        if call[:2] == ['cat', '/proc/cpuinfo']:
            raise AdbError('yok')
        if call[:2] == ['dumpsys', 'thermalservice']:
            return AdbResult(0, 'mValue=5.0\n', '')
        if call[:2] == ['cat', '/sys/class/thermal/thermal_zone0/temp']:
            return AdbResult(0, '45000\n', '')
        return None

    eng = ShellEngine(handler)
    out = eng.cpu_info('S')
    assert out['soc'] == 'amlogic'
    assert out['cores'] == 4
    assert out['temp'] == '45.0°C'


def test_cpu_info_sysfs_kucuk_deger():
    def handler(call):
        if call[:2] == ['getprop', 'ro.product.cpu.abi']:
            return AdbResult(0, '', '')
        if call[:2] == ['getprop', 'ro.soc.model']:
            return AdbResult(0, '', '')
        if call[:2] == ['getprop', 'ro.board.platform']:
            return AdbResult(0, '', '')
        if call[:2] == ['cat', '/proc/cpuinfo']:
            return AdbResult(0, '', '')
        if call[:2] == ['dumpsys', 'thermalservice']:
            return AdbResult(0, '', '')
        if call[:2] == ['cat', '/sys/class/thermal/thermal_zone0/temp']:
            return AdbResult(0, '45\n', '')
        return None

    eng = ShellEngine(handler)
    out = eng.cpu_info('S')
    assert out['abi'] == '?'
    assert out['soc'] == '?'
    assert out['temp'] == '45.0°C'


def test_cpu_info_tum_kaynaklar_yok():
    def handler(call):
        if call[:1] == ['getprop']:
            return AdbResult(0, '', '')
        raise AdbError('yok')

    eng = ShellEngine(handler)
    out = eng.cpu_info('S')
    assert out == {'abi': '?', 'soc': '?', 'cores': 4, 'temp': '?'}


def test_cpu_info_hardware_soc_yedegi():
    def handler(call):
        if call[:1] == ['getprop']:
            return AdbResult(0, '', '')
        if call[:2] == ['cat', '/proc/cpuinfo']:
            return AdbResult(
                0, 'processor : 0\nHardware : Amlogic S905X\n', '')
        raise AdbError('yok')

    eng = ShellEngine(handler)
    out = eng.cpu_info('S')
    assert out['soc'] == 'Amlogic S905X'
    assert out['cores'] == 1
    assert out['temp'] == '?'


# --- usb_storages ------------------------------------------------------------

def test_usb_storages_listeler():
    def handler(call):
        if call == ['ls', '-1', '/storage']:
            return AdbResult(
                0, 'emulated\nself\nsdcard\nABCD-1234\nknox-emulated\n', '')
        if call[:2] == ['df', '/storage/ABCD-1234']:
            return AdbResult(
                0,
                'Filesystem 1K-blocks Used Available Use% Mounted on\n'
                '/dev/block/sda1 31457280 1048576 30408704 4% '
                '/storage/ABCD-1234\n', '')
        return None

    eng = ShellEngine(handler)
    assert eng.usb_storages('S') == [{
        'name': 'USB Disk (ABCD-1234)',
        'path': '/storage/ABCD-1234',
        'total_kb': 31457280,
        'avail_kb': 30408704,
    }]


def test_usb_storages_df_cozulemezse_sifir():
    def handler(call):
        if call == ['ls', '-1', '/storage']:
            return AdbResult(0, 'ABCD-1234\n', '')
        if call[:2] == ['df', '/storage/ABCD-1234']:
            return AdbResult(0, 'boyle bir cihaz yok\n', '')
        return None

    eng = ShellEngine(handler)
    assert eng.usb_storages('S') == [{
        'name': 'USB Disk (ABCD-1234)',
        'path': '/storage/ABCD-1234',
        'total_kb': 0,
        'avail_kb': 0,
    }]


def test_usb_storages_df_sayisal_degilse():
    def handler(call):
        if call == ['ls', '-1', '/storage']:
            return AdbResult(0, 'ABCD-1234\n', '')
        if call[:2] == ['df', '/storage/ABCD-1234']:
            return AdbResult(
                0,
                'Filesystem 1K-blocks Used Available Use% Mounted on\n'
                'x abc 123 456 789 /storage/ABCD-1234\n', '')
        return None

    eng = ShellEngine(handler)
    assert eng.usb_storages('S') == [{
        'name': 'USB Disk (ABCD-1234)',
        'path': '/storage/ABCD-1234',
        'total_kb': 0,
        'avail_kb': 0,
    }]


def test_usb_storages_hata_bos_liste():
    def handler(call):
        raise AdbError('kapali')

    eng = ShellEngine(handler)
    assert eng.usb_storages('S') == []


# --- private_dns -------------------------------------------------------------

class DnsHandler:
    """settings private_dns anahtarlarini durum tutarak taklit eder."""

    def __init__(self):
        self.mod = 'null'
        self.spec = 'null'
        self.put_hata = ''
        self.delete_hata = ''
        self.get_hata = ''
        self.getirilen = None

    def __call__(self, call):
        if call[:2] == ['settings', 'put']:
            if self.put_hata:
                return AdbResult(1, self.put_hata, '')
            if call[3] == 'private_dns_mode':
                self.mod = call[4]
            else:
                self.spec = call[4]
            return AdbResult(0, '', '')
        if call[:2] == ['settings', 'delete']:
            if self.delete_hata:
                return AdbResult(1, self.delete_hata, '')
            self.spec = 'null'
            return AdbResult(0, '', '')
        if call[:2] == ['settings', 'get']:
            if self.get_hata:
                return AdbResult(1, self.get_hata, '')
            if self.getirilen is not None:
                deger = (self.getirilen[0] if call[3] == 'private_dns_mode'
                         else self.getirilen[1])
                return AdbResult(0, deger, '')
            deger = self.mod if call[3] == 'private_dns_mode' else self.spec
            return AdbResult(0, deger, '')
        return None


def test_private_dns_get_okur():
    handler = DnsHandler()
    handler.mod = 'hostname\n'
    handler.spec = 'dns.adguard.com\n'
    eng = ShellEngine(handler)
    assert eng.private_dns_get('S') == {
        'mode': 'hostname', 'specifier': 'dns.adguard.com'}


def test_private_dns_get_null_degerleri():
    eng = ShellEngine(DnsHandler())
    assert eng.private_dns_get('S') == {'mode': 'off', 'specifier': ''}


def test_private_dns_get_hata_varsayilan():
    def handler(call):
        raise AdbError('kapali')

    eng = ShellEngine(handler)
    assert eng.private_dns_get('S') == {'mode': 'off', 'specifier': ''}


def test_private_dns_set_hostname():
    handler = DnsHandler()
    eng = ShellEngine(handler)
    assert eng.private_dns_set('S', 'hostname', 'dns.adguard.com') == {
        'mode': 'hostname', 'specifier': 'dns.adguard.com'}
    assert ['settings', 'put', 'global', 'private_dns_mode', 'hostname'] \
        in eng.calls
    assert ['settings', 'put', 'global', 'private_dns_specifier',
            'dns.adguard.com'] in eng.calls


def test_private_dns_set_sondaki_nokta_kirpilir():
    handler = DnsHandler()
    eng = ShellEngine(handler)
    assert eng.private_dns_set('S', 'hostname', 'dns.adguard.com.') == {
        'mode': 'hostname', 'specifier': 'dns.adguard.com'}


def test_private_dns_set_off_specifier_siler():
    handler = DnsHandler()
    handler.mod = 'hostname'
    handler.spec = 'eski.dns.com'
    eng = ShellEngine(handler)
    assert eng.private_dns_set('S', 'off') == {'mode': 'off', 'specifier': ''}
    assert ['settings', 'delete', 'global', 'private_dns_specifier'] \
        in eng.calls


def test_private_dns_set_opportunistic():
    eng = ShellEngine(DnsHandler())
    assert eng.private_dns_set('S', 'opportunistic') == {
        'mode': 'opportunistic', 'specifier': ''}
    assert not any(call[:2] == ['settings', 'delete'] for call in eng.calls)


def test_private_dns_set_gecersiz_mod():
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError) as exc:
        eng.private_dns_set('S', 'auto')
    assert 'Gecersiz DNS modu' in str(exc.value)
    assert eng.calls == []


@pytest.mark.parametrize('specifier', ['adguard', '', 'kötü!host',
                                       'a' * 260 + '.com'])
def test_private_dns_set_gecersiz_sunucu(specifier):
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError) as exc:
        eng.private_dns_set('S', 'hostname', specifier)
    assert 'geçerli bir sunucu adı' in str(exc.value)
    assert eng.calls == []


def test_private_dns_set_put_hatasi():
    handler = DnsHandler()
    handler.put_hata = 'SecurityException: permission denied'
    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.private_dns_set('S', 'off')
    assert 'modu ayarlanamadı' in str(exc.value)


def test_private_dns_set_specifier_put_hatasi():
    def handler(call):
        if call[:2] == ['settings', 'put']:
            if call[3] == 'private_dns_specifier':
                return AdbResult(1, 'boom', '')
            return AdbResult(0, '', '')
        return None

    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.private_dns_set('S', 'hostname', 'dns.adguard.com')
    assert 'sunucusu ayarlanamadı' in str(exc.value)


def test_private_dns_set_delete_hatasi():
    handler = DnsHandler()
    handler.mod = 'hostname'
    handler.delete_hata = 'Error'
    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.private_dns_set('S', 'off')
    assert 'silinemedi' in str(exc.value)


def test_private_dns_set_dogrulama_uyusmazsa_hata():
    handler = DnsHandler()
    handler.getirilen = ('off\n', 'null\n')
    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.private_dns_set('S', 'hostname', 'dns.adguard.com')
    assert 'uygulanmadı' in str(exc.value)


def test_private_dns_set_dogrulama_okunamazsa_hata():
    handler = DnsHandler()
    handler.get_hata = 'Error'
    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.private_dns_set('S', 'off')
    assert 'doğrulanamadı' in str(exc.value)


def test_private_dns_set_specifier_dogrulanamazsa():
    def handler(call):
        if call[:2] == ['settings', 'put']:
            return AdbResult(0, '', '')
        if call[:2] == ['settings', 'get']:
            if call[3] == 'private_dns_mode':
                return AdbResult(0, 'hostname\n', '')
            return AdbResult(1, 'Error', '')
        return None

    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.private_dns_set('S', 'hostname', 'dns.adguard.com')
    assert 'sunucusu doğrulanamadı' in str(exc.value)


def test_private_dns_set_dogrulama_null_mod():
    def handler(call):
        if call[:2] == ['settings', 'put']:
            return AdbResult(0, '', '')
        if call[:2] == ['settings', 'delete']:
            return AdbResult(0, '', '')
        if call[:2] == ['settings', 'get']:
            return AdbResult(0, 'null\n', '')
        return None

    eng = ShellEngine(handler)
    assert eng.private_dns_set('S', 'off') == {'mode': 'off', 'specifier': ''}


# --- quick_boost -------------------------------------------------------------

class BoostEngine(ShellEngine):
    """health/trim/animator adimlarini taklit eden, kill-all'i kaydeden motor."""

    def __init__(self):
        super().__init__(lambda call: AdbResult(0, '', ''))
        self.health_cagrilari = 0
        self.trim_hata = False
        self.kill_hata = ''
        self.anim_hata = False
        self.mem_before = {'mem_total_kb': 1000, 'mem_avail_kb': 100}
        self.mem_after = {'mem_total_kb': 1000, 'mem_avail_kb': 600}

    def health(self, target, timeout=30):
        self.health_cagrilari += 1
        return self.mem_before if self.health_cagrilari == 1 \
            else self.mem_after

    def trim_caches(self, target, timeout=30):
        if self.trim_hata:
            raise AdbError('trim yok')

    def set_animator_scales(self, target, value, timeout=15):
        if self.anim_hata:
            raise AdbError('anim yok')

    def shell(self, target, *cmd, **kwargs):
        call = [str(c) for c in cmd]
        self.calls.append(call)
        if call == ['am', 'kill-all']:
            if self.kill_hata:
                return AdbResult(1, self.kill_hata, '')
            return AdbResult(0, '', '')
        raise AssertionError('Beklenmeyen shell cagrisi: {}'.format(call))


def test_quick_boost_basarili():
    eng = BoostEngine()
    sonuc = eng.quick_boost('S')
    assert sonuc['completed_steps'] == 3
    assert sonuc['failed_steps'] == 0
    assert sonuc['freed_mb'] == 0.5
    assert len(sonuc['summary']) == 3
    assert sonuc['health_before']['mem_avail_kb'] == 100
    assert sonuc['health_after']['mem_avail_kb'] == 600
    assert ['am', 'kill-all'] in eng.calls


def test_quick_boost_adim_hatalari():
    eng = BoostEngine()
    eng.trim_hata = True
    eng.kill_hata = 'boom'
    eng.anim_hata = True
    sonuc = eng.quick_boost('S')
    assert sonuc['completed_steps'] == 0
    assert sonuc['failed_steps'] == 3
    ozet = '\n'.join(sonuc['summary'])
    assert 'Onbellek temizleme' in ozet
    assert 'Surec sonlandirma' in ozet
    assert 'Animasyon olcekleri' in ozet


def test_quick_boost_iptal_geri_cagrisi():
    eng = BoostEngine()
    sayac = {'n': 0}

    def iptal():
        sayac['n'] += 1

    eng.quick_boost('S', check_cancel=iptal)
    assert sayac['n'] == 6


def test_quick_boost_bellek_farki_hesaplari():
    eng = BoostEngine()
    eng.mem_before = {}
    eng.mem_after = {}
    assert eng.quick_boost('S')['freed_mb'] is None

    eng2 = BoostEngine()
    eng2.mem_before = {'mem_total_kb': 1000, 'mem_avail_kb': 600}
    eng2.mem_after = {'mem_total_kb': 1000, 'mem_avail_kb': 100}
    assert eng2.quick_boost('S')['freed_mb'] == 0.0

    eng3 = BoostEngine()
    eng3.mem_after = {'mem_total_kb': 1000, 'mem_avail_kb': 99999}
    assert eng3.quick_boost('S')['freed_mb'] is None


def test_quick_boost_health_dict_degilse_ve_patlarsa():
    eng = BoostEngine()
    eng.mem_before = None
    eng.mem_after = None
    sonuc = eng.quick_boost('S')
    assert sonuc['health_before'] == {}
    assert sonuc['health_after'] == {}
    assert sonuc['freed_mb'] is None

    class PatlakHealth(BoostEngine):
        def health(self, target, timeout=30):
            raise RuntimeError('health yok')

    eng2 = PatlakHealth()
    sonuc2 = eng2.quick_boost('S')
    assert sonuc2['health_before'] == {}
    assert sonuc2['health_after'] == {}


# --- start_screensaver -------------------------------------------------------

def test_start_screensaver_dreams_ile():
    eng = ShellEngine(_sabit('Dream started'))
    r = eng.start_screensaver('S')
    assert r.output == 'Dream started'
    assert eng.calls == [['cmd', 'dreams', 'start-dreaming']]


def test_start_screensaver_backdrop_yedegi():
    def handler(call):
        if call[:2] == ['cmd', 'dreams']:
            return AdbResult(1, 'Error: unknown command', '')
        if call[:2] == ['am', 'start']:
            return AdbResult(0, 'Starting: Intent', '')
        return None

    eng = ShellEngine(handler)
    assert eng.start_screensaver('S').exit_code == 0
    assert eng.calls[1] == [
        'am', 'start', '-n', 'com.google.android.backdrop/.Backdrop']


def test_start_screensaver_hata_metni_yedek_tetikler():
    def handler(call):
        if call[:2] == ['cmd', 'dreams']:
            return AdbResult(0, 'Error: not found', '')
        if call[:2] == ['am', 'start']:
            return AdbResult(0, 'ok', '')
        return None

    eng = ShellEngine(handler)
    assert eng.start_screensaver('S').output == 'ok'


def test_start_screensaver_ikisi_de_basarisiz():
    def handler(call):
        if call[:2] == ['cmd', 'dreams']:
            return AdbResult(1, 'boom', '')
        if call[:2] == ['am', 'start']:
            return AdbResult(1, 'Exception: yok', '')
        return None

    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.start_screensaver('S')
    assert 'Ekran koruyucu başlatılamadı' in str(exc.value)


# --- device_info_full --------------------------------------------------------

class InfoEngine(ShellEngine):
    def device_info(self, target):
        return {'model': 'Mi Box'}


def test_device_info_full_tam_akis():
    def handler(call):
        if call[:2] == ['df', '/data']:
            return AdbResult(
                0,
                'Filesystem Size Used Avail Use% Mounted on\n'
                '/dev/block/dm-4 11G 5G 6G 45% /data\n', '')
        if call[:2] == ['dumpsys', 'battery']:
            return AdbResult(0, 'level: 87\nstatus: 2\n', '')
        if call[:1] == ['uptime']:
            return AdbResult(0, ' 12:34:56 up 3 days,  2:11,  0 users\n', '')
        if call[:2] == ['dumpsys', 'wifi']:
            return AdbResult(0, 'mWifiInfo SSID: "TestNetwork"\nip: 192.0.2.50\n', '')
        if call[:2] == ['wm', 'size']:
            return AdbResult(0, 'Physical size: 1920x1080\n', '')
        return None

    eng = InfoEngine(handler)
    info = eng.device_info_full('S')
    assert info['model'] == 'Mi Box'
    assert info['disk_data'] == '/dev/block/dm-4 11G 5G 6G 45% /data'
    assert info['battery'] == '87%'
    assert info['battery_status'] == '2'
    assert info['uptime'] == '12:34:56 up 3 days,  2:11,  0 users'
    assert info['wifi_ssid'] == 'TestNetwork'
    assert info['wifi_ip'] == '192.0.2.50'
    assert info['screen'] == 'Physical size: 1920x1080'


def test_device_info_full_ip_yedegi():
    def handler(call):
        if call[:2] == ['df', '/data']:
            return AdbResult(0, 'x\n', '')
        if call[:2] == ['dumpsys', 'battery']:
            return AdbResult(0, '', '')
        if call[:1] == ['uptime']:
            return AdbResult(0, '', '')
        if call[:2] == ['dumpsys', 'wifi']:
            return AdbResult(0, 'SSID: "TestNetwork"\n', '')
        if call[:2] == ['ip', 'route']:
            return AdbResult(0, 'src 10.0.0.7\n', '')
        if call[:2] == ['wm', 'size']:
            return AdbResult(0, '', '')
        return None

    eng = InfoEngine(handler)
    info = eng.device_info_full('S')
    assert info['wifi_ssid'] == 'TestNetwork'
    assert info['wifi_ip'] == '10.0.0.7'
    assert info['battery'] == '?'
    assert info['uptime'] == '?'
    assert info['screen'] == '?'


def test_device_info_full_ip_yedegi_istisnasi():
    def handler(call):
        if call[:2] == ['df', '/data']:
            return AdbResult(0, 'x\n', '')
        if call[:2] == ['dumpsys', 'battery']:
            return AdbResult(0, '', '')
        if call[:1] == ['uptime']:
            return AdbResult(0, '', '')
        if call[:2] == ['dumpsys', 'wifi']:
            return AdbResult(0, 'SSID: "TestNetwork"\n', '')
        if call[:2] == ['ip', 'route']:
            raise AdbError('ip kopuk')
        if call[:2] == ['wm', 'size']:
            return AdbResult(0, '', '')
        return None

    eng = InfoEngine(handler)
    info = eng.device_info_full('S')
    assert info['wifi_ssid'] == 'TestNetwork'
    assert info['wifi_ip'] == '?'


def test_device_info_full_hatalar_soru_isareti():
    def handler(call):
        raise AdbError('kapali')

    eng = InfoEngine(handler)
    info = eng.device_info_full('S')
    assert info['model'] == 'Mi Box'
    assert info['disk_data'] == '?'
    assert info['battery'] == '?'
    assert info['uptime'] == '?'
    assert info['wifi_ssid'] == '?'
    assert info['wifi_ip'] == '?'
    assert info['screen'] == '?'
