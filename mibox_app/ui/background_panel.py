# -*- coding: utf-8 -*-
"""Explicit background restrictions, separate from the application catalogue."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabBar,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..workers import AppScanWorker, BulkActionWorker
from . import kit
from .dialogs import confirm_action
from .flowlayout import FlowLayout


class BackgroundPanel(QWidget):
    def __init__(self, core, window):
        super().__init__()
        self.core, self.window = core, window
        self._apps = []
        self._has_scan = False
        self._busy = False
        self._worker = None
        self._generation = 0
        root = kit.page(self)

        card = QFrame()
        card.setObjectName('contentCard')
        card.setProperty('role', 'secondary')
        content = QVBoxLayout(card)
        content.setContentsMargins(12, 12, 12, 12)
        content.setSpacing(8)
        heading = QLabel('Arka plan uygulamaları')
        heading.setObjectName('cardTitle')
        heading.setProperty('role', 'primary')
        content.addWidget(heading)
        content.addWidget(kit.hint_label(
            'Arka planda çalışma izinlerini yönetin. Kısıtlama bildirimleri ve eşitlemeyi etkileyebilir; '
            'bir işlemin çalışıyor görünmesi, uygulamanın ekranda açık olduğu anlamına gelmez.'
        ))

        self.category_tabs = QTabBar()
        self.category_tabs.setAccessibleName('Uygulama türü')
        self.category_tabs.setExpanding(False)
        self.category_tabs.addTab('Kullanıcı (—)')
        self.category_tabs.addTab('Sistem (—)')
        self.category_tabs.currentChanged.connect(self._render)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Uygulama veya paket ara…')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._render)
        filters = QBoxLayout(QBoxLayout.LeftToRight)
        filters.setSpacing(8)
        filters.addWidget(self.category_tabs)
        filters.addWidget(self.search, 1)
        self._filter_layout = filters
        content.addLayout(filters)

        self.grid = kit.make_table(5, ['Seç', 'Uygulama', 'Paket', 'Arka plan izni', 'Çalışıyor'])
        for col in (1, 2):
            self.grid.horizontalHeader().setSectionResizeMode(col, QHeaderView.Stretch)
        for col in (0, 3, 4):
            self.grid.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.grid.horizontalHeader().setSortIndicatorShown(True)
        self.grid.horizontalHeader().setSortIndicator(1, Qt.AscendingOrder)
        self.grid.setSortingEnabled(True)
        content.addWidget(self.grid, 1)
        kit.empty_state(self.grid, 'Henüz tarama yok', 'Yenile ile uygulamaların izinlerini okuyun.')
        actions = FlowLayout()
        self.btn_refresh = QPushButton('Yenile')
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_restrict = QPushButton('Seçilenleri Kısıtla')
        self.btn_restrict.clicked.connect(lambda: self._apply(True))
        self.btn_free = QPushButton('Seçilenleri Serbest Bırak')
        self.btn_free.clicked.connect(lambda: self._apply(False))
        for button in (self.btn_refresh, self.btn_restrict, self.btn_free):
            actions.addWidget(button)
        content.addLayout(actions)
        self.status = kit.status_label('Henüz tarama yapılmadı. Cihaza bağlanıp Yenile’ye basın.')
        self.status.setTextFormat(Qt.PlainText)
        content.addWidget(self.status)
        root.addWidget(card, 1)
        core.connection_changed.connect(self._connection_changed)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        layout = getattr(self, '_filter_layout', None)
        if layout is not None:
            direction = (QBoxLayout.TopToBottom if self.width() < 620
                         else QBoxLayout.LeftToRight)
            layout.setDirection(direction)

    def _connection_changed(self, _connected, _target):
        self._generation += 1
        if self._worker is not None:
            self._worker.cancel()
        self._apps = []
        self._has_scan = False
        self._render()
        self.status.setText('Bağlantı değişti. Yeniden tarayın.')

    def _ready(self):
        if self._busy:
            return False
        if not self.core.connected or not self.core.target or getattr(self.window, '_connection_busy', False):
            self.status.setText('Önce cihaza bağlanın.')
            return False
        return True

    def _retain(self, worker, target, generation, on_ok):
        self._busy, self._worker = True, worker
        for button in (self.btn_refresh, self.btn_restrict, self.btn_free):
            button.setEnabled(False)
        current = lambda: self.core.connected and self.core.target == target and generation == self._generation
        worker.finished_ok.connect(lambda result: on_ok(result) if current() else None)
        worker.failed.connect(lambda error: self.status.setText('İşlem tamamlanamadı: ' + str(error)) if current() else None)
        worker.finished.connect(lambda: self._cleanup(worker))
        try:
            self.window._run(worker, desc=worker.job_name)
        except Exception as error:
            self._cleanup(worker)
            self.status.setText('İşlem başlatılamadı: ' + str(error))

    def _cleanup(self, worker):
        if self._worker is worker:
            self._worker, self._busy = None, False
            for button in (self.btn_refresh, self.btn_restrict, self.btn_free):
                button.setEnabled(True)

    def refresh(self):
        if not self._ready():
            return
        target, generation = self.core.target, self._generation
        worker = AppScanWorker(self.core.engine, target, True)
        self.status.setText('Arka plan izinleri okunuyor…')
        self._retain(worker, target, generation, self._loaded)

    def _loaded(self, apps):
        self._apps = [dict(app) for app in apps if app.get('installed_user0', True)]
        self._has_scan = True
        self._render()
        self.status.setText('{} paket incelendi. Seçerek kısıtlayabilir veya serbest bırakabilirsiniz.'.format(len(self._apps)))

    def _render(self, *_args):
        text = self.search.text().casefold().replace('ı', 'i')
        system_count = sum(bool(app.get('system', False)) for app in self._apps)
        user_count = len(self._apps) - system_count
        if self._has_scan:
            self.category_tabs.setTabText(0, 'Kullanıcı ({})'.format(user_count))
            self.category_tabs.setTabText(1, 'Sistem ({})'.format(system_count))
        else:
            self.category_tabs.setTabText(0, 'Kullanıcı (—)')
            self.category_tabs.setTabText(1, 'Sistem (—)')
        show_system = self.category_tabs.currentIndex() == 1
        header = self.grid.horizontalHeader()
        sort_column, sort_order = header.sortIndicatorSection(), header.sortIndicatorOrder()
        sorting = self.grid.isSortingEnabled()
        self.grid.setSortingEnabled(False)
        try:
            self.grid.setRowCount(0)
            palette = kit.colors(self)
            for app in self._apps:
                if bool(app.get('system', False)) != show_system:
                    continue
                pkg = app['package']
                name = app.get('label') or self.core.config.friendly_name(pkg)
                if text not in (pkg + ' ' + name).casefold().replace('ı', 'i'):
                    continue
                row = self.grid.rowCount()
                self.grid.insertRow(row)
                check = QTableWidgetItem()
                allowed = pkg not in self.core.config.protected and app.get('enabled', True)
                check.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable if allowed else Qt.ItemIsEnabled)
                check.setCheckState(Qt.Unchecked)
                check.setData(Qt.UserRole, pkg)
                if not allowed:
                    check.setToolTip('Korunan veya devre dışı paket')
                self.grid.setItem(row, 0, check)

                raw_status = str(app.get('status', '')).casefold()
                if raw_status in ('kisitli', 'kısıtlı'):
                    status, status_color = 'Kısıtlı', palette['danger']
                elif raw_status == 'serbest':
                    status, status_color = 'Serbest', palette['success']
                else:
                    status, status_color = 'Bilinmiyor', palette['warning']
                raw_running = str(app.get('running', 'Bilinmiyor')).strip().casefold()
                if raw_running == 'evet':
                    running, running_color = 'Evet', palette['success']
                elif raw_running in ('hayir', 'hayır'):
                    running, running_color = 'Hayır', palette['muted']
                else:
                    running, running_color = 'Bilinmiyor', palette['warning']

                values = ((name, palette['text']), (pkg, palette['text']),
                          (status, status_color), (running, running_color))
                for col, (value, color) in enumerate(values, 1):
                    item = QTableWidgetItem(value)
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    item.setForeground(QBrush(QColor(color)))
                    self.grid.setItem(row, col, item)
            kit.empty_state(self.grid, 'Uygulama bulunamadı',
                            'Filtreyi değiştirin veya Yenile ile tekrar tarayın.')
        finally:
            self.grid.setSortingEnabled(sorting)
            if sorting and 0 <= sort_column < self.grid.columnCount():
                self.grid.sortItems(sort_column, sort_order)

    def apply_theme(self):
        self._render()

    def _apply(self, restrict):
        if not self._ready():
            return
        if getattr(self.window, '_workers', []):
            self.status.setText('Diğer işlemlerin bitmesini bekleyin.')
            return
        packages = [item.data(Qt.UserRole) for row in range(self.grid.rowCount())
                    for item in [self.grid.item(row, 0)]
                    if item.flags() & Qt.ItemIsUserCheckable and item.checkState() == Qt.Checked
                    and item.data(Qt.UserRole) not in self.core.config.protected]
        if not packages:
            self.status.setText('Önce değiştirilecek uygulamaları seçin.')
            return
        target, generation = self.core.target, self._generation
        action = 'restrict' if restrict else 'unrestrict'
        if not confirm_action(self, action, packages, self.core.config.friendly_name):
            return
        if not self._ready() or self.core.target != target or self._generation != generation or getattr(self.window, '_workers', []):
            self.status.setText('Bağlantı veya işlem durumu değişti. Yeniden deneyin.')
            return
        worker = BulkActionWorker(self.core.engine, target, tuple(packages), restrict,
                                  set(self.core.config.protected), validate_packages=True)
        self.status.setText('Seçilen paketler işleniyor…')
        self._retain(worker, target, generation, self._applied)

    def _applied(self, result):
        changed = {pkg for pkg, ok, _message in result.get('details', []) if ok}
        failed = {pkg for pkg, ok, _message in result.get('details', []) if not ok}
        for app in self._apps:
            fresh = result.get('package_states', {}).get(app['package'])
            if fresh:
                app.update(fresh)
            if app['package'] in changed:
                app['status'] = 'Kisitli' if result.get('action') == 'restrict' else 'Serbest'
            elif app['package'] in failed:
                app['status'] = 'Bilinmiyor'
        self._apps = [app for app in self._apps if app.get('installed_user0', True)]
        self._render()
        message = '{} başarılı · {} uygulanamadı/atlandı.{}'.format(
            result.get('ok', 0), result.get('skip', 0), ' İşlem durduruldu.' if result.get('cancelled') else '')
        errors = ['{}: {}'.format(pkg, reason) for pkg, ok, reason in result.get('details', []) if not ok]
        self.status.setText('\n'.join([message] + errors[:6]))
