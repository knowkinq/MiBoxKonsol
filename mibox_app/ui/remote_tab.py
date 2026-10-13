# -*- coding: utf-8 -*-
"""Kumanda sekmesi: ADB keyevent tabanli uzaktan kumanda."""
import datetime
import os
import time

from PySide6.QtCore import Qt, QTimer, QEvent, QSize
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QPushButton, QLineEdit, QComboBox, QMessageBox,
    QFileDialog, QApplication, QBoxLayout, QSizePolicy,
)

from ..config import SHOT_DIR
from ..adb_engine import KEYCODE_POWER, KEYCODE_SLEEP, KEYCODE_WAKEUP
from ..workers import Worker, DeviceInfoWorker, CancelledError
from . import kit
from .flowlayout import FlowLayout

KEYS = {
    'guc': [
        ('GUC', KEYCODE_POWER), ('Uyku', KEYCODE_SLEEP), ('Uyan', KEYCODE_WAKEUP),
    ],
    'ses': [
        ('Ses +', 24), ('Ses -', 25), ('Sessiz', 164),
    ],
    'media': [
        ('Oynat/Duraklat', 85), ('Durdur', 86),
        ('Önceki', 88), ('Sonraki', 87),
        ('Geri Sar', 90), ('Hızlı Sar', 91),
        ('Kayıt', 130),
    ],
    'navigasyon': [
        ('Yukari', 19), ('Asagi', 20), ('Sol', 21), ('Sağ', 22),
        ('OK', 23), ('Geri', 4), ('Ana Ekran', 3), ('Menü', 82),
        ('Ayarlar', 176),
    ],
}


class RemoteTab(QWidget):
    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._busy = False
        self._held = None
        self._pending_ok = None
        self._hold_ready = False
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._hold_tick)
        self._shot_generation = 0
        self._shot_worker = None
        self._shot_busy = False
        self._shot_target = None
        self._shot_data_generation = None
        self._shot_data = None
        self._shot_pixmap = None
        self._apps_load_generation = 0
        self._build()
        self.core.connection_changed.connect(self._connection_changed)
        QApplication.instance().installEventFilter(self)

    REPEAT_KEYS = frozenset((19, 20, 21, 22, 24, 25, 90, 91))

    def _bind_key(self, button, code, label):
        button.setProperty('keyCode', code)
        if code in self.REPEAT_KEYS or code == 23:
            button.installEventFilter(self)
            button.pressed.connect(lambda: self._press_key(button, code, label))
            button.released.connect(lambda: self._release_key(button, activate=False))
            button.setToolTip('Basılı tut: uzun basış' if code == 23 else 'Basılı tut: sürekli tekrarla')
        else:
            button.clicked.connect(lambda: self._send_key(code, label))

    def _press_key(self, button, code, label):
        self._stop_hold()
        if not self.core.connected or not self.core.target:
            self.lbl_status.setText('Önce cihaza bağlanın.')
            return
        self._held = (button, code, label, self.core.target)
        self._hold_timer.start(450)
        if code != 23:
            self._send_key(code, label, target=self.core.target)

    def _release_key(self, button, activate=True):
        held = self._held
        if held is None or held[0] is not button:
            return
        send_ok = held[1] == 23 and activate
        longpress = self._hold_ready
        self._stop_hold()
        if send_ok:
            if self._busy:
                self._pending_ok = (held[1], held[2], held[3], longpress)
            else:
                self._send_key(held[1], held[2], target=held[3], longpress=longpress)

    def _stop_hold(self):
        self._hold_timer.stop()
        if self._held is not None:
            self._held[0].setDown(False)
        self._held = None
        self._hold_ready = False
        self._pending_ok = None

    def _hold_tick(self):
        held = self._held
        if held is None:
            return
        if not self.core.connected or self.core.target != held[3] or not held[0].isDown():
            self._stop_hold()
            return
        self._hold_ready = True
        if self._busy:
            # Retry after completion cadence, without accumulating stale commands.
            self._hold_timer.start(150)
            return
        self._send_key(held[1], held[2], target=held[3], longpress=held[1] == 23)
        if held[1] == 23:
            self._stop_hold()
        else:
            self._hold_timer.start(150)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize and obj is self.parentWidget() and hasattr(self, '_content_row'):
            self._content_row.setDirection(
                QBoxLayout.TopToBottom if event.size().width() < 850 else QBoxLayout.LeftToRight)
        if self._held is not None and obj is self._held[0]:
            if event.type() == QEvent.FocusOut:
                self._stop_hold()
            elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                self._release_key(obj, activate=obj.rect().contains(event.position().toPoint()))
            elif event.type() == QEvent.KeyRelease and event.key() == Qt.Key_Space and not event.isAutoRepeat():
                self._release_key(obj)
        if event.type() == QEvent.ApplicationDeactivate or (
                event.type() == QEvent.WindowDeactivate and obj is self.window):
            self._stop_hold()
        return super().eventFilter(obj, event)

    def hideEvent(self, event):
        self._stop_hold()
        super().hideEvent(event)

    def _connection_changed(self, *_):
        self._stop_hold()
        self._apps_load_generation += 1
        self._set_apps_loading(False)
        self._shot_generation += 1
        if self._shot_worker is not None:
            self._shot_worker.cancel()
        self._clear_shot('Bağlantı değişti; yeni görüntü alın.')

    def _key_button(self, label, code, min_h=44, min_w=0, tooltip='', role='secondary'):
        b = QPushButton(label)
        b.setMinimumHeight(min_h)
        if min_w:
            b.setMinimumWidth(min_w)
        b.setProperty('role', role)
        if tooltip:
            b.setToolTip(tooltip)
        self._bind_key(b, code, label)
        return b

    def _build_remote_body(self):
        """Build the compact primary controls around a centered directional pad."""
        body = QVBoxLayout()
        body.setContentsMargins(12, 6, 12, 12)
        body.setSpacing(8)
        self.lbl_status = kit.status_label('Hazır.')
        body.addWidget(self.lbl_status)

        power_row = QHBoxLayout()
        power_row.setSpacing(8)
        power_row.addWidget(self._key_button(
            'Güç', KEYCODE_POWER, min_h=38,
            tooltip='Güç (key {})'.format(KEYCODE_POWER)))
        power_row.addWidget(self._key_button(
            'Uyku', KEYCODE_SLEEP, min_h=38,
            tooltip='Uyku (key {})'.format(KEYCODE_SLEEP)))
        power_row.addWidget(self._key_button(
            'Uyan', KEYCODE_WAKEUP, min_h=38,
            tooltip='Uyan (key {})'.format(KEYCODE_WAKEUP)))
        body.addLayout(power_row)

        pad_shell = QWidget()
        pad_shell.setObjectName('remotePad')
        pad_shell.setFixedSize(194, 194)
        pad = QGridLayout(pad_shell)
        pad.setContentsMargins(10, 10, 10, 10)
        pad.setSpacing(6)
        self._pad_btn(pad, '↑', 19, 0, 1, tooltip='Yukarı (key 19)')
        self._pad_btn(pad, '←', 21, 1, 0, tooltip='Sol (key 21)')
        self._pad_btn(pad, 'OK', 23, 1, 1, accent=True, tooltip='OK (key 23)')
        self._pad_btn(pad, '→', 22, 1, 2, tooltip='Sağ (key 22)')
        self._pad_btn(pad, '↓', 20, 2, 1, tooltip='Aşağı (key 20)')
        direction_column = QVBoxLayout()
        direction_column.setSpacing(10)
        direction_column.addWidget(pad_shell, 0, Qt.AlignHCenter)

        nav_row = QHBoxLayout()
        nav_row.setSpacing(8)
        nav_row.addWidget(self._key_button('Geri', 4, min_h=40, role='quiet'))
        nav_row.addWidget(self._key_button('Ana ekran', 3, min_h=40))
        nav_row.addWidget(self._key_button('Menü', 82, min_h=40, role='quiet'))
        direction_column.addLayout(nav_row)
        direction_column.addStretch()

        controls = QVBoxLayout()
        controls.setSpacing(8)
        volume_card = QGroupBox('Ses')
        volume = QGridLayout(volume_card)
        volume.setContentsMargins(8, 8, 8, 6)
        volume.setSpacing(4)
        volume.addWidget(self._key_button('Ses −', 25, min_h=34), 0, 0)
        volume.addWidget(self._key_button('Ses +', 24, min_h=34), 0, 1)
        volume.addWidget(self._key_button('Sessiz', 164, min_h=32, role='quiet'), 1, 0, 1, 2)

        media_card = QGroupBox('Medya')
        media = QGridLayout(media_card)
        media.setContentsMargins(8, 8, 8, 6)
        media.setSpacing(4)
        for label, code, row, column, role in (
                ('Oynat / Duraklat', 85, 0, 0, 'primary'),
                ('Durdur', 86, 0, 1, 'secondary'),
                ('Önceki', 88, 1, 0, 'quiet'),
                ('Sonraki', 87, 1, 1, 'quiet'),
                ('Geri sar', 90, 2, 0, 'quiet'),
                ('İleri sar', 91, 2, 1, 'quiet')):
            media.addWidget(self._key_button(label, code, min_h=34, role=role), row, column)
        controls.addWidget(volume_card)
        controls.addWidget(media_card)
        controls.addStretch()
        middle = QHBoxLayout()
        middle.setSpacing(12)
        middle.addLayout(direction_column, 1)
        middle.addLayout(controls, 1)
        body.addLayout(middle)
        body.addStretch()
        return body

    def _build(self):
        root = kit.page(self)
        root.setSpacing(8)

        launch_card = QGroupBox()
        launch_card.setObjectName('compactCard')
        launch = QVBoxLayout(launch_card)
        launch.setSpacing(8)
        launch_title = QLabel('Uygulama başlat')
        launch_title.setObjectName('cardTitle')
        launch.addWidget(launch_title)

        launch_row = QHBoxLayout()
        launch_row.setSpacing(8)
        self.cmb_app = QComboBox()
        self.cmb_app.setPlaceholderText('Yüklü uygulamalar için listeyi yükleyin')
        self.cmb_app.setEditable(True)
        self.cmb_app.lineEdit().setPlaceholderText('Uygulama seçin veya paket adı yazın...')
        self.btn_load_apps = QPushButton('Yüklüleri Yükle')
        self.btn_load_apps.setProperty('role', 'secondary')
        self.btn_load_apps.setToolTip('Cihazdaki yüklü uygulamaları ad ve paket bilgisiyle listele')
        self.btn_load_apps.clicked.connect(self._load_installed_apps)
        self.btn_launch = QPushButton('Aç')
        self.btn_launch.setProperty('role', 'primary')
        self.btn_launch.clicked.connect(self._launch_selected)
        launch_row.addWidget(self.cmb_app, 1)
        launch_row.addWidget(self.btn_load_apps)
        launch_row.addWidget(self.btn_launch)
        launch.addLayout(launch_row)

        remote = QGroupBox('Kumanda')
        remote.setLayout(self._build_remote_body())
        primary_column = QVBoxLayout()
        primary_column.setSpacing(8)
        primary_column.addWidget(launch_card)
        primary_column.addWidget(remote, 3)
        # Start stacked so the horizontal minimum cannot prevent the widget
        # from shrinking before its first resize notification.
        content_row = QBoxLayout(QBoxLayout.TopToBottom)
        self._content_row = content_row
        content_row.setSpacing(8)
        content_row.addLayout(primary_column, 3)

        aux_row = QVBoxLayout()
        aux_row.setSpacing(8)
        input_card = QGroupBox()
        input_card.setObjectName('compactCard')
        input_layout = QVBoxLayout(input_card)
        input_layout.setSpacing(6)
        input_title = QLabel('Metin girişi')
        input_title.setObjectName('cardTitle')
        input_layout.addWidget(input_title)
        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText('TV’ye gönderilecek metin...')
        self.txt_input.returnPressed.connect(self._send_text)
        send_text = QPushButton('Gönder')
        send_text.setProperty('role', 'primary')
        send_text.clicked.connect(self._send_text)
        self.lbl_text_hint = kit.hint_label('')
        self.lbl_key_hint = kit.hint_label(
            'Yön, ses ve sarma tuşlarını basılı tutun. OK: kısa basış seçer, uzun basış seçenekleri açar.')
        input_layout.addWidget(self.txt_input)
        input_layout.addWidget(send_text)
        input_layout.addWidget(self.lbl_text_hint)
        input_layout.addWidget(self.lbl_key_hint)
        aux_row.addWidget(input_card)

        shot_card = QGroupBox()
        shot_card.setObjectName('compactCard')
        shot_layout = QVBoxLayout(shot_card)
        shot_layout.setSpacing(6)
        shot_title = QLabel('Ekran görüntüsü')
        shot_title.setObjectName('cardTitle')
        shot_layout.addWidget(shot_title)
        self.lbl_shot = QLabel('Henüz görüntü alınmadı.')
        self.lbl_shot.setAlignment(Qt.AlignCenter)
        self.lbl_shot.setMinimumSize(150, 120)
        self.lbl_shot.setMaximumHeight(240)
        self.lbl_shot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.lbl_shot.setStyleSheet(
            'border: 1px solid {}; border-radius: 6px;'.format(kit.colors(self)['border']))
        self.lbl_shot.setScaledContents(False)
        shot_layout.addWidget(self.lbl_shot)
        shot_row = QHBoxLayout()
        shot_row.setSpacing(6)
        self.btn_shot = QPushButton('Görüntü Al')
        self.btn_shot.setProperty('role', 'primary')
        self.btn_shot.clicked.connect(self._screenshot)
        self.chk_hd = kit.CheckBox('HD')
        self.chk_hd.setToolTip(
            'Fiziksel ekran yakalama; çözünürlük cihaz tarafından belirlenir')
        self.chk_hd.setChecked(self.core.config.screenshot_hd)
        self.chk_hd.toggled.connect(self._on_hd_toggle)
        self.btn_shot_open = QPushButton('Klasörü Aç')
        self.btn_shot_open.setProperty('role', 'secondary')
        self.btn_shot_open.clicked.connect(self._open_shot_dir)
        shot_row.addWidget(self.btn_shot)
        shot_row.addWidget(self.chk_hd)
        shot_row.addWidget(self.btn_shot_open)
        shot_layout.addLayout(shot_row)
        self.btn_shot_save = QPushButton('Görüntüyü Kaydet…')
        self.btn_shot_save.setProperty('role', 'secondary')
        self.btn_shot_save.setEnabled(False)
        self.btn_shot_save.clicked.connect(self._save_shot)
        shot_layout.addWidget(self.btn_shot_save)
        tv_settings = self._key_button('TV Ayarları', 176, min_h=38, role='quiet')
        tv_settings.setToolTip('TV ayarlarını aç (key 176)')
        shot_layout.addWidget(tv_settings)
        aux_row.addWidget(shot_card, 1)
        content_row.addLayout(aux_row, 2)
        root.addLayout(content_row)

        device_card = QGroupBox('Cihaz İşlemleri')
        device_layout = QVBoxLayout(device_card)
        device_layout.setSpacing(8)
        flow = FlowLayout()
        self.btn_info = QPushButton('Cihaz Bilgisi')
        self.btn_info.setProperty('role', 'secondary')
        self.btn_info.clicked.connect(self._device_info)
        self.btn_reboot = QPushButton('Yeniden Başlat')
        self.btn_reboot.setProperty('role', 'secondary')
        self.btn_reboot.clicked.connect(self._reboot)
        self.cmb_reboot = QComboBox()
        self.cmb_reboot.addItems(['Sistem', 'Recovery', 'Bootloader'])
        self.btn_cache = QPushButton('Önbelleği Temizle')
        self.btn_cache.setProperty('role', 'secondary')
        self.btn_cache.clicked.connect(self._trim_caches)
        self.btn_apk = QPushButton('APK Kur')
        self.btn_apk.setProperty('role', 'secondary')
        self.btn_apk.clicked.connect(self._install_apk)
        self.btn_apks = QPushButton('Split APK Kur')
        self.btn_apks.setProperty('role', 'secondary')
        self.btn_apks.clicked.connect(self._install_apks)
        self.btn_sleep = QPushButton('Uyut')
        self.btn_sleep.setProperty('role', 'secondary')
        self.btn_sleep.clicked.connect(lambda: self._send_key(KEYCODE_SLEEP, 'Uyku'))
        self.btn_wake = QPushButton('Uyandır')
        self.btn_wake.setProperty('role', 'secondary')
        self.btn_wake.clicked.connect(lambda: self._send_key(KEYCODE_WAKEUP, 'Uyan'))
        for button in (self.btn_info, self.btn_reboot, self.cmb_reboot, self.btn_sleep,
                       self.btn_wake, self.btn_cache, self.btn_apk, self.btn_apks):
            flow.addWidget(button)
        device_layout.addLayout(flow)
        root.addWidget(device_card)
        root.addStretch()

    def apply_theme(self):
        """Tema degisince: ipucu/durum etiketleri + cerceve yeni palete gecer."""
        try:
            dark = kit.dark_from(self)
            self.lbl_text_hint.setStyleSheet(kit.faint(dark))
            self.lbl_key_hint.setStyleSheet(kit.faint(dark))
            self.lbl_status.setStyleSheet(kit.muted(dark))
            self.lbl_shot.setStyleSheet('border: 1px solid {}; border-radius: 6px;'.format(kit.colors(self)['border']))
        except (RuntimeError, AttributeError):
            pass

    def _pad_btn(self, layout, label, code, r, c, accent=False, tooltip=''):
        b = QPushButton(label)
        b.setObjectName('remoteKey')
        b.setFixedSize(52, 52)
        b.setStyleSheet('border-radius: 18px; padding: 0;')
        b.setProperty('role', 'primary' if accent else 'secondary')
        if tooltip:
            b.setToolTip(tooltip)
        f = b.font()
        f.setBold(True)
        f.setPointSize(13)
        b.setFont(f)
        names = {19: 'Yukarı', 20: 'Aşağı', 21: 'Sol', 22: 'Sağ', 23: 'OK'}
        self._bind_key(b, code, names.get(code, label))
        layout.addWidget(b, r, c)

    def _on_hd_toggle(self, on):
        self.core.config.screenshot_hd = bool(on)
        self.core.config.save()

    def populate_apps(self, apps):
        """AppsTab taramasindan sonra cagrilir."""
        cur_text = self.cmb_app.currentText()
        cur_index = self.cmb_app.currentIndex()
        cur_item = self.cmb_app.itemText(cur_index) if cur_index >= 0 else ''
        cur_pkg = (self.cmb_app.itemData(cur_index)
                   if cur_index >= 0 and cur_text.strip() == cur_item.strip() else None)
        self.cmb_app.blockSignals(True)
        self.cmb_app.clear()
        for a in apps:
            if not a.get('installed_user0', True):
                continue
            pkg = a['package']
            name = a.get('name') or a.get('label') or pkg
            self.cmb_app.addItem('{}  ({})'.format(name, pkg), pkg)
        restored = False
        if cur_pkg:
            for i in range(self.cmb_app.count()):
                if self.cmb_app.itemData(i) == cur_pkg:
                    self.cmb_app.setCurrentIndex(i)
                    restored = True
                    break
        if not restored and cur_text:
            self.cmb_app.setCurrentIndex(-1)
            self.cmb_app.setEditText(cur_text)
        self.cmb_app.blockSignals(False)

    def _load_installed_apps(self):
        if not self.core.connected or not self.core.target:
            self.lbl_status.setText('Önce cihaza bağlanın.')
            return
        apps_tab = getattr(self.window, 'tab_apps', None)
        if apps_tab is None:
            self.lbl_status.setText('Uygulama listesi açılamadı.')
            return
        if getattr(apps_tab, '_busy', False):
            self.lbl_status.setText('Uygulama taraması sürüyor; bitince liste güncellenecek.')
            return

        self._apps_load_generation += 1
        generation = self._apps_load_generation
        target = self.core.target
        self._set_apps_loading(True)
        self.lbl_status.setText('Yüklü uygulamalar taranıyor…')

        def current():
            return (generation == self._apps_load_generation
                    and self.core.connected and self.core.target == target)

        def loaded(_apps):
            if not current():
                return
            self._set_apps_loading(False)
            count = self.cmb_app.count()
            self.lbl_status.setText(
                '{} yüklü uygulama listelendi.'.format(count)
                if count else 'Yüklü uygulama bulunamadı.')

        def failed(error):
            if not current():
                return
            self._set_apps_loading(False)
            self.lbl_status.setText('Uygulamalar yüklenemedi: {}'.format(error))

        started = apps_tab.refresh(on_done=loaded, on_fail=failed)
        if not started and current() and not self.btn_load_apps.isEnabled():
            self._set_apps_loading(False)
            self.lbl_status.setText('Uygulama taraması başlatılamadı.')

    def _set_apps_loading(self, loading):
        self.btn_load_apps.setEnabled(not loading)
        self.btn_load_apps.setText('Yükleniyor…' if loading else 'Yüklüleri Yükle')
        self.cmb_app.setEnabled(not loading)

    # ------------------------------------------------------------------
    def _send_key(self, code, label, target=None, longpress=False):
        # Hizli tik yagmurunda ADB kuyrugu siser; kisa kilit + desc log.
        if self._busy:
            return
        if not self.core.connected:
            self.lbl_status.setText('Önce cihaza bağlanın.')
            return
        target = self.core.target if target is None else target
        self._busy = True

        def do():
            if longpress:
                self.core.engine.keyevent(target, code, longpress=True)
            else:
                self.core.engine.keyevent(target, code)
            return label + (' · uzun basış' if longpress else '')
        w = Worker(do)
        w.job_name = 'Tus: ' + str(label)
        w.finished_ok.connect(self._key_done)
        w.failed.connect(self._key_failed)
        self.window._run(w)

    def _key_failed(self, _error):
        self._busy = False
        self._stop_hold()
        self.lbl_status.setText('Tuş gönderilemedi. Bağlantıyı kontrol edin.')

    def _key_done(self, label):
        self._busy = False
        try:
            self.lbl_status.setText('Basılı tutuluyor: ' + str(label) if self._held else 'Son tuş: ' + str(label))
        except RuntimeError:
            pass
        pending = self._pending_ok
        self._pending_ok = None
        if pending and self.core.connected and self.core.target == pending[2]:
            self._send_key(pending[0], pending[1], target=pending[2], longpress=pending[3])

    def _send_text(self):
        t = self.txt_input.text()
        if not t:
            return

        def do():
            self.core.engine.input_text(self.core.target, t)
            return t
        from ..adb_engine import sanitize_input_text
        safe = sanitize_input_text(t)
        if safe != t.replace(' ', '%s'):
            self.lbl_text_hint.setText('(temizlendi)')
        else:
            self.lbl_text_hint.setText('')
        w = Worker(do)
        w.finished_ok.connect(lambda m: self.lbl_status.setText('Metin gonderildi: ' + m))
        self.window._run(w)
        self.txt_input.clear()

    def _launch_selected(self):
        from .dialogs import pkg_lines
        index = self.cmb_app.currentIndex()
        selected_text = self.cmb_app.currentText().strip()
        item_text = self.cmb_app.itemText(index).strip() if index >= 0 else ''
        pkg = (self.cmb_app.itemData(index)
               if index >= 0 and selected_text == item_text else None)
        if not pkg:
            typed = self.cmb_app.currentText().strip()
            # "Ad (paket)" veya direkt paket girilmis olabilir
            if '(' in typed and ')' in typed:
                pkg = typed.rsplit('(', 1)[-1].rstrip(') ').strip()
            else:
                pkg = typed
        if not pkg:
            QMessageBox.information(self, 'Uygulama', 'Önce Uygulamalar sekmesinden liste yenileyin.')
            return
        try:
            name = self.core.config.friendly_name(pkg)
        except Exception:
            name = pkg
        shown = pkg_lines([pkg], lambda _p: name)[0]
        if QMessageBox.question(self, 'Aç', u'Açılsın mı?\n\n{}'.format(shown),
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return

        def do():
            self.core.engine.launch_resolved(self.core.target, pkg)
            return pkg
        w = Worker(do)
        w.job_name = 'Uygulama acma'
        w.finished_ok.connect(lambda p: self.lbl_status.setText('Açıldı: ' + p))
        self.window._run(w, desc='Kumanda: uygulama aciliyor: ' + pkg)

    # ------------------------------------------------------------------
    def _device_info(self):
        w = DeviceInfoWorker(self.core.engine, self.core.target)
        w.finished_ok.connect(self._show_info)
        self.window._run(w)

    def _show_info(self, info):
        txt = (
            'Model:      {model}\n'
            'Marka:      {brand}\n'
            'Isim:       {name}\n'
            'Android:    {release}  (SDK {sdk})\n'
            'Build:      {display}\n'
            'Parmak izi: {fingerprint}\n'
            'Donanim:    {device}\n'
            'Toplam RAM: {mem} kB\n'
            'Ekran:      {screen}\n'
            'Depolama (/data): {disk}\n'
            'Pil:        {batt}\n'
            'Wi-Fi:      {ssid} ({ip})\n'
            'Uptime:     {up}'
        ).format(
            model=info.get('ro.product.model', '?'),
            brand=info.get('ro.product.brand', '?'),
            name=info.get('ro.product.name', '?'),
            release=info.get('ro.build.version.release', '?'),
            sdk=info.get('ro.build.version.sdk', '?'),
            display=info.get('ro.build.display.id', '?'),
            fingerprint=info.get('ro.build.fingerprint', '?'),
            device=info.get('ro.product.device', '?'),
            mem=info.get('mem_total_kb', '?'),
            screen=info.get('screen', '?'),
            disk=info.get('disk_data', '?'),
            batt=info.get('battery', '?'),
            ssid=info.get('wifi_ssid', '?'),
            ip=info.get('wifi_ip', '?'),
            up=info.get('uptime', '?'),
        )
        QMessageBox.information(self, 'Cihaz Bilgileri', txt)

    def _screenshot(self):
        if self._shot_busy:
            self.lbl_status.setText('Görüntü alınıyor; bitmesini bekleyin.')
            return
        if getattr(self.window, '_connection_busy', False):
            self.lbl_status.setText('Bağlantı işlemi sürüyor; bitince yeniden deneyin.')
            return
        target = getattr(self.core, 'target', None)
        if not getattr(self.core, 'connected', False) or not target:
            self.lbl_status.setText('Ekran görüntüsü için önce cihaza bağlanın.')
            return
        try:
            eng = self.core.engine
        except Exception as exc:
            self.lbl_status.setText('ADB motoru açılamadı: {}'.format(exc))
            return

        hd = self.chk_hd.isChecked()
        self._shot_generation += 1
        generation = self._shot_generation
        self._shot_data_generation = None
        self._shot_target = None
        self._shot_data = None
        self._shot_pixmap = None
        self.btn_shot_save.setEnabled(False)
        self.btn_shot.setEnabled(False)
        self.lbl_shot.setPixmap(QPixmap())
        self.lbl_shot.setText('Görüntü alınıyor…')
        mode = 'HD' if hd else 'standart'
        self.lbl_status.setText('{} görüntü alınıyor · {}'.format(mode, target))

        def do():
            def check_request():
                worker.check_cancel()
                if (generation != self._shot_generation or
                        getattr(self.window, '_connection_busy', False) or
                        not getattr(self.core, 'connected', False) or
                        getattr(self.core, 'target', None) != target):
                    worker.cancel()
                    raise CancelledError('Ekran görüntüsü hedefi veya bağlantısı değişti.')

            check_request()
            # ADB remains available while an Android TV display sleeps. Wake it
            # before capture so the user gets a live frame when the panel was off.
            wake = getattr(eng, 'wakeup', None)
            if callable(wake):
                try:
                    wake(target)
                    time.sleep(0.65)
                except Exception:
                    pass
            check_request()
            hd_error = ''
            used_hd = False
            if hd:
                try:
                    capture_with_info = getattr(eng, 'screenshot_hd_with_info', None)
                    if callable(capture_with_info):
                        data, used_hd = capture_with_info(target, check_cancel=check_request)
                    else:
                        data = eng.screenshot_hd(target)
                        used_hd = True
                except Exception as exc:
                    check_request()
                    hd_error = str(exc)
                    data = eng.screenshot(target)
            else:
                data = eng.screenshot(target)
            check_request()
            if not data or data[1:4] != b'PNG':
                raise RuntimeError('Ekran görüntüsü bozuk indi (PNG imzası yok).')
            foreground = ''
            try:
                if self._looks_like_black_image(QImage.fromData(data)):
                    check_request()
                    get_foreground = getattr(eng, 'foreground_package', None)
                    if callable(get_foreground):
                        foreground = get_foreground(target) or ''
            except Exception:
                pass
            check_request()
            return {'data': bytes(data), 'target': target, 'generation': generation,
                    'hd_requested': hd, 'hd_used': used_hd, 'hd_error': hd_error,
                    'foreground_package': foreground}

        worker = Worker(do)
        worker.job_name = 'Ekran görüntüsü'
        worker.capture_generation = generation
        self._shot_worker = worker
        self._shot_busy = True
        worker.finished_ok.connect(self._screenshot_done)
        worker.failed.connect(lambda error: self._screenshot_failed(
            error, generation, target, hd))
        worker.finished.connect(lambda: self._screenshot_worker_finished(worker, generation))
        try:
            self.window._run(
                worker, desc='Kumanda: {} ekran görüntüsü alınıyor · {}'.format(mode, target))
        except Exception:
            self._screenshot_worker_finished(worker, generation)
            self._clear_shot('Görüntü alınamadı; yeniden deneyin.')
            raise

    def _capture_is_current(self, generation, target):
        return (generation == self._shot_generation and
                target == getattr(self.core, 'target', None) and
                getattr(self.core, 'connected', False) and
                not getattr(self.window, '_connection_busy', False))

    def _clear_shot(self, message=None):
        self._shot_target = None
        self._shot_data_generation = None
        self._shot_data = None
        self._shot_pixmap = None
        try:
            self.btn_shot_save.setEnabled(False)
            self.lbl_shot.setPixmap(QPixmap())
            self.lbl_shot.setText(message or 'Henüz görüntü alınmadı.')
        except RuntimeError:
            pass

    def _screenshot_done(self, result):
        generation = result.get('generation')
        target = result.get('target')
        if (generation != self._shot_generation or
                target != getattr(self.core, 'target', None)):
            return
        if (not getattr(self.core, 'connected', False) or
                getattr(self.window, '_connection_busy', False)):
            self._screenshot_failed('Bağlantı değişti; yeni görüntü alın.',
                                    generation, target, result.get('hd_requested', False))
            return
        data = result.get('data')
        pixmap = QPixmap()
        try:
            decoded = bool(data) and pixmap.loadFromData(data) and not pixmap.isNull()
        except Exception as exc:
            self._screenshot_failed('PNG çözümlenemedi: {}'.format(exc), generation, target,
                                    result.get('hd_requested', False))
            return
        if not decoded:
            self._screenshot_failed('PNG görüntüsü çözümlenemedi.', generation, target,
                                    result.get('hd_requested', False))
            return

        self._shot_target = target
        self._shot_data_generation = generation
        self._shot_data = bytes(data)
        self._shot_pixmap = pixmap
        self._fit_shot()
        if result.get('hd_used'):
            capture_mode = 'HD isteği'
        elif result.get('hd_requested'):
            capture_mode = 'standart (HD isteği kullanılamadı)'
        else:
            capture_mode = 'standart'
        resolution = '{}×{}'.format(pixmap.width(), pixmap.height())
        if self._looks_like_black_screenshot(pixmap):
            foreground = result.get('foreground_package') or ''
            try:
                app_name = self.core.config.friendly_name(foreground) if foreground else ''
            except Exception:
                app_name = foreground
            app_detail = ' Ön planda {} var.'.format(app_name) if app_name else ''
            self.lbl_status.setText(
                'Görüntü alındı ancak ekran siyah.{} Video veya korumalı görüntü yüzeyleri '
                'Android tarafından yakalamadan çıkarılabilir; uygulamanın menüsüne dönüp '
                'yeniden deneyin. ({} · {} · {})'.format(
                    app_detail, resolution, capture_mode, target))
        else:
            self.lbl_status.setText(
                'Görüntü alındı · {} · {} · {}'.format(resolution, capture_mode, target))

    @staticmethod
    def _looks_like_black_screenshot(pixmap):
        """Flag only very dark, nearly uniform captures as a possible black screen."""
        return RemoteTab._looks_like_black_image(pixmap.toImage())

    @staticmethod
    def _looks_like_black_image(image):
        if image.isNull():
            return False
        sample = image.scaled(
            QSize(32, 18), Qt.IgnoreAspectRatio, Qt.FastTransformation)
        sample = sample.convertToFormat(QImage.Format.Format_RGB32)
        brightness = []
        for y in range(sample.height()):
            for x in range(sample.width()):
                color = sample.pixelColor(x, y)
                brightness.append(max(color.red(), color.green(), color.blue()))
        return (bool(brightness) and max(brightness) < 24 and
                max(brightness) - min(brightness) <= 3)

    def _screenshot_worker_finished(self, worker, generation):
        if worker is not self._shot_worker:
            return
        self._shot_worker = None
        self._shot_busy = False
        try:
            self.btn_shot.setEnabled(True)
            self.btn_shot_save.setEnabled(bool(
                self._shot_data and self._capture_is_current(
                    self._shot_data_generation, self._shot_target)))
        except RuntimeError:
            pass

    def _screenshot_failed(self, error, generation, target, hd):
        if (generation != self._shot_generation or
                target != getattr(self.core, 'target', None)):
            return
        self._clear_shot('Görüntü alınamadı; yeniden deneyin.')
        self.lbl_status.setText('{} görüntü alınamadı · {}: {}'.format(
            'HD' if hd else 'Standart', target, error))

    def _save_shot(self):
        data = self._shot_data
        target = self._shot_target
        generation = self._shot_data_generation
        if self._shot_busy:
            self.lbl_status.setText('Görüntü hazırlanıyor; bitmesini bekleyin.')
            return
        if not data or not target:
            self.lbl_status.setText('Önce yeni bir ekran görüntüsü alın.')
            return
        if not self._capture_is_current(generation, target):
            self._shot_generation += 1
            self._clear_shot('Hedef veya bağlantı değişti; yeni görüntü alın.')
            self.lbl_status.setText('Görüntü kaydedilmedi; hedef veya bağlantı değişti.')
            return

        try:
            os.makedirs(SHOT_DIR, exist_ok=True)
            initial = os.path.join(
                SHOT_DIR, 'mibox-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '.png')
            path, _ = QFileDialog.getSaveFileName(
                self, 'Ekran Görüntüsünü Kaydet', initial, 'PNG görüntüsü (*.png)',
                options=QFileDialog.Option.DontConfirmOverwrite)
        except OSError as exc:
            self.lbl_status.setText('Görüntü kaydedilemedi: {}'.format(exc))
            QMessageBox.critical(self, 'Hata', str(exc))
            return
        if not path:
            return
        if (not self._capture_is_current(generation, target) or
                self._shot_data is not data or self._shot_data_generation != generation):
            self._shot_generation += 1
            self._clear_shot('Hedef veya bağlantı değişti; yeni görüntü alın.')
            self.lbl_status.setText('Görüntü kaydedilmedi; hedef veya bağlantı değişti.')
            return
        if not path.lower().endswith('.png'):
            path += '.png'
        try:
            path = os.path.abspath(path)
            if os.path.exists(path):
                answer = QMessageBox.question(
                    self, 'Dosya zaten var',
                    'Bu dosyanın üzerine yazılsın mı?\n\n{}'.format(path),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    self.lbl_status.setText('Görüntü kaydetme iptal edildi.')
                    return
                if (not self._capture_is_current(generation, target) or
                        self._shot_data is not data or self._shot_data_generation != generation):
                    self._shot_generation += 1
                    self._clear_shot('Hedef veya bağlantı değişti; yeni görüntü alın.')
                    self.lbl_status.setText('Görüntü kaydedilmedi; hedef veya bağlantı değişti.')
                    return
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'wb') as f:
                f.write(data)
            self.lbl_status.setText('Kaydedildi: ' + path)
        except OSError as e:
            self.lbl_status.setText('Görüntü kaydedilemedi: {}'.format(e))
            QMessageBox.critical(self, 'Hata', str(e))

    def _fit_shot(self):
        """Kayitli goruntuyu etiket boyutuna sigdir (orani koru)."""
        try:
            if self._shot_pixmap is None or self._shot_pixmap.isNull():
                return
            size = self.lbl_shot.size()
            if size.width() < 10 or size.height() < 10:
                size = self.lbl_shot.minimumSize()
            self.lbl_shot.setPixmap(self._shot_pixmap.scaled(
                size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except RuntimeError:
            pass
        except Exception:
            pass

    def resizeEvent(self, e):
        if hasattr(self, '_content_row'):
            available = self.parentWidget().width() if self.parentWidget() is not None else self.width()
            self._content_row.setDirection(
                QBoxLayout.TopToBottom if available < 850 else QBoxLayout.LeftToRight)
        # pencere boyutu degisince onizlemeyi yeniden sigdir
        try:
            self._fit_shot()
        except Exception:
            pass
        super().resizeEvent(e)

    def _open_shot_dir(self):
        try:
            os.makedirs(SHOT_DIR, exist_ok=True)
            os.startfile(SHOT_DIR)
        except OSError as e:
            QMessageBox.critical(self, 'Hata', str(e))

    def _reboot(self):
        mode = self.cmb_reboot.currentText()
        extra = None
        if mode == 'Bootloader':
            extra = ('DIKKAT: Bootloader\'dan TV kendi kendine donmeyebilir; '
                     'fiziksel erisim gerekebilir.')
        body = u'Cihaz yeniden başlatılsın mı ({})?'.format(mode)
        if extra:
            body += u'\n\n' + extra
        if QMessageBox.question(self, u'Onay — Yeniden Başlat', body,
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return

        def do():
            eng = self.core.engine
            if mode == 'Recovery':
                eng.reboot_recovery(self.core.target)
            elif mode == 'Bootloader':
                eng.reboot_bootloader(self.core.target)
            else:
                eng.reboot(self.core.target)
        w = Worker(do)
        w.finished_ok.connect(lambda _: self.lbl_status.setText('Cihaz yeniden baslatiliyor...'))
        self.window._run(w)

    def _trim_caches(self):
        w = Worker(lambda: self.core.engine.trim_caches(self.core.target))
        w.finished_ok.connect(lambda _: self.lbl_status.setText('Önbelleği temizlendi.'))
        self.window._run(w)

    def _install_apk(self):
        path, _ = QFileDialog.getOpenFileName(self, 'APK Seç', '', 'APK dosyalari (*.apk)')
        if not path:
            return
        base = os.path.basename(path)
        if QMessageBox.question(self, u'Onay — APK Kur',
                                u'Kurulsun mu?\n\n• {}'.format(base),
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        w = Worker(lambda: self.core.engine.install_apk(self.core.target, path))
        w.job_name = 'APK kurma'
        w.finished_ok.connect(self._apk_done)
        self.window._run(w, desc='Kumanda: APK kuruluyor: ' + base)

    def _apk_done(self, _res=None):
        try:
            self.lbl_status.setText('APK kuruldu.')
        except RuntimeError:
            pass
        try:
            self.window.tab_apps.refresh()
        except Exception:
            pass
        QMessageBox.information(self, 'Tamam', 'APK kuruldu; uygulama listesi yenilendi.')

    def _install_apks(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Split APK Seç (base + splitler)', '', 'APK (*.apk)')
        if not paths:
            return
        if QMessageBox.question(
                self, u'Onay — Split APK Kur',
                u'{} dosya kurulsun mu?\n\n{}'.format(
                    len(paths), '\n'.join(u'• ' + os.path.basename(p) for p in paths[:8]) +
                    (u'\n… ve {} tane daha'.format(len(paths) - 8) if len(paths) > 8 else '')),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes:
            return
        w = Worker(lambda: self.core.engine.install_apks(self.core.target, list(paths)))
        w.job_name = 'Split APK kurma'
        w.finished_ok.connect(lambda _: self._apk_done())
        self.window._run(w, desc='Kumanda: split APK kuruluyor ({} dosya)'.format(len(paths)))
