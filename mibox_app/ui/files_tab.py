# -*- coding: utf-8 -*-
"""Dosya sekmesi: sdcard gözat, push/pull, klasör aç, sil."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QMessageBox,
    QLineEdit, QFileDialog, QInputDialog,
)

from . import kit

from ..workers import Worker

COL_NAME = 0
COL_SIZE = 1
COL_MTIME = 2


def _fmt_size(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return '?'
    if n >= 1024 * 1024 * 1024:
        return '{:.1f} GB'.format(n / (1024 ** 3))
    if n >= 1024 * 1024:
        return '{:.0f} MB'.format(n / (1024 ** 2))
    if n >= 1024:
        return '{:.0f} KB'.format(n / 1024)
    return '{} B'.format(n)


class FilesTab(QWidget):
    ROOTS = ['/sdcard', '/sdcard/Download', '/sdcard/Movies', '/sdcard/DCIM']

    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._cwd = '/sdcard'
        self._entries = []
        self._hist = []
        self._build()

    def _build(self):
        root = kit.page(self)

        row = QHBoxLayout()
        row.setSpacing(4)
        self.btn_back = QPushButton('← Üst')
        self.btn_back.setMinimumWidth(95)
        self.btn_back.setMaximumWidth(110)
        self.btn_back.clicked.connect(self._up)
        self.txt_path = QLineEdit(self._cwd)
        self.txt_path.returnPressed.connect(self._go_typed)
        self.btn_go = QPushButton('Git')
        self.btn_go.clicked.connect(self._go_typed)
        row.addWidget(self.btn_back)
        row.addWidget(self.txt_path, 1)
        row.addWidget(self.btn_go)
        self.btn_refresh = QPushButton('Yenile')
        self.btn_refresh.setProperty('accent', True)
        self.btn_refresh.clicked.connect(self.refresh)
        row.addWidget(self.btn_refresh)
        root.addLayout(row)

        # Hizli kokler (tek tikla klasore git)
        roots_row = QHBoxLayout()
        roots_row.setSpacing(4)
        for r in self.ROOTS:
            b = QPushButton(r.rsplit('/', 1)[-1] or '/')
            b.setToolTip(r)
            b.clicked.connect(lambda _=False, p=r: self._go(p))
            roots_row.addWidget(b)
        roots_row.addStretch()
        root.addLayout(roots_row)

        self.grid = kit.single_table(3, ['Ad', 'Boyut', 'Değişiklik'])
        hdr = self.grid.horizontalHeader()
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        hdr.setSectionResizeMode(COL_SIZE, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_MTIME, QHeaderView.ResizeToContents)
        self.grid.doubleClicked.connect(self._on_double)
        root.addWidget(self.grid, 1)

        flow_row = QHBoxLayout()
        flow_row.setSpacing(4)
        self.btn_push = QPushButton('Yükle (push)')
        self.btn_push.clicked.connect(self._push)
        self.btn_pull = QPushButton('İndir (pull)')
        self.btn_pull.clicked.connect(self._pull)
        self.btn_mkdir = QPushButton('Klasör Aç')
        self.btn_mkdir.clicked.connect(self._mkdir)
        self.btn_del = QPushButton('Sil')
        self.btn_del.setProperty('danger', True)
        self.btn_del.clicked.connect(self._delete)
        for b in (self.btn_push, self.btn_pull, self.btn_mkdir, self.btn_del):
            flow_row.addWidget(b)
        flow_row.addStretch()
        root.addLayout(flow_row)

        self.lbl_status = QLabel('Hazır. Yenile ile listele.')
        root.addWidget(self.lbl_status)

    # ------------------------------------------------------------------
    def _go(self, path):
        if path != self._cwd:
            self._hist.append(self._cwd)
        self._cwd = path.rstrip('/') or '/'
        self.txt_path.setText(self._cwd)
        self.refresh()

    def _go_typed(self):
        self._go(self.txt_path.text().strip() or '/sdcard')

    def _up(self):
        if self._hist:
            self._cwd = self._hist.pop()
            self.txt_path.setText(self._cwd)
            self.refresh()
        elif self._cwd != '/':
            self._go('/'.join(self._cwd.rstrip('/').split('/')[:-1]) or '/')

    def refresh(self):
        def do():
            self.core.engine.connect(self.core.target)
            return self.core.engine.file_list(self.core.target, self._cwd)
        w = Worker(do)
        w.job_name = 'Dosya listeleme'
        w.finished_ok.connect(self._show)
        self.window._run(w, desc='Dosyalar Yenile: liste okunuyor')

    def _show(self, entries):
        self._entries = entries
        self.grid.setRowCount(0)
        for e in entries:
            r = self.grid.rowCount()
            self.grid.insertRow(r)
            name = ('📁 ' if e['dir'] else '📄 ') + e['name']
            ni = QTableWidgetItem(name)
            ni.setData(Qt.UserRole, e)
            si = QTableWidgetItem('' if e['dir'] else _fmt_size(e['size']))
            mi = QTableWidgetItem(e['mtime'])
            for it in (ni, si, mi):
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.grid.setItem(r, COL_NAME, ni)
            self.grid.setItem(r, COL_SIZE, si)
            self.grid.setItem(r, COL_MTIME, mi)
        self.lbl_status.setText('{}: {} öğe'.format(self._cwd, len(entries)))

    def _selected(self):
        row = self.grid.currentRow()
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def _on_double(self, index):
        e = self._entries[index.row()] if 0 <= index.row() < len(self._entries) else None
        if e and e['dir']:
            self._go(self._cwd.rstrip('/') + '/' + e['name'])

    def _push(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Cihaza Yükle', '', 'Tümü (*.*)')
        if not paths:
            return

        def do():
            n = 0
            for p in paths:
                self.core.engine.push(self.core.target, p,
                                      self._cwd.rstrip('/') + '/' + os.path.basename(p))
                n += 1
            return n
        w = Worker(do)
        w.job_name = 'Dosya yukleme'
        w.finished_ok.connect(lambda n: (self.lbl_status.setText('{} dosya yüklendi.'.format(n)),
                                         self.refresh()))
        self.window._run(w, desc='Dosyalar: {} dosya yukleniyor -> {}'.format(len(paths), self._cwd))

    def _pull(self):
        e = self._selected()
        if not e or e['dir']:
            QMessageBox.information(self, 'Seçim', 'Önce bir dosya seçin (klasör değil).')
            return
        dest, _ = QFileDialog.getSaveFileName(self, 'Farklı Kaydet', e['name'], 'Tümü (*.*)')
        if not dest:
            return

        def do():
            self.core.engine.pull(self.core.target,
                                  self._cwd.rstrip('/') + '/' + e['name'], dest)
            return dest
        w = Worker(do)
        w.job_name = 'Dosya indirme'
        w.finished_ok.connect(lambda d: self.lbl_status.setText('İndirildi: ' + d))
        self.window._run(w, desc='Dosyalar: indiriliyor: ' + e['name'])

    def _mkdir(self):
        name, ok = QInputDialog.getText(self, 'Klasör', 'Ad:')
        if not ok or not name.strip():
            return

        def do():
            self.core.engine.file_mkdir(self.core.target,
                                        self._cwd.rstrip('/') + '/' + name.strip())
            return name.strip()
        w = Worker(do)
        w.job_name = 'Klasör olusturma'
        w.finished_ok.connect(lambda _: self.refresh())
        self.window._run(w, desc='Dosyalar: klasör aciliyor: ' + name.strip())

    def _delete(self):
        e = self._selected()
        if not e:
            QMessageBox.information(self, 'Seçim', 'Önce öğe seçin.')
            return
        full = self._cwd.rstrip('/') + '/' + e['name']
        if QMessageBox.question(self, u'Onay — Kalıcı Sil',
                                u'Silinsin mi? (Geri alınamaz!)\n\n• {}{}'.format(
                                    full, '  [KLASÖR]' if e.get('dir') else ''),
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return

        def do():
            self.core.engine.file_remove(self.core.target, full)
            return full
        w = Worker(do)
        w.job_name = 'Dosya silme'
        w.finished_ok.connect(lambda _: self.refresh())
        self.window._run(w, desc='Dosyalar: siliniyor: ' + full)
