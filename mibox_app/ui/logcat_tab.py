# -*- coding: utf-8 -*-
"""Logcat sekmesi: canlı sistem günlüğü + çökme avcısı + filtre."""
from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPlainTextEdit, QPushButton,
    QLabel, QComboBox, QLineEdit, QMessageBox, QFileDialog, QCheckBox,
)

from . import kit

from ..workers import Worker

# Geriye donuk uyumluluk: koyu palet tabanli seviye renkleri.
# Yeni kod apply_theme() icinde theme.logcat_colors_for(dark) kullanir.
from .theme import logcat_colors_for

LEVEL_COLORS = logcat_colors_for(True)
# FATAL her temada kizil kalir (logcat'in kendisi kizildir, palet disi)
LEVEL_COLORS['F'] = '#ff0000'


def dedup_new_lines(prev, lines):
    """Kayan pencere dedup (Faz 6): YALNIZCA yeni satirlari dondur.

    Her yoklama son N satiri getirir; onceki yoklamanin soneki ile yeni
    yoklamanin basindaki EN UZUN ortak parca bulup onu atlar. Filtre
    degisirse ortak bulunamaz -> tum satirlar 'yeni' sayilir (dogru).
    """
    k = 0
    for i in range(min(len(prev), len(lines)), 0, -1):
        if lines[:i] == prev[-i:]:
            k = i
            break
    return lines[k:]


class LogcatTab(QWidget):
    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._build()

    def _build(self):
        root = kit.page(self)

        row = QHBoxLayout()
        row.setSpacing(4)
        self.cmb_level = QComboBox()
        self.cmb_level.addItems(['Tümü (V)', 'Debug (D)', 'Info (I)', 'Uyarı (W)', 'Hata (E)', 'Fatal (F)'])
        self.cmb_level.setCurrentIndex(2)
        self.txt_tag = QLineEdit()
        self.txt_tag.setPlaceholderText('Etiket filtresi (örn: AndroidRuntime)...')
        self.txt_tag.setMaximumWidth(200)
        self.btn_start = QPushButton('Başlat')
        self.btn_start.setProperty('accent', True)
        self.btn_start.clicked.connect(self._toggle)
        self.btn_crash = QPushButton('Çökme Avcısı')
        self.btn_crash.setToolTip('Son FATAL/AndroidRuntime izlerini getirir')
        self.btn_crash.clicked.connect(self._crash)
        self.btn_clear_dev = QPushButton('Logu Temizle')
        self.btn_clear_dev.setToolTip('Cihaz log tamponunu temizle')
        self.btn_clear_dev.clicked.connect(self._clear_device)
        self.chk_follow = QCheckBox('Takip')
        self.chk_follow.setChecked(True)
        self.btn_save = QPushButton('Kaydet')
        self.btn_save.clicked.connect(self._save)
        row.addWidget(QLabel('Seviye:'))
        row.addWidget(self.cmb_level)
        row.addWidget(self.txt_tag)
        row.addWidget(self.btn_start)
        row.addWidget(self.btn_crash)
        row.addWidget(self.btn_clear_dev)
        row.addWidget(self.chk_follow)
        row.addStretch()
        row.addWidget(self.btn_save)
        root.addLayout(row)

        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(3000)
        self.txt_log.setStyleSheet(kit.mono_style())
        self._level_colors = logcat_colors_for(kit.dark_from(self))
        root.addWidget(self.txt_log, 1)

        self.lbl_status = QLabel('Hazır. Başlat ile canlı izle (3 sn aralık).')
        root.addWidget(self.lbl_status)

    def _level(self):
        idx = self.cmb_level.currentIndex()
        return [None, 'D', 'I', 'W', 'E', 'F'][idx]

    def _toggle(self):
        if self._timer.isActive():
            self._timer.stop()
            self.btn_start.setText('Başlat')
            self.lbl_status.setText('Durduruldu.')
        else:
            try:
                self.core.engine.connect(self.core.target)
            except Exception as e:
                QMessageBox.critical(self, 'Bağlantı', str(e))
                return
            self.txt_log.clear()
            self._prev_lines = []
            self._poll()
            self._timer.start(3000)
            self.btn_start.setText('Durdur')
            self.lbl_status.setText('Canlı izleniyor...')

    def _poll(self):
        level = self._level()
        tag = self.txt_tag.text().strip() or None

        def do():
            return self.core.engine.logcat_dump(self.core.target, lines=120,
                                                level=level, tag=tag)
        w = Worker(do)
        w.job_name = 'Logcat okuma'
        w.finished_ok.connect(self._append)
        # canli yoklama her 3 sn doner; log kirliligi olmasin diye desc yok
        self.window._run(w)

    def apply_theme(self):
        """Tema degisince: log kutusu tipografisi + seviye renkleri yenilenir."""
        self._level_colors = logcat_colors_for(kit.dark_from(self))
        try:
            self.txt_log.setStyleSheet(kit.mono_style())
        except RuntimeError:
            return

    def _append(self, text):
        if not text.strip():
            return
        lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
        # Pencere örtüsü: her yoklama son 120 satiri getirir; ayni satirlar
        # tekrar tekrar eklenir. dedup_new_lines() YALNIZCA yeni satirlari verir.
        prev = getattr(self, '_prev_lines', [])
        new_lines = dedup_new_lines(prev, lines)
        self._prev_lines = lines
        if not new_lines:
            return
        pal = getattr(self, '_level_colors', None) or logcat_colors_for(kit.dark_from(self))
        default = kit.colors(self).get('text', '#cdd6f4')
        for line in new_lines:
            lvl = line[2] if len(line) > 3 and line[1] == '/' else 'I'
            color = pal.get(lvl, default)
            self.txt_log.appendHtml(
                '<span style="color:{};">{}</span>'.format(color, self._esc(line)))
        if self.chk_follow.isChecked():
            self.txt_log.moveCursor(QTextCursor.End)

    @staticmethod
    def _esc(s):
        return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))

    def _crash(self):
        def do():
            return self.core.engine.logcat_crash(self.core.target)
        w = Worker(do)
        w.job_name = 'Cokme avcisi'
        w.finished_ok.connect(self._show_crash)
        self.window._run(w, desc='Logcat: cokme izleri araniyor')

    def _show_crash(self, text):
        if not text.strip():
            QMessageBox.information(self, 'Çökme Avcısı', 'Son çökme izi bulunamadı. Temiz görünüyor.')
            return
        if self._timer.isActive():
            self._toggle()
        self.txt_log.clear()
        self._append(text)
        self.lbl_status.setText('Son çökme izleri gösteriliyor.')

    def _clear_device(self):
        # Cihaz tamponu silinir: onaysiz yapma (cokme izleri gidebilir).
        if QMessageBox.question(
                self, u'Onay — Cihaz Logunu Temizle',
                u'Cihazdaki log tamponu silinsin mi?\n(İncelenmemis çökme izleri kaybolur.)',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes:
            return

        def do():
            self.core.engine.logcat_clear(self.core.target)
            return 'temizlendi'
        w = Worker(do)
        w.job_name = 'Logcat temizleme'
        w.finished_ok.connect(lambda _: self.lbl_status.setText('Cihaz log tamponu temizlendi.'))
        self.window._run(w, desc='Logcat: cihaz tamponu temizleniyor')

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Logcat Kaydet', 'mibox-logcat.txt', 'Metin (*.txt)')
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.txt_log.toPlainText())
            QMessageBox.information(self, 'Tamam', 'Kaydedildi:\n' + path)
        except OSError as e:
            QMessageBox.critical(self, 'Hata', str(e))
