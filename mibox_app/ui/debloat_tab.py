# -*- coding: utf-8 -*-
"""Debloat sekmesi: kategorili bloatware listesi + toplu kaldirma/geri yukleme."""
import csv

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QMessageBox,
    QComboBox, QLineEdit, QFileDialog, QInputDialog, QSizePolicy,
    QMenu, QToolButton,
)

from ..debloat_db import (all_categories, CAT_COLORS, add_user_entry, remove_user_entry,
                            uad_removal_of, uad_list_of, needed_by, REMOVAL_TR,
                            REMOVAL_COLOR, CAT_LABELS)
from ..profiles import PROFILES, profile_summary, validate_profile
from .theme import cat_colors_for, removal_colors_for
from ..workers import CancelledError, PackageActionWorker, Worker
from . import kit
from .flowlayout import FlowLayout

COL_CHECK = 0
COL_NAME = 1
COL_PKG = 2
COL_DESC = 3
COL_PRESENT = 4
COL_STATE = 5
COL_UAD = 6
COL_SAFETY = 7


class DebloatTab(QWidget):
    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._present = set()
        self._disabled = set()
        self._uninstalled = set()
        self._entries = []
        # Varlik bilinmiyor (hic tarama yapilmadi) vs bos ayırımı:
        # False iken liste GOSTERILMEZ (uydurma yok), otomatik tarama baslar.
        self._presence_known = False
        self._presence_scanning = False
        self._presence_generation = 0
        self._presence_worker = None
        self._presence_target = None
        self.core.connection_changed.connect(self._connection_changed)
        self._build()

    def _connection_changed(self, connected, target):
        """Invalidate device presence whenever the active connection changes."""
        self._invalidate_presence_scan()
        self._present.clear()
        self._disabled.clear()
        self._presence_known = False
        self._presence_target = target if connected else None
        self.btn_scan.setEnabled(True)
        self._update_presence_label()
        if connected:
            self.lbl_summary.setText('Cihaz varlığı bilinmiyor — tarama bekleniyor...')
            kit.empty_state(self.grid, 'Cihaz taranıyor',
                            'Paket listesi tarama tamamlandığında gösterilecek.')
        else:
            self._reload()

    def _invalidate_presence_scan(self):
        self._presence_generation += 1
        worker, self._presence_worker = self._presence_worker, None
        self._presence_scanning = False
        if worker is not None:
            try:
                worker.cancel()
            except (AttributeError, RuntimeError):
                pass

    def _presence_context_current(self, worker, engine, target, generation):
        try:
            return (self._presence_worker is worker
                    and self._presence_target == target
                    and self._presence_generation == generation
                    and getattr(worker, '_presence_user_id', 0)
                    == int(self.core.config.user_id or 0)
                    and self.core.connected
                    and self.core.target == target
                    and self.core.engine is engine)
        except Exception:
            return False

    def _finish_presence_worker(self, worker):
        """Release only this scan's retained state; stale workers cannot clear newer ones."""
        if self._presence_worker is not worker:
            return
        self._presence_worker = None
        self._presence_scanning = False
        self.btn_scan.setEnabled(True)
        self._update_presence_label()

    def _capture_mutation_context(self, title):
        if not getattr(self.core, 'connected', False):
            QMessageBox.warning(self, title, 'Önce bir cihaza bağlanın.')
            return None
        try:
            return self.core.engine, self.core.target, self._presence_generation
        except Exception as error:
            QMessageBox.warning(self, title, 'Cihaz bağlantısı doğrulanamadı: {}'.format(error))
            return None

    def _mutation_context_current(self, context):
        if context is None:
            return False
        engine, target, generation = context
        try:
            return (self.core.connected and self.core.target == target
                    and self._presence_generation == generation
                    and self.core.engine is engine)
        except Exception:
            return False

    def _revalidate_mutation_context(self, context, title):
        if self._mutation_context_current(context):
            return True
        QMessageBox.warning(
            self, title,
            'Bağlantı, hedef veya cihaz paket bilgisi değişti. İşlem başlatılmadı; yeniden deneyin.')
        return False

    def _build(self):
        root = kit.page(self)

        filter_box = kit.section('Paket listesi')
        filter_layout = QVBoxLayout(filter_box)
        filter_layout.setContentsMargins(10, 14, 10, 8)
        filter_layout.setSpacing(3)
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        self.cmb_cat = QComboBox()
        self.cmb_cat.setMinimumWidth(190)
        self.cmb_cat.setMaximumWidth(260)
        self.cmb_cat.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.cmb_cat.setSizeAdjustPolicy(QComboBox.AdjustToContentsOnFirstShow)
        self.cmb_cat.setToolTip('Debloat kategori filtresi')
        self._fill_categories()
        self.cmb_cat.currentIndexChanged.connect(self._reload)

        self.txt_search = QLineEdit()
        self.txt_search.setMinimumWidth(100)
        self.txt_search.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.txt_search.setPlaceholderText('Paketlerde ara...')
        self.txt_search.textChanged.connect(self._reload)

        self.lbl_presence = QLabel('Cihaz: bekleniyor')
        self.lbl_presence.setWordWrap(True)
        self.lbl_presence.setStyleSheet(kit.faint(kit.dark_from(self)))
        self.btn_scan = QPushButton('Varlığı Tara')
        self.btn_scan.clicked.connect(self._scan_presence)
        self.btn_advanced = QToolButton()
        self.btn_advanced.setText('Gelişmiş')
        self.btn_advanced.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_advanced.setArrowType(Qt.RightArrow)
        self.btn_advanced.setCheckable(True)

        self.cmb_removal = QComboBox()
        self.cmb_removal.setMinimumWidth(180)
        self.cmb_removal.setMaximumWidth(230)
        self.cmb_removal.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.cmb_removal.setSizeAdjustPolicy(QComboBox.AdjustToContentsOnFirstShow)
        self.cmb_removal.addItem('Seviye: Tümü', '')
        for lvl in ('Recommended', 'Advanced', 'Expert', 'Unsafe'):
            self.cmb_removal.addItem('{} ({})'.format(REMOVAL_TR[lvl], lvl), lvl)
        self.cmb_removal.currentIndexChanged.connect(self._reload)
        self.cmb_ulist = QComboBox()
        self.cmb_ulist.setMinimumWidth(150)
        self.cmb_ulist.setMaximumWidth(190)
        self.cmb_ulist.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.cmb_ulist.setSizeAdjustPolicy(QComboBox.AdjustToContentsOnFirstShow)
        self.cmb_ulist.addItem('Kaynak: Tümü', '')
        for lst in ('Google', 'Oem', 'Misc', 'Aosp', 'Carrier'):
            self.cmb_ulist.addItem(lst, lst)
        self.cmb_ulist.currentIndexChanged.connect(self._reload)
        self.chk_unlisted = kit.CheckBox('Listesiz (unlisted)')
        try:
            self.chk_unlisted.setChecked(bool(self.core.config.show_unlisted))
        except AttributeError:
            self.core.config.show_unlisted = False
        self.chk_unlisted.setToolTip('UAD unlisted filtresi: DB de olmayan cihaz paketlerini gosterir')
        self.chk_unlisted.toggled.connect(self._unlisted_toggle)

        self.cmb_user = QComboBox()
        self.cmb_user.setMinimumWidth(150)
        self.cmb_user.setMaximumWidth(200)
        self.cmb_user.setToolTip('İşlem uygulanacak Android kullanıcısı (UAD multi-user)')
        saved_user_id = int(self.core.config.user_id or 0)
        if saved_user_id:
            self.cmb_user.addItem(
                'Kullanıcı: {} (kayıtlı; adını bulmak için tara)'.format(saved_user_id),
                saved_user_id)
        else:
            self.cmb_user.addItem('Kullanıcı: Owner (0)', 0)
        self.cmb_user.currentIndexChanged.connect(self._user_changed)
        self.btn_users = QPushButton('Kullanıcıları Tara')
        self.btn_users.clicked.connect(self._scan_users)

        row1.addWidget(QLabel('Kategori:'))
        row1.addWidget(self.cmb_cat)
        row1.addWidget(self.txt_search, 1)
        row1.addWidget(self.btn_scan)
        row1.addWidget(self.btn_advanced)
        filter_layout.addLayout(row1)
        filter_layout.addWidget(self.lbl_presence)

        self.advanced_filters = QWidget()
        advanced_row = FlowLayout(self.advanced_filters, margin=0, hspacing=4, vspacing=4)
        for widget in (self.cmb_removal, self.cmb_ulist, self.chk_unlisted,
                       self.cmb_user, self.btn_users):
            advanced_row.addWidget(widget)
        self.advanced_filters.hide()
        filter_layout.addWidget(self.advanced_filters)
        self.btn_advanced.toggled.connect(self._toggle_advanced_filters)
        # Match the table width; the search field uses the remaining row space.
        root.addWidget(filter_box)

        self.btn_sel_export = QPushButton('Seçimi Dışa Aktar')
        self.btn_sel_export.setToolTip('UAD uad_exported_selection.txt biçimi')
        self.btn_sel_export.clicked.connect(self._export_selection)
        self.btn_sel_import = QPushButton('Seçimi İçe Aktar')
        self.btn_sel_import.clicked.connect(self._import_selection)

        self.lbl_hint = QLabel(
            'Yalnızca cihazda kurulu paketler listelenir; kritik ve korumalı paketler seçilemez.')
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet(kit.muted(kit.dark_from(self)))
        root.addWidget(self.lbl_hint)

        self.grid = kit.make_table(
            8, ['Seç', 'Uygulama', 'Paket', 'Açıklama', 'Cihazda', 'Durum',
                'UAD', 'Güvenlik'])
        self.grid.setMinimumHeight(220)
        hdr = self.grid.horizontalHeader()
        hdr.setSectionResizeMode(COL_PKG, QHeaderView.Stretch)
        hdr.setSectionResizeMode(COL_DESC, QHeaderView.Stretch)
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.Fixed)
        self.grid.setColumnWidth(COL_NAME, 190)
        hdr.setSectionResizeMode(COL_CHECK, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_PRESENT, QHeaderView.Fixed)
        self.grid.setColumnWidth(COL_PRESENT, 64)
        hdr.setSectionResizeMode(COL_STATE, QHeaderView.Fixed)
        self.grid.setColumnWidth(COL_STATE, 88)
        hdr.setSectionResizeMode(COL_UAD, QHeaderView.Fixed)
        self.grid.setColumnWidth(COL_UAD, 140)
        hdr.setSectionResizeMode(COL_SAFETY, QHeaderView.Fixed)
        self.grid.setColumnWidth(COL_SAFETY, 112)
        self.grid.itemChanged.connect(lambda _it: self._update_sel_count())
        self.grid.itemSelectionChanged.connect(self._update_sel_count)
        root.addWidget(self.grid, 1)

        self.chk_all = QPushButton('Tümü Seç')
        self.chk_all.clicked.connect(lambda: self._toggle_all(True))
        self.chk_none = QPushButton('Seçimi Kaldır')
        self.chk_none.clicked.connect(lambda: self._toggle_all(False))
        self.chk_inv = QPushButton('Ters Çevir')
        self.chk_inv.clicked.connect(self._invert_all)
        self.lbl_sel = QLabel('')
        self.lbl_sel.setAlignment(Qt.AlignCenter)
        self.lbl_sel.setMinimumWidth(90)
        self.lbl_sel.setStyleSheet(kit.faint(kit.dark_from(self)))
        self.btn_smart = QPushButton('Akilli Kaldır')
        self.btn_smart.setProperty('accent', True)
        self.btn_smart.setToolTip('Önce devre dışı birakir, olmazsa kaldirir (UAD yontemi)')
        self.btn_smart.clicked.connect(lambda: self._bulk('smart'))
        self.btn_remove = QPushButton('Kaldır (user)')
        self.btn_remove.setProperty('danger', True)
        self.btn_remove.clicked.connect(lambda: self._bulk('uninstall'))
        self.btn_disable = QPushButton('Devre dışı')
        self.btn_disable.clicked.connect(lambda: self._bulk('disable'))
        self.btn_restore = QPushButton('Geri Yükle')
        self.btn_restore.setProperty('accent', True)
        self.btn_restore.clicked.connect(lambda: self._bulk('restore'))
        self.btn_addfav = QPushButton('Favori Ekle')
        self.btn_addfav.clicked.connect(self._add_favorite_dialog)
        self.btn_rmfav = QPushButton('Favoriden Cikar')
        self.btn_rmfav.clicked.connect(self._remove_favorite_selected)
        self.btn_export = QPushButton('CSV Aktar')
        self.btn_export.clicked.connect(self._export_csv)

        self.lbl_stage = QLabel('Sahne: 0 işlem')
        self.lbl_stage.setStyleSheet(kit.title(kit.dark_from(self)))
        self.btn_stage_add_disable = QPushButton('Seçiliyi Sahneye: Devre dışı')
        self.btn_stage_add_disable.clicked.connect(lambda: self._stage_add('disable'))
        self.btn_stage_add_uninstall = QPushButton('Seçiliyi Sahneye: Kaldır')
        self.btn_stage_add_uninstall.clicked.connect(lambda: self._stage_add('uninstall'))
        self.btn_stage_show = QPushButton('Sahneyi Önizle/Uygula')
        self.btn_stage_show.clicked.connect(self._stage_show)
        self.btn_stage_clear = QPushButton('Sahneyi Temizle')
        self.btn_stage_clear.clicked.connect(self._stage_clear)
        self.btn_select_menu = QToolButton()
        self.btn_select_menu.setText('Seçim')
        self.btn_select_menu.setPopupMode(QToolButton.InstantPopup)
        select_menu = QMenu(self.btn_select_menu)
        for label, button in (('Tümünü seç', self.chk_all),
                              ('Seçimi kaldır', self.chk_none),
                              ('Ters çevir', self.chk_inv)):
            action = select_menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, target=button: target.click())
        self.btn_select_menu.setMenu(select_menu)

        self.btn_other = QToolButton()
        self.btn_other.setText('Diğer işlemler')
        self.btn_other.setPopupMode(QToolButton.InstantPopup)
        other_menu = QMenu(self.btn_other)

        def add_button_action(menu, button):
            action = menu.addAction(button.text())
            action.setToolTip(button.toolTip())
            action.triggered.connect(
                lambda _checked=False, target=button: target.click())

        other_menu.addSection('Seçim ve dışa aktarma')
        for button in (self.btn_sel_export, self.btn_sel_import, self.btn_export):
            add_button_action(other_menu, button)
        other_menu.addSection('Paket işlemleri')
        for button in (self.btn_remove, self.btn_addfav, self.btn_rmfav):
            add_button_action(other_menu, button)
        other_menu.addSection('Sahne')
        for button in (self.btn_stage_add_disable, self.btn_stage_add_uninstall,
                       self.btn_stage_clear):
            add_button_action(other_menu, button)
        other_menu.addSection('Hazır debloat profilleri')
        for key, profile in PROFILES.items():
            action = other_menu.addAction(profile['label'])
            action.setToolTip(profile_summary(key))
            action.triggered.connect(
                lambda _checked=False, profile_key=key:
                    self._apply_profile(profile_key))
        self.btn_other.setMenu(other_menu)

        hidden_buttons = (
            self.chk_all, self.chk_none, self.chk_inv, self.btn_sel_export,
            self.btn_sel_import, self.btn_remove, self.btn_addfav,
            self.btn_rmfav, self.btn_export, self.btn_stage_add_disable,
            self.btn_stage_add_uninstall, self.btn_stage_clear,
        )
        for button in hidden_buttons:
            button.setParent(self)
            button.hide()

        actions = FlowLayout(margin=0, hspacing=4, vspacing=4)
        for widget in (self.btn_select_menu, self.lbl_sel, self.btn_smart,
                       self.btn_disable, self.btn_restore, self.lbl_stage,
                       self.btn_stage_show, self.btn_other):
            actions.addWidget(widget)
        root.addLayout(actions)

        self.lbl_summary = kit.status_label('Cihaz varlığı bilinmiyor — taranıyor...')
        root.addWidget(self.lbl_summary)
        kit.empty_state(self.grid, 'Cihaz uygulamaları bekleniyor',
                        'Bağlı cihaz tarandıktan sonra seçilen kategorideki kurulu paketler görünür.')
        # _presence bilinmiyor -> _reload bos gosterir + otomatik tarama baslar
        self._reload()

    def _toggle_advanced_filters(self, expanded):
        self.advanced_filters.setVisible(bool(expanded))
        self.btn_advanced.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

    def _update_presence_label(self):
        if not getattr(self.core, 'connected', False):
            text = 'Cihaz: bağlı değil'
        elif self._presence_scanning:
            text = 'Cihaz: taranıyor…'
        elif self._presence_known:
            text = 'Cihaz: {} paket kurulu'.format(len(self._present))
        else:
            text = 'Cihaz: bilinmiyor'
        self.lbl_presence.setText(text)

    def _fill_categories(self):
        self.cmb_cat.blockSignals(True)
        self.cmb_cat.clear()
        self.cmb_cat.addItem('Tümü', 'all')
        for key, label, _ in all_categories():
            self.cmb_cat.addItem(label, key)
        self.cmb_cat.blockSignals(False)

    def reload(self):
        self._fill_categories()
        self._reload()

    def apply_theme(self):
        """Tema degisince: etiketler + tablo on renkleri yeni palete gecer."""
        try:
            dark = kit.dark_from(self)
            self.lbl_hint.setStyleSheet(kit.muted(dark))
            self.lbl_presence.setStyleSheet(kit.faint(dark))
            self.lbl_sel.setStyleSheet(kit.faint(dark))
            self.lbl_stage.setStyleSheet(kit.title(dark))
        except (RuntimeError, AttributeError):
            return
        try:
            self._reload()
        except (RuntimeError, AttributeError):
            pass
        except Exception:
            pass

    def _is_protected(self, pkg):
        checker = getattr(self.core.config, 'is_protected', None)
        if callable(checker):
            return bool(checker(pkg))
        return pkg in getattr(self.core.config, 'protected', ())

    # ------------------------------------------------------------------
    def _reload(self):
        # YALNIZCA-CIHAZ MODU: varlık bilinmiyorsa liste BOŞ gösterilir,
        # arka planda otomatik varlık taraması başlar. '?'/'Yok' uydurma yok.
        if not self._presence_known:
            self.grid.setRowCount(0)
            self._entries = []
            self._update_presence_label()
            # Bagli degilken ADB'ye dokunma: sadece bekle mesaji.
            # Baglanti kurulunca main_window otomatik cagirir (scan_if_needed).
            if self.core.connected:
                self.lbl_summary.setText('Cihaz varlığı bilinmiyor — taranıyor...')
                kit.empty_state(self.grid, 'Cihaz taranıyor',
                                'Paket listesi tarama tamamlandığında gösterilecek.')
                if not self._presence_scanning:
                    self._scan_presence()
            else:
                self.btn_scan.setEnabled(True)
                self.lbl_summary.setText('Bağlı cihaz yok — bağlanınca cihaz uygulamaları listelenecek.')
                kit.empty_state(self.grid, 'Bağlı cihaz yok',
                                'Debloat listesi yalnızca bağlı cihazda kurulu paketleri gösterir.')
            return
        cat = self.cmb_cat.currentData() or 'guvenli'
        q = self.txt_search.text().strip().lower()
        removal_f = self.cmb_removal.currentData() or ''
        ulist_f = self.cmb_ulist.currentData() or ''
        show_unlisted = self.chk_unlisted.isChecked()
        entries = []
        categories = all_categories()
        for key, _label, items in categories:
            if cat == 'all' or key == cat:
                entries.extend((pkg, name, desc, key)
                               for pkg, name, desc in items)
        if cat == 'all':
            # Favori kaydı, veritabanındaki güvenlik kategorisini değiştiremez.
            unique = {}
            for entry in entries:
                unique.setdefault(entry[0], entry)
            entries = list(unique.values())
        if show_unlisted:
            # UAD 'unlisted': SADECE cihazda kurulu ama DB de olmayanlar.
            # _present disinda hicbir paket uretilmez (uydurma yok).
            known = set()
            for _k, _l, items2 in all_categories():
                for p, _n, _d in items2:
                    known.add(p)
            for p in sorted(self._present):
                if p not in known:
                    entries.append((p, p.rsplit('.', 1)[-1].replace('.', ' '),
                                    'Listesiz — cihazda kurulu, veritabanında yok', None))
        # YALNIZCA-CIHAZ: cihazda olmayan hicbir satir gosterilmez.
        entries = [e for e in entries if e[0] in self._present]
        self._entries = entries
        self.grid.setRowCount(0)
        shown = 0
        for pkg, name, desc, entry_cat in entries:
            if q and q not in (name + ' ' + pkg + ' ' + desc).lower():
                continue
            # UAD filtreleri
            if ulist_f and uad_list_of(pkg) != ulist_f:
                continue
            if removal_f and uad_removal_of(pkg) != removal_f:
                continue
            r = self.grid.rowCount()
            self.grid.insertRow(r)
            critical = (entry_cat == 'dokunma')
            protected = self._is_protected(pkg)
            chk = QTableWidgetItem()
            if critical or protected:
                chk.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if protected:
                    chk.setToolTip('Koruma listesinde: işlem için seçilemez')
                else:
                    chk.setToolTip('Kritik sistem paketi: işlem için seçilemez')
            else:
                chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Unchecked)
            chk.setData(Qt.UserRole, pkg)
            nm = QTableWidgetItem(name)
            nm.setToolTip(name)
            pk = QTableWidgetItem(pkg)
            pk.setToolTip(pkg)
            ds = QTableWidgetItem(desc)
            ds.setToolTip(desc)
            present = pkg in self._present
            # Varlik bilinmiyorsa '?' — bu noktaya zaten ulasilmaz
            # (_reload bastan engeller), savunma amaçlı bırakıldı.
            pr = QTableWidgetItem('Evet' if present else (
                'Hayir' if self._presence_known else '?'))
            dark = kit.dark_from(self)
            pal = kit.colors(self)
            cat_pal = cat_colors_for(dark)
            rem_pal = removal_colors_for(dark)
            if present:
                pr.setForeground(QBrush(QColor(pal['success'])))
            # durum: kaldirilmis / devre disi / kurulu
            if pkg in self._uninstalled or (self._presence_known and pkg not in self._present):
                state_txt, state_color = 'Kaldirilmis', pal['accent']
            elif pkg in self._disabled:
                state_txt, state_color = 'Devre dışı', pal['warning']
            elif present:
                state_txt, state_color = 'Kurulu', pal['success']
            else:
                state_txt, state_color = (('Yok', pal['faint']) if self._presence_known
                                          else ('?', pal['faint']))
            st = QTableWidgetItem(state_txt)
            st.setForeground(QBrush(QColor(state_color)))
            # kategori rengi
            color = cat_pal.get(entry_cat, CAT_COLORS.get(entry_cat))
            if color and not critical:
                nm.setForeground(QBrush(QColor(color)))
            if critical:
                nm.setForeground(QBrush(QColor(pal['danger'])))
                f = nm.font()
                f.setBold(True)
                nm.setFont(f)
            elif protected:
                nm.setForeground(QBrush(QColor(pal['warning'])))
                nm.setToolTip('Koruma listesinde: işlem için seçilemez')
            safety_label = ('Dokunma (Kritik)' if entry_cat == 'dokunma'
                            else CAT_LABELS.get(entry_cat, 'Listesiz'))
            safety = QTableWidgetItem(safety_label)
            safety.setToolTip(
                '{}{}'.format(safety_label,
                              '\nKoruma listesinde: işlem için seçilemez'
                              if protected else ''))
            if color:
                safety.setForeground(QBrush(QColor(color)))
            if critical:
                safety.setForeground(QBrush(QColor(pal['danger'])))
                f = safety.font()
                f.setBold(True)
                safety.setFont(f)
            # UAD sutunu: removal seviyesi + kaynak listesi + bagimlilik uyari
            removal = uad_removal_of(pkg)
            ulist = uad_list_of(pkg)
            deps = needed_by(pkg)
            uad_txt = '{} / {}'.format(REMOVAL_TR.get(removal, removal), ulist)
            if deps:
                uad_txt += ' ⚠'
            uad_cell = QTableWidgetItem(uad_txt)
            uad_cell.setToolTip(uad_txt)
            uad_cell.setForeground(QBrush(QColor(rem_pal.get(removal, REMOVAL_COLOR.get(removal, pal['faint'])))))
            if deps:
                uad_cell.setToolTip('{}\nBUNA IHTIAC DUYANLAR: {}\n'
                                    '(Kaldırınca bunlar bozulabilir)'.format(
                                        uad_txt, ', '.join(deps)))
            uad_cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            for it in (nm, pk, ds, pr, st):
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.grid.setItem(r, COL_CHECK, chk)
            self.grid.setItem(r, COL_NAME, nm)
            self.grid.setItem(r, COL_PKG, pk)
            self.grid.setItem(r, COL_DESC, ds)
            self.grid.setItem(r, COL_PRESENT, pr)
            self.grid.setItem(r, COL_STATE, st)
            self.grid.setItem(r, COL_UAD, uad_cell)
            self.grid.setItem(r, COL_SAFETY, safety)
            shown += 1
        category_label = 'Tümü' if cat == 'all' else CAT_LABELS.get(cat, cat)
        self.lbl_summary.setText(
            '{}: {} / {} kurulu paket gösteriliyor; cihazda toplam {} paket kurulu.'.format(
                category_label, shown, len(entries), len(self._present)))
        self._update_presence_label()
        if shown:
            kit.empty_state(self.grid, 'Cihaz uygulamaları bekleniyor',
                            'Bağlı cihaz tarandıktan sonra seçilen kategorideki kurulu paketler görünür.')
        elif entries:
            kit.empty_state(self.grid, 'Eşleşen paket yok',
                            'Arama metnini veya seviye ve kaynak filtrelerini değiştirin.')
        else:
            kit.empty_state(self.grid, 'Bu kategoride kurulu paket yok',
                            'Başka bir kategori seçin veya cihaz paketlerini yeniden tarayın.')

    def _stage(self):
        if not hasattr(self.window, 'stage'):
            from .. import stage as stagemod
            self.window.stage = stagemod.Stage()
        return self.window.stage

    def _stage_refresh_label(self):
        self.lbl_stage.setText('Sahne: {} işlem'.format(self._stage().count()))

    def _stage_add(self, action):
        pkgs = self._selected_packages()
        if not pkgs:
            QMessageBox.information(self, 'Seçim', 'Önce paket seçin.')
            return
        n = self._stage().add_many(action, pkgs)
        self._stage_refresh_label()
        self.window.append_log('Sahneye eklendi: {} x {} ({} yeni)'.format(action, len(pkgs), n), 'INFO')

    def _stage_clear(self):
        self._stage().clear()
        self._stage_refresh_label()

    def _stage_show(self):
        from .stage_dialog import StageDialog
        from ..workers import StageWorker
        st = self._stage()
        if not st.count():
            QMessageBox.information(self, 'Sahne', 'Sahne boş. Önce işlem ekleyin.')
            return
        context = self._capture_mutation_context('Sahne')
        if context is None:
            return
        engine, target, _generation = context
        dlg = StageDialog(self, st, self.core.config.friendly_name)
        if dlg.exec() != dlg.Accepted:
            return
        if not self._revalidate_mutation_context(context, 'Sahne'):
            return
        w = StageWorker(engine, target, st.items(),
                        self.core.config.protected,
                        user_id=int(self.core.config.user_id or 0))
        w.finished_ok.connect(self._on_done)
        def on_ok(_result):
            if self._mutation_context_current(context):
                self._stage_clear()
                self._scan_presence()
        self.window._run(w, on_ok=on_ok)

    def _apply_profile(self, key):
        """Önizlemeli hazır profil işlemi; genel sahneden bağımsız çalışır."""
        profile = PROFILES.get(key)
        if profile is None:
            QMessageBox.warning(self, 'Hazır profil', 'Profil bulunamadı.')
            return

        context = self._capture_mutation_context('Hazır profil')
        if context is None:
            return
        _engine, target, _generation = context
        inventory_current = (self._presence_known
                             and self._presence_target == target)
        if self._presence_scanning:
            QMessageBox.information(
                self, 'Hazır profil',
                'Cihaz paket taraması sürüyor. Tarama tamamlandıktan sonra profili yeniden seçin.')
            return
        if not inventory_current:
            self._scan_presence()
            QMessageBox.information(
                self, 'Hazır profil',
                'Cihaz paket bilgisi güncel değil. Tarama başlatıldı; tamamlandıktan sonra profili yeniden seçin.')
            return

        clean, rejected = validate_profile(key)
        installed = []
        missing_count = 0
        protected_count = 0
        for pkg in clean:
            if pkg not in self._present:
                missing_count += 1
            elif self._is_protected(pkg):
                protected_count += 1
            else:
                installed.append(pkg)

        from ..stage import Stage
        stage = Stage()
        stage.add_many(profile['method'], installed)
        skipped_count = missing_count + protected_count
        profile_counts = (
            'Uygulanacak: {} paket · Atlanacak: {} '
            '(cihazda yok: {}, koruma listesinde: {}) · Reddedilen: {}'
            .format(stage.count(), skipped_count, missing_count,
                    protected_count, len(rejected)))

        if not stage.count():
            QMessageBox.information(
                self, 'Hazır profil',
                '{}\n\n{}'.format(profile_counts, profile_summary(key)))
            return

        from .stage_dialog import StageDialog
        from ..workers import StageWorker, format_action_result
        dialog = StageDialog(
            self, stage, self.core.config.friendly_name,
            description=profile_summary(key), summary=profile_counts)
        if dialog.exec() != dialog.Accepted:
            return
        if not self._revalidate_mutation_context(context, 'Hazır profil'):
            return

        engine, target, _generation = context
        user_id = int(self.core.config.user_id or 0)
        worker = StageWorker(
            engine, target, stage.items(), self.core.config.protected,
            user_id=user_id)

        def show_profile_result(result):
            applied_count = result.get('ok', 0) if isinstance(result, dict) else 0
            result_text = format_action_result(result, self._debloat_name)
            counts = (
                'Uygulandı: {} · Atlandı: {} '
                '(cihazda yok: {}, koruma listesinde: {}) · Reddedildi: {}'
                .format(applied_count, skipped_count, missing_count,
                        protected_count, len(rejected)))
            QMessageBox.information(
                self, 'Hazır profil sonucu',
                '{}\n\n{}'.format(counts, result_text))

        worker.finished_ok.connect(show_profile_result)
        self.window._run(
            worker, on_ok=lambda _result: self._scan_presence()
            if self._mutation_context_current(context) else None)

    def _toggle_all(self, on):
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
            self.lbl_sel.setText('Seçili: {}/{}{}'.format(
                len(rows), self.grid.rowCount(),
                ' (satir)' if selected and not checked else ''))
        except RuntimeError:
            pass

    def _selected_packages(self):
        out = []
        for row in range(self.grid.rowCount()):
            it = self.grid.item(row, COL_CHECK)
            if it and (it.flags() & Qt.ItemIsUserCheckable) and it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        if not out:
            for r in {i.row() for i in self.grid.selectedIndexes()}:
                it = self.grid.item(r, COL_CHECK)
                if it and (it.flags() & Qt.ItemIsUserCheckable):
                    out.append(it.data(Qt.UserRole))
        return out

    def _bulk(self, action):
        # Debloat adlarini DB aciklamasindan coz (dost ad yoksa paket).
        from .dialogs import confirm_action, ACTION_TR
        pkgs = self._selected_packages()
        if not pkgs:
            QMessageBox.information(self, 'Seçim', 'Önce paketleri seçin.')
            return
        cat = self.cmb_cat.currentData()
        package_categories = {}
        if cat == 'all':
            for key, _label, items in all_categories():
                for pkg, _name, _desc in items:
                    package_categories.setdefault(pkg, key)
            blocked = [p for p in pkgs
                       if package_categories.get(p) == 'dokunma'
                       or self._is_protected(p)]
            if blocked:
                QMessageBox.warning(
                    self, 'Paket işlemi',
                    'Kritik veya koruma listesindeki paketler işlemden çıkarıldı: {}'
                    .format(', '.join(blocked[:8])))
                pkgs = [p for p in pkgs if p not in blocked]
                if not pkgs:
                    return
        context = self._capture_mutation_context('Paket işlemi')
        if context is None:
            return
        engine, target, _generation = context
        user_id = int(self.core.config.user_id or 0)
        name_of = lambda p: self._debloat_name(p)
        label = ACTION_TR.get(action, action)
        # UAD bağımlılık uyarısı (auto-remove YOK, sadece uyar — UAD davranışı)
        dep_warn = []
        for p in pkgs:
            nb = needed_by(p)
            if nb:
                dep_warn.append('{} gerekli: {}'.format(p, ', '.join(nb)))
        if dep_warn:
            answer = QMessageBox.question(
                self, 'Bağımlılık Uyarısı',
                'Bazı paketlere BAŞKALARI ihtiyaç duyuyor (UAD neededBy):\n\n' +
                '\n'.join(dep_warn[:10]) +
                ('\n... ve {} tane daha'.format(len(dep_warn) - 10) if len(dep_warn) > 10 else '') +
                '\n\nYine de devam edilsin mi?')
            if not self._revalidate_mutation_context(context, 'Paket işlemi'):
                return
            if answer != QMessageBox.Yes:
                return
        # Risk politikasi (UAD onerisi): riskli kategoride uninstall YASAK,
        # yerine disable-oncelikli smart uygulanir.
        risk_pkgs = ([p for p in pkgs if package_categories.get(p) == 'riskli']
                     if cat == 'all' else [])
        if cat == 'all' and action == 'uninstall' and risk_pkgs:
            regular_pkgs = [p for p in pkgs if p not in risk_pkgs]
            if regular_pkgs:
                if not confirm_action(self, action, regular_pkgs, name_of):
                    return
                if not self._revalidate_mutation_context(context, 'Paket işlemi'):
                    return
            extra = ('RISKL kategori: Güvenlik politikasi geregi Kaldır yerine '
                     'önce Devre dışı denenir (Akilli Kaldır).')
            if not confirm_action(self, 'smart', risk_pkgs, name_of, extra):
                return
            if not self._revalidate_mutation_context(context, 'Paket işlemi'):
                return
            if regular_pkgs:
                worker = PackageActionWorker(
                    engine, target, regular_pkgs, action,
                    self.core.config.protected, user_id=user_id)
                worker.finished_ok.connect(self._on_done)
                def remove_risky_after_regular(result):
                    if (worker.isInterruptionRequested()
                            or not isinstance(result, dict) or result.get('cancelled')):
                        return
                    self._smart_remove(risk_pkgs, context, user_id)

                worker.finished_ok.connect(remove_risky_after_regular)
                self.window._run(worker)
            else:
                self._smart_remove(risk_pkgs, context, user_id)
            return
        if cat == 'all':
            if action in ('uninstall', 'disable', 'smart') and risk_pkgs:
                extra = 'RISKL kategori — sistem bozulabilir!'
                if not confirm_action(self, action, pkgs, name_of, extra):
                    return
                if not self._revalidate_mutation_context(context, 'Paket işlemi'):
                    return
            elif action in ('uninstall', 'disable', 'smart', 'restore'):
                if not confirm_action(self, action, pkgs, name_of):
                    return
                if not self._revalidate_mutation_context(context, 'Paket işlemi'):
                    return
        elif cat == 'riskli' and action == 'uninstall':
            extra = ('RISKL kategori: Güvenlik politikasi geregi Kaldır yerine '
                     'önce Devre dışı denenir (Akilli Kaldır).')
            if not confirm_action(self, 'smart', pkgs, name_of, extra):
                return
            if not self._revalidate_mutation_context(context, 'Paket işlemi'):
                return
            self._smart_remove(pkgs, context, user_id)
            return
        elif action in ('uninstall', 'disable', 'smart') and cat == 'riskli':
            extra = 'RISKL kategori — sistem bozulabilir!'
            if not confirm_action(self, action, pkgs, name_of, extra):
                return
            if not self._revalidate_mutation_context(context, 'Paket işlemi'):
                return
        elif action in ('uninstall', 'disable', 'smart', 'restore'):
            if not confirm_action(self, action, pkgs, name_of):
                return
            if not self._revalidate_mutation_context(context, 'Paket işlemi'):
                return
        if action == 'smart':
            self._smart_remove(pkgs, context, user_id)
            return
        if not self._revalidate_mutation_context(context, 'Paket işlemi'):
            return
        w = PackageActionWorker(engine, target, pkgs,
                                action, self.core.config.protected,
                                user_id=user_id)
        w.finished_ok.connect(self._on_done)
        self.window._run(
            w, on_ok=lambda _: self._scan_presence()
            if self._mutation_context_current(context) else None)

    def _debloat_name(self, pkg):
        """Debloat DB aciklamasindan kisa ad; yoksa paket."""
        try:
            for _k, _l, items in all_categories():
                for p, n, _d in items:
                    if p == pkg:
                        return n or pkg
        except Exception:
            pass
        return pkg

    def _smart_remove(self, pkgs, context, user_id):
        """Akilli kaldirma: her paket icin disable dene, olmazsa uninstall."""
        from ..workers import SmartRemoveWorker, format_action_result
        if not self._revalidate_mutation_context(context, 'Akıllı kaldırma'):
            return
        engine, target, _generation = context
        w = SmartRemoveWorker(engine, target, pkgs,
                              self.core.config.protected,
                              user_id=user_id)
        w.finished_ok.connect(self._on_done_smart)
        self.window._run(
            w, on_ok=lambda _: self._scan_presence()
            if self._mutation_context_current(context) else None)

    def _on_done_smart(self, res):
        from ..workers import format_action_result
        QMessageBox.information(self, 'Akilli Kaldırma',
                                format_action_result(res, self._debloat_name))

    def _on_done(self, res):
        from ..workers import format_action_result
        QMessageBox.information(self, 'Tamam',
                                format_action_result(res, self._debloat_name))

    def _unlisted_toggle(self, on):
        self.core.config.show_unlisted = bool(on)
        self.core.config.save()
        self._reload()

    def _user_changed(self, idx):
        if idx < 0:
            return
        user_id = int(self.cmb_user.itemData(idx) or 0)
        self._activate_user_id(user_id)

    def sync_user_id_from_config(self):
        """Synchronize imported user scope with the visible list and its scan."""
        user_id = int(self.core.config.user_id or 0)
        self.cmb_user.blockSignals(True)
        try:
            idx = self.cmb_user.findData(user_id)
            if idx < 0:
                label = ('Kullanıcı: Owner (0)' if user_id == 0 else
                         'Kullanıcı: {} (kayıtlı; adını bulmak için tara)'.format(user_id))
                self.cmb_user.insertItem(0, label, user_id)
                idx = 0
            self.cmb_user.setCurrentIndex(idx)
        finally:
            self.cmb_user.blockSignals(False)
        # The config object already contains the imported value. Force a fresh
        # scan even when it matches so stale package rows cannot remain active.
        self._activate_user_id(user_id, persist=False, force=True)

    def _activate_user_id(self, user_id, persist=True, force=False):
        if user_id == int(self.core.config.user_id or 0):
            if not force:
                return
        self._invalidate_presence_scan()
        self._present.clear()
        self._disabled.clear()
        self._presence_known = False
        self.core.config.user_id = user_id
        if persist and not self.core.config.save():
            self.window.append_log(
                'Kullanıcı tercihi bu oturumda uygulandı ancak ayarlara kaydedilemedi.',
                'WARN')
        self.window.append_log('İşlem kullanıcısı: user {}'.format(user_id), 'INFO')
        if getattr(self.core, 'connected', False):
            self._presence_target = self.core.target
            self.lbl_summary.setText(
                'user {} için paket varlığı taranıyor...'.format(user_id))
            self._scan_presence()
        else:
            self._presence_target = None
            self._reload()

    def _scan_users(self):
        if not getattr(self.core, 'connected', False) or not getattr(self.core, 'target', None):
            QMessageBox.information(self, 'Kullanıcılar', "Bağlı cihaz yok. Kullanıcıları listelemek için önce TV'ye bağlanın.")
            return
        engine, target = self.core.engine, self.core.target
        def do():
            engine.connect(target)
            return engine.list_users(target)
        w = Worker(do)
        w.finished_ok.connect(lambda users: self._show_users(users, target, engine))
        self.window._run(w)

    def _show_users(self, users, target=None, engine=None):
        if ((target is not None and self.core.target != target)
                or (engine is not None and self.core.engine is not engine)):
            return
        cur = int(self.core.config.user_id or 0)
        self.cmb_user.blockSignals(True)
        self.cmb_user.clear()
        for u in users:
            label = 'Kullanıcı: {} ({}){}'.format(u['name'], u['id'],
                                                 ' [çalışıyor]' if u.get('running') else '')
            self.cmb_user.addItem(label, u['id'])
        matching_index = next(
            (i for i in range(self.cmb_user.count())
             if self.cmb_user.itemData(i) == cur), None)
        if matching_index is None:
            self.core.config.user_id = 0
            cur = 0
            matching_index = next(
                (i for i in range(self.cmb_user.count())
                 if self.cmb_user.itemData(i) == 0), None)
            self.core.config.save()
        if matching_index is not None:
            self.cmb_user.setCurrentIndex(matching_index)
        self.cmb_user.blockSignals(False)
        self.window.append_log('{} kullanıcı bulundu.'.format(len(users)), 'INFO')
        if getattr(self.core, 'connected', False):
            self._invalidate_presence_scan()
            self._present.clear()
            self._disabled.clear()
            self._presence_known = False
            self._presence_target = self.core.target
            self._scan_presence()

    def _export_selection(self):
        """UAD uad_exported_selection.txt biçiminde seçimi dışa aktar."""
        pkgs = self._selected_packages()
        if not pkgs:
            QMessageBox.information(self, 'Seçim', 'Önce paket seçin.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Seçimi Dışa Aktar',
                                              'uad_exported_selection.txt', 'Metin (*.txt)')
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                for p in pkgs:
                    f.write(p + '\n')
            QMessageBox.information(self, 'Tamam',
                                    '{} paket aktarıldı (UAD uyumlu):\n{}'.format(len(pkgs), path))
        except OSError as e:
            QMessageBox.critical(self, 'Hata', str(e))

    def _import_selection(self):
        """UAD seçim dosyasını içe aktar, tabloda işaretle."""
        path, _ = QFileDialog.getOpenFileName(self, 'Seçimi İçe Aktar', '', 'Metin (*.txt)')
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                wanted = {l.strip() for l in f if l.strip() and not l.startswith('#')}
        except OSError as e:
            QMessageBox.critical(self, 'Hata', str(e))
            return
        # önce listeyi genişlet (unlisted dahil), sonra işaretle
        marked, missing = 0, []
        for row in range(self.grid.rowCount()):
            it = self.grid.item(row, COL_CHECK)
            if it and (it.flags() & Qt.ItemIsUserCheckable):
                pkg = it.data(Qt.UserRole)
                if pkg in wanted:
                    it.setCheckState(Qt.Checked)
                    marked += 1
        missing = sorted(w for w in wanted if not any(
            self.grid.item(r, COL_CHECK) and self.grid.item(r, COL_CHECK).data(Qt.UserRole) == w
            for r in range(self.grid.rowCount())))
        msg = '{} paket işaretlendi.'.format(marked)
        if missing:
            msg += '\nTabloda yok ({}): {}'.format(len(missing), ', '.join(missing[:10]))
        QMessageBox.information(self, 'İçe Aktar', msg)

    def _scan_presence(self):
        if not getattr(self.core, 'connected', False):
            if self._presence_worker is not None:
                self._invalidate_presence_scan()
            self._present.clear()
            self._disabled.clear()
            self._presence_known = False
            self._presence_target = None
            self.btn_scan.setEnabled(True)
            self._update_presence_label()
            self.lbl_summary.setText('Bağlı cihaz yok — bağlanınca paket varlığı taranabilir.')
            kit.empty_state(self.grid, 'Bağlı cihaz yok',
                            'Debloat listesi yalnızca bağlı cihazda kurulu paketleri gösterir.')
            return

        if self._presence_scanning:
            worker = self._presence_worker
            if worker is not None and self._presence_context_current(
                    worker, worker._presence_engine, worker._presence_target,
                    worker._presence_generation):
                return
            self._invalidate_presence_scan()

        try:
            engine, target = self.core.engine, self.core.target
        except Exception as error:
            self._on_presence_fail(str(error))
            return
        generation = self._presence_generation
        user_id = int(self.core.config.user_id or 0)
        self._presence_target = target
        worker_ref = {}

        def do():
            worker = worker_ref['worker']

            def check_context():
                if (worker.isInterruptionRequested()
                        or self._presence_generation != generation
                        or int(self.core.config.user_id or 0) != user_id
                        or not self.core.connected
                        or self.core.target != target
                        or self._presence_target != target
                        or self.core.engine is not engine):
                    raise CancelledError('connection changed')

            check_context()
            engine.connect(target)
            check_context()
            entries = engine.list_packages_detailed(
                target, include_system=True, use_cache=False, user_id=user_id)
            check_context()
            installed = [entry for entry in entries
                         if entry.get('installed_user0') is True]
            present = {entry['package'] for entry in installed}
            disabled = {entry['package'] for entry in installed
                        if entry.get('enabled') is False}
            return {'present': present, 'disabled': disabled}

        worker = Worker(do)
        worker_ref['worker'] = worker
        worker._presence_engine = engine
        worker._presence_target = target
        worker._presence_generation = generation
        worker._presence_user_id = user_id
        worker.job_name = 'Debloat varlik taramasi'
        self._presence_scanning = True
        self._presence_worker = worker
        self.btn_scan.setEnabled(False)
        self._update_presence_label()
        worker.finished_ok.connect(
            lambda result: self._presence_scan_succeeded(
                worker, engine, target, generation, result))
        worker.failed.connect(
            lambda error: self._presence_scan_failed(
                worker, engine, target, generation, error))
        worker.finished.connect(lambda: self._finish_presence_worker(worker))

        # The device may have changed while the worker and callbacks were being prepared.
        if not self._presence_context_current(worker, engine, target, generation):
            self._finish_presence_worker(worker)
            return
        try:
            self.window._run(worker, desc='Debloat: cihazda kurulu paketler taraniyor')
        except Exception as error:
            self._presence_scan_failed(worker, engine, target, generation, str(error))

    def _presence_scan_succeeded(self, worker, engine, target, generation, result):
        if not self._presence_context_current(worker, engine, target, generation):
            self._finish_presence_worker(worker)
            return
        try:
            self._set_present(result)
        finally:
            self._finish_presence_worker(worker)

    def _presence_scan_failed(self, worker, engine, target, generation, error):
        if not self._presence_context_current(worker, engine, target, generation):
            self._finish_presence_worker(worker)
            return
        try:
            self._on_presence_fail(error)
        finally:
            self._finish_presence_worker(worker)

    def _on_presence_fail(self, error):
        self._update_presence_label()
        self.lbl_summary.setText('Paket varlığı taranamadı: {}'.format(error))
        if not self._presence_known:
            kit.empty_state(self.grid, 'Paketler taranamadı',
                            'Bağlantıyı kontrol edip “Varlığı Tara” ile yeniden deneyin.')

    def _set_present(self, res):
        if isinstance(res, dict):
            self._present = set(res.get('present', ()))
            self._disabled = set(res.get('disabled', ()))
        else:
            self._present = set(res or [])
            self._disabled = set()
        self._presence_known = True
        self._reload()

    def set_present(self, pkgs):
        """Cihazdaki tum paketleri (Uygulamalar taramasindan) alir."""
        if not getattr(self.core, 'connected', False):
            self._invalidate_presence_scan()
            self._present.clear()
            self._disabled.clear()
            self._presence_known = False
            self._presence_target = None
            self.btn_scan.setEnabled(True)
            self._reload()
            return
        # AppScanWorker reports Owner/user 0. Do not let that cross-tab result
        # overwrite the Debloat tab's explicitly selected Android user.
        if int(self.core.config.user_id or 0) != 0:
            return
        self._invalidate_presence_scan()
        self._presence_target = self.core.target
        if isinstance(pkgs, dict):
            self._present = set(pkgs.get('present', ()))
            self._disabled = set(pkgs.get('disabled', ()))
        else:
            self._present = set(pkgs or [])
            if not hasattr(self, '_disabled'):
                self._disabled = set()
        self._presence_known = True
        self.btn_scan.setEnabled(True)
        self._reload()

    def scan_if_needed(self):
        """Baglanti sonrasi cagrilir: varlik bilinmiyorsa tara, varsa tazele."""
        if not self._presence_scanning:
            self._scan_presence()

    # --- favoriler ---
    def _add_favorite_dialog(self):
        pkg, ok = QInputDialog.getText(self, 'Favori Ekle', 'Paket adi:')
        if not ok or not pkg.strip():
            return
        pkg = pkg.strip()
        name, ok2 = QInputDialog.getText(self, 'Favori Ekle', 'Dost ad (opsiyonel):')
        if not ok2:
            return
        if add_user_entry(pkg, name.strip() or pkg, 'Kullanıcı favorisi'):
            self.reload()
        else:
            QMessageBox.information(self, 'Favori', 'Bu paket zaten listede.')

    def _remove_favorite_selected(self):
        if self.cmb_cat.currentData() != 'favoriler':
            QMessageBox.information(self, 'Favori', 'Önce "Favoriler" kategorisini seçin.')
            return
        pkgs = self._selected_packages()
        if not pkgs:
            QMessageBox.information(self, 'Seçim', 'Önce paket seçin.')
            return
        for p in pkgs:
            remove_user_entry(p)
        self.reload()

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, 'CSV Kaydet', 'mibox-debloat.csv', 'CSV (*.csv)')
        if not path:
            return
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(['Ad', 'Paket', 'Açıklama', 'Cihazda'])
                for row in range(self.grid.rowCount()):
                    w.writerow([self.grid.item(row, c).text() if self.grid.item(row, c) else ''
                                for c in (COL_NAME, COL_PKG, COL_DESC, COL_PRESENT)])
            QMessageBox.information(self, 'Tamam', 'Aktarıldı:\n' + path)
        except OSError as e:
            QMessageBox.critical(self, 'Hata', str(e))
