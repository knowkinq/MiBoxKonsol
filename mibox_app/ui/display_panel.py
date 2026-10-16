# -*- coding: utf-8 -*-
"""Ekran, çözünürlük, DPI ve kenar taşması (overscan) yönetim paneli."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QBoxLayout, QGridLayout, QFrame, QLabel,
    QPushButton, QComboBox, QMessageBox, QDialog, QDialogButtonBox,
)

from ..workers import Worker, CancelledError
from . import kit


class _DisplayComboBox(QComboBox):
    """Keep display settings unchanged when scrolling the page."""

    def wheelEvent(self, event):
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()


class DisplayPanel(QWidget):
    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._jobs = set()
        self._confirming = False
        self._generation = 0
        self._read_worker = None
        self._read_token = None
        self._close_after_transaction = False
        self._build()
        self.core.connection_changed.connect(self._on_connection_changed)

    def _build(self):
        root = kit.page(self)
        root.setSpacing(kit.SPACING)
        self._cards = QBoxLayout(QBoxLayout.LeftToRight)
        self._cards.setSpacing(12)
        root.addLayout(self._cards)

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
        title.setWordWrap(True)
        self.btn_read = QPushButton('Ekranı Sorgula')
        self.btn_read.clicked.connect(self.read_display)
        info_header.addWidget(title)
        info_header.addStretch(1)
        info_header.addWidget(self.btn_read)
        info_lay.addLayout(info_header)

        self.lbl_status = QLabel('Mevcut ekran bilgisi henüz okunmadı. "Ekranı Sorgula" ile mevcut değerleri okuyun.')
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setTextFormat(Qt.PlainText)
        self.lbl_status.setProperty('role', 'quiet')
        info_lay.addWidget(self.lbl_status)

        metrics = QGridLayout()
        metrics.setSpacing(8)
        for index, (label, attr) in enumerate([
            ('Çözünürlük (Boyut)', 'lbl_res_val'),
            ('Yenileme Hızı (Hz)', 'lbl_fps_val'),
            ('Arayüz Ölçeği (DPI)', 'lbl_dens_val'),
            ('Bağlı TV / Monitör', 'lbl_sink_val'),
        ]):
            box = QFrame()
            box.setObjectName('metricCard')
            box.setProperty('role', 'secondary')
            lay = QVBoxLayout(box)
            lay.setContentsMargins(8, 8, 8, 8)
            lay.setSpacing(3)
            lbl = QLabel(label)
            lbl.setWordWrap(True)
            lbl.setProperty('role', 'quiet')
            val = QLabel('—')
            val.setWordWrap(True)
            val.setTextFormat(Qt.PlainText)
            val.setObjectName('metricValue')
            setattr(self, attr, val)
            lay.addWidget(lbl)
            lay.addWidget(val)
            metrics.addWidget(box, index // 2, index % 2)
        metrics.setColumnStretch(0, 1)
        metrics.setColumnStretch(1, 1)
        info_lay.addLayout(metrics)
        info_lay.addStretch(1)
        self._cards.addWidget(info_card, 2)

        # 2. Ayarlar Kartı
        settings_group = QFrame()
        settings_group.setObjectName('contentCard')
        settings_group.setProperty('role', 'secondary')
        set_lay = QVBoxLayout(settings_group)
        set_lay.setContentsMargins(12, 12, 12, 12)
        set_lay.setSpacing(10)
        heading = QLabel('Görüntü ayarları')
        heading.setObjectName('cardTitle')
        heading.setProperty('role', 'primary')
        set_lay.addWidget(heading)

        hint = kit.hint_label(
            'TV ekran çözünürlüğünü ve DPI ölçeğini değiştirebilirsiniz. '
            'Yanlış ayarda siyah ekranda kalmamanız için 15 saniyelik otomatik geri alma koruması bulunur.'
        )
        set_lay.addWidget(hint)

        controls = QVBoxLayout()
        controls.setSpacing(10)

        # Çözünürlük
        res_col = QVBoxLayout()
        res_col.addWidget(QLabel('Çözünürlük (Çıkış Boyutu)'))
        self.cmb_res = _DisplayComboBox()
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
        self.cmb_dpi = _DisplayComboBox()
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
        self.cmb_ov = _DisplayComboBox()
        self.cmb_ov.addItem('Değiştirme (Mevcut Kalsın)', None)
        self.cmb_ov.addItem('Kenarları Sıfırla (0px · Tam Ekran)', (0, 0, 0, 0))
        self.cmb_ov.addItem('Kenarlardan 15px İçeri Çek (Hafif Kırpılma)', (15, 15, 15, 15))
        self.cmb_ov.addItem('Kenarlardan 30px İçeri Çek (Orta Kırpılma)', (30, 30, 30, 30))
        self.cmb_ov.addItem('Kenarlardan 45px İçeri Çek (Belirgin Kırpılma)', (45, 45, 45, 45))
        ov_col.addWidget(self.cmb_ov)
        controls.addLayout(ov_col, 1)

        set_lay.addLayout(controls)

        btn_row = QVBoxLayout()
        self.btn_apply = QPushButton('Görüntü Ayarlarını Uygula')
        self.btn_apply.setProperty('accent', True)
        self.btn_apply.clicked.connect(self._apply_settings)

        self.btn_reset_all = QPushButton('Tüm Görüntüyü Fabrikaya Sıfırla')
        self.btn_reset_all.setProperty('role', 'quiet')
        self.btn_reset_all.clicked.connect(self._reset_all)

        btn_row.addWidget(self.btn_apply)
        btn_row.addWidget(self.btn_reset_all)
        set_lay.addLayout(btn_row)
        set_lay.addStretch(1)

        self._cards.addWidget(settings_group, 3)
        root.addStretch(1)

        for combo in (self.cmb_res, self.cmb_dpi, self.cmb_ov):
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(20)
            combo.setMinimumHeight(34)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        direction = (QBoxLayout.LeftToRight if self.width() >= 900
                     else QBoxLayout.TopToBottom)
        self._cards.setDirection(direction)

    def _on_connection_changed(self, connected, _target):
        self._generation += 1
        self._invalidate_read()
        for combo in (self.cmb_res, self.cmb_dpi, self.cmb_ov):
            combo.setCurrentIndex(0)
        self.lbl_res_val.setText('—')
        self.lbl_fps_val.setText('—')
        self.lbl_dens_val.setText('—')
        self.lbl_sink_val.setText('—')
        if not connected:
            self.lbl_status.setText('Bağlı cihaz yok. Cihaza bağlanıp ekranı sorgulayın.')
        else:
            self.read_display()

    def _invalidate_read(self):
        self._read_token = None
        if self._read_worker is not None:
            self._read_worker.cancel()
            self._read_worker = None

    def read_display(self):
        if (getattr(self.window, '_closing', False)
                or getattr(self.window, '_close_pending', False)):
            return
        if self._read_worker is not None:
            return
        if (not self.core.connected or not self.core.target
                or getattr(self.window, '_connection_busy', False)):
            QMessageBox.information(self, 'Bağlantı Yok', 'Ekran bilgilerini okumak için önce cihaza bağlanın.')
            return
        target = self.core.target
        generation = self._generation
        try:
            engine = self.core.engine
        except Exception as error:
            self.lbl_status.setText('Cihaz motoru hazır değil: ' + str(error))
            return
        token = object()
        self._read_token = token
        current = lambda: (self.core.connected and self.core.target == target
                           and self._generation == generation and self._read_token is token
                           and self.core.engine is engine
                           and not getattr(self.window, '_connection_busy', False)
                           and not getattr(self.window, '_closing', False)
                           and not getattr(self.window, '_close_pending', False))

        def do():
            if not current():
                raise CancelledError('Bağlantı değişti.')
            return engine.display_details(target)

        def done(info):
            if not current():
                return
            self.lbl_res_val.setText('{}×{}'.format(info['width'], info['height']))
            self.lbl_fps_val.setText('{} Hz'.format(info['fps']))
            self.lbl_dens_val.setText('{} DPI'.format(info['density']))
            self.lbl_sink_val.setText(info.get('sink_name') or 'Standart TV / Monitör')

            parts = ['Ekran: {}×{} @ {}Hz ({} DPI)'.format(
                info['width'], info['height'], info['fps'], info['density'])]
            if info.get('override_width') or info.get('override_density'):
                parts.append('· Özel ayar etkin')
            if info.get('sink_name'):
                parts.append('· ' + info['sink_name'])
            if info.get('overscan'):
                parts.append('· Kenar boşluğu: {}'.format(info['overscan']))
            self.lbl_status.setText(' '.join(parts))

        w = Worker(do)
        self._read_worker = w
        w.job_name = 'Ekran Bilgisi Okuma'
        w.finished_ok.connect(done)
        w.failed.connect(lambda err: self.lbl_status.setText('Ekran okunamadı: ' + str(err))
                         if current() else None)
        def cleanup():
            if self._read_worker is w:
                self._read_worker = None
        w.finished.connect(cleanup)
        self.lbl_status.setText('Mevcut ekran bilgileri okunuyor…')
        try:
            self.window._run(w, desc='Ekran: mevcut çözünürlük ve DPI okunuyor')
        except Exception as error:
            cleanup()
            if not getattr(self.window, '_closing', False):
                self.lbl_status.setText('Ekran bilgisi okuması başlatılamadı: ' + str(error))

    def _ready(self):
        if (getattr(self.window, '_closing', False)
                or getattr(self.window, '_close_pending', False)):
            return False
        if self._jobs or self._confirming or self._read_worker is not None:
            self.lbl_status.setText('Devam eden ekran işleminin bitmesini bekleyin.')
            return False
        if (not self.core.connected or not self.core.target
                or getattr(self.window, '_connection_busy', False)):
            self.lbl_status.setText('Önce bir cihaza bağlanın.')
            return False
        return True

    def _update_controls(self):
        enabled = not self._jobs and not self._confirming
        for widget in (self.btn_read, self.btn_apply, self.btn_reset_all,
                       self.cmb_res, self.cmb_dpi, self.cmb_ov):
            widget.setEnabled(enabled)

    def _run_change(self, worker, description):
        if (getattr(self.window, '_closing', False)
                or getattr(self.window, '_close_pending', False)):
            return
        self._invalidate_read()
        self._jobs.add(worker)
        self._update_controls()
        def cleanup():
            self._jobs.discard(worker)
            self._update_controls()
            self._maybe_close_after_transaction()
        worker.finished.connect(cleanup)
        try:
            self.window._run(worker, desc=description)
            if worker not in getattr(self.window, '_workers', ()) and not worker.isRunning():
                cleanup()
        except Exception as error:
            cleanup()
            if not getattr(self.window, '_closing', False):
                self.lbl_status.setText('Ekran işlemi başlatılamadı: ' + str(error))

    def _has_pending_display_transaction(self):
        return (self._confirming or any(
            getattr(worker, 'job_name', '') in (
                'Görüntü Ayarlama', 'Görüntü Sıfırlama', 'Ekran ayarı geri alma')
            for worker in self._jobs))

    def _maybe_close_after_transaction(self):
        if not self._close_after_transaction or self._has_pending_display_transaction():
            return
        self._close_after_transaction = False
        QTimer.singleShot(0, self.window.close)

    def _reset_all(self):
        if not self._ready():
            return
        target = self.core.target
        generation = self._generation
        try:
            engine = self.core.engine
        except Exception as error:
            self.lbl_status.setText('Cihaz motoru hazır değil: ' + str(error))
            return
        current = lambda: (self.core.connected and self.core.target == target
                          and self._generation == generation and self.core.engine is engine
                          and not getattr(self.window, '_connection_busy', False)
                          and not getattr(self.window, '_closing', False)
                          and not getattr(self.window, '_close_pending', False))
        if QMessageBox.question(self, 'Görüntüyü sıfırla',
                                'Çözünürlük, DPI ve kenar boşlukları fabrika değerlerine döndürülsün mü?',
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        if not current() or not self._ready():
            return

        def do():
            w.check_cancel()
            if not current():
                raise CancelledError('Bağlantı değişti; görüntü sıfırlama durduruldu.')
            previous = engine.display_details(target)
            unreadable = set(('size', 'density', 'overscan')) & set(previous.get('read_errors', []))
            if unreadable:
                raise RuntimeError(
                    'Geri alma için mevcut değerler okunamadı: {}. Hiçbir ayar değiştirilmedi.'
                    .format(', '.join(sorted(unreadable))))

            def restore(field):
                if field == 'size':
                    width, height = previous.get('override_width'), previous.get('override_height')
                    if width and height:
                        engine.set_display_size(target, width, height)
                    else:
                        engine.reset_display_size(target)
                elif field == 'density':
                    density = previous.get('override_density')
                    if density:
                        engine.set_display_density(target, density)
                    else:
                        engine.reset_display_density(target)
                elif field == 'overscan':
                    overscan = previous.get('overscan')
                    if overscan:
                        engine.set_display_overscan(target, *overscan)
                    else:
                        engine.reset_display_overscan(target)

            attempted = []
            try:
                for field, action in (
                        ('size', engine.reset_display_size),
                        ('density', engine.reset_display_density),
                        ('overscan', engine.reset_display_overscan)):
                    w.check_cancel()
                    if not current():
                        raise CancelledError('Bağlantı değişti; görüntü sıfırlama durduruldu.')
                    attempted.append(field)
                    action(target)
                w.check_cancel()
                if not current():
                    raise CancelledError('Bağlantı değişti; görüntü sıfırlama durduruldu.')
                info = engine.display_details(target)
                w.check_cancel()
                if not current():
                    raise CancelledError('Bağlantı değişti; görüntü sıfırlama durduruldu.')
                return info
            except Exception as apply_error:
                rollback_errors = []
                for field in reversed(attempted):
                    try:
                        restore(field)
                    except Exception as rollback_error:
                        rollback_errors.append('{}: {}'.format(field, rollback_error))
                if 'overscan' in attempted and previous.get('overscan') is None:
                    rollback_errors.append(
                        'Kenar taşmasının işlem öncesi değeri cihazdan okunamadı; fabrika değerine dönmüş olabilir.')
                if rollback_errors:
                    raise RuntimeError(
                        'Görüntü sıfırlama tamamlanamadı: {}. Önceki ayarların tümü geri yüklenemedi: {}'
                        .format(apply_error, '; '.join(rollback_errors))) from apply_error
                raise

        def done(_info):
            if not current():
                return
            self.read_display()
            QMessageBox.information(self, 'Görüntü Sıfırlandı',
                                    'Çözünürlük, DPI ölçeği ve kenar taşması fabrika varsayılanına döndürüldü.')

        w = Worker(do)
        w.job_name = 'Görüntü Sıfırlama'
        w.finished_ok.connect(done)
        w.failed.connect(lambda err: QMessageBox.critical(
            self, 'Hata', 'Görüntü sıfırlanamadı: ' + str(err)) if current() else None)
        self._run_change(w, 'Ekran: fabrika varsayılanına sıfırlanıyor')

    def _apply_settings(self):
        if not self._ready():
            return
        res_choice = self.cmb_res.currentData()
        dens_choice = self.cmb_dpi.currentData()
        ov_choice = self.cmb_ov.currentData()

        if res_choice is None and dens_choice is None and ov_choice is None:
            QMessageBox.information(self, 'Seçim Yapılmadı',
                                    'Uygulamak için çözünürlük, DPI veya kenar taşması seçeneklerinden en az birini belirleyin.')
            return

        target = self.core.target
        generation = self._generation
        try:
            engine = self.core.engine
        except Exception as error:
            self.lbl_status.setText('Cihaz motoru hazır değil: ' + str(error))
            return
        current = lambda: (self.core.connected and self.core.target == target
                           and self._generation == generation and self.core.engine is engine
                           and not getattr(self.window, '_connection_busy', False)
                           and not getattr(self.window, '_closing', False)
                           and not getattr(self.window, '_close_pending', False))

        def do():
            w.check_cancel()
            if not current():
                raise CancelledError('Bağlantı değişti.')
            prev_info = engine.display_details(target)
            w.check_cancel()
            if not current():
                raise CancelledError('Bağlantı değişti.')
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
                w.check_cancel()
                if not current():
                    raise CancelledError('Bağlantı değişti; görüntü ayarı durduruldu.')
                if res_choice == 'reset':
                    applied.append('size')
                    engine.reset_display_size(target)
                elif isinstance(res_choice, tuple):
                    applied.append('size')
                    engine.set_display_size(target, res_choice[0], res_choice[1])

                w.check_cancel()
                if not current():
                    raise CancelledError('Bağlantı değişti; görüntü ayarı durduruldu.')
                if dens_choice == 'reset':
                    applied.append('density')
                    engine.reset_display_density(target)
                elif isinstance(dens_choice, int):
                    applied.append('density')
                    engine.set_display_density(target, dens_choice)

                w.check_cancel()
                if not current():
                    raise CancelledError('Bağlantı değişti; görüntü ayarı durduruldu.')
                if ov_choice is not None:
                    applied.append('overscan')
                    if ov_choice == (0, 0, 0, 0):
                        engine.reset_display_overscan(target)
                    elif isinstance(ov_choice, tuple):
                        engine.set_display_overscan(target, *ov_choice)

                w.check_cancel()
                if not current():
                    raise CancelledError('Bağlantı değişti; görüntü ayarı durduruldu.')
                new_info = engine.display_details(target)
                w.check_cancel()
                if not current():
                    raise CancelledError('Bağlantı değişti; görüntü ayarı durduruldu.')
                return new_info, prev_info
            except Exception as exc:
                rollback_errors = []
                for name in reversed(applied):
                    try:
                        restore(name)
                    except Exception as rollback_exc:
                        rollback_errors.append('{}: {}'.format(name, rollback_exc))
                if 'overscan' in applied and prev_info.get('overscan') is None:
                    rollback_errors.append(
                        'Kenar taşmasının işlem öncesi değeri okunamadı; fabrika değerine dönmüş olabilir.')
                if rollback_errors:
                    raise RuntimeError(
                        '{}; önceki ayarlar tamamen geri yüklenemedi: {}'.format(
                            exc, '; '.join(rollback_errors))) from exc
                raise

        def on_applied(result):
            new_info, prev_info = result
            fields = tuple(name for name, choice in (
                ('size', res_choice), ('density', dens_choice), ('overscan', ov_choice))
                if choice is not None)
            disconnect_requested = (
                getattr(self.window, '_disconnect_pending', False)
                or getattr(self.window, '_disconnect_in_progress', False))
            if not current() or disconnect_requested:
                self._revert(prev_info, target, fields, engine=engine)
                if disconnect_requested:
                    QTimer.singleShot(0, self.window._watchdog_worker_finished)
                return
            self._confirming = True
            self._update_controls()
            dlg = QDialog(self)
            dlg.setWindowTitle('Görüntü Ayarı Onayı')
            dlg.setMinimumWidth(380)
            dlay = QVBoxLayout(dlg)
            rollback_text = ('Onaylamazsanız çözünürlük ve DPI önceki değerlerine döner. '
                             'Cihaz mevcut kenar boşluğunu bildirmediği için overscan fabrika değerine sıfırlanabilir.'
                             if 'overscan' in fields and prev_info.get('overscan') is None else
                             'Onaylamazsanız görüntü otomatik olarak önceki haline dönecektir.')
            msg_lbl = QLabel(
                'Yeni görüntü ayarı uygulandı!\n\n'
                '• Çözünürlük: {}×{}\n'
                '• DPI Ölçeği: {}\n\n'
                'Bu ayarı korumak istiyor musunuz?\n{}'.format(
                    new_info['width'], new_info['height'], new_info['density'], rollback_text)
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
                if seconds_left[0] <= 0 or not current():
                    timer.stop()
                    dlg.reject()
                else:
                    countdown_lbl.setText('Kalan süre: {} saniye'.format(seconds_left[0]))

            timer.timeout.connect(tick)
            timer.start(1000)

            btn_keep.clicked.connect(lambda: (timer.stop(), dlg.accept()))
            btn_revert.clicked.connect(lambda: (timer.stop(), dlg.reject()))

            result = dlg.exec()
            timer.stop()
            self._confirming = False
            disconnect_requested = (
                getattr(self.window, '_disconnect_pending', False)
                or getattr(self.window, '_disconnect_in_progress', False))
            if (result != QDialog.Accepted or not current()
                    or disconnect_requested):
                timer.stop()
                self._revert(prev_info, target, fields, engine=engine)
                if disconnect_requested:
                    QTimer.singleShot(0, self.window._watchdog_worker_finished)
            else:
                self.read_display()
            self._update_controls()
            self._maybe_close_after_transaction()

        w = Worker(do)
        w.job_name = 'Görüntü Ayarlama'
        w.finished_ok.connect(on_applied)

        def on_failed(error):
            if not current():
                return
            self.read_display()
            QMessageBox.critical(self, 'Görüntü Hatası', str(error))

        w.failed.connect(on_failed)
        self._run_change(w, 'Ekran: yeni çözünürlük/DPI uygulanıyor')

    def _revert(self, prev_info, target, fields=('size', 'density', 'overscan'), engine=None):
        if engine is None:
            try:
                engine = self.core.engine
            except Exception as error:
                self.lbl_status.setText('Görüntü ayarları geri alınamadı: ' + str(error))
                return

        def do():
            errors = []
            for field in fields:
                try:
                    if field == 'size':
                        if prev_info.get('override_width') and prev_info.get('override_height'):
                            engine.set_display_size(target, prev_info['override_width'], prev_info['override_height'])
                        else:
                            engine.reset_display_size(target)
                    elif field == 'density':
                        if prev_info.get('override_density'):
                            engine.set_display_density(target, prev_info['override_density'])
                        else:
                            engine.reset_display_density(target)
                    elif field == 'overscan':
                        if prev_info.get('overscan'):
                            engine.set_display_overscan(target, *prev_info['overscan'])
                        else:
                            engine.reset_display_overscan(target)
                except Exception as error:
                    errors.append('{}: {}'.format(field, error))
            if errors:
                raise RuntimeError('Bazı görüntü ayarları geri alınamadı: ' + '; '.join(errors))
            return engine.display_details(target)

        w = Worker(do)
        w.job_name = 'Ekran ayarı geri alma'
        w.preserve_on_close = True
        w._allow_during_disconnect = True
        w._preserve_from_cancel = True
        generation = self._generation
        current = lambda: (self.core.connected and self.core.target == target
                           and self._generation == generation)
        def on_reverted(_result):
            if not current():
                return
            self.read_display()
            if 'overscan' in fields and prev_info.get('overscan') is None:
                QMessageBox.warning(
                    self, 'Geri Alma Tamamlandı',
                    'Diğer seçili görüntü ayarları geri yüklendi. Cihaz önceki kenar boşluğunu bildirmediği '
                    'için overscan fabrika değerine sıfırlandı.')
            else:
                QMessageBox.information(
                    self, 'Geri Alındı', 'Görüntü ayarları önceki durumuna geri döndürüldü.')

        w.finished_ok.connect(on_reverted)
        w.failed.connect(lambda error: QMessageBox.critical(
            self, 'Görüntü geri alınamadı', str(error)))
        self._run_change(w, 'Ekran: ayarlar geri alınıyor')
