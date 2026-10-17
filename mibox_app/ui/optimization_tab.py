# -*- coding: utf-8 -*-
"""Device diagnostics and explicitly selected, non-destructive tuning."""
import math

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..workers import CancelledError, Worker
from . import kit
from .flowlayout import FlowLayout


class _NoWheelComboBox(QComboBox):
    """Avoid changing a setting when the user scrolls the containing page."""

    def wheelEvent(self, event):
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()


def _content_card(title, metric=False):
    card = QFrame()
    card.setObjectName('metricCard' if metric else 'contentCard')
    card.setProperty('role', 'secondary')
    layout = QVBoxLayout(card)
    layout.setContentsMargins(10 if metric else 12, 10 if metric else 12,
                              10 if metric else 12, 10 if metric else 12)
    layout.setSpacing(6)
    heading = QLabel(title)
    heading.setObjectName('metricLabel' if metric else 'cardTitle')
    heading.setProperty('role', 'quiet' if metric else 'primary')
    heading.setWordWrap(True)
    layout.addWidget(heading)
    return card, layout


def size_text(kb):
    if kb is None:
        return 'Ölçülmedi'
    try:
        value = float(kb)
        return '{:.1f} GB'.format(value / 1024 ** 2) if math.isfinite(value) and value >= 0 else 'Ölçülmedi'
    except (ValueError, TypeError):
        return 'Ölçülmedi'


def measurement(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (TypeError, ValueError):
        return None


class OptimizationTab(QWidget):
    analysis_ready = Signal(dict)
    busy_changed = Signal(bool)

    def __init__(self, core, window, embedded=False):
        super().__init__()
        self.core, self.window = core, window
        self._busy = False
        self._generation = 0
        self._worker = None
        self._embedded = embedded
        self._build()
        core.connection_changed.connect(self._connection_changed)

    def _build(self):
        root = kit.page(self)
        intro_text = ('Kasma nedenlerini inceleyin, uygulamak istediğiniz adımları seçin. '
                      'Animasyonları kısaltmak geçişleri hızlandırır; donanım gücünü artırmaz.')
        if self._embedded:
            intro_text += ' Ekran ve çözünürlük ayarları Cihaz ayarları bölümündedir.'
        intro = kit.hint_label(intro_text)
        root.addWidget(intro)
        metrics = QBoxLayout(QBoxLayout.LeftToRight)
        metrics.setSpacing(8)
        for title, value_name, detail_name in (
                ('Depolama doluluğu', 'lbl_disk', 'lbl_disk_detail'),
                ('RAM kullanımı', 'lbl_ram', 'lbl_ram_detail'),
                ('Animasyon ölçeği', 'lbl_anim', 'lbl_anim_detail')):
            card, layout = _content_card(title, metric=True)
            value = QLabel('—')
            value.setObjectName('metricValue')
            value.setTextFormat(Qt.PlainText)
            detail = kit.hint_label('Henüz ölçülmedi')
            detail.setTextFormat(Qt.PlainText)
            setattr(self, value_name, value)
            setattr(self, detail_name, detail)
            layout.addWidget(value)
            layout.addWidget(detail)
            metrics.addWidget(card, 1)
        self._metrics_layout = metrics
        root.addLayout(metrics)
        if self._embedded:
            # Storage and RAM live in the health overview; keep the current
            # animation state next to its controls.
            for index in range(2):
                metrics.itemAt(index).widget().hide()
        diagnostics, analysis_layout = _content_card('Cihaz analizi')
        self.lbl_findings = kit.status_label('Önce cihaza bağlanın ve Analiz Et ile mevcut durumu okuyun.')
        self.lbl_findings.setTextFormat(Qt.PlainText)
        analysis_layout.addWidget(self.lbl_findings)
        self.btn_analyze = QPushButton('Analiz Et')
        self.btn_analyze.setProperty('role', 'primary')
        self.btn_analyze.clicked.connect(self.refresh)
        analysis_layout.addWidget(self.btn_analyze, 0, Qt.AlignLeft)
        if self._embedded:
            metrics.addWidget(diagnostics, 1)
        else:
            root.addWidget(diagnostics)

        tuning, plan = _content_card('Performans ve bakım adımları')
        self.chk_cache = kit.CheckBox('Uygulama önbelleklerini temizle')
        self.chk_cache.setChecked(True)
        plan.addWidget(self.chk_cache)
        plan.addWidget(kit.hint_label('Geçici önbellekleri azaltır; uygulama verileri ve hesaplar silinmez. '
                                     'Uygulamaların ilk açılışı geçici olarak yavaşlayabilir.'))
        self.chk_animation = kit.CheckBox('Animasyon hızını değiştir')
        self.chk_animation.setChecked(False)
        plan.addWidget(self.chk_animation)
        self.cmb_animation = _NoWheelComboBox()
        self.cmb_animation.addItem('Daha kısa geçişler · 0,5×', '0.5')
        self.cmb_animation.addItem('Standart geçişler · 1×', '1')
        self.cmb_animation.addItem('Animasyonları kapat · 0×', '0')
        self.chk_animation.toggled.connect(self.cmb_animation.setEnabled)
        self.cmb_animation.setEnabled(self.chk_animation.isChecked())
        plan.addWidget(self.cmb_animation)
        plan.addWidget(kit.hint_label('Yalnızca seçilen adımlar uygulanır. Arka plandaki uygulamalar zorla kapatılmaz.'))
        plan_buttons = FlowLayout()
        self.btn_apply = QPushButton('Seçilenleri Uygula')
        self.btn_apply.setProperty('role', 'primary')
        self.btn_apply.clicked.connect(self._apply)
        self.btn_boost = QPushButton('Hızlı Hızlandırma Uygula')
        self.btn_boost.setProperty('accent', True)
        self.btn_boost.setToolTip(
            'Arka plan süreçlerini sonlandırır, önbellekleri temizler ve animasyon hızını 0,5× yapar.')
        self.btn_boost.clicked.connect(self._quick_boost)
        plan_buttons.addWidget(self.btn_apply)
        plan_buttons.addWidget(self.btn_boost)
        plan.addLayout(plan_buttons)
        root.addWidget(tuning)

        # Retain the standalone display controls for callers that use this tab
        # directly; the embedded Health view exposes DisplayPanel instead.
        disp_group, disp_layout = _content_card('Ekran ve görüntü ayarları')
        disp_hint = kit.hint_label(
            'TV ekran çözünürlüğünü ve arayüz DPI ölçeğini değiştirin. '
            'Yanlış ayarda siyah ekranda kalmamanız için 15 saniyelik otomatik geri alma koruması bulunur.'
        )
        disp_layout.addWidget(disp_hint)

        self.lbl_disp_current = QLabel('Mevcut Ekran: Henüz sorgulanmadı')
        self.lbl_disp_current.setProperty('role', 'quiet')
        self.lbl_disp_current.setTextFormat(Qt.PlainText)
        self.lbl_disp_current.setWordWrap(True)
        disp_layout.addWidget(self.lbl_disp_current)

        disp_controls = QBoxLayout(QBoxLayout.LeftToRight)
        disp_controls.setSpacing(8)
        self._display_controls_layout = disp_controls

        self.cmb_resolution = _NoWheelComboBox()
        self.cmb_resolution.addItem('Çözünürlük: Değiştirme', None)
        self.cmb_resolution.addItem('1080p Full HD (1920×1080) · Standart TV', (1920, 1080))
        self.cmb_resolution.addItem('720p HD (1280×720) · Yüksek Hız / Eski TV', (1280, 720))
        self.cmb_resolution.addItem('4K UHD (3840×2160)', (3840, 2160))
        self.cmb_resolution.addItem('Fabrika Çözünürlüğüne Sıfırla', 'reset')

        self.cmb_density = _NoWheelComboBox()
        self.cmb_density.addItem('DPI Ölçeği: Değiştirme', None)
        self.cmb_density.addItem('240 DPI (Kompakt · Ekranda Daha Çok Öğe)', 240)
        self.cmb_density.addItem('280 DPI (Orta)', 280)
        self.cmb_density.addItem('320 DPI (Standart 1080p)', 320)
        self.cmb_density.addItem('360 DPI (Büyük & Kolay Okunur)', 360)
        self.cmb_density.addItem('Fabrika DPI Değerine Sıfırla', 'reset')

        self.cmb_overscan = _NoWheelComboBox()
        self.cmb_overscan.addItem('Kenar Taşması (Overscan): Değiştirme', None)
        self.cmb_overscan.addItem('Kenarları Sıfırla (0px)', (0, 0, 0, 0))
        self.cmb_overscan.addItem('Kenarlardan 20px İçeri Çek (Hafif Kırpılma)', (20, 20, 20, 20))
        self.cmb_overscan.addItem('Kenarlardan 40px İçeri Çek (Belirgin Kırpılma)', (40, 40, 40, 40))

        disp_controls.addWidget(self.cmb_resolution, 1)
        disp_controls.addWidget(self.cmb_density, 1)
        disp_controls.addWidget(self.cmb_overscan, 1)
        disp_layout.addLayout(disp_controls)

        disp_btn_row = FlowLayout()
        self.btn_apply_disp = QPushButton('Görüntü Ayarlarını Uygula')
        self.btn_apply_disp.setProperty('role', 'primary')
        self.btn_apply_disp.clicked.connect(self._apply_display_settings)
        self.btn_read_disp = QPushButton('Ekran Bilgisini Oku')
        self.btn_read_disp.clicked.connect(self._read_display_settings)
        self.btn_reset_disp_all = QPushButton('Görüntüyü Fabrikaya Sıfırla')
        self.btn_reset_disp_all.clicked.connect(self._reset_display_all)

        disp_btn_row.addWidget(self.btn_apply_disp)
        disp_btn_row.addWidget(self.btn_read_disp)
        disp_btn_row.addWidget(self.btn_reset_disp_all)
        disp_layout.addLayout(disp_btn_row)

        self.disp_group = disp_group
        if self._embedded:
            self.disp_group.hide()
        else:
            root.addWidget(disp_group)

        tools = FlowLayout()
        apps = QPushButton('Arka plan yönetimi')
        apps.clicked.connect(self._open_running_apps)
        files = QPushButton('Depolamayı incele')
        files.clicked.connect(lambda: self.window.tabs.setCurrentWidget(self.window.tab_files))
        self.btn_reboot = QPushButton('Cihazı Yeniden Başlat')
        self.btn_reboot.clicked.connect(self._reboot)
        for button in (apps, files, self.btn_reboot):
            tools.addWidget(button)
        root.addLayout(tools)
        self.lbl_status = kit.status_label('Analiz bekliyor. Cihaza bağlanıp Analiz Et’i seçin.')
        self.lbl_status.setTextFormat(Qt.PlainText)
        root.addWidget(self.lbl_status)
        self.txt_report = QPlainTextEdit()
        self.txt_report.setReadOnly(True)
        self.txt_report.setPlaceholderText('Uygulanan adımların ve önce/sonra ölçümlerinin sonucu burada görünür.')
        self.txt_report.setMinimumHeight(72)
        self.txt_report.setMaximumHeight(132)
        self.txt_report.setMaximumBlockCount(120)
        root.addWidget(self.txt_report)
        root.addStretch()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 760
        direction = QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight
        metrics_layout = getattr(self, '_metrics_layout', None)
        if metrics_layout is not None:
            metrics_layout.setDirection(direction)
        display_layout = getattr(self, '_display_controls_layout', None)
        if display_layout is not None:
            display_layout.setDirection(direction)

    def _open_running_apps(self):
        health = getattr(self.window, 'tab_health_inner', None)
        if health is not None:
            self.window.tabs.setCurrentWidget(self.window.tab_health)
            if all(hasattr(health, name) for name in ('_open_section', 'scroll_bg', 'background')):
                health._open_section(health.scroll_bg, health.background)
            elif hasattr(health, 'scroll_bg'):
                health.sections.setCurrentWidget(health.scroll_bg)
            else:
                health.sections.setCurrentIndex(3)
            return
        self.window.tabs.setCurrentWidget(self.window.tab_apps)
        combo = self.window.tab_apps.cmb_status
        index = combo.findData('running')
        if index >= 0:
            combo.setCurrentIndex(index)

    def _connection_changed(self, _connected, _target):
        self._generation += 1
        if self._worker is not None:
            self._worker.cancel()
        for label in (self.lbl_disk, self.lbl_ram, self.lbl_anim):
            label.setText('—')
        for label in (self.lbl_disk_detail, self.lbl_ram_detail, self.lbl_anim_detail):
            label.setText('Henüz ölçülmedi')
        self.lbl_findings.setText('Bağlantı değişti. Mevcut cihazı yeniden analiz edin.')
        self.lbl_status.setText('Bağlantı değişti. Mevcut cihazı yeniden analiz edin.')
        self.lbl_disp_current.setText('Bağlantı değişti. Mevcut cihazı yeniden okuyun.')
        self.txt_report.clear()

    def _ready(self):
        if self._busy or getattr(self.window, "_closing", False) or getattr(self.window, "_close_pending", False):
            return False
        if getattr(self.window, '_connection_busy', False) or not self.core.connected or not self.core.target:
            self.lbl_status.setText('Önce cihaz bağlantısının kurulmasını bekleyin.')
            return False
        return True

    def refresh(self):
        self._start('analyze')

    def _apply(self):
        self._start('apply', self.chk_cache.isChecked(),
                    self.cmb_animation.currentData() if self.chk_animation.isChecked() else None)

    def _start(self, kind, trim=False, animation=None):
        if not self._ready():
            return
        if kind == 'apply' and not trim and animation is None:
            self.lbl_status.setText('Uygulamak için en az bir adım seçin.')
            return
        if kind == 'apply' and getattr(self.window, '_workers', []):
            self.lbl_status.setText('Diğer işlemlerin bitmesini bekleyip yeniden deneyin.')
            return
        from ..optimization import analyze, run_plan
        target, generation = self.core.target, self._generation
        try:
            engine = self.core.engine
        except Exception as error:
            self.lbl_status.setText('Cihaz motoru hazır değil: ' + str(error))
            return

        def check():
            worker.check_cancel()
            if (generation != self._generation or not self.core.connected or self.core.target != target
                    or engine is not self.core.engine or getattr(self.window, '_connection_busy', False)
                    or getattr(self.window, '_closing', False) or getattr(self.window, '_close_pending', False)):
                raise CancelledError('Bağlantı değişti; işlem durduruldu.')

        def do():
            if kind == 'analyze':
                return analyze(engine, target, check_cancel=check)
            return run_plan(engine, target, trim=trim, animation=animation,
                            check_cancel=check, progress=worker.progress.emit)

        worker = Worker(do)
        worker.job_name = 'Cihaz analizi' if kind == 'analyze' else 'Cihaz optimizasyonu'
        self._worker = worker
        self._set_busy(True)
        self.lbl_status.setText('Cihaz analiz ediliyor…' if kind == 'analyze' else 'Seçilen adımlar uygulanıyor…')
        current = lambda: (generation == self._generation and target == self.core.target
                           and self.core.connected and engine is self.core.engine
                           and not getattr(self.window, '_connection_busy', False)
                           and not getattr(self.window, '_closing', False)
                           and not getattr(self.window, '_close_pending', False))
        worker.finished_ok.connect(lambda result: self._show_analysis(result) if current() and kind == 'analyze'
                                   else self._show_result(result) if current() else None)
        worker.failed.connect(lambda error: self.lbl_status.setText('İşlem tamamlanamadı: ' + str(error)) if current() else None)

        def cleanup():
            if self._worker is worker:
                self._worker = None
                self._set_busy(False)
        worker.finished.connect(cleanup)
        try:
            self.window._run(worker, desc=worker.job_name)
        except Exception as error:
            cleanup()
            self.lbl_status.setText('İşlem başlatılamadı: ' + str(error))

    def _set_busy(self, busy):
        self._busy = bool(busy)
        for widget in (self.btn_analyze, self.btn_apply, self.btn_reboot, self.chk_cache, self.chk_animation,
                       self.btn_boost,
                       self.btn_apply_disp, self.btn_read_disp, self.btn_reset_disp_all):
            widget.setEnabled(not busy)
        self.cmb_animation.setEnabled(not busy and self.chk_animation.isChecked())
        self.busy_changed.emit(self._busy)

    def _show_analysis(self, result):
        health, animations = dict(result.get('health', {})), result.get('animations', {})
        for key in ('disk_pct', 'mem_pct'):
            value = measurement(health.get(key))
            if value is None or value > 100:
                health.pop(key, None)
            else:
                health[key] = int(value)
        self.analysis_ready.emit(health)
        self.lbl_disk.setText('{}%'.format(health['disk_pct']) if 'disk_pct' in health else '—')
        self.lbl_ram.setText('{}%'.format(health['mem_pct']) if 'mem_pct' in health else '—')
        self.lbl_disk_detail.setText('Boş: {}'.format(size_text(health.get('disk_avail_kb'))))
        self.lbl_ram_detail.setText('Kullanılabilir: {}'.format(size_text(health.get('mem_avail_kb'))))
        values = [str(animations.get(key, '?')) for key in
                  ('window_animation_scale', 'transition_animation_scale', 'animator_duration_scale')]
        known = all(value not in ('?', 'null', '', 'None') for value in values)
        self.lbl_anim.setText(str(values[0]) + '×' if known and len(set(values)) == 1 else 'Karma' if known else '—')
        self.lbl_anim_detail.setText('Pencere / geçiş / süre: ' + ' / '.join(map(str, values)) if values else 'Henüz ölçülmedi')
        findings = []
        if health.get('disk_pct', 0) >= 85:
            findings.append('Depolama büyük ölçüde dolu. Gereksiz dosyaları inceleyin; önbellek temizliği alan açabilir.')
        if health.get('mem_pct', 0) >= 85:
            findings.append('RAM kullanımı yüksek. Sürekli çalışan uygulamaları inceleyin; RAM doluluğu tek başına arıza göstermez.')
        measured = 'disk_pct' in health or 'mem_pct' in health
        if measured and not findings:
            findings.append('Okunan depolama ve RAM değerlerinde belirgin bir doluluk uyarısı yok.')
        if not measured:
            findings.append('Cihaz ölçümleri okunamadı; durum değerlendirmesi yapılamıyor.')
        findings.extend(result.get('warnings', []))
        findings.append('Kasma sürüyorsa yeniden başlatmayı deneyin; sorun yayın bağlantısından veya cihaz sıcaklığından da kaynaklanabilir.')
        self.lbl_findings.setText('\n'.join(findings))
        self.lbl_status.setText('Analiz tamamlandı.')

    def _show_result(self, result):
        if result.get('after'):
            self._show_analysis(result['after'])
        elif result.get('before'):
            self._show_analysis(result['before'])
        lines = []
        for step in result.get('steps', []):
            lines.append(('Tamamlandı: ' if step['ok'] else 'Başarısız: ') + step['message'])
        before = (result.get('before') or {}).get('health', {})
        after = (result.get('after') or {}).get('health', {})
        if measurement(before.get('disk_avail_kb')) is not None and measurement(after.get('disk_avail_kb')) is not None:
            lines.append('Boş depolama: {} → {}'.format(size_text(before['disk_avail_kb']), size_text(after['disk_avail_kb'])))
            difference = (measurement(after['disk_avail_kb']) - measurement(before['disk_avail_kb'])) / 1024
            lines.append('Boş alan farkı: {:+.1f} MB'.format(difference))
        if 'mem_pct' in before and 'mem_pct' in after:
            lines.append('RAM kullanımı: {}% → {}% (anlık ölçüm)'.format(before['mem_pct'], after['mem_pct']))
        if result.get('cancelled'):
            status = 'İşlem durduruldu. Tamamlanan adımlar aşağıda listeleniyor.'
        elif any(not step['ok'] for step in result.get('steps', [])):
            status = 'Bazı adımlar uygulanamadı; ayrıntıları kontrol edin.'
        else:
            status = 'Seçilen adımlar tamamlandı.'
        self.lbl_status.setText(status)
        self.txt_report.setPlainText('\n'.join(lines) or status)

    def _reboot(self):
        if not self._ready():
            return
        if getattr(self.window, '_workers', []):
            self.lbl_status.setText('Yeniden başlatmadan önce diğer işlemlerin bitmesini bekleyin.')
            return
        target, generation = self.core.target, self._generation
        if QMessageBox.question(self, 'Yeniden başlat',
                                'Oynatma ve açık uygulamalar kesilecek. Cihaz yeniden başlatılsın mı?',
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        if not self._ready() or target != self.core.target or generation != self._generation or getattr(self.window, '_workers', []):
            self.lbl_status.setText('Bağlantı değişti veya başka bir işlem çalışıyor; yeniden deneyin.')
            return
        try:
            engine = self.core.engine
        except Exception as error:
            self.lbl_status.setText('Cihaz motoru hazır değil: ' + str(error))
            return
        current = lambda: (generation == self._generation and target == self.core.target
                           and self.core.connected and engine is self.core.engine
                           and not getattr(self.window, '_connection_busy', False)
                           and not getattr(self.window, '_closing', False)
                           and not getattr(self.window, '_close_pending', False))

        def dispatch():
            worker.check_cancel()
            if not current() or getattr(self.window, '_connection_busy', False):
                raise CancelledError('Bağlantı değişti; yeniden başlatma iptal edildi.')
            result = engine.reboot(target)
            if getattr(result, 'exit_code', 0) != 0:
                raise RuntimeError(getattr(result, 'error', '') or getattr(result, 'output', '') or 'Cihaz yeniden başlatma isteğini reddetti.')
            return result

        worker = Worker(dispatch)
        worker.job_name = 'Cihaz yeniden başlatma'
        self._set_busy(True)
        self._worker = worker
        self.lbl_status.setText('Yeniden başlatma isteniyor…')

        def done(_result):
            if not current():
                return
            self.core.connected = False
            self.core.connection_changed.emit(False, target)
            self.lbl_status.setText('Yeniden başlatma istendi. Cihaz açılınca yeniden bağlanın.')
        worker.finished_ok.connect(done)
        worker.failed.connect(lambda error: self.lbl_status.setText('Yeniden başlatılamadı: ' + str(error)) if current() else None)

        def cleanup():
            if self._worker is worker:
                self._worker = None
                self._set_busy(False)
        worker.finished.connect(cleanup)
        try:
            self.window._run(worker, desc=worker.job_name)
        except Exception as error:
            cleanup()
            self.lbl_status.setText('Yeniden başlatma başlatılamadı: ' + str(error))

    def _quick_boost(self):
        if not self._ready():
            return
        if getattr(self.window, '_workers', []):
            self.lbl_status.setText('Diğer işlemlerin bitmesini bekleyip yeniden deneyin.')
            return
        target, generation = self.core.target, self._generation
        try:
            engine = self.core.engine
        except Exception as error:
            self.lbl_status.setText('Cihaz motoru hazır değil: ' + str(error))
            return
        if QMessageBox.question(
                self, 'Süper Hızlandırma',
                'Tek tıkla süper hızlandırma uygulanacak:\n\n'
                '• Arka plan işlemleri sonlandırılacak\n'
                '• Önbellekler temizlenecek\n'
                '• Animasyon geçişleri 0.5× yapılacak\n\n'
                'Devam edilsin mi?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        if (not self._ready() or target != self.core.target or generation != self._generation
                or engine is not self.core.engine or getattr(self.window, '_workers', [])):
            self.lbl_status.setText('Cihaz veya işlem durumu değişti. Yeniden deneyin.')
            return

        current = lambda: (generation == self._generation and target == self.core.target
                           and self.core.connected and engine is self.core.engine
                           and not getattr(self.window, '_connection_busy', False)
                           and not getattr(self.window, '_closing', False)
                           and not getattr(self.window, '_close_pending', False))

        def check():
            worker.check_cancel()
            if not current():
                raise CancelledError('Bağlantı değişti; hızlandırma durduruldu.')

        def do():
            return engine.quick_boost(target, check_cancel=check)

        worker = Worker(do)
        worker.job_name = 'Süper Hızlandırma'
        self._worker = worker
        results, errors = [], []
        self._set_busy(True)
        self.lbl_status.setText('Süper hızlandırma uygulanıyor…')

        def done(res):
            res = res or {}
            freed = measurement(res.get('freed_mb'))
            summary = res.get('summary') or []
            if not isinstance(summary, (list, tuple)):
                summary = [summary]
            step_specs = (
                ('Önbellek temizleme', 'Uygulama onbellekleri temizlendi.', 'Onbellek temizleme:'),
                ('Arka plan süreçlerini sonlandırma',
                 'Arka plan bosta kalan surecler sonlandirildi.', 'Surec sonlandirma:'),
                ('Animasyon ölçeklerini ayarlama',
                 'Animasyon hizlari 0.5x (hizli) yapildi.', 'Animasyon olcekleri:'),
            )
            result_lines = []
            recognized_steps = set()
            duplicate_step = False
            failed_steps = 0
            for item in summary:
                if not isinstance(item, str):
                    result_lines.append('Sonuç: {}'.format(item))
                    continue
                for label, success_text, failure_prefix in step_specs:
                    if item == success_text:
                        result_lines.append('Tamamlandı: {}'.format(label))
                        duplicate_step |= label in recognized_steps
                        recognized_steps.add(label)
                        break
                    if item.startswith(failure_prefix):
                        error = item[len(failure_prefix):].strip()
                        result_lines.append('Başarısız: {}{}'.format(
                            label, ' — ' + error if error else ''))
                        duplicate_step |= label in recognized_steps
                        recognized_steps.add(label)
                        failed_steps += 1
                        break
                else:
                    result_lines.append('Sonuç: {}'.format(item))

            report_lines = ['🚀 Süper Hızlandırma Sonucu',
                            '• Kazanılan RAM: {:+.1f} MB'.format(freed)
                            if freed is not None else '• Kazanılan RAM: Ölçülemedi']
            report_lines.extend(['', *result_lines] if result_lines else [])
            complete_report = (len(summary) == len(step_specs)
                               and len(recognized_steps) == len(step_specs)
                               and not duplicate_step)
            if failed_steps:
                dialog_title = 'Kısmi Hızlandırma'
                status = 'Süper hızlandırma kısmen tamamlandı; bazı adımlar uygulanamadı.'
                report_lines.insert(1, 'Bazı adımlar tamamlanamadı:')
            elif not complete_report:
                dialog_title = 'Eksik Hızlandırma Sonucu'
                status = 'Hızlandırma sonucu eksik raporlandı; adım durumları doğrulanamadı.'
                report_lines.insert(1, 'Tüm adımların durumu doğrulanamadı.')
            else:
                dialog_title = 'Hızlandırma Başarılı'
                status = 'Süper hızlandırma tamamlandı.'
            msg = '\n'.join(report_lines)
            self.lbl_status.setText(status)
            self.txt_report.setPlainText(msg)
            if failed_steps or not complete_report:
                QMessageBox.warning(self, dialog_title, msg)
            else:
                QMessageBox.information(self, dialog_title, msg)

        worker.finished_ok.connect(results.append)
        worker.failed.connect(errors.append)

        def finish():
            if self._worker is not worker:
                return
            self._worker = None
            self._set_busy(False)
            if not current():
                return
            if errors:
                self.lbl_status.setText('Hızlandırma tamamlanamadı: ' + str(errors[-1]))
            elif results:
                done(results[-1])
            else:
                self.lbl_status.setText('Hızlandırma durduruldu. Bazı adımlar uygulanmış olabilir.')

        worker.finished.connect(finish)
        try:
            self.window._run(worker, desc='Süper Hızlandırma')
        except Exception as error:
            if self._worker is worker:
                self._worker = None
                self._set_busy(False)
            if current():
                self.lbl_status.setText('Hızlandırma başlatılamadı: ' + str(error))

    def _read_display_settings(self):
        if not self._ready():
            return
        target = self.core.target
        engine = self.core.engine

        def do():
            return engine.display_details(target)

        worker = Worker(do)
        worker.job_name = 'Ekran Bilgisi Okuma'

        def done(info):
            txt = f"Mevcut: {info['width']}×{info['height']} @ {info['fps']}Hz · {info['density']} DPI"
            if info.get('override_width') or info.get('override_density'):
                txt += ' · Özel ayar etkin'
            if info.get('sink_name'):
                txt += f" · {info['sink_name']}"
            if info.get('overscan'):
                txt += f" · Overscan: {info['overscan']}"
            self.lbl_disp_current.setText(txt)

        worker.finished_ok.connect(done)
        worker.failed.connect(lambda err: self.lbl_disp_current.setText('Ekran bilgisi okunamadı: ' + str(err)))
        self.window._run(worker, desc='Ekran: mevcut çözünürlük okunuyor')

    def _reset_display_all(self):
        if not self._ready():
            return
        target = self.core.target
        engine = self.core.engine

        def do():
            engine.reset_display_size(target)
            engine.reset_display_density(target)
            engine.reset_display_overscan(target)
            return engine.display_details(target)

        worker = Worker(do)
        worker.job_name = 'Görüntü Sıfırlama'

        def done(info):
            self._read_display_settings()
            QMessageBox.information(self, 'Görüntü Sıfırlandı',
                                    'Çözünürlük, DPI ölçeği ve kenar taşması fabrika varsayılanına döndürüldü.')

        worker.finished_ok.connect(done)
        worker.failed.connect(lambda err: QMessageBox.critical(self, 'Hata', 'Görüntü sıfırlanamadı: ' + str(err)))
        self.window._run(worker, desc='Ekran: fabrika ayarlarına sıfırlanıyor')

    def _apply_display_settings(self):
        if not self._ready():
            return
        res_choice = self.cmb_resolution.currentData()
        dens_choice = self.cmb_density.currentData()
        overscan_choice = self.cmb_overscan.currentData()

        if res_choice is None and dens_choice is None and overscan_choice is None:
            QMessageBox.information(self, 'Seçim Yapılmadı',
                                    'Uygulamak için çözünürlük, DPI veya overscan seçeneklerinden en az birini belirleyin.')
            return

        target = self.core.target
        engine = self.core.engine

        def do_apply():
            prev_info = engine.display_details(target)
            required = []
            if res_choice is not None:
                required.append('size')
            if dens_choice is not None:
                required.append('density')
            if overscan_choice is not None:
                required.append('overscan')
            unreadable = set(required) & set(prev_info.get('read_errors', []))
            if unreadable:
                raise RuntimeError(
                    'Geri alma için mevcut değerler okunamadı: {}. Hiçbir ayar değiştirilmedi.'
                    .format(', '.join(sorted(unreadable)))
                )
            attempted_fields = []
            try:
                if res_choice == 'reset':
                    attempted_fields.append('size')
                    engine.reset_display_size(target)
                elif isinstance(res_choice, tuple):
                    attempted_fields.append('size')
                    engine.set_display_size(target, res_choice[0], res_choice[1])

                if dens_choice == 'reset':
                    attempted_fields.append('density')
                    engine.reset_display_density(target)
                elif isinstance(dens_choice, int):
                    attempted_fields.append('density')
                    engine.set_display_density(target, dens_choice)

                if overscan_choice is not None:
                    attempted_fields.append('overscan')
                    if overscan_choice == (0, 0, 0, 0):
                        engine.reset_display_overscan(target)
                    elif isinstance(overscan_choice, tuple):
                        engine.set_display_overscan(target, *overscan_choice)

                return engine.display_details(target), prev_info
            except Exception as apply_error:
                try:
                    self._restore_display_fields(engine, target, prev_info, attempted_fields)
                except Exception as rollback_error:
                    raise RuntimeError(
                        'Görüntü ayarı uygulanamadı: {}. Önceki ayarlara dönüş de başarısız oldu: {}'
                        .format(apply_error, rollback_error)) from apply_error
                if attempted_fields:
                    raise RuntimeError(
                        'Görüntü ayarı uygulanamadı; önceki değerler geri yüklendi: {}'
                        .format(apply_error)) from apply_error
                raise

        def on_applied(result):
            new_info, prev_info = result
            self._read_display_settings()
            dlg = QDialog(self)
            dlg.setWindowTitle('Görüntü Ayarı Onayı')
            dlg.setMinimumWidth(380)
            dlay = QVBoxLayout(dlg)
            msg_lbl = QLabel(
                f"Yeni görüntü ayarı uygulandı!\n\n"
                f"• Çözünürlük: {new_info['width']}×{new_info['height']}\n"
                f"• DPI Ölçeği: {new_info['density']}\n\n"
                f"Bu ayarı korumak istiyor musunuz?\n"
                f"Onaylamazsanız görüntü otomatik olarak önceki haline dönecektir."
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
                    countdown_lbl.setText(f'Kalan süre: {seconds_left[0]} saniye')

            timer.timeout.connect(tick)
            timer.start(1000)

            btn_keep.clicked.connect(lambda: (timer.stop(), dlg.accept()))
            btn_revert.clicked.connect(lambda: (timer.stop(), dlg.reject()))

            if dlg.exec() != QDialog.Accepted:
                timer.stop()
                self._revert_display(prev_info, target)

        worker = Worker(do_apply)
        worker.job_name = 'Görüntü Ayarlama'
        worker.finished_ok.connect(on_applied)

        def on_apply_failed(error):
            self._read_display_settings()
            QMessageBox.critical(self, 'Görüntü Hatası', str(error))

        worker.failed.connect(on_apply_failed)
        self.window._run(worker, desc='Ekran: yeni çözünürlük/DPI uygulanıyor')

    def _revert_display(self, prev_info, target):
        engine = self.core.engine

        def do_revert():
            self._restore_display_fields(engine, target, prev_info, ('size', 'density', 'overscan'))
            return engine.display_details(target)

        w = Worker(do_revert)
        w.finished_ok.connect(lambda _: (
            self._read_display_settings(),
            QMessageBox.information(self, 'Geri Alındı', 'Görüntü ayarları önceki durumuna geri döndürüldü.')
        ))
        w.failed.connect(lambda error: QMessageBox.critical(
            self, 'Görüntü Geri Alma Hatası', 'Önceki görüntü ayarları geri yüklenemedi: ' + str(error)))
        self.window._run(w, desc='Ekran: ayarlar geri alınıyor')

    @staticmethod
    def _restore_display_fields(engine, target, prev_info, fields):
        failures = []
        for field in reversed(fields):
            try:
                if field == 'size':
                    if prev_info.get('override_width'):
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
                label = {'size': 'çözünürlük', 'density': 'DPI', 'overscan': 'kenar taşması'}.get(field, field)
                failures.append('{}: {}'.format(label, error))
        if failures:
            raise RuntimeError('Geri yüklenemeyen ayarlar: ' + '; '.join(failures))
