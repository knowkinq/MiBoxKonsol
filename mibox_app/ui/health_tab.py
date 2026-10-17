# -*- coding: utf-8 -*-
"""Sağlık sekmesi: cihaz ölçümleri, bakım ve gelişmiş taramalar."""
import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..workers import CancelledError, Worker
from . import kit
from .background_panel import BackgroundPanel
from .display_panel import DisplayPanel
from .flowlayout import FlowLayout
from .optimization_tab import OptimizationTab, measurement

AUTO_COL_NAME = 0
AUTO_COL_PACKAGE = 1
AUTO_COL_RESTRICT = 2
_PACKAGE_ID_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+')


def _fmt_kb(kb):
    try:
        kb = int(kb)
    except (TypeError, ValueError):
        return '?'
    if kb >= 1024 * 1024:
        return '{:.1f} GB'.format(kb / (1024 * 1024))
    if kb >= 1024:
        return '{:.0f} MB'.format(kb / 1024)
    return '{} KB'.format(kb)


class HealthTab(QWidget):
    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._generation = 0
        self._read_workers = {}
        self._section_groups = {}
        self._health_measurements = {}
        self._summary_worker = None
        self._build()
        core.connection_changed.connect(self._connection_changed)
        if getattr(window, '_connection_busy', False):
            initial_state = 'connecting'
        else:
            initial_state = 'unmeasured' if core.connected else 'offline'
        self._update_measurement_summary(initial_state)
        self._sync_refresh_button()
        self.performance.busy_changed.connect(lambda _busy: self._sync_refresh_button())

    def _build(self):
        root = kit.page(self)
        self.sections = QTabWidget()
        self.sections.setObjectName('healthSections')
        self.sections.setDocumentMode(True)
        navigation = self.sections.tabBar()
        navigation.setObjectName('healthNavigation')
        navigation.setAccessibleName('Sağlık bölümleri')
        navigation.setExpanding(True)
        navigation.setDrawBase(False)
        navigation.setElideMode(Qt.ElideNone)
        navigation.setUsesScrollButtons(True)
        self.sections.setStyleSheet('''
            QTabWidget#healthSections::pane { border: none; }
            QTabBar#healthNavigation::tab {
                min-height: 24px;
                padding: 10px 16px;
                margin-right: 4px;
                border-radius: 8px;
            }
            QTabBar#healthNavigation::tab:selected {
                border-bottom: 3px solid #818cf8;
                font-weight: 600;
            }
        ''')
        self.sections.setMinimumHeight(260)
        root.addWidget(self.sections, 1)
        overview = QWidget()
        overview_root = kit.page(overview)
        def add_page(widget, title):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidget(widget)
            self.sections.addTab(scroll, title)
            return scroll

        self.scroll_overview = add_page(overview, 'Genel durum')
        devices_page = QWidget()
        devices_root = kit.page(devices_page)
        self.scroll_devices = add_page(devices_page, 'Cihaz ayarları')
        maintenance_page = QWidget()
        maintenance_root = kit.page(maintenance_page)
        self.scroll_maintenance = add_page(maintenance_page, 'Bakım ve analiz')

        self.performance = OptimizationTab(self.core, self.window, embedded=True)
        self.performance.analysis_ready.connect(self._show)
        self.scroll_performance = self.scroll_maintenance
        self.display_panel = DisplayPanel(self.core, self.window)
        self.scroll_display = self.scroll_devices
        devices_root.addWidget(self.display_panel)
        self.background = BackgroundPanel(self.core, self.window)
        self.scroll_bg = self.scroll_devices
        devices_root.addWidget(self.background)
        advanced_page = QWidget()
        advanced_root = kit.page(advanced_page)
        self.scroll_advanced = self.scroll_maintenance

        def section_links(layout, page, entries):
            links = QHBoxLayout()
            links.setSpacing(10)
            group = []
            for text, target in entries:
                button = QPushButton(text)
                button.setMinimumHeight(36)
                button.setProperty('role', 'secondary')
                button.setCheckable(True)
                button.setAccessibleName(text)
                button.clicked.connect(
                    lambda _checked=False, page=page, target=target:
                    self._open_section(page, target)
                )
                links.addWidget(button, 1)
                group.append((button, target))
            self._section_groups[page] = group
            for index, (button, target) in enumerate(group):
                button.setChecked(index == 0)
                if index:
                    target.hide()
            layout.insertLayout(0, links)

        section_links(devices_root, self.scroll_devices, (
            ('Ekran ayarları', self.display_panel),
            ('Arka plan izinleri', self.background),
        ))
        section_links(maintenance_root, self.scroll_maintenance, (
            ('Performans ve bakım', self.performance),
            ('Uygulama taramaları', advanced_page),
        ))
        for index, description in enumerate((
            'Depolama, bellek ve donanım ölçümleri',
            'Ekran ayarları ve uygulamaların arka plan izinleri',
            'Performans işlemleri, depolama ve uygulama taramaları',
        )):
            self.sections.setTabToolTip(index, description)
        root = overview_root
        title = QLabel('Cihaz sağlığı')
        title.setObjectName('cardTitle')
        title.setProperty('role', 'primary')
        title_row = QHBoxLayout()
        title_row.addWidget(title, 1)
        self.btn_refresh = QPushButton('Yenile')
        self.btn_refresh.setProperty('accent', True)
        self.btn_refresh.clicked.connect(self.refresh)
        title_row.addWidget(self.btn_refresh)
        root.addLayout(title_row)
        intro = QLabel('Depolama, bellek ve uygulama paketlerinin anlık durumu.')
        intro.setProperty('role', 'quiet')
        intro.setWordWrap(True)
        root.addWidget(intro)

        metrics = QBoxLayout(QBoxLayout.LeftToRight)
        self._overview_metrics = metrics
        metrics.setSpacing(kit.SPACING)
        self.lbl_disk = QLabel('—')
        self.lbl_disk_detail = QLabel('Henüz ölçüm alınmadı')
        self.bar_disk = QProgressBar()
        self.bar_disk.setRange(0, 100)
        self.lbl_mem = QLabel('—')
        self.lbl_mem_detail = QLabel('Henüz ölçüm alınmadı')
        self.bar_mem = QProgressBar()
        self.bar_mem.setRange(0, 100)
        self.lbl_pkg = QLabel('—')
        self.lbl_pkg_detail = QLabel('Henüz ölçüm alınmadı')
        for label, value, detail, bar in (
                ('Depolama', self.lbl_disk, self.lbl_disk_detail, self.bar_disk),
                ('Bellek', self.lbl_mem, self.lbl_mem_detail, self.bar_mem),
                ('Uygulama paketleri', self.lbl_pkg, self.lbl_pkg_detail, None)):
            card = QFrame()
            card.setObjectName('metricCard')
            card.setProperty('role', 'secondary')
            card.setMinimumWidth(160)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 12, 12, 12)
            card_layout.setSpacing(6)
            metric_label = QLabel(label)
            metric_label.setObjectName('metricLabel')
            metric_label.setProperty('role', 'quiet')
            value.setObjectName('metricValue')
            value.setWordWrap(True)
            value.setTextFormat(Qt.PlainText)
            value.setProperty('role', 'primary')
            detail.setWordWrap(True)
            detail.setProperty('role', 'quiet')
            card_layout.addWidget(metric_label)
            card_layout.addWidget(value)
            if bar is not None:
                bar.setTextVisible(False)
                card_layout.addWidget(bar)
            card_layout.addWidget(detail)
            metrics.addWidget(card, 1)
        root.addLayout(metrics)

        hardware_metrics = QBoxLayout(QBoxLayout.LeftToRight)
        self._hardware_metrics = hardware_metrics
        hardware_metrics.setSpacing(kit.SPACING)
        self.lbl_display = QLabel('—')
        self.lbl_display_detail = QLabel('Henüz ölçüm alınmadı')
        self.lbl_cpu = QLabel('—')
        self.lbl_cpu_detail = QLabel('Henüz ölçüm alınmadı')
        for label, value, detail in (
                ('Ekran & TV', self.lbl_display, self.lbl_display_detail),
                ('İşlemci & Donanım', self.lbl_cpu, self.lbl_cpu_detail)):
            card = QFrame()
            card.setObjectName('metricCard')
            card.setProperty('role', 'secondary')
            card.setMinimumWidth(160)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 12, 12, 12)
            card_layout.setSpacing(6)
            metric_label = QLabel(label)
            metric_label.setObjectName('metricLabel')
            metric_label.setProperty('role', 'quiet')
            value.setObjectName('metricValue')
            value.setWordWrap(True)
            value.setTextFormat(Qt.PlainText)
            value.setProperty('role', 'primary')
            detail.setWordWrap(True)
            detail.setTextFormat(Qt.PlainText)
            detail.setProperty('role', 'quiet')
            card_layout.addWidget(metric_label)
            card_layout.addWidget(value)
            card_layout.addWidget(detail)
            hardware_metrics.addWidget(card, 1)
        root.addLayout(hardware_metrics)
        summary_card = QFrame()
        summary_card.setObjectName('contentCard')
        summary_card.setProperty('role', 'secondary')
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(12, 10, 12, 10)
        summary_layout.setSpacing(5)
        summary_header = QHBoxLayout()
        summary_title = QLabel('Ölçüm özeti')
        summary_title.setObjectName('cardTitle')
        summary_title.setProperty('role', 'primary')
        summary_header.addWidget(summary_title, 1)
        self.lbl_measurement_state = QLabel()
        self.lbl_measurement_state.setProperty('role', 'badge')
        summary_header.addWidget(self.lbl_measurement_state, 0, Qt.AlignRight)
        summary_layout.addLayout(summary_header)
        self.lbl_measurement_summary = QLabel()
        self.lbl_measurement_summary.setWordWrap(True)
        self.lbl_measurement_summary.setTextFormat(Qt.PlainText)
        self.lbl_measurement_summary.setProperty('role', 'secondary')
        summary_layout.addWidget(self.lbl_measurement_summary)
        root.addWidget(summary_card)

        self.lbl_overview = kit.status_label('')
        self.lbl_overview.setTextFormat(Qt.PlainText)
        self.lbl_overview.hide()
        root.addWidget(self.lbl_overview)
        overview_tools = FlowLayout()
        for text, page, target in (
            ('Performans ve bakım', self.scroll_performance, self.performance),
            ('Ekran ve çözünürlük', self.scroll_display, self.display_panel),
            ('Arka plan yönetimi', self.scroll_bg, self.background),
        ):
            button = QPushButton(text)
            button.clicked.connect(
                lambda _checked=False, page=page, target=target:
                self._open_section(page, target)
            )
            overview_tools.addWidget(button)
        root.addLayout(overview_tools)
        root.addStretch()
        root = advanced_root

        def section_card(text, object_name='contentCard'):
            card = QFrame()
            card.setObjectName(object_name)
            card.setProperty('role', 'secondary')
            layout = QVBoxLayout(card)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(6)
            heading = QLabel(text)
            heading.setObjectName('cardTitle')
            heading.setProperty('role', 'primary')
            layout.addWidget(heading)
            return card, layout

        advanced, av = section_card('Depolama analizi')
        advanced_hint = QLabel('Depolamada en çok yer kaplayan klasörleri boyutlarıyla listeleyin.')
        advanced_hint.setProperty('role', 'quiet')
        advanced_hint.setWordWrap(True)
        av.addWidget(advanced_hint)
        self.btn_top = QPushButton('En büyük 15 klasörü tara')
        self.btn_top.clicked.connect(self._storage_top)
        top_row = QHBoxLayout()
        top_row.addWidget(self.btn_top)
        top_row.addStretch()
        av.addLayout(top_row)
        self.grid_top = kit.make_table(2, ['Klasör', 'Boyut'])
        kit.empty_state(self.grid_top, 'Henüz tarama yok', 'Klasör boyutlarını görmek için taramayı başlatın.')
        self.grid_top.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.grid_top.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._size_result_table(self.grid_top, 0, 190)
        av.addWidget(self.grid_top)
        self._analysis_cards = QBoxLayout(QBoxLayout.LeftToRight)
        self._analysis_cards.setSpacing(kit.SPACING)
        self._analysis_cards.addWidget(advanced, 1)
        root.addLayout(self._analysis_cards)

        permissions, av = section_card('Uygulama izinleri')
        av.addWidget(kit.hint_label('Paket adını girerek verilen izinleri ve hassas izinleri inceleyin.'))
        prow = QHBoxLayout()
        self.txt_perm_pkg = QLineEdit()
        self.txt_perm_pkg.setPlaceholderText('paket adı (örn: ar.tvplayer.tv)...')
        self.btn_perm = QPushButton('İzinleri Göster')
        self.btn_perm.clicked.connect(self._show_perms)
        prow.addWidget(self.txt_perm_pkg, 1)
        prow.addWidget(self.btn_perm)
        av.addLayout(prow)
        self.lbl_perms = QLabel('')
        self.lbl_perms.hide()
        self.lbl_perms.setWordWrap(True)
        self.lbl_perms.setTextFormat(Qt.PlainText)
        self.lbl_perms.setTextInteractionFlags(Qt.TextSelectableByMouse)
        av.addWidget(self.lbl_perms)
        av.addStretch(1)
        self._analysis_cards.addWidget(permissions, 1)

        autorun, av = section_card('Başlangıç uygulamaları')
        auto_hint = QLabel('Açılış yayınlarını dinleyen paketleri tarayın; kısıtlama için ayrı onay istenir.')
        auto_hint.setProperty('role', 'quiet')
        auto_hint.setWordWrap(True)
        av.addWidget(auto_hint)
        self.btn_autorun = QPushButton('Tara')
        self.btn_autorun.clicked.connect(self._autorun_scan)
        auto_row = QHBoxLayout()
        auto_row.addWidget(self.btn_autorun)
        auto_row.addStretch()
        av.addLayout(auto_row)
        self.grid_auto = kit.make_table(3, ['Uygulama', 'Paket kimliği', 'Kısıtla'])
        kit.empty_state(self.grid_auto, 'Henüz tarama yok', 'Otomatik başlayan uygulamaları tarayın.')
        self.grid_auto.itemChanged.connect(self._auto_item_guard)
        self.grid_auto.itemChanged.connect(lambda _it: self._update_auto_count())
        self.grid_auto.horizontalHeader().setSectionResizeMode(AUTO_COL_NAME, QHeaderView.Stretch)
        self.grid_auto.horizontalHeader().setSectionResizeMode(AUTO_COL_PACKAGE, QHeaderView.Stretch)
        self.grid_auto.horizontalHeader().setSectionResizeMode(AUTO_COL_RESTRICT, QHeaderView.ResizeToContents)
        self.grid_auto.horizontalHeader().setSortIndicatorShown(True)
        self.grid_auto.horizontalHeader().setSortIndicator(AUTO_COL_NAME, Qt.AscendingOrder)
        self.grid_auto.setSortingEnabled(True)
        self._size_result_table(self.grid_auto, 0, 150)
        av.addWidget(self.grid_auto)
        self.lbl_auto_found = QLabel('')
        self.lbl_auto_found.setProperty('role', 'quiet')
        av.addWidget(self.lbl_auto_found)
        self.btn_autorun_restrict = QPushButton('Seçilenleri Kısıtla')
        self.btn_autorun_restrict.setProperty('accent', True)
        self.btn_autorun_restrict.clicked.connect(self._autorun_restrict)
        self.btn_auto_all = QPushButton('Tümünü Seç')
        self.btn_auto_all.clicked.connect(lambda: self._auto_toggle_all(True))
        self.btn_auto_none = QPushButton('Seçimi Bırak')
        self.btn_auto_none.clicked.connect(lambda: self._auto_toggle_all(False))
        self.lbl_auto_sel = QLabel('')
        self.lbl_auto_sel.setProperty('role', 'quiet')
        flow6 = FlowLayout()
        flow6.addWidget(self.btn_auto_all)
        flow6.addWidget(self.btn_auto_none)
        flow6.addWidget(self.btn_autorun_restrict)
        flow6.addWidget(self.lbl_auto_sel)
        av.addLayout(flow6)
        root.addWidget(autorun)
        root.addStretch()
        maintenance_root.addWidget(self.performance)
        maintenance_root.addWidget(advanced_page)
        maintenance_root.addStretch()
        devices_root.addStretch()

    def _open_section(self, page, target):
        self.sections.setCurrentWidget(page)
        for button, section in self._section_groups.get(page, ()):
            active = section is target
            button.setChecked(active)
            section.setVisible(active)
        QTimer.singleShot(0, lambda: page.verticalScrollBar().setValue(0)
                          if self.sections.currentWidget() is page else None)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        direction = (QBoxLayout.TopToBottom if self.width() < 620
                     else QBoxLayout.LeftToRight)
        self._overview_metrics.setDirection(direction)
        self._hardware_metrics.setDirection(direction)
        self._analysis_cards.setDirection(
            QBoxLayout.TopToBottom if self.width() < 900 else QBoxLayout.LeftToRight)

    def apply_theme(self):
        """Tema degisince: bilgi/seçim etiketleri yeni palete gecer."""
        try:
            dark = kit.dark_from(self)
            self.lbl_auto_sel.setStyleSheet(kit.faint(dark))
        except (RuntimeError, AttributeError):
            pass

    # ------------------------------------------------------------------
    def refresh(self):
        self._refresh_hardware()
        current_page = self.sections.currentWidget()
        if current_page is self.scroll_devices:
            if not self.display_panel.isHidden() and self.core.connected and self.core.target:
                self.display_panel.read_display()
            elif not self.background.isHidden():
                self.background.refresh()
        elif (current_page is self.scroll_overview
              or (current_page is self.scroll_performance and not self.performance.isHidden())):
            if getattr(self.window, '_connection_busy', False):
                self._update_measurement_summary('connecting')
            elif not self.core.connected or not self.core.target:
                self._update_measurement_summary('offline')
            elif self.performance._busy:
                worker = self.performance._worker
                if worker is not None and getattr(worker, 'job_name', '') == 'Cihaz analizi':
                    self._update_measurement_summary('loading')
                    self._watch_measurement_worker(worker)
            else:
                self._update_measurement_summary('loading')
                self._set_operation_status('')
                self.performance.refresh()
                worker = self.performance._worker
                if worker is not None and getattr(worker, 'job_name', '') == 'Cihaz analizi':
                    self._watch_measurement_worker(worker)
                elif not self.performance._busy:
                    self._update_measurement_summary('failure')
        self._sync_refresh_button()

    def _connection_changed(self, connected, _target):
        self._generation += 1
        for worker in list(self._read_workers.values()):
            worker.cancel()
        self._read_workers.clear()
        self._health_measurements = {}
        self._show({}, state='unmeasured' if connected else 'offline')
        self.lbl_display.setText('—')
        self.lbl_display_detail.setText('Henüz ölçüm alınmadı')
        self.lbl_cpu.setText('—')
        self.lbl_cpu_detail.setText('Henüz ölçüm alınmadı')
        self.grid_top.setRowCount(0)
        self.grid_auto.setRowCount(0)
        kit.empty_state(self.grid_top, 'Henüz tarama yok', 'Mevcut cihazda depolama taraması çalıştırın.')
        kit.empty_state(self.grid_auto, 'Henüz tarama yok', 'Mevcut cihazda başlangıç uygulamalarını tarayın.')
        self.lbl_perms.clear()
        self.lbl_perms.hide()
        self.lbl_auto_found.clear()
        self.lbl_auto_sel.clear()
        self._set_operation_status('')
        if connected:
            self._refresh_hardware()
        self._sync_refresh_button()

    def _refresh_hardware(self):
        if not self.core.connected or not self.core.target:
            return
        def fetch(eng, t):
            disp = eng.display_info(t)
            cpu = eng.cpu_info(t)
            return disp, cpu
        self._read('Donanım bilgisi', fetch, self._show_hardware)

    def _show_hardware(self, result):
        disp, cpu = result
        if disp and (disp.get('width') or disp.get('sink_name')):
            w = disp.get('width', '?')
            h = disp.get('height', '?')
            fps = measurement(disp.get('fps'))
            fps_text = ('{:g}'.format(fps) if fps is not None else '?')
            sink = disp.get('sink_name') or 'Android TV'
            dpi = disp.get('density') or '?'
            self.lbl_display.setText('{}×{} @ {}Hz'.format(w, h, fps_text))
            self.lbl_display_detail.setText('{} dpi · HDMI: {}'.format(dpi, sink))
        else:
            self.lbl_display.setText('—')
            self.lbl_display_detail.setText('Ekran bilgisi okunamadı')

        if cpu and (cpu.get('soc') or cpu.get('cores')):
            soc = cpu.get('soc') or 'Bilinmeyen SoC'
            cores = cpu.get('cores', 4)
            abi = cpu.get('abi', '')
            temp = cpu.get('temp') or cpu.get('temperature_c')
            if isinstance(temp, (int, float)):
                temp_str = f' · {round(temp, 1)}°C'
            elif isinstance(temp, str) and temp != '?':
                temp_str = f' · {temp}' if not temp.startswith(' ·') else temp
            else:
                temp_str = ''
            self.lbl_cpu.setText('{} ({} Çekirdek)'.format(soc, cores))
            self.lbl_cpu_detail.setText('{}{}'.format(abi, temp_str))
        else:
            self.lbl_cpu.setText('—')
            self.lbl_cpu_detail.setText('İşlemci bilgisi okunamadı')

    def _read(self, name, func, on_ok):
        if name in self._read_workers:
            return

        def closing():
            return bool(getattr(self.window, '_closing', False)
                        or getattr(self.window, '_close_pending', False))

        if closing():
            return
        if (not self.core.connected or not self.core.target
                or getattr(self.window, '_connection_busy', False)):
            self._set_operation_status('Önce cihaza bağlanın.')
            return
        target, generation = self.core.target, self._generation
        try:
            engine = self.core.engine
        except Exception as error:
            self._set_operation_status('Cihaz motoru hazır değil: ' + str(error))
            return

        def current():
            return (not closing() and self.core.connected and engine is not None
                    and self.core.engine is engine and self.core.target == target
                    and self._generation == generation
                    and not getattr(self.window, '_connection_busy', False))

        if closing():
            return
        if not current():
            self._set_operation_status('Önce cihaza bağlanın.')
            return
        if any(getattr(existing, 'job_name', None) == name and not existing.isFinished()
               for existing in getattr(self.window, '_workers', ())):
            return

        def do():
            worker.check_cancel()
            if not current():
                raise CancelledError('Bağlantı değişti.')
            return func(engine, target)

        worker = Worker(do)
        worker.job_name = name
        self._read_workers[name] = worker
        worker.finished_ok.connect(lambda result: on_ok(result) if current() else None)

        def cleanup():
            if self._read_workers.get(name) is worker:
                self._read_workers.pop(name, None)
            if not closing():
                self._sync_refresh_button()

        worker.failed.connect(lambda error: self._set_operation_status('{}: {}'.format(name, error))
                              if current() else None)
        worker.finished.connect(cleanup)
        try:
            self.window._run(worker, desc=name)
            self._sync_refresh_button()
        except Exception as error:
            cleanup()
            if current():
                self._set_operation_status('{} başlatılamadı: {}'.format(name, error))

    def _show(self, h, state=None):
        h = dict(h)
        for key in ('disk_pct', 'mem_pct'):
            value = measurement(h.get(key))
            if value is None or value > 100:
                h.pop(key, None)
            else:
                h[key] = int(value)
        measurement_keys = (
            'disk_pct', 'disk_total_kb', 'disk_avail_kb',
            'mem_pct', 'mem_total_kb', 'mem_avail_kb',
        )
        self._health_measurements = {key: h[key] for key in measurement_keys if key in h}
        measured = ('disk_pct' in h, 'mem_pct' in h)
        if state is None:
            state = ('measured' if all(measured) else 'partial' if any(measured) else 'failure')
        self._update_measurement_summary(state)
        self._set_operation_status('')
        if 'disk_pct' in h:
            self.bar_disk.setValue(h['disk_pct'])
            total = h.get('disk_total_kb')
            avail = h.get('disk_avail_kb')
            try:
                used = max(0, int(total) - int(avail))
            except (TypeError, ValueError):
                used = None
            self.lbl_disk.setText('{}%'.format(h['disk_pct']))
            self.lbl_disk_detail.setText('{} kullanılıyor · {} toplam · {} boş'.format(
                _fmt_kb(used), _fmt_kb(total), _fmt_kb(avail)) if used is not None
                else 'Depolama (/data)')
        else:
            self.lbl_disk.setText('—')
            self.lbl_disk_detail.setText('Depolama verisi okunamadı')
            self.bar_disk.setValue(0)
        if 'mem_pct' in h:
            self.bar_mem.setValue(h['mem_pct'])
            self.lbl_mem.setText('{}%'.format(h['mem_pct']))
            self.lbl_mem_detail.setText('{} toplam · {} kullanılabilir'.format(
                _fmt_kb(h.get('mem_total_kb')), _fmt_kb(h.get('mem_avail_kb'))))
        else:
            self.lbl_mem.setText('—')
            self.lbl_mem_detail.setText('Bellek verisi okunamadı')
            self.bar_mem.setValue(0)
        if 'pkg_total' in h:
            self.lbl_pkg.setText(str(h.get('pkg_total', '?')))
            self.lbl_pkg_detail.setText('{} devre dışı · {} kullanıcı 0 için kaldırılmış'.format(
                h.get('pkg_disabled', '?'), h.get('pkg_removed_u0', '?')))
        else:
            self.lbl_pkg.setText('—')
            self.lbl_pkg_detail.setText('Paket verisi okunamadı')

    def _update_measurement_summary(self, state):
        states = {
            'offline': ('Cihaz bağlı değil', 'badge'),
            'connecting': ('Bağlantı kuruluyor…', 'badge-accent'),
            'unmeasured': ('Ölçüm alınmadı', 'badge'),
            'loading': ('Ölçüm alınıyor…', 'badge-accent'),
            'failure': ('Ölçüm alınamadı', 'badge-accent'),
            'partial': ('Kısmi ölçüm', 'badge-accent'),
            'measured': ('Ölçüm güncellendi', 'badge-success'),
        }
        if state not in states:
            state = 'failure'
        label, role = states[state]
        self.lbl_measurement_state.setText(label)
        self.lbl_measurement_state.setProperty('role', role)
        self.lbl_measurement_state.style().unpolish(self.lbl_measurement_state)
        self.lbl_measurement_state.style().polish(self.lbl_measurement_state)

        data = self._health_measurements
        disk_pct = data.get('disk_pct')
        mem_pct = data.get('mem_pct')
        lines = []
        if disk_pct is not None:
            if disk_pct >= 95:
                lines.append('Depolama %{} dolu. Büyük klasörleri inceleyip yer açmayı değerlendirin.'
                             .format(disk_pct))
            elif disk_pct >= 85:
                lines.append('Depolama %{} dolu. Alan kullanımını gözden geçirin.'.format(disk_pct))
            else:
                lines.append('Depolama doluluğu: %{}.'.format(disk_pct))
        elif state == 'partial':
            lines.append('Depolama ölçümü okunamadı.')

        if mem_pct is not None:
            memory = 'Bellek: %{} kullanım ölçüldü'.format(mem_pct)
            mem_avail = measurement(data.get('mem_avail_kb'))
            if mem_avail is not None:
                memory += ' · {} kullanılabilir'.format(_fmt_kb(mem_avail))
            lines.append(memory + '.')
        elif state == 'partial':
            lines.append('Bellek ölçümü okunamadı.')

        if state == 'offline':
            text = 'Ölçüm için bir cihaza bağlanın.'
        elif state == 'connecting':
            text = 'Cihaz bağlantısı tamamlandığında ölçüm alınabilir.'
        elif state == 'unmeasured':
            text = 'Henüz ölçüm alınmadı. Yenile ile depolama ve bellek değerlerini okuyun.'
        elif state == 'loading':
            text = ('Depolama ve bellek verileri okunuyor.' if not lines else
                    'Yeni ölçüm alınıyor; son ölçülen değerler: ' + ' '.join(lines))
        elif state == 'failure':
            text = ('Depolama ve bellek değerleri alınamadı; yeniden deneyin.' if not lines else
                    'Yenileme başarısız; son başarılı ölçüm: ' + ' '.join(lines))
        elif state == 'partial':
            text = ' '.join(lines)
        elif not lines:
            self.lbl_measurement_state.setText(states['failure'][0])
            self.lbl_measurement_state.setProperty('role', states['failure'][1])
            text = 'Depolama ve bellek değerleri alınamadı; yeniden deneyin.'
        else:
            text = ' '.join(lines)
        self.lbl_measurement_summary.setText(text)

    def _set_operation_status(self, text):
        self.lbl_overview.setText(text)
        self.lbl_overview.setVisible(bool(text))

    def _watch_measurement_worker(self, worker):
        if self._summary_worker is worker:
            return
        self._summary_worker = worker
        target, generation = self.core.target, self._generation

        def failed(error):
            if (self._summary_worker is worker and self.core.connected
                    and self.core.target == target and self._generation == generation):
                self._update_measurement_summary('failure')
                self._set_operation_status('Cihaz analizi: {}'.format(error))

        worker.failed.connect(failed)
        worker.finished.connect(lambda: self._measurement_worker_finished(worker))

    def _measurement_worker_finished(self, worker):
        if self._summary_worker is worker:
            self._summary_worker = None
        QTimer.singleShot(0, self._sync_refresh_button)

    def _sync_refresh_button(self):
        if not hasattr(self, 'btn_refresh'):
            return
        hardware_worker = self._read_workers.get('Donanım bilgisi')
        busy = bool(getattr(self.performance, '_busy', False))
        busy = busy or bool(hardware_worker is not None and not hardware_worker.isFinished())
        busy = busy or bool(getattr(self.window, '_connection_busy', False))
        connected = bool(self.core.connected and self.core.target)
        self.btn_refresh.setText('Bekleyin…' if busy else 'Yenile')
        self.btn_refresh.setEnabled(connected and not busy)

    def _storage_top(self):
        self._read('Depolama taraması', lambda engine, target: engine.storage_top(target), self._show_top)

    def _show_top(self, items):
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtWidgets import QTableWidgetItem as _TWI
        self.grid_top.setRowCount(0)
        for e in items:
            r = self.grid_top.rowCount()
            self.grid_top.insertRow(r)
            pi = _TWI(e['path'])
            si = _TWI(_fmt_kb(e['kb']))
            for it in (pi, si):
                it.setFlags(_Qt.ItemIsEnabled | _Qt.ItemIsSelectable)
            self.grid_top.setItem(r, 0, pi)
            self.grid_top.setItem(r, 1, si)
        if not items:
            kit.empty_state(self.grid_top, 'Sonuç bulunamadı', 'Depolama taraması tamamlandı; eşleşen klasör bulunmadı.')
        self._size_result_table(self.grid_top, self.grid_top.rowCount(), 190)

    @staticmethod
    def _size_result_table(table, row_count, maximum):
        """Keep empty scan tables concise while showing several result rows."""
        height = max(130, row_count * kit.ROW_H + 38)
        table.setFixedHeight(min(maximum, height))

    def _show_perms(self):
        pkg = self.txt_perm_pkg.text().strip()
        if not _PACKAGE_ID_RE.fullmatch(pkg):
            QMessageBox.information(self, 'İzinler', 'Geçerli bir paket adı yazın (ör. org.videolan.vlc).')
            return

        self._read('İzin okuma', lambda engine, target: engine.app_permissions(target, pkg),
                   lambda result: self._render_perms(pkg, result))

    def _autorun_scan(self):
        def scan(engine, target):
            found = engine.autorun_receivers(target)
            try:
                labels = engine.app_labels(target)
            except Exception:
                labels = {}
            return found, labels

        self._read('Otomatik başlayan taraması', scan, self._show_autorun)

    def _show_autorun(self, found, labels=None):
        from PySide6.QtCore import Qt as _Qt3
        from PySide6.QtWidgets import QTableWidgetItem as _TWI3
        if labels is None and isinstance(found, tuple) and len(found) == 2:
            found, labels = found
        labels = labels if isinstance(labels, dict) else {}
        if not isinstance(found, dict):
            found = {}
        pkgs = sorted(p for p in found if isinstance(p, str) and _PACKAGE_ID_RE.fullmatch(p))
        header = self.grid_auto.horizontalHeader()
        sort_column, sort_order = header.sortIndicatorSection(), header.sortIndicatorOrder()
        sorting = self.grid_auto.isSortingEnabled()
        signals_blocked = self.grid_auto.blockSignals(True)
        self.grid_auto.setSortingEnabled(False)
        try:
            self.grid_auto.setRowCount(0)
            for p in pkgs:
                r = self.grid_auto.rowCount()
                self.grid_auto.insertRow(r)
                name = self._autorun_app_name(p, labels)
                name_item = _TWI3(name)
                name_item.setFlags(_Qt3.ItemIsEnabled | _Qt3.ItemIsSelectable)
                package_item = _TWI3(p)
                package_item.setData(_Qt3.UserRole, p)
                package_item.setFlags(_Qt3.ItemIsEnabled | _Qt3.ItemIsSelectable)
                check_item = _TWI3()
                check_item.setFlags((_Qt3.ItemIsUserCheckable | _Qt3.ItemIsEnabled)
                                    if p not in self.core.config.protected else _Qt3.ItemIsEnabled)
                if p in self.core.config.protected:
                    check_item.setToolTip('Korunan paket kısıtlanamaz.')
                check_item.setCheckState(_Qt3.Unchecked)
                self.grid_auto.setItem(r, AUTO_COL_NAME, name_item)
                self.grid_auto.setItem(r, AUTO_COL_PACKAGE, package_item)
                self.grid_auto.setItem(r, AUTO_COL_RESTRICT, check_item)
            if not pkgs:
                kit.empty_state(self.grid_auto, 'Sonuç bulunamadı',
                                'Otomatik başlayan paket bulunamadı.')
        finally:
            self.grid_auto.blockSignals(signals_blocked)
            self.grid_auto.setSortingEnabled(sorting)
            if sorting and 0 <= sort_column < self.grid_auto.columnCount():
                self.grid_auto.sortItems(sort_column, sort_order)
        self._size_result_table(self.grid_auto, len(pkgs), 150)
        self.lbl_auto_found.setText('{} otomatik başlayan paket bulundu.'.format(len(pkgs)))
        self._update_auto_count()

    def _autorun_app_name(self, package, labels=None):
        label = (labels or {}).get(package)
        if label and str(label).strip() and str(label).strip() != package:
            return str(label).strip()
        app_tab = getattr(self.window, 'tab_apps', None)
        for app in getattr(app_tab, '_apps', ()) or ():
            if isinstance(app, dict) and app.get('package') == package:
                label = app.get('label') or app.get('name')
                if label and str(label).strip():
                    return str(label).strip()
        try:
            label = self.core.config.friendly_name(package)
        except (AttributeError, TypeError):
            label = None
        return str(label).strip() if label and str(label).strip() else package

    def _auto_toggle_all(self, on):
        from PySide6.QtCore import Qt as _Qt
        st = _Qt.Checked if on else _Qt.Unchecked
        self.grid_auto.blockSignals(True)
        try:
            for row in range(self.grid_auto.rowCount()):
                it = self.grid_auto.item(row, AUTO_COL_RESTRICT)
                if it and (it.flags() & _Qt.ItemIsUserCheckable):
                    if it.checkState() != st:
                        it.setCheckState(st)
        finally:
            try:
                self.grid_auto.blockSignals(False)
            except (RuntimeError, AttributeError):
                pass
        self._update_auto_count()

    def _update_auto_count(self):
        from PySide6.QtCore import Qt as _Qt
        try:
            n = sum(1 for row in range(self.grid_auto.rowCount())
                    for _it in [self.grid_auto.item(row, AUTO_COL_RESTRICT)]
                    if _it is not None and (_it.flags() & _Qt.ItemIsUserCheckable)
                    and _it.checkState() == _Qt.Checked)
            self.lbl_auto_sel.setText('Seçili: {}/{}'.format(n, self.grid_auto.rowCount()))
        except (RuntimeError, AttributeError):
            pass

    def _auto_item_guard(self, item):
        # AppsTab'daki stack-overflow dersinden: sinyal yarisi olursa kilitle.
        # Bu tabloda bayrak degisimi yok; olasi ic-ice cagriyi kes.
        try:
            self.grid_auto.blockSignals(True)
        except (RuntimeError, AttributeError):
            pass
        finally:
            try:
                self.grid_auto.blockSignals(False)
            except (RuntimeError, AttributeError):
                pass

    def _autorun_restrict(self):
        from PySide6.QtCore import Qt as _Qt4

        from ..workers import BulkActionWorker

        def closing():
            return bool(getattr(self.window, '_closing', False)
                        or getattr(self.window, '_close_pending', False))

        if closing():
            return
        if (not self.core.connected or not self.core.target
                or getattr(self.window, '_connection_busy', False)):
            self._set_operation_status('Önce cihaza bağlanın.')
            return
        target, generation = self.core.target, self._generation
        try:
            engine = self.core.engine
        except Exception as error:
            self._set_operation_status('Cihaz motoru hazır değil: ' + str(error))
            return

        def current():
            return (not closing() and self.core.connected and engine is not None
                    and self.core.engine is engine and self.core.target == target
                    and self._generation == generation
                    and not getattr(self.window, '_connection_busy', False))

        if closing():
            return
        if not current() or getattr(self.window, '_workers', []):
            self.lbl_auto_found.setText('Bağlantının kurulmasını ve diğer işlemlerin bitmesini bekleyin.')
            return
        pkgs = []
        for row in range(self.grid_auto.rowCount()):
            ci = self.grid_auto.item(row, AUTO_COL_RESTRICT)
            pi = self.grid_auto.item(row, AUTO_COL_PACKAGE)
            if ci and ci.flags() & _Qt4.ItemIsUserCheckable and ci.checkState() == _Qt4.Checked and pi:
                pkgs.append(pi.data(_Qt4.UserRole))
        if not pkgs:
            QMessageBox.information(self, 'Seçim', 'Önce Kısıtla sütununda işaretleyin.')
            return
        from .dialogs import confirm_action
        if not confirm_action(self, 'restrict', pkgs,
                              self.core.config.friendly_name):
            return
        if closing():
            return
        if not current() or getattr(self.window, '_workers', []):
            self.lbl_auto_found.setText('Bağlantı veya işlem durumu değişti. Yeniden deneyin.')
            return
        w = BulkActionWorker(engine, target, tuple(pkgs), True,
                             set(self.core.config.protected), validate_packages=True)
        name = 'Otomatik başlama kısıtlaması'
        result = {'value': None, 'error': None}
        self._read_workers[name] = w

        def collect_result(value):
            result['value'] = value

        def collect_error(error):
            result['error'] = str(error)

        def report_completion():
            if closing() or not current():
                return
            error = result['error']
            if error is not None:
                self.lbl_auto_found.setText('Kısıtlama başarısız: {}'.format(error))
                return
            value = result['value']
            if not isinstance(value, dict):
                self.lbl_auto_found.setText('Kısıtlama sonucu alınamadı.')
                return
            summary = '{} başarılı, {} atlandı.'.format(
                value.get('ok', 0), value.get('skip', 0))
            self.lbl_auto_found.setText(summary)
            details = []
            for item in value.get('details', ()) or ():
                try:
                    package, succeeded, description = item
                except (TypeError, ValueError):
                    continue
                status = 'başarılı' if succeeded else 'atlandı'
                detail = str(description).strip()
                details.append('{}: {}{}'.format(
                    package, status, ' ({})'.format(detail) if detail else ''))
            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Information)
            dialog.setWindowTitle('Tamam')
            dialog.setText(summary)
            if details:
                dialog.setDetailedText('\n'.join(details))
            dialog.exec()

        def cleanup():
            if self._read_workers.get(name) is w:
                self._read_workers.pop(name, None)
            if not closing():
                self._sync_refresh_button()
                QTimer.singleShot(0, report_completion)

        w.finished_ok.connect(collect_result)
        w.failed.connect(collect_error)
        w.finished.connect(cleanup)
        try:
            self.window._run(w, desc='Sağlık: {} paket kısıtlanıyor'.format(len(pkgs)))
        except Exception as error:
            if self._read_workers.get(name) is w:
                self._read_workers.pop(name, None)
            if not closing():
                self._sync_refresh_button()
                if current():
                    self.lbl_auto_found.setText('Kısıtlama başlatılamadı: {}'.format(error))

    def _render_perms(self, pkg, res):
        self.lbl_perms.show()
        perms = res.get('all', [])
        if not perms:
            self.lbl_perms.setText(pkg + ': izin bilgisi okunamadı.')
            return
        risky = {'CAMERA', 'RECORD_AUDIO', 'ACCESS_FINE_LOCATION', 'ACCESS_COARSE_LOCATION',
                 'READ_CONTACTS', 'READ_CALL_LOG', 'READ_SMS', 'READ_PHONE_STATE'}
        lines = ['{}: {} izin ({} verilmiş)'.format(pkg, len(perms), len(res.get('granted', [])))]
        for p in perms:
            short = p['perm'].rsplit('.', 1)[-1]
            flag = ''
            if any(r in short for r in risky):
                flag = ' ⚠'
            lines.append('{} {}{}'.format('✓' if p['granted'] else '✗', short, flag))
        self.lbl_perms.setText('\n'.join(lines))
