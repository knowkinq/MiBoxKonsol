# -*- coding: utf-8 -*-
"""Device diagnostics and explicitly selected, non-destructive tuning."""
from PySide6.QtCore import Qt, Signal
import math
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QComboBox, QPlainTextEdit, QMessageBox,
)

from ..workers import Worker, CancelledError
from . import kit
from .flowlayout import FlowLayout


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
        intro = kit.hint_label('Kasma nedenlerini inceleyin, uygulamak istediğiniz adımları seçin. '
                               'Animasyonları kısaltmak geçişleri hızlandırır; donanım gücünü artırmaz.')
        root.addWidget(intro)
        metrics = QHBoxLayout()
        for title, value_name, detail_name in (
                ('Depolama doluluğu', 'lbl_disk', 'lbl_disk_detail'),
                ('RAM kullanımı', 'lbl_ram', 'lbl_ram_detail'),
                ('Animasyon ölçeği', 'lbl_anim', 'lbl_anim_detail')):
            card = QGroupBox(title)
            layout = QVBoxLayout(card)
            value = QLabel('—')
            value.setObjectName('metricValue')
            detail = kit.hint_label('Henüz ölçülmedi')
            setattr(self, value_name, value)
            setattr(self, detail_name, detail)
            layout.addWidget(value)
            layout.addWidget(detail)
            metrics.addWidget(card, 1)
        root.addLayout(metrics)
        if self._embedded:
            # Storage and RAM live in the health overview; keep the current
            # animation state next to its controls.
            for index in range(2):
                metrics.itemAt(index).widget().hide()
        diagnostics = QGroupBox('Cihaz analizi')
        analysis_layout = QVBoxLayout(diagnostics)
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

        tuning = QGroupBox('Performans ve bakım adımları')
        plan = QVBoxLayout(tuning)
        self.chk_cache = kit.CheckBox('Uygulama önbelleklerini temizle')
        self.chk_cache.setChecked(True)
        plan.addWidget(self.chk_cache)
        plan.addWidget(kit.hint_label('Geçici önbellekleri azaltır; uygulama verileri ve hesaplar silinmez. '
                                     'Uygulamaların ilk açılışı geçici olarak yavaşlayabilir.'))
        self.chk_animation = kit.CheckBox('Animasyon hızını değiştir')
        self.chk_animation.setChecked(False)
        plan.addWidget(self.chk_animation)
        self.cmb_animation = QComboBox()
        self.cmb_animation.addItem('Daha kısa geçişler · 0,5×', '0.5')
        self.cmb_animation.addItem('Standart geçişler · 1×', '1')
        self.cmb_animation.addItem('Animasyonları kapat · 0×', '0')
        self.chk_animation.toggled.connect(self.cmb_animation.setEnabled)
        self.cmb_animation.setEnabled(self.chk_animation.isChecked())
        plan.addWidget(self.cmb_animation)
        plan.addWidget(kit.hint_label('Yalnızca seçilen adımlar uygulanır. Arka plandaki uygulamalar zorla kapatılmaz.'))
        self.btn_apply = QPushButton('Seçilenleri Uygula')
        self.btn_apply.setProperty('role', 'primary')
        self.btn_apply.clicked.connect(self._apply)
        plan.addWidget(self.btn_apply, 0, Qt.AlignLeft)
        root.addWidget(tuning)

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
        self.lbl_status = kit.status_label('Hazır.')
        self.lbl_status.setTextFormat(Qt.PlainText)
        root.addWidget(self.lbl_status)
        self.txt_report = QPlainTextEdit()
        self.txt_report.setReadOnly(True)
        self.txt_report.setPlaceholderText('Uygulanan adımların ve önce/sonra ölçümlerinin sonucu burada görünür.')
        self.txt_report.setMinimumHeight(90)
        self.txt_report.setMaximumHeight(180)
        self.txt_report.setMaximumBlockCount(120)
        root.addWidget(self.txt_report)
        root.addStretch()

    def _open_running_apps(self):
        health = getattr(self.window, 'tab_health_inner', None)
        if health is not None:
            self.window.tabs.setCurrentWidget(self.window.tab_health)
            health.sections.setCurrentIndex(2)
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
        self.txt_report.clear()

    def _ready(self):
        if self._busy:
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
            if generation != self._generation or not self.core.connected or self.core.target != target or getattr(self.window, '_connection_busy', False):
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
        current = lambda: generation == self._generation and target == self.core.target and self.core.connected
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
        for widget in (self.btn_analyze, self.btn_apply, self.btn_reboot, self.chk_cache, self.chk_animation):
            widget.setEnabled(not busy)
        self.cmb_animation.setEnabled(not busy and self.chk_animation.isChecked())

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
        current = lambda: generation == self._generation and target == self.core.target and self.core.connected

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
