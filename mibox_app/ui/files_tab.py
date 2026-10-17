# -*- coding: utf-8 -*-
"""Dosya sekmesi: sdcard gözat, push/pull, klasör oluştur, sil."""
import os
import posixpath
import tempfile
import unicodedata

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..workers import Worker
from . import kit

COL_NAME = 0
COL_SIZE = 1
COL_MTIME = 2


def _fmt_size(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return '?'
    if n >= 1024 * 1024 * 1024:
        return '{:.1f} GB'.format(n / (1024 ** 3))
    if n >= 1024 * 1024:
        return '{:.0f} MB'.format(n / (1024 ** 2))
    if n >= 1024:
        return '{:.0f} KB'.format(n / 1024)
    return '{} B'.format(n)


class FilesTab(QWidget):
    ROOTS = ['/sdcard', '/sdcard/Download', '/sdcard/Movies', '/sdcard/DCIM']

    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._cwd = '/sdcard'
        self._entries = []
        self._loaded = False
        self._empty_context = ('Dosyalar henüz yüklenmedi', 'Cihaza bağlanın ve Yenile ile klasör içeriğini alın.')
        self._hist = []
        self._request_generation = 0
        self._status_request_floor = 0
        self._connection_generation = 0
        self._operation_busy = False
        self._operation_worker = None
        self.core.connection_changed.connect(self._on_connection_changed)
        self._build()

    def _build(self):
        root = kit.page(self)

        def card(title):
            frame = QFrame()
            frame.setObjectName('contentCard')
            frame.setProperty('role', 'secondary')
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(kit.SPACING)
            heading = QLabel(title)
            heading.setObjectName('cardTitle')
            heading.setProperty('role', 'primary')
            layout.addWidget(heading)
            return frame, layout

        navigation, nv = card('Cihaz dosyaları')
        row = QHBoxLayout()
        self.btn_back = QPushButton('← Geri')
        self.btn_back.setMinimumWidth(95)
        self.btn_back.clicked.connect(self._back)
        self.btn_up = QPushButton('↑ Üst')
        self.btn_up.clicked.connect(self._up)
        self.txt_path = QLineEdit(self._cwd)
        self.txt_path.setClearButtonEnabled(True)
        self.txt_path.setToolTip('Cihazdaki klasör yolu')
        self.txt_path.returnPressed.connect(self._go_typed)
        self.btn_go = QPushButton('Git')
        self.btn_go.clicked.connect(self._go_typed)
        row.addWidget(self.btn_back)
        row.addWidget(self.txt_path, 1)
        row.addWidget(self.btn_go)
        self.btn_refresh = QPushButton('Yenile')
        self.btn_refresh.setProperty('accent', True)
        self.btn_refresh.clicked.connect(self.refresh)
        row.addWidget(self.btn_refresh)
        row.insertWidget(1, self.btn_up)
        nv.addLayout(row)

        self.lbl_breadcrumb = QLabel(' /  sdcard')
        self.lbl_breadcrumb.setTextFormat(Qt.PlainText)
        self.lbl_breadcrumb.setProperty('role', 'secondary')
        self.lbl_breadcrumb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        nv.addWidget(self.lbl_breadcrumb)

        roots_title = QLabel('Hızlı konumlar')
        roots_title.setObjectName('metricLabel')
        roots_title.setProperty('role', 'quiet')
        nv.addWidget(roots_title)
        self.roots_row = kit.action_bar()
        self._usb_buttons = []
        for r in self.ROOTS:
            names = {'/sdcard': 'Depolama', '/sdcard/Download': 'İndirilenler',
                     '/sdcard/Movies': 'Filmler', '/sdcard/DCIM': 'Kamera'}
            b = QPushButton(names.get(r, r.rsplit('/', 1)[-1] or '/'))
            b.setToolTip(r)
            b.clicked.connect(lambda _=False, p=r: self._go(p))
            self.roots_row.addWidget(b)
        nv.addLayout(self.roots_row)
        root.addWidget(navigation)

        self.txt_filter = QLineEdit()
        self.txt_filter.setPlaceholderText('Dosya adında filtrele…')
        self.txt_filter.setClearButtonEnabled(True)
        self.txt_filter.textChanged.connect(self._apply_filter)
        root.addWidget(self.txt_filter)

        self.lbl_list_summary = QLabel('Dosya listesi henüz yüklenmedi.')
        self.lbl_list_summary.setProperty('role', 'quiet')
        self.lbl_list_summary.setTextFormat(Qt.PlainText)
        root.addWidget(self.lbl_list_summary)

        self.grid = kit.single_table(3, ['Ad', 'Boyut', 'Değişiklik'])
        kit.empty_state(self.grid, 'Dosyalar henüz yüklenmedi',
                        'Cihaza bağlanın ve Yenile ile klasör içeriğini alın.')
        hdr = self.grid.horizontalHeader()
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        hdr.setSectionResizeMode(COL_SIZE, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_MTIME, QHeaderView.ResizeToContents)
        for column, alignment in (
                (COL_NAME, Qt.AlignLeft),
                (COL_SIZE, Qt.AlignRight),
                (COL_MTIME, Qt.AlignLeft)):
            self.grid.horizontalHeaderItem(column).setTextAlignment(
                alignment | Qt.AlignVCenter)
        self.grid.setMinimumHeight(240)
        self.grid.doubleClicked.connect(self._on_double)
        self.grid.itemSelectionChanged.connect(self._update_action_buttons)
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._context_menu)
        self.setAcceptDrops(True)
        self.grid.setAcceptDrops(True)
        self.grid.viewport().installEventFilter(self)
        self.grid.installEventFilter(self)
        root.addWidget(self.grid, 1)

        transfer, tv = card('Dosya aktarımı')
        transfer_hint = QLabel('Dosyaları bu klasöre gönderin, seçili bir dosyayı indirin veya sürükleyip bırakın.')
        transfer_hint.setWordWrap(True)
        transfer_hint.setProperty('role', 'quiet')
        tv.addWidget(transfer_hint)
        self.lbl_transfer_context = QLabel()
        self.lbl_transfer_context.setProperty('role', 'quiet')
        self.lbl_transfer_context.setTextFormat(Qt.PlainText)
        self.lbl_transfer_context.setWordWrap(True)
        tv.addWidget(self.lbl_transfer_context)
        flow_row = kit.action_bar()
        self.btn_push = QPushButton('Cihaza Yükle')
        self.btn_push.setProperty('accent', True)
        self.btn_push.clicked.connect(self._push)
        self.btn_pull = QPushButton('Seçili Dosyayı İndir')
        self.btn_pull.clicked.connect(self._pull)
        self.btn_install_remote = QPushButton('Cihazda Kur (APK)')
        self.btn_install_remote.setToolTip('Seçili APK dosyasını bilgisayara indirmeden doğrudan TV üzerinde kur')
        self.btn_install_remote.clicked.connect(self._install_remote_apk)
        flow_row.addWidget(self.btn_push)
        flow_row.addWidget(self.btn_pull)
        flow_row.addWidget(self.btn_install_remote)
        tv.addLayout(flow_row)
        self.progress_transfer = QProgressBar()
        self.progress_transfer.setAccessibleName('Dosya işlemi ilerlemesi')
        self.progress_transfer.hide()
        tv.addWidget(self.progress_transfer)
        self.btn_stop_transfer = QPushButton('Aktarımı durdur')
        self.btn_stop_transfer.setProperty('role', 'quiet')
        self.btn_stop_transfer.setToolTip('Devam eden aktarım için durdurma ister; TV’de kısmi dosya kalabilir.')
        self.btn_stop_transfer.clicked.connect(self._stop_transfer)
        self.btn_stop_transfer.hide()
        tv.addWidget(self.btn_stop_transfer)
        root.addWidget(transfer)

        management, mv = card('Klasör ve dosya işlemleri')
        self.btn_mkdir = QPushButton('Yeni klasör')
        self.btn_mkdir.clicked.connect(self._mkdir)
        self.btn_rename = QPushButton('Yeniden Adlandır')
        self.btn_rename.clicked.connect(self._rename)
        self.btn_del = QPushButton('Seçileni Kalıcı Olarak Sil')
        self.btn_del.setProperty('danger', True)
        self.btn_del.clicked.connect(self._delete)
        manage_row = kit.action_bar()
        manage_row.addWidget(self.btn_mkdir)
        manage_row.addWidget(self.btn_rename)
        manage_row.addWidget(self.btn_del)
        mv.addLayout(manage_row)

        self.lbl_status = kit.status_label('Hazır. Yenile ile listele.')
        self.lbl_status.setTextFormat(Qt.PlainText)
        mv.addWidget(self.lbl_status)
        root.addWidget(management)
        self._update_action_buttons()

    # ------------------------------------------------------------------
    def _go(self, path):
        if self._operation_busy:
            return
        path = posixpath.normpath(path or '/sdcard')
        if not path.startswith('/'):
            path = '/' + path
        if path != self._cwd:
            self._hist.append(self._cwd)
        self._set_path(path)

    def _set_path(self, path):
        self._cwd = path
        self.txt_path.setText(self._cwd)
        self._update_breadcrumb()
        self._clear_view('Klasör yükleniyor', 'İçerik cihazdan okunuyor…')
        self.refresh()

    def _go_typed(self):
        self._go(self.txt_path.text().strip() or '/sdcard')

    def _back(self):
        if self._operation_busy:
            return
        if self._hist:
            self._set_path(self._hist.pop())

    def _up(self):
        if self._cwd != '/':
            self._go(posixpath.dirname(self._cwd.rstrip('/')) or '/')

    def _connection_problem(self, expected_target=None):
        if getattr(self.window, '_connection_busy', False):
            return 'Bağlantı işlemi sürüyor; tamamlanınca yeniden deneyin.'
        if not getattr(self.core, 'connected', False):
            return 'Cihaz bağlı değil. Dosya işlemleri için önce bağlanın.'
        target = (getattr(self.core, 'target', '') or '').strip()
        if not target:
            return 'Bağlı cihaz hedefi bulunamadı.'
        if expected_target is not None and target != expected_target:
            return 'Bağlı cihaz değişti. Dosya işlemini yeniden başlatın.'
        return ''

    def _can_mutate(self, expected_target=None):
        if self._operation_busy:
            self.lbl_status.setText('Başka bir dosya işlemi sürüyor.')
            return False
        problem = self._connection_problem(expected_target)
        if problem:
            self.lbl_status.setText(problem)
            return False
        return True

    def _update_action_buttons(self, *_args):
        navigating = not self._operation_busy
        self.btn_back.setEnabled(navigating and bool(self._hist))
        self.btn_up.setEnabled(navigating and self._cwd != '/')
        self.btn_go.setEnabled(navigating)
        self.txt_path.setEnabled(navigating)
        for index in range(self.roots_row.count()):
            button = self.roots_row.itemAt(index).widget()
            if button is not None:
                button.setEnabled(navigating)
        connected = not self._connection_problem()
        self.btn_refresh.setEnabled(connected and navigating)
        can_mutate = connected and not self._operation_busy
        self.btn_push.setEnabled(can_mutate)
        self.btn_mkdir.setEnabled(can_mutate)
        has_sel = self._selected() is not None
        self.btn_del.setEnabled(can_mutate and has_sel)
        if hasattr(self, 'btn_rename'):
            self.btn_rename.setEnabled(can_mutate and has_sel)
        entry = self._selected()
        is_file = bool(entry) and not entry.get('dir')
        self.btn_pull.setEnabled(can_mutate and is_file)
        is_apk = is_file and str(entry.get('name', '')).lower().endswith('.apk')
        self.btn_install_remote.setEnabled(can_mutate and is_apk)
        self._update_transfer_context()

    def _update_transfer_context(self):
        if not hasattr(self, 'lbl_transfer_context'):
            return
        entry = self._selected()
        if entry is None:
            selection = 'Seçim: yok'
        elif entry.get('dir'):
            selection = 'Seçili klasör: {}'.format(entry.get('name', ''))
        else:
            selection = 'Seçili dosya: {} ({})'.format(
                entry.get('name', ''), _fmt_size(entry.get('size')))
        self.lbl_transfer_context.setText(
            '{}\nCihaza yükleme hedefi: {}'.format(selection, self._cwd))

    def _clear_view(self, title, description):
        self._loaded = False
        self._empty_context = (title, description)
        self._entries = []
        self.grid.setRowCount(0)
        kit.empty_state(self.grid, title, description)
        self._update_list_summary([])
        self._update_action_buttons()

    def refresh(self):
        if self._operation_busy:
            return
        self._request_generation += 1
        request_id = self._request_generation
        target = (getattr(self.core, 'target', '') or '').strip()
        cwd = self._cwd
        problem = self._connection_problem()
        if problem:
            if not self.core.connected:
                self._clear_view(
                    'Cihaz bağlı değil',
                    'Dosyaları görmek için cihaza bağlanın, ardından Yenile’ye basın.')
            elif not self._loaded:
                self._clear_view('Dosya listesi bekliyor', problem)
            self.lbl_status.setText(problem)
            self._update_action_buttons()
            return
        if not self._loaded:
            self._clear_view('Klasör yükleniyor', 'İçerik cihazdan okunuyor…')
        self.lbl_status.setText('{}: okunuyor…'.format(cwd))
        self._check_usb_storages(target)

        def do():
            return request_id, target, cwd, self.core.engine.file_list(target, cwd)
        w = Worker(do)
        w.job_name = 'Dosya listeleme'
        w._files_request_context = (request_id, target, cwd)
        w.finished_ok.connect(self._show_request)
        w.failed.connect(self._show_list_error)
        self.window._run(w, desc='Dosyalar Yenile: liste okunuyor')

    def _request_is_current(self, request_id, target, cwd):
        return (request_id == self._request_generation
                and cwd == self._cwd
                and target == getattr(self.core, 'target', None)
                and not self._connection_problem())

    def _show_request(self, result):
        request_id, target, cwd, entries = result
        if self._request_is_current(request_id, target, cwd):
            self._show(entries)
            if not self._operation_busy and request_id >= self._status_request_floor:
                self.lbl_status.setText('Klasör içeriği güncellendi.')

    def _show_list_error(self, error):
        worker = self.sender()
        context = getattr(worker, '_files_request_context', None)
        if context is None:
            return
        request_id, target, cwd = context
        if self._request_is_current(request_id, target, cwd):
            if not self._loaded:
                self._clear_view(
                    'Klasör okunamadı',
                    'Bağlantıyı ve klasör yolunu kontrol edin; Yenile ile tekrar deneyin.')
            if not self._operation_busy and request_id >= self._status_request_floor:
                self.lbl_status.setText('Dosya listesi yüklenemedi: {}'.format(error))

    def _on_connection_changed(self, connected, target):
        self._connection_generation += 1
        self._request_generation += 1
        self._clear_view(
            'Dosyalar henüz yüklenmedi',
            'Bağlantı değişti; yeni cihazın klasör içeriğini Yenile ile alın.'
            if connected else 'Cihaza bağlanın ve Yenile ile klasör içeriğini alın.')
        self.lbl_status.setText(
            'Bağlantı değişti: {}. Yenile ile listeleyin.'.format(target)
            if connected else 'Cihaz bağlantısı kesildi.')
        self._update_usb_buttons([])
        if connected and target:
            self._check_usb_storages(target)

    def _check_usb_storages(self, target):
        if not target or self._connection_problem():
            return
        generation = self._connection_generation
        def do():
            try:
                storages = self.core.engine.usb_storages(target)
            except Exception:
                storages = []
            return target, generation, storages
        w = Worker(do)
        w.job_name = 'USB kontrolü'
        w.finished_ok.connect(self._show_usb_storages)
        self.window._run(w, desc='USB sürücü kontrolü')

    def _show_usb_storages(self, result):
        target, generation, storages = result
        if (generation == self._connection_generation
                and self.core.connected and self.core.target == target):
            self._update_usb_buttons(storages)

    def _update_usb_buttons(self, storages):
        for b in list(self._usb_buttons):
            self.roots_row.removeWidget(b)
            b.deleteLater()
        self._usb_buttons.clear()
        for s in (storages or []):
            path = s.get('path')
            if not path:
                continue
            name = s.get('name') or path.rsplit('/', 1)[-1]
            free = _fmt_size(s.get('free', 0))
            btn = QPushButton('💾 USB: {}'.format(name))
            btn.setToolTip('{} (Boş alan: {})'.format(path, free))
            btn.clicked.connect(lambda _=False, p=path: self._go(p))
            self.roots_row.addWidget(btn)
            self._usb_buttons.append(btn)
        self._update_action_buttons()

    def eventFilter(self, watched, event):
        if watched in (self.grid, self.grid.viewport()):
            if event.type() == QEvent.DragEnter:
                if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
                    event.acceptProposedAction()
                    return True
            elif event.type() == QEvent.Drop:
                urls = event.mimeData().urls()
                paths = [u.toLocalFile() for u in urls if u.isLocalFile()]
                if paths:
                    event.acceptProposedAction()
                    self._push_paths(paths)
                    return True
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            if paths:
                event.acceptProposedAction()
                self._push_paths(paths)
                return
        super().dropEvent(event)

    def _update_breadcrumb(self):
        parts = [part for part in self._cwd.strip('/').split('/') if part]
        self.lbl_breadcrumb.setText(' /  ' + '  /  '.join(parts) if parts else '/')

    def _show(self, entries):
        self._loaded = True
        self._entries = list(entries or [])
        self._apply_filter()

    def _apply_filter(self, *_args):
        query = self.txt_filter.text().strip().casefold()
        visible = [e for e in self._entries
                   if not query or query in str(e.get('name', '')).casefold()]
        self.grid.setRowCount(0)
        for e in visible:
            r = self.grid.rowCount()
            self.grid.insertRow(r)
            name = ('📁 ' if e['dir'] else '📄 ') + e['name']
            ni = QTableWidgetItem(name)
            ni.setData(Qt.UserRole, e)
            si = QTableWidgetItem('' if e['dir'] else _fmt_size(e['size']))
            mi = QTableWidgetItem(e['mtime'])
            ni.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            si.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            mi.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            for it in (ni, si, mi):
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.grid.setItem(r, COL_NAME, ni)
            self.grid.setItem(r, COL_SIZE, si)
            self.grid.setItem(r, COL_MTIME, mi)
        if not self._loaded:
            kit.empty_state(self.grid, *self._empty_context)
        elif not self._entries:
            kit.empty_state(self.grid, 'Bu klasör boş',
                            'Başka bir konuma gidin veya buraya dosya yükleyin.')
        elif not visible:
            kit.empty_state(self.grid, 'Eşleşme yok',
                            'Dosya adı filtresini değiştirin veya temizleyin.')
        else:
            kit.empty_state(self.grid, '', '')
        self._update_list_summary(visible)
        self._update_action_buttons()

    def _update_list_summary(self, visible=None):
        if not hasattr(self, 'lbl_list_summary'):
            return
        if not self._loaded:
            self.lbl_list_summary.setText('Dosya listesi henüz yüklenmedi.')
            return
        if visible is None:
            query = self.txt_filter.text().strip().casefold()
            visible = [e for e in self._entries
                       if not query or query in str(e.get('name', '')).casefold()]
        files = [entry for entry in visible if not entry.get('dir', False)]
        known_sizes = []
        unknown_sizes = 0
        for entry in files:
            try:
                size = int(entry.get('size'))
                if size < 0:
                    raise ValueError
                known_sizes.append(size)
            except (TypeError, ValueError):
                unknown_sizes += 1
        size_summary = _fmt_size(sum(known_sizes))
        if unknown_sizes:
            size_summary += ' · {} dosyanın boyutu bilinmiyor'.format(unknown_sizes)
        self.lbl_list_summary.setText(
            'Yüklenen listede {} öğe · gösterilen {} öğe ({} dosya, {})'.format(
                len(self._entries), len(visible), len(files), size_summary))

    def _selected(self):
        row = self.grid.currentRow()
        item = self.grid.item(row, COL_NAME) if row >= 0 else None
        return item.data(Qt.UserRole) if item is not None else None

    def _on_double(self, index):
        item = self.grid.item(index.row(), COL_NAME)
        e = item.data(Qt.UserRole) if item is not None else None
        if e and e['dir']:
            self._go(self._remote_child(self._cwd, e['name']))

    @staticmethod
    def _remote_child(cwd, name):
        return (cwd.rstrip('/') + '/' + str(name)) if cwd != '/' else '/' + str(name)

    def _start_mutation(self, worker, desc, on_ok, on_fail=None):
        if (getattr(self.window, '_closing', False)
                or getattr(self.window, '_close_pending', False)
                or not self._can_mutate()):
            worker.deleteLater()
            return
        target = self.core.target
        generation = self._connection_generation
        engine = self.core.engine
        original_func = worker._func
        original_args, original_kwargs = worker._args, worker._kwargs

        def is_current():
            return (generation == self._connection_generation
                    and self.core.connected and self.core.target == target
                    and self.core.engine is engine
                    and not getattr(self.window, '_connection_busy', False))

        def guarded():
            worker.check_cancel()
            if not is_current():
                from ..workers import CancelledError
                raise CancelledError('bağlantı değişti')
            return original_func(*original_args, **original_kwargs)

        worker._func = guarded
        worker._args, worker._kwargs = (), {}
        self._operation_busy = True
        self._status_request_floor = self._request_generation + 1
        self._operation_worker = worker
        self.progress_transfer.setRange(0, 0)
        self.progress_transfer.show()
        self.btn_stop_transfer.setVisible(bool(getattr(worker, '_files_transfer', False)))
        self.btn_stop_transfer.setEnabled(True)
        self.lbl_status.setText(desc)
        self._update_action_buttons()
        results, errors = [], []
        worker.finished_ok.connect(results.append)
        worker.failed.connect(errors.append)

        def progress(current, total):
            if self._operation_worker is worker and is_current() and total > 0:
                self.progress_transfer.setRange(0, total)
                self.progress_transfer.setValue(current)
                self.progress_transfer.setFormat('%v / %m dosya')

        def finished():
            if self._operation_worker is not worker:
                return
            self._operation_worker = None
            self._operation_busy = False
            self.progress_transfer.hide()
            self.btn_stop_transfer.hide()
            self._update_action_buttons()
            if (not is_current() or getattr(self.window, '_closing', False)
                    or getattr(self.window, '_close_pending', False)):
                return
            if results:
                on_ok(results[0])
            else:
                error = str(errors[-1] if errors else 'İşlem tamamlanamadı.')
                if on_fail:
                    on_fail(error)
                else:
                    self.lbl_status.setText('Hata: ' + error)

        worker.progress.connect(progress)
        worker.finished.connect(finished)
        try:
            self.window._run(worker, desc=desc)
        except Exception as error:
            errors.append(str(error))
            finished()

    def _stop_transfer(self):
        worker = self._operation_worker
        if worker is None or not getattr(worker, '_files_transfer', False):
            return
        worker.cancel()
        self.btn_stop_transfer.setEnabled(False)
        self.lbl_status.setText('Aktarım durduruluyor; tamamlanmasını bekleyin.')

    def _push(self):
        if not self._can_mutate():
            return
        target, cwd, generation = self.core.target, self._cwd, self._connection_generation
        paths, _ = QFileDialog.getOpenFileNames(self, 'Cihaza Yükle', '', 'Tümü (*.*)')
        if paths:
            if (generation != self._connection_generation or cwd != self._cwd
                    or not self._can_mutate(target)):
                self.lbl_status.setText('Bağlantı veya klasör değişti; dosyaları yeniden seçin.')
                return
            self._push_paths(paths)

    def _push_paths(self, paths):
        if not self._can_mutate():
            return
        target, cwd = self.core.target, self._cwd
        generation = self._connection_generation
        paths = [os.path.abspath(p) for p in paths if os.path.exists(p)]
        if not paths:
            return
        if (generation != self._connection_generation
                or not self._can_mutate(target)):
            self.lbl_status.setText('Bağlantı değişti veya işlem sürüyor; yeniden deneyin.')
            return
        names = {}
        for path in paths:
            name = os.path.basename(path)
            key = unicodedata.normalize('NFC', name).casefold()
            names.setdefault(key, []).append(name)
        duplicates = sorted({name for matches in names.values() if len(matches) > 1
                             for name in matches}, key=str.casefold)
        if duplicates:
            QMessageBox.warning(
                self, 'Dosya adları çakışıyor',
                'Aynı ada sahip dosyalar aynı klasöre yüklenemez. '
                'Dosyaları yeniden adlandırıp tekrar seçin:\n\n' +
                '\n'.join(duplicates))
            return
        destinations = [(p, self._remote_child(cwd, os.path.basename(p))) for p in paths]

        engine = self.core.engine

        def do():
            for index, (path, remote) in enumerate(destinations, 1):
                w.check_cancel()
                if (not self.core.connected or self.core.target != target
                        or generation != self._connection_generation):
                    raise RuntimeError('Hedef veya bağlantı değişti; kalan dosyalar yüklenmedi.')
                try:
                    engine.push(
                        target, path, remote,
                        cancel_check=w.isInterruptionRequested)
                except Exception:
                    if w.isInterruptionRequested():
                        w.log.emit(
                            'Aktarım durduruldu; hedefte kısmi dosya kalmış olabilir.')
                        w.check_cancel()
                    raise
                w.progress.emit(index, len(destinations))
            return len(destinations)
        w = Worker(do)
        w.job_name = 'Dosya yukleme'
        w._files_transfer = True
        self._start_mutation(
            w, 'Dosyalar: {} dosya yukleniyor -> {}'.format(len(paths), cwd),
            lambda n: (self.lbl_status.setText('{} dosya yüklendi.'.format(n)),
                       self.refresh()),
            on_fail=lambda error: self.lbl_status.setText(
                'Yükleme durduruldu; TV’de tamamlanmış veya kısmi dosyalar kalmış olabilir.'
                if 'kullanıcı durdurdu' in error.casefold()
                else 'Yükleme tamamlanamadı: {}. Bazı dosyalar aktarılmış olabilir.'.format(error)))

    def _pull(self):
        if not self._can_mutate():
            return
        e = self._selected()
        if not e or e['dir']:
            QMessageBox.information(self, 'Seçim', 'Önce bir dosya seçin (klasör değil).')
            return
        target, cwd = self.core.target, self._cwd
        generation = self._connection_generation
        remote = self._remote_child(cwd, e['name'])
        dest, _ = QFileDialog.getSaveFileName(self, 'Farklı Kaydet', e['name'], 'Tümü (*.*)')
        if not dest:
            return
        if (generation != self._connection_generation
                or not self._can_mutate(target)):
            self.lbl_status.setText('Bağlantı değişti veya işlem sürüyor; yeniden deneyin.')
            return

        engine = self.core.engine
        expected_size = e.get('size')

        def do():
            parent = os.path.dirname(os.path.abspath(dest)) or os.getcwd()
            fd, staged = tempfile.mkstemp(
                prefix='.mibox-download-', suffix='.part', dir=parent)
            os.close(fd)
            try:
                engine.pull(
                    target, remote, staged,
                    cancel_check=w.isInterruptionRequested)
                w.check_cancel()
                if not os.path.isfile(staged):
                    raise OSError('İndirilen geçici dosya oluşturulamadı.')
                if (type(expected_size) is int and expected_size >= 0
                        and os.path.getsize(staged) != expected_size):
                    raise OSError('İndirilen dosyanın boyutu listeyle eşleşmiyor. '
                                  'TV’de dosya değişmiş veya aktarım eksik kalmış olabilir; '
                                  'listeyi yenileyip tekrar deneyin. Mevcut yerel dosya korundu.')
                w.check_cancel()
                os.replace(staged, dest)
            except Exception:
                if w.isInterruptionRequested():
                    w.log.emit(
                        'Aktarım durduruldu; geçici indirme temizlendi, mevcut dosya korundu.')
                    w.check_cancel()
                raise
            finally:
                try:
                    os.remove(staged)
                except OSError:
                    pass
            return dest
        w = Worker(do)
        w.job_name = 'Dosya indirme'
        w._files_transfer = True
        self._start_mutation(
            w, 'Dosyalar: indiriliyor: ' + e['name'],
            lambda d: self.lbl_status.setText('İndirildi: ' + d),
            on_fail=lambda error: self.lbl_status.setText(
                'Aktarım durduruldu.' if 'kullanıcı durdurdu' in error.casefold()
                else 'Hata: {}'.format(error)))

    def _mkdir(self):
        if not self._can_mutate():
            return
        target, cwd = self.core.target, self._cwd
        generation = self._connection_generation
        name, ok = QInputDialog.getText(self, 'Klasör', 'Ad:')
        if not ok or not name.strip():
            return
        if (generation != self._connection_generation
                or not self._can_mutate(target)):
            self.lbl_status.setText('Bağlantı değişti veya işlem sürüyor; yeniden deneyin.')
            return
        name = name.strip()
        if (name in ('.', '..') or '/' in name or '\\' in name
                or any(unicodedata.category(ch) == 'Cc' for ch in name)):
            QMessageBox.warning(self, 'Klasör', 'Klasör adı tek bir geçerli ad olmalıdır.')
            return
        remote = self._remote_child(cwd, name)

        engine = self.core.engine

        def do():
            engine.file_mkdir(target, remote)
            return name
        w = Worker(do)
        w.job_name = 'Klasör olusturma'
        self._start_mutation(
            w, 'Dosyalar: klasör aciliyor: ' + name,
            lambda _: (self.lbl_status.setText('Klasör oluşturuldu: ' + name),
                       self.refresh()))

    def _delete(self):
        if not self._can_mutate():
            return
        e = self._selected()
        if not e:
            QMessageBox.information(self, 'Seçim', 'Önce öğe seçin.')
            return
        target, cwd = self.core.target, self._cwd
        generation = self._connection_generation
        full = self._remote_child(cwd, e['name'])
        if QMessageBox.question(self, u'Onay — Kalıcı Sil',
                                u'Silinsin mi? (Geri alınamaz!)\n\n• {}{}'.format(
                                    full, '  [KLASÖR]' if e.get('dir') else ''),
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        if (generation != self._connection_generation
                or not self._can_mutate(target)):
            self.lbl_status.setText('Bağlantı değişti veya işlem sürüyor; yeniden deneyin.')
            return

        engine = self.core.engine

        def do():
            engine.file_remove(target, full)
            return full
        w = Worker(do)
        w.job_name = 'Dosya silme'
        self._start_mutation(
            w, 'Dosyalar: siliniyor: ' + full,
            lambda _: (self.lbl_status.setText('Silindi: ' + full), self.refresh()))

    def _rename(self):
        if not self._can_mutate():
            return
        e = self._selected()
        if not e:
            QMessageBox.information(self, 'Seçim', 'Önce öğe seçin.')
            return
        old_name = e.get('name', '')
        target, cwd = self.core.target, self._cwd
        generation = self._connection_generation
        old_path = self._remote_child(cwd, old_name)

        new_name, ok = QInputDialog.getText(
            self, 'Yeniden Adlandır',
            'Yeni ad girin:', QLineEdit.Normal, old_name
        )
        if not ok or not new_name.strip() or new_name.strip() == old_name:
            return
        if (generation != self._connection_generation
                or not self._can_mutate(target)):
            self.lbl_status.setText('Bağlantı değişti veya işlem sürüyor; yeniden deneyin.')
            return

        new_name = new_name.strip()
        if (new_name in ('.', '..') or '/' in new_name or '\\' in new_name
                or any(unicodedata.category(ch) == 'Cc' for ch in new_name)):
            QMessageBox.warning(self, 'Yeniden Adlandır',
                                'Yeni ad tek bir geçerli dosya veya klasör adı olmalıdır.')
            return
        new_path = self._remote_child(cwd, new_name)

        engine = self.core.engine

        def do():
            engine.rename_file(target, old_path, new_path)
            return new_name

        w = Worker(do)
        w.job_name = 'Yeniden adlandirma'
        self._start_mutation(
            w, 'Dosyalar: yeniden adlandırılıyor: {} → {}'.format(old_name, new_name),
            lambda _: (self.lbl_status.setText('Adı değiştirildi: ' + new_name),
                       self.refresh())
        )

    def _context_menu(self, pos):
        if not getattr(self.core, 'connected', False):
            return
        clicked_item = self.grid.itemAt(pos)
        if clicked_item is not None and clicked_item.row() != self.grid.currentRow():
            self.grid.setCurrentCell(clicked_item.row(), clicked_item.column())
        elif clicked_item is None:
            self.grid.clearSelection()
            self.grid.setCurrentCell(-1, -1)
        menu = QMenu(self)
        entry = self._selected()
        generation, cwd = self._connection_generation, self._cwd
        selected_name = entry.get('name') if entry else None

        def invoke(callback):
            selected = self._selected()
            name_now = selected.get('name') if selected else None
            if (generation != self._connection_generation or cwd != self._cwd
                    or name_now != selected_name or self._operation_busy
                    or self._connection_problem()):
                self.lbl_status.setText('Bağlantı, klasör veya seçim değişti; menüyü yeniden açın.')
                return
            callback()

        can_mutate = not self._connection_problem() and not self._operation_busy

        if entry:
            name = entry.get('name', '')
            is_dir = entry.get('dir', False)
            is_apk = not is_dir and str(name).lower().endswith('.apk')

            if is_dir:
                a_open = menu.addAction('📂 {} Klasörünü Aç'.format(name))
                a_open.triggered.connect(lambda: invoke(lambda: self._go(self._remote_child(cwd, name))))
            else:
                a_pull = menu.addAction('📥 Bilgisayara İndir (Pull)')
                a_pull.setEnabled(can_mutate)
                a_pull.triggered.connect(lambda: invoke(self._pull))
                if is_apk:
                    a_install = menu.addAction('🚀 TV\'de Kur (APK)')
                    a_install.setEnabled(can_mutate)
                    a_install.triggered.connect(lambda: invoke(self._install_remote_apk))

            menu.addSeparator()
            a_copy = menu.addAction('📋 Tam Yolu Kopyala')
            a_copy.triggered.connect(lambda: QApplication.clipboard().setText(self._remote_child(cwd, name)))

            a_rename = menu.addAction('✏️ Yeniden Adlandır')
            a_rename.setEnabled(can_mutate)
            a_rename.triggered.connect(lambda: invoke(self._rename))

            a_del = menu.addAction('🗑 Kalıcı Olarak Sil')
            a_del.setEnabled(can_mutate)
            a_del.triggered.connect(lambda: invoke(self._delete))
        else:
            a_mkdir = menu.addAction('📁 Yeni Klasör Oluştur')
            a_mkdir.setEnabled(can_mutate)
            a_mkdir.triggered.connect(lambda: invoke(self._mkdir))

            a_push = menu.addAction('📤 Bilgisayardan Dosya Yükle (Push)')
            a_push.setEnabled(can_mutate)
            a_push.triggered.connect(lambda: invoke(self._push))

            menu.addSeparator()
            a_refresh = menu.addAction('🔄 Yenile')
            a_refresh.triggered.connect(lambda: invoke(self.refresh))

        menu.exec(self.grid.viewport().mapToGlobal(pos))

    def _install_remote_apk(self):
        if not self._can_mutate():
            return
        e = self._selected()
        if not e or e.get('dir') or not str(e.get('name', '')).lower().endswith('.apk'):
            QMessageBox.information(self, 'Seçim', 'Kurulacak bir APK dosyası seçin.')
            return
        target, cwd = self.core.target, self._cwd
        generation = self._connection_generation
        remote = self._remote_child(cwd, e['name'])
        if QMessageBox.question(
                self, 'Onay — Cihazda Kur',
                'Bu APK doğrudan TV üzerinde kurulsun mu?\n\n• {}'.format(remote),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        if (generation != self._connection_generation
                or not self._can_mutate(target)):
            self.lbl_status.setText('Bağlantı değişti veya işlem sürüyor; yeniden deneyin.')
            return

        grant = getattr(self.core.config, 'install_grant_perms', True)

        engine = self.core.engine

        def do():
            return engine.install_remote_apk(target, remote, grant_perms=grant)

        w = Worker(do)
        w.job_name = 'Cihazda APK kurma'
        self._start_mutation(
            w, 'Dosyalar: Cihazda kuruluyor: ' + e['name'],
            lambda res: (self.lbl_status.setText('Cihazda kuruldu: ' + str(res)),
                         QMessageBox.information(self, 'Kurulum Tamamlandı',
                                                 'APK başarıyla TV üzerinde kuruldu:\n\n' + e['name'])),
            on_fail=lambda error: QMessageBox.critical(self, 'Kurulum Hatası', str(error)))
