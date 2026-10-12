# -*- coding: utf-8 -*-
"""Uygulamalar sekmesi: liste, filtre, kisitla/serbest, paket islemleri."""
import csv

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidgetItem, QLineEdit, QComboBox, QPushButton,
    QLabel, QHeaderView, QMenu, QMessageBox,
    QFileDialog, QDialog, QDialogButtonBox, QTextEdit,
)

from ..config import APK_DIR
from ..debloat_db import package_to_category, CAT_LABELS, CAT_COLORS
from ..workers import AppScanWorker, BulkActionWorker, PackageActionWorker, ApkBackupWorker, Worker
from . import kit
from .flowlayout import FlowLayout
from .theme import cat_colors_for

COL_CHECK = 0
COL_NAME = 1
COL_PKG = 2
COL_STATUS = 3
COL_RUNNING = 4
COL_DEBLOAT = 5
COL_ENABLED = 6

# Durum filtresi: eskiden ayri duran "Calisan / Kaldirilmis / Sistem"
# kutularinin islevi artik bu TEK acilir listenin icinde toplanmistir.
#
# ONEMLI: ekranda gorunen ETIKET ile karsilastirilan VERI ayridir.
# Filtre karsilastirmalari HER ZAMAN veri (currentData) ile yapilir; boylece
# "Kisitli" -> "Kısıtlı" gibi yazim duzeltmeleri filtreyi sessizce bozamaz.
STATUS_ALL = 'all'
STATUS_RESTRICTED = 'restricted'
STATUS_FREE = 'free'
STATUS_DISABLED = 'disabled'
STATUS_REMOVED = 'removed'
STATUS_RUNNING = 'running'
STATUS_SYSTEM = 'system'
STATUS_ITEMS = [
    ('Tümü', STATUS_ALL),
    ('Kısıtlı', STATUS_RESTRICTED),
    ('Serbest', STATUS_FREE),
    ('Devre dışı', STATUS_DISABLED),
    ('Kaldırılmış', STATUS_REMOVED),
    ('Çalışan', STATUS_RUNNING),
    ('Sistem', STATUS_SYSTEM),
]
# Motorun urettigi VERI degerleri (adb_engine.app_status / workers) — etiket degil.
DATA_RESTRICTED = 'Kisitli'
DATA_FREE = 'Serbest'
DATA_RUNNING = 'Evet'
DEBLOAT_ALL_LABEL = 'Debloat: Tümü'


class AppsTab(QWidget):
    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._apps = []
        self._presence = set()
        self._in_item_changed = False  # ozyineleme kilidi (stack overflow korumasi)
        self._busy = False
        # Son tarama sistem paketlerini kapsadi mi? ('Sistem' filtresi icin)
        self._scanned_with_system = bool(getattr(core.config, 'include_system', False))
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(250)
        self._filter_timer.timeout.connect(self._apply_filter_now)
        self._build()

    def _build(self):
        root = kit.page(self)

        # --- Araclar satir 1: arama + durum filtresi + debloat + CSV ---
        row1 = QHBoxLayout()
        row1.setSpacing(kit.SPACING)
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText('Ara: ad veya paket...')
        self.txt_search.setMinimumWidth(220)
        self.txt_search.textChanged.connect(lambda: self._filter_timer.start())
        # Durum filtresi: Tümü / Kısıtlı / Serbest / Devre dışı / Kaldırılmış /
        # Çalışan / Sistem. (Eskiden ayri duran 3 kutu artik burada.)
        self.cmb_status = QComboBox()
        for etiket, veri in STATUS_ITEMS:
            self.cmb_status.addItem(etiket, veri)
        # Kutu, listedeki en uzun secenegi (Kaldırılmış/Devre dışı) gosterecek
        # kadar genis olsun; secenekler kirpilmasin.
        self.cmb_status.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.cmb_status.setMinimumWidth(110)
        self.cmb_status.setToolTip(
            'Duruma gore filtrele — Tümü: hepsi, Kaldırılmış: user 0\'dan '
            'kaldirilanlar (geri yuklenebilir), Çalışan: su an acik olanlar, '
            'Sistem: ROM uygulamalari (tarama sistem paketlerini de kapsar)')
        self.cmb_status.currentIndexChanged.connect(self._on_status_combo)
        self._restore_status_from_config()
        self.cmb_debloat = QComboBox()
        self.cmb_debloat.addItem(DEBLOAT_ALL_LABEL, '')
        for etiket in CAT_LABELS.values():
            self.cmb_debloat.addItem(etiket, etiket)
        self.cmb_debloat.currentIndexChanged.connect(self._apply_filter_now)
        self.btn_export = QPushButton('CSV')
        self.btn_export.setToolTip('Listeyi CSV olarak aktar')
        self.btn_export.clicked.connect(self._export_csv)
        row1.addWidget(self.txt_search, 1)
        row1.addWidget(self.cmb_status)
        row1.addWidget(self.cmb_debloat)
        row1.addWidget(self.btn_export)
        root.addLayout(row1)

        # --- Araclar satir 2: yenile ---
        row2 = QHBoxLayout()
        row2.setSpacing(4)
        self.btn_refresh = QPushButton('Yenile')
        self.btn_refresh.setProperty('accent', True)
        self.btn_refresh.clicked.connect(self.refresh)
        row2.addWidget(self.btn_refresh)
        row2.addStretch()
        root.addLayout(row2)

        # --- Tablo (esnek, pencereyle buyur/kucuk) ---
        self.grid = kit.make_table(7, ['Sec', 'Uygulama', 'Paket', 'Durum',
                                       'Calisiyor', 'Debloat', 'Aktif'])
        hdr = self.grid.horizontalHeader()
        hdr.setSectionResizeMode(COL_PKG, QHeaderView.Stretch)
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        hdr.setSectionResizeMode(COL_CHECK, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_RUNNING, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_DEBLOAT, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_ENABLED, QHeaderView.ResizeToContents)
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

        # --- Islem cubuklari (FlowLayout: dar ekranda alt satira kayar) ---
        # Sec basligi tiklanabilir: 3 durum (bos -> tumu -> ters) + sayac.
        # Ayri buton YOK: tek tik, tek Birak.
        flow1 = FlowLayout()
        self.chk_inv = QPushButton('Ters Cevir')
        self.chk_inv.clicked.connect(self._invert_all)
        self.lbl_sel = QLabel('')
        self.lbl_sel.setStyleSheet(kit.faint(kit.dark_from(self)))
        self.btn_restrict = QPushButton('Kisitla')
        self.btn_restrict.setProperty('danger', True)
        self.btn_restrict.clicked.connect(lambda: self._bulk_restrict(True))
        self.btn_unrestrict = QPushButton('Serbest Birak')
        self.btn_unrestrict.setProperty('accent', True)
        self.btn_unrestrict.clicked.connect(lambda: self._bulk_restrict(False))
        for b in (self.chk_inv, self.btn_restrict, self.btn_unrestrict):
            flow1.addWidget(b)
        flow1.addWidget(self.lbl_sel)
        kit.fit_buttons(self.chk_inv)
        root.addLayout(flow1)

        flow2 = kit.action_bar()
        self.btn_stop = QPushButton('Force Stop')
        self.btn_stop.clicked.connect(lambda: self._pkg_action('stop'))
        self.btn_clear = QPushButton('Veriyi Sil')
        self.btn_clear.clicked.connect(lambda: self._pkg_action('clear'))
        self.btn_disable = QPushButton('Devre disi')
        self.btn_disable.clicked.connect(lambda: self._pkg_action('disable'))
        self.btn_enable = QPushButton('Aktif et')
        self.btn_enable.clicked.connect(lambda: self._pkg_action('enable'))
        self.btn_uninstall = QPushButton('Kaldir (user)')
        self.btn_uninstall.setProperty('danger', True)
        self.btn_uninstall.clicked.connect(lambda: self._pkg_action('uninstall'))
        self.btn_restore = QPushButton('Geri Yukle')
        self.btn_restore.clicked.connect(lambda: self._pkg_action('restore'))
        self.btn_launch = QPushButton('Ac')
        self.btn_launch.clicked.connect(lambda: self._pkg_action('launch'))
        self.btn_apk = QPushButton('APK Yedekle')
        self.btn_apk.clicked.connect(self._backup_apk)
        for b in (self.btn_stop, self.btn_clear, self.btn_disable, self.btn_enable,
                  self.btn_uninstall, self.btn_restore, self.btn_launch, self.btn_apk):
            flow2.addWidget(b)
        kit.fit_buttons(self.btn_stop, self.btn_clear, self.btn_disable, self.btn_enable,
                        self.btn_uninstall, self.btn_restore, self.btn_launch, self.btn_apk)
        root.addLayout(flow2)

        # --- Ozet ---
        self.lbl_summary = kit.status_label('Liste bos. "Yenile" ile baslayin.')
        root.addWidget(self.lbl_summary)

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
        """Durum filtresi: 'Kaldirilmis' gorunurlugu + 'Sistem' taramasi burada.

        Eskiden ayri iki kutu (Kaldirilmis / Sistem) ile yonetiliyordu; artik
        tek acilir liste hem filtre hem de tarama kapsamini belirler.
        """
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
        # 'Sistem' secilince tarama sistem paketlerini de kapsar (kalici);
        # eldeki liste sistem paketleri olmadan tarandiysa tazele.
        if veri == STATUS_SYSTEM:
            need_scan = False
            try:
                if not self.core.config.include_system:
                    self.core.config.include_system = True
                    self.core.config.save()
                    need_scan = True
            except Exception:
                pass
            if need_scan or not getattr(self, '_scanned_with_system', False):
                try:
                    self.window.append_log(
                        'Sistem filtresi: sistem uygulamalari da taranacak.', 'INFO')
                except Exception:
                    pass
                self.refresh()
                # Tarama basladiysa filtre bitince uygulanir; tarama zaten
                # suruyorsa (refresh erken dondu) eldeki listeyi hemen filtrele.
                self._apply_filter_now()
                return
        self._apply_filter_now()

    def _sort_by(self, col, order):
        keys = {COL_NAME: 'name', COL_PKG: 'package', COL_STATUS: 'status',
                COL_RUNNING: 'running', COL_DEBLOAT: 'debloat',
                COL_ENABLED: 'enabled'}
        key = keys.get(col)
        if not key:
            return
        rev = (order == Qt.DescendingOrder)
        self._apps.sort(key=lambda a: str(a.get(key) or ''), reverse=rev)
        self._apply_filter_now()

    # ------------------------------------------------------------------
    def refresh(self):
        if getattr(self, '_busy', False):
            self.lbl_summary.setText('Tarama zaten suruyor; bitmesini bekleyin.')
            return
        try:
            engine = self.core.engine
        except Exception as e:
            self.lbl_summary.setText('Tarama basarisiz: ' + str(e))
            return
        self.lbl_summary.setText('Taraniyor...')
        # Tarama kapsami: 'Sistem' filtresi icin bu bayrak kullanilir.
        self._scanned_with_system = bool(self.core.config.include_system)
        w = AppScanWorker(engine, self.core.target, self.core.config.include_system)
        w.progress.connect(self._on_progress)
        w.finished_ok.connect(self._on_scan_done)
        w.failed.connect(self._on_scan_fail)
        w.presence.connect(self._on_presence)
        self.window._run(w, on_ok=lambda _: self._set_busy(False),
                           desc='Uygulamalar Yenile: {} taraniyor'.format(self.core.target))
        self._set_busy(True)

    def _set_busy(self, busy):
        # Ayni anda ikinci worker baslatma: tik/crash ve eski veri yarisi biter.
        self._busy = bool(busy)
        kit.set_busy((self.btn_refresh, self.btn_restrict, self.btn_unrestrict,
                      self.btn_stop, self.btn_clear, self.btn_disable,
                      self.btn_enable, self.btn_uninstall, self.btn_restore,
                      self.btn_launch, self.btn_apk), busy)
        kit.set_busy((self.chk_inv,), busy)
        if not busy:
            self.grid.setEnabled(True)

    def _on_scan_fail(self, err):
        self._set_busy(False)
        self.lbl_summary.setText('Tarama basarisiz: ' + str(err))

    def _on_presence(self, pkgs):
        self._presence = set(pkgs)
        try:
            self.window.tab_debloat.set_present(self._presence)
        except Exception:
            pass

    def _on_progress(self, cur, total):
        self.lbl_summary.setText('{}/{} kontrol ediliyor...'.format(cur, total))

    def _on_scan_done(self, apps):
        self._apps = apps
        for a in apps:
            # Once cihazdan gelen GERCEK ad; yoksa paket adi.
            # (Bilinen-uygulama listesi kaldirildi: sistem ne derse o.)
            a['name'] = a.get('label') or a['package']
            cat = package_to_category(a['package'])
            a['debloat_cat'] = cat
            a['debloat'] = CAT_LABELS.get(cat, '')
        try:
            self._remote_tab().populate_apps(apps)
        except Exception:
            pass
        try:
            self.window.tab_debloat.set_present(self._presence)
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
                    pkg = self.grid.item(r, COL_PKG)
                except RuntimeError:
                    continue
                if pkg and pkg.text() not in out:
                    out.append(pkg.text())
        return out

    def _apply_filter(self):
        self._filter_timer.start()

    def apply_theme(self):
        """Tema degisince: secim etiketi + tablo on renklerini yeni palete gecir."""
        try:
            self.lbl_sel.setStyleSheet(kit.faint(kit.dark_from(self)))
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
        df = self.cmb_debloat.currentData()     # '' = tum kategoriler
        # Tek acilir liste: durum + calisan + kaldirilmis + sistem filtreleri.
        only_removed = (sf == STATUS_REMOVED)
        only_run = (sf == STATUS_RUNNING)
        only_system = (sf == STATUS_SYSTEM)
        self.grid.blockSignals(True)
        self.grid.setRowCount(0)
        free = 0
        lim = 0
        bloat = 0
        removed = 0
        removed_hidden = 0
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
            if sf == STATUS_RESTRICTED and a['status'] != DATA_RESTRICTED:
                continue
            if sf == STATUS_FREE and a['status'] != DATA_FREE:
                continue
            if sf == STATUS_DISABLED and (a.get('enabled', True) or is_removed):
                continue
            if only_system and not a.get('system'):
                continue
            if df and a['debloat'] != df:
                continue
            if only_run and a['running'] != DATA_RUNNING:
                continue
            r = self.grid.rowCount()
            self.grid.insertRow(r)
            chk = QTableWidgetItem()
            chk.setFlags(self._check_flags(a['package'], self.core.config.protected))
            chk.setCheckState(Qt.Unchecked)
            chk.setData(Qt.UserRole, a['package'])
            name = QTableWidgetItem(a['name'])
            name.setData(Qt.UserRole, a['package'])
            pkg = QTableWidgetItem(a['package'])
            db = QTableWidgetItem(a['debloat'] or '')
            dark = kit.dark_from(self)
            pal = kit.colors(self)
            cat_pal = cat_colors_for(dark)
            if a['debloat_cat']:
                db.setForeground(QBrush(QColor(cat_pal.get(a['debloat_cat'], CAT_COLORS.get(a['debloat_cat'], pal['accent'])))))
                f = db.font()
                f.setBold(True)
                db.setFont(f)
                bloat += 1
            st = QTableWidgetItem(a['status'])
            run = QTableWidgetItem(a['running'])
            removed_u0 = not a.get('installed_user0', True)
            disabled = removed_u0 or not a.get('enabled', True)
            if removed_u0:
                en = QTableWidgetItem('Kaldirilmis')
            else:
                en = QTableWidgetItem('Evet' if a.get('enabled', True) else 'Hayir')
            if removed_u0:
                en.setForeground(QBrush(QColor(pal['accent'])))
                f_en = en.font()
                f_en.setBold(True)
                en.setFont(f_en)
                en.setToolTip('user 0 icin kaldirilmis; sag tik > Geri Yukle ile dondurulebilir')
            elif not a.get('enabled', True):
                en.setForeground(QBrush(QColor(pal['warning'])))
            prot = self.core.config.is_protected(a['package'])
            if prot:
                for it in (name, pkg, db, st, run, en):
                    it.setForeground(QBrush(QColor(pal['warning'])))
                name.setToolTip('Koruma listesinde (islem icin secilemez)')
                chk.setToolTip('Koruma listesinde (islem icin secilemez)')
            if a['status'] == 'Kisitli':
                st.setForeground(QBrush(QColor(pal['danger'])))
                f = st.font()
                f.setBold(True)
                st.setFont(f)
                lim += 1
            else:
                st.setForeground(QBrush(QColor(pal['success'])))
                free += 1
            if disabled:
                # Kaldirilmis / devre disi: ad + paket satiri ustu cizili ve soluk
                for it in (name, pkg):
                    fnt = it.font()
                    fnt.setStrikeOut(True)
                    it.setFont(fnt)
                    it.setForeground(QBrush(QColor(pal['faint'])))
                name.setToolTip('Kaldirilmis: {} — sag tik > Geri Yukle ile dondurulebilir'.format(
                    a['package']) if removed_u0 else 'Devre disi: {}'.format(a['package']))
            for it in (name, pkg, db, st, run, en):
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.grid.setItem(r, COL_CHECK, chk)
            self.grid.setItem(r, COL_NAME, name)
            self.grid.setItem(r, COL_PKG, pkg)
            self.grid.setItem(r, COL_STATUS, st)
            self.grid.setItem(r, COL_RUNNING, run)
            self.grid.setItem(r, COL_DEBLOAT, db)
            self.grid.setItem(r, COL_ENABLED, en)
        self.grid.blockSignals(False)
        suffix = ('  |  ({} kaldirilmis gizli — "Kaldirilmis" secenegiyle goster)'.format(
            removed_hidden) if removed_hidden else '')
        self.lbl_summary.setText(
            'Gosterilen: {}  |  Serbest: {}  |  Kisitli: {}  |  Kaldirilmis: {}  |  Debloat DB de: {}{}'.format(
                self.grid.rowCount(), free, lim, removed, bloat, suffix))
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
        self._update_sel_count()
        # baslik gostergesi: tamami seciliyse ☑, kismi ☐
        try:
            hdr_item = self.grid.horizontalHeaderItem(COL_CHECK)
            if hdr_item is not None:
                hdr_item.setText('☑ Sec' if on else 'Sec')
        except RuntimeError:
            pass

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
            selected = {ix.row() for ix in self.grid.selectedIndexes()}
            rows = checked or selected
            self.lbl_sel.setText('Secili: {}/{}{}'.format(
                len(rows), self.grid.rowCount(),
                ' (satir)' if selected and not checked else ''))
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    def _bulk_restrict(self, restrict):
        from .dialogs import confirm_action
        pkgs = self._selected_packages()
        if not pkgs:
            QMessageBox.information(self, 'Secim', 'Once uygulamalari secin (satir secimi de olur).')
            return
        prot = [p for p in pkgs if self.core.config.is_protected(p)]
        if prot and len(prot) == len(pkgs):
            names = '\n'.join(u'• {}'.format(self.core.config.friendly_name(p)) for p in prot[:10])
            QMessageBox.warning(
                self, 'Koruma',
                u'Seçilenlerin TAMAMI koruma listesinde; işlem yapılmadı:\n\n{}'.format(names))
            return
        if not confirm_action(self, 'restrict' if restrict else 'unrestrict',
                              pkgs, self.core.config.friendly_name):
            return
        w = BulkActionWorker(self.core.engine, self.core.target, pkgs,
                             restrict, self.core.config.protected)
        w.progress.connect(self._on_progress)
        w.finished_ok.connect(self._on_bulk_done)
        try:
            self.window.set_last_action(
                '{} uygulamaya {}: {} paket'.format(
                    len(pkgs), 'Kisitla' if restrict else 'Serbest Birak',
                    ', '.join(pkgs[:3]) + ('…' if len(pkgs) > 3 else '')))
        except Exception:
            pass
        self.window._run(w, on_ok=lambda _: self.refresh())

    def _on_bulk_done(self, res):
        if isinstance(res, dict):
            details = res.get('details', [])
            lines = ['{} basarili, {} atlandi.'.format(res.get('ok', 0), res.get('skip', 0))]
            for pkg, good, msg in details[:60]:
                name = self.core.config.friendly_name(pkg)
                disp = '{} ({})'.format(name, pkg) if name != pkg else pkg
                lines.append('{} {}: {}'.format('+' if good else 'X', disp, msg))
            if len(details) > 60:
                lines.append('… {} uygulama daha.'.format(len(details) - 60))
            QMessageBox.information(self, 'Tamam', '\n'.join(lines))
        else:
            try:
                ok, skip = res
            except Exception:
                ok, skip = res, '?'
            QMessageBox.information(self, 'Tamam',
                                    '{} basarili, {} atlandi.'.format(ok, skip))

    def _pkg_action(self, action):
        from .dialogs import confirm_action
        pkgs = self._selected_packages()
        if not pkgs:
            QMessageBox.information(self, 'Secim', 'Once uygulama secin.')
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
            QMessageBox.information(self, 'Secim', 'Once APK yedeklenecek uygulamalari secin.')
            return
        import os
        os.makedirs(APK_DIR, exist_ok=True)
        w = ApkBackupWorker(self.core.engine, self.core.target, pkgs, APK_DIR)
        w.progress.connect(self._on_progress)
        w.finished_ok.connect(self._on_backup_done)
        self.window._run(w)

    def _on_backup_done(self, res):
        QMessageBox.information(
            self, 'Tamam',
            '{} APK yedeklendi, {} basarisiz.\nKlasor: {}'.format(
                res.get('ok', 0), res.get('fail', 0), APK_DIR))

    def _export_csv(self):
        if not self._apps:
            QMessageBox.information(self, 'Aktar', 'Once listeyi yenileyin.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'CSV Kaydet', 'mibox-uygulamalar.csv',
                                              'CSV (*.csv)')
        if not path:
            return
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(['Ad', 'Paket', 'Durum', 'Calisiyor', 'Debloat', 'Aktif'])
                for row in range(self.grid.rowCount()):
                    w.writerow([self.grid.item(row, c).text() if self.grid.item(row, c) else ''
                                for c in (COL_NAME, COL_PKG, COL_STATUS, COL_RUNNING,
                                          COL_DEBLOAT, COL_ENABLED)])
            QMessageBox.information(self, 'Tamam', 'Aktarildi:\n' + path)
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
        txt.setPlainText('Yukleniyor...')
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
                'Ilk kurulum: {}\nSon guncelleme: {}\nAktif: {}\nVeri boyutu: {}\n'
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
        en_cell = self.grid.item(row, COL_ENABLED)
        if en_cell and en_cell.text() == 'Kaldirilmis':
            removed = True
        if removed:
            act = menu.addAction('Geri Yukle (onerilen)')
            f = act.font()
            f.setBold(True)
            act.setFont(f)
            act.triggered.connect(lambda: self._pkg_action_single('restore', p))
            menu.addSeparator()
        menu.addAction('Kisitla', lambda: self._ctx_action([p], 'restrict'))
        menu.addAction('Serbest Birak', lambda: self._ctx_action([p], 'unrestrict'))
        menu.addSeparator()
        menu.addAction('Detay', lambda: self._show_detail(p))
        menu.addAction('Ac', lambda: self._pkg_action_single('launch', p))
        menu.addAction('Force Stop', lambda: self._pkg_action_single('stop', p))
        menu.addAction('Veriyi Sil', lambda: self._pkg_action_single('clear', p))
        menu.addAction('Devre disi birak', lambda: self._pkg_action_single('disable', p))
        menu.addAction('Aktif et', lambda: self._pkg_action_single('enable', p))
        menu.addAction('Kaldir (user)', lambda: self._pkg_action_single('uninstall', p))
        menu.addAction('Geri Yukle', lambda: self._pkg_action_single('restore', p))
        menu.addAction('APK Yedekle', lambda: self._backup_apk())
        menu.addAction('Favorilere Ekle (Debloat)', lambda: self._add_favorite(p))
        menu.exec(self.grid.viewport().mapToGlobal(pos))

    def _add_favorite(self, pkg):
        from ..debloat_db import add_user_entry
        # cihazdan gelen ad; yoksa paket (bilinen-liste yok)
        name = next((a.get('name', '') for a in self._apps
                     if a['package'] == pkg), '') or pkg
        if add_user_entry(pkg, name, 'Kullanici favorisi'):
            QMessageBox.information(self, 'Favori', pkg + ' favorilere eklendi.')
            try:
                self.window.tab_debloat.reload()
            except Exception:
                pass
        else:
            QMessageBox.information(self, 'Favori', pkg + ' zaten listede.')

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

    def _ctx_action(self, pkgs, kind):
        w = BulkActionWorker(self.core.engine, self.core.target, pkgs,
                             kind == 'restrict', self.core.config.protected)
        w.progress.connect(self._on_progress)
        w.finished_ok.connect(self._on_bulk_done)
        self.window._run(w, on_ok=lambda _: self.refresh())
