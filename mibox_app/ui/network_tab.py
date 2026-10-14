# -*- coding: utf-8 -*-
"""Ag sekmesi: LAN'da ADB portu acik cihazlari tarar + eslestirme."""
import concurrent.futures
import re
import socket
import time

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QLineEdit,
    QSpinBox, QMessageBox, QInputDialog, QProgressBar, QSizePolicy, QFrame,
)

from ..workers import Worker
from . import kit

COL_IP = 0
COL_STATE = 1
COL_LATENCY = 2


def local_subnet_guess():
    """Yerel IP'den /24 on eki tahmin eder (orn: 192.168.1.)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
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
        self._build()

    def _build(self):
        root = kit.page(self)
        root.setSpacing(8)
        self._root_layout = root

        self.scan_card = QGroupBox()
        self.scan_card.setObjectName('compactCard')
        self.scan_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        scan_layout = QVBoxLayout(self.scan_card)
        scan_layout.setContentsMargins(12, 8, 12, 8)
        scan_layout.setSpacing(5)
        self.scan_header = QWidget(self.scan_card)
        self.scan_header.setObjectName('networkScanHeader')
        header_row = QHBoxLayout(self.scan_header)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(10)
        self.lbl_scan_title = QLabel('LAN taraması')
        self.lbl_scan_title.setObjectName('cardTitle')
        self.lbl_scan_hint = kit.hint_label(
            'Ağ önekini ve adres aralığını seçerek açık ADB portlarını bulun.')
        self.lbl_scan_hint.setWordWrap(True)
        header_row.addWidget(self.lbl_scan_title)
        header_row.addWidget(self.lbl_scan_hint, 1)
        scan_layout.addWidget(self.scan_header)

        network_row = QHBoxLayout()
        network_row.setSpacing(8)
        self.txt_subnet = QLineEdit(local_subnet_guess())
        self.txt_subnet.setPlaceholderText('Örnek: 192.168.1.')
        self.spn_port = QSpinBox()
        self.spn_port.setRange(1, 65535)
        self.spn_port.setValue(5555)
        self.spn_port.setPrefix('Port: ')
        self.spn_port.setMaximumWidth(132)
        self.spn_port.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        network_row.addWidget(QLabel('Ağ öneki'))
        network_row.addWidget(self.txt_subnet, 1)
        network_row.addWidget(self.spn_port)
        scan_layout.addLayout(network_row)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.addWidget(QLabel('Adres aralığı'))
        self.spn_from = QSpinBox()
        self.spn_from.setRange(1, 254)
        self.spn_from.setValue(1)
        self.spn_from.setPrefix('İlk: ')
        self.spn_from.setMinimumWidth(92)
        self.spn_from.setMaximumWidth(118)
        self.spn_to = QSpinBox()
        self.spn_to.setRange(1, 254)
        self.spn_to.setValue(254)
        self.spn_to.setPrefix('Son: ')
        self.spn_to.setMinimumWidth(92)
        self.spn_to.setMaximumWidth(118)
        self.btn_scan = QPushButton('Tara')
        self.btn_scan.setProperty('role', 'primary')
        self.btn_scan.clicked.connect(self.scan)
        self.btn_stop = QPushButton('Durdur')
        self.btn_stop.setProperty('role', 'secondary')
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_scan)
        toolbar.addWidget(self.spn_from)
        toolbar.addWidget(self.spn_to)
        toolbar.addStretch(1)
        toolbar.addWidget(self.btn_scan)
        toolbar.addWidget(self.btn_stop)
        scan_layout.addLayout(toolbar)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMaximumHeight(12)
        scan_layout.addWidget(self.progress)
        root.addWidget(self.scan_card)

        results_card = QGroupBox()
        results_card.setObjectName('compactCard')
        results_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.results_card = results_card
        results_layout = QVBoxLayout(results_card)
        results_layout.setSpacing(8)
        results_title = QLabel('Bulunan cihazlar')
        results_title.setObjectName('cardTitle')
        results_layout.addWidget(results_title)
        self.grid = kit.single_table(3, ['IP', 'Durum', 'Gecikme (ms)'])
        self.grid.setFixedHeight(130)
        kit.empty_state(self.grid, 'Ağdaki cihazları keşfedin',
                        'Adres aralığını seçin ve Tara düğmesine basın.')
        self.grid.horizontalHeader().setSectionResizeMode(COL_IP, QHeaderView.Stretch)
        self.grid.horizontalHeader().setSectionResizeMode(COL_STATE, QHeaderView.ResizeToContents)
        self.grid.horizontalHeader().setSectionResizeMode(COL_LATENCY, QHeaderView.ResizeToContents)
        self.grid.doubleClicked.connect(self._on_double_click)
        results_layout.addWidget(self.grid, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.lbl_summary = kit.status_label(
            'Sonuçları çift tıklayarak veya seçip hedef yaparak bağlanın.')
        self.lbl_summary.setWordWrap(True)
        actions.addWidget(self.lbl_summary, 1)
        self.btn_pair = QPushButton('Kablosuz Eşleştir')
        self.btn_pair.setProperty('role', 'secondary')
        self.btn_pair.clicked.connect(self._pair)
        self.btn_use = QPushButton('Seçiliyi Hedef Yap')
        self.btn_use.setProperty('role', 'primary')
        self.btn_use.clicked.connect(self._use_selected)
        actions.addWidget(self.btn_pair)
        actions.addWidget(self.btn_use)
        results_layout.addLayout(actions)
        root.addWidget(results_card)

        # TV Network & WiFi Diagnostics Card
        diag_card = QGroupBox('Canlı TV WiFi & Ağ Sağlığı Teşhisi')
        diag_card.setObjectName('compactCard')
        diag_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        diag_layout = QVBoxLayout(diag_card)
        diag_layout.setContentsMargins(12, 10, 12, 10)
        diag_layout.setSpacing(6)

        diag_header = QHBoxLayout()
        diag_title = QLabel('Bağlı Cihaz Ağ Analizi')
        diag_title.setObjectName('cardTitle')
        self.btn_run_diag = QPushButton('🔍 Ağı Test Et')
        self.btn_run_diag.setToolTip('Bağlı Mi Box TV Wi-Fi sinyal kalitesini, modem pingini ve hızını test eder.')
        self.btn_run_diag.setProperty('accent', True)
        self.btn_run_diag.clicked.connect(self._run_diagnostics)
        diag_header.addWidget(diag_title)
        diag_header.addStretch(1)
        diag_header.addWidget(self.btn_run_diag)
        diag_layout.addLayout(diag_header)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(8)

        card_defs = [
            ('Wi-Fi Sinyali', 'lbl_wifi_signal', 'lbl_wifi_signal_detail'),
            ('Bağlantı Hızı', 'lbl_wifi_speed', 'lbl_wifi_speed_detail'),
            ('Modem Gecikmesi', 'lbl_gw_ping', 'lbl_gw_ping_detail'),
            ('TV Yerel IP', 'lbl_net_ip', 'lbl_net_ip_detail'),
        ]
        for title, val_attr, detail_attr in card_defs:
            m_box = QFrame()
            m_box.setObjectName('metricCard')
            m_box.setProperty('role', 'secondary')
            m_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            m_lay = QVBoxLayout(m_box)
            m_lay.setContentsMargins(10, 8, 10, 8)
            m_lay.setSpacing(3)

            m_title = QLabel(title)
            m_title.setObjectName('metricLabel')
            m_title.setProperty('role', 'quiet')

            m_val = QLabel('—')
            m_val.setStyleSheet('font-size: 15px; font-weight: 600;')
            m_val.setProperty('role', 'primary')
            setattr(self, val_attr, m_val)

            m_detail = QLabel('Ölçüm bekleniyor')
            m_detail.setProperty('role', 'quiet')
            m_detail.setStyleSheet('font-size: 11px;')
            m_detail.setWordWrap(True)
            setattr(self, detail_attr, m_detail)

            m_lay.addWidget(m_title)
            m_lay.addWidget(m_val)
            m_lay.addWidget(m_detail)
            metrics_row.addWidget(m_box, 1)

        diag_layout.addLayout(metrics_row)

        self.diag_progress = QProgressBar()
        self.diag_progress.setRange(0, 100)
        self.diag_progress.setValue(0)
        self.diag_progress.setMaximumHeight(8)
        self.diag_progress.setTextVisible(False)
        self.diag_progress.hide()
        diag_layout.addWidget(self.diag_progress)

        self.lbl_diag_advice = QLabel('Bağlı Mi Box TV’nin Wi-Fi sinyal kalitesini, modem pingini ve paket kaybını test edin.')
        self.lbl_diag_advice.setWordWrap(True)
        self.lbl_diag_advice.setProperty('role', 'quiet')
        diag_layout.addWidget(self.lbl_diag_advice)

        root.addWidget(diag_card)
        root.addStretch(1)
        self._stop_flag = False

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
            rssi = res.get('rssi_dbm')
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
        self.lbl_summary.setText('Durduruluyor...')

    def scan(self):
        prefix = self.txt_subnet.text().strip()
        port = self.spn_port.value()
        start, end = self.spn_from.value(), self.spn_to.value()
        if not re.match(r'^\d{1,3}(\.\d{1,3}){2}\.$', prefix):
            QMessageBox.warning(self, 'Subnet', 'Subnet on eki 3 nokta ile bitmeli.\nOrnek: 192.168.1.')
            return
        if start > end:
            start, end = end, start
        self.lbl_summary.setText('Taraniyor: {}{}-{} :{} ...'.format(prefix, start, end, port))
        self.btn_scan.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress.setValue(0)
        self._stop_flag = False
        worker_ref = {'worker': None}
        total = end - start + 1

        def do():
            found = []
            completed = 0

            def probe(last):
                if self._stop_flag:
                    return None
                ip = prefix + str(last)
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(0.7)
                    t0 = time.time()
                    r = s.connect_ex((ip, port))
                    lat = int((time.time() - t0) * 1000)
                    s.close()
                    if r == 0:
                        return (ip, 'Açık', str(lat))
                except OSError:
                    pass
                return None

            with concurrent.futures.ThreadPoolExecutor(max_workers=32) as ex:
                futs = {ex.submit(probe, last): last for last in range(start, end + 1)}
                for fut in concurrent.futures.as_completed(futs):
                    if self._stop_flag:
                        for f in futs:
                            f.cancel()
                        break
                    res = fut.result()
                    if res:
                        found.append(res)
                    completed += 1
                    worker = worker_ref['worker']
                    if worker is not None:
                        worker.progress.emit(completed, total)
            found.sort(key=lambda x: int(x[-1]))
            return found

        def show(found):
            self._show_results(found)
            self.btn_scan.setEnabled(True)
            self.btn_stop.setEnabled(False)

        w = Worker(do)
        worker_ref['worker'] = w
        w.job_name = 'LAN tarama'
        w.progress.connect(self._update_scan_progress)
        w.finished_ok.connect(show)
        w.failed.connect(lambda e: (self.btn_scan.setEnabled(True), self.btn_stop.setEnabled(False)))
        self.window._run(w, on_ok=lambda _: None,
                         desc='Ag: {}{}-{} taraniyor'.format(prefix, start, end))

    @Slot(int, int)
    def _update_scan_progress(self, completed, total):
        if total <= 0:
            return
        self.progress.setValue(min(100, int(completed * 100 / total)))
        self.lbl_summary.setText(
            'Taranıyor: {} / {} adres'.format(completed, total))

    def _show_results(self, found):
        self._found = found
        self.grid.setRowCount(0)
        for ip, state, lat in found:
            r = self.grid.rowCount()
            self.grid.insertRow(r)
            self.grid.setItem(r, COL_IP, QTableWidgetItem(ip))
            self.grid.setItem(r, COL_STATE, QTableWidgetItem(state))
            self.grid.setItem(r, COL_LATENCY, QTableWidgetItem(lat))
        row_height = self.grid.verticalHeader().defaultSectionSize()
        header_height = self.grid.horizontalHeader().height()
        desired_height = header_height + len(found) * row_height + 8
        if found:
            self.grid.setFixedHeight(min(420, max(120, desired_height)))
        else:
            self.grid.setFixedHeight(130)
        results_layout = self.results_card.layout()
        results_layout.invalidate()
        self.results_card.updateGeometry()
        root_layout = self.layout()
        root_layout.invalidate()
        root_layout.activate()
        self.progress.setValue(100)
        self.lbl_summary.setText('{} cihaz bulundu (port açık).'.format(len(found)))

    def _selected_ip(self):
        row = self.grid.currentRow()
        if row < 0:
            return None
        it = self.grid.item(row, COL_IP)
        return it.text() if it else None

    def _use_selected(self):
        ip = self._selected_ip()
        if not ip:
            QMessageBox.information(self, 'Seçim', 'Önce listeden bir IP seçin.')
            return
        self._set_target(ip + ':' + str(self.spn_port.value()))

    def _on_double_click(self, index):
        ip = self.grid.item(index.row(), COL_IP)
        if ip:
            self._set_target(ip.text() + ':' + str(self.spn_port.value()))

    def _set_target(self, target):
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
