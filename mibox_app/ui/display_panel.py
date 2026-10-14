# -*- coding: utf-8 -*-
"""Ekran, çözünürlük, DPI ve kenar taşması (overscan) yönetim paneli."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QComboBox, QMessageBox, QDialog, QDialogButtonBox, QSpinBox, QGroupBox,
)

from ..workers import Worker
from . import kit


class DisplayPanel(QWidget):
    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._busy = False
        self._build()
        self.core.connection_changed.connect(self._on_connection_changed)

    def _build(self):
        root = kit.page(self)
        root.setSpacing(kit.SPACING)

        # 1. Mevcut Ekran Durumu Kartı
        info_card = QFrame()
        info_card.setObjectName('contentCard')
        info_card.setProperty('role', 'secondary')
        info_lay = QVBoxLayout(info_card)
        info_lay.setContentsMargins(12, 12, 12, 12)
        info_lay.setSpacing(6)

        info_header = QHBoxLayout()
        title = QLabel('Bağlı Ekran & TV Bilgileri')
        title.setObjectName('cardTitle')
        title.setProperty('role', 'primary')
        self.btn_read = QPushButton('Ekranı Sorgula')
        self.btn_read.clicked.connect(self.read_display)
        info_header.addWidget(title)
        info_header.addStretch(1)
        info_header.addWidget(self.btn_read)
        info_lay.addLayout(info_header)

        self.lbl_status = QLabel('Mevcut ekran bilgisi henüz okunmadı. "Ekranı Sorgula" ile mevcut değerleri okuyun.')
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setProperty('role', 'quiet')
        info_lay.addWidget(self.lbl_status)

        metrics = QHBoxLayout()
        metrics.setSpacing(8)
        for label, attr in [
            ('Çözünürlük (Boyut)', 'lbl_res_val'),
            ('Yenileme Hızı (Hz)', 'lbl_fps_val'),
            ('Arayüz Ölçeği (DPI)', 'lbl_dens_val'),
            ('Bağlı TV / Monitör', 'lbl_sink_val'),
        ]:
            box = QFrame()
            box.setObjectName('metricCard')
            box.setProperty('role', 'secondary')
            lay = QVBoxLayout(box)
            lay.setContentsMargins(8, 8, 8, 8)
            lay.setSpacing(3)
            lbl = QLabel(label)
            lbl.setProperty('role', 'quiet')
            val = QLabel('—')
            val.setObjectName('metricValue')
            setattr(self, attr, val)
            lay.addWidget(lbl)
            lay.addWidget(val)
            metrics.addWidget(box, 1)
        info_lay.addLayout(metrics)
        root.addWidget(info_card)

        # 2. Ayarlar Kartı
        settings_group = QGroupBox('Ekran ve Görüntü Yapılandırması')
        set_lay = QVBoxLayout(settings_group)
        set_lay.setContentsMargins(12, 12, 12, 12)
        set_lay.setSpacing(10)

        hint = kit.hint_label(
            'TV ekran çözünürlüğünü ve DPI ölçeğini değiştirebilirsiniz. '
            'Yanlış ayarda siyah ekranda kalmamanız için 15 saniyelik otomatik geri alma koruması bulunur.'
        )
        set_lay.addWidget(hint)

        controls = QHBoxLayout()
        controls.setSpacing(12)

        # Çözünürlük
        res_col = QVBoxLayout()
        res_col.addWidget(QLabel('Çözünürlük (Çıkış Boyutu)'))
        self.cmb_res = QComboBox()
        self.cmb_res.addItem('Değiştirme (Mevcut Kalsın)', None)
        self.cmb_res.addItem('1080p Full HD (1920×1080) · Standart TV', (1920, 1080))
        self.cmb_res.addItem('720p HD (1280×720) · Yüksek Hız / Eski TV', (1280, 720))
        self.cmb_res.addItem('4K UHD (3840×2160) · Ultra HD TV', (3840, 2160))
        self.cmb_res.addItem('Fabrika Çözünürlüğüne Sıfırla', 'reset')
        res_col.addWidget(self.cmb_res)
        controls.addLayout(res_col, 1)

        # DPI
        dpi_col = QVBoxLayout()
        dpi_col.addWidget(QLabel('Arayüz Ölçeği (DPI / Yazı Boyutu)'))
        self.cmb_dpi = QComboBox()
        self.cmb_dpi.addItem('Değiştirme (Mevcut Kalsın)', None)
        self.cmb_dpi.addItem('240 DPI (Kompakt · Ekranda Daha Çok İçerik)', 240)
        self.cmb_dpi.addItem('280 DPI (Dengeli · Orta Ölçek)', 280)
        self.cmb_dpi.addItem('320 DPI (Standart 1080p TV Boyutu)', 320)
        self.cmb_dpi.addItem('360 DPI (Büyük & Kolay Okunur Yazılar)', 360)
        self.cmb_dpi.addItem('Fabrika DPI Değerine Sıfırla', 'reset')
        dpi_col.addWidget(self.cmb_dpi)
        controls.addLayout(dpi_col, 1)

        # Overscan
        ov_col = QVBoxLayout()
        ov_col.addWidget(QLabel('Kenar Taşması (Overscan Kırpılma)'))
        self.cmb_ov = QComboBox()
        self.cmb_ov.addItem('Değiştirme (Mevcut Kalsın)', None)
        self.cmb_ov.addItem('Kenarları Sıfırla (0px · Tam Ekran)', (0, 0, 0, 0))
        self.cmb_ov.addItem('Kenarlardan 15px İçeri Çek (Hafif Kırpılma)', (15, 15, 15, 15))
        self.cmb_ov.addItem('Kenarlardan 30px İçeri Çek (Orta Kırpılma)', (30, 30, 30, 30))
        self.cmb_ov.addItem('Kenarlardan 45px İçeri Çek (Belirgin Kırpılma)', (45, 45, 45, 45))
        ov_col.addWidget(self.cmb_ov)
        controls.addLayout(ov_col, 1)

        set_lay.addLayout(controls)

        btn_row = QHBoxLayout()
        self.btn_apply = QPushButton('Görüntü Ayarlarını Uygula')
        self.btn_apply.setProperty('accent', True)
        self.btn_apply.clicked.connect(self._apply_settings)

        self.btn_reset_all = QPushButton('Tüm Görüntüyü Fabrikaya Sıfırla')
        self.btn_reset_all.setProperty('role', 'quiet')
        self.btn_reset_all.clicked.connect(self._reset_all)

        btn_row.addWidget(self.btn_apply)
        btn_row.addWidget(self.btn_reset_all)
        btn_row.addStretch(1)
        set_lay.addLayout(btn_row)

        root.addWidget(settings_group)
        root.addStretch(1)

    def _on_connection_changed(self, connected, _target):
        if not connected:
            self.lbl_res_val.setText('—')
            self.lbl_fps_val.setText('—')
            self.lbl_dens_val.setText('—')
            self.lbl_sink_val.setText('—')
            self.lbl_status.setText('Bağlı cihaz yok. Cihaza bağlanıp ekranı sorgulayın.')
        else:
            self.read_display()

    def read_display(self):
        if not self.core.connected or not self.core.target:
            QMessageBox.information(self, 'Bağlantı Yok', 'Ekran bilgilerini okumak için önce cihaza bağlanın.')
            return
        target = self.core.target
        engine = self.core.engine

        def do():
            return engine.display_details(target)

        def done(info):
            self.lbl_res_val.setText('{}×{}'.format(info['width'], info['height']))
            self.lbl_fps_val.setText('{} Hz'.format(info['fps']))
            self.lbl_dens_val.setText('{} DPI'.format(info['density']))
            self.lbl_sink_val.setText(info.get('sink_name') or 'Standart TV / Monitör')

            parts = ['Ekran: <b>{}×{}</b> @ {}Hz ({} DPI)'.format(
                info['width'], info['height'], info['fps'], info['density'])]
            if info.get('override_width') or info.get('override_density'):
                parts.append("<font color='#2196f3'>[Özel Ayar Etkin]</font>")
            if info.get('sink_name'):
                parts.append('· ' + info['sink_name'])
            if info.get('overscan'):
                parts.append('· Kenar boşluğu: {}'.format(info['overscan']))
            self.lbl_status.setText(' '.join(parts))

        w = Worker(do)
        w.job_name = 'Ekran Bilgisi Okuma'
        w.finished_ok.connect(done)
        w.failed.connect(lambda err: self.lbl_status.setText('Ekran okunamadı: ' + str(err)))
        self.window._run(w, desc='Ekran: mevcut çözünürlük ve DPI okunuyor')

    def _reset_all(self):
        if not self.core.connected or not self.core.target:
            QMessageBox.information(self, 'Bağlantı Yok', 'Önce cihaza bağlanın.')
            return
        target = self.core.target
        engine = self.core.engine

        def do():
            engine.reset_display_size(target)
            engine.reset_display_density(target)
            engine.reset_display_overscan(target)
            return engine.display_details(target)

        def done(info):
            self.read_display()
            QMessageBox.information(self, 'Görüntü Sıfırlandı',
                                    'Çözünürlük, DPI ölçeği ve kenar taşması fabrika varsayılanına döndürüldü.')

        w = Worker(do)
        w.job_name = 'Görüntü Sıfırlama'
        w.finished_ok.connect(done)
        w.failed.connect(lambda err: QMessageBox.critical(self, 'Hata', 'Görüntü sıfırlanamadı: ' + str(err)))
        self.window._run(w, desc='Ekran: fabrika varsayılanına sıfırlanıyor')

    def _apply_settings(self):
        if not self.core.connected or not self.core.target:
            QMessageBox.information(self, 'Bağlantı Yok', 'Önce cihaza bağlanın.')
            return
        res_choice = self.cmb_res.currentData()
        dens_choice = self.cmb_dpi.currentData()
        ov_choice = self.cmb_ov.currentData()

        if res_choice is None and dens_choice is None and ov_choice is None:
            QMessageBox.information(self, 'Seçim Yapılmadı',
                                    'Uygulamak için çözünürlük, DPI veya kenar taşması seçeneklerinden en az birini belirleyin.')
            return

        target = self.core.target
        engine = self.core.engine

        def do():
            prev_info = engine.display_details(target)
            required = []
            if res_choice is not None:
                required.append('size')
            if dens_choice is not None:
                required.append('density')
            if ov_choice is not None:
                required.append('overscan')
            unreadable = set(required) & set(prev_info.get('read_errors', []))
            if unreadable:
                raise RuntimeError(
                    'Geri alma için mevcut değerler okunamadı: {}. Hiçbir ayar değiştirilmedi.'
                    .format(', '.join(sorted(unreadable))))

            def restore(name):
                if name == 'size':
                    width = prev_info.get('override_width')
                    height = prev_info.get('override_height')
                    if width and height:
                        engine.set_display_size(target, width, height)
                    else:
                        engine.reset_display_size(target)
                elif name == 'density':
                    density = prev_info.get('override_density')
                    if density:
                        engine.set_display_density(target, density)
                    else:
                        engine.reset_display_density(target)
                elif name == 'overscan':
                    overscan = prev_info.get('overscan')
                    if overscan:
                        engine.set_display_overscan(target, *overscan)
                    else:
                        engine.reset_display_overscan(target)

            applied = []
            try:
                if res_choice == 'reset':
                    applied.append('size')
                    engine.reset_display_size(target)
                elif isinstance(res_choice, tuple):
                    applied.append('size')
                    engine.set_display_size(target, res_choice[0], res_choice[1])

                if dens_choice == 'reset':
                    applied.append('density')
                    engine.reset_display_density(target)
                elif isinstance(dens_choice, int):
                    applied.append('density')
                    engine.set_display_density(target, dens_choice)

                if ov_choice is not None:
                    applied.append('overscan')
                    if ov_choice == (0, 0, 0, 0):
                        engine.reset_display_overscan(target)
                    elif isinstance(ov_choice, tuple):
                        engine.set_display_overscan(target, *ov_choice)

                return engine.display_details(target), prev_info
            except Exception as exc:
                rollback_errors = []
                for name in reversed(applied):
                    try:
                        restore(name)
                    except Exception as rollback_exc:
                        rollback_errors.append('{}: {}'.format(name, rollback_exc))
                if rollback_errors:
                    raise RuntimeError(
                        '{}; önceki ayarlar tamamen geri yüklenemedi: {}'.format(
                            exc, '; '.join(rollback_errors))) from exc
                raise

        def on_applied(result):
            new_info, prev_info = result
            self.read_display()
            dlg = QDialog(self)
            dlg.setWindowTitle('Görüntü Ayarı Onayı')
            dlg.setMinimumWidth(380)
            dlay = QVBoxLayout(dlg)
            msg_lbl = QLabel(
                'Yeni görüntü ayarı uygulandı!\n\n'
                '• Çözünürlük: {}×{}\n'
                '• DPI Ölçeği: {}\n\n'
                'Bu ayarı korumak istiyor musunuz?\n'
                'Onaylamazsanız görüntü otomatik olarak önceki haline dönecektir.'.format(
                    new_info['width'], new_info['height'], new_info['density'])
            )
            msg_lbl.setWordWrap(True)
            dlay.addWidget(msg_lbl)

            countdown_lbl = QLabel('Kalan süre: 15 saniye')
            countdown_lbl.setStyleSheet('font-weight: bold; color: #ff9800;')
            dlay.addWidget(countdown_lbl)

            btns = QDialogButtonBox()
            btn_keep = btns.addButton('Ayarları Koru', QDialogButtonBox.AcceptRole)
            btn_revert = btns.addButton('Geri Al', QDialogButtonBox.RejectRole)
            btn_keep.setProperty('accent', True)
            dlay.addWidget(btns)

            seconds_left = [15]
            timer = QTimer(dlg)

            def tick():
                seconds_left[0] -= 1
                if seconds_left[0] <= 0:
                    timer.stop()
                    dlg.reject()
                else:
                    countdown_lbl.setText('Kalan süre: {} saniye'.format(seconds_left[0]))

            timer.timeout.connect(tick)
            timer.start(1000)

            btn_keep.clicked.connect(lambda: (timer.stop(), dlg.accept()))
            btn_revert.clicked.connect(lambda: (timer.stop(), dlg.reject()))

            if dlg.exec() != QDialog.Accepted:
                timer.stop()
                self._revert(prev_info, target)

        w = Worker(do)
        w.job_name = 'Görüntü Ayarlama'
        w.finished_ok.connect(on_applied)

        def on_failed(error):
            self.read_display()
            QMessageBox.critical(self, 'Görüntü Hatası', str(error))

        w.failed.connect(on_failed)
        self.window._run(w, desc='Ekran: yeni çözünürlük/DPI uygulanıyor')

    def _revert(self, prev_info, target):
        engine = self.core.engine

        def do():
            if prev_info.get('override_width'):
                engine.set_display_size(target, prev_info['override_width'], prev_info['override_height'])
            else:
                engine.reset_display_size(target)

            if prev_info.get('override_density'):
                engine.set_display_density(target, prev_info['override_density'])
            else:
                engine.reset_display_density(target)

            if prev_info.get('overscan'):
                engine.set_display_overscan(target, *prev_info['overscan'])
            else:
                engine.reset_display_overscan(target)
            return engine.display_details(target)

        w = Worker(do)
        w.finished_ok.connect(lambda _: (
            self.read_display(),
            QMessageBox.information(self, 'Geri Alındı', 'Görüntü ayarları önceki durumuna geri döndürüldü.')
        ))
        self.window._run(w, desc='Ekran: ayarlar geri alınıyor')
