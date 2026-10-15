# -*- coding: utf-8 -*-
"""Uygulamalar sekmesi: uygulama listesi, filtreler ve paket islemleri."""
import csv
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidgetItem, QLineEdit, QComboBox, QPushButton,
    QLabel, QHeaderView, QMenu, QMessageBox, QToolButton,
    QFileDialog, QDialog, QDialogButtonBox, QTextEdit, QApplication,
)

from ..config import APK_DIR
from ..workers import AppScanWorker, PackageActionWorker, ApkBackupWorker, Worker
from . import kit
from .flowlayout import FlowLayout

COL_CHECK = 0
COL_NAME = 1
COL_PKG = 2
COL_STATE = 3
# Kept as an alias for callers that used the old enabled-state column name.
COL_ENABLED = COL_STATE

# Filter values are independent from their visible labels.
STATUS_ALL = 'all'
STATUS_ACTIVE = 'active'
STATUS_DISABLED = 'disabled'
STATUS_REMOVED = 'removed'
STATUS_RUNNING = 'running'
STATUS_SYSTEM = 'system'
STATUS_ITEMS = [
    ('Tümü', STATUS_ALL),
    ('Etkin', STATUS_ACTIVE),
    ('Devre dışı', STATUS_DISABLED),
    ('Kaldırılmış', STATUS_REMOVED),
    ('Çalışan süreç', STATUS_RUNNING),
]
DATA_RUNNING = 'Evet'


class AppsTab(QWidget):
    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._apps = []
        self._presence = set()
        self._last_scan_at = None
        self._in_item_changed = False  # ozyineleme kilidi (stack overflow korumasi)
        self._busy = False
        self._scan_generation = 0
        # Son tarama sistem paketlerini kapsadi mi? ('Sistem' filtresi icin)
        self._scanned_with_system = bool(getattr(core.config, 'include_system', False))
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(250)
        self._filter_timer.timeout.connect(self._apply_filter_now)
        self._build()
        self.core.connection_changed.connect(self._connection_changed)

    def _connection_changed(self, connected, _target):
        if not connected:
            self._scan_generation += 1
            self._apps = []
            self._presence.clear()
            self._last_scan_at = None
            self._apply_filter_now()
            try:
                self._remote_tab().populate_apps([])
                self.window.tab_debloat.set_present(set())
            except (AttributeError, RuntimeError):
                pass
            self.lbl_summary.setText('Bağlı cihaz yok. Cihaza bağlanıp listeyi yenileyin.')

    def _build(self):
        root = kit.page(self)

        # Arama, filtreler ve yenileme tek bir araç çubuğunda kalır.
        toolbar = QHBoxLayout()
        toolbar.setSpacing(kit.SPACING)
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText('Ara: ad veya paket...')
        self.txt_search.setMinimumWidth(200)
        self.txt_search.textChanged.connect(lambda: self._filter_timer.start())
        # Uygulama durumu ve süreç filtresi.
        self.cmb_status = QComboBox()
        for etiket, veri in STATUS_ITEMS:
            self.cmb_status.addItem(etiket, veri)
        # Kutu, listedeki en uzun secenegi (Kaldırılmış/Devre dışı) gosterecek
        # kadar genis olsun; secenekler kirpilmasin.
        self.cmb_status.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.cmb_status.setMinimumWidth(110)
        self.cmb_status.setAccessibleName('Durum filtresi')
        self.cmb_status.setToolTip(
            'Etkin/devre dışı/kaldırılmış uygulamalara göre filtrele. '
            'Çalışan süreç, ADB tarafından çalışan olarak raporlanan işlemdir; '
            'uygulamanın ön planda olduğu anlamına gelmez. '
            'Sistem düğmesi ROM uygulamalarının görünürlüğünü değiştirir.')
        self.cmb_status.currentIndexChanged.connect(self._on_status_combo)
        self._restore_status_from_config()
        self.btn_system = QPushButton('Sistem')
        self.btn_system.setObjectName('btnSystemFilter')
        self.btn_system.setCheckable(True)
        self.btn_system.setChecked(True)
        self.btn_system.toggled.connect(self._on_system_toggle)
        self.btn_refresh = QPushButton('Yenile')
        self.btn_refresh.setProperty('accent', True)
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_export = QPushButton('CSV')
        self.btn_export.setToolTip('Listeyi CSV olarak aktar')
        self.btn_export.clicked.connect(self._export_csv)
        toolbar.addWidget(self.txt_search, 1)
        toolbar.addWidget(self.cmb_status)
        toolbar.addWidget(self.btn_system)
        toolbar.addWidget(self.btn_refresh)
        toolbar.addWidget(self.btn_export)
        root.addLayout(toolbar)

        # --- Tablo (esnek, pencereyle buyur/kucuk) ---
        self.grid = kit.make_table(4, ['Seç', 'Uygulama', 'Paket', 'Durum'])
        hdr = self.grid.horizontalHeader()
        hdr.setSectionResizeMode(COL_PKG, QHeaderView.Stretch)
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        hdr.setSectionResizeMode(COL_CHECK, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_STATE, QHeaderView.ResizeToContents)
        hdr.setSortIndicatorShown(True)
        hdr.sortIndicatorChanged.connect(self._sort_by)
        self.grid.setSortingEnabled(False)
        hdr.sectionClicked.connect(self._on_header_clicked)
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._context_menu)
        self.grid.itemChanged.connect(self._on_item_changed)
        self.grid.doubleClicked.connect(self._on_double_click)
        self.grid.itemChanged.connect(lambda _it: self._update_sel_count())
        self.grid.itemSelectionChanged.connect(self._update_sel_count)
        root.addWidget(self.grid, 1)

        # Sık kullanılan işler görünür; daha seyrek paket işleri menüdedir.
        actions = FlowLayout(hspacing=4, vspacing=4)
        self.btn_select_all = QPushButton('Tümünü Seç')
        self.btn_select_all.clicked.connect(self._select_all)
        self.chk_inv = QPushButton('Ters Çevir')
        self.chk_inv.clicked.connect(self._invert_all)
        self.lbl_sel = QLabel('')
        self.lbl_sel.setAlignment(Qt.AlignCenter)
        self.lbl_sel.setMinimumWidth(90)
        self.lbl_sel.setStyleSheet(kit.faint(kit.dark_from(self)))
        self.btn_launch = QPushButton('Aç')
        self.btn_launch.clicked.connect(lambda: self._pkg_action('launch'))

        self.btn_stop = QPushButton('Zorla durdur')
        self.btn_stop.clicked.connect(lambda: self._pkg_action('stop'))
        self.btn_clear = QPushButton('Veriyi Sil')
        self.btn_clear.setProperty('danger', True)
        self.btn_clear.setToolTip('Uygulama verilerini kalıcı olarak siler')
        self.btn_clear.clicked.connect(lambda: self._pkg_action('clear'))
        self.btn_disable = QPushButton('Devre dışı')
        self.btn_disable.clicked.connect(lambda: self._pkg_action('disable'))
        self.btn_enable = QPushButton('Aktif et')
        self.btn_enable.clicked.connect(lambda: self._pkg_action('enable'))
        self.btn_uninstall = QPushButton('Kaldır (user)')
        self.btn_uninstall.setProperty('danger', True)
        self.btn_uninstall.clicked.connect(lambda: self._pkg_action('uninstall'))
        self.btn_restore = QPushButton('Geri Yükle')
        self.btn_restore.clicked.connect(lambda: self._pkg_action('restore'))
        self.btn_apk = QPushButton('APK Yedekle')
        self.btn_apk.clicked.connect(self._backup_apk)
        self.btn_open_apk_dir = QPushButton('📁 Yedekler')
        self.btn_open_apk_dir.setToolTip('Yedeklenen APK dosyalarının bulunduğu klasörü açar')
        self.btn_open_apk_dir.clicked.connect(self._open_apk_dir)

        actions.addWidget(self.btn_select_all)
        actions.addWidget(self.chk_inv)
        actions.addWidget(self.lbl_sel)
        actions.addWidget(self.btn_launch)
        actions.addWidget(self.btn_stop)
        actions.addWidget(self.btn_apk)
        actions.addWidget(self.btn_open_apk_dir)
        actions.addWidget(self.btn_disable)
        actions.addWidget(self.btn_enable)
        actions.addWidget(self.btn_clear)
        actions.addWidget(self.btn_uninstall)
        actions.addWidget(self.btn_restore)
        root.addLayout(actions)

        # --- Özet ve başlangıç durumu ---
        self.lbl_summary = kit.status_label('Liste boş. "Yenile" ile başlayın.')
        root.addWidget(self.lbl_summary)
        kit.empty_state(self.grid, 'Henüz uygulama listesi yok',
                        'Cihazdaki uygulamaları görmek için Yenile’yi seçin.')
        self._update_system_btn()

    def _remote_tab(self):
        inner = getattr(self.window, 'tab_remote_inner', None)
        return inner or self.window.tab_remote

    # ------------------------------------------------------------------
    def _restore_status_from_config(self):
        """Kalici 'kaldirilmis gorunumu' ayarini acilir listeye uygula."""
        try:
            want = STATUS_REMOVED if self.core.config.show_removed else STATUS_ALL
            idx = self.cmb_status.findData(want)
        except Exception:
            return
        if idx < 0 or idx == self.cmb_status.currentIndex():
            return
        self.cmb_status.blockSignals(True)
        try:
            self.cmb_status.setCurrentIndex(idx)
        finally:
            try:
                self.cmb_status.blockSignals(False)
            except RuntimeError:
                pass

    def _on_status_combo(self):
        """Durum filtresini uygula; sistem görünürlüğü ayrı düğmeden yönetilir."""
        try:
            veri = self.cmb_status.currentData()
        except RuntimeError:
            return
        # 'Kaldirilmis' secilince kaldirilmis uygulamalar gorunur (kalici).
        try:
            want_removed = (veri == STATUS_REMOVED)
            if bool(self.core.config.show_removed) != want_removed:
                self.core.config.show_removed = want_removed
                self.core.config.save()
        except Exception:
            pass
        self._apply_filter_now()

    def _sort_by(self, col, order):
        keys = {COL_NAME: 'name', COL_PKG: 'package', COL_STATE: 'enabled'}
        key = keys.get(col)
        if not key:
            return
        rev = (order == Qt.DescendingOrder)
        self._apps.sort(key=lambda a: str(a.get(key) or ''), reverse=rev)
        self._apply_filter_now()

    # ------------------------------------------------------------------
    def refresh(self, on_done=None, on_fail=None):
        if getattr(self, '_busy', False):
            self.lbl_summary.setText('Tarama zaten suruyor; bitmesini bekleyin.')
            return False
        if not getattr(self.core, 'connected', False) or not getattr(self.core, 'target', None):
            self.lbl_summary.setText("Bağlı cihaz yok. Uygulamaları listelemek için önce TV'ye bağlanın.")
            if on_fail:
                on_fail('cihaz bağlı değil')
            return False
        try:
            engine = self.core.engine
        except Exception as e:
            self.lbl_summary.setText('Tarama başarısız: ' + str(e))
            if on_fail:
                on_fail(str(e))
            return False
        self.lbl_summary.setText('Taraniyor...')
        # Tarama kapsami: 'Sistem' filtresi icin bu bayrak kullanilir.
        self._scanned_with_system = True
        self._scan_generation += 1
        generation, target = self._scan_generation, self.core.target
        w = AppScanWorker(engine, self.core.target, True)
        current = lambda: generation == self._scan_generation and target == self.core.target
        w.progress.connect(lambda *args: self._on_progress(*args) if current() else None)

        def scan_done(apps):
            if not current():
                return
            self._on_scan_done(apps)
            if on_done:
                on_done(apps)

        def scan_failed(error):
            if not current():
                self._set_busy(False)
                return
            self._on_scan_fail(error)
            if on_fail:
                on_fail(str(error))

        w.finished_ok.connect(scan_done)
        w.failed.connect(scan_failed)
        w.presence.connect(lambda pkgs: self._on_presence(pkgs) if current() else None)
        self.window._run(w, on_ok=lambda _: self._set_busy(False),
                           desc='Uygulamalar Yenile: {} taraniyor'.format(self.core.target))
        self._set_busy(True)
        return True

    def _set_busy(self, busy):
        # Ayni anda ikinci worker baslatma: tik/crash ve eski veri yarisi biter.
        self._busy = bool(busy)
        kit.set_busy((self.btn_refresh, self.btn_stop, self.btn_clear, self.btn_disable,
                      self.btn_enable, self.btn_uninstall, self.btn_restore,
                      self.btn_launch, self.btn_apk), busy)
        kit.set_busy((self.chk_inv,), busy)
        if not busy:
            self.grid.setEnabled(True)

    def _on_scan_fail(self, err):
        self._set_busy(False)
        self.lbl_summary.setText('Tarama başarısız: ' + str(err))

    def _on_presence(self, pkgs):
        if isinstance(pkgs, dict):
            self._presence = set(pkgs.get('present', ()))
            self._disabled_presence = set(pkgs.get('disabled', ()))
            self._presence_info = pkgs
        else:
            self._presence = set(pkgs)
            self._disabled_presence = set()
            self._presence_info = {'present': self._presence, 'disabled': set()}
        try:
            self.window.tab_debloat.set_present(self._presence_info)
        except Exception:
            pass

    def _on_progress(self, cur, total):
        self.lbl_summary.setText('{}/{} kontrol ediliyor...'.format(cur, total))

    def _on_scan_done(self, apps):
        self._apps = apps
        self._last_scan_at = datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %z')
        for a in apps:
            # Cihaz etiketi birincil kaynaktır; bilinen dost adları, ROM'un
            # uygulama etiketini ADB üzerinden vermediği durumlarda kullanılır.
            a['name'] = (a.get('label') or
                         self.core.config.friendly_name(a['package']))
        try:
            self._remote_tab().populate_apps(apps)
        except Exception:
            pass
        try:
            info = getattr(self, '_presence_info', None)
            if info is None:
                installed = [a for a in apps if a.get('installed_user0', True)]
                info = {
                    'present': {a['package'] for a in installed},
                    'disabled': {a['package'] for a in installed if not a.get('enabled', True)}
                }
            self.window.tab_debloat.set_present(info)
        except Exception:
            pass
        self._apply_filter_now()

    # ------------------------------------------------------------------
    @staticmethod
    def _check_flags(pkg, protected):
        """Koruma listesindeki uygulamalar islem icin secilemez."""
        if pkg in protected:
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return Qt.ItemIsUserCheckable | Qt.ItemIsEnabled

    def _selected_packages(self):
        # Silinmis satirlara erisim RuntimeError verebilir; korumali topla
        # (tik-crash suphelisi #3).
        out = []
        try:
            nrows = self.grid.rowCount()
        except RuntimeError:
            return out
        for row in range(nrows):
            try:
                item = self.grid.item(row, COL_CHECK)
            except RuntimeError:
                continue
            if item and (item.flags() & Qt.ItemIsUserCheckable) and item.checkState() == Qt.Checked:
                try:
                    pkg = self.grid.item(row, COL_PKG)
                except RuntimeError:
                    continue
                if pkg:
                    out.append(pkg.text())
        # secili satirlardan da topla (checkbox isaretlenmemisse bile)
        if not out:
            try:
                rows = {i.row() for i in self.grid.selectedIndexes()}
            except RuntimeError:
                return out
            for r in rows:
                try:
                    check = self.grid.item(r, COL_CHECK)
                    pkg = self.grid.item(r, COL_PKG)
                except RuntimeError:
                    continue
                if (check and (check.flags() & Qt.ItemIsUserCheckable)
                        and pkg and pkg.text() not in out):
                    out.append(pkg.text())
        return out

    def _apply_filter(self):
        self._filter_timer.start()

    def _on_system_toggle(self, _checked):
        self._update_system_btn()
        self._apply_filter_now()

    def _update_system_btn(self):
        """Sistem filtresi dügmesini aktif/inaktif durumuna göre görsel olarak özellestirir."""
        count = sum(bool(a.get('system')) and a.get('installed_user0', True) for a in self._apps)
        checked = self.btn_system.isChecked()
        dark = kit.dark_from(self)

        if checked:
            self.btn_system.setText('✓ Sistem ({})'.format(count))
            self.btn_system.setToolTip(
                'Sistem uygulamaları dahil (gösteriliyor — {} paket).\n'
                'Yalnızca kullanıcı uygulamalarını görmek için tıklayın.'.format(count))
            if dark:
                self.btn_system.setStyleSheet('''
                    QPushButton#btnSystemFilter {
                        background-color: #38457c;
                        color: #ffffff;
                        border: 1.5px solid #8795ff;
                        border-radius: 6px;
                        padding: 4px 12px;
                        font-weight: 600;
                    }
                    QPushButton#btnSystemFilter:hover {
                        background-color: #46569a;
                        border-color: #a0abff;
                    }
                ''')
            else:
                self.btn_system.setStyleSheet('''
                    QPushButton#btnSystemFilter {
                        background-color: #5365d8;
                        color: #ffffff;
                        border: 1.5px solid #4253bb;
                        border-radius: 6px;
                        padding: 4px 12px;
                        font-weight: 600;
                    }
                    QPushButton#btnSystemFilter:hover {
                        background-color: #4253bb;
                    }
                ''')
        else:
            self.btn_system.setText('○ Sistem: Gizli ({})'.format(count))
            self.btn_system.setToolTip(
                'Sistem uygulamaları gizlendi ({} paket gizli).\n'
                'Sistem uygulamalarını listeye dahil etmek için tıklayın.'.format(count))
            if dark:
                self.btn_system.setStyleSheet('''
                    QPushButton#btnSystemFilter {
                        background-color: rgba(255, 255, 255, 0.03);
                        color: #828c9f;
                        border: 1px dashed #454c5c;
                        border-radius: 6px;
                        padding: 4px 12px;
                        font-weight: normal;
                    }
                    QPushButton#btnSystemFilter:hover {
                        background-color: rgba(255, 255, 255, 0.08);
                        color: #edf0f7;
                        border-color: #636b7b;
                    }
                ''')
            else:
                self.btn_system.setStyleSheet('''
                    QPushButton#btnSystemFilter {
                        background-color: transparent;
                        color: #778297;
                        border: 1px dashed #bcc5d7;
                        border-radius: 6px;
                        padding: 4px 12px;
                        font-weight: normal;
                    }
                    QPushButton#btnSystemFilter:hover {
                        background-color: #e8ebf3;
                        color: #202637;
                    }
                ''')

    def apply_theme(self):
        """Tema degisince: secim etiketi + tablo on renklerini yeni palete gecir."""
        try:
            self.lbl_sel.setStyleSheet(kit.faint(kit.dark_from(self)))
            self._update_system_btn()
        except (RuntimeError, AttributeError):
            return
        try:
            self._apply_filter_now()
        except (RuntimeError, AttributeError):
            pass
        except Exception:
            pass

    def _apply_filter_now(self):
        q = self.txt_search.text().strip().lower()
        sf = self.cmb_status.currentData()      # etiket degil, VERI
        # Durum + süreç + sistem filtreleri tek listede.
        only_removed = (sf == STATUS_REMOVED)
        only_run = (sf == STATUS_RUNNING)
        include_system = self.btn_system.isChecked()
        self.grid.blockSignals(True)
        self.grid.setRowCount(0)
        removed = 0
        removed_hidden = 0
        shown_system = 0
        for a in self._apps:
            is_removed = not a.get('installed_user0', True)
            if is_removed:
                removed += 1
                if not only_removed:
                    removed_hidden += 1
                    continue
            elif only_removed:
                # 'Kaldırılmış' filtresi: kurulu olanlar gösterilmez.
                continue
            hay = (a['name'] + ' ' + a['package']).lower()
            if q and q not in hay:
                continue
            enabled = bool(a.get('enabled', True))
            if sf == STATUS_ACTIVE and (not enabled or is_removed):
                continue
            if sf == STATUS_DISABLED and (enabled or is_removed):
                continue
            if not include_system and a.get('system'):
                continue
            if only_run and (not enabled or is_removed
                             or a.get('running') != DATA_RUNNING):
                continue
            shown_system += int(bool(a.get('system')))
            r = self.grid.rowCount()
            self.grid.insertRow(r)
            chk = QTableWidgetItem()
            chk.setFlags(self._check_flags(a['package'], self.core.config.protected))
            chk.setCheckState(Qt.Unchecked)
            chk.setData(Qt.UserRole, a['package'])
            name = QTableWidgetItem(a['name'])
            name.setData(Qt.UserRole, a['package'])
            pkg = QTableWidgetItem(a['package'])
            pal = kit.colors(self)
            removed_u0 = not a.get('installed_user0', True)
            disabled = removed_u0 or not a.get('enabled', True)
            if removed_u0:
                state = QTableWidgetItem('Kaldırılmış')
            else:
                state = QTableWidgetItem('Devre dışı' if not enabled else 'Etkin')
            if removed_u0:
                state.setToolTip('user 0 için kaldırılmış; sağ tık > Geri Yükle ile döndürülebilir')
                state_color = pal['accent']
            elif not enabled:
                state_color = pal['warning']
            else:
                state_color = pal['success']
            state.setForeground(QBrush(QColor(state_color)))
            prot = self.core.config.is_protected(a['package'])
            if prot:
                for it in (name, pkg, state):
                    it.setForeground(QBrush(QColor(pal['warning'])))
                name.setToolTip('Koruma listesinde (işlem için secilemez)')
                chk.setToolTip('Koruma listesinde (işlem için secilemez)')
            if disabled:
                # Kaldirilmis / devre disi: ad + paket satiri ustu cizili ve soluk
                for it in (name, pkg):
                    fnt = it.font()
                    fnt.setStrikeOut(True)
                    it.setFont(fnt)
                    it.setForeground(QBrush(QColor(pal['faint'])))
                name.setToolTip('Kaldırılmış: {} — sağ tık > Geri Yükle ile döndürülebilir'.format(
                    a['package']) if removed_u0 else 'Devre dışı: {}'.format(a['package']))
            for it in (name, pkg, state):
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.grid.setItem(r, COL_CHECK, chk)
            self.grid.setItem(r, COL_NAME, name)
            self.grid.setItem(r, COL_PKG, pkg)
            self.grid.setItem(r, COL_STATE, state)
        self.grid.blockSignals(False)
        suffix = ('  |  ({} kaldırılmış gizli — "Kaldırılmış" seçeneğiyle göster)'.format(
            removed_hidden) if removed_hidden else '')
        scan_time = ('  |  Son tarama: {}'.format(self._last_scan_at)
                     if self._last_scan_at else '')
        self.lbl_summary.setText(
            'Gösterilen: {}  |  Kullanıcı: {}  |  Sistem: {}{}{}'.format(
                self.grid.rowCount(), self.grid.rowCount() - shown_system, shown_system, suffix, scan_time))
        self._update_system_btn()
        if self._apps and not self.grid.rowCount():
            if only_run:
                eligible = [a for a in self._apps
                            if a.get('enabled', True) and a.get('installed_user0', True)
                            and (not q or q in (a['name'] + ' ' + a['package']).lower())
                            and (include_system or not a.get('system'))]
                if not eligible:
                    title = 'Eşleşen uygulama yok'
                    description = (
                        'Bu arama ve süreç filtresiyle eşleşen etkin, kurulu uygulama yok.')
                elif any(a.get('running') not in ('Evet', 'Hayır', 'Hayir')
                         for a in eligible):
                    title = 'Çalışma durumu bilinmiyor'
                    description = (
                        'ADB süreç bilgisi alınamadı. Son tarama: {}. '
                        'Bu filtre süreçleri gösterir; ön plandaki uygulamayı belirtmez.'
                    ).format(self._last_scan_at or 'henüz tarama yapılmadı')
                else:
                    title = 'Çalışan süreç yok'
                    description = (
                        'Son tarama: {}. Etkin ve kurulu uygulamalardan hiçbiri için '
                        'çalışan süreç bildirilmedi; bu, ön plandaki uygulamayı belirtmez.'
                    ).format(self._last_scan_at or 'henüz tarama yapılmadı')
                kit.empty_state(self.grid, title, description)
            else:
                kit.empty_state(self.grid, 'Eşleşen uygulama yok',
                                'Arama metnini veya durum filtresini değiştirin.')
        else:
            kit.empty_state(self.grid, 'Henüz uygulama listesi yok',
                            'Cihazdaki uygulamaları görmek için Yenile’yi seçin.')
        self._update_sel_count()

    def _on_item_changed(self, item):
        # KRITIK: setFlags() itemChanged'i TETIKLER -> ozyineleme ->
        # stack overflow (crash-20261012.log'da yakalandi). Koruma:
        # yeniden-giris bayragi + sinyal bastirma + bayrak esitlik kontrolu.
        if getattr(self, '_in_item_changed', False):
            return
        self._in_item_changed = True
        try:
            if item is None or item.column() != COL_CHECK:
                return
            row = item.row()
            if row < 0 or row >= self.grid.rowCount():
                return
            pkg_item = self.grid.item(row, COL_PKG)
            if pkg_item:
                want = self._check_flags(pkg_item.text(), self.core.config.protected)
                if item.flags() != want:
                    self.grid.blockSignals(True)
                    try:
                        item.setFlags(want)
                    finally:
                        self.grid.blockSignals(False)
        except RuntimeError:
            pass
        except Exception:
            pass
        finally:
            self._in_item_changed = False

    def _on_header_clicked(self, section):
        # 'Sec' basligina tik: bos -> tumu, tumu -> birak. Diger sutunlar: sirala.
        if section != COL_CHECK:
            return
        try:
            total = sum(1 for row in range(self.grid.rowCount())
                        for _it in [self.grid.item(row, COL_CHECK)]
                        if _it is not None and (_it.flags() & Qt.ItemIsUserCheckable))
            checked = sum(1 for row in range(self.grid.rowCount())
                          for _it in [self.grid.item(row, COL_CHECK)]
                          if _it is not None and (_it.flags() & Qt.ItemIsUserCheckable)
                          and _it.checkState() == Qt.Checked)
        except RuntimeError:
            return
        self._toggle_all(checked < total)

    def _toggle_all(self, on):
        # Tumunu sec/birak: sinyalleri bastir (147 satir x itemChanged
        # yavasligi ve yeniden-giris yarisini onler — tik-crash suphelisi).
        st = Qt.Checked if on else Qt.Unchecked
        self.grid.blockSignals(True)
        try:
            for row in range(self.grid.rowCount()):
                it = self.grid.item(row, COL_CHECK)
                if it and (it.flags() & Qt.ItemIsUserCheckable):
                    if it.checkState() != st:
                        it.setCheckState(st)
        finally:
            self.grid.blockSignals(False)
        try:
            header_item = self.grid.horizontalHeaderItem(COL_CHECK)
            if header_item is not None:
                header_item.setText('☑ Seç')
        except RuntimeError:
            pass
        self._update_sel_count()
        # baslik gostergesi: tamami seciliyse ☑, kismi ☐
        try:
            hdr_item = self.grid.horizontalHeaderItem(COL_CHECK)
            if hdr_item is not None:
                hdr_item.setText('☑ Seç' if on else 'Seç')
        except RuntimeError:
            pass

    def _select_all(self):
        self.grid.blockSignals(True)
        try:
            for row in range(self.grid.rowCount()):
                it = self.grid.item(row, COL_CHECK)
                if it and (it.flags() & Qt.ItemIsUserCheckable):
                    it.setCheckState(Qt.Checked)
        finally:
            self.grid.blockSignals(False)
        self._update_sel_count()

    def _invert_all(self):
        self.grid.blockSignals(True)
        try:
            for row in range(self.grid.rowCount()):
                it = self.grid.item(row, COL_CHECK)
                if it and (it.flags() & Qt.ItemIsUserCheckable):
                    it.setCheckState(
                        Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)
        finally:
            self.grid.blockSignals(False)
        self._update_sel_count()

    def _update_sel_count(self):
        try:
            checked = {row for row in range(self.grid.rowCount())
                       for _it in [self.grid.item(row, COL_CHECK)]
                       if _it is not None and (_it.flags() & Qt.ItemIsUserCheckable)
                       and _it.checkState() == Qt.Checked}
            selected = {ix.row() for ix in self.grid.selectedIndexes()
                        if self.grid.item(ix.row(), COL_CHECK) is not None
                        and self.grid.item(ix.row(), COL_CHECK).flags() & Qt.ItemIsUserCheckable}
            rows = checked or selected
            self.lbl_sel.setText('Seçili: {}/{}{}'.format(
                len(rows), self.grid.rowCount(),
                ' (satir)' if selected and not checked else ''))
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    def _pkg_action(self, action):
        from .dialogs import confirm_action
        pkgs = self._selected_packages()
        if not pkgs:
            QMessageBox.information(self, 'Seçim', 'Önce uygulama seçin.')
            return
        prot = [p for p in pkgs if self.core.config.is_protected(p)]
        if prot and len(prot) == len(pkgs):
            names = '\n'.join(u'• {}'.format(self.core.config.friendly_name(p)) for p in prot[:10])
            QMessageBox.warning(
                self, 'Koruma',
                u'Seçilenlerin TAMAMI koruma listesinde; işlem yapılmadı:\n\n{}'.format(names))
            return
        if action in ('uninstall', 'clear', 'disable', 'stop'):
            if not confirm_action(self, action, pkgs,
                                  self.core.config.friendly_name):
                return
        from .dialogs import ACTION_TR
        try:
            self.window.set_last_action(
                '{} uygulamaya {}: {} paket'.format(
                    len(pkgs), ACTION_TR.get(action, action),
                    ', '.join(pkgs[:3]) + ('…' if len(pkgs) > 3 else '')))
        except Exception:
            pass
        w = PackageActionWorker(self.core.engine, self.core.target, pkgs,
                                action, self.core.config.protected)
        w.progress.connect(self._on_progress)
        w.finished_ok.connect(self._on_pkg_done)
        self.window._run(w, on_ok=lambda _: self.refresh())

    def _on_pkg_done(self, res):
        from ..workers import format_action_result
        QMessageBox.information(self, 'Tamam', format_action_result(res))

    def _backup_apk(self):
        pkgs = self._selected_packages()
        if not pkgs:
            QMessageBox.information(self, 'Seçim', 'Önce APK yedeklenecek uygulamaları seçin.')
            return
        import os
        os.makedirs(APK_DIR, exist_ok=True)
        w = ApkBackupWorker(self.core.engine, self.core.target, pkgs, APK_DIR)
        w.progress.connect(self._on_progress)
        w.finished_ok.connect(self._on_backup_done)
        self.window._run(w)

    def _open_apk_dir(self):
        import os, subprocess, sys
        os.makedirs(APK_DIR, exist_ok=True)
        try:
            if sys.platform == 'win32':
                os.startfile(APK_DIR)
            else:
                subprocess.Popen(['xdg-open', APK_DIR])
        except Exception as e:
            QMessageBox.warning(self, 'Hata', f'Klasör açılamadı: {e}')

    def _on_backup_done(self, res):
        ok = res.get('ok', 0)
        fail = res.get('fail', 0)
        msg = f'{ok} APK yedeklendi' + (f', {fail} başarısız.' if fail else '.') + f'\n\nKonum: {APK_DIR}\n\nYedekleme klasörü açılsın mı?'
        if QMessageBox.question(self, 'Yedekleme Tamamlandı', msg, QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self._open_apk_dir()

    def _export_csv(self):
        if not self._apps:
            QMessageBox.information(self, 'Aktar', 'Önce listeyi yenileyin.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'CSV Kaydet', 'mibox-uygulamalar.csv',
                                              'CSV (*.csv)')
        if not path:
            return
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(['Ad', 'Paket', 'Durum'])
                for row in range(self.grid.rowCount()):
                    w.writerow([self.grid.item(row, c).text() if self.grid.item(row, c) else ''
                                for c in (COL_NAME, COL_PKG, COL_STATE)])
            QMessageBox.information(self, 'Tamam', 'Aktarıldı:\n' + path)
        except OSError as e:
            QMessageBox.critical(self, 'Hata', str(e))

    # ------------------------------------------------------------------
    def _on_double_click(self, index):
        pkg_item = self.grid.item(index.row(), COL_PKG)
        if pkg_item:
            self._show_detail(pkg_item.text())

    def _show_detail(self, pkg):
        dlg = QDialog(self)
        dlg.setWindowTitle('Uygulama Detayi - ' + pkg)
        dlg.resize(560, 420)
        lay = QVBoxLayout(dlg)
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText('Yükleniyor...')
        lay.addWidget(txt)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        def do():
            eng = self.core.engine
            t = self.core.target
            eng.connect(t)
            d = eng.app_detail(t, pkg)
            try:
                size_kb = eng.app_size(t, pkg)
            except Exception:
                size_kb = None
            return d, size_kb

        def done(res):
            d, size_kb = res
            size_txt = ('{:.1f} MB'.format(size_kb / 1024) if size_kb else 'olcumulemedi')
            txt.setPlainText(
                'Paket: {}\nAd: {}\nSurum: {} ({})\nKurucu: {}\n'
                'İlk kurulum: {}\nSon güncelleme: {}\nAktif: {}\nVeri boyutu: {}\n'
                'APK yolu: {}\nVeri klasoru: {}\n'.format(
                    d['package'], self.core.config.friendly_name(pkg),
                    d['versionName'], d['versionCode'], d['installer'],
                    d['firstInstall'], d['lastUpdate'],
                    'Evet' if d['enabled'] else 'Hayir', size_txt,
                    d['codePath'], d['dataDir']))

        w = Worker(do)
        w.finished_ok.connect(done)
        w.failed.connect(lambda e: txt.setPlainText('Hata: ' + str(e)))
        self.window._run(w)
        dlg.exec()

    # ------------------------------------------------------------------
    def _context_menu(self, pos):
        # Sag tik sirasinda grid degismis olabilir; tum erisim korumali
        # (tik-crash suphelisi #2: menu acilirken row kaymasi).
        try:
            row = self.grid.rowAt(pos.y())
            if row < 0 or row >= self.grid.rowCount():
                return
            pkg = self.grid.item(row, COL_PKG)
            if not pkg:
                return
            p = pkg.text()
        except RuntimeError:
            return
        except Exception:
            return
        try:
            chk = self.grid.item(row, COL_CHECK)
            if chk and (chk.flags() & Qt.ItemIsUserCheckable):
                self.grid.blockSignals(True)
                try:
                    chk.setCheckState(Qt.Checked)
                finally:
                    self.grid.blockSignals(False)
        except RuntimeError:
            return
        except Exception:
            pass
        menu = QMenu(self)
        # kaldirilmis mi? (user 0 listesinde yoksa)
        removed = False
        state_cell = self.grid.item(row, COL_STATE)
        if state_cell and state_cell.text() == 'Kaldırılmış':
            removed = True
        if removed:
            act = menu.addAction('Geri Yükle (önerilen)')
            f = act.font()
            f.setBold(True)
            act.setFont(f)
            act.triggered.connect(lambda: self._pkg_action_single('restore', p))
        menu.addAction('📋 Paket Adını Kopyala', lambda: QApplication.clipboard().setText(p))
        menu.addSeparator()
        menu.addAction('Detay', lambda: self._show_detail(p))
        menu.addAction('Aç', lambda: self._pkg_action_single('launch', p))
        menu.addAction('Zorla durdur', lambda: self._pkg_action_single('stop', p))
        menu.addAction('Veriyi Sil', lambda: self._pkg_action_single('clear', p))
        menu.addAction('Devre dışı bırak', lambda: self._pkg_action_single('disable', p))
        menu.addAction('Aktif et', lambda: self._pkg_action_single('enable', p))
        menu.addAction('Kaldır (user)', lambda: self._pkg_action_single('uninstall', p))
        menu.addAction('Geri Yükle', lambda: self._pkg_action_single('restore', p))
        menu.addAction('APK Yedekle', lambda: self._backup_apk())
        menu.exec(self.grid.viewport().mapToGlobal(pos))

    def _pkg_action_single(self, action, pkg):
        from .dialogs import confirm_action
        if action in ('uninstall', 'clear', 'disable', 'stop'):
            if not confirm_action(self, action, [pkg],
                                  self.core.config.friendly_name):
                return
        w = PackageActionWorker(self.core.engine, self.core.target, [pkg],
                                action, self.core.config.protected)
        w.finished_ok.connect(self._on_pkg_done)
        self.window._run(w, on_ok=lambda _: self.refresh())
