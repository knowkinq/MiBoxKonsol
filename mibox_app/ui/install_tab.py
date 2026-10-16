# -*- coding: utf-8 -*-
"""Kurulum sekmesi: APK toplu kurma + HOME launcher + hızlandırma + konsol.

Kaynaklar: ADB AppControl (batch install/APKS), tvboxtools (set-home-activity,
animasyon kapatma, command gate), android-tv-debloat-toolkit (launcher akışı).
"""
import os
import glob
import html

from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox, QFileDialog, QComboBox,
    QLineEdit, QPlainTextEdit, QAbstractItemView,
    QTableWidget, QTableWidgetItem, QTabWidget, QProgressBar, QHeaderView,
    QDialog, QDialogButtonBox,
)

from ..workers import Worker
from ..catalog import TV_CATALOG, TV_CATEGORIES, get_catalog, download_apk
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

    def connect(self, target, cancel_check=None):
        if target != self._target:
            raise ValueError('Snapshot hedefi değiştirilemez.')
        # InstallTab checked the user's existing connection before starting.
        if cancel_check is not None and cancel_check():
            from ..workers import CancelledError
            raise CancelledError('kullanıcı durdurdu')

    def __getattr__(self, name):
        return getattr(self._engine, name)


class InstallTab(QWidget):
    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._connection_generation = 0
        self._catalog_refresh_generation = 0
        self._files = []
        self._statuses = {}
        self._installing = False
        self._install_worker = None
        self._install_result = None
        self._install_snapshot = ()
        self._install_operation = None
        self._meta_cache = {}
        self._installed_pkgs = set()
        self._catalog_status_known = False
        self._catalog_status_target = None
        self._catalog_status_error_target = None
        self._catalog_installing = set()
        self._catalog_worker = None
        self._catalog_refresh_pending = False
        self._catalog_layout_timer = QTimer(self)
        self._catalog_layout_timer.setSingleShot(True)
        self._catalog_layout_timer.timeout.connect(self._update_catalog_columns)
        self._build()
        self._populate_catalog_table()
        connection_changed = getattr(self.core, 'connection_changed', None)
        if connection_changed is not None:
            connection_changed.connect(self._on_connection_changed)
        if getattr(self.core, 'connected', False):
            self._refresh_catalog_statuses()

    def _build(self):
        root = kit.page(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.subtabs = QTabWidget()
        root.addWidget(self.subtabs)

        # ----------------------------------------------------
        # SEKME 1: Popüler TV Uygulamaları (Mağaza)
        # ----------------------------------------------------
        tab_catalog = QWidget()
        cat_layout = QVBoxLayout(tab_catalog)
        cat_layout.setContentsMargins(10, 10, 10, 10)
        cat_layout.setSpacing(kit.SPACING)

        cat_toolbar = QHBoxLayout()
        cat_toolbar.setSpacing(8)

        self.cmb_catalog_cat = QComboBox()
        for c in TV_CATEGORIES:
            self.cmb_catalog_cat.addItem(c)
        self.cmb_catalog_cat.setAccessibleName('Katalog kategorisi')
        self.cmb_catalog_cat.setAccessibleDescription('Uygulamaları kategoriye göre filtreleyin.')
        self.cmb_catalog_cat.setToolTip('Katalog uygulamalarını kategoriye göre filtreleyin.')
        self.cmb_catalog_cat.currentIndexChanged.connect(lambda _: self._populate_catalog_table())

        self.txt_catalog_search = QLineEdit()
        self.txt_catalog_search.setClearButtonEnabled(True)
        self.txt_catalog_search.setAccessibleName('Katalogda uygulama ara')
        self.txt_catalog_search.setToolTip('Uygulama adı, açıklaması veya paket adına göre arayın.')
        self.txt_catalog_search.setPlaceholderText('Popüler uygulama ara (SmartTube, Kodi, VLC, Launcher)...')
        self.txt_catalog_search.textChanged.connect(lambda _: self._populate_catalog_table())

        self.btn_catalog_reset = QPushButton('Filtreleri Sıfırla')
        self.btn_catalog_reset.setAccessibleName('Katalog filtrelerini sıfırla')
        self.btn_catalog_reset.setToolTip('Kategori filtresini Tümü yapın ve arama metnini temizleyin.')
        self.btn_catalog_reset.clicked.connect(self._reset_catalog_filters)

        self.btn_catalog_refresh = QPushButton('Kurulum Durumunu Güncelle')
        self.btn_catalog_refresh.clicked.connect(self._refresh_catalog_statuses)

        cat_toolbar.addWidget(QLabel('Kategori:'))
        cat_toolbar.addWidget(self.cmb_catalog_cat)
        cat_toolbar.addWidget(self.txt_catalog_search, 1)
        cat_toolbar.addWidget(self.btn_catalog_reset)
        cat_toolbar.addWidget(self.btn_catalog_refresh)
        cat_layout.addLayout(cat_toolbar)

        self.lbl_catalog_summary = QLabel()
        self.lbl_catalog_summary.setProperty('role', 'quiet')
        cat_layout.addWidget(self.lbl_catalog_summary)

        self.table_catalog = kit.make_table(6, ['Uygulama', 'Kategori', 'Açıklama', 'Geliştirici', 'Durum', 'İşlem'])
        self.table_catalog.setMinimumHeight(240)
        self.table_catalog.setWordWrap(True)
        self.table_catalog.setTextElideMode(Qt.ElideNone)
        self.table_catalog.setAccessibleName('Popüler TV uygulamaları kataloğu')
        self.table_catalog.setAccessibleDescription(
            'Altı sütunlu uygulama kataloğu. Uygulama ayrıntılarını görmek için bir satıra çift tıklayın. '
            'İşlem sütunundaki düğmeler uygulamayı TV’de açar veya kurar.')
        self.table_catalog.setToolTip(
            'Tam açıklama ve kaynak bilgileri için uygulama satırına çift tıklayın.')
        self.table_catalog.doubleClicked.connect(self._show_catalog_details)
        hdr = self.table_catalog.horizontalHeader()
        for column in range(6):
            hdr.setSectionResizeMode(column, QHeaderView.Fixed)
        self.table_catalog.setColumnWidth(0, 190)
        self.table_catalog.setColumnWidth(5, 185)
        self.table_catalog.setColumnWidth(1, 145)
        self.table_catalog.setColumnWidth(3, 145)
        self.table_catalog.setColumnWidth(4, 120)
        for column in range(5):
            self.table_catalog.horizontalHeaderItem(column).setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table_catalog.viewport().installEventFilter(self)
        cat_layout.addWidget(self.table_catalog, 1)

        self.progress_catalog = QProgressBar()
        self.progress_catalog.setRange(0, 100)
        self.progress_catalog.setValue(0)
        self.progress_catalog.setMaximumHeight(8)
        self.progress_catalog.setTextVisible(False)
        self.progress_catalog.hide()
        cat_layout.addWidget(self.progress_catalog)

        self.lbl_catalog_status = QLabel('Hazır. İstediğiniz popüler TV uygulamasını tek tıkla indirip TV’nize yükleyin.')
        self.lbl_catalog_status.setProperty('role', 'quiet')
        cat_layout.addWidget(self.lbl_catalog_status)

        self.subtabs.addTab(tab_catalog, '🌟 Popüler TV Uygulamaları')

        # ----------------------------------------------------
        # SEKME 2: Yerel APK / APKS Kurulumu & Ana Ekran
        # ----------------------------------------------------
        tab_local = QWidget()
        local_layout = QVBoxLayout(tab_local)
        local_layout.setContentsMargins(10, 10, 10, 10)
        local_layout.setSpacing(kit.SPACING)

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

        g, gv = card('APK kurulumu')
        self._info = QLabel('Tek APK kurun veya paketleri kuyruğa ekleyin. '
                            'Başarılı paketler kuyruktan kaldırılır; başarısızlar yeniden deneme için kalır. '
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
        self.btn_retry_failed = QPushButton('Başarısızları Yeniden Dene')
        self.btn_retry_failed.setToolTip(
            'Yalnızca hâlâ mevcut olan başarısız kuyruk paketlerini açık onayınızla yeniden dener.')
        self.btn_retry_failed.setEnabled(False)
        self.btn_retry_failed.clicked.connect(self._retry_failed)
        self.btn_single_install = QPushButton('Tek APK Seç ve Kur')
        self.btn_single_install.clicked.connect(self._install_single)
        queue_actions = kit.action_bar()
        for button in (self.btn_add, self.btn_add_dir, self.btn_rm,
                       self.btn_single_install, self.btn_install,
                       self.btn_retry_failed):
            queue_actions.addWidget(button)
        gv.addLayout(queue_actions)

        options_row = kit.action_bar()
        self.chk_reinstall = kit.CheckBox('Üzerine yaz (-r)')
        self.chk_reinstall.setChecked(True)
        self.chk_reinstall.setToolTip('Mevcut uygulamanın verilerini koruyarak üzerine yükler')
        self.chk_grant_perms = kit.CheckBox('Tüm izinleri ver (-g)')
        self.chk_grant_perms.setChecked(getattr(self.core.config, 'install_grant_perms', True))
        self.chk_grant_perms.setToolTip('Tüm çalışma zamanı izinlerini kurulum anında otomatik onaylar')
        self.chk_downgrade = kit.CheckBox('Sürüm düşürme (-d)')
        self.chk_downgrade.setChecked(False)
        self.chk_downgrade.setToolTip('Daha eski bir sürümün yüklenmesine izin verir')
        options_row.addWidget(self.chk_reinstall)
        options_row.addWidget(self.chk_grant_perms)
        options_row.addWidget(self.chk_downgrade)
        gv.addLayout(options_row)

        self.lst = _DropQueueList(self._add_paths)
        self.lst.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.lst.setFixedHeight(80)
        self.lst.itemSelectionChanged.connect(self._on_queue_selection_changed)
        gv.addWidget(self.lst)
        self.lbl_queue = QLabel('Kuyruk: 0')
        self.lbl_queue.setProperty('role', 'quiet')
        gv.addWidget(self.lbl_queue)
        self.lbl_apk_empty = QLabel('Kuyruk boş. Paket ekleyin veya aşağıdan tek APK seçin.')
        self.lbl_apk_empty.setWordWrap(True)
        self.lbl_apk_empty.setProperty('role', 'quiet')
        gv.addWidget(self.lbl_apk_empty)
        self.lbl_meta = QLabel('')
        self.lbl_meta.setWordWrap(True)
        self.lbl_meta.setTextFormat(Qt.RichText)
        self.lbl_meta.setProperty('role', 'quiet')
        self.lbl_meta.setVisible(False)
        gv.addWidget(self.lbl_meta)
        self.lbl_inst = QLabel('')
        self.lbl_inst.setVisible(False)
        self.lbl_inst.setWordWrap(True)
        self.lbl_inst.setProperty('role', 'quiet')
        gv.addWidget(self.lbl_inst)
        local_layout.addWidget(g)

        # Launcher controls
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
        local_layout.addWidget(g2)
        local_layout.addStretch()

        self.subtabs.addTab(tab_local, '📦 Yerel APK ve ana ekran')

        # ----------------------------------------------------
        # SEKME 3: Gelişmiş Komut Konsolu
        # ----------------------------------------------------
        tab_console = QWidget()
        console_layout = QVBoxLayout(tab_console)
        console_layout.setContentsMargins(10, 10, 10, 10)
        console_layout.setSpacing(kit.SPACING)

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
        self.txt_out.setMaximumHeight(200)
        self.txt_out.setStyleSheet(kit.mono_style())
        v4.addWidget(self.txt_out)
        console_layout.addWidget(g4)
        console_layout.addStretch()

        self.subtabs.addTab(tab_console, '⌨ Gelişmiş Komut Konsolu')

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
            palette = kit.colors(self)
            for row in range(self.table_catalog.rowCount()):
                status = self.table_catalog.item(row, 4)
                if status is not None:
                    status.setForeground(QColor(
                        palette['success'] if status.data(Qt.UserRole) else palette['muted']))
        except (RuntimeError, AttributeError):
            pass

    # --- APK ---
    def _get_meta(self, path):
        if path not in self._meta_cache:
            if os.path.isfile(path) and path.lower().endswith('.apk'):
                try:
                    self._meta_cache[path] = self.core.engine.read_apk_metadata(path)
                except Exception:
                    self._meta_cache[path] = {}
            else:
                self._meta_cache[path] = {}
        return self._meta_cache.get(path, {})

    def _on_queue_selection_changed(self):
        items = self.lst.selectedItems()
        if not items:
            self.lbl_meta.setVisible(False)
            return
        path = items[0].data(Qt.UserRole)
        meta = self._get_meta(path)
        if meta and meta.get('package'):
            label = meta.get('label') or os.path.basename(path)
            ver = meta.get('version_name') or '?'
            code = meta.get('version_code') or '?'
            pkg = meta.get('package')
            min_sdk = meta.get('min_sdk') or '?'
            self.lbl_meta.setText(
                '🏷️ <b>{}</b>  ·  📦 {}  ·  🔢 v{} ({})  ·  ⚙️ Min SDK: {}'.format(
                    *(html.escape(str(value)) for value in
                      (label, pkg, ver, code, min_sdk))))
            self.lbl_meta.setVisible(True)
        else:
            self.lbl_meta.setVisible(False)

    def _refresh_list(self):
        self.lst.clear()
        for f in self._files:
            meta = self._get_meta(f)
            label = meta.get('label')
            ver = meta.get('version_name')
            if label and ver:
                display_name = '{} v{} ({})'.format(label, ver, os.path.basename(f))
            elif label:
                display_name = '{} ({})'.format(label, os.path.basename(f))
            else:
                display_name = os.path.basename(f) or f
            item = QListWidgetItem('{}  —  {}'.format(
                display_name, self._status_text(self._statuses.get(self._path_key(f), 'queued'))),
                self.lst)
            item.setData(Qt.UserRole, f)
            item.setToolTip(f)
        self.lbl_apk_empty.setVisible(not self._files)
        self.lst.setFixedHeight(min(150, max(80, len(self._files) * 30 + 8)))
        self._refresh_queue_summary()
        self._update_retry_failed_enabled()
        self._on_queue_selection_changed()

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

    def _failed_queue_files(self):
        failed = []
        for path in self._files:
            if self._statuses.get(self._path_key(path)) != 'failed':
                continue
            if os.path.isdir(path):
                eligible = any(os.path.isfile(item)
                               for item in glob.glob(os.path.join(path, '*.apk')))
            else:
                eligible = (os.path.isfile(path)
                            and path.lower().endswith(_PACKAGE_EXTENSIONS))
            if eligible:
                failed.append(path)
        return tuple(failed)

    def _update_retry_failed_enabled(self):
        self.btn_retry_failed.setEnabled(
            not self._installing and self._catalog_worker is None
            and bool(self._failed_queue_files()))

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

    def refresh(self):
        """F5 veya sayfa yenileme çağrısında kuyruğu ve mağaza durumunu günceller."""
        if getattr(self.core, 'connected', False):
            self._refresh_catalog_statuses()
        self._refresh_list()

    def showEvent(self, event):
        super().showEvent(event)
        self._catalog_layout_timer.start(0)
        if getattr(self.core, 'connected', False):
            self._refresh_catalog_statuses()

    def _on_connection_changed(self, connected=False, target=None, *_):
        self._connection_generation += 1
        if self._catalog_worker is not None:
            self._catalog_worker.cancel()
        self._catalog_refresh_generation += 1
        current_target = target or getattr(self.core, 'target', None)
        if (not connected or current_target != self._catalog_status_target):
            self._catalog_status_known = False
            self._catalog_status_target = None
            self._catalog_status_error_target = None
            self._installed_pkgs = set()
        self._launchers_target = None
        self._launchers_generation = None
        if hasattr(self, 'cmb_launch'):
            self.cmb_launch.clear()
        if hasattr(self, 'lbl_home'):
            self.lbl_home.setText('Mevcut HOME: —')
        if self._catalog_installing:
            self.progress_catalog.hide()
            self.lbl_catalog_status.setText(
                'Hedef değişti; önceki cihazın kurulum sonucu gösterilmeyecek.')
        if connected or getattr(self.core, 'connected', False):
            self._refresh_catalog_statuses()
        else:
            self._populate_catalog_table()

    def _target_is_current(self, target, generation):
        return (generation == self._connection_generation
                and getattr(self.core, 'connected', False)
                and getattr(self.core, 'target', None) == target
                and not getattr(self.window, '_connection_busy', False))

    def _catalog_status_known_for(self, target):
        return (self._catalog_status_known
                and self._catalog_status_target == target
                and self._target_is_current(target, self._connection_generation))

    def _catalog_item_verified_installed(self, item):
        target = getattr(self.core, 'target', None)
        return (self._catalog_status_target == target
                and self._target_is_current(target, self._connection_generation)
                and self._is_catalog_item_installed(item))

    def _reset_catalog_filters(self):
        category_index = self.cmb_catalog_cat.findText('Tümü')
        category_signals_were_blocked = self.cmb_catalog_cat.blockSignals(True)
        search_signals_were_blocked = self.txt_catalog_search.blockSignals(True)
        try:
            if category_index >= 0:
                self.cmb_catalog_cat.setCurrentIndex(category_index)
            self.txt_catalog_search.clear()
        finally:
            self.cmb_catalog_cat.blockSignals(category_signals_were_blocked)
            self.txt_catalog_search.blockSignals(search_signals_were_blocked)
        self._populate_catalog_table()

    def _show_catalog_details(self, index):
        name_item = self.table_catalog.item(index.row(), 0)
        item = name_item.data(Qt.UserRole) if name_item else None
        if not isinstance(item, dict):
            return

        name = str(item.get('name') or 'Uygulama')
        dialog = QDialog(self)
        dialog.setWindowTitle('Uygulama Ayrıntıları — {}'.format(name))
        dialog.setAccessibleName('Uygulama ayrıntıları: {}'.format(name))
        layout = QVBoxLayout(dialog)
        details = QPlainTextEdit(dialog)
        details.setReadOnly(True)
        details.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        details.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        details.setAccessibleName('{} uygulama ayrıntıları'.format(name))
        details.setPlainText(
            'Açıklama:\n{description}\n\nKategori: {category}\nRozet: {badge}\n'
            'Geliştirici: {author}\nResmî web sitesi: {website}'.format(
                description=str(item.get('description') or 'Belirtilmemiş'),
                category=str(item.get('category') or 'Belirtilmemiş'),
                badge=str(item.get('badge') or 'Belirtilmemiş'),
                author=str(item.get('author') or 'Belirtilmemiş'),
                website=str(item.get('website') or 'Belirtilmemiş')))
        layout.addWidget(details)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=dialog)
        buttons.button(QDialogButtonBox.Close).setText('Kapat')
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        available = self.screen().availableGeometry()
        max_width = max(1, available.width() - 32)
        max_height = max(1, available.height() - 48)
        dialog.setMaximumSize(max_width, max_height)
        dialog.resize(min(620, max_width), min(460, max_height))
        dialog.exec()

    def _populate_catalog_table(self):
        cat = self.cmb_catalog_cat.currentText() if hasattr(self, 'cmb_catalog_cat') else 'Tümü'
        search = self.txt_catalog_search.text() if hasattr(self, 'txt_catalog_search') else ''
        items = get_catalog(category=cat, search=search)
        target = getattr(self.core, 'target', None)
        status_known = self._catalog_status_known_for(target)
        connected = bool(getattr(self.core, 'connected', False) and target)

        self.table_catalog.setRowCount(0)
        self.table_catalog.setRowCount(len(items))
        action_width = 220
        installed_count = 0

        for row, item in enumerate(items):
            # Col 0: Uygulama (Icon + Name)
            it_name = QTableWidgetItem('{}  {}'.format(item['icon'], item['name']))
            it_name.setData(Qt.UserRole, item)
            tooltip = [item.get('description', ''),
                       'Geliştirici: {}'.format(item.get('author', ''))]
            if item.get('website'):
                tooltip.append('Web: {}'.format(item['website']))
            it_name.setToolTip('\n'.join(value for value in tooltip if value))
            self.table_catalog.setItem(row, 0, it_name)

            # Col 1: Kategori
            it_cat = QTableWidgetItem('{} · {}'.format(item['category'], item['badge']))
            it_cat.setToolTip('{} · {}'.format(item['category'], item['badge']))
            self.table_catalog.setItem(row, 1, it_cat)

            # Col 2: Açıklama
            it_desc = QTableWidgetItem(item['description'])
            it_desc.setToolTip(item['description'])
            self.table_catalog.setItem(row, 2, it_desc)

            # Col 3: Geliştirici
            it_author = QTableWidgetItem(item['author'])
            it_author.setToolTip('Geliştirici: {}'.format(item['author']))
            self.table_catalog.setItem(row, 3, it_author)

            # Col 4: Durum
            is_installed = self._catalog_item_verified_installed(item)
            if not connected:
                status_text = 'Bağlantı yok'
            elif not status_known and not is_installed:
                status_text = ('Kontrol başarısız'
                               if self._catalog_status_error_target == target
                               else 'Kontrol bekleniyor')
            else:
                status_text = '✓ TV\'de Kurulu' if is_installed else 'Kurulu Değil'
            it_status = QTableWidgetItem(status_text)
            it_status.setData(Qt.UserRole, is_installed if status_known or is_installed else None)
            if status_text == 'Kontrol başarısız':
                it_status.setToolTip(
                    'TV uygulama durumu sorgulanamadı; yeniden denemek için '
                    'Kurulum Durumunu Güncelle düğmesini kullanın.')
            else:
                it_status.setToolTip(status_text)
            palette = kit.colors(self)
            it_status.setForeground(QColor(
                palette['success'] if is_installed else palette['muted']))
            self.table_catalog.setItem(row, 4, it_status)
            installed_count += int(is_installed)

            # Col 5: İşlem Butonları
            cell_widget = QWidget()
            cell_widget.setObjectName('catalogActions')
            cell_widget.setStyleSheet('''
                QWidget#catalogActions { background: transparent; }
                QPushButton#catalogAction { border-radius: 6px; padding: 4px 12px; }
            ''')
            cell_layout = QHBoxLayout(cell_widget)
            cell_layout.setContentsMargins(8, 6, 8, 6)
            cell_layout.setSpacing(8)

            if is_installed:
                btn_open = QPushButton('TV\'de Aç')
                btn_open.setProperty('role', 'secondary')
                btn_open.clicked.connect(lambda _, it=item: self._launch_catalog_app(it))
                cell_layout.addWidget(btn_open)

                btn_reinstall = QPushButton('Yeniden Kur')
                btn_reinstall.setProperty('role', 'secondary')
                btn_reinstall.clicked.connect(
                    lambda _, it=item: self._install_catalog_app(it, require_installed=True))
                cell_layout.addWidget(btn_reinstall)
            else:
                btn_inst = QPushButton('İndir ve TV\'ye Kur')
                btn_inst.setProperty('accent', True)
                btn_inst.clicked.connect(lambda _, it=item: self._install_catalog_app(it))
                cell_layout.addWidget(btn_inst)

            for index in range(cell_layout.count()):
                button = cell_layout.itemAt(index).widget()
                button.setEnabled(not self._installing and self._catalog_worker is None
                                  and not getattr(self.window, '_connection_busy', False))
                button.setObjectName('catalogAction')
                button.setProperty('compact', True)
                button.ensurePolished()
                button.setFixedHeight(max(36, button.fontMetrics().height() + 14))
                button.setMinimumWidth(max(
                    button.sizeHint().width(),
                    button.fontMetrics().horizontalAdvance(button.text()) + 24,
                ))
            cell_widget.ensurePolished()
            self.table_catalog.setCellWidget(row, 5, cell_widget)
            self.table_catalog.setRowHeight(row, max(52, cell_widget.sizeHint().height() + 4))
            margins = cell_layout.contentsMargins()
            required_width = sum(
                cell_layout.itemAt(index).widget().minimumWidth()
                for index in range(cell_layout.count())
            ) + margins.left() + margins.right() + cell_layout.spacing() * (cell_layout.count() - 1)
            action_width = max(action_width, required_width + 8, cell_widget.sizeHint().width() + 8)
        if not items:
            summary = 'Aramayla eşleşen uygulama yok.'
            kit.empty_state(self.table_catalog, 'Eşleşen uygulama yok',
                            'Arama metnini temizleyin veya başka bir kategori seçin.')
        elif not connected:
            summary = 'Filtrede {} uygulama · Kurulum durumunu görmek için TV’ye bağlanın.'.format(
                len(items))
        elif status_known:
            summary = 'Filtrede {} uygulama · TV’de kurulu: {}'.format(
                len(items), installed_count)
        else:
            summary = 'Filtrede {} uygulama · Kurulum durumu kontrol bekliyor.'.format(
                len(items))
        if self._catalog_status_error_target == target:
            summary += (' Yeni kurulum durumu sorgulanamadı; varsa önceki doğrulanmış '
                        'sonuçlar gösteriliyor. Bağlantıyı kontrol edip '
                        '“Kurulum Durumunu Güncelle” ile yeniden deneyin.')
        self.lbl_catalog_summary.setText(summary)
        self.table_catalog.setColumnWidth(5, action_width)
        self._update_catalog_columns()

    def _update_catalog_columns(self):
        """Keep catalog details readable, including in smaller windows."""
        if not hasattr(self, 'table_catalog'):
            return
        table = self.table_catalog
        for column in range(6):
            table.setColumnHidden(column, False)
        other_width = sum(table.columnWidth(column) for column in (0, 1, 3, 4, 5))
        # Narrow windows scroll horizontally instead of losing application details.
        table.setColumnWidth(2, max(300, table.viewport().width() - other_width))
        table.resizeRowsToContents()
        for row in range(table.rowCount()):
            actions = table.cellWidget(row, 5)
            minimum = max(64, actions.sizeHint().height() + 8) if actions else 64
            table.setRowHeight(row, max(minimum, table.rowHeight(row) + 8))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._catalog_layout_timer.start(0)

    def eventFilter(self, watched, event):
        if (hasattr(self, 'table_catalog')
                and watched is self.table_catalog.viewport()
                and event.type() in (QEvent.Resize, QEvent.Show)):
            # The scroll area lays out its viewport after the parent resize.
            self._catalog_layout_timer.start(0)
        return super().eventFilter(watched, event)

    def _is_catalog_item_installed(self, item):
        candidates = [item['package']] + item.get('alt_packages', [])
        return any(c in self._installed_pkgs for c in candidates)

    def _get_installed_pkg(self, item):
        candidates = [item['package']] + item.get('alt_packages', [])
        for c in candidates:
            if c in self._installed_pkgs:
                return c
        return item['package']

    def _install_catalog_app(self, item, require_installed=False):
        if (self._catalog_worker is not None or self._installing
                or getattr(self.window, '_connection_busy', False)
                or getattr(self.window, '_closing', False)
                or getattr(self.window, '_close_pending', False)):
            self.lbl_catalog_status.setText('Devam eden işlem bitmeden yeni kurulum başlatılamaz.')
            return
        item = dict(item)
        if not self.core.connected or not self.core.target:
            QMessageBox.information(self, 'Bağlantı Yok', 'Uygulama kurmak için önce bir TV cihazına bağlanın.')
            return

        target = self.core.target
        if require_installed and not self._catalog_item_verified_installed(item):
            self.lbl_catalog_status.setText(
                'Kurulum durumu doğrulanmadı; yeniden kurma başlatılmadı.')
            self._populate_catalog_table()
            return

        install_key = item.get('id') or item['package']
        if install_key in self._catalog_installing:
            self.lbl_catalog_status.setText('{} için kurulum zaten sürüyor.'.format(item['name']))
            return

        generation = self._connection_generation
        engine = self.core.engine
        app_name = item['name']
        pkg = item['package']
        grant_perms = getattr(self.core.config, 'install_grant_perms', False)
        permission_note = ('Tüm çalışma zamanı izinleri otomatik verilecek.'
                           if grant_perms else 'İzinler otomatik verilmeyecek.')
        source = item.get('website') or item.get('url') or 'belirtilmemiş'
        answer = QMessageBox.warning(
            self, 'Üçüncü Taraf APK Kurulumu',
            '{} MiBox tarafından yayımlanmıyor. APK yayıncı imzası MiBox tarafından '
            'doğrulanmıyor; SHA-256 özeti kontrol edilmiyor. Kurulumdan önce kaynağı kontrol edin.\n\n'
            'Kaynak: {}\nPaket: {}\n{}'.format(app_name, source, pkg, permission_note),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        if (self._catalog_worker is not None or self._installing
                or getattr(self.window, '_closing', False)
                or getattr(self.window, '_close_pending', False)
                or not self._target_is_current(target, generation)):
            self.lbl_catalog_status.setText('Hedef veya işlem durumu değişti; kurulum başlatılmadı.')
            return
        self._catalog_installing.add(install_key)
        self._catalog_refresh_generation += 1

        self.lbl_catalog_status.setText('{} indiriliyor ve kuruluyor...'.format(app_name))
        self.progress_catalog.setRange(0, 0)
        self.progress_catalog.show()

        def do():
            w.check_cancel()

            def prog(downloaded, total):
                w.progress.emit(int(downloaded), int(total))

            apk_path = download_apk(item, progress_cb=prog, check_cancel=w.check_cancel)
            w.check_cancel()
            if not self._target_is_current(target, generation):
                raise RuntimeError('Hedef veya bağlantı değişti; APK kurulmadı.')
            meta = engine.read_apk_metadata(apk_path)
            actual_pkg = meta.get('package')
            if not actual_pkg or actual_pkg != item['package']:
                raise RuntimeError('İndirilen APK beklenen paket kimliğine sahip değil.')

            w.progress.emit(100, 100)
            if not self._target_is_current(target, generation):
                raise RuntimeError('Hedef veya bağlantı değişti; APK kurulmadı.')
            w.check_cancel()
            res = engine.install_apk(target, apk_path, reinstall=True,
                                     grant_perms=grant_perms,
                                     cancel_check=w.check_cancel)
            try:
                engine.invalidate_pkg_cache(target)
            except Exception:
                pass
            installed = engine.is_installed(target, actual_pkg)
            if not installed:
                raise RuntimeError('{} paketinin TV\'ye kurulduğu doğrulanamadı.'.format(actual_pkg))
            return {'installed': installed, 'output': getattr(res, 'output', ''),
                    'package': actual_pkg, 'cancel_requested': w.isInterruptionRequested()}

        w = Worker(do)
        w.job_name = '{} Kurulumu'.format(app_name)

        def on_prog(cur, total):
            if not self._target_is_current(target, generation):
                return
            if total > 0:
                self.progress_catalog.setRange(0, 100)
                pct = min(100, max(0, int(cur * 100 / total)))
                self.progress_catalog.setValue(pct)
                if cur == 100 and total == 100:
                    self.lbl_catalog_status.setText('{} TV\'ye yükleniyor (ADB)...'.format(app_name))
                else:
                    dl_mb = cur / (1024 * 1024)
                    tot_mb = total / (1024 * 1024)
                    self.lbl_catalog_status.setText('{} indiriliyor: {:.1f} / {:.1f} MB (%{})'.format(app_name, dl_mb, tot_mb, pct))
            else:
                self.progress_catalog.setRange(0, 0)
                self.lbl_catalog_status.setText('{} indiriliyor...'.format(app_name))

        def on_done(res):
            self._catalog_installing.discard(install_key)
            if not self._target_is_current(target, generation):
                return
            if not isinstance(res, dict) or not res.get('installed') or not res.get('package'):
                on_fail('TV üzerinde kurulum doğrulanamadı.')
                return
            actual_pkg = res['package']
            self.progress_catalog.hide()
            self.lbl_catalog_status.setText('✓ {} TV\'ye başarıyla kuruldu!'.format(app_name))
            self._catalog_status_target = target
            self._installed_pkgs.add(actual_pkg)
            self._populate_catalog_table()

            if res.get('cancel_requested'):
                self.lbl_catalog_status.setText(
                    '{} kuruldu ve doğrulandı; durdurma isteği başlamış kurulumu geri almadı.'.format(app_name))
                return

            box = QMessageBox(self)
            box.setWindowTitle('Kurulum Başarılı')
            box.setText('<b>{}</b> başarıyla TV\'ye yüklendi!\n\nŞimdi TV ekranında başlatmak ister misiniz?'.format(app_name))
            btn_launch = box.addButton('TV\'de Başlat', QMessageBox.AcceptRole)
            btn_launch.setProperty('accent', True)
            box.addButton('Kapat', QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() == btn_launch:
                if self._target_is_current(target, generation):
                    self._launch_catalog_app(item)
                else:
                    self.lbl_catalog_status.setText(
                        'Hedef veya bağlantı değişti; uygulama başlatılmadı.')

        def on_fail(err):
            self._catalog_installing.discard(install_key)
            if not self._target_is_current(target, generation):
                return
            self.progress_catalog.hide()
            if 'kullanıcı durdurdu' in str(err).casefold():
                self.lbl_catalog_status.setText('Kurulum durduruldu; indirilmiş APK yerelde kalabilir.')
                return
            self.lbl_catalog_status.setText('Kurulum başarısız: ' + str(err))
            QMessageBox.critical(self, 'Kurulum Hatası', '{}\n{}'.format(app_name, err))

        results, errors = [], []
        w.progress.connect(on_prog)
        w.finished_ok.connect(results.append)
        w.failed.connect(errors.append)
        self._catalog_worker = w
        self._set_queue_controls_enabled(False)
        self.btn_catalog_refresh.setEnabled(False)
        self._populate_catalog_table()

        def finished():
            if self._catalog_worker is not w:
                return
            self._catalog_worker = None
            self.progress_catalog.hide()
            self.btn_catalog_refresh.setEnabled(True)
            self._catalog_installing.discard(install_key)
            self._set_queue_controls_enabled(not self._installing)
            self._populate_catalog_table()
            if (self._catalog_refresh_pending
                    and not getattr(self.window, '_closing', False)
                    and not getattr(self.window, '_close_pending', False)):
                self._refresh_catalog_statuses()
            if (getattr(self.window, '_closing', False)
                    or getattr(self.window, '_close_pending', False)
                    or not self._target_is_current(target, generation)):
                return
            if results:
                on_done(results[0])
            else:
                on_fail(errors[-1] if errors else 'Kurulum tamamlanamadı.')

        w.finished.connect(finished)
        try:
            self.window._run(w, desc='Kurulum: {} indiriliyor ve kuruluyor'.format(app_name))
        except Exception as error:
            errors.append(str(error))
            finished()

    def _launch_catalog_app(self, item):
        if (self._catalog_worker is not None or self._installing
                or getattr(self.window, '_connection_busy', False)):
            return
        if not self.core.connected or not self.core.target:
            QMessageBox.information(self, 'Bağlantı Yok', 'Uygulamayı başlatmak için önce cihaza bağlanın.')
            return
        target = self.core.target
        if not self._catalog_item_verified_installed(item):
            QMessageBox.information(
                self, 'Kurulum Durumu Bilinmiyor',
                'Uygulama durumu bu TV için doğrulanmadı. Kurulum durumunu güncelleyin.')
            return
        generation = self._connection_generation
        engine = self.core.engine
        pkg = self._get_installed_pkg(item)
        app_name = item['name']

        def do():
            w.check_cancel()
            if not self._target_is_current(target, generation):
                from ..workers import CancelledError
                raise CancelledError('bağlantı değişti')
            return engine.launch_app(target, pkg)

        def on_done(_):
            if self._target_is_current(target, generation):
                self.lbl_catalog_status.setText('{} için başlatma komutu gönderildi.'.format(app_name))

        def on_fail(err):
            if self._target_is_current(target, generation):
                QMessageBox.warning(self, 'Başlatma Uyarısı', 'Uygulama açılamadı:\n' + str(err))

        w = Worker(do)
        w.job_name = '{} Başlatma'.format(app_name)
        w.finished_ok.connect(on_done)
        w.failed.connect(on_fail)
        self.window._run(w, desc='Katalog: {} TV ekranında başlatılıyor'.format(app_name))

    def _refresh_catalog_statuses(self):
        if self._catalog_worker is not None or self._installing:
            self._catalog_refresh_pending = True
            return
        self._catalog_refresh_pending = False
        self._catalog_refresh_generation += 1
        request_generation = self._catalog_refresh_generation
        if not self.core.connected or not self.core.target:
            self._catalog_status_known = False
            self._catalog_status_target = None
            self._catalog_status_error_target = None
            self._installed_pkgs = set()
            self._populate_catalog_table()
            return
        target = self.core.target
        if self._catalog_status_target != target:
            self._catalog_status_known = False
            self._catalog_status_target = None
            self._catalog_status_error_target = None
            self._installed_pkgs = set()
            self._populate_catalog_table()
        connection_generation = self._connection_generation
        engine = self.core.engine

        def do():
            return set(engine.list_packages(target, include_system=True))

        w = Worker(do)
        w.job_name = 'TV Uygulama Durumu'
        def on_done(pkgs):
            if (request_generation == self._catalog_refresh_generation
                    and self._target_is_current(target, connection_generation)):
                self._installed_pkgs = pkgs
                self._catalog_status_target = target
                self._catalog_status_known = True
                self._catalog_status_error_target = None
                self._populate_catalog_table()

        def on_fail(_error):
            if (request_generation == self._catalog_refresh_generation
                    and self._target_is_current(target, connection_generation)):
                self._catalog_status_error_target = target
                self._populate_catalog_table()

        w.finished_ok.connect(on_done)
        w.failed.connect(on_fail)
        self.window._run(w, desc='Katalog: kurulu TV uygulamaları taranıyor')

    def _install_all(self):
        if self._installing or self._catalog_worker is not None:
            return
        if getattr(self.window, '_connection_busy', False):
            self._set_install_status('Bağlantı işlemi sürüyor; tamamlanınca kurulumu başlatın.')
            return
        if not self._files:
            QMessageBox.information(self, 'Kurulum', 'Önce APK ekleyin.')
            return
        self._start_install(tuple(self._files), 'batch')

    def _retry_failed(self):
        if self._installing or self._catalog_worker is not None:
            return
        files = self._failed_queue_files()
        if not files:
            self._refresh_list()
            self._set_install_status(
                'Yeniden denenecek başarısız paket yok; dosyaları ve kuyruk durumunu kontrol edin.')
            return
        self._start_install(files, 'batch')

    def _install_single(self):
        if self._installing or self._catalog_worker is not None:
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
        if self._installing or self._catalog_worker is not None:
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
        if (self._installing or self._catalog_worker is not None or
                getattr(self.window, '_closing', False) or
                getattr(self.window, '_close_pending', False) or
                getattr(self.window, '_connection_busy', False) or
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
        reinstall = self.chk_reinstall.isChecked()
        grant_perms = self.chk_grant_perms.isChecked()
        allow_downgrade = self.chk_downgrade.isChecked()
        self._install_snapshot = files
        self._install_result = None
        self._install_operation = operation
        self._installing = True
        self._catalog_refresh_generation += 1
        self._catalog_status_known = False
        self._catalog_status_target = None
        self._catalog_refresh_pending = True
        self._populate_catalog_table()
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

            def target_is_current():
                return self._target_is_current(t, connection_generation)

            try:
                worker.check_cancel()
            except Exception as exc:
                from ..workers import CancelledError
                if isinstance(exc, CancelledError):
                    operation['cancelled'] = True
                    operation['cancel_reason'] = 'Kullanıcı durdurdu.'
                    return operation
                raise
            if not target_is_current():
                operation['cancelled'] = True
                operation['cancel_reason'] = 'Hedef veya bağlantı değişti; paketler korunuyor.'
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
                if not target_is_current():
                    operation['cancelled'] = True
                    operation['cancel_reason'] = 'Hedef veya bağlantı değişti; kalan paketler korunuyor.'
                    break
                try:
                    if os.path.isdir(f) or f.lower().endswith(('.apks', '.apkm', '.xapk')):
                        eng.install_multiple(t, f, reinstall=reinstall,
                                             grant_perms=grant_perms, allow_downgrade=allow_downgrade,
                                             cancel_check=worker.check_cancel)
                    else:
                        eng.install_apk(t, f, reinstall=reinstall,
                                        grant_perms=grant_perms, allow_downgrade=allow_downgrade,
                                        cancel_check=worker.check_cancel)
                    operation['successes'].append(f)
                    operation['msgs'].append('+ ' + os.path.basename(f))
                    if worker.isInterruptionRequested():
                        operation['cancelled'] = True
                        operation['cancel_reason'] = (
                            'Durdurma isteği geldi; başlamış son kurulum tamamlandı.'
                            if i == total else
                            'Durdurma isteği geldi; başlamış kurulum tamamlandı, '
                            'kalan paketler kuyrukta bırakıldı.')
                        break
                except CancelledError:
                    operation['cancelled'] = True
                    operation['cancel_reason'] = 'Kullanıcı durdurdu; kalanlar kuyrukta.'
                    break
                except Exception as e:
                    operation['failures'].append(f)
                    operation['msgs'].append('X {}: {}'.format(os.path.basename(f), e))
                    if worker.isInterruptionRequested():
                        operation['cancelled'] = True
                        operation['cancel_reason'] = (
                            'Durdurma isteği geldi; başlayan son kurulum başarısız oldu, '
                            'başarısız paket kuyrukta tutuldu.'
                            if i == total else
                            'Durdurma isteği geldi; başlayan kurulum başarısız oldu, '
                            'başarısız ve kalan paketler kuyrukta tutuldu.')
                        break
            try:
                eng.invalidate_pkg_cache(t)
            except Exception:
                pass
            return operation
        worker = Worker(do)
        worker.job_name = 'Tek APK kurma' if mode == 'single' else 'APK kuyruk kurulumu'
        worker.finished_ok.connect(self._install_done)
        worker.progress.connect(self._install_progress)
        worker.failed.connect(
            lambda error: self._install_failed(operation, error, worker))
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
            self._populate_catalog_table()
            self._refresh_catalog_statuses()
            raise

    def _set_queue_controls_enabled(self, enabled):
        enabled = bool(enabled and self._catalog_worker is None)
        for button in (self.btn_add, self.btn_add_dir, self.btn_rm,
                       self.btn_single_install, self.btn_install,
                       self.chk_reinstall, self.chk_grant_perms,
                       self.chk_downgrade):
            button.setEnabled(bool(enabled))
        self.lst.setEnabled(bool(enabled))
        self._update_retry_failed_enabled()

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

    def _install_failed(self, operation, error, worker=None):
        message = str(error)
        if (worker is not None and worker.isInterruptionRequested()
                and 'kullanıcı durdurdu' in message.casefold()):
            operation['cancelled'] = True
            operation['cancel_reason'] = (
                'İşlem başlamadan durduruldu; paketler kuyrukta korundu.')
            return
        operation['worker_error'] = message

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
        self._populate_catalog_table()
        closing = (getattr(self.window, '_closing', False)
                   or getattr(self.window, '_close_pending', False))
        if closing:
            return
        self._refresh_catalog_statuses()
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
                len(result.get('successes', [])), len(result.get('failures', []))),
                     'Başarılılar kuyruktan kaldırıldı; başarısızlar kuyrukta tutuldu.']
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
        target = getattr(self.core, 'target', None)
        generation = self._connection_generation
        if not self._target_is_current(target, generation):
            QMessageBox.information(self, 'Launcher', 'Önce bir TV cihazına bağlanın.')
            return
        engine = self.core.engine

        def do():
            engine.connect(target)
            return engine.launcher_apps(target)

        w = Worker(do)
        w.job_name = 'Launcher tarama'
        w.finished_ok.connect(
            lambda items: self._show_launchers(items, target, generation))
        self.window._run(w, desc='Kurulum: launcherlar taraniyor')

    def _show_launchers(self, items, target=None, generation=None):
        if (target is not None and generation is not None
                and not self._target_is_current(target, generation)):
            return
        self.cmb_launch.clear()
        self._launchers_target = target
        self._launchers_generation = generation
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
        target = getattr(self.core, 'target', None)
        generation = self._connection_generation
        if not self._target_is_current(target, generation):
            QMessageBox.information(self, 'HOME', 'Önce bir TV cihazına bağlanın.')
            return
        engine = self.core.engine

        def do():
            engine.connect(target)
            return engine.home_activity(target)

        def on_done(current):
            if self._target_is_current(target, generation):
                self.lbl_home.setText('Mevcut HOME: ' + current)

        w = Worker(do)
        w.job_name = 'HOME okuma'
        w.finished_ok.connect(on_done)
        self.window._run(w, desc='Kurulum: mevcut HOME okunuyor')

    def _set_home(self):
        comp = self.cmb_launch.currentData()
        if not comp:
            QMessageBox.information(self, 'HOME', 'Önce Launcherları Tara ile seçin.')
            return
        target = getattr(self.core, 'target', None)
        generation = self._connection_generation
        if (not self._target_is_current(target, generation)
                or getattr(self, '_launchers_target', None) != target
                or getattr(self, '_launchers_generation', None) != generation):
            QMessageBox.information(self, 'HOME',
                                    'Hedef değişti; launcherları bu cihazda yeniden tarayın.')
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
        if (not self._target_is_current(target, generation)
                or getattr(self, '_launchers_target', None) != target
                or getattr(self, '_launchers_generation', None) != generation
                or self.cmb_launch.currentData() != comp):
            QMessageBox.information(self, 'HOME',
                                    'Hedef veya launcher seçimi değişti; HOME ayarlanmadı.')
            return
        engine = self.core.engine

        def do():
            engine.connect(target)
            engine.set_home_activity(target, comp)
            return {'home': engine.home_activity(target),
                    'notes': list(getattr(engine, 'last_home_notes', []) or [])}

        def on_done(result):
            self._home_done(result, target, generation)

        w = Worker(do)
        w.job_name = 'HOME ayarlama'
        w.finished_ok.connect(on_done)
        self.window._run(w, desc='Kurulum: HOME ayarlaniyor: ' + comp)

    def _home_done(self, res, target, generation):
        if not self._target_is_current(target, generation):
            return
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
        target = getattr(self.core, 'target', None)
        generation = self._connection_generation
        if not self._target_is_current(target, generation):
            self.txt_out.appendPlainText('Komut için önce bir cihaza bağlanın.')
            return
        cmd = self.txt_cmd.text().strip()
        if not cmd:
            return
        cls = gate.classify(cmd)
        if cls == 'REFUSED':
            QMessageBox.critical(self, 'Kapı', gate.REFUSED_MSG)
            self.txt_out.appendPlainText('$ ' + cmd + '\nREDDEDİLDİ (yıkıcı komut).')
            return
        if cls in ('SETTING', 'CHANGE'):
            if QMessageBox.question(self, 'Onay',
                                    '[{}] {}\n\nCihazda değişiklik yapar. Çalıştırılsın mı?'.format(cls, cmd),
                                    QMessageBox.Yes | QMessageBox.No,
                                    QMessageBox.No) != QMessageBox.Yes:
                return
        if not self._target_is_current(target, generation):
            self.txt_out.appendPlainText('Hedef veya bağlantı değişti; komut çalıştırılmadı.')
            return
        parts = cmd.split()
        engine = self.core.engine
        worker_ref = {}

        def do():
            worker = worker_ref['worker']
            worker.check_cancel()
            if not self._target_is_current(target, generation):
                raise RuntimeError('Hedef veya bağlantı değişti; komut çalıştırılmadı.')
            try:
                engine.connect(target, cancel_check=worker.isInterruptionRequested)
            except Exception:
                worker.check_cancel()
                raise
            worker.check_cancel()
            if not self._target_is_current(target, generation):
                raise RuntimeError('Hedef veya bağlantı değişti; komut çalıştırılmadı.')
            try:
                r = engine.shell(
                    target, *parts, timeout=30, hide_from_trace=True,
                    cancel_check=worker.isInterruptionRequested)
            except Exception:
                worker.check_cancel()
                raise
            return '[{}] exit={}\n{}{}'.format(
                cls, r.exit_code,
                (r.output + '\n' if r.output else ''),
                (r.error if r.error else ''))
        w = Worker(do)
        worker_ref['worker'] = w
        w.job_name = 'Konsol komutu'
        w.finished_ok.connect(lambda out: self.txt_out.appendPlainText('$ ' + cmd + '\n' + out)
                              if self._target_is_current(target, generation) else None)
        self.window._run(w, desc='Kurulum konsolu komutu')
