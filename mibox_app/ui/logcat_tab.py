# -*- coding: utf-8 -*-
"""Logcat sekmesi: canlı sistem günlüğü + çökme avcısı + filtre."""
import re
from collections import deque

from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPlainTextEdit, QPushButton,
    QLabel, QComboBox, QLineEdit, QMessageBox, QFileDialog, QApplication,
)

from . import kit
from .actions_dialog import search_key

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
        self._poll_generation = 0
        self._poll_sequence = 0
        self._poll_active_request = None
        self._crash_generation = 0
        self._clear_busy = False
        self._lines = deque(maxlen=3000)
        self._prev_lines = []
        self.core.connection_changed.connect(self._on_connection_changed)
        self._build()

    def _build(self):
        root = kit.page(self)

        filters = QHBoxLayout()
        filters.setSpacing(kit.SPACING)
        self.cmb_level = QComboBox()
        self.cmb_level.addItems(['Tümü (V)', 'Debug (D)', 'Info (I)', 'Uyarı (W)', 'Hata (E)', 'Fatal (F)'])
        self.cmb_level.setCurrentIndex(2)
        self.cmb_level.setAccessibleName('Log seviyesi')
        self.txt_tag = QLineEdit()
        self.txt_tag.setPlaceholderText('Etiket filtresi (örn: AndroidRuntime)...')
        self.txt_tag.setMinimumWidth(180)
        self.txt_tag.setAccessibleName('Log etiketi filtresi')
        self.txt_tag.setClearButtonEnabled(True)
        self.btn_start = QPushButton('Başlat')
        self.btn_start.setProperty('accent', True)
        self.btn_start.clicked.connect(self._toggle)
        self.chk_follow = kit.CheckBox('Canlı görünümü izle')
        self.chk_follow.setChecked(True)
        self.chk_follow.setToolTip('Kapalıyken görünüm duraklar; kayıtlar sınırlı tamponda birikmeye devam eder.')
        self.chk_follow.toggled.connect(lambda enabled: self._render_lines() if enabled else None)
        filters.addWidget(QLabel('Seviye'))
        filters.addWidget(self.cmb_level)
        filters.addWidget(self.txt_tag, 1)
        filters.addWidget(self.chk_follow)
        filters.addWidget(self.btn_start)
        root.addLayout(filters)

        tools = kit.action_bar()
        tools.setSpacing(kit.SPACING)
        self.btn_crash = QPushButton('Çökme Avcısı')
        self.btn_crash.setToolTip('Son FATAL/AndroidRuntime izlerini getirir')
        self.btn_crash.clicked.connect(self._crash)
        self.btn_clear_screen = QPushButton('Ekranı Temizle')
        self.btn_clear_screen.setToolTip('Log ekranını anında temizler')
        self.btn_clear_screen.clicked.connect(self._clear_screen)
        self.btn_clear_dev = QPushButton('Cihaz Logunu Temizle')
        self.btn_clear_dev.setProperty('danger', True)
        self.btn_clear_dev.setToolTip('Cihazdaki log tamponunu ve ekranı temizle')
        self.btn_clear_dev.clicked.connect(self._clear_device)
        self.btn_save = QPushButton('Kaydet')
        self.btn_save.clicked.connect(self._save)
        self.btn_copy = QPushButton('Görüneni kopyala')
        self.btn_copy.clicked.connect(self._copy_visible)
        tools.addWidget(self.btn_crash)
        tools.addWidget(self.btn_clear_screen)
        tools.addWidget(self.btn_clear_dev)
        tools.addWidget(self.btn_copy)
        tools.addWidget(self.btn_save)
        root.addLayout(tools)

        search_row = QHBoxLayout()
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText('Alınan kayıtlarda ara: uygulama, hata veya metin…')
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.setAccessibleName('Alınan cihaz kayıtlarında ara')
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._render_lines)
        self.txt_search.textChanged.connect(lambda: self._search_timer.start())
        self.lbl_count = QLabel('0 kayıt')
        self.lbl_count.setProperty('role', 'quiet')
        search_row.addWidget(self.txt_search, 1)
        search_row.addWidget(self.lbl_count)
        root.addLayout(search_row)

        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setPlaceholderText(
            'Canlı log henüz yok. Başlat ile izlemeyi açın veya Çökme Avcısı ile son izleri görüntüleyin.')
        self.txt_log.setMaximumBlockCount(3000)
        self.txt_log.setStyleSheet(kit.mono_style())
        self._level_colors = logcat_colors_for(kit.dark_from(self))
        root.addWidget(self.txt_log, 1)

        self.lbl_status = kit.status_label('Hazır. Canlı izleme 3 saniyede bir yenilenir.')
        root.addWidget(self.lbl_status)
        self._source_filter_key = (self._level(), self.txt_tag.text().strip())
        self.cmb_level.currentIndexChanged.connect(self._source_filters_changed)
        self.txt_tag.editingFinished.connect(self._source_filters_changed)
        self._render_lines()

    def _source_filters_changed(self, *_):
        key = (self._level(), self.txt_tag.text().strip())
        if key == self._source_filter_key:
            return
        self._source_filter_key = key
        self._clear_screen()
        if self._timer.isActive():
            self.lbl_status.setText('Kaynak filtresi değişti; yeni kayıtlar bekleniyor…')
            self._poll()

    def _level(self):
        idx = self.cmb_level.currentIndex()
        return [None, 'D', 'I', 'W', 'E', 'F'][idx]

    def _toggle(self):
        if self._clear_busy:
            self.lbl_status.setText('Cihaz günlüğü temizleniyor; tamamlanınca yeniden başlatın.')
            return
        if self._timer.isActive():
            self._timer.stop()
            self._poll_generation += 1
            self._poll_active_request = None
            self.btn_start.setText('Başlat')
            self.lbl_status.setText('Durduruldu.')
        else:
            if getattr(self.window, '_connection_busy', False):
                self.lbl_status.setText('Bağlantı işlemi sürüyor; tamamlanınca Başlat’a basın.')
                return
            if not getattr(self.core, 'connected', False) or not getattr(self.core, 'target', None):
                QMessageBox.information(self, 'Logcat', "Bağlı cihaz yok. Canlı izleme başlatmak için önce TV'ye bağlanın.")
                return
            self._clear_screen()
            self._poll_generation += 1
            self._timer.start(3000)
            self.btn_start.setText('Durdur')
            self.lbl_status.setText('Canlı izleniyor...')
            self._poll()

    def _on_connection_changed(self, connected, target):
        self._poll_generation += 1
        self._poll_active_request = None
        self._crash_generation += 1
        if self._timer.isActive():
            self._timer.stop()
            self.btn_start.setText('Başlat')
        self._prev_lines = []
        self.lbl_status.setText(
            'Cihaz bağlantısı değişti; canlı izleme durduruldu.' if connected
            else 'Cihaz bağlantısı kesildi; canlı izleme durduruldu.')

    def _poll(self):
        if self._poll_active_request is not None:
            return
        target = getattr(self.core, 'target', None)
        if (not self._timer.isActive() or not getattr(self.core, 'connected', False)
                or not target or getattr(self.window, '_connection_busy', False)):
            return
        level, tag = self._source_filter_key
        tag = tag or None
        generation = self._poll_generation
        self._poll_sequence += 1
        request = self._poll_sequence
        self._poll_active_request = request

        def do():
            return self.core.engine.logcat_dump(target, lines=120,
                                                level=level, tag=tag)

        def done(text):
            if self._poll_active_request != request:
                return
            self._poll_active_request = None
            if (generation == self._poll_generation and self._timer.isActive()
                    and self.core.connected and self.core.target == target):
                self._append(text)
                self.lbl_status.setText('Canlı izleniyor · 3 saniyede bir yenilenir.')

        def failed(error):
            if self._poll_active_request != request:
                return
            self._poll_active_request = None
            if (generation == self._poll_generation and self._timer.isActive()
                    and self.core.connected and self.core.target == target):
                self.lbl_status.setText('Logcat okunamadı: {}'.format(error))
                self._timer.stop()
                self.btn_start.setText('Yeniden Başlat')
        w = Worker(do)
        w.job_name = 'Logcat okuma'
        w.finished_ok.connect(done)
        w.failed.connect(failed)
        # canli yoklama her 3 sn doner; log kirliligi olmasin diye desc yok
        self.window._run(w)

    def apply_theme(self):
        """Tema degisince: log kutusu tipografisi + seviye renkleri yenilenir."""
        self._level_colors = logcat_colors_for(kit.dark_from(self))
        try:
            self.txt_log.setStyleSheet(kit.mono_style())
            self._render_lines()
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
        self._lines.extend(new_lines)
        if self.chk_follow.isChecked():
            self._render_lines()
        else:
            self.lbl_count.setText('{} kayıt · görünüm duraklatıldı'.format(len(self._lines)))

    def _render_lines(self):
        terms = search_key(self.txt_search.text()).split()
        visible = [line for line in self._lines
                   if all(term in search_key(line) for term in terms)]
        pal = self._level_colors
        default = kit.colors(self)['text']
        chunks = []
        for line in visible:
            match = re.match(r'^([VDIWEF])/', line)
            color = pal.get(match.group(1), default) if match else default
            chunks.append('<p><span style="color:{};">{}</span></p>'.format(color, self._esc(line)))
        self.txt_log.clear()
        if chunks:
            self.txt_log.appendHtml(''.join(chunks))
        if self.chk_follow.isChecked():
            self.txt_log.moveCursor(QTextCursor.End)
        self.lbl_count.setText('{} / {} kayıt'.format(len(visible), len(self._lines)))
        self.btn_copy.setEnabled(bool(visible))
        self.btn_save.setEnabled(bool(visible))

    def _copy_visible(self):
        QApplication.clipboard().setText(self.txt_log.toPlainText())
        self.lbl_status.setText('Görünen cihaz kayıtları kopyalandı.')

    @staticmethod
    def _esc(s):
        return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))

    def _crash(self):
        if self._clear_busy:
            self.lbl_status.setText('Cihaz günlüğünün temizlenmesini bekleyin.')
            return
        if getattr(self.window, '_connection_busy', False):
            self.lbl_status.setText('Bağlantı işlemi sürüyor; tamamlanınca yeniden deneyin.')
            return
        if not getattr(self.core, 'connected', False) or not getattr(self.core, 'target', None):
            QMessageBox.information(self, 'Çökme Avcısı', "Bağlı cihaz yok. Çökme analizi için önce TV'ye bağlanın.")
            return
        target = self.core.target
        generation = self._poll_generation
        self._crash_generation += 1
        request = self._crash_generation

        def do():
            return self.core.engine.logcat_crash(target)

        def done(text):
            if (request == self._crash_generation and generation == self._poll_generation
                    and self.core.connected and self.core.target == target
                    and not getattr(self.window, '_connection_busy', False)):
                self._show_crash(text)

        def failed(error):
            if (request == self._crash_generation and generation == self._poll_generation
                    and self.core.connected and self.core.target == target):
                self.lbl_status.setText('Çökme kayıtları okunamadı: {}'.format(error))
        w = Worker(do)
        w.job_name = 'Cokme avcisi'
        w.finished_ok.connect(done)
        w.failed.connect(failed)
        self.window._run(w, desc='Logcat: cokme izleri araniyor')

    def _show_crash(self, text):
        if not text.strip():
            QMessageBox.information(self, 'Çökme Avcısı', 'Bu sorguda çökme kaydı dönmedi; bu sonuç cihazda hiç hata olmadığı anlamına gelmez.')
            return
        if self._timer.isActive():
            self._toggle()
        else:
            self._poll_generation += 1
            self._poll_active_request = None
        self.txt_log.clear()
        self._lines.clear()
        self._prev_lines = []
        self._append(text)
        self._render_lines()
        self.lbl_status.setText('Son çökme izleri gösteriliyor.')

    def _clear_screen(self):
        """Log goruntuleme kutusunu ve yinelenen filtre tamponunu aninda temizler."""
        self.txt_log.clear()
        self._lines.clear()
        self._render_lines()
        self._poll_generation += 1
        self._poll_active_request = None
        self._prev_lines = []
        self.lbl_status.setText('Log ekranı temizlendi.')

    def _clear_device(self):
        if self._clear_busy:
            return
        target = getattr(self.core, 'target', None)
        if (not getattr(self.core, 'connected', False) or not target
                or getattr(self.window, '_connection_busy', False)):
            self.lbl_status.setText('Cihaz günlüğünü temizlemek için bağlantının hazır olmasını bekleyin.')
            return
        generation = self._poll_generation
        if QMessageBox.question(self, 'Cihaz günlüğünü temizle',
                                'TV’nin günlük tamponu silinecek. Devam edilsin mi?',
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        if (generation != self._poll_generation or not self.core.connected
                or self.core.target != target or getattr(self.window, '_connection_busy', False)):
            self.lbl_status.setText('Bağlantı değişti; cihaz günlüğü temizlenmedi.')
            return
        self._clear_screen()
        self._timer.stop()
        self.btn_start.setText('Başlat')
        self._clear_busy = True
        self.btn_start.setEnabled(False)
        self.btn_clear_dev.setEnabled(False)
        self.lbl_status.setText('Cihaz günlüğü temizleniyor…')
        generation = self._poll_generation

        def do():
            self.core.engine.logcat_clear(target)
            return 'temizlendi'

        def done(_):
            self._finish_clear()
            if (generation == self._poll_generation and self.core.connected
                    and self.core.target == target):
                self.lbl_status.setText('Cihaz log tamponu ve ekran temizlendi.')

        def failed(error):
            self._finish_clear()
            if (generation == self._poll_generation and self.core.connected
                    and self.core.target == target):
                self.lbl_status.setText('Cihaz günlüğü temizlenemedi: {}'.format(error))
        w = Worker(do)
        w.job_name = 'Logcat temizleme'
        w.finished_ok.connect(done)
        w.failed.connect(failed)
        self.window._run(w, desc='Logcat: cihaz tamponu temizleniyor')

    def _finish_clear(self):
        self._clear_busy = False
        self.btn_start.setEnabled(True)
        self.btn_clear_dev.setEnabled(True)

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
