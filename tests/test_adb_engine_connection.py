# -*- coding: utf-8 -*-
"""AdbEngine baglanti yollari testleri (FakeEngine: ADB yok).

Kapsam: connect USB cihaz dogrulamasi, ag baglantisi, gecici hata tekrar
denemesi (istisna, metin ve durum hatalari), iptal geri cagrisi iletimi,
disconnect sarmalama ve pair IPv6/hostname dogrulama dallari ile maskeleme.
Gercek cihaz, ag veya bekleme kullanilmaz (time.sleep monkeypatch'lenir).
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


@pytest.fixture
def uyku(monkeypatch):
    kayit = []
    monkeypatch.setattr('time.sleep', lambda s: kayit.append(s))
    return kayit


# --- connect: USB cihaz ------------------------------------------------------

def test_connect_usb_cihaz_listesinden():
    def handler(call):
        if call == ['devices', '-l']:
            return AdbResult(0, 'List of devices attached\nR58M12345\tdevice\n', '')
        if call == ['-s', 'R58M12345', 'get-state']:
            return AdbResult(0, 'device', '')
        return None

    eng = ShellEngine(handler)
    assert eng.connect('R58M12345') == 'R58M12345'
    assert eng.calls == [['devices', '-l'], ['-s', 'R58M12345', 'get-state']]


def test_connect_usb_cihaz_bulunamazsa():
    eng = ShellEngine(lambda call: AdbResult(0, 'List of devices attached\n', '')
                      if call == ['devices', '-l'] else None)
    with pytest.raises(AdbError) as exc:
        eng.connect('YOK123')
    assert 'listesinde bulunamadı' in str(exc.value)


def test_connect_usb_cihaz_hazir_degil():
    def handler(call):
        if call == ['devices', '-l']:
            return AdbResult(
                0, 'List of devices attached\nABC\tunauthorized\n', '')
        return None

    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.connect('ABC')
    assert 'hazır değil (unauthorized)' in str(exc.value)
    assert eng.calls == [['devices', '-l']]


def test_connect_usb_get_state_offline():
    def handler(call):
        if call == ['devices', '-l']:
            return AdbResult(0, 'List of devices attached\nABC\tdevice\n', '')
        if call == ['-s', 'ABC', 'get-state']:
            return AdbResult(0, 'offline', '')
        return None

    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.connect('ABC')
    assert 'hazır değil' in str(exc.value)
    assert 'offline' in str(exc.value)


# --- connect: ag -------------------------------------------------------------

def test_connect_ag_basarili():
    def handler(call):
        if call == ['connect', '192.168.1.5:5555']:
            return AdbResult(0, 'connected to 192.168.1.5:5555', '')
        if call == ['-s', '192.168.1.5:5555', 'get-state']:
            return AdbResult(0, 'device', '')
        return None

    eng = ShellEngine(handler)
    assert eng.connect('192.168.1.5:5555') == '192.168.1.5:5555'
    assert eng.calls == [
        ['connect', '192.168.1.5:5555'],
        ['-s', '192.168.1.5:5555', 'get-state'],
    ]


def test_connect_ag_hata_metni():
    eng = ShellEngine(lambda call: AdbResult(
        0, 'failed to connect to 192.168.1.5:5555', '')
        if call == ['connect', '192.168.1.5:5555'] else None)
    with pytest.raises(AdbError) as exc:
        eng.connect('192.168.1.5:5555')
    assert 'Bağlantı başarısız' in str(exc.value)


def test_connect_ag_gecici_istisna_tekrar_dener(uyku):
    durum = {'n': 0}

    def handler(call):
        if call == ['connect', '10.0.0.9:5555']:
            durum['n'] += 1
            if durum['n'] == 1:
                raise AdbError('adb: timeout')
            return AdbResult(0, 'connected to 10.0.0.9:5555', '')
        if call == ['-s', '10.0.0.9:5555', 'get-state']:
            return AdbResult(0, 'device', '')
        return None

    eng = ShellEngine(handler)
    assert eng.connect('10.0.0.9:5555', deneme=2, bekleme=0.7) == \
        '10.0.0.9:5555'
    assert durum['n'] == 2
    assert uyku == [0.7]


def test_connect_ag_gecici_metin_tekrar_dener(uyku):
    durum = {'n': 0}

    def handler(call):
        if call == ['connect', '10.0.0.9:5555']:
            durum['n'] += 1
            if durum['n'] == 1:
                return AdbResult(1, 'connection refused', '')
            return AdbResult(0, 'connected to 10.0.0.9:5555', '')
        if call == ['-s', '10.0.0.9:5555', 'get-state']:
            return AdbResult(0, 'device', '')
        return None

    eng = ShellEngine(handler)
    assert eng.connect('10.0.0.9:5555', deneme=2, bekleme=0.1) == \
        '10.0.0.9:5555'
    assert durum['n'] == 2
    assert uyku == [0.1]


def test_connect_ag_gecici_durum_hatasi_tekrar_dener(uyku):
    durum = {'n': 0}

    def handler(call):
        if call == ['connect', '10.0.0.9:5555']:
            return AdbResult(0, 'connected to 10.0.0.9:5555', '')
        if call == ['-s', '10.0.0.9:5555', 'get-state']:
            durum['n'] += 1
            if durum['n'] == 1:
                return AdbResult(0, 'device offline', '')
            return AdbResult(0, 'device', '')
        return None

    eng = ShellEngine(handler)
    assert eng.connect('10.0.0.9:5555', deneme=2, bekleme=0.2) == \
        '10.0.0.9:5555'
    assert durum['n'] == 2
    assert uyku == [0.2]


def test_connect_ag_gecici_olmayan_hata_tekrar_denemez(uyku):
    durum = {'n': 0}

    def handler(call):
        if call == ['connect', '10.0.0.9:5555']:
            durum['n'] += 1
            return AdbResult(1, 'wrong password', '')
        return None

    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.connect('10.0.0.9:5555', deneme=2)
    assert 'Bağlantı başarısız' in str(exc.value)
    assert durum['n'] == 1
    assert uyku == []


def test_connect_ag_gecici_olmayan_istisna_tekrar_denemez(uyku):
    durum = {'n': 0}

    def handler(call):
        if call == ['connect', '10.0.0.9:5555']:
            durum['n'] += 1
            raise AdbError('adb: device unauthorized')
        return None

    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.connect('10.0.0.9:5555', deneme=2)
    assert 'unauthorized' in str(exc.value)
    assert durum['n'] == 1


def test_connect_ag_deneme_sifirsa_tek_deneme(uyku):
    durum = {'n': 0}

    def handler(call):
        if call == ['connect', '10.0.0.9:5555']:
            durum['n'] += 1
            return AdbResult(1, 'timeout', '')
        return None

    eng = ShellEngine(handler)
    with pytest.raises(AdbError):
        eng.connect('10.0.0.9:5555', deneme=0)
    assert durum['n'] == 1
    assert uyku == []


def test_connect_ag_iptal_durdurur():
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError) as exc:
        eng.connect('10.0.0.9:5555', cancel_check=lambda: True)
    assert 'durduruldu' in str(exc.value)
    assert eng.calls == []


def test_connect_iptal_geri_cagrisi_iletilir():
    class KayitEngine(ShellEngine):
        def __init__(self):
            super().__init__(lambda call: None)
            self.cancel_degerleri = []

        def run(self, args, timeout=30, binary=False, quiet_first=False,
                preserve_output_whitespace=False, cancel_check=None,
                hide_shell_from_trace=False):
            self.cancel_degerleri.append(cancel_check)
            call = [str(a) for a in args]
            self.calls.append(call)
            if call == ['connect', '10.0.0.9:5555']:
                return AdbResult(0, 'connected to 10.0.0.9:5555', '')
            if call == ['-s', '10.0.0.9:5555', 'get-state']:
                return AdbResult(0, 'device', '')
            return None

    eng = KayitEngine()

    def iptal():
        return False

    assert eng.connect('10.0.0.9:5555', cancel_check=iptal) == '10.0.0.9:5555'
    assert eng.cancel_degerleri == [iptal, iptal]


# --- disconnect --------------------------------------------------------------

def test_disconnect_usb_hedefi_atlanir():
    eng = ShellEngine(lambda call: None)
    assert eng.disconnect('R58M12345') is None
    assert eng.calls == []


def test_disconnect_ag_basarili():
    eng = ShellEngine(lambda call: AdbResult(
        0, 'disconnected 10.0.0.9:5555', ''))
    assert eng.disconnect('10.0.0.9:5555') is None
    assert eng.calls == [['disconnect', '10.0.0.9:5555']]


def test_disconnect_istisna_sarmalanir():
    def handler(call):
        raise AdbError('adb: server not running')

    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.disconnect('10.0.0.9:5555')
    assert 'bağlantısı kesilemedi' in str(exc.value)
    assert 'server not running' in str(exc.value)


def test_disconnect_cikis_kodu_detayi():
    eng = ShellEngine(lambda call: AdbResult(1, '', 'error: no such device'))
    with pytest.raises(AdbError) as exc:
        eng.disconnect('10.0.0.9:5555')
    assert 'bağlantısı kesilemedi' in str(exc.value)
    assert 'no such device' in str(exc.value)


def test_disconnect_bos_detay():
    eng = ShellEngine(lambda call: AdbResult(1, '', ''))
    with pytest.raises(AdbError) as exc:
        eng.disconnect('10.0.0.9:5555')
    assert 'çıkış koduyla tamamlandı' in str(exc.value)


# --- pair: IPv6 ve hostname dallari -----------------------------------------

def test_pair_ipv6_basarili():
    eng = ShellEngine(lambda call: AdbResult(
        0, 'Successfully paired to [fe80::1]:5555 [guid=adb-x]', ''))
    sonuc = eng.pair('[fe80::1]:5555', '123456')
    assert eng.calls == [['pair', '[fe80::1]:5555', '123456']]
    assert '******' in sonuc
    assert 'fe80::1' not in sonuc


@pytest.mark.parametrize('host_port', [
    '[fe80::1%wlan0]:5555',
    '[fe80::1:5555',
    '[fe80::1]x5555',
    '[fe80::zz]:5555',
])
def test_pair_ipv6_gecersiz(host_port):
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError) as exc:
        eng.pair(host_port, '123456')
    assert 'Geçersiz eşleştirme adresi' in str(exc.value)
    assert eng.calls == []


def test_pair_sayisal_ana_bilgisayar_reddedilir():
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError) as exc:
        eng.pair('999.1.1.1:5555', '123456')
    assert 'Geçersiz eşleştirme adresi' in str(exc.value)
    assert eng.calls == []


@pytest.mark.parametrize('host_port', [
    '-kotu-.local:5555',
    'kotu..local:5555',
    'a' * 254 + ':5555',
])
def test_pair_hostname_gecersiz(host_port):
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError) as exc:
        eng.pair(host_port, '123456')
    assert 'Geçersiz eşleştirme adresi' in str(exc.value)
    assert eng.calls == []


def test_pair_hostname_ve_sondaki_nokta():
    def handler(call):
        return AdbResult(
            0, 'Successfully paired to mibox.local:5555', '')

    eng = ShellEngine(handler)
    assert eng.pair('mibox.local:5555', '123456') is not None
    assert eng.calls == [['pair', 'mibox.local:5555', '123456']]

    eng2 = ShellEngine(handler)
    eng2.pair('mibox.local.:5555', '123456')
    assert eng2.calls == [['pair', 'mibox.local.:5555', '123456']]

    eng3 = ShellEngine(handler)
    eng3.pair('mibox:5555', '123456')
    assert eng3.calls == [['pair', 'mibox:5555', '123456']]


def test_pair_basarisiz_maskeleme():
    eng = ShellEngine(lambda call: AdbResult(
        0, 'Failed to pair to 192.168.1.5:5555 with code 123456', ''))
    with pytest.raises(AdbError) as exc:
        eng.pair('192.168.1.5:5555', '123456')
    mesaj = str(exc.value)
    assert 'Eşleştirme başarısız' in mesaj
    assert '192.168.1.5' not in mesaj
    assert '123456' not in mesaj
    assert '******' in mesaj


def test_pair_dogrulanmamis_cikti():
    eng = ShellEngine(lambda call: AdbResult(0, '', ''))
    with pytest.raises(AdbError) as exc:
        eng.pair('10.0.0.9:5555', '123456')
    assert 'Eşleştirme başarısız' in str(exc.value)
    assert 'doğrulamadı' in str(exc.value)
