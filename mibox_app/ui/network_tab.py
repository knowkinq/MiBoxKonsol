# -*- coding: utf-8 -*-
"""Ag sekmesi: LAN'da ADB portu acik cihazlari tarar + eslestirme."""
import ipaddress
import re
import socket

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..workers import CancelledError, NetworkScanWorker, Worker
from . import kit
from .flowlayout import FlowLayout

COL_IP = 0
COL_STATE = 1
COL_LATENCY = 2


class _NetworkSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


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
        self._generation = 0
        self._dns_revision = 0
        self._dns_busy = False
        self._diag_worker = None
        self._pending_scan_target = None
        self._scan_workers = set()
        self._pair_worker = None
        self._pair_prompt = False
        self._build()
        for button in self.findChildren(QPushButton):
            if button.maximumHeight() <= 34:
                button.setProperty('compact', True)
        self.core.connection_changed.connect(self._on_connection_changed)
        self._sync_device_controls()

    def _build(self):
        root = kit.page(self)
        root.setSpacing(12)
        self._root_layout = root

        def card(title):
            frame = QFrame()
            frame.setObjectName('contentCard')
            frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(16, 14, 16, 14)
            layout.setSpacing(10)
            heading = QLabel(title)
            heading.setObjectName('networkCardTitle')
            heading.setStyleSheet('font-weight: 600; font-size: 15px;')
            heading.setWordWrap(True)
            heading.setMinimumWidth(0)
            layout.addWidget(heading)
            return frame, layout

        # 1. BİRLEŞİK KART: LAN Cihaz Keşfi ve Port Taraması
        self.scan_card, card_layout = card('🔍 LAN Cihaz Keşfi · Port Taraması')
        self.results_card = self.scan_card  # Geriye dönük uyumluluk referansı

        # Üst Bilgi Satırı
        hint_label = kit.hint_label(
            'Yerel Wi-Fi ağınızdaki açık ADB portlu (5555) Android TV / Mi Box cihazlarını otomatik arar ve listeler.')
        hint_label.setWordWrap(True)
        card_layout.addWidget(hint_label)

        # Keep labels and controls together on one row.
        ctrl_row = FlowLayout(hspacing=10, vspacing=8)
        ctrl_row.setContentsMargins(0, 4, 0, 4)
        ctrl_row.setSpacing(10)

        lbl_prefix = QLabel('Ağ Öneki:')
        lbl_prefix.setStyleSheet('font-weight: 600; font-size: 11.5px;')

        self.txt_subnet = QLineEdit(local_subnet_guess())
        self.txt_subnet.setPlaceholderText('192.168.1.')
        self.txt_subnet.setFixedWidth(150)
        self.txt_subnet.setFixedHeight(36)
        self.txt_subnet.setToolTip('Taranacak yerel ağ öneki (Örn: 192.168.1.)')

        lbl_range = QLabel('IP Aralığı:')
        lbl_range.setStyleSheet('font-weight: 600; font-size: 11.5px;')

        self.spn_from = _NetworkSpinBox()
        self.spn_from.setRange(1, 254)
        self.spn_from.setValue(1)
        self.spn_from.setPrefix('')
        self.spn_from.setFixedWidth(76)
        self.spn_from.setFixedHeight(36)
        self.spn_from.setToolTip('Başlangıç IP son hanesi')

        lbl_dash = QLabel('—')
        lbl_dash.setStyleSheet('color: #64748b; font-weight: bold;')

        self.spn_to = _NetworkSpinBox()
        self.spn_to.setRange(1, 254)
        self.spn_to.setValue(254)
        self.spn_to.setPrefix('')
        self.spn_to.setFixedWidth(76)
        self.spn_to.setFixedHeight(36)
        self.spn_to.setToolTip('Bitiş IP son hanesi')

        lbl_port = QLabel('Port:')
        lbl_port.setStyleSheet('font-weight: 600; font-size: 11.5px;')

        self.spn_port = _NetworkSpinBox()
        self.spn_port.setRange(1, 65535)
        self.spn_port.setValue(5555)
        self.spn_port.setFixedWidth(94)
        self.spn_port.setFixedHeight(36)
        self.spn_port.setToolTip('ADB bağlantı portu (Standart: 5555)')

        self.btn_scan = QPushButton('🔍 Ağda Ara')
        self.btn_scan.setProperty('primary', True)
        self.btn_scan.setFixedHeight(36)
        self.btn_scan.setMinimumWidth(116)
        self.btn_scan.setStyleSheet('font-weight: bold; background: #6366f1; color: white;')
        self.btn_scan.clicked.connect(self.scan)
        self.btn_scan.setToolTip('Belirtilen aralıkta açık ADB portlu TV cihazlarını ara')

        self.btn_stop = QPushButton('⏹ Durdur')
        self.btn_stop.setProperty('role', 'danger')
        self.btn_stop.setFixedHeight(36)
        self.btn_stop.setMinimumWidth(96)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_scan)
        self.btn_stop.setToolTip('Devam eden ağ taramasını durdur')

        range_row = QHBoxLayout()
        range_row.setSpacing(8)
        range_row.addWidget(self.spn_from)
        range_row.addWidget(lbl_dash)
        range_row.addWidget(self.spn_to)
        scan_actions = QHBoxLayout()
        scan_actions.setSpacing(10)
        scan_actions.addWidget(self.btn_scan)
        scan_actions.addWidget(self.btn_stop)
        for label, control in ((lbl_prefix, self.txt_subnet),
                               (lbl_range, range_row), (lbl_port, self.spn_port),
                               (None, scan_actions)):
            group = QWidget()
            group.setObjectName('networkControlGroup')
            group.setStyleSheet('QWidget#networkControlGroup, QWidget#networkControlGroup QLabel { background: transparent; }')
            group_layout = QHBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(8)
            if label is not None:
                group_layout.addWidget(label)
            if isinstance(control, QWidget):
                group_layout.addWidget(control)
            else:
                group_layout.addLayout(control)
            ctrl_row.addWidget(group)

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
        self.grid.setFixedHeight(120)
        kit.empty_state(self.grid, 'Ağdaki TV\'leri Keşfedin',
                        'Yukarıdaki "Ağda Ara" butonuna basarak ağınızdaki cihazları otomatik bulun.')
        self.grid.horizontalHeader().setSectionResizeMode(COL_IP, QHeaderView.Stretch)
        self.grid.horizontalHeader().setSectionResizeMode(COL_STATE, QHeaderView.ResizeToContents)
        self.grid.horizontalHeader().setSectionResizeMode(COL_LATENCY, QHeaderView.ResizeToContents)
        self.grid.doubleClicked.connect(self._on_double_click)
        self.grid.itemSelectionChanged.connect(self._sync_device_controls)
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
        self.btn_pair.setFixedHeight(36)
        self.btn_pair.setToolTip('Android 11+ Kablosuz Eşleştirme (6 haneli kod)')
        self.btn_pair.clicked.connect(self._pair)

        self.btn_connect = QPushButton('🔗 Bağlan')
        self.btn_connect.setProperty('accent', True)
        self.btn_connect.setFixedHeight(36)
        self.btn_connect.setMinimumWidth(110)
        self.btn_connect.setStyleSheet('font-weight: bold; padding: 0 16px;')
        self.btn_connect.setToolTip('Seçili TV cihazına hemen bağlan')
        self.btn_connect.clicked.connect(self._use_selected)
        self.btn_use = self.btn_connect  # Geriye dönük uyumluluk referansı

        actions.addWidget(self.lbl_summary, 1)
        self.btn_copy_address = QPushButton('Adresi kopyala')
        self.btn_copy_address.clicked.connect(self._copy_selected_address)
        actions.addWidget(self.btn_copy_address)
        actions.addWidget(self.btn_pair)
        actions.addWidget(self.btn_connect)
        card_layout.addLayout(actions)

        root.addWidget(self.scan_card)

        # TV Network & WiFi Diagnostics Card (Sol Kart)
        diag_card, diag_layout = card('📶 Canlı TV WiFi · Ağ Sağlığı Teşhisi')

        diag_header = QHBoxLayout()
        self.btn_run_diag = QPushButton('🔍 Test Et')
        self.btn_run_diag.setToolTip('Bağlı Mi Box TV Wi-Fi sinyal kalitesini, modem pingini ve hızını test eder.')
        self.btn_run_diag.setProperty('accent', True)
        self.btn_run_diag.setFixedHeight(36)
        self.btn_run_diag.clicked.connect(self._run_diagnostics)
        diag_header.addWidget(diag_layout.takeAt(0).widget(), 1)
        diag_header.setSpacing(12)
        diag_header.addWidget(self.btn_run_diag)
        diag_layout.addLayout(diag_header)

        metrics_grid = QGridLayout()
        metrics_grid.setSpacing(10)

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
            m_lay.setContentsMargins(12, 8, 12, 8)
            m_lay.setSpacing(4)

            m_title = QLabel(title)
            m_title.setObjectName('metricLabel')
            m_title.setProperty('role', 'quiet')

            m_val = QLabel('—')
            m_val.setTextFormat(Qt.PlainText)
            m_val.setWordWrap(True)
            m_val.setStyleSheet('font-size: 20px; font-weight: 600;')
            m_val.setProperty('role', 'primary')
            setattr(self, val_attr, m_val)

            m_detail = QLabel('Ölçüm bekleniyor')
            m_detail.setTextFormat(Qt.PlainText)
            m_detail.setProperty('role', 'quiet')
            m_detail.setStyleSheet('font-size: 12px;')
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
        self.lbl_diag_advice.setTextFormat(Qt.PlainText)
        self.lbl_diag_advice.setProperty('role', 'quiet')
        diag_layout.addWidget(self.lbl_diag_advice)
        diag_layout.addStretch(1)

        # DNS & Reklam Engelleyici Kartı (Sağ Kart)
        dns_card, dns_layout = card('🛡️ Özel DNS · Reklam Engelleme')

        dns_header = QHBoxLayout()
        self.btn_refresh_dns = QPushButton('🔄 DNS Oku')
        self.btn_refresh_dns.setFixedHeight(36)
        self.btn_refresh_dns.setProperty('role', 'secondary')
        self.btn_refresh_dns.clicked.connect(self._fetch_dns_status)
        dns_header.addWidget(dns_layout.takeAt(0).widget(), 1)
        dns_header.setSpacing(12)
        dns_header.addWidget(self.btn_refresh_dns)
        dns_layout.addLayout(dns_header)

        dns_desc = QLabel('TV için reklam engelleme veya hızlı/güvenli DNS seçin:')
        dns_desc.setProperty('role', 'quiet')
        dns_desc.setWordWrap(True)
        dns_layout.addWidget(dns_desc)

        # Preset Butonları (2x2 Dengeli Izgara)
        presets_grid = QGridLayout()
        presets_grid.setSpacing(10)

        self.btn_dns_adguard = QPushButton('🛡️ AdGuard')
        self.btn_dns_adguard.setFixedHeight(38)
        self.btn_dns_adguard.setProperty('primary', True)
        self.btn_dns_adguard.setToolTip('AdGuard DNS: Reklam ve takipçileri engeller')
        self.btn_dns_adguard.clicked.connect(lambda: self._set_dns_preset('hostname', 'dns.adguard-dns.com', 'AdGuard DNS'))

        self.btn_dns_cloudflare = QPushButton('⚡ Cloudflare')
        self.btn_dns_cloudflare.setFixedHeight(38)
        self.btn_dns_cloudflare.setProperty('role', 'secondary')
        self.btn_dns_cloudflare.setToolTip('Cloudflare 1.1.1.1: Hızlı ve güvenli DNS')
        self.btn_dns_cloudflare.clicked.connect(lambda: self._set_dns_preset('hostname', '1dot1dot1dot1.cloudflare-dns.com', 'Cloudflare DNS'))

        self.btn_dns_google = QPushButton('🔍 Google DNS')
        self.btn_dns_google.setFixedHeight(38)
        self.btn_dns_google.setProperty('role', 'secondary')
        self.btn_dns_google.setToolTip('Google DNS: dns.google')
        self.btn_dns_google.clicked.connect(lambda: self._set_dns_preset('hostname', 'dns.google', 'Google DNS'))

        self.btn_dns_off = QPushButton('❌ Kapat')
        self.btn_dns_off.setFixedHeight(38)
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
        custom_row.setSpacing(10)
        self.txt_custom_dns = QLineEdit()
        self.txt_custom_dns.setPlaceholderText('Özel DNS (örn. dns.nextdns.io)...')
        self.txt_custom_dns.setFixedHeight(36)

        self.btn_apply_custom_dns = QPushButton('Uygula')
        self.btn_apply_custom_dns.setFixedHeight(36)
        self.btn_apply_custom_dns.clicked.connect(self._apply_custom_dns)

        custom_row.addWidget(QLabel('Özel:'))
        custom_row.addWidget(self.txt_custom_dns, 1)
        custom_row.addWidget(self.btn_apply_custom_dns)
        dns_layout.addLayout(custom_row)

        self.lbl_dns_current = QLabel('Mevcut DNS: Ölçüm bekleniyor (Cihaza bağlanın)')
        self.lbl_dns_current.setWordWrap(True)
        self.lbl_dns_current.setTextFormat(Qt.PlainText)
        self.lbl_dns_current.setMinimumWidth(0)
        self.lbl_dns_current.setStyleSheet('font-size: 11px; font-weight: bold; color: #94a3b8;')
        dns_layout.addWidget(self.lbl_dns_current)
        dns_layout.addStretch(1)

        # Alt Bölüm: WiFi Teşhisi ve Özel DNS Yan Yana (Kullanıcı İsteği)
        side_layout = QHBoxLayout()
        self._side_layout = side_layout
        side_layout.setSpacing(12)
        side_layout.addWidget(diag_card, 1)
        side_layout.addWidget(dns_card, 1)
        root.addLayout(side_layout)
        root.addStretch(1)
        self._stop_flag = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_side_layout'):
            direction = (QBoxLayout.TopToBottom if self.width() < 900
                         else QBoxLayout.LeftToRight)
            self._side_layout.setDirection(direction)

    def apply_theme(self):
        palette = kit.colors(self)
        for row in range(self.grid.rowCount()):
            status = self.grid.item(row, COL_STATE)
            if status is not None:
                status.setForeground(QColor(palette['success']))
        self.lbl_dns_current.setStyleSheet(
            'font-size: 11px; font-weight: 600; color: {};'.format(palette['muted']))

    def _device_ready(self):
        return (bool(getattr(self.core, 'connected', False))
                and bool(getattr(self.core, 'target', None))
                and not getattr(self.window, '_connection_busy', False))

    def _sync_device_controls(self):
        if not hasattr(self, 'btn_apply_custom_dns'):
            return
        ready = self._device_ready()
        for button in (self.btn_refresh_dns, self.btn_dns_adguard,
                       self.btn_dns_cloudflare, self.btn_dns_google,
                       self.btn_dns_off, self.btn_apply_custom_dns):
            button.setEnabled(ready and not self._dns_busy)
        self.txt_custom_dns.setEnabled(ready and not self._dns_busy)
        self.btn_run_diag.setEnabled(ready and self._diag_worker is None)
        selected = bool(self._selected_ip())
        self.btn_connect.setEnabled(selected and not getattr(self.window, '_connection_busy', False))
        self.btn_copy_address.setEnabled(selected)
        self.btn_pair.setEnabled(self._pair_worker is None and not self._pair_prompt
                                 and not getattr(self.window, '_connection_busy', False))

    def _copy_selected_address(self):
        ip = self._selected_ip()
        if not ip:
            return
        item = self.grid.item(self.grid.currentRow(), COL_IP)
        port = item.data(Qt.UserRole + 1) if item else None
        address = '{}:{}'.format(ip, port or self.spn_port.value())
        QApplication.clipboard().setText(address)
        self.lbl_summary.setText('Seçili cihaz adresi kopyalandı: ' + address)

    def _on_connection_changed(self, connected=False, target=None):
        self._generation += 1
        for label in (self.lbl_wifi_signal, self.lbl_wifi_speed, self.lbl_gw_ping, self.lbl_net_ip):
            label.setText('—')
        for label in (self.lbl_wifi_signal_detail, self.lbl_wifi_speed_detail,
                      self.lbl_gw_ping_detail, self.lbl_net_ip_detail):
            label.setText('Ölçüm bekleniyor')
        self.lbl_diag_advice.setText('Mevcut cihazın ağ durumunu ölçmek için Test Et’i seçin.')
        self._sync_device_controls()
        if self._device_ready():
            self._fetch_dns_status()
        elif connected:
            self.lbl_dns_current.setText('Mevcut DNS: Bağlantının tamamlanması bekleniyor')
        else:
            self.lbl_dns_current.setText('Mevcut DNS: Cihaz bağlı değil')

    def _fetch_dns_status(self):
        if not self._device_ready():
            self.lbl_dns_current.setText('Mevcut DNS: Bağlantı hazır değil')
            return
        target = self.core.target
        generation = self._generation
        self._dns_revision += 1
        revision = self._dns_revision
        current = lambda: (self.core.connected and self.core.target == target
                           and self._generation == generation and self._dns_revision == revision
                           and self._device_ready())
        self.lbl_dns_current.setText('Mevcut DNS: Okunuyor…')
        def do():
            if not current():
                raise CancelledError('Bağlantı değişti.')
            return self.core.engine.private_dns_get(target)
        def on_ok(res):
            if not current():
                return
            mode = res.get('mode')
            spec = res.get('specifier', '')
            if mode == 'hostname' and spec:
                self.lbl_dns_current.setText(f'Mevcut DNS: Sunucu kayıtlı: {spec}')
            elif mode == 'opportunistic':
                self.lbl_dns_current.setText('Mevcut DNS: Otomatik (Fırsatçı)')
            elif mode == 'off':
                self.lbl_dns_current.setText('Mevcut DNS: Kapalı (İSS / Modem Varsayılanı)')
            else:
                self.lbl_dns_current.setText('Mevcut DNS: Ayar tam okunamadı; DNS Oku ile yeniden deneyin.')
        w = Worker(do)
        w.finished_ok.connect(on_ok)
        w.failed.connect(lambda error: self.lbl_dns_current.setText('DNS okunamadı: ' + str(error))
                         if current() else None)
        self.window._run(w)

    def _set_dns_preset(self, mode, specifier, label):
        if self._dns_busy:
            return
        if not self._device_ready():
            QMessageBox.information(self, 'Bağlantı Yok', 'DNS ayarlamak için önce bir TV cihazına bağlanın.')
            return
        target = self.core.target
        generation = self._generation
        self._dns_revision += 1
        current = lambda: (self.core.connected and self.core.target == target
                           and self._generation == generation and self._device_ready())
        self._dns_busy = True
        self._sync_device_controls()
        self.lbl_dns_current.setText(f'DNS ayarlanıyor: {label}...')
        def do():
            if not current():
                raise CancelledError('Bağlantı değişti.')
            return self.core.engine.private_dns_set(target, mode, specifier)
        def on_ok(res):
            if not current():
                return
            if hasattr(self.window, 'append_log'):
                self.window.append_log(f'Özel DNS güncellendi: mode={mode}, specifier={specifier}', 'INFO')
            self._fetch_dns_status()
            QMessageBox.information(self, 'DNS Güncellendi', f'TV Özel DNS başarıyla ayarlandı:\n\n{label} ({specifier or "Kapalı"})')
        def on_fail(err):
            if not current():
                return
            self.lbl_dns_current.setText('DNS ayarlanamadı.')
            QMessageBox.warning(self, 'DNS Hatası', f'DNS ayarlanamadı:\n{err}')
        w = Worker(do)
        w.finished_ok.connect(on_ok)
        w.failed.connect(on_fail)
        def cleanup():
            self._dns_busy = False
            self._sync_device_controls()
        w.finished.connect(cleanup)
        try:
            self.window._run(w, desc=f'DNS Ayarlanıyor: {label}')
        except Exception:
            cleanup()
            raise

    def _apply_custom_dns(self):
        val = self.txt_custom_dns.text().strip()
        if not val:
            QMessageBox.warning(self, 'Eksik Bilgi', 'Lütfen geçerli bir DNS sunucu adresi girin (örn. dns.adguard-dns.com).')
            return
        self._set_dns_preset('hostname', val, f'Özel ({val})')

    def _run_diagnostics(self):
        if self._diag_worker is not None:
            return
        if not self._device_ready():
            QMessageBox.information(self, 'Bağlantı Yok', 'Ağ teşhisi yapmak için önce bir cihaza bağlanın.')
            return
        target = self.core.target
        engine = self.core.engine
        generation = self._generation
        current = lambda: (self.core.connected and self.core.target == target
                           and self._generation == generation and self._device_ready())

        self.btn_run_diag.setEnabled(False)
        self.diag_progress.setRange(0, 0)
        self.diag_progress.show()
        self.lbl_diag_advice.setText('Ağ ve Wi-Fi parametreleri ölçülüyor (ping, RSSI, link speed)...')

        def do():
            if not current():
                raise CancelledError('Bağlantı değişti.')
            return engine.network_diagnostics(target)

        def done(res):
            if not current():
                return
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

            rating = res.get('health_rating') or 'Ölçüm eksik'
            advice = res.get('advice', '')
            self.lbl_diag_advice.setText('Durum: {} — {}'.format(rating, advice))

        def fail(err):
            if not current():
                return
            self.btn_run_diag.setEnabled(True)
            self.diag_progress.hide()
            self.lbl_diag_advice.setText('Teşhis tamamlanamadı: {}'.format(err))

        w = Worker(do)
        self._diag_worker = w
        w.job_name = 'TV Ağ Teşhisi'
        w.finished_ok.connect(done)
        w.failed.connect(fail)
        def cleanup():
            if self._diag_worker is w:
                self._diag_worker = None
                self._sync_device_controls()
                self.diag_progress.hide()
        w.finished.connect(cleanup)
        try:
            self.window._run(w, desc='Ağ: TV WiFi ve bağlantı kalitesi test ediliyor')
        except Exception:
            cleanup()
            raise

    def _stop_scan(self):
        self._stop_flag = True
        if getattr(self, '_current_worker', None):
            try:
                self._current_worker.cancel()
            except Exception:
                pass
        self.btn_scan.setEnabled(self._current_worker is None)
        self.btn_stop.setEnabled(False)
        if self._found:
            self.lbl_summary.setText(f'⏹ Tarama durduruldu · {len(self._found)} cihaz bulundu.')
        else:
            self.lbl_summary.setText('⏹ Tarama durduruldu.')
            kit.empty_state(self.grid, 'Tarama durduruldu',
                            'Aramayı yeniden başlatmak için taramanın bitmesini bekleyin.')

    def scan(self):
        if (self._current_worker is not None
                or getattr(self.window, '_closing', False)
                or getattr(self.window, '_close_pending', False)):
            return
        self._pending_scan_target = None
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
        self._scan_port = port

        # Arayüzü sıfırla ve yeni taramaya hazırla
        self._found = []
        self.grid.setRowCount(0)
        self.grid.setFixedHeight(120)
        kit.empty_state(self.grid, 'Ağ taranıyor...',
                        '{} portu açık olan cihazlar aranıyor...'.format(port))

        self.lbl_summary.setText(f'🔍 Taranıyor: {prefix}{start}-{end} :{port} ...')
        self.btn_scan.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress.setValue(0)
        self._stop_flag = False

        w = NetworkScanWorker(prefix, start, end, port)
        self._scan_workers.add(w)
        self._current_worker = w
        active = lambda: self._current_worker is w and not self._stop_flag
        w.device_found.connect(lambda ip, state, latency:
                               self._on_device_found(ip, state, latency) if active() else None)
        w.progress.connect(lambda completed, total:
                           self._update_scan_progress(completed, total) if active() else None)
        results, errors = [], []
        w.finished_ok.connect(results.append)
        w.failed.connect(errors.append)

        def cleanup():
            self._scan_workers.discard(w)
            if self._current_worker is w:
                stopped = self._stop_flag
                self._current_worker = None
                self.btn_scan.setEnabled(True)
                self.btn_stop.setEnabled(False)
                if (not stopped and not getattr(self.window, '_closing', False)
                        and not getattr(self.window, '_close_pending', False)):
                    if results:
                        self._on_scan_finished(results[0])
                    else:
                        self._on_scan_failed(errors[-1] if errors else 'Tarama tamamlanamadı.')
            QTimer.singleShot(0, self._connect_scan_target)

        w.finished.connect(cleanup)
        try:
            self.window._run(w, desc=f'Ağ: {prefix}{start}-{end} taranıyor')
        except Exception as error:
            errors.append(str(error))
            cleanup()

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
        item_ip.setData(Qt.UserRole + 1, getattr(self, '_scan_port', self.spn_port.value()))

        item_state = QTableWidgetItem(f'● {state}')
        item_state.setTextAlignment(Qt.AlignCenter)
        item_state.setForeground(QColor(kit.colors(self)['success']))

        item_lat = QTableWidgetItem(f'{lat} ms')
        item_lat.setTextAlignment(Qt.AlignCenter)

        self.grid.setItem(r, COL_IP, item_ip)
        self.grid.setItem(r, COL_STATE, item_state)
        self.grid.setItem(r, COL_LATENCY, item_lat)

        # Tablo yüksekliğini bulunan satır sayısına göre dinamik ve dengeli büyüt
        row_height = self.grid.verticalHeader().defaultSectionSize() or 34
        header_height = self.grid.horizontalHeader().height() or 30
        desired_height = header_height + (r + 1) * row_height + 10
        self.grid.setFixedHeight(min(200, max(120, desired_height)))

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
                            'Belirtilen aralıkta açık ADB portu ({}) olan cihaz bulunamadı.\nTV\'nizin açık, aynı ağda ve ADB hata ayıklamanın etkin olduğundan emin olun.'.format(
                                getattr(self, '_scan_port', self.spn_port.value())))
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
                kit.empty_state(self.grid, 'Tarama durduruldu',
                                'Aramayı yeniden başlatmak için Ağda Ara düğmesine basın.')
        else:
            self.lbl_summary.setText(f'Tarama hatası: {err}')
            if not self._found:
                kit.empty_state(self.grid, 'Tarama tamamlanamadı',
                                'Ağ bağlantınızı ve adres aralığını kontrol edip yeniden deneyin.')

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
        item = self.grid.item(self.grid.currentRow(), COL_IP)
        port = item.data(Qt.UserRole + 1) if item else None
        self._set_target(ip + ':' + str(port or self.spn_port.value()))

    def _on_double_click(self, index):
        it = self.grid.item(index.row(), COL_IP)
        if it:
            ip = it.data(Qt.UserRole) or it.text().replace('📺', '').strip()
            self._set_target(ip + ':' + str(it.data(Qt.UserRole + 1) or self.spn_port.value()))

    def _set_target(self, target):
        if getattr(self.window, '_connection_busy', False):
            self.lbl_summary.setText('Bağlantı işlemi sürüyor; tamamlanınca cihazı yeniden seçin.')
            return
        self._stop_scan()
        self._pending_scan_target = target
        QTimer.singleShot(0, self._connect_scan_target)

    def _connect_scan_target(self):
        target = self._pending_scan_target
        if not target:
            return
        if getattr(self.window, '_closing', False) or getattr(self.window, '_close_pending', False):
            self._pending_scan_target = None
            return
        if self._scan_workers:
            return
        if (getattr(self.window, '_connection_busy', False)
                or getattr(self.window, '_workers', ())):
            self._pending_scan_target = None
            self.lbl_summary.setText('Devam eden işlem var; tamamlanınca cihazı yeniden seçin.')
            return
        self._pending_scan_target = None
        self.window._set_target_fields(target)
        self.window.append_log('Seçili ağ cihazına bağlantı başlatılıyor.', 'INFO')
        self.window.on_connect()

    def _pair(self):
        if (self._pair_worker is not None or self._pair_prompt
                or getattr(self.window, '_connection_busy', False)
                or getattr(self.window, '_closing', False)
                or getattr(self.window, '_close_pending', False)):
            return
        self._pair_prompt = True
        self._sync_device_controls()
        try:
            host, ok = QInputDialog.getText(
                self, 'Kablosuz eşleştirme',
                'TV’deki eşleştirme adresi (IP:port). Bu port bağlantı portundan farklı olabilir:',
                text=self.txt_subnet.text().strip() + '1:')
            if not ok or not host.strip():
                return
            code, ok = QInputDialog.getText(
                self, 'Kablosuz eşleştirme', 'TV’de gösterilen 6 haneli eşleştirme kodu:',
                QLineEdit.Password)
            if not ok:
                return
            host, code = host.strip(), code.strip()
            if not re.fullmatch(r'[0-9]{6}', code):
                QMessageBox.warning(self, 'Eşleştirme', 'Eşleştirme kodu 6 rakam olmalıdır.')
                return
            if (getattr(self.window, '_connection_busy', False)
                    or getattr(self.window, '_closing', False)
                    or getattr(self.window, '_close_pending', False)):
                self.lbl_summary.setText('İşlem durumu değişti; eşleştirme başlatılmadı.')
                return
            engine = self.core.engine

            def do():
                w.check_cancel()
                return engine.pair(host, code)

            w = Worker(do)
            w.job_name = 'Kablosuz eşleştirme'
            results, errors = [], []
            w.finished_ok.connect(results.append)
            w.failed.connect(errors.append)
            self._pair_worker = w
            self.lbl_summary.setText('Kablosuz eşleştirme bekleniyor…')

            def finished():
                if self._pair_worker is not w:
                    return
                self._pair_worker = None
                self._sync_device_controls()
                if (getattr(self.window, '_closing', False)
                        or getattr(self.window, '_close_pending', False)):
                    return
                if results:
                    self.lbl_summary.setText('Eşleştirme tamamlandı. TV’deki bağlantı portuyla bağlanın.')
                    QMessageBox.information(
                        self, 'Eşleştirme tamamlandı',
                        'TV eşleştirildi. Bağlanmak için TV’deki kablosuz hata ayıklama '
                        'ekranının bağlantı adresini kullanın; eşleştirme portu farklı olabilir.')
                else:
                    self.lbl_summary.setText('Eşleştirme tamamlanamadı: ' +
                                             str(errors[-1] if errors else 'Sonuç alınamadı.'))

            w.finished.connect(finished)
            try:
                self.window._run(w, desc='Ağ: kablosuz eşleştirme')
            except Exception as error:
                errors.append(str(error))
                finished()
        except Exception as error:
            self.lbl_summary.setText('Eşleştirme başlatılamadı: ' + str(error))
        finally:
            self._pair_prompt = False
            self._sync_device_controls()
