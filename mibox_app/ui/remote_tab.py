# -*- coding: utf-8 -*-
"""Kumanda sekmesi: ADB keyevent tabanlı büyük, ergonomik uzaktan kumanda,
canlı ekran önizleme, dokunmatik etkileşim (tap/swipe), pano senkronizasyonu ve TV kontrolleri.
"""
import math
import os
import shlex
import struct
import subprocess
import sys
import time

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..adb_engine import (
    KEYCODE_POWER,
    KEYCODE_SLEEP,
    KEYCODE_WAKEUP,
    AdbError,
    sanitize_input_text,
)
from ..config import BASE_DIR
from ..scrcpy_manager import ScrcpyDownloader, find_scrcpy, launch_scrcpy
from ..workers import CancelledError, Worker
from . import kit
from .icons import line_icon


class _NoWheelComboBox(QComboBox):
    """Do not change a device setting while the containing page is scrolled."""

    def wheelEvent(self, event):
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()


def _is_complete_mp4(path):
    """Check that an MP4 has complete top-level boxes including its index."""
    try:
        file_size = os.path.getsize(path)
        if file_size < 24:
            return False
        found = set()
        offset = 0
        with open(path, 'rb') as video:
            while offset + 8 <= file_size:
                video.seek(offset)
                header = video.read(8)
                box_size = struct.unpack('>I', header[:4])[0]
                box_type = header[4:8]
                header_size = 8
                if box_size == 1:
                    extended = video.read(8)
                    if len(extended) != 8:
                        return False
                    box_size = struct.unpack('>Q', extended)[0]
                    header_size = 16
                elif box_size == 0:
                    box_size = file_size - offset
                if box_size < header_size or offset + box_size > file_size:
                    return False
                found.add(box_type)
                offset += box_size
        return offset == file_size and {b'ftyp', b'mdat', b'moov'}.issubset(found)
    except (OSError, struct.error, ValueError):
        return False


class InteractiveScreenWidget(QLabel):
    """TV ekran görüntüsünü 16:9 oranında gösteren, tıklama ve sürüklemeleri
    cihaz koordinatlarına çevirerek sinyal üreten interaktif ekran widget'ı.
    """
    tap_requested = Signal(int, int)
    swipe_requested = Signal(int, int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(240, 135)
        self.setMaximumHeight(480)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setWordWrap(True)
        self._pixmap = None
        self._press_pos = None
        self._tv_width = 1920
        self._tv_height = 1080
        self.setCursor(Qt.PointingHandCursor)
        self.setText('Ekran önizlemesi burada görünür\nTV’ye bağlanıp “Ekranı Al”ı veya “Canlı İzle”yi seçin')

    def minimumSizeHint(self):
        return QSize(240, 135)

    def sizeHint(self):
        return QSize(400, 225)

    def set_screen_image(self, pixmap, tv_w=1920, tv_h=1080):
        self._pixmap = pixmap
        if tv_w and tv_h:
            self._tv_width = tv_w
            self._tv_height = tv_h
        self.setText("")
        self._update_display()

    def clear_screen_image(self, message="TV Canlı Ekranı\n'Ekranı Al' ile görüntü yakalayın"):
        self._pixmap = None
        self.setPixmap(QPixmap())
        self.setText(message)

    def _get_displayed_rect(self):
        """Etiket alanı içindeki ölçeklenmiş resmin tam koordinatlarını döner."""
        if not self._pixmap or self._pixmap.isNull():
            return None
        w_avail = self.width() - 8
        h_avail = self.height() - 8
        scaled = self._pixmap.scaled(w_avail, h_avail, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        return scaled, x, y, scaled.width(), scaled.height()

    def _update_display(self):
        if not self._pixmap or self._pixmap.isNull():
            return
        rect_info = self._get_displayed_rect()
        if rect_info:
            scaled, _x, _y, _w, _h = rect_info
            self.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_display()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._press_pos is not None:
            release_pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
            rect_info = self._get_displayed_rect()
            if rect_info:
                _scaled, rx, ry, rw, rh = rect_info
                # Basılan ve bırakılan noktaları resim sınırlarına normalize et
                def to_tv_coord(p):
                    nx = (p.x() - rx) / float(rw)
                    ny = (p.y() - ry) / float(rh)
                    nx = max(0.0, min(1.0, nx))
                    ny = max(0.0, min(1.0, ny))
                    return int(nx * self._tv_width), int(ny * self._tv_height)

                start_x, start_y = to_tv_coord(self._press_pos)
                end_x, end_y = to_tv_coord(release_pos)

                dx = abs(release_pos.x() - self._press_pos.x())
                dy = abs(release_pos.y() - self._press_pos.y())

                if dx < 12 and dy < 12:
                    self.tap_requested.emit(start_x, start_y)
                else:
                    self.swipe_requested.emit(start_x, start_y, end_x, end_y)

            self._press_pos = None
        super().mouseReleaseEvent(event)


class RemoteTab(QWidget):
    """Büyük tuşlu, modern TV uzaktan kumandası, canlı ekran önizleme ve TV araçları."""

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
        self._volume_generation = 0
        self._connection_generation = 0
        self._vol_edit_revision = 0
        self._vol_setting = False
        self._vol_reading = False

        # Canlı Ekran Önizleme durumları
        self._live_timer = QTimer(self)
        self._live_timer.timeout.connect(self._on_live_tick)
        self._capture_busy = False
        self._capture_generation = 0
        self._last_screen_pixmap = None
        self._scrcpy_download_worker = None
        self._scrcpy_process = None
        self._scrcpy_launch_context = None
        self._scrcpy_shutdown_started = None
        self._scrcpy_kill_requested = False
        self._scrcpy_poll_timer = QTimer(self)
        self._scrcpy_poll_timer.setInterval(750)
        self._scrcpy_poll_timer.timeout.connect(self._poll_scrcpy_process)

        # Canlı Video Kaydı durumları
        self._recording_proc = None
        self._recording_timer = None
        self._recording_seconds = 0
        self._recording_target = None
        self._recording_remote_path = None
        self._recording_pid = None
        self._recording_engine = None
        self._recording_starting = False
        self._recording_finalizing = False
        self._recording_stop_requested = False
        self._recording_started_at = None

        # Uyku Zamanlayıcısı durumları
        self._sleep_timer = QTimer(self)
        self._sleep_timer.timeout.connect(self._on_sleep_timer_tick)
        self._sleep_remaining_seconds = 0
        self._sleep_target = None
        self._sleep_context = None
        self._sleep_deadline = None
        self._sleep_dispatching = False
        self._sleep_generation = 0

        self._build()
        self.core.connection_changed.connect(self._connection_changed)
        if self.window is not None:
            self.window.installEventFilter(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_responsive_layout()

    def _update_responsive_layout(self):
        if not hasattr(self, '_remote_box') or not hasattr(self, 'screen_view'):
            return
        viewport_width = max(1, self.width())
        viewport_height = max(1, self.height())
        button_width = max(
            (button.sizeHint().width() for button in self._remote_box.findChildren(QPushButton)
             if button.objectName() not in ('dpadArrow', 'dpadOk', 'btnMute')),
            default=88,
        )
        margins = self._remote_box.layout().contentsMargins()
        minimum_width = button_width * 3 + 12 + margins.left() + margins.right() + 4
        remote_width = max(310, minimum_width, min(360, int(viewport_width * 0.28)))
        self._remote_box.setFixedWidth(remote_width)
        preview_width = max(240, viewport_width - remote_width - 52)
        height_limit = max(180, viewport_height - 460)
        preview_height = min(480, height_limit, int(preview_width * 9 / 16))
        self.screen_view.setMaximumHeight(max(180, preview_height))

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
            import shiboken6
            if not shiboken6.isValid(obj):
                return False
        except Exception:
            pass

        try:
            if self._held is not None and obj is self._held[0]:
                ev_type = event.type()
                if ev_type == QEvent.FocusOut:
                    self._stop_hold()
                elif ev_type == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                    pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
                    self._release_key(obj, activate=obj.rect().contains(pos))
                elif ev_type == QEvent.KeyRelease and event.key() == Qt.Key_Space and not event.isAutoRepeat():
                    self._release_key(obj)
            ev_type = event.type()
            if ev_type in (QEvent.ApplicationDeactivate, QEvent.WindowDeactivate):
                self._stop_hold()
            return super().eventFilter(obj, event)
        except Exception:
            return False

    def closeEvent(self, event):
        try:
            self._live_timer.stop()
            if self.window is not None:
                self.window.removeEventFilter(self)
        except Exception:
            pass
        self._stop_hold()
        super().closeEvent(event)

    def hideEvent(self, event):
        self._live_timer.stop()
        if hasattr(self, 'btn_live_stream') and self.btn_live_stream.isChecked():
            self.btn_live_stream.setChecked(False)
        self._stop_hold()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self.core, 'connected', False) and getattr(self.core, 'target', None):
            if hasattr(self, '_fetch_volume'):
                QTimer.singleShot(250, self._fetch_volume)
            if self.cmb_app.count() == 0 and not getattr(self, '_apps_loading', False):
                QTimer.singleShot(300, self._load_installed_apps)

    def _connection_changed(self, connected=False, target=None):
        self._connection_generation += 1
        if self._recording_starting:
            self._recording_stop_requested = True
        self._stop_hold()
        self._busy = False
        self._pending_ok = None
        self._volume_generation += 1
        self._vol_setting = False
        self._vol_reading = False
        self._vol_debounce_timer.stop()
        self.slider_vol.setEnabled(False)
        self.lbl_vol_val.setText('— / {}'.format(self.slider_vol.maximum()))
        self._live_timer.stop()
        if hasattr(self, 'btn_live_stream'):
            self.btn_live_stream.setChecked(False)
        self._apps_load_generation += 1
        self._set_apps_loading(False)
        self._capture_generation += 1
        self._capture_busy = False
        self._last_screen_pixmap = None
        if hasattr(self, 'screen_view'):
            self.btn_save_screen.setEnabled(False)
            self.screen_view.clear_screen_image(
                'TV Canlı Ekranı\nCihaz bağlı değil' if not connected
                else 'TV Canlı Ekranı\nYeni cihazdan ekran almak için “Ekranı Al”ı seçin')
        if self._sleep_deadline is not None or self._sleep_dispatching:
            self._reset_sleep_timer('Bağlantı değişti; zamanlayıcı iptal edildi.')
        if getattr(self.core, 'connected', False) and getattr(self.core, 'target', None):
            self.lbl_status.setText('Bağlandı. Komut göndermeye hazır.')
            if hasattr(self, '_fetch_volume'):
                QTimer.singleShot(500, self._fetch_volume)
            if self.isVisible():
                QTimer.singleShot(400, self._load_installed_apps)
        else:
            self.lbl_status.setText('Cihaz bağlı değil.')
        if (self._recording_remote_path
                and (not connected or target != self._recording_target)):
            self._stop_screen_recording(show_saved_dialog=False)
        scrcpy_context = self._scrcpy_launch_context
        if (self._scrcpy_process is not None
                and (not connected or scrcpy_context is None
                     or target != scrcpy_context[1])):
            self._request_scrcpy_shutdown()

    def _capture_device_context(self):
        if (not self.core.connected or not self.core.target
                or getattr(self.window, '_connection_busy', False)):
            return None
        try:
            return self.core.engine, self.core.target, self._connection_generation
        except Exception:
            return None

    def _device_context_current(self, context):
        if context is None:
            return False
        engine, target, generation = context
        try:
            return (self._connection_generation == generation
                    and self.core.connected and self.core.target == target
                    and not getattr(self.window, '_connection_busy', False)
                    and self.core.engine is engine)
        except Exception:
            return False

    def _require_device_context(self, context):
        if not self._device_context_current(context):
            raise CancelledError('bağlantı değişti')

    def _run_device_action(self, context, action, description, on_ok=None):
        """Keep a system action and its displayed result on the captured device."""
        if context is None:
            self.lbl_status.setText('Önce cihaz bağlantısının tamamlanmasını bekleyin.')
            return
        engine, target, _generation = context
        def do():
            self._require_device_context(context)
            result = action(engine, target)
            if hasattr(result, 'ok') and not result.ok:
                raise AdbError(result.error or result.output or 'Cihaz komutu başarısız.')
            return result
        def done(result):
            if self._device_context_current(context):
                if on_ok is not None:
                    on_ok(result)
                else:
                    self.lbl_status.setText(description + ' tamamlandı.')
        self.window._run(Worker(do), on_ok=done, desc=description)

    # ------------------------------------------------------------------
    # Tuş Oluşturucular
    # ------------------------------------------------------------------
    def _key_btn(self, label, code, height=44, role='secondary', tooltip='', custom_style=None):
        b = QPushButton(label)
        b.setStyleSheet('QPushButton { padding: 2px 6px; }')
        b.setFixedHeight(height)
        b.setProperty('role', role)
        if custom_style:
            b.setStyleSheet(custom_style)
        if tooltip:
            b.setToolTip(tooltip)
        self._bind_key(b, code, label)
        return b

    def _style_arrow(self, b, dark):
        palette = kit.colors(self)
        b.setStyleSheet(f"""
            QPushButton#dpadArrow {{
                min-width: 0; min-height: 0;
                padding: 0; margin: 0; border: 1px solid transparent;
                border-radius: 20px; background: transparent;
            }}
            QPushButton#dpadArrow:hover {{ background: {palette['border']}; }}
            QPushButton#dpadArrow:pressed {{ background: {palette['accent']}; }}
            QPushButton#dpadArrow:focus {{ border: 1px solid {palette['accent']}; }}
        """)
        points = {
            19: ((16, 34), (28, 22), (40, 34)),
            20: ((16, 22), (28, 34), (40, 22)),
            21: ((34, 16), (22, 28), (34, 40)),
            22: ((22, 16), (34, 28), (22, 40)),
        }.get(b.property('keyCode'))
        if points:
            pixmap = QPixmap(56, 56)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(QColor(palette['text']), 4, Qt.SolidLine,
                                Qt.RoundCap, Qt.RoundJoin))
            painter.drawLine(QPoint(*points[0]), QPoint(*points[1]))
            painter.drawLine(QPoint(*points[1]), QPoint(*points[2]))
            painter.end()
            pixmap.setDevicePixelRatio(2)
            b.setIcon(QIcon(pixmap))
            b.setIconSize(QSize(32, 32))

    def _style_navigation_disc(self):
        palette = kit.colors(self)
        self._navigation_disc.setStyleSheet(f"""
            QWidget#navigationDisc {{
                background: transparent;
                border: 1.5px solid {palette['border']}; border-radius: 100px;
            }}
        """)
        self.btn_ok.setStyleSheet(f"""
            QPushButton#dpadOk {{
                min-width: 0; min-height: 0;
                border-radius: 36px; padding: 0; margin: 0;
                background: transparent; color: {palette['accent']};
                border: 2px solid {palette['accent']}; font-size: 15px; font-weight: 600;
            }}
            QPushButton#dpadOk:hover {{ background: {palette['accent']}; color: white; }}
            QPushButton#dpadOk:pressed {{ background: {palette['accent']}; color: white; }}
            QPushButton#dpadOk:focus {{ border-color: {palette['accent']}; }}
        """)

    def _style_remote_cards(self):
        palette = kit.colors(self)
        self.screen_view.setStyleSheet(f"""
            InteractiveScreenWidget {{
                color: {palette['muted']}; background: transparent;
                border: 1px solid {palette['border']}; border-radius: 10px;
                font-size: 11pt; font-weight: 600;
            }}
        """)
        danger = palette['danger']
        self.btn_power.setStyleSheet(f"""
            QPushButton#remotePower {{
                color: {danger}; background: transparent;
                border: 1px solid {danger}; border-radius: 8px;
                font-weight: 600; padding: 2px 6px;
            }}
        """)

    def _make_ok_btn(self, parent):
        b = QPushButton('OK', parent)
        b.setObjectName('dpadOk')
        b.setGeometry(64, 64, 72, 72)
        b.setFixedSize(72, 72)
        b.setCursor(Qt.PointingHandCursor)
        b.setAccessibleName('Tamam')
        b.setToolTip('OK (key 23)')
        self._bind_key(b, 23, 'OK')
        return b

    def _make_arrow_btn(self, parent, label, code, name, x, y):
        b = QPushButton('', parent)
        b.setAccessibleName(name)
        b.setCursor(Qt.PointingHandCursor)
        b.setObjectName('dpadArrow')
        b.setFixedSize(72 if code in (19, 20) else 56,
                       56 if code in (19, 20) else 72)
        b.move(x, y)
        b.setToolTip('{} (key {})'.format(name, code))
        try:
            dark = kit.dark_from(self)
        except Exception:
            dark = getattr(self.core.config, 'dark_mode', False)
        self._bind_key(b, code, name)
        self._style_arrow(b, dark)
        if not hasattr(self, '_arrow_buttons'):
            self._arrow_buttons = []
        self._arrow_buttons.append(b)
        return b

    # ------------------------------------------------------------------
    # Arayüz Yapısı
    # ------------------------------------------------------------------
    def _build_remote_box(self):
        """Kompakt, konforlu ve ergonomik TV uzaktan kumandası."""
        remote_box = QGroupBox('Uzaktan Kumanda')
        remote_box.setObjectName('remoteCard')
        remote_box.setMinimumWidth(260)
        remote_box.setMaximumWidth(310)
        remote_box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self._remote_box = remote_box
        rl = QVBoxLayout(remote_box)
        rl.setContentsMargins(12, 10, 12, 10)
        rl.setSpacing(7)

        # 1. Güç Kontrolleri
        p_row = QHBoxLayout()
        p_row.setSpacing(6)
        self.btn_power = self._key_btn(
            '⏻ Güç', KEYCODE_POWER, height=38, role='danger',
            tooltip='Güç aç/kapat (key {})\nSağ tık: Gelişmiş yeniden başlatma menüsü'.format(KEYCODE_POWER))
        self.btn_power.setObjectName('remotePower')
        self.btn_power.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_power.customContextMenuRequested.connect(self._power_context_menu)
        p_row.addWidget(self.btn_power, 1)
        p_row.addWidget(self._key_btn(
            '☾ Uyku', KEYCODE_SLEEP, height=38, role='secondary',
            tooltip='Uyku modu (key {})'.format(KEYCODE_SLEEP)), 1)
        p_row.addWidget(self._key_btn(
            '☼ Uyan', KEYCODE_WAKEUP, height=38, role='secondary',
            tooltip='Cihazı uyandır (key {})'.format(KEYCODE_WAKEUP)), 1)
        rl.addLayout(p_row)

        # 2. D-Pad (Yön Gezinme Takımı)
        pad_box = QWidget()
        pad_box.setObjectName('navigationDisc')
        self._navigation_disc = pad_box
        pad_box.setFixedSize(200, 200)

        self.btn_ok = self._make_ok_btn(pad_box)
        self.btn_up = self._make_arrow_btn(pad_box, '↑', 19, 'Yukarı', 64, 4)
        self.btn_down = self._make_arrow_btn(pad_box, '↓', 20, 'Aşağı', 64, 140)
        self.btn_left = self._make_arrow_btn(pad_box, '←', 21, 'Sol', 4, 64)
        self.btn_right = self._make_arrow_btn(pad_box, '→', 22, 'Sağ', 140, 64)
        self._style_navigation_disc()
        rl.addWidget(pad_box, 0, Qt.AlignHCenter)

        # 3. Ana Gezinme
        nav_row = QHBoxLayout()
        nav_row.setSpacing(6)
        nav_row.addWidget(self._key_btn('↩ Geri', 4, height=38, role='secondary', tooltip='Geri (key 4)'), 1)
        nav_row.addWidget(self._key_btn(
            '⌂ Ana Ekran', 3, height=38, role='primary',
            tooltip='Ana Ekran (key 3)'), 1)
        nav_row.addWidget(self._key_btn('☰ Menü', 82, height=38, role='secondary', tooltip='Menü (key 82)'), 1)
        rl.addLayout(nav_row)

        # 4. Ses ve Oynatma Kontrolleri
        vol_row = QHBoxLayout()
        vol_row.setSpacing(6)
        vol_row.addWidget(self._key_btn('Ses −', 25, height=38, role='secondary', tooltip='Ses Azalt (key 25)'), 1)
        vol_row.addWidget(self._key_btn(
            '⏯ Oynat', 85, height=38, role='primary',
            tooltip='Oynat / Duraklat (key 85)'), 1)
        vol_row.addWidget(self._key_btn('Ses +', 24, height=38, role='secondary', tooltip='Ses Artır (key 24)'), 1)
        rl.addLayout(vol_row)

        # 4.1 Canlı Ses Seviyesi Kaydırıcısı (Volume Slider & Mute)
        vol_slider_row = QHBoxLayout()
        vol_slider_row.setSpacing(6)

        self.btn_mute = QPushButton()
        self.btn_mute.setObjectName('btnMute')
        self.btn_mute.setFixedSize(36, 30)
        self.btn_mute.setIcon(line_icon('mute', color=kit.colors(self)['danger'], size=16))
        self.btn_mute.setIconSize(QSize(16, 16))
        self.btn_mute.setToolTip('Sesi Kapat / Aç (Mute)')
        self.btn_mute.setProperty('role', 'secondary')
        self.btn_mute.clicked.connect(self._toggle_mute)

        self.slider_vol = QSlider(Qt.Horizontal)
        self.slider_vol.setRange(0, 15)
        self.slider_vol.setValue(0)
        self.slider_vol.setSingleStep(1)
        self.slider_vol.setPageStep(1)
        self.slider_vol.setTickInterval(1)
        self.slider_vol.setTickPosition(QSlider.TicksBelow)
        self.slider_vol.setFixedHeight(34)
        self.slider_vol.setEnabled(False)
        self.slider_vol.setToolTip('Ses kademesi: 0 sessiz, 1–15 arası birer adım. Cihaz bağlanınca gerçek aralık okunur.')
        self._vol_debounce_timer = QTimer(self)
        self._vol_debounce_timer.setSingleShot(True)
        self._vol_debounce_timer.setInterval(250)
        self._vol_debounce_timer.timeout.connect(self._on_volume_slider_released)
        self.slider_vol.valueChanged.connect(self._on_volume_slider_changed)
        self.slider_vol.sliderReleased.connect(self._on_volume_slider_released)

        self.lbl_vol_val = QLabel('— / 15')
        self.lbl_vol_val.setFixedWidth(48)
        self.lbl_vol_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_vol_val.setStyleSheet('font-size: 10pt; font-weight: 600;')

        vol_slider_row.addWidget(self.btn_mute)
        vol_slider_row.addWidget(self.slider_vol, 1)
        vol_slider_row.addWidget(self.lbl_vol_val)
        rl.addLayout(vol_slider_row)

        # 5. Medya Sarma ve Durdurma
        media_row = QHBoxLayout()
        media_row.setSpacing(6)
        media_row.addWidget(self._key_btn('⏪ Geri', 90, height=36, role='secondary', tooltip='Geri Sar (key 90)'), 1)
        media_row.addWidget(self._key_btn('⏹ Durdur', 86, height=36, role='secondary', tooltip='Durdur (key 86)'), 1)
        media_row.addWidget(self._key_btn('⏩ İleri', 91, height=36, role='secondary', tooltip='Hızlı Sar (key 91)'), 1)
        rl.addLayout(media_row)

        # 6. Kanal ve Sessiz
        ch_row = QHBoxLayout()
        ch_row.setSpacing(6)
        ch_row.addWidget(self._key_btn('Kanal −', 167, height=36, role='secondary', tooltip='Kanal Azalt (key 167)'), 1)
        ch_row.addWidget(self._key_btn('🔇 Sessiz', 164, height=36, role='secondary', tooltip='Sessize Al (key 164)'), 1)
        ch_row.addWidget(self._key_btn('Kanal +', 166, height=36, role='secondary', tooltip='Kanal Artır (key 166)'), 1)
        rl.addLayout(ch_row)

        # 7. Hızlı TV Tuşları
        tv_row = QHBoxLayout()
        tv_row.setSpacing(6)
        tv_row.addWidget(self._key_btn('🗂 Son', 187, height=36, role='secondary', tooltip='Son Uygulamalar / Çoklu Görev (key 187)'), 1)
        tv_row.addWidget(self._key_btn('⚙ Ayarlar', 176, height=36, role='secondary', tooltip='TV Android Ayarları (key 176)'), 1)
        tv_row.addWidget(self._key_btn('📺 Giriş', 178, height=36, role='secondary', tooltip='TV Giriş / Kaynak (key 178)'), 1)
        rl.addLayout(tv_row)

        # 8. Durum Etiketi
        self.lbl_status = kit.status_label('Hazır · Tuşları tıklayabilir veya klavye ile kontrol edebilirsiniz.')
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setWordWrap(True)
        rl.addWidget(self.lbl_status)
        key_hint = kit.hint_label('↑ ↓ ← → gezin · Enter: OK · Esc: Geri')
        key_hint.setAlignment(Qt.AlignCenter)
        rl.addWidget(key_hint)
        rl.addStretch()

        return remote_box

    def _build_screen_box(self):
        """Üst panel: Canlı TV Ekranı Önizleme, Dokunmatik Etkileşim ve Scrcpy Entegrasyonu."""
        box = QGroupBox('Canlı TV Ekranı && Dokunmatik Kontrol')
        box.setObjectName('screenCard')
        self._screen_box = box
        lay = QVBoxLayout(box)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        # Canlı ekran göstergesi
        self.screen_view = InteractiveScreenWidget()
        if self.core.connected and self.core.target:
            self.screen_view.setText('Bağlantı hazır\nİlk görüntü için “Ekranı Al”ı veya “Canlı İzle”yi seçin')
        else:
            self.screen_view.setText('Cihaz bağlı değil\nÖnizleme için önce bir TV cihazına bağlanın')
        self.screen_view.tap_requested.connect(self._on_screen_tap)
        self.screen_view.swipe_requested.connect(self._on_screen_swipe)
        lay.addWidget(self.screen_view, 1)

        # Ekran kontrol araç çubuğu (2 sıralı ergonomik yerleşim)
        stream_row1 = QHBoxLayout()
        stream_row1.setSpacing(6)

        self.btn_live_stream = QPushButton('▶ Canlı İzle')
        self.btn_live_stream.setCheckable(True)
        self.btn_live_stream.setFixedHeight(28)
        self.btn_live_stream.setProperty('role', 'primary')
        self.btn_live_stream.toggled.connect(self._toggle_live_stream)
        self.btn_live_stream.setToolTip('TV ekranını belirli aralıklarla otomatik yenileyerek gösterir.')

        self.btn_scrcpy = QPushButton('🚀 Scrcpy (60 FPS)')
        self.btn_scrcpy.setFixedHeight(28)
        self.btn_scrcpy.setProperty('accent', True)
        self.btn_scrcpy.clicked.connect(self._launch_scrcpy)
        self.btn_scrcpy.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_scrcpy.customContextMenuRequested.connect(self._scrcpy_context_menu)
        self.btn_scrcpy.setToolTip('Ultra akıcı 60 FPS canlı TV ekranı açar (Kurulu değilse otomatik onay ile indirir).\nSağ tık: Gelişmiş modlar ve yeniden indirme.')

        stream_row1.addWidget(self.btn_live_stream, 1)
        stream_row1.addWidget(self.btn_scrcpy, 1)
        lay.addLayout(stream_row1)

        stream_row2 = QHBoxLayout()
        stream_row2.setSpacing(6)

        self.btn_capture_once = QPushButton('📸 Ekranı Al')
        self.btn_capture_once.setFixedHeight(26)
        self.btn_capture_once.setProperty('role', 'secondary')
        self.btn_capture_once.clicked.connect(lambda: self._capture_screen(force=True))
        self.btn_capture_once.setToolTip('Tek bir ekran görüntüsü çeker.')

        self.btn_save_screen = QPushButton('💾 Kaydet')
        self.btn_save_screen.setFixedHeight(26)
        self.btn_save_screen.setProperty('role', 'secondary')
        self.btn_save_screen.setEnabled(False)
        self.btn_save_screen.clicked.connect(self._save_screenshot)
        self.btn_save_screen.setToolTip('Mevcut ekran görüntüsünü bilgisayarınıza PNG olarak kaydeder.')

        self.btn_record_video = QPushButton('🎥 Video Kaydet')
        self.btn_record_video.setFixedHeight(26)
        self.btn_record_video.setProperty('role', 'secondary')
        self.btn_record_video.clicked.connect(self._toggle_screen_recording)
        self.btn_record_video.setToolTip('TV ekranını canlı MP4 video olarak kaydeder (Maks. 3 dk).')

        stream_row2.addWidget(self.btn_capture_once, 1)
        stream_row2.addWidget(self.btn_save_screen, 1)
        stream_row2.addWidget(self.btn_record_video, 1)
        lay.addLayout(stream_row2)

        hint_text = 'Ekrana tıklayın veya sürükleyin · Klavye: ↑ ↓ ← →, Enter, Esc'
        if not getattr(getattr(self.core, 'config', None), 'keyboard_nav', True):
            hint_text = 'Ekrana tıklayın veya sürükleyin · Kaydırmak için sürükleyin'
        hint = kit.hint_label('💡 ' + hint_text)
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        lay.addWidget(hint)

        return box

    def _build_control_deck(self):
        """Alt panel: Hızlı Uygulama Başlatıcı, Metin/Pano, Sistem & Güç ve Numpad sekmeleri."""
        deck_tabs = QTabWidget()
        deck_tabs.setObjectName('controlDeck')
        deck_tabs.setStyleSheet("""
            QTabWidget#controlDeck QTabBar::tab {
                padding: 4px 10px;
                font-size: 11px;
            }
        """)
        deck_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # TAB 1: Hızlı Uygulama Başlatıcı & Metin
        app_tab = QWidget()
        app_lay = QVBoxLayout(app_tab)
        app_lay.setContentsMargins(10, 8, 10, 8)
        app_lay.setSpacing(6)

        # Hızlı Uygulamalar (6 popüler TV uygulaması 2x3 ızgara)
        fav_grid = QGridLayout()
        fav_grid.setContentsMargins(0, 0, 0, 0)
        fav_grid.setSpacing(5)
        fav_apps = [
            ('▶ SmartTube', 'org.smarttube.stable'),
            ('🍿 Kodi', 'org.xbmc.kodi'),
            ('🎬 VLC', 'org.videolan.vlc'),
            ('📺 Netflix', 'com.netflix.ninja'),
            ('⊞ Projectivy', 'com.spocky.projengmenu'),
            ('⚙ Ayarlar', 'com.android.tv.settings'),
        ]
        for idx, (name, pkg) in enumerate(fav_apps):
            btn = QPushButton(name)
            btn.setFixedHeight(26)
            btn.setProperty('role', 'secondary')
            btn.clicked.connect(lambda _=False, p=pkg: self._launch_package_direct(p))
            fav_grid.addWidget(btn, idx // 3, idx % 3)
        app_lay.addLayout(fav_grid)

        # Uygulama Seç ve TV'de Aç Satırı
        launch_row = QHBoxLayout()
        launch_row.setSpacing(6)

        self.cmb_app = QComboBox()
        self.cmb_app.setPlaceholderText('Uygulama seç veya paket yaz...')
        self.cmb_app.setEditable(True)
        self.cmb_app.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_app.setMinimumContentsLength(8)
        if self.cmb_app.lineEdit():
            self.cmb_app.lineEdit().setPlaceholderText('Uygulama seç veya paket yaz...')
        self.cmb_app.setFixedHeight(28)
        self.cmb_app.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.btn_load_apps = QPushButton('🔄 Listele')
        self.btn_load_apps.setFixedHeight(28)
        self.btn_load_apps.setProperty('role', 'secondary')
        self.btn_load_apps.clicked.connect(self._load_installed_apps)

        self.btn_launch = QPushButton('▶ TV\'de Aç')
        self.btn_launch.setFixedHeight(28)
        self.btn_launch.setProperty('role', 'primary')
        self.btn_launch.setStyleSheet('font-size: 11.5px; font-weight: bold; background: #6366f1; color: white; border-radius: 6px;')
        self.btn_launch.clicked.connect(self._launch_selected)

        launch_row.addWidget(self.cmb_app, 3)
        launch_row.addWidget(self.btn_load_apps, 1)
        launch_row.addWidget(self.btn_launch, 1)
        app_lay.addLayout(launch_row)

        # Metin & Pano Gönderme Satırı
        text_row = QHBoxLayout()
        text_row.setSpacing(5)

        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText('TV\'ye metin veya link yazın...')
        self.txt_input.setFixedHeight(28)
        self.txt_input.returnPressed.connect(self._send_text)

        send_text = QPushButton('✉ Gönder')
        send_text.setFixedHeight(28)
        send_text.setProperty('role', 'primary')
        send_text.clicked.connect(self._send_text)

        self.btn_text_delete = self._key_btn('⌫ Sil', 67, height=28)
        self.btn_text_delete.setToolTip(
            'TV’de odaklı metin alanında imlecin solundaki karakteri siler.\n'
            'Basılı tut: sürekli sil.')

        btn_paste_pc = QPushButton('📋 Pano')
        btn_paste_pc.setFixedHeight(28)
        btn_paste_pc.setProperty('role', 'secondary')
        btn_paste_pc.setToolTip('Bilgisayarınızda kopyaladığınız metni TV’ye yapıştırır.')
        btn_paste_pc.clicked.connect(self._paste_clipboard)

        btn_open_url = QPushButton('🌐 Link Aç')
        btn_open_url.setFixedHeight(28)
        btn_open_url.setProperty('role', 'secondary')
        btn_open_url.setToolTip('Metin kutusundaki veya panodaki YouTube/web video linkini doğrudan TV\'de oynatır/açar.')
        btn_open_url.clicked.connect(self._open_url_on_tv)

        self.lbl_text_hint = kit.hint_label('')
        text_row.addWidget(self.txt_input, 2)
        text_row.addWidget(send_text)
        text_row.addWidget(self.btn_text_delete)
        text_row.addWidget(btn_paste_pc)
        text_row.addWidget(btn_open_url)
        app_lay.addLayout(text_row)

        deck_tabs.addTab(app_tab, '🚀 Başlatıcı')

        # TAB 2: Sistem Araçları & Güç
        tools_tab = QWidget()
        tools_layout = QVBoxLayout(tools_tab)
        tools_layout.setContentsMargins(10, 8, 10, 8)
        tools_layout.setSpacing(6)

        tools_row1 = QHBoxLayout()
        tools_row1.setSpacing(6)

        self.btn_turbo = QPushButton('⚡ Turbo RAM')
        self.btn_turbo.setFixedHeight(28)
        self.btn_turbo.setProperty('primary', True)
        self.btn_turbo.setStyleSheet('font-weight: bold; background: #6366f1; color: white;')
        self.btn_turbo.setToolTip('Arka plan artıklarını sonlandırır, önbelleği temizler ve RAM kazandırır.')
        self.btn_turbo.clicked.connect(self._turbo_boost)

        self.btn_info = QPushButton('ℹ Sistem')
        self.btn_info.setFixedHeight(28)
        self.btn_info.setProperty('role', 'secondary')
        self.btn_info.clicked.connect(self._device_info)

        self.btn_cache = QPushButton('🧹 Önbellek')
        self.btn_cache.setFixedHeight(28)
        self.btn_cache.setProperty('role', 'secondary')
        self.btn_cache.clicked.connect(self._trim_caches)

        self.btn_tv_settings = self._key_btn(
            '⚙ Ayarlar', 176, height=28, role='secondary',
            tooltip='TV ayarlarını aç (key 176)')

        tools_row1.addWidget(self.btn_turbo, 1)
        tools_row1.addWidget(self.btn_info, 1)
        tools_row1.addWidget(self.btn_cache, 1)
        tools_row1.addWidget(self.btn_tv_settings, 1)
        tools_layout.addLayout(tools_row1)

        tools_row2 = QHBoxLayout()
        tools_row2.setSpacing(6)

        self.btn_reboot = QPushButton('🔄 Yeniden Başlat')
        self.btn_reboot.setFixedHeight(28)
        self.btn_reboot.setProperty('role', 'secondary')
        self.btn_reboot.clicked.connect(self._reboot)

        self.cmb_reboot = _NoWheelComboBox()
        self.cmb_reboot.setFixedHeight(28)
        self.cmb_reboot.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_reboot.setMinimumContentsLength(8)
        self.cmb_reboot.addItems(['Sistem (Normal)', 'Hızlı (Soft Reboot)', 'Kurtarma (Recovery)', 'Bootloader'])

        tools_row2.addWidget(self.btn_reboot, 1)
        tools_row2.addWidget(self.cmb_reboot, 1)
        tools_layout.addLayout(tools_row2)

        # tools_row3: Ekran & Ortam Modları
        tools_row3 = QHBoxLayout()
        tools_row3.setSpacing(6)

        self.btn_ambient = QPushButton('🖼️ Ekran Koruyucu')
        self.btn_ambient.setFixedHeight(28)
        self.btn_ambient.setProperty('role', 'secondary')
        self.btn_ambient.setToolTip('TV ekran koruyucusunu (Google Ambient / Backdrop) hemen başlatır.')
        self.btn_ambient.clicked.connect(self._start_ambient_screensaver)

        self.btn_screen_off = QPushButton('🌙 Ekranı Kapat')
        self.btn_screen_off.setFixedHeight(28)
        self.btn_screen_off.setProperty('role', 'secondary')
        self.btn_screen_off.setToolTip('TV ekranını kapatır ve cihazı bekleme/uyku moduna alır.')
        self.btn_screen_off.clicked.connect(lambda: self._send_key(KEYCODE_SLEEP, 'Ekran Kapat'))

        tools_row3.addWidget(self.btn_ambient, 1)
        tools_row3.addWidget(self.btn_screen_off, 1)
        tools_layout.addLayout(tools_row3)

        # tools_row4: Uyku Zamanlayıcısı Kartı
        timer_card = QFrame()
        timer_card.setObjectName('metricCard')
        timer_card.setProperty('role', 'secondary')
        timer_lay = QVBoxLayout(timer_card)
        timer_lay.setContentsMargins(10, 8, 10, 8)
        timer_lay.setSpacing(5)

        timer_ctrl_row = QHBoxLayout()
        timer_ctrl_row.setSpacing(6)

        lbl_t_title = QLabel('⏳ Uyku:')
        lbl_t_title.setStyleSheet('font-weight: bold; font-size: 11.5px;')

        self.cmb_sleep_duration = _NoWheelComboBox()
        self.cmb_sleep_duration.setFixedHeight(28)
        self.cmb_sleep_duration.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_sleep_duration.setMinimumContentsLength(6)
        self.cmb_sleep_duration.addItems(['15 dk', '30 dk', '45 dk', '60 dk', '90 dk', '120 dk'])
        self.cmb_sleep_duration.setCurrentIndex(1)

        self.btn_sleep_toggle = QPushButton('▶ Başlat')
        self.btn_sleep_toggle.setFixedHeight(28)
        self.btn_sleep_toggle.setProperty('role', 'primary')
        self.btn_sleep_toggle.clicked.connect(self._toggle_sleep_timer)

        timer_ctrl_row.addWidget(lbl_t_title)
        timer_ctrl_row.addWidget(self.cmb_sleep_duration, 1)
        timer_ctrl_row.addWidget(self.btn_sleep_toggle)
        timer_lay.addLayout(timer_ctrl_row)

        self.lbl_sleep_countdown = QLabel('Zamanlayıcı kapalı · Süre sonunda uyku komutu gönderilir.')
        self.lbl_sleep_countdown.setProperty('role', 'quiet')
        self.lbl_sleep_countdown.setStyleSheet('font-size: 11px;')
        self.lbl_sleep_countdown.setWordWrap(True)
        timer_lay.addWidget(self.lbl_sleep_countdown)

        tools_layout.addWidget(timer_card)

        deck_tabs.addTab(tools_tab, '⚙ Sistem')

        # TAB 3: Sayı Tuş Takımı (Numpad) - Standart 3x4 TV Kumanda Dizilimi
        num_tab = QWidget()
        num_layout = QGridLayout(num_tab)
        num_layout.setContentsMargins(10, 8, 10, 8)
        num_layout.setSpacing(4)

        num_keys = [
            ('1', 8, 0, 0), ('2', 9, 0, 1), ('3', 10, 0, 2),
            ('4', 11, 1, 0), ('5', 12, 1, 1), ('6', 13, 1, 2),
            ('7', 14, 2, 0), ('8', 15, 2, 1), ('9', 16, 2, 2),
            ('⌫ Sil', 67, 3, 0), ('0', 7, 3, 1), ('⏺ Seç', 130, 3, 2),
        ]
        for item in num_keys:
            lbl, kcode, r, c = item[:4]
            btn = self._key_btn(
                lbl, kcode, height=28,
                role='secondary',
                tooltip='Tuş: {} (key {})'.format(lbl, kcode))
            num_layout.addWidget(btn, r, c)
        deck_tabs.addTab(num_tab, '🔢 Numpad')

        # Geriye dönük uyumluluk referansları
        self.btn_apk = QPushButton('APK Kur')
        self.btn_apk.clicked.connect(self._install_apk)
        self.btn_apks = QPushButton('Split APK Kur')
        self.btn_apks.clicked.connect(self._install_apks)
        self.btn_sleep = QPushButton('Uyut')
        self.btn_sleep.clicked.connect(lambda: self._send_key(KEYCODE_SLEEP, 'Uyku'))
        self.btn_wake = QPushButton('Uyandır')
        self.btn_wake.clicked.connect(lambda: self._send_key(KEYCODE_WAKEUP, 'Uyan'))

        return deck_tabs

    def _build(self):
        root = kit.page(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

        content_row = QHBoxLayout()
        content_row.setSpacing(12)

        remote_box = self._build_remote_box()

        right_panel = QVBoxLayout()
        right_panel.setSpacing(10)

        screen_box = self._build_screen_box()
        control_deck = self._build_control_deck()

        right_panel.addWidget(screen_box, 1)
        right_panel.addWidget(control_deck, 0)

        content_row.addWidget(remote_box, 0, Qt.AlignTop)
        content_row.addLayout(right_panel, 1)
        root.addLayout(content_row)
        for button in self.findChildren(QPushButton):
            if button.maximumHeight() <= 34:
                button.setProperty('compact', True)

    # ------------------------------------------------------------------
    # Canlı Ekran & Etkileşim (Tap & Swipe & Scrcpy)
    # ------------------------------------------------------------------
    def _toggle_live_stream(self, active):
        if active:
            if self._capture_device_context() is None:
                self.btn_live_stream.setChecked(False)
                QMessageBox.information(self, 'Bağlantı', 'Canlı ekran için cihaz bağlantısının tamamlanmasını bekleyin.')
                return
            self.btn_live_stream.setText('⏹ Durdur')
            self._capture_screen(force=True)
            self._live_timer.start(1600)  # Her 1.6 saniyede bir kare yenile
            self.lbl_status.setText('Canlı ekran izleme aktif.')
        else:
            self._live_timer.stop()
            self.btn_live_stream.setText('▶ Canlı İzle')
            self.lbl_status.setText('Canlı ekran durduruldu.')

    def _on_live_tick(self):
        if not self.core.connected or not self.core.target:
            self.btn_live_stream.setChecked(False)
            return
        self._capture_screen(force=False)

    def _capture_screen(self, force=False):
        if self._capture_busy:
            return
        context = self._capture_device_context()
        if context is None:
            return

        self._capture_busy = True
        engine, target, _generation = context
        capture_generation = self._capture_generation

        def current():
            return (capture_generation == self._capture_generation
                    and self._device_context_current(context))

        def do():
            self._require_device_context(context)
            return engine.screenshot(target)

        def done(data):
            if capture_generation != self._capture_generation:
                return
            self._capture_busy = False
            if not current():
                return
            if not data:
                failed('TV boş görüntü döndürdü.')
                return
            img = QImage()
            if img.loadFromData(data):
                pixmap = QPixmap.fromImage(img)
                self._last_screen_pixmap = pixmap
                self.screen_view.set_screen_image(pixmap, img.width(), img.height())
                self.btn_save_screen.setEnabled(True)
            else:
                failed('Ekran görüntüsü çözülemedi.')

        def failed(err):
            if capture_generation != self._capture_generation:
                return
            self._capture_busy = False
            if not current():
                return
            was_live = self.btn_live_stream.isChecked()
            if was_live:
                self.btn_live_stream.setChecked(False)
            self.lbl_status.setText(
                '{}Ekran alınamadı: {} Yeniden denemek için Ekranı Al düğmesini kullanın.'.format(
                    'Canlı izleme durduruldu. ' if was_live else '', err))

        w = Worker(do)
        w.finished_ok.connect(done)
        w.failed.connect(failed)
        self.window._run(w, silent=not force, desc='Ekran görüntüsü alma')

    def _save_screenshot(self):
        if not self._last_screen_pixmap or self._last_screen_pixmap.isNull():
            QMessageBox.information(self, 'Ekran Yok', 'Önce "Ekranı Al" ile bir ekran görüntüsü yakalayın.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Ekran Görüntüsünü Kaydet', 'tv_ekran.png', 'PNG Resimleri (*.png)')
        if path:
            if self._last_screen_pixmap.save(path, 'PNG'):
                QMessageBox.information(self, 'Kaydedildi', 'Ekran görüntüsü kaydedildi:\n{}'.format(path))
            else:
                QMessageBox.warning(self, 'Hata', 'Dosya kaydedilemedi.')

    def _scrcpy_context_menu(self, pos):
        context = self._capture_device_context()
        menu = QMenu(self)
        a_run = menu.addAction('🚀 Scrcpy Başlat (Varsayılan - 60 FPS)')
        a_low = menu.addAction('📶 Wi-Fi Hızlı Mod (4 Mbps, düşük gecikme)')
        a_mute = menu.addAction('🔇 Yalnızca Görüntü (Sessiz / --no-audio)')
        menu.addSeparator()
        a_reinstall = menu.addAction('🔄 Scrcpy\'yi Yeniden İndir / Güncelle')
        a_open_folder = menu.addAction('📁 Scrcpy Klasörünü Aç')

        act = menu.exec(self.btn_scrcpy.mapToGlobal(pos))
        if context is None and act in (a_run, a_low, a_mute, a_reinstall):
            self.lbl_status.setText('Menü açılırken bağlantı hazır değildi. Bağlandıktan sonra yeniden deneyin.')
            return
        if act == a_run:
            self._launch_scrcpy(context=context)
        elif act == a_low:
            self._launch_scrcpy(extra_args=['--video-bit-rate=4M', '--max-size=1280'], context=context)
        elif act == a_mute:
            self._launch_scrcpy(extra_args=['--no-audio'], context=context)
        elif act == a_reinstall:
            self._download_and_launch_scrcpy(force_download=True, context=context)
        elif act == a_open_folder:
            installed = find_scrcpy()
            if not installed:
                self.lbl_status.setText('Doğrulanmış Scrcpy kurulumu bulunamadı.')
                return
            try:
                target_dir = os.path.dirname(installed)
                if sys.platform == 'win32':
                    os.startfile(target_dir)
                else:
                    subprocess.Popen(['xdg-open', target_dir])
            except OSError as error:
                self.lbl_status.setText('Scrcpy klasörü açılamadı: ' + str(error))

    def _launch_scrcpy(self, extra_args=None, context=None):
        context = context if context is not None else self._capture_device_context()
        if not self._device_context_current(context):
            QMessageBox.information(self, 'Bağlantı Yok', 'Scrcpy ile bağlanmak için önce bir TV cihazına bağlanın.')
            return
        if self._scrcpy_download_worker is not None:
            self.lbl_status.setText('Scrcpy indirmesi sürüyor; tamamlanmasını bekleyin.')
            return
        if self._scrcpy_process is not None and self._scrcpy_process.poll() is None:
            self.lbl_status.setText('Scrcpy penceresi zaten açık. Yeni oturum için önce onu kapatın.')
            return

        scrcpy_path = find_scrcpy()
        if scrcpy_path:
            self._start_scrcpy_process(scrcpy_path, extra_args=extra_args, context=context)
            return

        self._download_and_launch_scrcpy(extra_args=extra_args, context=context)

    def _download_and_launch_scrcpy(self, extra_args=None, force_download=False, context=None):
        if self._scrcpy_download_worker is not None:
            self.lbl_status.setText('Scrcpy indirmesi sürüyor; tamamlanmasını bekleyin.')
            return
        context = context if context is not None else self._capture_device_context()
        if not self._device_context_current(context):
            self.lbl_status.setText('Scrcpy için önce cihaz bağlantısının tamamlanmasını bekleyin.')
            return
        if getattr(self.window, '_closing', False) or getattr(self.window, '_close_pending', False):
            return
        reply = QMessageBox.question(
            self,
            'Scrcpy İndirme Onayı',
            ('Resmî Scrcpy paketi yeniden indirilsin mi?' if force_download else
             'Doğrulanmış Scrcpy kurulumu bulunamadı. Resmî paket indirilsin mi?') +
            '\n\nPaket doğrulandıktan sonra seçili cihazda ekran yansıtma başlatılacak.\nHedef: ' + context[1],
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            self.lbl_status.setText('Scrcpy indirme işlemi kullanıcı tarafından iptal edildi.')
            return
        if (not self._device_context_current(context) or getattr(self.window, '_closing', False)
                or getattr(self.window, '_close_pending', False)):
            self.lbl_status.setText('Bağlantı değişti veya uygulama kapanıyor; indirme başlatılmadı.')
            return
        if self._scrcpy_download_worker is not None:
            self.lbl_status.setText('Scrcpy indirmesi zaten sürüyor.')
            return
        launch_args = list(extra_args or [])
        dlg = QProgressDialog('Scrcpy hazırlanıyor...', 'İptal', 0, 100, self)
        dlg.setWindowTitle('Scrcpy İndiriliyor')
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)
        dlg.show()

        worker = ScrcpyDownloader(force_download=force_download)
        self._scrcpy_download_worker = worker
        self.btn_scrcpy.setEnabled(False)
        cancelled = False

        def close_progress():
            dlg.blockSignals(True)
            dlg.close()

        def cleanup():
            if self._scrcpy_download_worker is worker:
                self._scrcpy_download_worker = None
                if not getattr(self.window, '_closing', False):
                    self.btn_scrcpy.setEnabled(True)
            close_progress()

        def on_cancel():
            nonlocal cancelled
            cancelled = True
            worker.cancel()
            dlg.setLabelText('İptal ediliyor...')
            self.lbl_status.setText('Scrcpy indirmesi iptal ediliyor…')

        dlg.canceled.connect(on_cancel)

        def on_progress(cur, total):
            if cancelled:
                return
            if total > 0:
                dlg.setMaximum(total)
                dlg.setValue(cur)
                pct = int((cur / total) * 100)
                cur_mb = cur / (1024 * 1024)
                tot_mb = total / (1024 * 1024)
                dlg.setLabelText(f'Scrcpy indiriliyor... {cur_mb:.1f} / {tot_mb:.1f} MB (%{pct})')
            else:
                dlg.setMaximum(0)
                dlg.setLabelText('Scrcpy indiriliyor...')

        worker.progress.connect(on_progress)
        worker.status_text.connect(lambda message: dlg.setLabelText(message) if not cancelled else None)
        worker.finished.connect(cleanup)

        def on_ok(result):
            close_progress()
            if cancelled or worker.isInterruptionRequested():
                self.lbl_status.setText('Scrcpy indirmesi iptal edildi; otomatik başlatılmadı.')
                return
            scrcpy_path = result.get('scrcpy_path')
            ver = result.get('version', '')
            self.lbl_status.setText(f'✅ Scrcpy {ver} başarıyla kuruldu.')
            if self._device_context_current(context):
                self._start_scrcpy_process(scrcpy_path, extra_args=launch_args, context=context)
            else:
                self.lbl_status.setText('Scrcpy kuruldu. Bağlantı değiştiği için açılmadı; yeniden Scrcpy düğmesine basın.')

        def on_fail(err):
            close_progress()
            if 'kullanıcı durdurdu' in str(err).lower() or 'iptal' in str(err).lower():
                self.lbl_status.setText('Scrcpy indirme işlemi iptal edildi.')
            else:
                self.lbl_status.setText('Scrcpy indirilemedi. Ayrıntılar işlem günlüğünde.')

        try:
            self.window._run(worker, on_ok=on_ok, on_fail=on_fail, desc='Scrcpy İndiriliyor')
        except Exception:
            cleanup()
            raise

    def _start_scrcpy_process(self, scrcpy_path, extra_args=None, context=None):
        context = context if context is not None else self._capture_device_context()
        if (not self._device_context_current(context) or getattr(self.window, '_closing', False)
                or getattr(self.window, '_close_pending', False)):
            self.lbl_status.setText('Bağlantı hazır değil; Scrcpy başlatılmadı.')
            return
        if self._scrcpy_process is not None and self._scrcpy_process.poll() is None:
            self.lbl_status.setText('Scrcpy penceresi zaten açık. Yeni oturum için önce onu kapatın.')
            return
        engine, target, _generation = context
        self._scrcpy_poll_timer.stop()
        self._scrcpy_process = None
        self._scrcpy_launch_context = None
        try:
            adb_path = getattr(engine, 'adb_path', None)
            self._scrcpy_process = launch_scrcpy(
                scrcpy_path=scrcpy_path,
                target=target,
                adb_path=adb_path,
                extra_args=extra_args,
            )
            self._scrcpy_launch_context = context
            self._scrcpy_poll_timer.start()
            self.lbl_status.setText('Scrcpy işlemi başlatıldı; görüntü ayrı pencerede açılacak.')
            if hasattr(self.window, 'append_log'):
                self.window.append_log('Scrcpy işlemi başlatıldı.', 'INFO')
        except Exception as e:
            QMessageBox.warning(self, 'Scrcpy Hatası', f'Scrcpy başlatılamadı:\n{e}')

    def _poll_scrcpy_process(self):
        process = self._scrcpy_process
        if process is None:
            self._scrcpy_poll_timer.stop()
            return
        code = process.poll()
        if code is None:
            if (self._scrcpy_shutdown_started is not None
                    and not self._scrcpy_kill_requested
                    and time.monotonic() - self._scrcpy_shutdown_started >= 1.5):
                try:
                    process.kill()
                except OSError:
                    pass
                else:
                    self._scrcpy_kill_requested = True
            return
        context = self._scrcpy_launch_context
        self._scrcpy_process = None
        self._scrcpy_launch_context = None
        self._scrcpy_shutdown_started = None
        self._scrcpy_kill_requested = False
        self._scrcpy_poll_timer.stop()
        if getattr(self.window, '_closing', False) or getattr(self.window, '_close_pending', False):
            return
        if self._device_context_current(context):
            message = 'Scrcpy penceresi kapandı.' if code == 0 else 'Scrcpy hata koduyla kapandı: {}. Scrcpy günlüğünü inceleyin.'.format(code)
            self.lbl_status.setText(message)
            self.window.append_log(message, 'INFO' if code == 0 else 'ERROR')

    def _on_screen_tap(self, x, y):
        context = self._capture_device_context()
        if context is None:
            return
        engine, target, _generation = context

        def do():
            self._require_device_context(context)
            engine.tap(target, x, y)
            return (x, y)

        w = Worker(do)
        w.finished_ok.connect(
            lambda pt: self.lbl_status.setText('Dokunuldu: ({}, {})'.format(pt[0], pt[1]))
            if self._device_context_current(context) else None)
        self.window._run(w)

        # Tıklama sonrası ekranı hemen güncelle
        if hasattr(self, 'btn_live_stream') and self.btn_live_stream.isChecked():
            QTimer.singleShot(400, lambda: self._capture_screen(force=False))

    def _on_screen_swipe(self, x1, y1, x2, y2):
        context = self._capture_device_context()
        if context is None:
            return
        engine, target, _generation = context

        def do():
            self._require_device_context(context)
            engine.swipe(target, x1, y1, x2, y2, duration_ms=250)
            return (x1, y1, x2, y2)

        w = Worker(do)
        w.finished_ok.connect(
            lambda pts: self.lbl_status.setText(
                'Kaydırıldı: ({}, {}) → ({}, {})'.format(pts[0], pts[1], pts[2], pts[3]))
            if self._device_context_current(context) else None)
        self.window._run(w)

        if hasattr(self, 'btn_live_stream') and self.btn_live_stream.isChecked():
            QTimer.singleShot(500, lambda: self._capture_screen(force=False))

    # ------------------------------------------------------------------
    # Pano (Clipboard) ve Metin
    # ------------------------------------------------------------------
    def _paste_clipboard(self):
        clip = QApplication.clipboard()
        text = clip.text()
        if not text:
            QMessageBox.information(self, 'Pano Boş', 'Bilgisayarınızın panosunda kopyalanmış bir metin bulunamadı.')
            return
        self.txt_input.setText(text)
        self._send_text()

    def _launch_package_direct(self, pkg):
        context = self._capture_device_context()
        if context is None:
            QMessageBox.information(self, 'Bağlantı Yok', 'Önce bir cihaza bağlanın.')
            return
        engine, target, _generation = context

        def do():
            self._require_device_context(context)
            engine.launch_resolved(target, pkg)
            return pkg

        w = Worker(do)
        w.finished_ok.connect(
            lambda p: self.lbl_status.setText('Açıldı: ' + p)
            if self._device_context_current(context) else None)
        self.window._run(w)

    # ------------------------------------------------------------------
    # Tema Uyumu
    # ------------------------------------------------------------------
    def apply_theme(self):
        try:
            dark = kit.dark_from(self)
            self.lbl_text_hint.setStyleSheet(kit.faint(dark))
            self.lbl_status.setStyleSheet(kit.muted(dark))
            self._style_remote_cards()
            self._style_navigation_disc()
            for b in getattr(self, '_arrow_buttons', []):
                self._style_arrow(b, dark)
            if hasattr(self, 'btn_mute'):
                self.btn_mute.setIcon(line_icon('mute', color=kit.colors(self)['danger'], size=16))
        except (RuntimeError, AttributeError):
            pass

    # ------------------------------------------------------------------
    # Uygulama Doldurma ve Başlatma
    # ------------------------------------------------------------------
    def populate_apps(self, apps):
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
        self.btn_load_apps.setText('Yükleniyor…' if loading else '🔄 Yüklüleri Listele')
        self.cmb_app.setEnabled(not loading)

    # ------------------------------------------------------------------
    # Tuş ve Metin Gönderimi
    # ------------------------------------------------------------------
    def _send_key(self, code, label, target=None, longpress=False):
        if self._busy:
            return
        context = self._capture_device_context()
        if context is None:
            self.lbl_status.setText('Önce cihaza bağlanın.')
            return
        engine, current_target, _generation = context
        if target is not None and target != current_target:
            return
        target = current_target
        self._busy = True

        def do():
            self._require_device_context(context)
            if longpress:
                engine.keyevent(target, code, longpress=True)
            else:
                engine.keyevent(target, code)
            return label + (' · uzun basış' if longpress else '')

        w = Worker(do, silent=True)
        w.job_name = 'Tuş: ' + str(label)
        w.finished_ok.connect(lambda result: self._key_done(result, context))
        w.failed.connect(lambda error: self._key_failed(error, context))
        self.window._run(w, silent=True)

    def _key_failed(self, _error, context=None):
        if context is not None and context[2] != self._connection_generation:
            return
        self._busy = False
        self._stop_hold()
        if context is not None and not self._device_context_current(context):
            return
        self.lbl_status.setText('Tuş gönderilemedi. Bağlantıyı kontrol edin.')

    def _key_done(self, label, context=None):
        if context is not None and context[2] != self._connection_generation:
            return
        self._busy = False
        if context is not None and not self._device_context_current(context):
            self._stop_hold()
            self._pending_ok = None
            return
        try:
            self.lbl_status.setText('Basılı tutuluyor: ' + str(label) if self._held else 'Son tuş: ' + str(label))
        except RuntimeError:
            pass
        if 'Ses' in str(label) and hasattr(self, '_fetch_volume'):
            QTimer.singleShot(400, self._fetch_volume)
        pending = self._pending_ok
        self._pending_ok = None
        if pending and self.core.connected and self.core.target == pending[2]:
            self._send_key(pending[0], pending[1], target=pending[2], longpress=pending[3])

    def _send_text(self):
        t = self.txt_input.text()
        if not t:
            return
        context = self._capture_device_context()
        if context is None:
            self.lbl_status.setText('Önce cihaza bağlanın.')
            return
        engine, target, _generation = context

        def do():
            self._require_device_context(context)
            engine.input_text(target, t)
            return t

        safe = sanitize_input_text(t)
        if safe != t.replace(' ', '%s'):
            self.lbl_text_hint.setText('(temizlendi)')
        else:
            self.lbl_text_hint.setText('')
        w = Worker(do)
        w.finished_ok.connect(
            lambda m: self.lbl_status.setText('Metin gönderildi: ' + m)
            if self._device_context_current(context) else None)
        self.window._run(w)
        self.txt_input.clear()

    def _launch_selected(self):
        context = self._capture_device_context()
        if context is None:
            self.lbl_status.setText('Önce cihaza bağlanın.')
            return
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
        engine, target, _generation = context

        def do():
            self._require_device_context(context)
            engine.launch_resolved(target, pkg)
            return pkg

        w = Worker(do)
        w.job_name = 'Uygulama açma'
        w.finished_ok.connect(
            lambda p: self.lbl_status.setText('Açıldı: ' + p)
            if self._device_context_current(context) else None)
        self.window._run(w, desc='Kumanda: uygulama açılıyor: ' + pkg)

    # ------------------------------------------------------------------
    # Cihaz Bilgisi ve Sistem İşlemleri
    # ------------------------------------------------------------------
    def _device_info(self):
        self._run_device_action(
            self._capture_device_context(), lambda engine, target: engine.device_info_full(target),
            'Cihaz bilgilerini okuma', self._show_info)

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

    def _reboot(self, mode=None, context=None):
        context = context if context is not None else self._capture_device_context()
        if context is None:
            self.lbl_status.setText('Önce cihaza bağlanın.')
            return
        mode = mode if isinstance(mode, str) else self.cmb_reboot.currentText()
        extra = None
        if mode == 'Bootloader':
            extra = ('DİKKAT: Bootloader modundan TV kendi kendine dönmeyebilir; fiziksel erişim gerekebilir.')
        body = 'Cihaz yeniden başlatılsın mı ({})?\n\nHedef: {}'.format(mode, context[1])
        if extra:
            body += '\n\n' + extra
        if QMessageBox.question(self, 'Onay — Yeniden Başlat', body,
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return

        def do(eng, target):
            if 'Recovery' in mode:
                return eng.reboot_recovery(target)
            elif 'Bootloader' in mode:
                return eng.reboot_bootloader(target)
            elif 'Soft' in mode or 'Zygote' in mode:
                return eng.soft_reboot(target)
            else:
                return eng.reboot(target)
        self._run_device_action(context, do, 'Yeniden başlatma',
            lambda _: self.lbl_status.setText(f'Yeniden başlatma komutu gönderildi ({mode}).'))

    def _power_context_menu(self, pos):
        context = self._capture_device_context()
        if context is None:
            self.lbl_status.setText('Önce cihaz bağlantısının tamamlanmasını bekleyin.')
            return
        menu = QMenu(self)
        a_reboot = menu.addAction('🔄 Normal Yeniden Başlat (Reboot)')
        a_soft = menu.addAction('⚡ Hızlı Soft Reboot (3 sn - Zygote)')
        a_rec = menu.addAction('🛑 Kurtarma Modu (Recovery)')
        menu.addSeparator()
        a_sleep = menu.addAction('☾ Uykuya Al (Sleep)')
        a_wake = menu.addAction('☼ Cihazı Uyandır (Wakeup)')

        act = menu.exec(self.btn_power.mapToGlobal(pos))
        if not self._device_context_current(context):
            return
        if act == a_reboot:
            self._reboot('Sistem (Normal)', context)
        elif act == a_soft:
            self._reboot('Hızlı (Soft Reboot)', context)
        elif act == a_rec:
            self._reboot('Kurtarma (Recovery)', context)
        elif act == a_sleep:
            self._run_device_action(context, lambda engine, target: engine.keyevent(target, KEYCODE_SLEEP),
                                    'Uyku komutu gönderme')
        elif act == a_wake:
            self._run_device_action(context, lambda engine, target: engine.keyevent(target, KEYCODE_WAKEUP),
                                    'Uyandırma komutu gönderme')

    def _trim_caches(self):
        self._run_device_action(self._capture_device_context(),
            lambda engine, target: engine.trim_caches(target), 'Önbellek temizleme')

    def _turbo_boost(self):
        if (getattr(self.window, '_closing', False)
                or getattr(self.window, '_close_pending', False)):
            return
        if getattr(self.window, '_workers', []):
            self.lbl_status.setText('Diğer işlemlerin bitmesini bekleyin.')
            return
        context = self._capture_device_context()
        if context is None:
            self.lbl_status.setText('Önce cihaza bağlanın.')
            return
        self.lbl_status.setText('⚡ Turbo hızlandırma çalışıyor...')
        def on_ok(res):
            freed = res.get('freed_mb')
            completed = res.get('completed_steps', 0)
            failed = res.get('failed_steps', 0)
            msg = 'Bakım sonucu: {} adım tamamlandı, {} adım başarısız.'.format(completed, failed)
            if isinstance(freed, (int, float)) and not isinstance(freed, bool) and freed > 0:
                msg += ' Ölçülen boş RAM artışı: {:.1f} MB.'.format(freed)
            self.lbl_status.setText(msg)
            if hasattr(self.window, 'append_log'):
                self.window.append_log(msg, 'WARN' if failed else 'INFO')
                for detail in res.get('summary', []):
                    self.window.append_log(str(detail), 'INFO')
        engine, target, _generation = context

        def current():
            return (self._device_context_current(context)
                    and not getattr(self.window, '_closing', False)
                    and not getattr(self.window, '_close_pending', False))

        def check():
            worker.check_cancel()
            if not current():
                raise CancelledError('Bağlantı değişti; hızlandırma durduruldu.')

        worker = Worker(lambda: engine.quick_boost(target, check_cancel=check))
        results, errors = [], []
        worker.finished_ok.connect(results.append)
        worker.failed.connect(errors.append)

        def finish():
            if not current():
                return
            if errors:
                self.lbl_status.setText('Hızlandırma tamamlanamadı: ' + str(errors[-1]))
            elif results:
                on_ok(results[-1])
            else:
                self.lbl_status.setText('Hızlandırma durduruldu. Bazı adımlar uygulanmış olabilir.')

        worker.finished.connect(finish)
        try:
            self.window._run(worker, desc='Turbo Hızlandırma')
        except Exception as error:
            if current():
                self.lbl_status.setText('Hızlandırma başlatılamadı: ' + str(error))

    def _on_volume_slider_changed(self, v):
        self.lbl_vol_val.setText('{} / {}'.format(v, self.slider_vol.maximum()))
        self._vol_edit_revision += 1
        if not self.slider_vol.isSliderDown():
            self._vol_debounce_timer.start(250)

    def _toggle_mute(self):
        context = self._capture_device_context()
        if context is None:
            return
        engine, target, _generation = context
        def do():
            self._require_device_context(context)
            return engine.set_volume_mute(target)
        def done(_):
            if self._device_context_current(context):
                self.lbl_status.setText('Sesi Aç/Kapat (Mute) tuşlandı.')
                QTimer.singleShot(250, self._fetch_volume)
        def failed(_):
            if self._device_context_current(context):
                self.lbl_status.setText('Sesi aç/kapat komutu gönderilemedi. Bağlantıyı kontrol edin.')
        w = Worker(do, silent=True)
        w.job_name = 'Sesi Aç/Kapat'
        w.finished_ok.connect(done)
        w.failed.connect(failed)
        self.window._run(w, silent=True)

    def _on_volume_slider_released(self):
        self._vol_debounce_timer.stop()
        context = self._capture_device_context()
        if context is None or not self.slider_vol.isEnabled():
            return
        if getattr(self, '_vol_setting', False):
            return
        self._vol_setting = True
        val = self.slider_vol.value()
        engine, target, _connection_generation = context
        generation = self._volume_generation
        def do():
            self._require_device_context(context)
            return engine.set_volume_level(target, val)
        w = Worker(do, silent=True)
        w.job_name = 'Ses Ayarla'
        def on_done(_):
            if generation != self._volume_generation:
                return
            self._vol_setting = False
            if not self._device_context_current(context):
                return
            self.lbl_status.setText('TV ses seviyesi {} / {} yapıldı.'.format(val, self.slider_vol.maximum()))
            if self.slider_vol.value() != val:
                if not self.slider_vol.isSliderDown():
                    self._on_volume_slider_released()
            else:
                QTimer.singleShot(250, self._fetch_volume)
        def on_fail(err):
            if generation != self._volume_generation:
                return
            self._vol_setting = False
            if not self._device_context_current(context):
                return
            self.lbl_status.setText('Ses ayarlanamadı.')
            QTimer.singleShot(250, self._fetch_volume)
        w.finished_ok.connect(on_done)
        w.failed.connect(on_fail)
        self.window._run(w, silent=True)

    def _fetch_volume(self):
        context = self._capture_device_context()
        if context is None:
            return
        if (self._vol_setting or self._vol_reading or self.slider_vol.isSliderDown()
                or self._vol_debounce_timer.isActive()):
            return
        self._vol_reading = True
        engine, target, _connection_generation = context
        generation = self._volume_generation
        revision = self._vol_edit_revision
        def do():
            self._require_device_context(context)
            return engine.get_volume_info(target)
        w = Worker(do, silent=True)
        w.job_name = 'Ses Seviyesi'
        def on_ok(info):
            if generation != self._volume_generation:
                return
            self._vol_reading = False
            if not self._device_context_current(context):
                return
            if (revision != self._vol_edit_revision or self._vol_setting
                    or self.slider_vol.isSliderDown() or self._vol_debounce_timer.isActive()):
                return
            val, minimum, maximum = info
            if maximum <= minimum or not minimum <= val <= maximum:
                self.slider_vol.setEnabled(False)
                self.lbl_vol_val.setText('—')
                return
            self.slider_vol.blockSignals(True)
            try:
                self.slider_vol.setRange(minimum, maximum)
                self.slider_vol.setValue(val)
                self.lbl_vol_val.setText('{} / {}'.format(val, maximum))
                self.slider_vol.setToolTip('Ses kademesi: {}–{}, birer adım.'.format(minimum, maximum))
                self.slider_vol.setEnabled(True)
            finally:
                self.slider_vol.blockSignals(False)
        def on_fail(_):
            if generation == self._volume_generation:
                self._vol_reading = False
                if not self._device_context_current(context):
                    return
                if revision != self._vol_edit_revision or self._vol_setting:
                    return
                self.slider_vol.setEnabled(False)
                self.lbl_vol_val.setText('— / {}'.format(self.slider_vol.maximum()))
                self.lbl_status.setText('Ses seviyesi okunamadı; Ses − / Ses + tuşlarını kullanabilirsiniz.')
        w.finished_ok.connect(on_ok)
        w.failed.connect(on_fail)
        self.window._run(w, silent=True)

    def _toggle_screen_recording(self):
        if self._recording_starting or self._recording_finalizing:
            return
        if self._recording_remote_path:
            self._stop_screen_recording()
        else:
            self._start_screen_recording()

    def _start_screen_recording(self):
        if (self._recording_starting or self._recording_finalizing or self._recording_remote_path
                or getattr(self.window, '_closing', False)
                or getattr(self.window, '_close_pending', False)):
            return
        context = self._capture_device_context()
        if context is None:
            QMessageBox.information(self, 'Bağlantı Yok', 'Video kaydetmek için önce TV cihazına bağlanın.')
            return

        engine, target, _generation = context
        self._recording_starting = True
        self._recording_stop_requested = False
        self.btn_record_video.setEnabled(False)
        self.btn_record_video.setText('Başlatılıyor…')
        self.lbl_status.setText('TV ekran kaydı başlatılıyor…')

        def do_start():
            remote_pid = None
            remote_tmp = '/sdcard/.mibox_screenrecord_{}.mp4'.format(os.urandom(6).hex())

            def stop_by_unique_path():
                # The ADB response may be lost after screenrecord starts, so
                # recover its PID by the unique output path instead of leaving
                # an untracked recording running on the TV.
                script = (
                    'needle={}; '
                    'for file in /proc/[0-9]*/cmdline; do '
                    'pid=${{file#/proc/}}; pid=${{pid%/cmdline}}; '
                    '[ -r "/proc/$pid/comm" ] || continue; '
                    'comm=$(cat "/proc/$pid/comm" 2>/dev/null) || continue; '
                    '[ "$comm" = screenrecord ] || continue; '
                    'args=$(tr "\\000" " " < "$file" 2>/dev/null) || continue; '
                    'case "$args" in *"$needle"*) ;; *) continue ;; esac; '
                    '[ -r "/proc/$pid/comm" ] || continue; '
                    'comm=$(cat "/proc/$pid/comm" 2>/dev/null) || continue; '
                    '[ "$comm" = screenrecord ] || continue; '
                    'args=$(tr "\\000" " " < "$file" 2>/dev/null) || continue; '
                    'case "$args" in *"$needle"*) '
                    'kill -2 "$pid" 2>/dev/null || true ;; esac; '
                    'done'
                ).format(shlex.quote(remote_tmp))
                return engine.shell(
                    target, 'sh', '-c', shlex.quote(script), timeout=8)

            try:
                self._require_device_context(context)
                worker.check_cancel()
                start_script = (
                    'nohup screenrecord --time-limit 180 {} '
                    '>/dev/null 2>&1 </dev/null & echo $!'
                ).format(remote_tmp)
                result = engine.shell(target, 'sh', '-c', shlex.quote(start_script), timeout=10)
                if result.exit_code != 0:
                    raise RuntimeError(result.error or result.output or 'TV ekran kaydı başlatılamadı.')
                pid_lines = (result.output or '').strip().splitlines()
                remote_pid = pid_lines[-1].strip() if pid_lines else ''
                if not remote_pid.isdigit() or int(remote_pid) <= 1:
                    remote_pid = None
                    raise RuntimeError('TV ekran kaydının işlem kimliği doğrulanamadı.')
                deadline = time.monotonic() + 2.0
                while True:
                    process_info = engine.shell(target, 'cat', '/proc/{}/cmdline'.format(remote_pid), timeout=5)
                    process_cmd = (process_info.output or '').replace('\x00', ' ').lower()
                    if (process_info.exit_code == 0 and 'screenrecord' in process_cmd
                            and remote_tmp.lower() in process_cmd):
                        break
                    worker.check_cancel()
                    if time.monotonic() >= deadline:
                        raise RuntimeError('TV ekran kaydı işlemi başlatıldı ancak doğrulanamadı.')
                    time.sleep(0.1)
                worker.check_cancel()
                return remote_tmp, remote_pid, time.monotonic()
            except Exception as error:
                try:
                    # Scan and signal in one TV-side command, rechecking the
                    # unique path immediately before SIGINT to reduce PID reuse risk.
                    stop_by_unique_path()
                except Exception:
                    pass
                raise RuntimeError('{} TV’de oluşmuş kayıt dosyası silinmedi: {}'.format(error, remote_tmp)) from error

        def done(result):
            self._recording_starting = False
            remote_tmp, remote_pid, started_at = result
            self._recording_proc = None
            self._recording_engine = engine
            self._recording_target = target
            self._recording_remote_path = remote_tmp
            self._recording_pid = remote_pid
            self._recording_seconds = 0
            self._recording_started_at = started_at
            if self._recording_stop_requested or not self._device_context_current(context):
                self._stop_screen_recording(show_saved_dialog=False)
                QTimer.singleShot(0, self.window._watchdog_worker_finished)
                return

            if self._recording_timer is None:
                self._recording_timer = QTimer(self)
                self._recording_timer.timeout.connect(self._on_record_tick)
            self._recording_timer.start(1000)

            self.btn_record_video.setEnabled(True)
            self.btn_record_video.setText('⏹ Durdur (00:00)')
            self.btn_record_video.setStyleSheet('background-color: #ef4444; color: white; font-weight: bold; border-radius: 6px;')
            self.lbl_status.setText('🔴 Canlı TV video kaydı başlatıldı...')
        def failed(_error):
            self._recording_starting = False
            self.btn_record_video.setEnabled(True)
            self.btn_record_video.setText('🎥 Video Kaydet')
            if not self._recording_stop_requested:
                self.lbl_status.setText('Video kaydı başlatılamadı. Ayrıntılar işlem günlüğünde.')
            QTimer.singleShot(0, self.window._watchdog_worker_finished)
        worker = Worker(do_start)
        try:
            self.window._run(worker, on_ok=done, on_fail=failed, desc='TV video kaydını başlatma')
        except Exception:
            failed('')
            raise

    def prepare_recording_close(self):
        if self._recording_starting:
            self._recording_stop_requested = True
            return False
        if self._recording_remote_path:
            self._stop_screen_recording(show_saved_dialog=False)
        return True

    def _request_scrcpy_shutdown(self):
        process = self._scrcpy_process
        if process is None:
            return True
        if process.poll() is not None:
            self._poll_scrcpy_process()
            return True
        if self._scrcpy_shutdown_started is None:
            self._scrcpy_shutdown_started = time.monotonic()
            try:
                process.terminate()
            except OSError:
                pass
        if not self._scrcpy_poll_timer.isActive():
            self._scrcpy_poll_timer.start()
        return False

    def prepare_scrcpy_close(self):
        """Stop the separately launched Scrcpy process before the app exits."""
        if self._scrcpy_process is None:
            return True
        if self._scrcpy_process.poll() is not None:
            self._poll_scrcpy_process()
            return True
        self._request_scrcpy_shutdown()
        if self._scrcpy_process is None or self._scrcpy_shutdown_started is None:
            return True
        elapsed = time.monotonic() - self._scrcpy_shutdown_started
        if elapsed < 4.0:
            return False
        # A delayed event loop may not have polled at 1.5s; attempt escalation
        # synchronously before allowing app shutdown to continue.
        self._poll_scrcpy_process()
        if self._scrcpy_process is None:
            return True
        # Do not trap app shutdown if the OS refuses to stop the child process.
        return None

    def prepare_recording_disconnect(self):
        self._recording_stop_requested = True
        if self._recording_remote_path:
            self._stop_screen_recording(show_saved_dialog=False)

    def _on_record_tick(self):
        if not self._recording_remote_path or self._recording_started_at is None:
            return
        self._recording_seconds = int(time.monotonic() - self._recording_started_at)
        m = self._recording_seconds // 60
        s = self._recording_seconds % 60
        self.btn_record_video.setText(f'⏹ Durdur ({m:02d}:{s:02d})')
        self.lbl_status.setText(f'🔴 Canlı TV ekranı kaydediliyor... ({m:02d}:{s:02d})')

        if self._recording_seconds >= 180:
            self._stop_screen_recording()

    def _stop_screen_recording(self, show_saved_dialog=True):
        if self._recording_starting:
            self._recording_stop_requested = True
            return
        if self._recording_finalizing or not self._recording_remote_path:
            return
        if self._recording_timer:
            self._recording_timer.stop()

        proc = self._recording_proc
        target = self._recording_target
        remote_tmp = self._recording_remote_path
        remote_pid = self._recording_pid
        engine = self._recording_engine
        self._recording_finalizing = True
        self._recording_proc = None
        self._recording_target = None
        self._recording_remote_path = None
        self._recording_pid = None
        self._recording_engine = None
        self._recording_started_at = None
        self.btn_record_video.setEnabled(False)
        self.btn_record_video.setText('Aktarılıyor…')
        self.btn_record_video.setStyleSheet('')
        self.lbl_status.setText('Video TV\'den bilgisayara aktarılıyor...')

        def do_finalize():
            local_dest = None
            local_stage = None
            transfer_succeeded = False
            try:
                if engine is None or not target or not remote_tmp:
                    raise RuntimeError('Kayıt hedefi bulunamadı; video güvenli biçimde aktarılamadı.')

                if remote_pid:
                    proc_path = '/proc/{}/cmdline'.format(remote_pid)

                    def process_cmdline():
                        info = engine.shell(target, 'cat', proc_path, timeout=5)
                        if info.exit_code != 0:
                            return ''
                        return (info.output or '').replace('\x00', ' ').lower()

                    running_cmd = process_cmdline()
                    is_our_recording = (
                        'screenrecord' in running_cmd
                        and remote_tmp.lower() in running_cmd
                    )
                    if is_our_recording:
                        stopped = engine.shell(target, 'kill', '-2', remote_pid, timeout=5)
                        if stopped.exit_code != 0:
                            raise RuntimeError(
                                'TV ekran kaydı güvenli biçimde durdurulamadı; uzak dosya korunuyor.')
                        deadline = time.monotonic() + 8.0
                        while time.monotonic() < deadline:
                            running_cmd = process_cmdline()
                            if ('screenrecord' not in running_cmd
                                    or remote_tmp.lower() not in running_cmd):
                                break
                            time.sleep(0.25)
                        else:
                            raise RuntimeError(
                                'TV ekran kaydı durma süresini aştı; uzak dosya korunuyor.')

                if proc and proc.poll() is None:
                    try:
                        proc.wait(timeout=3.0)
                    except subprocess.TimeoutExpired:
                        proc.terminate()
                        try:
                            proc.wait(timeout=2.0)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait(timeout=2.0)

                time.sleep(0.25)
                video_dir = os.path.join(BASE_DIR, 'ekran-videolari')
                os.makedirs(video_dir, exist_ok=True)
                ts_str = time.strftime('%Y%m%d_%H%M%S')
                local_dest = os.path.join(video_dir, f'TV_Kayit_{ts_str}_{os.urandom(3).hex()}.mp4')
                local_stage = local_dest + '.partial'
                engine.pull(target, remote_tmp, local_stage)
                if not _is_complete_mp4(local_stage):
                    raise RuntimeError('Video dosyası eksik veya MP4 olarak tamamlanmamış.')
                os.replace(local_stage, local_dest)
                transfer_succeeded = True
            except Exception as exc:
                if local_stage:
                    try:
                        if os.path.exists(local_stage):
                            os.remove(local_stage)
                    except OSError:
                        pass
                recovery = '{} TV kaydı korundu; daha sonra {} cihazından şu yolu aktarabilirsiniz: {}'.format(
                    exc, target, remote_tmp or '(uzak yol bilinmiyor)')
                try:
                    video_dir = os.path.join(BASE_DIR, 'ekran-videolari')
                    os.makedirs(video_dir, exist_ok=True)
                    note = os.path.join(video_dir, 'Kayit_kurtarma_{}_{}.txt'.format(
                        time.strftime('%Y%m%d_%H%M%S'), os.urandom(3).hex()))
                    with open(note, 'x', encoding='utf-8') as recovery_file:
                        recovery_file.write(recovery + '\n')
                    recovery += '\nYerel kurtarma notu: ' + note
                except OSError:
                    pass
                raise RuntimeError(recovery) from exc
            finally:
                if transfer_succeeded and target and remote_tmp:
                    try:
                        engine.shell(target, 'rm', '-f', remote_tmp)
                    except Exception:
                        pass
            return local_dest

        w = Worker(do_finalize)
        w.preserve_on_close = True
        w._recording_finalize = True
        w._allow_during_disconnect = True
        def cleanup():
            self._recording_finalizing = False
            if not getattr(self.window, '_closing', False):
                self.btn_record_video.setEnabled(True)
                self.btn_record_video.setText('🎥 Video Kaydet')
        w.finished.connect(cleanup)
        def on_done(dest_file):
            self.lbl_status.setText(f'✅ Video kaydedildi: {os.path.basename(dest_file)}')
            if not show_saved_dialog or getattr(self.window, '_close_pending', False):
                return
            reply = QMessageBox.question(
                self,
                'Video Kaydedildi',
                f'TV ekran kaydı başarıyla kaydedildi:\n\n{dest_file}\n\nDosyanın bulunduğu klasörü açmak ister misiniz?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                if sys.platform == 'win32':
                    subprocess.Popen(['explorer', '/select,', os.path.abspath(dest_file)])
                else:
                    subprocess.Popen(['xdg-open', os.path.dirname(dest_file)])

        def on_err(err):
            self.lbl_status.setText('Video aktarılamadı; TV’deki kayıt dosyası silinmedi. Ayrıntılar işlem günlüğünde.')

        try:
            self.window._run(w, on_ok=on_done, on_fail=on_err, desc='Video Kaydı Aktarılıyor')
        except Exception:
            cleanup()
            raise

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

    # ------------------------------------------------------------------
    # Geriye Dönük Uyumluluk (APK Kurma vb.)
    # ------------------------------------------------------------------
    def _install_apk(self):
        context = self._capture_device_context()
        if context is None:
            self.lbl_status.setText('APK kurmak için önce cihaz bağlantısının tamamlanmasını bekleyin.')
            return
        path, _ = QFileDialog.getOpenFileName(self, 'APK Seç', '', 'APK dosyaları (*.apk)')
        if not path:
            return
        base = os.path.basename(path)
        if QMessageBox.question(self, 'Onay — APK Kur',
                                'Kurulsun mu?\n\nHedef: {}\n• {}'.format(context[1], base),
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        self._run_device_action(context, lambda engine, target: engine.install_apk(target, path),
                                'Kumanda: APK kuruluyor: ' + base, self._apk_done)

    def _apk_done(self, _res=None):
        try:
            self.lbl_status.setText('APK kuruldu.')
        except RuntimeError:
            pass
        try:
            self.window.tab_apps.refresh()
        except Exception:
            pass
        QMessageBox.information(self, 'Tamam', 'APK kuruldu. Uygulama listesinden kurulum durumunu kontrol edebilirsiniz.')

    def _install_apks(self):
        context = self._capture_device_context()
        if context is None:
            self.lbl_status.setText('APK kurmak için önce cihaz bağlantısının tamamlanmasını bekleyin.')
            return
        paths, _ = QFileDialog.getOpenFileNames(self, 'Split APK Seç (base + splitler)', '', 'APK (*.apk)')
        if not paths:
            return
        if QMessageBox.question(
                self, 'Onay — Split APK Kur',
                '{} dosya kurulsun mu?\n\nHedef: {}\n{}'.format(
                    len(paths), context[1], '\n'.join('• ' + os.path.basename(p) for p in paths[:8]) +
                    ('\n… ve {} tane daha'.format(len(paths) - 8) if len(paths) > 8 else '')),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes:
            return
        self._run_device_action(context, lambda engine, target: engine.install_apks(target, list(paths)),
            'Kumanda: split APK kuruluyor ({} dosya)'.format(len(paths)), self._apk_done)

    # ------------------------------------------------------------------
    # Link Açma, Uyku Zamanlayıcısı ve Ekran Koruyucu
    # ------------------------------------------------------------------
    def _open_url_on_tv(self):
        context = self._capture_device_context()
        if context is None:
            QMessageBox.information(self, 'Bağlantı Yok', 'Link açmak için önce bir TV cihazına bağlanın.')
            return
        url = self.txt_input.text().strip()
        if not url:
            clip = QApplication.clipboard().text().strip()
            if clip.lower().startswith(('http://', 'https://', 'rtsp://', 'magnet:')):
                url = clip
                self.txt_input.setText(url)
        if not url or not url.lower().startswith(('http://', 'https://', 'rtsp://', 'magnet:')):
            QMessageBox.information(
                self, 'Geçersiz Link',
                'HTTP, HTTPS, RTSP veya magnet bağlantısı girin.'
            )
            return
        def on_ok(_):
            self.lbl_status.setText('Bağlantıyı açma komutu TV’ye gönderildi.')
            if hasattr(self.window, 'append_log'):
                self.window.append_log('Bağlantıyı açma komutu TV’ye gönderildi.', 'INFO')
        self._run_device_action(context, lambda engine, target: engine.open_url(target, url),
                                'TV’de bağlantı açma', on_ok)

    def _reset_sleep_timer(self, message):
        self._sleep_timer.stop()
        self._sleep_generation += 1
        self._sleep_remaining_seconds = 0
        self._sleep_deadline = None
        self._sleep_context = None
        self._sleep_target = None
        self._sleep_dispatching = False
        self.btn_sleep_toggle.setText('▶ Başlat')
        self.btn_sleep_toggle.setEnabled(True)
        self.btn_sleep_toggle.setProperty('role', 'primary')
        self.btn_sleep_toggle.setStyle(self.btn_sleep_toggle.style())
        self.cmb_sleep_duration.setEnabled(True)
        self.lbl_sleep_countdown.setText(message)

    def _toggle_sleep_timer(self):
        if self._sleep_dispatching:
            return
        if self._sleep_deadline is not None:
            self._reset_sleep_timer('Zamanlayıcı iptal edildi.')
            if hasattr(self.window, 'append_log'):
                self.window.append_log('Uyku zamanlayıcısı iptal edildi.', 'INFO')
        else:
            context = self._capture_device_context()
            if (context is None or getattr(self.window, '_closing', False)
                    or getattr(self.window, '_close_pending', False)):
                QMessageBox.information(self, 'Bağlantı Yok', 'Uyku zamanlayıcısını başlatmak için önce TV\'ye bağlanın.')
                return
            duration_text = self.cmb_sleep_duration.currentText()
            minutes = int(duration_text.split()[0])
            self._sleep_generation += 1
            self._sleep_context = context
            self._sleep_target = context[1]
            self._sleep_deadline = time.monotonic() + minutes * 60
            self._sleep_remaining_seconds = minutes * 60
            self._sleep_timer.start(1000)
            self.btn_sleep_toggle.setText('⏹ İptal Et')
            self.btn_sleep_toggle.setProperty('role', 'danger')
            self.btn_sleep_toggle.setStyle(self.btn_sleep_toggle.style())
            self.cmb_sleep_duration.setEnabled(False)
            self._update_sleep_countdown_label()
            if hasattr(self.window, 'append_log'):
                self.window.append_log(f'Uyku zamanlayıcısı başlatıldı: {minutes} dakika sonra uyku komutu gönderilecek.', 'INFO')

    def _on_sleep_timer_tick(self):
        if self._sleep_deadline is None:
            return
        context = self._sleep_context
        if (not self._device_context_current(context) or getattr(self.window, '_close_pending', False)
                or getattr(self.window, '_closing', False)):
            self._reset_sleep_timer('Bağlantı hazır değil veya uygulama kapanıyor; zamanlayıcı iptal edildi.')
            return
        self._sleep_remaining_seconds = max(0, math.ceil(self._sleep_deadline - time.monotonic()))
        if self._sleep_remaining_seconds <= 0:
            self._sleep_timer.stop()
            self._sleep_deadline = None
            self._sleep_dispatching = True
            self.btn_sleep_toggle.setText('Gönderiliyor…')
            self.btn_sleep_toggle.setEnabled(False)
            self.lbl_sleep_countdown.setText('Süre doldu; uyku komutu gönderiliyor…')
            generation = self._sleep_generation
            engine, target, _connection_generation = context
            def do():
                self._require_device_context(context)
                result = engine.keyevent(target, KEYCODE_SLEEP)
                if not result.ok:
                    raise AdbError(result.error or result.output or 'Uyku komutu gönderilemedi.')
                return result
            def done(_):
                if generation != self._sleep_generation:
                    return
                if not self._device_context_current(context):
                    self._reset_sleep_timer('Bağlantı değişti; uyku komutu sonucu doğrulanamadı.')
                    return
                self._reset_sleep_timer('Uyku komutu TV’ye gönderildi.')
                self.window.append_log('Uyku zamanlayıcısı: uyku komutu gönderildi.', 'INFO')
            def failed(_error):
                if generation == self._sleep_generation:
                    self._reset_sleep_timer('Uyku komutu gönderilemedi. Bağlantıyı kontrol edin.')
            try:
                self.window._run(Worker(do), on_ok=done, on_fail=failed, desc='Uyku zamanlayıcısı komutu')
            except Exception:
                failed('')
                raise
        else:
            self._update_sleep_countdown_label()

    def _update_sleep_countdown_label(self):
        mins = self._sleep_remaining_seconds // 60
        secs = self._sleep_remaining_seconds % 60
        self.lbl_sleep_countdown.setText(f'⏳ Kalan süre: {mins:02d}:{secs:02d} · Süre sonunda uyku komutu gönderilecek.')

    def _start_ambient_screensaver(self):
        self._run_device_action(self._capture_device_context(),
            lambda engine, target: engine.start_screensaver(target), 'Ekran koruyucu komutu gönderme',
            lambda _: self.lbl_status.setText('Ekran koruyucu komutu TV’ye gönderildi.'))
