# -*- coding: utf-8 -*-
"""network_tab: LAN tarama, Wi-Fi teshisi, DNS ve eslestirme akislari."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QResizeEvent, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QInputDialog,
    QMessageBox,
    QTableWidgetItem,
)

from mibox_app.ui import network_tab as net_mod
from mibox_app.ui.network_tab import (
    COL_IP,
    COL_LATENCY,
    COL_STATE,
    NetworkTab,
)
from mibox_app.workers import CancelledError


class _Motor:
    def __init__(self):
        self.calls = []
        self.dns = {'mode': 'hostname', 'specifier': 'dns.google'}
        self.diag = {}
        self.pair_sonuc = {'ok': True, 'user': 'tv'}
        self.get_patlak = False
        self.set_patlak = False
        self.diag_patlak = False
        self.pair_patlak = False

    def private_dns_get(self, target):
        self.calls.append(('private_dns_get', target))
        if self.get_patlak:
            raise RuntimeError('dns okunamadi')
        return dict(self.dns)

    def private_dns_set(self, target, mode, specifier):
        self.calls.append(('private_dns_set', target, mode, specifier))
        if self.set_patlak:
            raise RuntimeError('dns yazilamadi')
        return {'ok': True}

    def network_diagnostics(self, target):
        self.calls.append(('network_diagnostics', target))
        if self.diag_patlak:
            raise RuntimeError('teshis yok')
        return dict(self.diag)

    def pair(self, host, code):
        self.calls.append(('pair', host, code))
        if self.pair_patlak:
            raise RuntimeError('eslesme yok')
        return dict(self.pair_sonuc)


class _Cekirdek(QObject):
    connection_changed = Signal(bool, object)

    def __init__(self):
        super().__init__()
        self.connected = True
        self.target = 'tv-1'
        self.engine = _Motor()


class _Pencere:
    def __init__(self):
        self.runs = []
        self._workers = ()
        self._connection_busy = False
        self._closing = False
        self._close_pending = False
        self.logs = []
        self.target_fields = []
        self.connect_sayaci = 0
        self.patlak_run = False

    def _run(self, worker, desc=None):
        if self.patlak_run:
            raise RuntimeError('patladi')
        self.runs.append((worker, desc))

    def append_log(self, message, level='INFO'):
        self.logs.append((message, level))

    def _set_target_fields(self, target):
        self.target_fields.append(target)

    def on_connect(self):
        self.connect_sayaci += 1


class _SahteIsci(QObject):
    finished_ok = Signal(object)
    failed = Signal(str)
    finished = Signal()
    progress = Signal(int, int)
    device_found = Signal(str, str, str)

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.args = args
        self.kwargs = kwargs
        self.job_name = ''
        self.iptal = False
        self.cancel_patlak = False

    def cancel(self):
        self.iptal = True
        if self.cancel_patlak:
            raise RuntimeError('iptal edilemedi')

    def check_cancel(self):
        pass


@pytest.fixture
def net(qtbot, monkeypatch):
    monkeypatch.setattr(net_mod, 'local_subnet_guess', lambda: '10.0.0.')
    monkeypatch.setattr(net_mod, 'Worker', _SahteIsci)
    monkeypatch.setattr(net_mod, 'NetworkScanWorker', _SahteIsci)
    core = _Cekirdek()
    win = _Pencere()
    tab = NetworkTab(core, win)
    qtbot.addWidget(tab)
    return tab, core, win


class _SahteSoket:
    def __init__(self, ip):
        self.ip = ip

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def settimeout(self, _timeout):
        pass

    def connect(self, _address):
        if self.ip is None:
            raise OSError('ag yok')

    def getsockname(self):
        return (self.ip, 0)


def test_yerel_alt_ag_tahmini(monkeypatch):
    monkeypatch.setattr(net_mod.socket, 'socket',
                        lambda *a, **k: _SahteSoket('10.1.2.3'))
    assert net_mod.local_subnet_guess() == '10.1.2.'

    monkeypatch.setattr(net_mod.socket, 'socket',
                        lambda *a, **k: _SahteSoket(None))
    assert net_mod.local_subnet_guess() == '192.168.1.'

    monkeypatch.setattr(net_mod.socket, 'socket',
                        lambda *a, **k: _SahteSoket('abc'))
    assert net_mod.local_subnet_guess() == '192.168.1.'


def _tekerlek(widget, yon=120):
    ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0),
                     QPoint(0, yon), Qt.NoButton, Qt.NoModifier,
                     Qt.ScrollUpdate, False)
    widget.wheelEvent(ev)
    return ev


def test_kurulum_ve_tema(net):
    tab, _core, _win = net
    assert tab.txt_subnet.text() == '10.0.0.'
    assert tab.spn_from.value() == 1
    assert tab.spn_to.value() == 254
    assert tab.spn_port.value() == 5555
    assert tab.btn_stop.isEnabled() is False
    assert tab.progress.value() == 0
    assert tab.grid.columnCount() == 3
    basliklar = [tab.grid.horizontalHeaderItem(i).text() for i in range(3)]
    assert basliklar == ['IP Adresi', 'Durum', 'Gecikme']
    assert tab.btn_use is tab.btn_connect
    assert tab.results_card is tab.scan_card
    assert tab.lbl_dns_current.text() == (
        'Mevcut DNS: Ölçüm bekleniyor (Cihaza bağlanın)')
    assert tab.lbl_diag_advice.text() == (
        'TV Wi-Fi sinyal kalitesini, modem pingini ve paket kaybını test edin.')
    assert tab.diag_progress.isHidden() is True
    assert tab.lbl_wifi_signal.text() == '—'
    assert tab.lbl_wifi_signal_detail.text() == 'Ölçüm bekleniyor'
    assert tab.txt_custom_dns.text() == ''
    for button in (tab.btn_refresh_dns, tab.btn_dns_adguard,
                   tab.btn_dns_cloudflare, tab.btn_dns_google,
                   tab.btn_dns_off, tab.btn_apply_custom_dns):
        assert button.isEnabled() is True
    assert tab.btn_connect.isEnabled() is False
    assert tab.btn_copy_address.isEnabled() is False
    assert tab.btn_pair.isEnabled() is True

    assert _tekerlek(tab.spn_from).isAccepted() is False
    assert _tekerlek(tab.spn_to).isAccepted() is False
    assert _tekerlek(tab.spn_port).isAccepted() is False

    tab.setFixedSize(1000, 700)
    tab.resizeEvent(QResizeEvent(tab.size(), tab.size()))
    assert tab.width() == 1000
    assert tab._side_layout.direction() == QBoxLayout.LeftToRight
    tab.setFixedSize(400, 700)
    tab.resizeEvent(QResizeEvent(tab.size(), tab.size()))
    assert tab.width() == 400
    assert tab._side_layout.direction() == QBoxLayout.TopToBottom

    tab.apply_theme()
    assert tab.lbl_dns_current.styleSheet().startswith(
        'font-size: 11px; font-weight: 600; color: #')
    tab._on_device_found('10.0.0.7', 'açık', 12)
    tab.apply_theme()
    item = tab.grid.item(0, COL_STATE)
    assert item.foreground().color().name() != '#000000'
    tab.grid.insertRow(1)
    tab.grid.setItem(1, COL_IP, QTableWidgetItem('bos'))
    tab.apply_theme()


def test_cihaz_kontrolleri_ve_kopyalama(net):
    tab, core, win = net
    NetworkTab._sync_device_controls(SimpleNamespace())

    def durumlar():
        return [tab.btn_refresh_dns.isEnabled(),
                tab.txt_custom_dns.isEnabled(),
                tab.btn_run_diag.isEnabled(),
                tab.btn_connect.isEnabled(),
                tab.btn_copy_address.isEnabled(),
                tab.btn_pair.isEnabled()]

    assert tab._device_ready() is True
    assert durumlar() == [True, True, True, False, False, True]

    core.connected = False
    tab._sync_device_controls()
    assert tab._device_ready() is False
    assert durumlar() == [False, False, False, False, False, True]
    core.connected = True

    win._connection_busy = True
    tab._sync_device_controls()
    assert durumlar() == [False, False, False, False, False, False]
    win._connection_busy = False

    tab._dns_busy = True
    tab._sync_device_controls()
    assert tab.btn_refresh_dns.isEnabled() is False
    assert tab.txt_custom_dns.isEnabled() is False
    tab._dns_busy = False

    tab._diag_worker = SimpleNamespace()
    tab._sync_device_controls()
    assert tab.btn_run_diag.isEnabled() is False
    tab._diag_worker = None

    tab._pair_worker = SimpleNamespace()
    tab._sync_device_controls()
    assert tab.btn_pair.isEnabled() is False
    tab._pair_worker = None

    tab._copy_selected_address()
    assert tab.lbl_summary.text().startswith('💡 İpucu:')

    tab._on_device_found('10.0.0.9', 'açık', 15)
    assert tab.btn_connect.isEnabled() is True
    assert tab.btn_copy_address.isEnabled() is True
    tab._copy_selected_address()
    assert QApplication.clipboard().text() == '10.0.0.9:5555'
    assert tab.lbl_summary.text() == (
        'Seçili cihaz adresi kopyalandı: 10.0.0.9:5555')

    tab.grid.item(0, COL_IP).setData(Qt.UserRole + 1, 9999)
    tab._copy_selected_address()
    assert QApplication.clipboard().text() == '10.0.0.9:9999'

    tab.grid.setCurrentCell(-1, -1)
    assert tab._selected_ip() is None
    tab.grid.setRowCount(0)
    tab.grid.insertRow(0)
    tab.grid.setItem(0, COL_IP, QTableWidgetItem('📺  10.0.0.42'))
    tab.grid.setCurrentCell(0, 0)
    assert tab._selected_ip() == '10.0.0.42'
    tab.grid.item(0, COL_IP).setData(Qt.UserRole, '')
    assert tab._selected_ip() == '10.0.0.42'
    tab.grid.item(0, COL_IP).setData(Qt.UserRole, '10.1.1.1')
    assert tab._selected_ip() == '10.1.1.1'
    tab.grid.takeItem(0, COL_IP)
    assert tab._selected_ip() is None


def test_baglanti_degisimi(net):
    tab, core, win = net
    core.connection_changed.emit(True, 'tv-1')
    assert tab._generation == 1
    assert tab.lbl_dns_current.text() == 'Mevcut DNS: Okunuyor…'
    ilk = len(win.runs)
    assert ilk == 1

    tab.lbl_wifi_signal.setText('dolu')
    core.target = None
    core.connection_changed.emit(True, None)
    assert tab.lbl_wifi_signal.text() == '—'
    assert tab.lbl_wifi_signal_detail.text() == 'Ölçüm bekleniyor'
    assert tab.lbl_diag_advice.text() == (
        'Mevcut cihazın ağ durumunu ölçmek için Test Et’i seçin.')
    assert tab.lbl_dns_current.text() == (
        'Mevcut DNS: Bağlantının tamamlanması bekleniyor')

    core.connected = False
    core.connection_changed.emit(False, None)
    assert tab.lbl_dns_current.text() == 'Mevcut DNS: Cihaz bağlı değil'

    core.connected = True
    core.target = 'tv-1'


def test_dns_okuma(net):
    tab, core, win = net
    core.target = None
    tab._fetch_dns_status()
    assert tab.lbl_dns_current.text() == 'Mevcut DNS: Bağlantı hazır değil'
    core.target = 'tv-1'

    tab._fetch_dns_status()
    w = win.runs[-1][0]
    assert tab.lbl_dns_current.text() == 'Mevcut DNS: Okunuyor…'
    assert w.args[0]() == {'mode': 'hostname', 'specifier': 'dns.google'}
    assert core.engine.calls[-1] == ('private_dns_get', 'tv-1')
    w.finished_ok.emit({'mode': 'hostname', 'specifier': 'dns.google'})
    assert tab.lbl_dns_current.text() == 'Mevcut DNS: Sunucu kayıtlı: dns.google'

    tab._fetch_dns_status()
    w = win.runs[-1][0]
    w.finished_ok.emit({'mode': 'opportunistic'})
    assert tab.lbl_dns_current.text() == 'Mevcut DNS: Otomatik (Fırsatçı)'

    tab._fetch_dns_status()
    w = win.runs[-1][0]
    w.finished_ok.emit({'mode': 'off'})
    assert tab.lbl_dns_current.text() == (
        'Mevcut DNS: Kapalı (İSS / Modem Varsayılanı)')

    tab._fetch_dns_status()
    w = win.runs[-1][0]
    w.finished_ok.emit({'mode': 'bilinmeyen'})
    assert tab.lbl_dns_current.text() == (
        'Mevcut DNS: Ayar tam okunamadı; DNS Oku ile yeniden deneyin.')

    tab._fetch_dns_status()
    w = win.runs[-1][0]
    onceki = tab.lbl_dns_current.text()
    tab._generation += 1
    w.finished_ok.emit({'mode': 'off'})
    assert tab.lbl_dns_current.text() == onceki

    tab._fetch_dns_status()
    w = win.runs[-1][0]
    w.failed.emit('kopma')
    assert tab.lbl_dns_current.text() == 'DNS okunamadı: kopma'

    tab._fetch_dns_status()
    w = win.runs[-1][0]
    onceki = tab.lbl_dns_current.text()
    tab._generation += 1
    w.failed.emit('yine kopma')
    assert tab.lbl_dns_current.text() == onceki

    tab._fetch_dns_status()
    w = win.runs[-1][0]
    tab._generation += 1
    with pytest.raises(CancelledError):
        w.args[0]()


def test_dns_ayarlama_ve_ozel(net, monkeypatch):
    tab, core, win = net
    bilgi, uyari = [], []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgi.append(a))
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: uyari.append(a))

    tab._dns_busy = True
    tab._set_dns_preset('hostname', 'x', 'X')
    assert win.runs == []
    tab._dns_busy = False

    core.connected = False
    tab._set_dns_preset('hostname', 'x', 'X')
    assert bilgi[-1][1] == 'Bağlantı Yok'
    assert bilgi[-1][2] == 'DNS ayarlamak için önce bir TV cihazına bağlanın.'
    core.connected = True

    tab._set_dns_preset('hostname', 'dns.adguard-dns.com', 'AdGuard DNS')
    w, desc = win.runs[-1]
    assert desc == 'DNS Ayarlanıyor: AdGuard DNS'
    assert tab._dns_busy is True
    assert tab.lbl_dns_current.text() == 'DNS ayarlanıyor: AdGuard DNS...'
    assert tab.btn_dns_adguard.isEnabled() is False
    assert w.args[0]() == {'ok': True}
    assert core.engine.calls[-1] == ('private_dns_set', 'tv-1', 'hostname',
                                     'dns.adguard-dns.com')
    w.finished_ok.emit({'ok': True})
    assert win.logs[-1] == (
        'Özel DNS güncellendi: mode=hostname, specifier=dns.adguard-dns.com',
        'INFO')
    assert bilgi[-1][1] == 'DNS Güncellendi'
    assert 'AdGuard DNS (dns.adguard-dns.com)' in bilgi[-1][2]
    assert tab.lbl_dns_current.text() == 'Mevcut DNS: Okunuyor…'
    w.finished.emit()
    assert tab._dns_busy is False
    assert tab.btn_dns_adguard.isEnabled() is True

    tab._set_dns_preset('hostname', 'dns.google', 'Google DNS')
    w2 = win.runs[-1][0]
    onceki = tab.lbl_dns_current.text()
    sayi = len(bilgi)
    tab._generation += 1
    w2.finished_ok.emit({'ok': True})
    assert len(bilgi) == sayi
    assert tab.lbl_dns_current.text() == onceki
    w2.finished.emit()

    tab._set_dns_preset('off', '', 'Kapalı')
    w3 = win.runs[-1][0]
    assert w3.args[0]() == {'ok': True}
    assert core.engine.calls[-1] == ('private_dns_set', 'tv-1', 'off', '')
    w3.failed.emit('zaman aşımı')
    assert tab.lbl_dns_current.text() == 'DNS ayarlanamadı.'
    assert uyari[-1][1] == 'DNS Hatası'
    assert 'zaman aşımı' in uyari[-1][2]
    w3.finished.emit()

    sayi = len(uyari)
    tab._set_dns_preset('off', '', 'Kapalı')
    w4 = win.runs[-1][0]
    onceki = tab.lbl_dns_current.text()
    tab._generation += 1
    w4.failed.emit('eski hata')
    assert len(uyari) == sayi
    assert tab.lbl_dns_current.text() == onceki
    w4.finished.emit()

    tab._set_dns_preset('hostname', 'dns.google', 'Google DNS')
    w5 = win.runs[-1][0]
    tab._generation += 1
    with pytest.raises(CancelledError):
        w5.args[0]()
    w5.finished.emit()

    win.patlak_run = True
    with pytest.raises(RuntimeError):
        tab._set_dns_preset('hostname', 'dns.google', 'Google DNS')
    win.patlak_run = False
    assert tab._dns_busy is False

    sayi = len(uyari)
    tab.txt_custom_dns.setText('   ')
    tab._apply_custom_dns()
    assert len(uyari) == sayi + 1
    assert uyari[-1][1] == 'Eksik Bilgi'

    tab.txt_custom_dns.setText('dns.nextdns.io')
    tab._apply_custom_dns()
    w6 = win.runs[-1][0]
    assert tab.lbl_dns_current.text() == (
        'DNS ayarlanıyor: Özel (dns.nextdns.io)...')
    assert w6.args[0]() == {'ok': True}
    assert core.engine.calls[-1] == ('private_dns_set', 'tv-1', 'hostname',
                                     'dns.nextdns.io')
    w6.finished.emit()
    assert tab._dns_busy is False


def test_dns_logsuz_pencere(qtbot, monkeypatch):
    monkeypatch.setattr(net_mod, 'local_subnet_guess', lambda: '10.0.0.')
    monkeypatch.setattr(net_mod, 'Worker', _SahteIsci)
    core = _Cekirdek()
    win = SimpleNamespace(runs=[], _connection_busy=False)
    win._run = lambda w, desc=None: win.runs.append((w, desc))
    tab = NetworkTab(core, win)
    qtbot.addWidget(tab)
    bilgi = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgi.append(a))

    tab._set_dns_preset('hostname', 'dns.google', 'Google DNS')
    w = win.runs[-1][0]
    w.finished_ok.emit({'ok': True})
    assert bilgi[-1][1] == 'DNS Güncellendi'
    w.finished.emit()


def test_teshis(net, monkeypatch):
    tab, core, win = net
    bilgi = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgi.append(a))

    tab._diag_worker = SimpleNamespace()
    tab._run_diagnostics()
    assert win.runs == []
    tab._diag_worker = None

    core.connected = False
    tab._run_diagnostics()
    assert bilgi[-1][1] == 'Bağlantı Yok'
    assert bilgi[-1][2] == 'Ağ teşhisi yapmak için önce bir cihaza bağlanın.'
    core.connected = True

    tab._run_diagnostics()
    w, desc = win.runs[-1]
    assert desc == 'Ağ: TV WiFi ve bağlantı kalitesi test ediliyor'
    assert w.job_name == 'TV Ağ Teşhisi'
    assert tab.btn_run_diag.isEnabled() is False
    assert tab.diag_progress.isHidden() is False
    assert tab.lbl_diag_advice.text() == (
        'Ağ ve Wi-Fi parametreleri ölçülüyor (ping, RSSI, link speed)...')
    assert w.args[0]() == {}
    assert core.engine.calls[-1] == ('network_diagnostics', 'tv-1')

    w.finished_ok.emit({
        'signal_label': 'Harika', 'rssi': -55, 'ssid': 'TestNetwork',
        'link_speed': '866 Mbps', 'frequency': '5 GHz',
        'gateway_ping_ms': 4, 'packet_loss_pct': 0, 'ip': '10.0.0.9',
        'interface': 'wlan0', 'health_rating': 'Mükemmel',
        'advice': 'Harika görünüyor.'})
    assert tab.lbl_wifi_signal.text() == 'Harika'
    assert tab.lbl_wifi_signal_detail.text() == 'TestNetwork (-55 dBm)'
    assert tab.lbl_wifi_speed.text() == '866 Mbps'
    assert tab.lbl_wifi_speed_detail.text() == '5 GHz'
    assert tab.lbl_gw_ping.text() == '4 ms'
    assert tab.lbl_gw_ping_detail.text() == '%0 paket kaybı'
    assert tab.lbl_net_ip.text() == '10.0.0.9'
    assert tab.lbl_net_ip_detail.text() == 'wlan0 (Wi-Fi)'
    assert tab.lbl_diag_advice.text() == 'Durum: Mükemmel — Harika görünüyor.'
    assert tab.btn_run_diag.isEnabled() is True
    assert tab.diag_progress.isHidden() is True

    w.finished_ok.emit({})
    assert tab.lbl_wifi_signal.text() == '—'
    assert tab.lbl_wifi_signal_detail.text() == 'Sinyal bilgisi alındı'
    assert tab.lbl_wifi_speed.text() == '—'
    assert tab.lbl_wifi_speed_detail.text() == 'Wi-Fi bağlantısı'
    assert tab.lbl_gw_ping.text() == '—'
    assert tab.lbl_gw_ping_detail.text() == 'Ping ölçülemedi'
    assert tab.lbl_net_ip.text() == '—'
    assert tab.lbl_net_ip_detail.text() == 'Ağ arabirimi'
    assert tab.lbl_diag_advice.text() == 'Durum: Ölçüm eksik — '

    w.finished_ok.emit({'ssid': '—', 'rssi_dbm': -80})
    assert tab.lbl_wifi_signal_detail.text() == '-80 dBm'
    w.finished_ok.emit({'ssid': 'TestNetwork', 'rssi': None, 'rssi_dbm': None})
    assert tab.lbl_wifi_signal_detail.text() == 'TestNetwork'
    w.finished_ok.emit({'gateway_ping_ms': None, 'packet_loss_pct': 12})
    assert tab.lbl_gw_ping_detail.text() == '%12 paket kaybı'
    w.finished_ok.emit({'interface': 'eth0'})
    assert tab.lbl_net_ip_detail.text() == 'eth0 (Ethernet)'
    w.finished_ok.emit({'interface': 'usb0'})
    assert tab.lbl_net_ip_detail.text() == 'usb0 (usb0)'
    w.finished_ok.emit({'link_speed': '', 'frequency': '—'})
    assert tab.lbl_wifi_speed.text() == '—'
    assert tab.lbl_wifi_speed_detail.text() == 'Wi-Fi bağlantısı'

    onceki = tab.lbl_wifi_signal.text()
    tab._generation += 1
    w.finished_ok.emit({'signal_label': 'YENI'})
    assert tab.lbl_wifi_signal.text() == onceki
    w.finished.emit()
    assert tab._diag_worker is None

    tab._run_diagnostics()
    w2 = win.runs[-1][0]
    w2.failed.emit('zaman aşımı')
    assert tab.lbl_diag_advice.text() == 'Teşhis tamamlanamadı: zaman aşımı'
    assert tab.btn_run_diag.isEnabled() is True
    assert tab.diag_progress.isHidden() is True
    tab._generation += 1
    onceki = tab.lbl_diag_advice.text()
    w2.failed.emit('eski hata')
    assert tab.lbl_diag_advice.text() == onceki
    w2.finished.emit()
    assert tab._diag_worker is None

    tab._run_diagnostics()
    w3 = win.runs[-1][0]
    tab._diag_worker = SimpleNamespace()
    w3.finished.emit()
    assert tab._diag_worker is not None
    tab._diag_worker = None

    tab._run_diagnostics()
    w4 = win.runs[-1][0]
    tab._generation += 1
    with pytest.raises(CancelledError):
        w4.args[0]()
    w4.finished.emit()

    win.patlak_run = True
    with pytest.raises(RuntimeError):
        tab._run_diagnostics()
    win.patlak_run = False
    assert tab._diag_worker is None


def test_tarama(net, monkeypatch):
    tab, _core, win = net
    uyari = []
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: uyari.append(a))

    tab._current_worker = object()
    tab.scan()
    assert win.runs == []
    tab._current_worker = None

    win._closing = True
    tab.scan()
    assert win.runs == []
    win._closing = False
    win._close_pending = True
    tab.scan()
    assert win.runs == []
    win._close_pending = False

    tab.txt_subnet.setText('10.0.')
    tab.scan()
    assert uyari[-1][1] == 'Subnet'
    assert '3 nokta' in uyari[-1][2]

    tab.txt_subnet.setText('10.0.999.')
    tab.scan()
    assert uyari[-1][2] == 'Ağ öneki geçerli IPv4 adresleri üretmelidir.'

    tab.txt_subnet.setText('10.0.0.')
    tab.spn_from.setValue(30)
    tab.spn_to.setValue(10)
    tab.scan()
    w, desc = win.runs[-1]
    assert desc == 'Ağ: 10.0.0.10-30 taranıyor'
    assert w.args == ('10.0.0.', 10, 30, 5555)
    assert tab.lbl_summary.text() == '🔍 Taranıyor: 10.0.0.10-30 :5555 ...'
    assert tab.btn_scan.isEnabled() is False
    assert tab.btn_stop.isEnabled() is True
    assert tab._stop_flag is False
    assert w in tab._scan_workers
    assert tab._current_worker is w

    w.device_found.emit('10.0.0.15', 'açık', '9')
    assert tab._found == [('10.0.0.15', 'açık', '9')]
    assert tab.grid.rowCount() == 1
    assert tab.lbl_summary.text() == (
        '🎯 Cihaz bulundu: 10.0.0.15 (9 ms)! "Bağlan" butonuna basarak '
        'bağlanabilirsiniz.')
    w.progress.emit(50, 100)
    assert tab.progress.value() == 50
    assert tab.lbl_summary.text() == (
        'Taranıyor: 50 / 100 adres · 🎯 1 cihaz bulundu')

    tab._stop_flag = True
    w.device_found.emit('10.0.0.16', 'açık', '9')
    w.progress.emit(80, 100)
    assert tab.grid.rowCount() == 1
    assert tab.progress.value() == 50
    tab._stop_flag = False

    w.finished_ok.emit([('10.0.0.15', 'açık', '9')])
    w.finished.emit()
    assert tab._current_worker is None
    assert w not in tab._scan_workers
    assert tab.progress.value() == 100
    assert tab.lbl_summary.text() == (
        '✅ Tarama tamamlandı: 1 cihaz bulundu. Çift tıklayarak veya "Bağlan" '
        'butonuyla hemen bağlanabilirsiniz.')
    assert tab.btn_scan.isEnabled() is True
    assert tab.btn_stop.isEnabled() is False

    tab.scan()
    w2 = win.runs[-1][0]
    w2.failed.emit('soket kapandı')
    w2.finished.emit()
    assert tab.lbl_summary.text() == 'Tarama hatası: soket kapandı'
    assert tab._current_worker is None

    tab.scan()
    w3 = win.runs[-1][0]
    w3.device_found.emit('10.0.0.20', 'açık', '5')
    tab._stop_scan()
    assert w3.iptal is True
    assert tab.lbl_summary.text() == '⏹ Tarama durduruldu · 1 cihaz bulundu.'
    assert tab.btn_stop.isEnabled() is False
    w3.finished.emit()
    assert tab._current_worker is None
    assert tab.btn_scan.isEnabled() is True

    tab.scan()
    w4 = win.runs[-1][0]
    win._closing = True
    w4.finished_ok.emit([('10.0.0.30', 'açık', '7')])
    w4.finished.emit()
    win._closing = False
    assert tab._current_worker is None

    win.patlak_run = True
    tab.scan()
    win.patlak_run = False
    assert tab.lbl_summary.text() == 'Tarama hatası: patladi'
    assert tab._current_worker is None


def test_tarama_durdurma_koseleri(net):
    tab, _core, _win = net
    tab._stop_scan()
    assert tab.lbl_summary.text() == '⏹ Tarama durduruldu.'

    class _Patlak:
        def cancel(self):
            raise RuntimeError('iptal yok')

    tab._current_worker = _Patlak()
    tab._stop_scan()
    tab._current_worker = None


def test_tarama_yardimcilari(net):
    tab, _core, _win = net
    tab._on_device_found('10.0.0.5', 'açık', 12)
    tab._on_device_found('10.0.0.5', 'açık', 12)
    assert tab.grid.rowCount() == 1
    assert tab.grid.item(0, COL_IP).text() == '📺  10.0.0.5'
    assert tab.grid.item(0, COL_IP).data(Qt.UserRole) == '10.0.0.5'
    assert tab.grid.item(0, COL_IP).data(Qt.UserRole + 1) == 5555
    assert tab.grid.item(0, COL_STATE).text() == '● açık'
    assert tab.grid.item(0, COL_LATENCY).text() == '12 ms'
    assert tab.grid.currentRow() == 0

    tab._on_device_found('10.0.0.6', 'açık', 20)
    assert tab.grid.rowCount() == 2
    assert tab.grid.currentRow() == 0

    tab._update_scan_progress(5, 0)
    onceki = tab.progress.value()
    tab._update_scan_progress(0, 0)
    assert tab.progress.value() == onceki

    tab._update_scan_progress(30, 100)
    assert tab.lbl_summary.text() == (
        'Taranıyor: 30 / 100 adres · 🎯 2 cihaz bulundu')
    tab._found = []
    tab._update_scan_progress(30, 100)
    assert tab.lbl_summary.text() == 'Taranıyor: 30 / 100 adres...'

    tab._on_device_found('10.0.0.10', 'açık', 5)
    tab._on_scan_failed('kullanıcı durdurdu')
    assert tab.lbl_summary.text() == '⏹ Tarama durduruldu · 1 cihaz bulundu.'

    tab._found = []
    tab._on_scan_failed('işlemci durdurdu')
    assert tab.lbl_summary.text() == '⏹ Tarama kullanıcı tarafından durduruldu.'

    tab._on_device_found('10.0.0.7', 'açık', 8)
    tab._on_scan_failed('süre aşımı')
    assert tab.lbl_summary.text() == 'Tarama hatası: süre aşımı'

    tab._found = []
    tab._on_scan_failed('süre aşımı')
    assert tab.lbl_summary.text() == 'Tarama hatası: süre aşımı'

    tab._on_scan_finished([])
    assert tab.lbl_summary.text() == (
        '0 cihaz bulundu (port açık değil veya cihaz çevrimdışı).')
    assert tab.progress.value() == 100

    tab._show_results([('10.0.0.8', 'açık', 11), ('10.0.0.9', 'açık', 13)])
    assert len(tab._found) == 2
    assert tab.grid.rowCount() == 2
    assert tab.lbl_summary.text().startswith(
        '✅ Tarama tamamlandı: 2 cihaz bulundu.')


def test_hedef_secimi_ve_baglanti(net, monkeypatch):
    tab, _core, win = net
    bilgi = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgi.append(a))

    tab._use_selected()
    assert bilgi[-1][1] == 'Cihaz Seçin'

    tab._on_device_found('10.0.0.9', 'açık', 15)
    tab.grid.item(0, COL_IP).setData(Qt.UserRole + 1, 9999)
    tab._use_selected()
    assert tab._pending_scan_target == '10.0.0.9:9999'
    assert tab._stop_flag is True
    assert win.connect_sayaci == 0

    tab._connect_scan_target()
    assert tab._pending_scan_target is None
    assert win.target_fields == ['10.0.0.9:9999']
    assert win.logs[-1] == ('Seçili ağ cihazına bağlantı başlatılıyor.', 'INFO')
    assert win.connect_sayaci == 1

    tab._connect_scan_target()
    assert win.connect_sayaci == 1

    tab._pending_scan_target = 'x:1'
    win._closing = True
    tab._connect_scan_target()
    assert tab._pending_scan_target is None
    win._closing = False

    tab._pending_scan_target = 'x:1'
    tab._scan_workers.add(object())
    tab._connect_scan_target()
    assert tab._pending_scan_target == 'x:1'
    tab._scan_workers.clear()

    win._connection_busy = True
    tab._connect_scan_target()
    assert tab._pending_scan_target is None
    assert tab.lbl_summary.text() == (
        'Devam eden işlem var; tamamlanınca cihazı yeniden seçin.')
    win._connection_busy = False

    tab._pending_scan_target = 'x:1'
    win._workers = (object(),)
    tab._connect_scan_target()
    assert tab._pending_scan_target is None
    win._workers = ()

    win._connection_busy = True
    tab._set_target('10.0.0.9:5555')
    assert tab._pending_scan_target is None
    assert tab.lbl_summary.text() == (
        'Bağlantı işlemi sürüyor; tamamlanınca cihazı yeniden seçin.')
    win._connection_busy = False


def test_cift_tiklama(net):
    tab, _core, _win = net
    tab._on_device_found('10.0.0.9', 'açık', 15)
    tab.grid.item(0, COL_IP).setData(Qt.UserRole + 1, 9999)
    idx = tab.grid.model().index(0, 0)
    tab._on_double_click(idx)
    assert tab._pending_scan_target == '10.0.0.9:9999'

    tab.grid.item(0, COL_IP).setData(Qt.UserRole, '')
    tab.grid.item(0, COL_IP).setData(Qt.UserRole + 1, 0)
    tab._on_double_click(idx)
    assert tab._pending_scan_target == '10.0.0.9:5555'

    tab._pending_scan_target = None
    tab.grid.insertRow(1)
    tab._on_double_click(tab.grid.model().index(1, 0))
    assert tab._pending_scan_target is None


def test_eslestirme(net, monkeypatch):
    tab, core, win = net
    uyari, bilgi = [], []
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: uyari.append(a))
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgi.append(a))
    cevaplar = []

    def sor(*a, **k):
        return cevaplar.pop(0)

    monkeypatch.setattr(QInputDialog, 'getText', sor)

    tab._pair_worker = SimpleNamespace()
    tab._pair()
    assert win.runs == []
    tab._pair_worker = None
    tab._pair_prompt = True
    tab._pair()
    assert win.runs == []
    tab._pair_prompt = False
    win._connection_busy = True
    tab._pair()
    assert win.runs == []
    win._connection_busy = False
    win._closing = True
    tab._pair()
    assert win.runs == []
    win._closing = False
    win._close_pending = True
    tab._pair()
    assert win.runs == []
    win._close_pending = False

    cevaplar.append(('', False))
    tab._pair()
    assert win.runs == []
    assert tab._pair_prompt is False

    cevaplar.append(('   ', True))
    tab._pair()
    assert win.runs == []

    cevaplar.extend([('10.0.0.1:5555', True), ('', False)])
    tab._pair()
    assert win.runs == []

    cevaplar.extend([('10.0.0.1:5555', True), ('12345', True)])
    tab._pair()
    assert uyari[-1][1] == 'Eşleştirme'
    assert uyari[-1][2] == 'Eşleştirme kodu 6 rakam olmalıdır.'

    cevaplar.extend([('10.0.0.1:5555', True), ('123456', True)])

    def sor_busy(*a, **k):
        cevap = cevaplar.pop(0)
        if not cevaplar:
            win._connection_busy = True
        return cevap

    monkeypatch.setattr(QInputDialog, 'getText', sor_busy)
    tab._pair()
    monkeypatch.setattr(QInputDialog, 'getText', sor)
    win._connection_busy = False
    assert tab.lbl_summary.text() == (
        'İşlem durumu değişti; eşleştirme başlatılmadı.')

    cevaplar.extend([('10.0.0.1:5555', True), ('123456', True)])
    tab._pair()
    w, desc = win.runs[-1]
    assert desc == 'Ağ: kablosuz eşleştirme'
    assert w.job_name == 'Kablosuz eşleştirme'
    assert tab._pair_worker is w
    assert tab.lbl_summary.text() == 'Kablosuz eşleştirme bekleniyor…'
    assert w.args[0]() == {'ok': True, 'user': 'tv'}
    assert core.engine.calls[-1] == ('pair', '10.0.0.1:5555', '123456')
    w.finished_ok.emit({'ok': True, 'user': 'tv'})
    w.finished.emit()
    assert tab._pair_worker is None
    assert tab.lbl_summary.text() == (
        'Eşleştirme tamamlandı. TV’deki bağlantı portuyla bağlanın.')
    assert bilgi[-1][1] == 'Eşleştirme tamamlandı'

    cevaplar.extend([('10.0.0.2:5555', True), ('654321', True)])
    tab._pair()
    w2 = win.runs[-1][0]
    w2.failed.emit('kod reddedildi')
    w2.finished.emit()
    assert tab.lbl_summary.text() == 'Eşleştirme tamamlanamadı: kod reddedildi'

    cevaplar.extend([('10.0.0.3:5555', True), ('654321', True)])
    tab._pair()
    w3 = win.runs[-1][0]
    w3.finished.emit()
    assert tab.lbl_summary.text() == 'Eşleştirme tamamlanamadı: Sonuç alınamadı.'

    cevaplar.extend([('10.0.0.4:5555', True), ('111111', True)])
    tab._pair()
    w4 = win.runs[-1][0]
    tab._pair_worker = SimpleNamespace()
    w4.finished.emit()
    assert tab._pair_worker is not None
    tab._pair_worker = None

    cevaplar.extend([('10.0.0.5:5555', True), ('222222', True)])
    tab._pair()
    w5 = win.runs[-1][0]
    win._closing = True
    w5.finished_ok.emit({'ok': True})
    w5.finished.emit()
    win._closing = False
    assert tab._pair_worker is None

    cevaplar.extend([('10.0.0.6:5555', True), ('333333', True)])
    win.patlak_run = True
    tab._pair()
    win.patlak_run = False
    assert tab.lbl_summary.text() == 'Eşleştirme tamamlanamadı: patladi'

    def patlak_dialog(*a, **k):
        raise RuntimeError('diyalog yok')

    monkeypatch.setattr(QInputDialog, 'getText', patlak_dialog)
    tab._pair()
    assert tab.lbl_summary.text() == 'Eşleştirme başlatılamadı: diyalog yok'
    assert tab._pair_prompt is False


def test_kompakt_dugme_property(qtbot, monkeypatch):
    monkeypatch.setattr(net_mod, 'local_subnet_guess', lambda: '10.0.0.')

    class _KompaktDugme(net_mod.QPushButton):
        def maximumHeight(self):
            return 20

    monkeypatch.setattr(net_mod, 'QPushButton', _KompaktDugme)
    core = _Cekirdek()
    win = _Pencere()
    tab = NetworkTab(core, win)
    qtbot.addWidget(tab)
    dugmeler = tab.findChildren(_KompaktDugme)
    assert dugmeler
    assert all(dugme.property('compact') is True for dugme in dugmeler)
