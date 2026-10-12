# -*- coding: utf-8 -*-
"""Kumanda sekmesi: ADB keyevent tabanli uzaktan kumanda."""
import datetime
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QPushButton, QLineEdit, QComboBox, QMessageBox, QCheckBox,
    QFileDialog,
)

from ..config import SHOT_DIR
from ..workers import Worker, DeviceInfoWorker
from . import kit
from .flowlayout import FlowLayout

KEYS = {
    'guc': [
        ('GUC', 26), ('Uyku', 223), ('Uyan', 224),
    ],
    'ses': [
        ('Ses +', 24), ('Ses -', 25), ('Sessiz', 164),
    ],
    'media': [
        ('Oynat/Duraklat', 85), ('Durdur', 86),
        ('Onceki', 88), ('Sonraki', 87),
        ('Geri Sar', 90), ('Hizli Sar', 91),
        ('Kayit', 130),
    ],
    'navigasyon': [
        ('Yukari', 19), ('Asagi', 20), ('Sol', 21), ('Sag', 22),
        ('OK', 23), ('Geri', 4), ('Ana Ekran', 3), ('Menu', 82),
        ('Ayarlar', 176),
    ],
}


class RemoteTab(QWidget):
    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._busy = False  # tus islemi surerken cift tik kilidi
        self._shot_data = None  # son goruntu (resize'da yeniden olcekle)
        self._build()

    def _key_button(self, label, code, min_h=44, min_w=0, tooltip=''):
        b = QPushButton(label)
        b.setMinimumHeight(min_h)
        if min_w:
            b.setMinimumWidth(min_w)
        if tooltip:
            b.setToolTip(tooltip)
        b.clicked.connect(lambda _=False, c=code, l=label: self._send_key(c, l))
        return b

    def _build_remote_body(self):
        """Fiziksel kumanda govdesi: dar, dikey, ortali kart.

        Duzen (ustten alta):
          1. GUC satiri (GUC kirmizi + Uyku + Uyan)
          2. D-Pad halka: Yukari / Sol-OK-Sag / Asagi
          3. Geri + Ana Ekran + Menu (D-Pad alti)
          4. Ses cubugu: Ses- / Sessiz / Ses+ (yan yana, yuksek buton)
          5. Media: Oynat/Duraklat genis + Onceki/Sonraki + Geri/Hizli sar
        """
        body = QVBoxLayout()
        body.setSpacing(8)

        # --- 1. guc satiri ---
        power_row = QHBoxLayout()
        power_row.setSpacing(6)
        b_power = self._key_button('⏻ GUC', 26, min_h=48, tooltip='Guc (key 26)')
        b_power.setProperty('danger', True)
        b_sleep = self._key_button('Uyku', 223, min_h=48, tooltip='Uyku (key 223)')
        b_wake = self._key_button('Uyan', 224, min_h=48, tooltip='Uyan (key 224)')
        power_row.addWidget(b_power, 1)
        power_row.addWidget(b_sleep, 1)
        power_row.addWidget(b_wake, 1)
        body.addLayout(power_row)

        # --- 2. D-Pad halka ---
        pad = QGridLayout()
        pad.setSpacing(6)
        self._pad_btn(pad, '▲', 19, 0, 1, tooltip='Yukari (key 19)')
        self._pad_btn(pad, '◀', 21, 1, 0, tooltip='Sol (key 21)')
        self._pad_btn(pad, 'OK', 23, 1, 1, accent=True, tooltip='OK (key 23)')
        self._pad_btn(pad, '▶', 22, 1, 2, tooltip='Sag (key 22)')
        self._pad_btn(pad, '▼', 20, 2, 1, tooltip='Asagi (key 20)')
        body.addLayout(pad)

        # --- 3. Geri / Ana Ekran / Menu ---
        nav_row = QHBoxLayout()
        nav_row.setSpacing(6)
        nav_row.addWidget(self._key_button('⟨ Geri', 4, min_h=44, tooltip='Geri (key 4)'))
        nav_row.addWidget(self._key_button('⌂ Home', 3, min_h=44, tooltip='Ana Ekran (key 3)'))
        nav_row.addWidget(self._key_button('☰ Menu', 82, min_h=44, tooltip='Menu (key 82)'))
        body.addLayout(nav_row)
        home_row = QHBoxLayout()
        home_row.setSpacing(6)
        home_row.addWidget(self._key_button('Ayarlar', 176, min_h=40, tooltip='Ayarlar (key 176)'))
        body.addLayout(home_row)

        # --- 4. ses cubugu ---
        vol_row = QHBoxLayout()
        vol_row.setSpacing(6)
        vol_row.addWidget(self._key_button('Ses −', 25, min_h=56, tooltip='Ses azalt (key 25)'))
        vol_row.addWidget(self._key_button('Sessiz', 164, min_h=56, tooltip='Sessiz (key 164)'))
        vol_row.addWidget(self._key_button('Ses +', 24, min_h=56, tooltip='Ses artir (key 24)'))
        body.addLayout(vol_row)

        # --- 5. media ---
        media_play = self._key_button('⏯ Oynat/Duraklat', 85, min_h=44,
                                      tooltip='Oynat/Duraklat (key 85)')
        body.addWidget(media_play)
        media_row = QHBoxLayout()
        media_row.setSpacing(6)
        prev_btn = self._key_button('⏮ Onceki', 88, min_h=40)
        next_btn = self._key_button('⏭ Sonraki', 87, min_h=40)
        kit.fit_buttons(prev_btn, next_btn)
        media_row.addWidget(prev_btn)
        media_row.addWidget(next_btn)
        body.addLayout(media_row)
        seek_row = FlowLayout()
        seek_row.addWidget(self._key_button('⏪ Geri Sar', 90, min_h=40))
        seek_row.addWidget(self._key_button('Durdur', 86, min_h=40))
        seek_row.addWidget(self._key_button('Hizli Sar ⏩', 91, min_h=40))
        body.addLayout(seek_row)
        return body

    def _build(self):
        root = kit.page(self)

        # --- Uygulama acma ---
        g_launch = QGroupBox('Uygulama Ac')
        gl = QHBoxLayout(g_launch)
        gl.setSpacing(4)
        self.cmb_app = QComboBox()
        self.cmb_app.setPlaceholderText('Uygulama sec (once Uygulamalar sekmesini yenileyin)')
        self.cmb_app.setMinimumWidth(200)
        self.cmb_app.setEditable(True)
        self.cmb_app.lineEdit().setPlaceholderText('Uygulama sec veya paket yaz...')
        self.btn_launch = QPushButton('Ac')
        self.btn_launch.setProperty('accent', True)
        self.btn_launch.clicked.connect(self._launch_selected)
        gl.addWidget(self.cmb_app, 1)
        gl.addWidget(self.btn_launch)
        root.addWidget(g_launch)

        # --- Kumanda govdesi: sol panel + ORTALI kumanda + sag panel ---
        mid_row = QHBoxLayout()
        mid_row.setSpacing(8)

        # sol: metin gonder (bos alani doldurur)
        g_left = QGroupBox('Metin Gonder')
        left_v = QVBoxLayout(g_left)
        left_v.setSpacing(4)
        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText('TV e gonderilecek metin...')
        self.txt_input.returnPressed.connect(self._send_text)
        btn_send = QPushButton('Gonder')
        btn_send.clicked.connect(self._send_text)
        self.lbl_text_hint = QLabel('')
        self.lbl_text_hint.setStyleSheet(kit.faint(kit.dark_from(self)))
        self.lbl_key_hint = QLabel('Ipucu: tuslara tikla; son basilan asagida yazar.')
        self.lbl_key_hint.setStyleSheet(kit.faint(kit.dark_from(self)))
        self.lbl_key_hint.setWordWrap(True)
        left_v.addWidget(self.txt_input)
        left_v.addWidget(btn_send)
        left_v.addWidget(self.lbl_text_hint)
        left_v.addWidget(self.lbl_key_hint)
        left_v.addStretch()
        mid_row.addWidget(g_left, 1)

        # orta: kumanda (sabit genislik, her iki yanda esit boslukla ortali)
        mid_row.addStretch()
        g_remote = QGroupBox('Kumanda')
        g_remote.setMinimumWidth(380)
        g_remote.setMaximumWidth(440)
        g_remote.setLayout(self._build_remote_body())
        mid_row.addWidget(g_remote)
        mid_row.addStretch()

        # sag: durum + ekran goruntusu (bos alani doldurur)
        g_right = QGroupBox('Durum / Goruntu')
        right_v = QVBoxLayout(g_right)
        right_v.setSpacing(4)
        self.lbl_status = QLabel('Hazir.')
        self.lbl_status.setStyleSheet(kit.muted(kit.dark_from(self)))
        self.lbl_status.setWordWrap(True)
        right_v.addWidget(self.lbl_status)
        self.lbl_shot = QLabel('Henuz alinmadi.')
        self.lbl_shot.setAlignment(Qt.AlignCenter)
        self.lbl_shot.setMinimumSize(200, 120)
        self.lbl_shot.setMaximumHeight(220)
        self.lbl_shot.setStyleSheet('border: 1px solid {}; border-radius: 6px;'.format(kit.colors(self)['border']))
        self.lbl_shot.setScaledContents(False)
        right_v.addWidget(self.lbl_shot)
        shot_row = QHBoxLayout()
        shot_row.setSpacing(4)
        self.btn_shot = QPushButton('Goruntu Al')
        self.btn_shot.clicked.connect(self._screenshot)
        self.chk_hd = QCheckBox('HD')
        self.chk_hd.setToolTip('internal_display ile yuksek cozunurluk')
        self.chk_hd.setChecked(self.core.config.screenshot_hd)
        self.chk_hd.toggled.connect(self._on_hd_toggle)
        self.btn_shot_open = QPushButton('Klasor')
        self.btn_shot_open.clicked.connect(self._open_shot_dir)
        shot_row.addWidget(self.btn_shot)
        shot_row.addWidget(self.chk_hd)
        shot_row.addWidget(self.btn_shot_open)
        right_v.addLayout(shot_row)
        right_v.addStretch()
        mid_row.addWidget(g_right, 1)

        root.addLayout(mid_row, 1)

        # --- Cihaz islemleri (FlowLayout) ---
        g_dev = QGroupBox('Cihaz Islemleri')
        dev_wrap = QVBoxLayout(g_dev)
        dev_wrap.setSpacing(4)
        flow = FlowLayout()
        self.btn_info = QPushButton('Cihaz Bilgisi')
        self.btn_info.clicked.connect(self._device_info)
        self.btn_reboot = QPushButton('Yeniden Baslat')
        self.btn_reboot.setProperty('danger', True)
        self.btn_reboot.clicked.connect(self._reboot)
        self.cmb_reboot = QComboBox()
        self.cmb_reboot.addItems(['Sistem', 'Recovery', 'Bootloader'])
        self.btn_cache = QPushButton('Onbellegi Temizle')
        self.btn_cache.clicked.connect(self._trim_caches)
        self.btn_apk = QPushButton('APK Kur')
        self.btn_apk.clicked.connect(self._install_apk)
        self.btn_apks = QPushButton('Split APK Kur')
        self.btn_apks.clicked.connect(self._install_apks)
        self.btn_sleep = QPushButton('Uyut')
        self.btn_sleep.clicked.connect(lambda: self._send_key(223, 'Uyku'))
        self.btn_wake = QPushButton('Uyandir')
        self.btn_wake.clicked.connect(lambda: self._send_key(224, 'Uyan'))
        for b in (self.btn_info, self.btn_reboot, self.cmb_reboot, self.btn_sleep,
                  self.btn_wake, self.btn_cache, self.btn_apk, self.btn_apks):
            flow.addWidget(b)
        dev_wrap.addLayout(flow)
        root.addWidget(g_dev)

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
        b.setMinimumSize(88, 56)
        if accent:
            b.setProperty('accent', True)
        if tooltip:
            b.setToolTip(tooltip)
        f = b.font()
        f.setBold(True)
        f.setPointSize(13)
        b.setFont(f)
        names = {19: 'Yukari', 20: 'Asagi', 21: 'Sol', 22: 'Sag', 23: 'OK'}
        b.clicked.connect(lambda _=False, co=code: self._send_key(co, names.get(co, label)))
        layout.addWidget(b, r, c)

    def _on_hd_toggle(self, on):
        self.core.config.screenshot_hd = bool(on)
        self.core.config.save()

    def populate_apps(self, apps):
        """AppsTab taramasindan sonra cagrilir."""
        cur = self.cmb_app.currentData() or self.cmb_app.currentText()
        self.cmb_app.blockSignals(True)
        self.cmb_app.clear()
        for a in apps:
            self.cmb_app.addItem('{}  ({})'.format(a['name'], a['package']), a['package'])
        self.cmb_app.blockSignals(False)
        if cur:
            for i in range(self.cmb_app.count()):
                if self.cmb_app.itemData(i) == cur or self.cmb_app.itemText(i) == cur:
                    self.cmb_app.setCurrentIndex(i)
                    break

    # ------------------------------------------------------------------
    def _send_key(self, code, label):
        # Hizli tik yagmurunda ADB kuyrugu siser; kisa kilit + desc log.
        if self._busy:
            return
        self._busy = True

        def do():
            try:
                self.core.engine.keyevent(self.core.target, code)
                return label
            finally:
                pass
        w = Worker(do)
        w.job_name = 'Tus: ' + str(label)
        w.finished_ok.connect(self._key_done)
        try:
            w.failed.connect(lambda _e: setattr(self, '_busy', False))
        except Exception:
            pass
        self.window._run(w, desc='Kumanda: {} (key {})'.format(label, code))

    def _key_done(self, label):
        self._busy = False
        try:
            self.lbl_status.setText('Son tus: ' + str(label))
        except RuntimeError:
            pass

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
        pkg = self.cmb_app.currentData()
        if not pkg:
            typed = self.cmb_app.currentText().strip()
            # "Ad (paket)" veya direkt paket girilmis olabilir
            if '(' in typed and ')' in typed:
                pkg = typed.rsplit('(', 1)[-1].rstrip(') ').strip()
            else:
                pkg = typed
        if not pkg:
            QMessageBox.information(self, 'Uygulama', 'Once Uygulamalar sekmesinden liste yenileyin.')
            return
        try:
            name = self.core.config.friendly_name(pkg)
        except Exception:
            name = pkg
        shown = pkg_lines([pkg], lambda _p: name)[0]
        if QMessageBox.question(self, 'Ac', u'Açılsın mı?\n\n{}'.format(shown),
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return

        def do():
            self.core.engine.launch_resolved(self.core.target, pkg)
            return pkg
        w = Worker(do)
        w.job_name = 'Uygulama acma'
        w.finished_ok.connect(lambda p: self.lbl_status.setText('Acildi: ' + p))
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
        hd = self.chk_hd.isChecked()

        def do():
            eng = self.core.engine
            t = self.core.target
            eng.connect(t)
            if hd:
                try:
                    data = eng.screenshot_hd(t)
                except Exception:
                    data = eng.screenshot(t)
            else:
                data = eng.screenshot(t)
            if not data or data[1:4] != b'PNG':
                raise RuntimeError('Ekran goruntusu bozuk indi (PNG degil).')
            return data

        w = Worker(do)
        w.finished_ok.connect(self._save_shot)
        self.window._run(w)

    def _save_shot(self, data):
        try:
            os.makedirs(SHOT_DIR, exist_ok=True)
            path = os.path.join(SHOT_DIR, 'mibox-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '.png')
            with open(path, 'wb') as f:
                f.write(data)
            self.lbl_status.setText('Kaydedildi: ' + os.path.basename(path))
            self._shot_data = bytes(data)
            self._fit_shot()
            QMessageBox.information(self, 'Tamam', 'Ekran goruntusu kaydedildi:\n' + path)
        except OSError as e:
            QMessageBox.critical(self, 'Hata', str(e))

    def _fit_shot(self):
        """Kayitli goruntuyu etiket boyutuna sigdir (orani koru)."""
        try:
            if not self._shot_data:
                return
            pix = QPixmap()
            if not pix.loadFromData(self._shot_data):
                self.lbl_status.setText('PNG okunamadi.')
                return
            size = self.lbl_shot.size()
            if size.width() < 10 or size.height() < 10:
                size = self.lbl_shot.minimumSize()
            self.lbl_shot.setPixmap(pix.scaled(
                size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except RuntimeError:
            pass
        except Exception:
            pass

    def resizeEvent(self, e):
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
        w.finished_ok.connect(lambda _: self.lbl_status.setText('Onbellegi temizlendi.'))
        self.window._run(w)

    def _install_apk(self):
        path, _ = QFileDialog.getOpenFileName(self, 'APK Sec', '', 'APK dosyalari (*.apk)')
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
        paths, _ = QFileDialog.getOpenFileNames(self, 'Split APK Sec (base + splitler)', '', 'APK (*.apk)')
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
