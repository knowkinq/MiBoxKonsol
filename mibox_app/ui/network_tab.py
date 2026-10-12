# -*- coding: utf-8 -*-
"""Ag sekmesi: LAN'da ADB portu acik cihazlari tarar + eslestirme."""
import concurrent.futures
import re
import socket
import time

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QLineEdit,
    QSpinBox, QMessageBox, QInputDialog, QProgressBar, QSizePolicy,
)

from ..workers import Worker
from . import kit
from .flowlayout import FlowLayout

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

        row1 = QHBoxLayout()
        row1.setSpacing(4)
        self.txt_subnet = QLineEdit(local_subnet_guess())
        self.txt_subnet.setPlaceholderText('Subnet (orn: 192.168.1.)')
        self.spn_port = QSpinBox()
        self.spn_port.setRange(1, 65535)
        self.spn_port.setValue(5555)
        self.spn_port.setPrefix('port: ')
        self.spn_port.setMinimumWidth(198)
        self.spn_port.setMaximumWidth(198)
        self.spn_port.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        row1.addWidget(QLabel('Subnet:'))
        row1.addWidget(self.txt_subnet, 1)
        row1.addWidget(self.spn_port, 0)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(4)
        self.spn_from = QSpinBox()
        self.spn_from.setRange(1, 254)
        self.spn_from.setValue(1)
        self.spn_from.setPrefix('ilk: ')
        self.spn_from.setMinimumWidth(159)
        self.spn_from.setMaximumWidth(159)
        self.spn_to = QSpinBox()
        self.spn_to.setRange(1, 254)
        self.spn_to.setValue(254)
        self.spn_to.setPrefix('son: ')
        self.spn_to.setMinimumWidth(159)
        self.spn_to.setMaximumWidth(159)
        self.btn_scan = QPushButton('Tara')
        self.btn_scan.setProperty('accent', True)
        self.btn_scan.clicked.connect(self.scan)
        self.btn_stop = QPushButton('Durdur')
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_scan)
        row2.addWidget(self.spn_from)
        row2.addWidget(self.spn_to)
        row2.addWidget(self.btn_scan)
        row2.addWidget(self.btn_stop)
        row2.addStretch()
        root.addLayout(row2)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMaximumHeight(14)
        root.addWidget(self.progress)

        self.grid = kit.single_table(3, ['IP', 'Durum', 'Gecikme (ms)'])
        self.grid.horizontalHeader().setSectionResizeMode(COL_IP, QHeaderView.Stretch)
        self.grid.horizontalHeader().setSectionResizeMode(COL_STATE, QHeaderView.ResizeToContents)
        self.grid.horizontalHeader().setSectionResizeMode(COL_LATENCY, QHeaderView.ResizeToContents)
        self.grid.doubleClicked.connect(self._on_double_click)
        root.addWidget(self.grid, 1)

        flow = FlowLayout()
        self.btn_pair = QPushButton('Kablosuz Eslestir')
        self.btn_pair.clicked.connect(self._pair)
        self.btn_use = QPushButton('Seciliyi Hedef Yap')
        self.btn_use.setProperty('accent', True)
        self.btn_use.clicked.connect(self._use_selected)
        flow.addWidget(self.btn_pair)
        flow.addWidget(self.btn_use)
        root.addLayout(flow)

        self.lbl_summary = QLabel("Tara: LAN'da ADB portu acik cihazlari bulur. Cift tiklama hedef yapar.")
        self.lbl_summary.setWordWrap(True)
        root.addWidget(self.lbl_summary)
        self._stop_flag = False

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

        def do():
            found = []

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
                        return (ip, 'Acik', str(lat))
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
            found.sort(key=lambda x: int(x[-1]))
            return found

        def show(found):
            self._show_results(found)
            self.btn_scan.setEnabled(True)
            self.btn_stop.setEnabled(False)

        w = Worker(do)
        w.job_name = 'LAN tarama'
        w.finished_ok.connect(show)
        w.failed.connect(lambda e: (self.btn_scan.setEnabled(True), self.btn_stop.setEnabled(False)))
        self.window._run(w, on_ok=lambda _: None,
                         desc='Ag: {}{}-{} taraniyor'.format(prefix, start, end))

    def _show_results(self, found):
        self._found = found
        self.grid.setRowCount(0)
        for ip, state, lat in found:
            r = self.grid.rowCount()
            self.grid.insertRow(r)
            self.grid.setItem(r, COL_IP, QTableWidgetItem(ip))
            self.grid.setItem(r, COL_STATE, QTableWidgetItem(state))
            self.grid.setItem(r, COL_LATENCY, QTableWidgetItem(lat))
        self.progress.setValue(100)
        self.lbl_summary.setText('{} cihaz bulundu (port acik).'.format(len(found)))

    def _selected_ip(self):
        row = self.grid.currentRow()
        if row < 0:
            return None
        it = self.grid.item(row, COL_IP)
        return it.text() if it else None

    def _use_selected(self):
        ip = self._selected_ip()
        if not ip:
            QMessageBox.information(self, 'Secim', 'Once listeden bir IP secin.')
            return
        self._set_target(ip + ':' + str(self.spn_port.value()))

    def _on_double_click(self, index):
        ip = self.grid.item(index.row(), COL_IP)
        if ip:
            self._set_target(ip.text() + ':' + str(self.spn_port.value()))

    def _set_target(self, target):
        self.window.txt_target.setText(target)
        self.window._sync_target()
        self.core.config.push_history(target)
        try:
            self.window.refresh_history_combo()
        except Exception:
            pass
        self.window.append_log('Hedef ayarlandi, baglaniliyor: ' + target, 'INFO')
        self.window.on_connect()

    def _pair(self):
        host, ok = QInputDialog.getText(self, 'Eslestir', 'Eslestirme adresi (IP:port):',
                                       text=self.txt_subnet.text().strip() + '1:XXXXX')
        if not ok or not host.strip():
            return
        code, ok2 = QInputDialog.getText(self, 'Eslestir', 'Eslestirme kodu (TVde yazar):')
        if not ok2 or not code.strip():
            return

        def do():
            return self.core.engine.pair(host.strip(), code.strip())
        w = Worker(do)
        w.job_name = 'Kablosuz eslestirme'
        w.finished_ok.connect(lambda m: QMessageBox.information(self, 'Eslestirme', m or 'Eslestirme tamam.'))
        self.window._run(w, desc='Ag: kablosuz eslestirme deneniyor')
