# -*- coding: utf-8 -*-
"""Dosya sekmesi: sdcard gözat, push/pull, klasör aç, sil."""
import os
import posixpath
import tempfile
import unicodedata

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QMessageBox,
    QLineEdit, QFileDialog, QInputDialog,
)

from . import kit

from ..workers import Worker

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
        self._operation_busy = False
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
        self.lbl_breadcrumb.setProperty('role', 'secondary')
        self.lbl_breadcrumb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        nv.addWidget(self.lbl_breadcrumb)

        roots_title = QLabel('Hızlı konumlar')
        roots_title.setObjectName('metricLabel')
        roots_title.setProperty('role', 'quiet')
        nv.addWidget(roots_title)
        roots_row = kit.action_bar()
        for r in self.ROOTS:
            names = {'/sdcard': 'Depolama', '/sdcard/Download': 'İndirilenler',
                     '/sdcard/Movies': 'Filmler', '/sdcard/DCIM': 'Kamera'}
            b = QPushButton(names.get(r, r.rsplit('/', 1)[-1] or '/'))
            b.setToolTip(r)
            b.clicked.connect(lambda _=False, p=r: self._go(p))
            roots_row.addWidget(b)
        nv.addLayout(roots_row)
        root.addWidget(navigation)

        self.txt_filter = QLineEdit()
        self.txt_filter.setPlaceholderText('Dosya adında filtrele…')
        self.txt_filter.setClearButtonEnabled(True)
        self.txt_filter.textChanged.connect(self._apply_filter)
        root.addWidget(self.txt_filter)

        self.grid = kit.single_table(3, ['Ad', 'Boyut', 'Değişiklik'])
        kit.empty_state(self.grid, 'Dosyalar henüz yüklenmedi',
                        'Cihaza bağlanın ve Yenile ile klasör içeriğini alın.')
        hdr = self.grid.horizontalHeader()
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        hdr.setSectionResizeMode(COL_SIZE, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_MTIME, QHeaderView.ResizeToContents)
        self.grid.doubleClicked.connect(self._on_double)
        self.grid.itemSelectionChanged.connect(self._update_action_buttons)
        root.addWidget(self.grid, 1)

        transfer, tv = card('Dosya aktarımı')
        transfer_hint = QLabel('Dosyaları bu klasöre gönderin veya seçili bir dosyayı bilgisayara indirin.')
        transfer_hint.setWordWrap(True)
        transfer_hint.setProperty('role', 'quiet')
        tv.addWidget(transfer_hint)
        flow_row = kit.action_bar()
        self.btn_push = QPushButton('Cihaza Yükle')
        self.btn_push.setProperty('accent', True)
        self.btn_push.clicked.connect(self._push)
        self.btn_pull = QPushButton('Seçili Dosyayı İndir')
        self.btn_pull.clicked.connect(self._pull)
        flow_row.addWidget(self.btn_push)
        flow_row.addWidget(self.btn_pull)
        tv.addLayout(flow_row)
        root.addWidget(transfer)

        management, mv = card('Klasör ve dosya işlemleri')
        self.btn_mkdir = QPushButton('Klasör Aç')
        self.btn_mkdir.clicked.connect(self._mkdir)
        self.btn_del = QPushButton('Seçileni Kalıcı Olarak Sil')
        self.btn_del.setProperty('danger', True)
        self.btn_del.clicked.connect(self._delete)
        manage_row = kit.action_bar()
        manage_row.addWidget(self.btn_mkdir)
        manage_row.addWidget(self.btn_del)
        mv.addLayout(manage_row)

        self.lbl_status = kit.status_label('Hazır. Yenile ile listele.')
        mv.addWidget(self.lbl_status)
        root.addWidget(management)
        self._update_action_buttons()

    # ------------------------------------------------------------------
    def _go(self, path):
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
        self.btn_back.setEnabled(bool(self._hist))
        self.btn_up.setEnabled(self._cwd != '/')
        connected = not self._connection_problem()
        self.btn_refresh.setEnabled(connected)
        can_mutate = connected and not self._operation_busy
        self.btn_push.setEnabled(can_mutate)
        self.btn_mkdir.setEnabled(can_mutate)
        self.btn_del.setEnabled(can_mutate and self._selected() is not None)
        entry = self._selected()
        self.btn_pull.setEnabled(can_mutate and bool(entry) and not entry.get('dir'))

    def _clear_view(self, title, description):
        self._loaded = False
        self._empty_context = (title, description)
        self._entries = []
        self.grid.setRowCount(0)
        kit.empty_state(self.grid, title, description)
        self._update_action_buttons()

    def refresh(self):
        self._request_generation += 1
        request_id = self._request_generation
        target = (getattr(self.core, 'target', '') or '').strip()
        cwd = self._cwd
        problem = self._connection_problem()
        if problem:
            self.lbl_status.setText(problem)
            self._update_action_buttons()
            return
        self.lbl_status.setText('{}: okunuyor…'.format(cwd))

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

    def _show_list_error(self, error):
        worker = self.sender()
        context = getattr(worker, '_files_request_context', None)
        if context is None:
            return
        request_id, target, cwd = context
        if self._request_is_current(request_id, target, cwd):
            self.lbl_status.setText('Hata: {}'.format(error))

    def _on_connection_changed(self, connected, target):
        self._request_generation += 1
        self._clear_view(
            'Dosyalar henüz yüklenmedi',
            'Bağlantı değişti; yeni cihazın klasör içeriğini Yenile ile alın.'
            if connected else 'Cihaza bağlanın ve Yenile ile klasör içeriğini alın.')
        self.lbl_status.setText(
            'Bağlantı değişti: {}. Yenile ile listeleyin.'.format(target)
            if connected else 'Cihaz bağlantısı kesildi.')

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
        if query:
            self.lbl_status.setText('{}: {} / {} öğe'.format(
                self._cwd, len(visible), len(self._entries)))
        else:
            self.lbl_status.setText('{}: {} öğe'.format(self._cwd, len(self._entries)))
        self._update_action_buttons()

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
        self._operation_busy = True
        self._update_action_buttons()

        def finished(result):
            self._operation_busy = False
            self._update_action_buttons()
            on_ok(result)

        def failed(error):
            self._operation_busy = False
            self._update_action_buttons()
            if on_fail:
                on_fail(str(error))
            else:
                self.lbl_status.setText('Hata: {}'.format(error))

        self.window._run(worker, on_ok=finished, on_fail=failed, desc=desc)

    def _push(self):
        if not self._can_mutate():
            return
        target, cwd = self.core.target, self._cwd
        paths, _ = QFileDialog.getOpenFileNames(self, 'Cihaza Yükle', '', 'Tümü (*.*)')
        if not paths:
            return
        if not self._can_mutate(target):
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

        def do():
            for index, (path, remote) in enumerate(destinations, 1):
                w.check_cancel()
                if not self.core.connected:
                    raise RuntimeError('Bağlantı kesildi; kalan dosyalar yüklenmedi.')
                try:
                    self.core.engine.push(
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
        self._start_mutation(
            w, 'Dosyalar: {} dosya yukleniyor -> {}'.format(len(paths), cwd),
            lambda n: (self.lbl_status.setText('{} dosya yüklendi.'.format(n)),
                       self.refresh()),
            on_fail=lambda error: self.lbl_status.setText(
                'Aktarım durduruldu.' if 'kullanıcı durdurdu' in error.casefold()
                else 'Hata: {}'.format(error)))

    def _pull(self):
        if not self._can_mutate():
            return
        e = self._selected()
        if not e or e['dir']:
            QMessageBox.information(self, 'Seçim', 'Önce bir dosya seçin (klasör değil).')
            return
        target, cwd = self.core.target, self._cwd
        remote = self._remote_child(cwd, e['name'])
        dest, _ = QFileDialog.getSaveFileName(self, 'Farklı Kaydet', e['name'], 'Tümü (*.*)')
        if not dest:
            return
        if not self._can_mutate(target):
            return

        def do():
            parent = os.path.dirname(os.path.abspath(dest)) or os.getcwd()
            fd, staged = tempfile.mkstemp(
                prefix='.mibox-download-', suffix='.part', dir=parent)
            os.close(fd)
            try:
                self.core.engine.pull(
                    target, remote, staged,
                    cancel_check=w.isInterruptionRequested)
                w.check_cancel()
                if not os.path.isfile(staged):
                    raise OSError('İndirilen geçici dosya oluşturulamadı.')
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
        name, ok = QInputDialog.getText(self, 'Klasör', 'Ad:')
        if not ok or not name.strip():
            return
        if not self._can_mutate(target):
            return
        name = name.strip()
        remote = self._remote_child(cwd, name)

        def do():
            self.core.engine.file_mkdir(target, remote)
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
        full = self._remote_child(cwd, e['name'])
        if QMessageBox.question(self, u'Onay — Kalıcı Sil',
                                u'Silinsin mi? (Geri alınamaz!)\n\n• {}{}'.format(
                                    full, '  [KLASÖR]' if e.get('dir') else ''),
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        if not self._can_mutate(target):
            return

        def do():
            self.core.engine.file_remove(target, full)
            return full
        w = Worker(do)
        w.job_name = 'Dosya silme'
        self._start_mutation(
            w, 'Dosyalar: siliniyor: ' + full,
            lambda _: (self.lbl_status.setText('Silindi: ' + full), self.refresh()))
