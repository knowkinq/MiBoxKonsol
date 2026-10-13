# -*- coding: utf-8 -*-
"""Kurulum sekmesi: APK toplu kurma + HOME launcher + hızlandırma + konsol.

Kaynaklar: ADB AppControl (batch install/APKS), tvboxtools (set-home-activity,
animasyon kapatma, command gate), android-tv-debloat-toolkit (launcher akışı).
"""
import os
import glob

from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox, QFileDialog, QComboBox,
    QLineEdit, QPlainTextEdit, QAbstractItemView,
)

from ..workers import Worker
from . import kit


_PACKAGE_EXTENSIONS = ('.apk', '.apks', '.apkm', '.xapk')


class _DropQueueList(QListWidget):
    """Queue list accepting local package files and split directories."""

    def __init__(self, on_paths, parent=None):
        super().__init__(parent)
        self._on_paths = on_paths
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self._on_paths(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class _SnapshotEngineView:
    """Let snapshot.take reuse an already-connected engine without reconnecting."""

    def __init__(self, engine, target):
        self._engine = engine
        self._target = target

    def connect(self, target):
        if target != self._target:
            raise ValueError('Snapshot hedefi değiştirilemez.')
        # InstallTab checked the user's existing connection before starting.

    def __getattr__(self, name):
        return getattr(self._engine, name)


class InstallTab(QWidget):
    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._connection_generation = 0
        self._files = []
        self._statuses = {}
        self._installing = False
        self._install_worker = None
        self._install_result = None
        self._install_snapshot = ()
        self._install_operation = None
        self._build()
        connection_changed = getattr(self.core, 'connection_changed', None)
        if connection_changed is not None:
            connection_changed.connect(self._on_connection_changed)

    def _build(self):
        root = kit.page(self)

        def card(text):
            frame = QFrame()
            frame.setObjectName('contentCard')
            frame.setProperty('role', 'secondary')
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(kit.SPACING)
            heading = QLabel(text)
            heading.setObjectName('cardTitle')
            heading.setProperty('role', 'primary')
            layout.addWidget(heading)
            return frame, layout

        # A one-off APK install and the package queue share the same worker pipeline.
        g, gv = card('APK kurulumu')
        self._info = QLabel('Tek APK kurun veya paketleri kuyruğa ekleyin. '
                            'Kurulum öncesi paket durumu kaydedilir; uygulama verileri yedeklenmez.')
        self._info.setWordWrap(True)
        self._info.setProperty('role', 'quiet')
        gv.addWidget(self._info)
        self.btn_add = QPushButton('Kuyruğa Paket Ekle')
        self.btn_add.clicked.connect(self._add_files)
        self.btn_add_dir = QPushButton('Klasör Ekle (split)')
        self.btn_add_dir.clicked.connect(self._add_dir)
        self.btn_rm = QPushButton('Seçiliyi Çıkar')
        self.btn_rm.clicked.connect(self._remove_sel)
        self.btn_install = QPushButton('Kuyruktakileri Kur')
        self.btn_install.setProperty('accent', True)
        self.btn_install.clicked.connect(self._install_all)
        self.btn_single_install = QPushButton('Tek APK Seç ve Kur')
        self.btn_single_install.clicked.connect(self._install_single)
        queue_actions = kit.action_bar()
        for button in (self.btn_add, self.btn_add_dir, self.btn_rm,
                       self.btn_single_install, self.btn_install):
            queue_actions.addWidget(button)
        gv.addLayout(queue_actions)
        self.lst = _DropQueueList(self._add_paths)
        self.lst.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.lst.setFixedHeight(80)
        gv.addWidget(self.lst)
        self.lbl_queue = QLabel('Kuyruk: 0')
        self.lbl_queue.setProperty('role', 'quiet')
        gv.addWidget(self.lbl_queue)
        self.lbl_apk_empty = QLabel('Kuyruk boş. Paket ekleyin veya aşağıdan tek APK seçin.')
        self.lbl_apk_empty.setWordWrap(True)
        self.lbl_apk_empty.setProperty('role', 'quiet')
        gv.addWidget(self.lbl_apk_empty)
        self.lbl_inst = QLabel('')
        self.lbl_inst.setVisible(False)
        self.lbl_inst.setWordWrap(True)
        self.lbl_inst.setProperty('role', 'quiet')
        gv.addWidget(self.lbl_inst)
        root.addWidget(g)

        # Launcher controls remain here; animation tuning lives in Health.
        g2, v2 = card('Ana ekran')
        self._info2 = QLabel('Kurulu bir launcher seçip varsayılan ana ekran yapın. '
                             'Stok launcher korunur. Bazı cihazlarda ilk kurulum sihirbazı '
                             'kapatılır ve cihaz kurulmuş olarak işaretlenir.')
        self._info2.setWordWrap(True)
        self._info2.setProperty('role', 'quiet')
        v2.addWidget(self._info2)
        hrow = QHBoxLayout()
        self.cmb_launch = QComboBox()
        self.cmb_launch.setMinimumWidth(180)
        self.cmb_launch.setMinimumContentsLength(28)
        self.cmb_launch.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.btn_launch_scan = QPushButton('Launcherları Tara')
        self.btn_launch_scan.clicked.connect(self._scan_launchers)
        self.btn_home_cur = QPushButton('HOME Bilgisini Oku')
        self.btn_home_cur.clicked.connect(self._show_home)
        hrow.addWidget(self.cmb_launch, 1)
        hrow.addWidget(self.btn_launch_scan)
        v2.addLayout(hrow)
        self.btn_set_home = QPushButton('Varsayılan Ana Ekran Yap')
        self.btn_set_home.setProperty('accent', True)
        self.btn_set_home.clicked.connect(self._set_home)
        self.lbl_home = QLabel('Mevcut HOME: ?')
        self.lbl_home.setProperty('role', 'quiet')
        self.lbl_home.setWordWrap(True)
        home_actions = QHBoxLayout()
        home_actions.addWidget(self.lbl_home, 1)
        home_actions.addWidget(self.btn_home_cur)
        home_actions.addWidget(self.btn_set_home)
        v2.addLayout(home_actions)

        root.addWidget(g2)

        g4, v4 = card('Gelişmiş komut')
        console_hint = QLabel('Yıkıcı komutlar engellenir; cihazda değişiklik yapan komutlar onay ister.')
        console_hint.setWordWrap(True)
        console_hint.setProperty('role', 'quiet')
        v4.addWidget(console_hint)
        crow = QHBoxLayout()
        self.txt_cmd = QLineEdit()
        self.txt_cmd.setPlaceholderText('örn: getprop ro.product.model  |  settings get global animator_duration_scale')
        self.txt_cmd.returnPressed.connect(self._run_cmd)
        self.btn_cmd = QPushButton('Çalıştır')
        self.btn_cmd.setProperty('accent', True)
        self.btn_cmd.clicked.connect(self._run_cmd)
        crow.addWidget(self.txt_cmd, 1)
        crow.addWidget(self.btn_cmd)
        v4.addLayout(crow)
        self.txt_out = QPlainTextEdit()
        self.txt_out.setReadOnly(True)
        self.txt_out.setMaximumBlockCount(500)
        self.txt_out.setMaximumHeight(150)
        self.txt_out.setStyleSheet(kit.mono_style())
        v4.addWidget(self.txt_out)
        root.addWidget(g4)
        root.addStretch()

    def _set_install_status(self, text):
        self.lbl_inst.setText(text)
        self.lbl_inst.setVisible(bool(text))

    def apply_theme(self):
        """Tema degisince: bilgi etiketleri + konsol tipografisi yenilenir."""
        try:
            dark = kit.dark_from(self)
            self._info.setStyleSheet(kit.muted(dark))
            self._info2.setStyleSheet(kit.muted(dark))
            self.txt_out.setStyleSheet(kit.mono_style())
        except (RuntimeError, AttributeError):
            pass

    # --- APK ---
    def _refresh_list(self):
        self.lst.clear()
        for f in self._files:
            item = QListWidgetItem('{}  —  {}'.format(
                os.path.basename(f) or f, self._status_text(self._statuses.get(self._path_key(f), 'queued'))),
                self.lst)
            item.setData(Qt.UserRole, f)
            item.setToolTip(f)
        self.lbl_apk_empty.setVisible(not self._files)
        self.lst.setFixedHeight(min(150, max(80, len(self._files) * 30 + 8)))
        self._refresh_queue_summary()

    @staticmethod
    def _path_key(path):
        return os.path.normcase(os.path.normpath(os.path.abspath(path)))

    @staticmethod
    def _status_text(status):
        return {
            'queued': 'Bekliyor', 'installing': 'Kuruluyor', 'success': 'Kuruldu',
            'failed': 'Başarısız', 'cancelled': 'İptal edildi',
        }.get(status, status)

    def _refresh_queue_summary(self):
        counts = {name: 0 for name in ('queued', 'installing', 'success', 'failed', 'cancelled')}
        for path in self._files:
            status = self._statuses.get(self._path_key(path), 'queued')
            counts[status] = counts.get(status, 0) + 1
        if not self._files:
            self.lbl_queue.setText('Kuyruk: 0')
            return
        self.lbl_queue.setWordWrap(True)
        self.lbl_queue.setText(
            'Kuyruk: {}  ·  Bekliyor: {}  ·  Kuruluyor: {}  ·  Kuruldu: {}  ·  '
            'Başarısız: {}  ·  İptal: {}'.format(
                len(self._files), counts['queued'], counts['installing'], counts['success'],
                counts['failed'], counts['cancelled']))

    def _add_paths(self, paths):
        if self._installing:
            return 0, len(paths)
        added = rejected = 0
        known = {self._path_key(path) for path in self._files}
        for raw_path in paths:
            raw_path = os.path.expanduser(str(raw_path or '').strip())
            if not raw_path:
                rejected += 1
                continue
            path = os.path.abspath(os.path.normpath(raw_path))
            if not os.path.exists(path):
                rejected += 1
                continue
            if os.path.isdir(path):
                # install_multiple accepts a directory containing flat split APKs.
                valid = any(os.path.isfile(p) for p in glob.glob(os.path.join(path, '*.apk')))
            else:
                valid = os.path.isfile(path) and path.lower().endswith(_PACKAGE_EXTENSIONS)
            key = self._path_key(path)
            if not valid:
                rejected += 1
            elif key in known:
                continue
            else:
                known.add(key)
                self._files.append(path)
                self._statuses[key] = 'queued'
                added += 1
        self._refresh_list()
        if added or rejected:
            self._set_install_status('{} eklendi{}.'.format(
                added, ', {} geçersiz öğe atlandı'.format(rejected) if rejected else ''))
        return added, rejected

    def _add_files(self):
        if self._installing:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, 'APK Seç', '', 'Android Paketi (*.apk *.apks *.apkm *.xapk)')
        self._add_paths(paths)

    def _add_dir(self):
        if self._installing:
            return
        d = QFileDialog.getExistingDirectory(self, 'Split-APK Klasörü Seç')
        if d:
            self._add_paths([d])

    def _remove_sel(self):
        if self._installing:
            return
        for it in self.lst.selectedItems():
            full = it.data(Qt.UserRole)
            if full in self._files:
                self._files.remove(full)
                self._statuses.pop(self._path_key(full), None)
        self._refresh_list()

    def _on_connection_changed(self, *_):
        self._connection_generation += 1

    def _install_all(self):
        if self._installing:
            return
        if getattr(self.window, '_connection_busy', False):
            self._set_install_status('Bağlantı işlemi sürüyor; tamamlanınca kurulumu başlatın.')
            return
        if not self._files:
            QMessageBox.information(self, 'Kurulum', 'Önce APK ekleyin.')
            return
        self._start_install(tuple(self._files), 'batch')

    def _install_single(self):
        if self._installing:
            return
        target = getattr(self.core, 'target', None)
        connection_generation = self._connection_generation
        if getattr(self.window, '_connection_busy', False):
            self._set_install_status('Bağlantı işlemi sürüyor; tamamlanınca kurulumu başlatın.')
            return
        if not getattr(self.core, 'connected', False) or not target:
            self._set_install_status('Kurulum için önce cihaza bağlanın.')
            QMessageBox.information(self, 'Kurulum', 'Kurulumdan önce cihaza bağlanın.')
            return
        path, _ = QFileDialog.getOpenFileName(
            self, 'Tek APK Seç', '', 'APK dosyası (*.apk)')
        if not path:
            return
        path = os.path.abspath(os.path.normpath(os.path.expanduser(path)))
        if not os.path.isfile(path) or not path.lower().endswith('.apk'):
            self._set_install_status('Geçerli bir APK dosyası seçin.')
            return
        self._start_install((path,), 'single', target, connection_generation)

    def _start_install(self, files, mode, expected_target=None,
                       expected_connection_generation=None):
        if self._installing:
            return
        if getattr(self.window, '_connection_busy', False):
            self._set_install_status('Bağlantı işlemi sürüyor; tamamlanınca kurulumu başlatın.')
            return
        current_target = getattr(self.core, 'target', None)
        target = (expected_target if expected_target is not None else current_target)
        connection_generation = (expected_connection_generation
                                 if expected_connection_generation is not None
                                 else self._connection_generation)
        if (connection_generation != self._connection_generation or
                current_target != target):
            self._set_install_status('Hedef veya bağlantı değişti. Kurulumu yeniden başlatın.')
            QMessageBox.information(self, 'Kurulum', 'Hedef veya bağlantı değişti; kurulum başlatılmadı.')
            return
        if not getattr(self.core, 'connected', False) or not target:
            self._set_install_status('Kurulum için önce cihaza bağlanın.')
            QMessageBox.information(self, 'Kurulum', 'Kurulumdan önce cihaza bağlanın.')
            return

        files = tuple(files)
        shown = '\n'.join(u'• ' + os.path.basename(f) for f in files[:8])
        if len(files) > 8:
            shown += u'\n… ve {} tane daha'.format(len(files) - 8)
        if mode == 'single':
            title = 'Onay — Tek APK Kur'
            prompt = 'Bu APK kurulsun mu?\n\n{}'.format(shown)
        else:
            title = 'Onay — Kuyruktakileri Kur'
            prompt = '{} kuyruk paketi kurulsun mu?\n\n{}'.format(len(files), shown)
        if QMessageBox.question(self, title, prompt,
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        if (getattr(self.window, '_connection_busy', False) or
                not getattr(self.core, 'connected', False) or
                getattr(self.core, 'target', None) != target or
                self._connection_generation != connection_generation):
            self._set_install_status('Hedef veya bağlantı değişti. Kurulumu yeniden başlatın.')
            QMessageBox.information(self, 'Kurulum', 'Hedef veya bağlantı değişti; kurulum başlatılmadı.')
            return
        from .. import snapshot as snapmod

        try:
            engine = self.core.engine
        except Exception as exc:
            self._set_install_status('ADB motoru açılamadı: {}'.format(exc))
            return

        operation = {'files': files, 'target': target, 'mode': mode,
                     'successes': [], 'failures': [],
                     'msgs': [], 'snap': None, 'cancelled': False, 'cancel_reason': ''}
        self._install_snapshot = files
        self._install_result = None
        self._install_operation = operation
        self._installing = True
        if mode == 'batch':
            for path in files:
                self._statuses[self._path_key(path)] = 'queued'
        self._set_queue_controls_enabled(False)
        self._set_install_status('Tek APK kurulumu hazırlanıyor…' if mode == 'single'
                              else 'Kuyruk kurulumu hazırlanıyor…')
        self._refresh_list()

        def do():
            eng = engine
            t = target
            try:
                worker.check_cancel()
            except Exception as exc:
                from ..workers import CancelledError
                if isinstance(exc, CancelledError):
                    operation['cancelled'] = True
                    operation['cancel_reason'] = 'Kullanıcı durdurdu.'
                    return operation
                raise
            if (getattr(self.window, '_connection_busy', False) or
                    not getattr(self.core, 'connected', False)):
                operation['cancelled'] = True
                operation['cancel_reason'] = 'Bağlantı kesildi; paketler korunuyor.'
                return operation
            try:
                sname, _c = snapmod.take(_SnapshotEngineView(eng, t), t)
                operation['snap'] = sname
            except Exception:
                pass
            total = len(files)
            from ..workers import CancelledError
            for i, f in enumerate(files, 1):
                try:
                    worker.check_cancel()
                except CancelledError:
                    operation['cancelled'] = True
                    operation['cancel_reason'] = 'Kullanıcı durdurdu; kalanlar kuyrukta.'
                    break
                if (getattr(self.window, '_connection_busy', False) or
                        not getattr(self.core, 'connected', False)):
                    operation['cancelled'] = True
                    operation['cancel_reason'] = 'Bağlantı kesildi; kalan paketler korunuyor.'
                    break
                worker.progress.emit(i, total)
                try:
                    if os.path.isdir(f) or f.lower().endswith(('.apks', '.apkm', '.xapk')):
                        eng.install_multiple(t, f)
                    else:
                        eng.install_apk(t, f)
                    operation['successes'].append(f)
                    operation['msgs'].append('+ ' + os.path.basename(f))
                except Exception as e:
                    operation['failures'].append(f)
                    operation['msgs'].append('X {}: {}'.format(os.path.basename(f), e))
            try:
                eng.invalidate_pkg_cache(t)
            except Exception:
                pass
            return operation
        worker = Worker(do)
        worker.job_name = 'Tek APK kurma' if mode == 'single' else 'APK kuyruk kurulumu'
        worker.finished_ok.connect(self._install_done)
        worker.progress.connect(self._install_progress)
        worker.failed.connect(lambda error: self._install_failed(operation, error))
        worker.finished.connect(lambda: self._install_complete(operation, worker))
        self._install_worker = worker
        try:
            desc = ('Kurulum: tek APK kuruluyor: {}'.format(os.path.basename(files[0]))
                    if mode == 'single' else
                    'Kurulum: kuyruktaki {} paket kuruluyor'.format(len(files)))
            self.window._run(worker, desc=desc)
        except Exception:
            self._installing = False
            self._install_worker = None
            self._set_queue_controls_enabled(True)
            raise

    def _set_queue_controls_enabled(self, enabled):
        for button in (self.btn_add, self.btn_add_dir, self.btn_rm,
                       self.btn_single_install, self.btn_install):
            button.setEnabled(bool(enabled))
        self.lst.setEnabled(bool(enabled))

    def _install_progress(self, current, total):
        if not self._installing:
            return
        index = max(0, min(int(current) - 1, len(self._install_snapshot) - 1))
        if self._install_snapshot:
            operation = self._install_operation or {}
            path = self._install_snapshot[index]
            if operation.get('mode') == 'batch':
                successes = {self._path_key(p) for p in operation.get('successes', [])}
                failures = {self._path_key(p) for p in operation.get('failures', [])}
                for completed in self._install_snapshot[:index]:
                    key = self._path_key(completed)
                    if key in successes:
                        self._statuses[key] = 'success'
                    elif key in failures:
                        self._statuses[key] = 'failed'
                self._statuses[self._path_key(path)] = 'installing'
                self._refresh_list()
                self._set_install_status('{}/{} kuyruk paketi kuruluyor: {}'.format(
                    current, total, os.path.basename(path)))
            else:
                self._set_install_status('Tek APK kuruluyor: {}'.format(os.path.basename(path)))

    def _install_failed(self, operation, error):
        operation['worker_error'] = str(error)

    def _install_done(self, res):
        self._install_result = res

    def _install_complete(self, operation, worker=None):
        result = self._install_result if isinstance(self._install_result, dict) else operation
        successes = set(self._path_key(path) for path in result.get('successes', []))
        failures = set(self._path_key(path) for path in result.get('failures', []))
        if result.get('mode') == 'batch':
            for path in self._install_snapshot:
                key = self._path_key(path)
                if key in successes:
                    self._statuses.pop(key, None)
                elif key in failures:
                    self._statuses[key] = 'failed'
                elif result.get('cancelled'):
                    self._statuses[key] = 'cancelled'
                else:
                    self._statuses[key] = 'queued'
            self._files = [path for path in self._files if self._path_key(path) not in successes]
        self._installing = False
        self._install_result = None
        self._install_snapshot = ()
        self._install_operation = None
        if worker is None or worker is self._install_worker:
            self._install_worker = None
        self._set_queue_controls_enabled(True)
        self._refresh_list()

        if result.get('mode') == 'single':
            if result.get('successes'):
                lines = ['Tek APK kuruldu: {}'.format(os.path.basename(result['successes'][0]))]
            elif result.get('cancelled'):
                lines = ['Tek APK kurulumu iptal edildi: {}'.format(
                    os.path.basename((result.get('files') or ['APK'])[0]))]
            else:
                path = (result.get('failures') or result.get('files') or ['APK'])[0]
                lines = ['Tek APK kurulamadı: {}'.format(os.path.basename(path))]
        else:
            lines = ['Kuyruk sonucu: {} kuruldu, {} başarısız.'.format(
                len(result.get('successes', [])), len(result.get('failures', [])))]
        if result.get('snap'):
            lines.append('Paket durumu snapshot’ı: {} (uygulama verileri yedeklenmez).'.format(
                result['snap']))
        if result.get('cancelled'):
            lines.append(result.get('cancel_reason') or 'Kurulum iptal edildi.')
        if result.get('worker_error'):
            lines.append('İşlem hatası: ' + result['worker_error'])
        lines += result.get('msgs', [])[:15]
        self._set_install_status('\n'.join(lines))
        QMessageBox.information(self, 'Kurulum', '\n'.join(lines))
        try:
            self.window.tab_apps.refresh()
        except Exception:
            pass

    # --- HOME ---
    def _scan_launchers(self):
        def do():
            self.core.engine.connect(self.core.target)
            return self.core.engine.launcher_apps(self.core.target)
        w = Worker(do)
        w.job_name = 'Launcher tarama'
        w.finished_ok.connect(self._show_launchers)
        self.window._run(w, desc='Kurulum: launcherlar taraniyor')

    def _show_launchers(self, items):
        self.cmb_launch.clear()
        if not items:
            self.cmb_launch.addItem('(bulunamadı)', '')
            return
        for c in sorted(set(items)):
            pkg = c.split('/')[0]
            try:
                name = self.core.config.friendly_name(pkg)
            except Exception:
                name = pkg
            label = name if name.casefold() == pkg.casefold() else '{} · {}'.format(name, pkg)
            index = self.cmb_launch.count()
            self.cmb_launch.addItem(label, c)
            self.cmb_launch.setItemData(index, c, Qt.ToolTipRole)

    def _show_home(self):
        def do():
            self.core.engine.connect(self.core.target)
            return self.core.engine.home_activity(self.core.target)
        w = Worker(do)
        w.job_name = 'HOME okuma'
        w.finished_ok.connect(lambda cur: self.lbl_home.setText('Mevcut HOME: ' + cur))
        self.window._run(w, desc='Kurulum: mevcut HOME okunuyor')

    def _set_home(self):
        comp = self.cmb_launch.currentData()
        if not comp:
            QMessageBox.information(self, 'HOME', 'Önce Launcherları Tara ile seçin.')
            return
        try:
            disp = self.cmb_launch.currentText()
        except Exception:
            disp = comp
        if QMessageBox.question(self, u'Onay — Varsayılan Ana Ekran Yap',
                                u'Kalıcı HOME yapılsın mı?\n\n• {}\n\n'
                                u'Stok launcher korunur. Bazı cihazlarda ilk kurulum sihirbazı '
                                u'devre dışı bırakılır ve cihaz kurulmuş olarak işaretlenir.'.format(disp),
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return

        def do():
            eng = self.core.engine
            eng.connect(self.core.target)
            eng.set_home_activity(self.core.target, comp)
            return {'home': eng.home_activity(self.core.target),
                    'notes': list(getattr(eng, 'last_home_notes', []) or [])}
        w = Worker(do)
        w.job_name = 'HOME ayarlama'
        w.finished_ok.connect(self._home_done)
        self.window._run(w, desc='Kurulum: HOME ayarlaniyor: ' + comp)

    def _home_done(self, res):
        if isinstance(res, dict):
            cur = res.get('home', '?')
            notes = res.get('notes') or []
        else:
            cur, notes = res, []
        self.lbl_home.setText('Mevcut HOME: ' + str(cur))
        msg = 'Yeni HOME: {}'.format(cur)
        if notes:
            msg += '\n\nYapılan ek işlemler:\n- ' + '\n- '.join(str(n) for n in notes)
        QMessageBox.information(self, 'Tamam', msg)

    # --- konsol ---
    def _run_cmd(self):
        from .. import gate
        cmd = self.txt_cmd.text().strip()
        if not cmd:
            return
        cls = gate.classify(cmd)
        if cls == 'REFUSED':
            QMessageBox.critical(self, 'Kapı', gate.REFUSED_MSG)
            self.txt_out.appendPlainText('$ ' + cmd + '\nREDDEDİLDİ (yıkıcı komut).')
            return
        if cls == 'CHANGE':
            if QMessageBox.question(self, 'Onay',
                                    '[{}] {}\n\nCihazda değişiklik yapar. Çalıştırılsın mı?'.format(cls, cmd)
                                    ) != QMessageBox.Yes:
                return
        parts = cmd.split()

        def do():
            eng = self.core.engine
            eng.connect(self.core.target)
            r = eng.shell(self.core.target, *parts, timeout=30)
            return '[{}] exit={}\n{}{}'.format(
                cls, r.exit_code,
                (r.output + '\n' if r.output else ''),
                (r.error if r.error else ''))
        w = Worker(do)
        w.job_name = 'Konsol komutu'
        w.finished_ok.connect(lambda out: self.txt_out.appendPlainText('$ ' + cmd + '\n' + out))
        self.window._run(w, desc='Kurulum konsolu: ' + cmd[:80])
