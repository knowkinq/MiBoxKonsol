# -*- coding: utf-8 -*-
"""Ag sekmesi: LAN'da ADB portu acik cihazlari tarar + eslestirme."""
import ipaddress
import re
import socket

from PySide6.QtCore import Slot, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QLineEdit,
    QSpinBox, QMessageBox, QInputDialog, QProgressBar, QSizePolicy, QFrame,
)

from ..workers import Worker, NetworkScanWorker
from . import kit

COL_IP = 0
COL_STATE = 1
COL_LATENCY = 2


def local_subnet_guess():
    """Yerel IP'den /24 on eki tahmin eder (orn: 192.168.1.)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(2)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
        parts = ip.split('.')
        if len(parts) == 4:
            return '.'.join(parts[:3]) + '.'
    except OSError:
        pass
    return '192.168.1.'


class NetworkTab(QWidget):
    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._found = []
        self._current_worker = None
        self._stop_flag = False
        self._build()
        self.core.connection_changed.connect(self._on_connection_changed)

    def _build(self):
        root = kit.page(self)
        root.setSpacing(8)
        self._root_layout = root

        # 1. BİRLEŞİK KART: LAN Cihaz Keşfi ve Port Taraması
        self.scan_card = QGroupBox('🔍 LAN Cihaz Keşfi · Port Taraması')
        self.scan_card.setObjectName('compactCard')
        self.scan_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.results_card = self.scan_card  # Geriye dönük uyumluluk referansı

        card_layout = QVBoxLayout(self.scan_card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(10)

        # Üst Bilgi Satırı
        hint_label = kit.hint_label(
            'Yerel Wi-Fi ağınızdaki açık ADB portlu (5555) Android TV / Mi Box cihazlarını otomatik arar ve listeler.')
        hint_label.setWordWrap(True)
        card_layout.addWidget(hint_label)

        # Tüm kontroller tek satırda yan yana (Kompakt, dar IP aralığı ve ferah yerleşim)
        spin_compact_style = '''
QSpinBox {
    padding-left: 6px;
    padding-right: 20px;
    padding-top: 1px;
    padding-bottom: 1px;
    border: 1px solid #334155;
    border-radius: 6px;
    background: #0f172a;
    color: #f8fafc;
    font-size: 12px;
}
QSpinBox:focus {
    border: 1.5px solid #6366f1;
}
QSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 17px;
    height: 13px;
    border-left: 1px solid #334155;
    border-bottom: 1px solid #334155;
    border-top-right-radius: 5px;
    background: #1e293b;
}
QSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 17px;
    height: 13px;
    border-left: 1px solid #334155;
    border-bottom-right-radius: 5px;
    background: #1e293b;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background: #475569;
}
QSpinBox::up-arrow {
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid #cbd5e1;
}
QSpinBox::down-arrow {
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #cbd5e1;
}
'''

        ctrl_row = QHBoxLayout()
        ctrl_row.setContentsMargins(0, 2, 0, 2)
        ctrl_row.setSpacing(6)

        lbl_prefix = QLabel('Ağ Öneki:')
        lbl_prefix.setStyleSheet('font-weight: 600; font-size: 11.5px;')

        self.txt_subnet = QLineEdit(local_subnet_guess())
        self.txt_subnet.setPlaceholderText('192.168.1.')
        self.txt_subnet.setFixedWidth(105)
        self.txt_subnet.setFixedHeight(28)
        self.txt_subnet.setToolTip('Taranacak yerel ağ öneki (Örn: 192.168.1.)')

        lbl_range = QLabel('IP Aralığı:')
        lbl_range.setStyleSheet('font-weight: 600; font-size: 11.5px;')

        self.spn_from = QSpinBox()
        self.spn_from.setRange(1, 254)
        self.spn_from.setValue(1)
        self.spn_from.setPrefix('')
        self.spn_from.setFixedWidth(62)
        self.spn_from.setFixedHeight(28)
        self.spn_from.setStyleSheet(spin_compact_style)
        self.spn_from.setToolTip('Başlangıç IP son hanesi')

        lbl_dash = QLabel('—')
        lbl_dash.setStyleSheet('color: #64748b; font-weight: bold;')

        self.spn_to = QSpinBox()
        self.spn_to.setRange(1, 254)
        self.spn_to.setValue(254)
        self.spn_to.setPrefix('')
        self.spn_to.setFixedWidth(62)
        self.spn_to.setFixedHeight(28)
        self.spn_to.setStyleSheet(spin_compact_style)
        self.spn_to.setToolTip('Bitiş IP son hanesi')

        lbl_port = QLabel('Port:')
        lbl_port.setStyleSheet('font-weight: 600; font-size: 11.5px;')

        self.spn_port = QSpinBox()
        self.spn_port.setRange(1, 65535)
        self.spn_port.setValue(5555)
        self.spn_port.setFixedWidth(78)
        self.spn_port.setFixedHeight(28)
        self.spn_port.setStyleSheet(spin_compact_style)
        self.spn_port.setToolTip('ADB bağlantı portu (Standart: 5555)')

        self.btn_scan = QPushButton('🔍 Ağda Ara')
        self.btn_scan.setProperty('primary', True)
        self.btn_scan.setFixedHeight(28)
        self.btn_scan.setFixedWidth(105)
        self.btn_scan.setStyleSheet('font-weight: bold; background: #6366f1; color: white;')
        self.btn_scan.clicked.connect(self.scan)
        self.btn_scan.setToolTip('Belirtilen aralıkta açık ADB portlu TV cihazlarını ara')

        self.btn_stop = QPushButton('⏹ Durdur')
        self.btn_stop.setProperty('role', 'danger')
        self.btn_stop.setFixedHeight(28)
        self.btn_stop.setFixedWidth(90)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_scan)
        self.btn_stop.setToolTip('Devam eden ağ taramasını durdur')

        ctrl_row.addWidget(lbl_prefix)
        ctrl_row.addWidget(self.txt_subnet)
        ctrl_row.addSpacing(6)
        ctrl_row.addWidget(lbl_range)
        ctrl_row.addWidget(self.spn_from)
        ctrl_row.addWidget(lbl_dash)
        ctrl_row.addWidget(self.spn_to)
        ctrl_row.addSpacing(6)
        ctrl_row.addWidget(lbl_port)
        ctrl_row.addWidget(self.spn_port)
        ctrl_row.addSpacing(10)
        ctrl_row.addWidget(self.btn_scan)
        ctrl_row.addWidget(self.btn_stop)
        ctrl_row.addStretch(1)

        card_layout.addLayout(ctrl_row)

        # İlerleme Çubuğu (Zarif ve Modern)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet("""
            QProgressBar {
                background: rgba(148, 163, 184, 0.12);
                border-radius: 3px;
                border: none;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #3b82f6);
                border-radius: 3px;
            }
        """)
        card_layout.addWidget(self.progress)

        # Bulunan Cihazlar Tablosu (Konforlu ve Dengeli Yükseklik)
        self.grid = kit.single_table(3, ['IP Adresi', 'Durum', 'Gecikme'])
        self.grid.setMinimumHeight(150)
        self.grid.setMaximumHeight(260)
        self.grid.setFixedHeight(175)
        kit.empty_state(self.grid, 'Ağdaki TV\'leri Keşfedin',
                        'Yukarıdaki "Ağda Ara" butonuna basarak ağınızdaki cihazları otomatik bulun.')
        self.grid.horizontalHeader().setSectionResizeMode(COL_IP, QHeaderView.Stretch)
        self.grid.horizontalHeader().setSectionResizeMode(COL_STATE, QHeaderView.ResizeToContents)
        self.grid.horizontalHeader().setSectionResizeMode(COL_LATENCY, QHeaderView.ResizeToContents)
        self.grid.doubleClicked.connect(self._on_double_click)
        card_layout.addWidget(self.grid, 1)

        # Alt Aksiyon ve Durum Çubuğu
        actions = QHBoxLayout()
        actions.setSpacing(10)

        self.lbl_summary = kit.status_label(
            '💡 İpucu: Listede beliren cihaza çift tıklayarak veya seçip "Bağlan" butonuna basarak hemen bağlanabilirsiniz.')
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setMinimumWidth(0)
        self.lbl_summary.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.btn_pair = QPushButton('📱 Eşleştir')
        self.btn_pair.setProperty('role', 'secondary')
        self.btn_pair.setFixedHeight(32)
        self.btn_pair.setToolTip('Android 11+ Kablosuz Eşleştirme (6 haneli kod)')
        self.btn_pair.clicked.connect(self._pair)

        self.btn_connect = QPushButton('🔗 Bağlan')
        self.btn_connect.setProperty('primary', True)
        self.btn_connect.setFixedHeight(32)
        self.btn_connect.setMinimumWidth(110)
        self.btn_connect.setStyleSheet('font-weight: bold; background: #10b981; color: white; padding: 0 16px;')
        self.btn_connect.setToolTip('Seçili TV cihazına hemen bağlan')
        self.btn_connect.clicked.connect(self._use_selected)
        self.btn_use = self.btn_connect  # Geriye dönük uyumluluk referansı

        actions.addWidget(self.lbl_summary, 1)
        actions.addWidget(self.btn_pair)
        actions.addWidget(self.btn_connect)
        card_layout.addLayout(actions)

        root.addWidget(self.scan_card)

        # TV Network & WiFi Diagnostics Card (Sol Kart)
        diag_card = QGroupBox('📶 Canlı TV WiFi · Ağ Sağlığı Teşhisi')
        diag_card.setObjectName('compactCard')
        diag_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        diag_layout = QVBoxLayout(diag_card)
        diag_layout.setContentsMargins(12, 10, 12, 10)
        diag_layout.setSpacing(6)

        diag_header = QHBoxLayout()
        diag_hint = QLabel('Sinyal · Modem Pingi')
        diag_hint.setStyleSheet('font-weight: 600; font-size: 11.5px;')
        diag_hint.setWordWrap(True)
        diag_hint.setMinimumWidth(0)
        self.btn_run_diag = QPushButton('🔍 Test Et')
        self.btn_run_diag.setToolTip('Bağlı Mi Box TV Wi-Fi sinyal kalitesini, modem pingini ve hızını test eder.')
        self.btn_run_diag.setProperty('accent', True)
        self.btn_run_diag.setFixedHeight(26)
        self.btn_run_diag.clicked.connect(self._run_diagnostics)
        diag_header.addWidget(diag_hint)
        diag_header.addStretch(1)
        diag_header.addWidget(self.btn_run_diag)
        diag_layout.addLayout(diag_header)

        metrics_grid = QGridLayout()
        metrics_grid.setSpacing(8)

        card_defs = [
            ('Wi-Fi Sinyali', 'lbl_wifi_signal', 'lbl_wifi_signal_detail'),
            ('Bağlantı Hızı', 'lbl_wifi_speed', 'lbl_wifi_speed_detail'),
            ('Modem Gecikmesi', 'lbl_gw_ping', 'lbl_gw_ping_detail'),
            ('TV Yerel IP', 'lbl_net_ip', 'lbl_net_ip_detail'),
        ]
        for idx, (title, val_attr, detail_attr) in enumerate(card_defs):
            m_box = QFrame()
            m_box.setObjectName('metricCard')
            m_box.setProperty('role', 'secondary')
            m_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            m_lay = QVBoxLayout(m_box)
            m_lay.setContentsMargins(8, 6, 8, 6)
            m_lay.setSpacing(2)

            m_title = QLabel(title)
            m_title.setObjectName('metricLabel')
            m_title.setProperty('role', 'quiet')

            m_val = QLabel('—')
            m_val.setStyleSheet('font-size: 14px; font-weight: 600;')
            m_val.setProperty('role', 'primary')
            setattr(self, val_attr, m_val)

            m_detail = QLabel('Ölçüm bekleniyor')
            m_detail.setProperty('role', 'quiet')
            m_detail.setStyleSheet('font-size: 10.5px;')
            m_detail.setWordWrap(True)
            setattr(self, detail_attr, m_detail)

            m_lay.addWidget(m_title)
            m_lay.addWidget(m_val)
            m_lay.addWidget(m_detail)
            r, c = divmod(idx, 2)
            metrics_grid.addWidget(m_box, r, c)

        diag_layout.addLayout(metrics_grid)

        self.diag_progress = QProgressBar()
        self.diag_progress.setRange(0, 100)
        self.diag_progress.setValue(0)
        self.diag_progress.setMaximumHeight(8)
        self.diag_progress.setTextVisible(False)
        self.diag_progress.hide()
        diag_layout.addWidget(self.diag_progress)

        self.lbl_diag_advice = QLabel('TV Wi-Fi sinyal kalitesini, modem pingini ve paket kaybını test edin.')
        self.lbl_diag_advice.setWordWrap(True)
        self.lbl_diag_advice.setProperty('role', 'quiet')
        diag_layout.addWidget(self.lbl_diag_advice)
        diag_layout.addStretch(1)

        # DNS & Reklam Engelleyici Kartı (Sağ Kart)
        dns_card = QGroupBox('🛡️ Özel DNS · Reklam Engelleme')
        dns_card.setObjectName('compactCard')
        dns_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        dns_layout = QVBoxLayout(dns_card)
        dns_layout.setContentsMargins(12, 10, 12, 10)
        dns_layout.setSpacing(6)

        dns_header = QHBoxLayout()
        dns_hint = QLabel('AdGuard · Cloudflare')
        dns_hint.setStyleSheet('font-weight: 600; font-size: 11.5px;')
        dns_hint.setWordWrap(True)
        dns_hint.setMinimumWidth(0)
        self.btn_refresh_dns = QPushButton('🔄 DNS Oku')
        self.btn_refresh_dns.setFixedHeight(26)
        self.btn_refresh_dns.setProperty('role', 'secondary')
        self.btn_refresh_dns.clicked.connect(self._fetch_dns_status)
        dns_header.addWidget(dns_hint)
        dns_header.addStretch(1)
        dns_header.addWidget(self.btn_refresh_dns)
        dns_layout.addLayout(dns_header)

        dns_desc = QLabel('TV için reklam engelleme veya hızlı/güvenli DNS seçin:')
        dns_desc.setProperty('role', 'quiet')
        dns_desc.setWordWrap(True)
        dns_layout.addWidget(dns_desc)

        # Preset Butonları (2x2 Dengeli Izgara)
        presets_grid = QGridLayout()
        presets_grid.setSpacing(6)

        self.btn_dns_adguard = QPushButton('🛡️ AdGuard')
        self.btn_dns_adguard.setFixedHeight(30)
        self.btn_dns_adguard.setProperty('primary', True)
        self.btn_dns_adguard.setToolTip('AdGuard DNS: Reklam ve takipçileri engeller')
        self.btn_dns_adguard.clicked.connect(lambda: self._set_dns_preset('hostname', 'dns.adguard-dns.com', 'AdGuard DNS'))

        self.btn_dns_cloudflare = QPushButton('⚡ Cloudflare')
        self.btn_dns_cloudflare.setFixedHeight(30)
        self.btn_dns_cloudflare.setProperty('role', 'secondary')
        self.btn_dns_cloudflare.setToolTip('Cloudflare 1.1.1.1: Hızlı ve güvenli DNS')
        self.btn_dns_cloudflare.clicked.connect(lambda: self._set_dns_preset('hostname', '1dot1dot1dot1.cloudflare-dns.com', 'Cloudflare DNS'))

        self.btn_dns_google = QPushButton('🔍 Google DNS')
        self.btn_dns_google.setFixedHeight(30)
        self.btn_dns_google.setProperty('role', 'secondary')
        self.btn_dns_google.setToolTip('Google DNS: dns.google')
        self.btn_dns_google.clicked.connect(lambda: self._set_dns_preset('hostname', 'dns.google', 'Google DNS'))

        self.btn_dns_off = QPushButton('❌ Kapat')
        self.btn_dns_off.setFixedHeight(30)
        self.btn_dns_off.setProperty('role', 'secondary')
        self.btn_dns_off.setToolTip('Özel DNS kapatılır, modem varsayılanı kullanılır')
        self.btn_dns_off.clicked.connect(lambda: self._set_dns_preset('off', '', 'Kapalı'))

        presets_grid.addWidget(self.btn_dns_adguard, 0, 0)
        presets_grid.addWidget(self.btn_dns_cloudflare, 0, 1)
        presets_grid.addWidget(self.btn_dns_google, 1, 0)
        presets_grid.addWidget(self.btn_dns_off, 1, 1)
        dns_layout.addLayout(presets_grid)

        # Özel DNS Giriş Satırı
        custom_row = QHBoxLayout()
        custom_row.setSpacing(6)
        self.txt_custom_dns = QLineEdit()
        self.txt_custom_dns.setPlaceholderText('Özel DNS (örn. dns.nextdns.io)...')
        self.txt_custom_dns.setFixedHeight(28)

        self.btn_apply_custom_dns = QPushButton('Uygula')
        self.btn_apply_custom_dns.setFixedHeight(28)
        self.btn_apply_custom_dns.clicked.connect(self._apply_custom_dns)

        custom_row.addWidget(QLabel('Özel:'))
        custom_row.addWidget(self.txt_custom_dns, 1)
        custom_row.addWidget(self.btn_apply_custom_dns)
        dns_layout.addLayout(custom_row)

        self.lbl_dns_current = QLabel('Mevcut DNS: Ölçüm bekleniyor (Cihaza bağlanın)')
        self.lbl_dns_current.setWordWrap(True)
        self.lbl_dns_current.setMinimumWidth(0)
        self.lbl_dns_current.setStyleSheet('font-size: 11px; font-weight: bold; color: #94a3b8;')
        dns_layout.addWidget(self.lbl_dns_current)
        dns_layout.addStretch(1)

        # Alt Bölüm: WiFi Teşhisi ve Özel DNS Yan Yana (Kullanıcı İsteği)
        side_layout = QHBoxLayout()
        side_layout.setSpacing(10)
        side_layout.addWidget(diag_card, 1)
        side_layout.addWidget(dns_card, 1)
        root.addLayout(side_layout)
        root.addStretch(1)
        self._stop_flag = False

    def _on_connection_changed(self, connected=False, target=None):
        if getattr(self.core, 'connected', False) and getattr(self.core, 'target', None):
            self._fetch_dns_status()
        else:
            self.lbl_dns_current.setText('Mevcut DNS: Cihaz bağlı değil')

    def _fetch_dns_status(self):
        if not self.core.connected or not self.core.target:
            self.lbl_dns_current.setText('Mevcut DNS: Cihaz bağlı değil')
            return
        target = self.core.target
        def do():
            return self.core.engine.private_dns_get(target)
        def on_ok(res):
            mode = res.get('mode', 'off')
            spec = res.get('specifier', '')
            if mode == 'hostname' and spec:
                if 'adguard' in spec.lower():
                    name = f'🛡️ AdGuard DNS ({spec}) - Reklam Engelleme Aktif'
                elif 'cloudflare' in spec.lower():
                    name = f'⚡ Cloudflare DNS ({spec}) - Hızlı DNS Aktif'
                elif 'google' in spec.lower():
                    name = f'🔍 Google DNS ({spec}) - Aktif'
                else:
                    name = f'Özel DNS: {spec} (Aktif)'
                self.lbl_dns_current.setText(f'Mevcut DNS: <font color="#4ade80"><b>{name}</b></font>')
            elif mode == 'opportunistic':
                self.lbl_dns_current.setText('Mevcut DNS: <b>Otomatik (Fırsatçı)</b>')
            else:
                self.lbl_dns_current.setText('Mevcut DNS: <font color="#94a3b8">Kapalı (İSS / Modem Varsayılanı)</font>')
        w = Worker(do)
        w.finished_ok.connect(on_ok)
        self.window._run(w)

    def _set_dns_preset(self, mode, specifier, label):
        if not self.core.connected or not self.core.target:
            QMessageBox.information(self, 'Bağlantı Yok', 'DNS ayarlamak için önce bir TV cihazına bağlanın.')
            return
        target = self.core.target
        self.lbl_dns_current.setText(f'DNS ayarlanıyor: {label}...')
        def do():
            return self.core.engine.private_dns_set(target, mode, specifier)
        def on_ok(res):
            if hasattr(self.window, 'append_log'):
                self.window.append_log(f'Özel DNS güncellendi: mode={mode}, specifier={specifier}', 'INFO')
            self._fetch_dns_status()
            QMessageBox.information(self, 'DNS Güncellendi', f'TV Özel DNS başarıyla ayarlandı:\n\n{label} ({specifier or "Kapalı"})')
        def on_fail(err):
            self.lbl_dns_current.setText('DNS ayarlanamadı.')
            QMessageBox.warning(self, 'DNS Hatası', f'DNS ayarlanamadı:\n{err}')
        w = Worker(do)
        w.finished_ok.connect(on_ok)
        w.failed.connect(on_fail)
        self.window._run(w, desc=f'DNS Ayarlanıyor: {label}')

    def _apply_custom_dns(self):
        val = self.txt_custom_dns.text().strip()
        if not val:
            QMessageBox.warning(self, 'Eksik Bilgi', 'Lütfen geçerli bir DNS sunucu adresi girin (örn. dns.adguard-dns.com).')
            return
        self._set_dns_preset('hostname', val, f'Özel ({val})')

    def _run_diagnostics(self):
        if not self.core.connected or not self.core.target:
            QMessageBox.information(self, 'Bağlantı Yok', 'Ağ teşhisi yapmak için önce bir cihaza bağlanın.')
            return
        target = self.core.target
        engine = self.core.engine

        self.btn_run_diag.setEnabled(False)
        self.diag_progress.setRange(0, 0)
        self.diag_progress.show()
        self.lbl_diag_advice.setText('Ağ ve Wi-Fi parametreleri ölçülüyor (ping, RSSI, link speed)...')

        def do():
            return engine.network_diagnostics(target)

        def done(res):
            self.btn_run_diag.setEnabled(True)
            self.diag_progress.hide()

            # Signal
            sig_lbl = res.get('signal_label', '—')
            rssi = res.get('rssi') if res.get('rssi') is not None else res.get('rssi_dbm')
            self.lbl_wifi_signal.setText(sig_lbl)
            ssid = res.get('ssid', '')
            if ssid and ssid != '—':
                rssi_str = ' ({} dBm)'.format(rssi) if rssi is not None else ''
                self.lbl_wifi_signal_detail.setText('{}{}'.format(ssid, rssi_str))
            elif rssi is not None:
                self.lbl_wifi_signal_detail.setText('{} dBm'.format(rssi))
            else:
                self.lbl_wifi_signal_detail.setText('Sinyal bilgisi alındı')

            # Speed & Frequency
            spd = res.get('link_speed', '—')
            self.lbl_wifi_speed.setText(spd if spd else '—')
            freq = res.get('frequency', '')
            self.lbl_wifi_speed_detail.setText(freq if freq and freq != '—' else 'Wi-Fi bağlantısı')

            # Ping & Loss
            ping_ms = res.get('gateway_ping_ms')
            loss = res.get('packet_loss_pct', 0)
            if ping_ms is not None:
                self.lbl_gw_ping.setText('{} ms'.format(ping_ms))
                self.lbl_gw_ping_detail.setText('%{} paket kaybı'.format(loss))
            else:
                self.lbl_gw_ping.setText('—')
                self.lbl_gw_ping_detail.setText('%{} paket kaybı'.format(loss) if loss else 'Ping ölçülemedi')

            # IP & Interface
            ip = res.get('ip', '—')
            iface = res.get('interface', '')
            self.lbl_net_ip.setText(ip if ip else '—')
            if iface:
                iface_desc = 'Wi-Fi' if 'wlan' in iface.lower() else 'Ethernet' if 'eth' in iface.lower() else iface
                self.lbl_net_ip_detail.setText('{} ({})'.format(iface, iface_desc))
            else:
                self.lbl_net_ip_detail.setText('Ağ arabirimi')

            rating = res.get('health_rating', 'İyi')
            advice = res.get('advice', '')
            color = '#4caf50' if rating == 'Mükemmel' else '#ff9800' if 'Zayıf' in rating or 'Yüksek' in rating else '#f44336'
            self.lbl_diag_advice.setText('<b>Durum: <font color="{}">{}</font></b> — {}'.format(color, rating, advice))

        def fail(err):
            self.btn_run_diag.setEnabled(True)
            self.diag_progress.hide()
            self.lbl_diag_advice.setText('Teşhis tamamlanamadı: {}'.format(err))

        w = Worker(do)
        w.job_name = 'TV Ağ Teşhisi'
        w.finished_ok.connect(done)
        w.failed.connect(fail)
        self.window._run(w, desc='Ağ: TV WiFi ve bağlantı kalitesi test ediliyor')

    def _stop_scan(self):
        self._stop_flag = True
        if getattr(self, '_current_worker', None):
            try:
                self._current_worker.cancel()
            except Exception:
                pass
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        if self._found:
            self.lbl_summary.setText(f'⏹ Tarama durduruldu · {len(self._found)} cihaz bulundu.')
        else:
            self.lbl_summary.setText('⏹ Tarama durduruldu.')

    def scan(self):
        prefix = self.txt_subnet.text().strip()
        port = self.spn_port.value()
        start, end = self.spn_from.value(), self.spn_to.value()
        if not re.fullmatch(r'\d{1,3}(\.\d{1,3}){2}\.', prefix):
            QMessageBox.warning(self, 'Subnet', 'Subnet ön eki 3 nokta ile bitmeli.\nÖrnek: 192.168.1.')
            return
        try:
            ipaddress.IPv4Address(prefix + str(start))
            ipaddress.IPv4Address(prefix + str(end))
        except ipaddress.AddressValueError:
            QMessageBox.warning(self, 'Subnet', 'Ağ öneki geçerli IPv4 adresleri üretmelidir.')
            return
        if start > end:
            start, end = end, start

        # Arayüzü sıfırla ve yeni taramaya hazırla
        self._found = []
        self.grid.setRowCount(0)
        self.grid.setFixedHeight(175)
        kit.empty_state(self.grid, 'Ağ taranıyor...', 'Açık ADB portlu (5555) cihazlar aranıyor...')

        self.lbl_summary.setText(f'🔍 Taranıyor: {prefix}{start}-{end} :{port} ...')
        self.btn_scan.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress.setValue(0)
        self._stop_flag = False

        w = NetworkScanWorker(prefix, start, end, port)
        self._current_worker = w
        w.device_found.connect(self._on_device_found)
        w.progress.connect(self._update_scan_progress)
        w.finished_ok.connect(self._on_scan_finished)
        w.failed.connect(self._on_scan_failed)
        self.window._run(w, desc=f'Ağ: {prefix}{start}-{end} taranıyor')

    @Slot(str, str, str)
    def _on_device_found(self, ip, state, lat):
        """Her bir cihaz IP'si tespit edildiği anda tabloya anında eklenir."""
        if any(item[0] == ip for item in self._found):
            return
        self._found.append((ip, state, lat))

        r = self.grid.rowCount()
        self.grid.insertRow(r)

        item_ip = QTableWidgetItem(f'📺  {ip}')
        item_ip.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        item_ip.setData(Qt.UserRole, ip)

        item_state = QTableWidgetItem(f'🟢 {state}')
        item_state.setTextAlignment(Qt.AlignCenter)
        item_state.setForeground(QColor('#10b981'))

        item_lat = QTableWidgetItem(f'{lat} ms')
        item_lat.setTextAlignment(Qt.AlignCenter)

        self.grid.setItem(r, COL_IP, item_ip)
        self.grid.setItem(r, COL_STATE, item_state)
        self.grid.setItem(r, COL_LATENCY, item_lat)

        # Tablo yüksekliğini bulunan satır sayısına göre dinamik ve dengeli büyüt
        row_height = self.grid.verticalHeader().defaultSectionSize() or 34
        header_height = self.grid.horizontalHeader().height() or 30
        desired_height = header_height + (r + 1) * row_height + 10
        self.grid.setFixedHeight(min(260, max(175, desired_height)))

        # İlk bulunan cihazı otomatik seç, kullanıcı doğrudan Enter veya "Bağlan" butonu ile bağlanabilsin
        if r == 0:
            self.grid.selectRow(0)

        self.lbl_summary.setText(f'🎯 Cihaz bulundu: {ip} ({lat} ms)! "Bağlan" butonuna basarak bağlanabilirsiniz.')

    @Slot(int, int)
    def _update_scan_progress(self, completed, total):
        if total <= 0:
            return
        self.progress.setValue(min(100, int(completed * 100 / total)))
        found_cnt = len(self._found)
        if found_cnt > 0:
            self.lbl_summary.setText(
                f'Taranıyor: {completed} / {total} adres · 🎯 {found_cnt} cihaz bulundu')
        else:
            self.lbl_summary.setText(
                f'Taranıyor: {completed} / {total} adres...')

    def _on_scan_finished(self, found):
        self.progress.setValue(100)
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._current_worker = None
        count = len(self._found)
        if count > 0:
            self.lbl_summary.setText(
                f'✅ Tarama tamamlandı: {count} cihaz bulundu. Çift tıklayarak veya "Bağlan" butonuyla hemen bağlanabilirsiniz.')
        else:
            kit.empty_state(self.grid, 'Cihaz bulunamadı',
                            'Belirtilen aralıkta açık ADB portu (5555) olan cihaz bulunamadı.\nTV\'nizin açık, aynı Wi-Fi ağında ve ADB hata ayıklamanın aktif olduğundan emin olun.')
            self.lbl_summary.setText('0 cihaz bulundu (port açık değil veya cihaz çevrimdışı).')

    def _on_scan_failed(self, err):
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._current_worker = None
        if 'durdurdu' in str(err).lower():
            if self._found:
                self.lbl_summary.setText(f'⏹ Tarama durduruldu · {len(self._found)} cihaz bulundu.')
            else:
                self.lbl_summary.setText('⏹ Tarama kullanıcı tarafından durduruldu.')
        else:
            self.lbl_summary.setText(f'Tarama hatası: {err}')

    def _show_results(self, found):
        """Geriye dönük uyumluluk için toplu gösterim fonksiyonu."""
        self._found = []
        self.grid.setRowCount(0)
        for ip, state, lat in found:
            self._on_device_found(ip, state, lat)
        self._on_scan_finished(found)

    def _selected_ip(self):
        row = self.grid.currentRow()
        if row < 0:
            return None
        it = self.grid.item(row, COL_IP)
        if not it:
            return None
        stored = it.data(Qt.UserRole)
        if stored:
            return str(stored)
        return it.text().replace('📺', '').strip()

    def _use_selected(self):
        ip = self._selected_ip()
        if not ip:
            QMessageBox.information(self, 'Cihaz Seçin', 'Lütfen bağlanmak istediğiniz TV cihazını listeden seçin.')
            return
        self._set_target(ip + ':' + str(self.spn_port.value()))

    def _on_double_click(self, index):
        it = self.grid.item(index.row(), COL_IP)
        if it:
            ip = it.data(Qt.UserRole) or it.text().replace('📺', '').strip()
            self._set_target(ip + ':' + str(self.spn_port.value()))

    def _set_target(self, target):
        self._stop_scan()
        self.window._set_target_fields(target)
        self.window._sync_target()
        self.core.config.push_history(target)
        try:
            self.window.refresh_history_combo()
        except Exception:
            pass
        self.window.append_log('Hedef ayarlandi, baglaniliyor: ' + target, 'INFO')
        self.window.on_connect()

    def _pair(self):
        host, ok = QInputDialog.getText(self, 'Eşleştir', 'Eşleştirme adresi (IP:port):',
                                       text=self.txt_subnet.text().strip() + '1:XXXXX')
        if not ok or not host.strip():
            return
        code, ok2 = QInputDialog.getText(self, 'Eşleştir', 'Eşleştirme kodu (TVde yazar):')
        if not ok2 or not code.strip():
            return

        def do():
            return self.core.engine.pair(host.strip(), code.strip())
        w = Worker(do)
        w.job_name = 'Kablosuz eşleştirme'
        w.finished_ok.connect(lambda m: QMessageBox.information(self, 'Eşleştirme', m or 'Eşleştirme tamam.'))
        self.window._run(w, desc='Ag: kablosuz eşleştirme deneniyor')
