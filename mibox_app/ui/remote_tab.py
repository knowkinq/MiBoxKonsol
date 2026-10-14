# -*- coding: utf-8 -*-
"""Kumanda sekmesi: ADB keyevent tabanlı büyük, ergonomik uzaktan kumanda ve TV kontrolleri."""
import os
import time

from PySide6.QtCore import Qt, QTimer, QEvent, Signal, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QPushButton, QLineEdit, QComboBox, QMessageBox,
    QFileDialog, QApplication, QBoxLayout, QSizePolicy, QFrame
)

from ..adb_engine import KEYCODE_POWER, KEYCODE_SLEEP, KEYCODE_WAKEUP, sanitize_input_text
from ..workers import Worker, DeviceInfoWorker
from . import kit


class RemoteTab(QWidget):
    """Büyük tuşlu, modern TV uzaktan kumandası ve hızlı uygulama/araç yönetim paneli."""

    REPEAT_KEYS = frozenset((19, 20, 21, 22, 24, 25, 67, 90, 91, 166, 167))

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
        self._apps_load_generation = 0
        self._build()
        self.core.connection_changed.connect(self._connection_changed)
        QApplication.instance().installEventFilter(self)

    # ------------------------------------------------------------------
    # Tuş Bağlama ve Basılı Tutma (Hold / Repeat) Mantığı
    # ------------------------------------------------------------------
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
            self._hold_timer.start(150)
            return
        self._send_key(held[1], held[2], target=held[3], longpress=held[1] == 23)
        if held[1] == 23:
            self._stop_hold()
        else:
            self._hold_timer.start(150)

    def eventFilter(self, obj, event):
        try:
            if self._held is not None and obj is self._held[0]:
                if event.type() == QEvent.FocusOut:
                    self._stop_hold()
                elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                    pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
                    self._release_key(obj, activate=obj.rect().contains(pos))
                elif event.type() == QEvent.KeyRelease and event.key() == Qt.Key_Space and not event.isAutoRepeat():
                    self._release_key(obj)
            if event.type() == QEvent.ApplicationDeactivate or (
                    event.type() == QEvent.WindowDeactivate and obj is self.window):
                self._stop_hold()
            return super().eventFilter(obj, event)
        except RuntimeError:
            return False

    def closeEvent(self, event):
        try:
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
        except Exception:
            pass
        self._stop_hold()
        super().closeEvent(event)

    def hideEvent(self, event):
        self._stop_hold()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self.core, 'connected', False) and getattr(self.core, 'target', None):
            if self.cmb_app.count() == 0 and not getattr(self, '_apps_loading', False):
                QTimer.singleShot(300, self._load_installed_apps)

    def _connection_changed(self, connected=False, target=None):
        self._stop_hold()
        self._apps_load_generation += 1
        self._set_apps_loading(False)
        if getattr(self.core, 'connected', False) and getattr(self.core, 'target', None):
            self.lbl_status.setText('Bağlandı. Komut göndermeye hazır.')
            if self.isVisible():
                QTimer.singleShot(400, self._load_installed_apps)
        else:
            self.lbl_status.setText('Cihaz bağlı değil.')

    # ------------------------------------------------------------------
    # Tuş Oluşturucular
    # ------------------------------------------------------------------
    def _key_btn(self, label, code, height=44, role='secondary', tooltip='', custom_style=None):
        b = QPushButton(label)
        b.setFixedHeight(height)
        b.setProperty('role', role)
        if custom_style:
            b.setStyleSheet(custom_style)
        if tooltip:
            b.setToolTip(tooltip)
        self._bind_key(b, code, label)
        return b

    def _style_arrow(self, b, dark):
        if dark:
            b.setStyleSheet('''
                QPushButton#dpadArrow {
                    min-width: 50px; max-width: 50px;
                    min-height: 50px; max-height: 50px;
                    border-radius: 25px;
                    padding: 0px; margin: 0px;
                    background-color: #252933;
                    color: #ffffff;
                    border: 1px solid #454c5c;
                    font-size: 20px;
                    font-weight: bold;
                }
                QPushButton#dpadArrow:hover { background-color: #373c60; border-color: #64748b; }
                QPushButton#dpadArrow:pressed { background-color: #1d2029; }
            ''')
        else:
            b.setStyleSheet('''
                QPushButton#dpadArrow {
                    min-width: 50px; max-width: 50px;
                    min-height: 50px; max-height: 50px;
                    border-radius: 25px;
                    padding: 0px; margin: 0px;
                    background-color: #ffffff;
                    color: #1e293b;
                    border: 1px solid #cbd5e1;
                    font-size: 20px;
                    font-weight: bold;
                }
                QPushButton#dpadArrow:hover { background-color: #f1f5f9; border-color: #94a3b8; }
                QPushButton#dpadArrow:pressed { background-color: #e2e8f0; }
            ''')

    def _make_ok_btn(self, parent):
        b = QPushButton('OK', parent)
        b.setObjectName('dpadOk')
        b.setGeometry(74, 74, 72, 72)
        b.setStyleSheet('''
            QPushButton#dpadOk {
                min-width: 72px; max-width: 72px;
                min-height: 72px; max-height: 72px;
                border-radius: 36px;
                padding: 0px; margin: 0px;
                background-color: #2563eb;
                color: #ffffff;
                border: 2px solid #60a5fa;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton#dpadOk:hover { background-color: #1d4ed8; border-color: #93c5fd; }
            QPushButton#dpadOk:pressed { background-color: #1e40af; border-color: #bfdbfe; }
        ''')
        b.setToolTip('OK (key 23)')
        self._bind_key(b, 23, 'OK')
        return b

    def _make_arrow_btn(self, parent, label, code, name, x, y):
        b = QPushButton(label, parent)
        b.setObjectName('dpadArrow')
        b.setGeometry(x, y, 50, 50)
        b.setToolTip('{} (key {})'.format(name, code))
        try:
            dark = kit.dark_from(self)
        except Exception:
            dark = getattr(self.core.config, 'dark_mode', False)
        self._style_arrow(b, dark)
        self._bind_key(b, code, name)
        if not hasattr(self, '_arrow_buttons'):
            self._arrow_buttons = []
        self._arrow_buttons.append(b)
        return b

    # ------------------------------------------------------------------
    # Arayüz Yapısı
    # ------------------------------------------------------------------
    def _build_remote_box(self):
        """Büyük, konforlu ve ergonomik TV uzaktan kumandası."""
        remote_box = QGroupBox('Uzaktan Kumanda')
        remote_box.setFixedWidth(340)
        remote_box.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                border: 2px solid rgba(100, 116, 139, 0.25);
                border-radius: 16px;
                margin-top: 10px;
                padding-top: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top center;
                padding: 0 10px;
            }
        """)
        rl = QVBoxLayout(remote_box)
        rl.setContentsMargins(12, 10, 12, 10)
        rl.setSpacing(7)

        # 1. Güç Kontrolleri
        p_row = QHBoxLayout()
        p_row.setSpacing(8)
        p_row.addWidget(self._key_btn(
            '⏻ Güç', KEYCODE_POWER, height=44,
            custom_style='font-size: 13px; font-weight: bold; background: #ef4444; color: white; border-radius: 8px;',
            tooltip='Güç aç/kapat (key {})'.format(KEYCODE_POWER)), 1)
        p_row.addWidget(self._key_btn(
            '☾ Uyku', KEYCODE_SLEEP, height=44, role='secondary',
            tooltip='Uyku modu (key {})'.format(KEYCODE_SLEEP)), 1)
        p_row.addWidget(self._key_btn(
            '☼ Uyan', KEYCODE_WAKEUP, height=44, role='secondary',
            tooltip='Cihazı uyandır (key {})'.format(KEYCODE_WAKEUP)), 1)
        rl.addLayout(p_row)

        # 2. D-Pad (Büyük Yön Gezinme Takımı)
        pad_box = QWidget()
        pad_box.setObjectName('remotePad')
        pad_box.setFixedSize(220, 220)
        pad_box.setStyleSheet('background: rgba(100, 116, 139, 0.14); border-radius: 110px;')

        self.btn_ok = self._make_ok_btn(pad_box)
        self.btn_up = self._make_arrow_btn(pad_box, '↑', 19, 'Yukarı', 85, 10)
        self.btn_down = self._make_arrow_btn(pad_box, '↓', 20, 'Aşağı', 85, 160)
        self.btn_left = self._make_arrow_btn(pad_box, '←', 21, 'Sol', 10, 85)
        self.btn_right = self._make_arrow_btn(pad_box, '→', 22, 'Sağ', 160, 85)
        rl.addWidget(pad_box, 0, Qt.AlignHCenter)

        # 3. Ana Gezinme
        nav_row = QHBoxLayout()
        nav_row.setSpacing(8)
        nav_row.addWidget(self._key_btn('↩ Geri', 4, height=44, role='secondary', tooltip='Geri (key 4)'), 1)
        nav_row.addWidget(self._key_btn(
            '⌂ Ana Ekran', 3, height=44, role='primary',
            custom_style='font-size: 13px; font-weight: bold; background: #2563eb; color: white; border-radius: 8px;',
            tooltip='Ana Ekran (key 3)'), 1)
        nav_row.addWidget(self._key_btn('☰ Menü', 82, height=44, role='secondary', tooltip='Menü (key 82)'), 1)
        rl.addLayout(nav_row)

        # 4. Ses ve Oynatma Kontrolleri
        vol_row = QHBoxLayout()
        vol_row.setSpacing(8)
        vol_row.addWidget(self._key_btn('Ses −', 25, height=44, role='secondary', tooltip='Ses Azalt (key 25)'), 1)
        vol_row.addWidget(self._key_btn(
            '⏯ Oynat / Duraklat', 85, height=44, role='primary',
            custom_style='font-size: 13px; font-weight: bold; background: #0284c7; color: white; border-radius: 8px;',
            tooltip='Oynat / Duraklat (key 85)'), 1)
        vol_row.addWidget(self._key_btn('Ses +', 24, height=44, role='secondary', tooltip='Ses Artır (key 24)'), 1)
        rl.addLayout(vol_row)

        # 5. Medya Sarma ve Durdurma
        media_row = QHBoxLayout()
        media_row.setSpacing(8)
        media_row.addWidget(self._key_btn('⏪ Geri Sar', 90, height=40, role='secondary', tooltip='Geri Sar (key 90)'), 1)
        media_row.addWidget(self._key_btn('⏹ Durdur', 86, height=40, role='secondary', tooltip='Durdur (key 86)'), 1)
        media_row.addWidget(self._key_btn('⏩ Hızlı Sar', 91, height=40, role='secondary', tooltip='Hızlı Sar (key 91)'), 1)
        rl.addLayout(media_row)

        # 6. Kanal ve Sessiz
        ch_row = QHBoxLayout()
        ch_row.setSpacing(8)
        ch_row.addWidget(self._key_btn('Kanal −', 167, height=40, role='secondary', tooltip='Kanal Azalt (key 167)'), 1)
        ch_row.addWidget(self._key_btn('🔇 Sessiz', 164, height=40, role='secondary', tooltip='Sessize Al (key 164)'), 1)
        ch_row.addWidget(self._key_btn('Kanal +', 166, height=40, role='secondary', tooltip='Kanal Artır (key 166)'), 1)
        rl.addLayout(ch_row)

        # 7. Hızlı TV Tuşları
        tv_row = QHBoxLayout()
        tv_row.setSpacing(8)
        tv_row.addWidget(self._key_btn('🗂 Son Uyg.', 187, height=38, role='secondary', tooltip='Son Uygulamalar (key 187)'), 1)
        tv_row.addWidget(self._key_btn('⚙ TV Ayar', 176, height=38, role='secondary', tooltip='TV Ayarları (key 176)'), 1)
        tv_row.addWidget(self._key_btn('📺 TV Giriş', 178, height=38, role='secondary', tooltip='TV Giriş / Kaynak (key 178)'), 1)
        rl.addLayout(tv_row)

        # 8. Durum Etiketi
        self.lbl_status = kit.status_label('Hazır · Tuşları tıklayabilir veya klavye ile kontrol edebilirsiniz.')
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setWordWrap(True)
        rl.addWidget(self.lbl_status)
        rl.addStretch()

        return remote_box

    def _build_right_column(self):
        """Sağ sütun: Uygulama başlatıcı, metin girişi, tam boyutlu Numpad ve hızlı araçlar."""
        right_col = QVBoxLayout()
        right_col.setSpacing(14)

        # --- KART 1: Uygulama ve Metin Girişi ---
        app_card = QGroupBox('Uygulama ve Metin Girişi')
        app_layout = QVBoxLayout(app_card)
        app_layout.setContentsMargins(14, 12, 14, 12)
        app_layout.setSpacing(8)

        # 1. Satır: Uygulama Seçimi
        self.cmb_app = QComboBox()
        self.cmb_app.setPlaceholderText('Uygulama seç veya paket adı yaz...')
        self.cmb_app.setEditable(True)
        if self.cmb_app.lineEdit():
            self.cmb_app.lineEdit().setPlaceholderText('Uygulama seç veya paket adı yaz...')
        self.cmb_app.setFixedHeight(36)
        self.cmb_app.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.cmb_app.minimumSizeHint = lambda: QSize(80, 36)
        app_layout.addWidget(self.cmb_app)

        # 2. Satır: Yenile ve TV'de Aç Butonları
        app_btns = QHBoxLayout()
        app_btns.setSpacing(6)

        self.btn_load_apps = QPushButton('🔄 Yenile')
        self.btn_load_apps.setFixedHeight(36)
        self.btn_load_apps.setProperty('role', 'secondary')
        self.btn_load_apps.setToolTip('Cihazdaki yüklü uygulamaları listele / yenile')
        self.btn_load_apps.clicked.connect(self._load_installed_apps)

        self.btn_launch = QPushButton('▶ TV\'de Aç')
        self.btn_launch.setFixedHeight(36)
        self.btn_launch.setProperty('role', 'primary')
        self.btn_launch.setStyleSheet('font-size: 13px; font-weight: bold; background: #2563eb; color: white; border-radius: 6px;')
        self.btn_launch.clicked.connect(self._launch_selected)

        app_btns.addWidget(self.btn_load_apps, 1)
        app_btns.addWidget(self.btn_launch, 1)
        app_layout.addLayout(app_btns)

        # 3. Satır: Metin Girişi
        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText('TV\'ye metin veya arama yaz...')
        self.txt_input.setFixedHeight(36)
        self.txt_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.txt_input.returnPressed.connect(self._send_text)
        app_layout.addWidget(self.txt_input)

        # 4. Satır: Gönder Butonu
        send_row = QHBoxLayout()
        send_row.setSpacing(6)

        send_text = QPushButton('✉ Gönder')
        send_text.setFixedHeight(36)
        send_text.setProperty('role', 'primary')
        send_text.setStyleSheet('font-size: 13px; font-weight: bold; background: #0284c7; color: white; border-radius: 6px;')
        send_text.clicked.connect(self._send_text)

        self.lbl_text_hint = kit.hint_label('')
        send_row.addWidget(send_text, 1)
        send_row.addWidget(self.lbl_text_hint)
        app_layout.addLayout(send_row)

        self.chk_key_nav = None

        # KART 2: Hızlı Cihaz Araçları
        tools_card = QGroupBox('Hızlı Cihaz Araçları')
        tools_layout = QVBoxLayout(tools_card)
        tools_layout.setContentsMargins(12, 10, 12, 10)
        tools_layout.setSpacing(6)

        self.btn_info = QPushButton('ℹ Cihaz Sistem Bilgileri')
        self.btn_info.setFixedHeight(36)
        self.btn_info.setProperty('role', 'secondary')
        self.btn_info.setStyleSheet('font-size: 13px; font-weight: bold;')
        self.btn_info.clicked.connect(self._device_info)

        reboot_row = QHBoxLayout()
        reboot_row.setSpacing(6)
        self.btn_reboot = QPushButton('🔄 Yeniden Başlat')
        self.btn_reboot.setFixedHeight(36)
        self.btn_reboot.setProperty('role', 'secondary')
        self.btn_reboot.setStyleSheet('font-size: 13px; font-weight: bold;')
        self.btn_reboot.clicked.connect(self._reboot)

        self.cmb_reboot = QComboBox()
        self.cmb_reboot.setFixedHeight(36)
        self.cmb_reboot.addItems(['Sistem', 'Recovery', 'Bootloader'])
        self.cmb_reboot.setFixedWidth(85)
        reboot_row.addWidget(self.btn_reboot, 1)
        reboot_row.addWidget(self.cmb_reboot)

        self.btn_cache = QPushButton('🧹 Tüm Önbelleği Temizle')
        self.btn_cache.setFixedHeight(36)
        self.btn_cache.setProperty('role', 'secondary')
        self.btn_cache.setStyleSheet('font-size: 13px; font-weight: bold;')
        self.btn_cache.setToolTip('Tüm uygulamaların geçici önbelleğini temizle')
        self.btn_cache.clicked.connect(self._trim_caches)

        self.btn_tv_settings = self._key_btn(
            '⚙ TV Android Ayarlarını Aç', 176, height=36, role='secondary',
            custom_style='font-size: 13px; font-weight: bold;',
            tooltip='TV ayarlarını aç (key 176)')

        tools_layout.addWidget(self.btn_info)
        tools_layout.addLayout(reboot_row)
        tools_layout.addWidget(self.btn_cache)
        tools_layout.addWidget(self.btn_tv_settings)

        # Kart 1 ve Kart 2 Yan Yana
        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addWidget(app_card, 1)
        top_row.addWidget(tools_card, 1)
        right_col.addLayout(top_row)

        # KART 3: Sayı Tuş Takımı (Numpad)
        num_card = QGroupBox('Sayı Tuş Takımı (Numpad)')
        num_layout = QGridLayout(num_card)
        num_layout.setContentsMargins(12, 10, 12, 10)
        num_layout.setSpacing(6)

        num_keys = [
            ('1', 8, 0, 0), ('2', 9, 0, 1), ('3', 10, 0, 2),
            ('4', 11, 1, 0), ('5', 12, 1, 1), ('6', 13, 1, 2),
            ('7', 14, 2, 0), ('8', 15, 2, 1), ('9', 16, 2, 2),
            ('⌫ Sil', 67, 3, 0), ('0', 7, 3, 1), ('⏺ Kayıt', 130, 3, 2),
        ]
        for lbl, kcode, r, c in num_keys:
            btn = self._key_btn(
                lbl, kcode, height=36,
                role='secondary',
                custom_style='font-size: 13px; font-weight: bold;' if lbl in ('⌫ Sil', '⏺ Kayıt') else 'font-size: 16px; font-weight: bold;',
                tooltip='Tuş: {} (key {})'.format(lbl, kcode))
            num_layout.addWidget(btn, r, c)

        right_col.addWidget(num_card)
        right_col.addStretch()

        # Geriye dönük uyumluluk referansları
        self.btn_apk = QPushButton('APK Kur')
        self.btn_apk.clicked.connect(self._install_apk)
        self.btn_apks = QPushButton('Split APK Kur')
        self.btn_apks.clicked.connect(self._install_apks)
        self.btn_sleep = QPushButton('Uyut')
        self.btn_sleep.clicked.connect(lambda: self._send_key(KEYCODE_SLEEP, 'Uyku'))
        self.btn_wake = QPushButton('Uyandır')
        self.btn_wake.clicked.connect(lambda: self._send_key(KEYCODE_WAKEUP, 'Uyan'))

        return right_col

    def _build(self):
        root = kit.page(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(12)

        content_row = QHBoxLayout()
        content_row.setSpacing(12)

        remote_box = self._build_remote_box()
        right_col = self._build_right_column()

        content_row.addWidget(remote_box, 0, Qt.AlignTop)
        content_row.addLayout(right_col, 1)
        root.addLayout(content_row)

    # ------------------------------------------------------------------
    # Tema Uyumu
    # ------------------------------------------------------------------
    def apply_theme(self):
        try:
            dark = kit.dark_from(self)
            self.lbl_text_hint.setStyleSheet(kit.faint(dark))
            self.lbl_status.setStyleSheet(kit.muted(dark))
            for b in getattr(self, '_arrow_buttons', []):
                self._style_arrow(b, dark)
        except (RuntimeError, AttributeError):
            pass

    # ------------------------------------------------------------------
    # Uygulama Doldurma ve Başlatma
    # ------------------------------------------------------------------
    def populate_apps(self, apps):
        """AppsTab taramasından sonra çağrılır."""
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
        self.btn_load_apps.setText('Yükleniyor…' if loading else '🔄 Yenile')
        self.cmb_app.setEnabled(not loading)

    # ------------------------------------------------------------------
    # Tuş ve Metin Gönderimi
    # ------------------------------------------------------------------
    def _send_key(self, code, label, target=None, longpress=False):
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
        w.job_name = 'Tuş: ' + str(label)
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

        safe = sanitize_input_text(t)
        if safe != t.replace(' ', '%s'):
            self.lbl_text_hint.setText('(temizlendi)')
        else:
            self.lbl_text_hint.setText('')
        w = Worker(do)
        w.finished_ok.connect(lambda m: self.lbl_status.setText('Metin gönderildi: ' + m))
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
            if '(' in typed and ')' in typed:
                pkg = typed.rsplit('(', 1)[-1].rstrip(') ').strip()
            else:
                pkg = typed
        if not pkg:
            QMessageBox.information(self, 'Uygulama', 'Önce listeden uygulama seçin veya adını yazın.')
            return
        try:
            name = self.core.config.friendly_name(pkg)
        except Exception:
            name = pkg
        shown = pkg_lines([pkg], lambda _p: name)[0]
        if QMessageBox.question(self, 'Aç', 'Açılsın mı?\n\n{}'.format(shown),
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return

        def do():
            self.core.engine.launch_resolved(self.core.target, pkg)
            return pkg

        w = Worker(do)
        w.job_name = 'Uygulama açma'
        w.finished_ok.connect(lambda p: self.lbl_status.setText('Açıldı: ' + p))
        self.window._run(w, desc='Kumanda: uygulama açılıyor: ' + pkg)

    # ------------------------------------------------------------------
    # Cihaz Bilgisi ve Sistem İşlemleri
    # ------------------------------------------------------------------
    def _device_info(self):
        if not self.core.connected or not self.core.target:
            self.lbl_status.setText('Önce cihaza bağlanın.')
            return
        w = DeviceInfoWorker(self.core.engine, self.core.target)
        w.finished_ok.connect(self._show_info)
        self.window._run(w)

    def _show_info(self, info):
        txt = (
            'Model:      {model}\n'
            'Marka:      {brand}\n'
            'İsim:       {name}\n'
            'Android:    {release}  (SDK {sdk})\n'
            'Build:      {display}\n'
            'Parmak izi: {fingerprint}\n'
            'Donanım:    {device}\n'
            'Toplam RAM: {mem} kB\n'
            'Ekran:      {screen}\n'
            'Depolama:   {disk}\n'
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

    def _reboot(self):
        if not self.core.connected or not self.core.target:
            self.lbl_status.setText('Önce cihaza bağlanın.')
            return
        mode = self.cmb_reboot.currentText()
        extra = None
        if mode == 'Bootloader':
            extra = ('DİKKAT: Bootloader modundan TV kendi kendine dönmeyebilir; fiziksel erişim gerekebilir.')
        body = 'Cihaz yeniden başlatılsın mı ({})?'.format(mode)
        if extra:
            body += '\n\n' + extra
        if QMessageBox.question(self, 'Onay — Yeniden Başlat', body,
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
        w.finished_ok.connect(lambda _: self.lbl_status.setText('Cihaz yeniden başlatılıyor...'))
        self.window._run(w)

    def _trim_caches(self):
        if not self.core.connected or not self.core.target:
            self.lbl_status.setText('Önce cihaza bağlanın.')
            return
        w = Worker(lambda: self.core.engine.trim_caches(self.core.target))
        w.finished_ok.connect(lambda _: self.lbl_status.setText('Tüm uygulamaların önbelleği temizlendi.'))
        self.window._run(w)

    def _on_key_nav_toggle(self, on):
        self.core.config.keyboard_nav = bool(on)
        self.core.config.save()

    def keyPressEvent(self, event):
        if getattr(self.core.config, 'keyboard_nav', True):
            key_map = {
                Qt.Key_Up: 19,
                Qt.Key_Down: 20,
                Qt.Key_Left: 21,
                Qt.Key_Right: 22,
                Qt.Key_Return: 23,
                Qt.Key_Enter: 23,
                Qt.Key_Escape: 4,
                Qt.Key_Backspace: 4,
                Qt.Key_Home: 3,
                Qt.Key_Menu: 82,
                Qt.Key_Space: 85,
                Qt.Key_0: 7,
                Qt.Key_1: 8,
                Qt.Key_2: 9,
                Qt.Key_3: 10,
                Qt.Key_4: 11,
                Qt.Key_5: 12,
                Qt.Key_6: 13,
                Qt.Key_7: 14,
                Qt.Key_8: 15,
                Qt.Key_9: 16,
            }
            code = key_map.get(event.key())
            if code is not None:
                from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QTextEdit
                focus = QApplication.focusWidget()
                if not isinstance(focus, (QLineEdit, QPlainTextEdit, QTextEdit)):
                    self._send_key(code, 'Klavye Tuşu')
                    event.accept()
                    return
        super().keyPressEvent(event)

    def resizeEvent(self, e):
        super().resizeEvent(e)

    # ------------------------------------------------------------------
    # Geriye Dönük Uyumluluk (APK Kurma vb.)
    # ------------------------------------------------------------------
    def _install_apk(self):
        path, _ = QFileDialog.getOpenFileName(self, 'APK Seç', '', 'APK dosyaları (*.apk)')
        if not path:
            return
        base = os.path.basename(path)
        if QMessageBox.question(self, 'Onay — APK Kur',
                                'Kurulsun mu?\n\n• {}'.format(base),
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
                self, 'Onay — Split APK Kur',
                '{} dosya kurulsun mu?\n\n{}'.format(
                    len(paths), '\n'.join('• ' + os.path.basename(p) for p in paths[:8]) +
                    ('\n… ve {} tane daha'.format(len(paths) - 8) if len(paths) > 8 else '')),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes:
            return
        w = Worker(lambda: self.core.engine.install_apks(self.core.target, list(paths)))
        w.job_name = 'Split APK kurma'
        w.finished_ok.connect(lambda _: self._apk_done())
        self.window._run(w, desc='Kumanda: split APK kuruluyor ({} dosya)'.format(len(paths)))
