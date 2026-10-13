# -*- coding: utf-8 -*-
"""Debloat sekmesi: kategorili bloatware listesi + toplu kaldirma/geri yukleme."""
import csv

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QMessageBox,
    QComboBox, QCheckBox, QLineEdit, QFileDialog, QInputDialog, QSizePolicy,
)

from ..debloat_db import (all_categories, CAT_COLORS, add_user_entry, remove_user_entry,
                            uad_removal_of, uad_list_of, needed_by, REMOVAL_TR,
                            REMOVAL_COLOR, CAT_LABELS)
from .theme import cat_colors_for, removal_colors_for
from ..workers import PackageActionWorker, Worker
from . import kit
from .flowlayout import FlowLayout

COL_CHECK = 0
COL_NAME = 1
COL_PKG = 2
COL_DESC = 3
COL_PRESENT = 4
COL_STATE = 5
COL_UAD = 6


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
        self._build()

    def _build(self):
        root = kit.page(self)

        row1 = QHBoxLayout()
        row1.setSpacing(4)
        self.cmb_cat = QComboBox()
        self.cmb_cat.setMinimumWidth(250)
        self.cmb_cat.setMaximumWidth(280)
        self.cmb_cat.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.cmb_cat.setSizeAdjustPolicy(QComboBox.AdjustToContentsOnFirstShow)
        self.cmb_cat.setToolTip('Debloat kategori filtresi')
        self._fill_categories()
        self.cmb_cat.currentIndexChanged.connect(self._reload)
        self.cmb_removal = QComboBox()
        self.cmb_removal.setMinimumWidth(240)
        self.cmb_removal.setMaximumWidth(270)
        self.cmb_removal.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.cmb_removal.setSizeAdjustPolicy(QComboBox.AdjustToContentsOnFirstShow)
        self.cmb_removal.addItem('Seviye: Tümü', '')
        for lvl in ('Recommended', 'Advanced', 'Expert', 'Unsafe'):
            self.cmb_removal.addItem('{} ({})'.format(REMOVAL_TR[lvl], lvl), lvl)
        self.cmb_removal.currentIndexChanged.connect(self._reload)
        self.cmb_ulist = QComboBox()
        self.cmb_ulist.setMinimumWidth(200)
        self.cmb_ulist.setMaximumWidth(230)
        self.cmb_ulist.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.cmb_ulist.setSizeAdjustPolicy(QComboBox.AdjustToContentsOnFirstShow)
        self.cmb_ulist.addItem('Kaynak: Tümü', '')
        for lst in ('Google', 'Oem', 'Misc', 'Aosp', 'Carrier'):
            self.cmb_ulist.addItem(lst, lst)
        self.cmb_ulist.currentIndexChanged.connect(self._reload)
        self.chk_installed = QCheckBox('Sadece kurulu')
        self.chk_installed.toggled.connect(self._reload)
        self.chk_unlisted = QCheckBox('Listesiz (unlisted)')
        try:
            self.chk_unlisted.setChecked(bool(self.core.config.show_unlisted))
        except AttributeError:
            self.core.config.show_unlisted = False
        self.chk_unlisted.setToolTip('UAD unlisted filtresi: DB de olmayan cihaz paketlerini gosterir')
        self.chk_unlisted.toggled.connect(self._unlisted_toggle)
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText('Ara...')
        self.txt_search.textChanged.connect(self._reload)
        row1.addWidget(QLabel('Kategori:'))
        row1.addWidget(self.cmb_cat)
        row1.addWidget(self.cmb_removal)
        row1.addWidget(self.cmb_ulist)
        row1.addWidget(self.chk_installed)
        row1.addWidget(self.chk_unlisted)
        row1.addWidget(self.txt_search, 1)
        root.addLayout(row1)

        urow = QHBoxLayout()
        urow.setSpacing(4)
        self.cmb_user = QComboBox()
        self.cmb_user.setToolTip('İşlem uygulanacak Android kullanicisi (UAD multi-user)')
        self.cmb_user.addItem('Kullanıcı: Owner (0)', 0)
        self.cmb_user.currentIndexChanged.connect(self._user_changed)
        self.btn_users = QPushButton('Kullanıcıları Tara')
        self.btn_users.clicked.connect(self._scan_users)
        self.btn_sel_export = QPushButton('Seçimi Dışa Aktar')
        self.btn_sel_export.setToolTip('UAD uad_exported_selection.txt biçimi')
        self.btn_sel_export.clicked.connect(self._export_selection)
        self.btn_sel_import = QPushButton('Seçimi İçe Aktar')
        self.btn_sel_import.clicked.connect(self._import_selection)
        urow.addWidget(self.cmb_user)
        urow.addWidget(self.btn_users)
        urow.addWidget(self.btn_sel_export)
        urow.addWidget(self.btn_sel_import)
        urow.addStretch()
        root.addLayout(urow)

        self.lbl_hint = QLabel(
            'İpucu: "Cihazda Var" sutunu paketin cihazda kurulu olup olmadigini gosterir. '
            '"Dokunma" kategorisindeki kritik paketler secilemez.')
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet(kit.muted(kit.dark_from(self)))
        root.addWidget(self.lbl_hint)

        # --- Hazır profiller ---
        prof_row = QHBoxLayout()
        prof_row.setSpacing(4)
        self.cmb_profile = QComboBox()
        self.cmb_profile.setMinimumWidth(220)
        self._fill_profiles()
        self.lbl_profile = QLabel('')
        self.lbl_profile.setWordWrap(True)
        self.lbl_profile.setStyleSheet(kit.muted(kit.dark_from(self)))
        self.cmb_profile.currentIndexChanged.connect(self._show_profile_desc)
        self.btn_profile = QPushButton('Profili Uygula')
        self.btn_profile.setProperty('accent', True)
        self.btn_profile.clicked.connect(self._apply_profile)
        prof_row.addWidget(QLabel('Profil:'))
        prof_row.addWidget(self.cmb_profile)
        prof_row.addWidget(self.btn_profile)
        root.addLayout(prof_row)
        root.addWidget(self.lbl_profile)
        self._show_profile_desc()

        self.grid = kit.make_table(
            7, ['Seç', 'Uygulama', 'Paket', 'Açıklama', 'Cihazda', 'Durum', 'UAD'])
        hdr = self.grid.horizontalHeader()
        hdr.setSectionResizeMode(COL_PKG, QHeaderView.Stretch)
        hdr.setSectionResizeMode(COL_DESC, QHeaderView.Stretch)
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_CHECK, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_PRESENT, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_STATE, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_UAD, QHeaderView.ResizeToContents)
        self.grid.itemChanged.connect(lambda _it: self._update_sel_count())
        self.grid.itemSelectionChanged.connect(self._update_sel_count)
        root.addWidget(self.grid, 1)

        flow1 = FlowLayout()
        self.chk_all = QPushButton('Tümü Seç')
        self.chk_all.clicked.connect(lambda: self._toggle_all(True))
        self.chk_none = QPushButton('Seçimi Kaldır')
        self.chk_none.clicked.connect(lambda: self._toggle_all(False))
        self.chk_inv = QPushButton('Ters Çevir')
        self.chk_inv.clicked.connect(self._invert_all)
        self.lbl_sel = QLabel('')
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
        self.btn_scan = QPushButton('Varligi Tara')
        self.btn_scan.clicked.connect(self._scan_presence)
        for b in (self.chk_all, self.chk_none, self.chk_inv, self.btn_smart, self.btn_remove,
                  self.btn_disable, self.btn_restore, self.btn_scan):
            flow1.addWidget(b)
        flow1.addWidget(self.lbl_sel)
        root.addLayout(flow1)

        flow2 = FlowLayout()
        self.btn_addfav = QPushButton('Favori Ekle')
        self.btn_addfav.clicked.connect(self._add_favorite_dialog)
        self.btn_rmfav = QPushButton('Favoriden Cikar')
        self.btn_rmfav.clicked.connect(self._remove_favorite_selected)
        self.btn_export = QPushButton('CSV Aktar')
        self.btn_export.clicked.connect(self._export_csv)
        for b in (self.btn_addfav, self.btn_rmfav, self.btn_export):
            flow2.addWidget(b)
        root.addLayout(flow2)

        # --- Sahne çubuğu ---
        stage_row = FlowLayout()
        self.lbl_stage = QLabel('Sahne: 0 işlem')
        self.lbl_stage.setStyleSheet(kit.title(kit.dark_from(self)))
        self.btn_stage_add_disable = QPushButton('Seçiliyi Sahneye: Devre dışı')
        self.btn_stage_add_disable.clicked.connect(lambda: self._stage_add('disable'))
        self.btn_stage_add_uninstall = QPushButton('Seçiliyi Sahneye: Kaldır')
        self.btn_stage_add_uninstall.clicked.connect(lambda: self._stage_add('uninstall'))
        self.btn_stage_show = QPushButton('Sahneyi Önizle/Uygula')
        self.btn_stage_show.setProperty('accent', True)
        self.btn_stage_show.clicked.connect(self._stage_show)
        self.btn_stage_clear = QPushButton('Sahneyi Temizle')
        self.btn_stage_clear.clicked.connect(self._stage_clear)
        stage_row.addWidget(self.lbl_stage)
        stage_row.addWidget(self.btn_stage_add_disable)
        stage_row.addWidget(self.btn_stage_add_uninstall)
        stage_row.addWidget(self.btn_stage_show)
        stage_row.addWidget(self.btn_stage_clear)
        kit.fit_buttons(self.btn_stage_add_disable, self.btn_stage_add_uninstall,
                        self.btn_stage_show, self.btn_stage_clear)
        root.addLayout(stage_row)

        self.lbl_summary = QLabel('Cihaz varlığı bilinmiyor — taranıyor...')
        root.addWidget(self.lbl_summary)
        # _presence bilinmiyor -> _reload bos gosterir + otomatik tarama baslar
        self._reload()

    def _fill_categories(self):
        self.cmb_cat.blockSignals(True)
        self.cmb_cat.clear()
        for key, label, _ in all_categories():
            self.cmb_cat.addItem(label, key)
        self.cmb_cat.blockSignals(False)

    def _fill_profiles(self):
        from .. import profiles as profmod
        self.cmb_profile.blockSignals(True)
        self.cmb_profile.clear()
        for key, prof in profmod.PROFILES.items():
            self.cmb_profile.addItem(prof['label'], key)
        self.cmb_profile.blockSignals(False)

    def _show_profile_desc(self):
        from .. import profiles as profmod
        key = self.cmb_profile.currentData()
        prof = profmod.PROFILES.get(key, {})
        clean, rejected = profmod.validate_profile(key)
        extra = ''
        if rejected:
            extra = ' [YASAKLI {} paket uygulanmaz: {}]'.format(
                len(rejected), ', '.join(p for p, _ in rejected[:5]))
        self.lbl_profile.setText((prof.get('desc', '') or '') + extra +
                                 ' ({} paket, yöntem: {})'.format(len(clean), prof.get('method', 'smart')))

    def _apply_profile(self):
        from .. import profiles as profmod
        from .. import stage as stagemod
        from .stage_dialog import StageDialog
        from ..workers import PackageActionWorker, SmartRemoveWorker, StageWorker
        key = self.cmb_profile.currentData()
        prof = profmod.PROFILES.get(key)
        if not prof:
            return
        clean, rejected = profmod.validate_profile(key)
        # YALNIZCA-CIHAZ: profilde olup cihazda olmayan paketlere dokunma.
        if self._presence_known and self._present:
            missing = [p for p in clean if p not in self._present]
            clean = [p for p in clean if p in self._present]
            if missing:
                self.window.append_log(
                    'Profil: {} paket cihazda yok, atlandı: {}'.format(
                        len(missing), ', '.join(missing[:8])), 'WARN')
        if not clean:
            QMessageBox.warning(self, 'Profil', 'Uygulanabilir paket yok (tümü yasaklı veya cihazda yok).')
            return
        # sahneye koy + önizle
        st = stagemod.Stage()
        method = prof.get('method', 'smart')
        if method == 'smart':
            # smart = disable öncelikli: sahnede disable olarak işaretle,
            # çalışırken olmazsa uninstall'a düş (run_stage smart-düşüşü)
            for p in clean:
                st.add('__smart__', p)
        else:
            st.add_many(method, clean)
        dlg = StageDialog(self, self._expand_smart(st), self.core.config.friendly_name)
        if dlg.exec() != dlg.Accepted:
            return
        if method == 'smart':
            w = SmartRemoveWorker(self.core.engine, self.core.target, clean,
                                  self.core.config.protected)
            w.finished_ok.connect(self._on_done_smart)
        else:
            w = PackageActionWorker(self.core.engine, self.core.target, clean,
                                    method, self.core.config.protected)
            w.finished_ok.connect(self._on_done)
        self.window._run(w, on_ok=lambda _: self._scan_presence())

    @staticmethod
    def _expand_smart(stage):
        """Önizleme için __smart__ işaretlerini disable satırına çevirir."""
        from .. import stage as stagemod
        out = stagemod.Stage()
        for action, pkg in stage.items():
            out.add('disable' if action == '__smart__' else action, pkg)
        return out

    def reload(self):
        self._fill_categories()
        self._reload()

    def apply_theme(self):
        """Tema degisince: etiketler + tablo on renkleri yeni palete gecer."""
        try:
            dark = kit.dark_from(self)
            self.lbl_hint.setStyleSheet(kit.muted(dark))
            self.lbl_profile.setStyleSheet(kit.muted(dark))
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

    # ------------------------------------------------------------------
    def _reload(self):
        # YALNIZCA-CIHAZ MODU: varlık bilinmiyorsa liste BOŞ gösterilir,
        # arka planda otomatik varlık taraması başlar. '?'/'Yok' uydurma yok.
        if not self._presence_known:
            self.grid.setRowCount(0)
            self._entries = []
            # Bagli degilken ADB'ye dokunma: sadece bekle mesaji.
            # Baglanti kurulunca main_window otomatik cagirir (scan_if_needed).
            if self.core.connected:
                self.lbl_summary.setText('Cihaz varlığı bilinmiyor — taranıyor...')
                if not self._presence_scanning:
                    try:
                        self._scan_presence()
                    except Exception:
                        pass
            else:
                self.lbl_summary.setText('Bağlı cihaz yok — bağlanınca cihaz uygulamaları listelenecek.')
            return
        cat = self.cmb_cat.currentData() or 'guvenli'
        q = self.txt_search.text().strip().lower()
        removal_f = self.cmb_removal.currentData() or ''
        ulist_f = self.cmb_ulist.currentData() or ''
        show_unlisted = self.chk_unlisted.isChecked()
        entries = []
        for key, _label, items in all_categories():
            if key == cat:
                entries = list(items)
                break
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
                                    'Listesiz — cihazda kurulu, veritabanında yok'))
        # YALNIZCA-CIHAZ: cihazda olmayan hicbir satir gosterilmez.
        entries = [e for e in entries if e[0] in self._present]
        self._entries = entries
        only_installed = True  # yalnizca-cihaz modunda her zaman acik
        try:
            if not self.chk_installed.isChecked():
                self.chk_installed.blockSignals(True)
                self.chk_installed.setChecked(True)
                self.chk_installed.setEnabled(False)
                self.chk_installed.setToolTip('Yalnızca-cihaz modu: hep açık')
                self.chk_installed.blockSignals(False)
        except Exception:
            pass
        self.grid.setRowCount(0)
        shown = 0
        for pkg, name, desc in entries:
            if q and q not in (name + ' ' + pkg + ' ' + desc).lower():
                continue
            # UAD filtreleri
            if ulist_f and uad_list_of(pkg) != ulist_f:
                continue
            if removal_f and uad_removal_of(pkg) != removal_f:
                continue
            r = self.grid.rowCount()
            self.grid.insertRow(r)
            critical = (cat == 'dokunma')
            chk = QTableWidgetItem()
            if critical:
                chk.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                chk.setToolTip('Kritik sistem paketi: işlem için secilemez')
            else:
                chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Unchecked)
            chk.setData(Qt.UserRole, pkg)
            nm = QTableWidgetItem(name)
            pk = QTableWidgetItem(pkg)
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
            color = cat_pal.get(cat, CAT_COLORS.get(cat))
            if color and not critical:
                nm.setForeground(QBrush(QColor(color)))
            if critical:
                nm.setForeground(QBrush(QColor(pal['danger'])))
                f = nm.font()
                f.setBold(True)
                nm.setFont(f)
            # UAD sutunu: removal seviyesi + kaynak listesi + bagimlilik uyari
            removal = uad_removal_of(pkg)
            ulist = uad_list_of(pkg)
            deps = needed_by(pkg)
            uad_txt = '{} / {}'.format(REMOVAL_TR.get(removal, removal), ulist)
            if deps:
                uad_txt += ' ⚠'
            uad_cell = QTableWidgetItem(uad_txt)
            uad_cell.setForeground(QBrush(QColor(rem_pal.get(removal, REMOVAL_COLOR.get(removal, pal['faint'])))))
            if deps:
                uad_cell.setToolTip('BUNA IHTIAC DUYANLAR: {}\n(Kaldırınca bunlar bozulabilir)'.format(
                    ', '.join(deps)))
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
            shown += 1
        note = '  |  filtre: sadece kurulu' if only_installed else ''
        self.lbl_summary.setText(
            'Kategori: {}  |  {} / {} paket gosteriliyor{}'.format(
                CAT_LABELS.get(cat, cat), shown, len(entries), note))

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
        dlg = StageDialog(self, st, self.core.config.friendly_name)
        if dlg.exec() != dlg.Accepted:
            return
        w = StageWorker(self.core.engine, self.core.target, st.items(),
                        self.core.config.protected)
        w.finished_ok.connect(self._on_done)
        self.window._run(w, on_ok=lambda _: (self._stage_clear(), self._scan_presence()))

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
        name_of = lambda p: self._debloat_name(p)
        label = ACTION_TR.get(action, action)
        # UAD bağımlılık uyarısı (auto-remove YOK, sadece uyar — UAD davranışı)
        dep_warn = []
        for p in pkgs:
            nb = needed_by(p)
            if nb:
                dep_warn.append('{} gerekli: {}'.format(p, ', '.join(nb)))
        if dep_warn and QMessageBox.question(
                self, 'Bağımlılık Uyarısı',
                'Bazı paketlere BAŞKALARI ihtiyaç duyuyor (UAD neededBy):\n\n' +
                '\n'.join(dep_warn[:10]) +
                ('\n... ve {} tane daha'.format(len(dep_warn) - 10) if len(dep_warn) > 10 else '') +
                '\n\nYine de devam edilsin mi?') != QMessageBox.Yes:
            return
        cat = self.cmb_cat.currentData()
        # Risk politikasi (UAD onerisi): riskli kategoride uninstall YASAK,
        # yerine disable-oncelikli smart uygulanir.
        if cat == 'riskli' and action == 'uninstall':
            extra = ('RISKL kategori: Güvenlik politikasi geregi Kaldır yerine '
                     'önce Devre dışı denenir (Akilli Kaldır).')
            if not confirm_action(self, 'smart', pkgs, name_of, extra):
                return
            self._smart_remove(pkgs)
            return
        if action in ('uninstall', 'disable', 'smart') and cat == 'riskli':
            extra = 'RISKL kategori — sistem bozulabilir!'
            if not confirm_action(self, action, pkgs, name_of, extra):
                return
        elif action in ('uninstall', 'disable', 'smart', 'restore'):
            if not confirm_action(self, action, pkgs, name_of):
                return
        if action == 'smart':
            self._smart_remove(pkgs)
            return
        w = PackageActionWorker(self.core.engine, self.core.target, pkgs,
                                action, self.core.config.protected)
        w.finished_ok.connect(self._on_done)
        self.window._run(w, on_ok=lambda _: self._scan_presence())

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

    def _smart_remove(self, pkgs):
        """Akilli kaldirma: her paket icin disable dene, olmazsa uninstall."""
        from ..workers import SmartRemoveWorker, format_action_result
        w = SmartRemoveWorker(self.core.engine, self.core.target, pkgs,
                              self.core.config.protected)
        w.finished_ok.connect(self._on_done_smart)
        self.window._run(w, on_ok=lambda _: self._scan_presence())

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
        self.core.config.user_id = int(self.cmb_user.itemData(idx) or 0)
        self.core.config.save()
        self.window.append_log('İşlem kullanıcısı: user {}'.format(self.core.config.user_id), 'INFO')

    def _scan_users(self):
        def do():
            self.core.engine.connect(self.core.target)
            return self.core.engine.list_users(self.core.target)
        w = Worker(do)
        w.finished_ok.connect(self._show_users)
        self.window._run(w)

    def _show_users(self, users):
        cur = self.core.config.user_id
        self.cmb_user.blockSignals(True)
        self.cmb_user.clear()
        for u in users:
            label = 'Kullanıcı: {} ({}){}'.format(u['name'], u['id'],
                                                 ' [çalışıyor]' if u.get('running') else '')
            self.cmb_user.addItem(label, u['id'])
        for i in range(self.cmb_user.count()):
            if self.cmb_user.itemData(i) == cur:
                self.cmb_user.setCurrentIndex(i)
                break
        self.cmb_user.blockSignals(False)
        self.window.append_log('{} kullanıcı bulundu.'.format(len(users)), 'INFO')

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
        def do():
            eng = self.core.engine
            t = self.core.target
            eng.connect(t)
            present = set(eng.list_packages(t, include_system=True))
            try:
                disabled = set()
                rd = eng.shell(t, 'pm', 'list', 'packages', '-d')
                for line in rd.output.splitlines():
                    line = line.strip()
                    if line.startswith('package:'):
                        disabled.add(line[len('package:'):].strip())
            except Exception:
                disabled = set()
            return {'present': present, 'disabled': disabled}
        w = Worker(do)
        w.job_name = 'Debloat varlik taramasi'
        self._presence_scanning = True
        w.finished_ok.connect(self._set_present)
        try:
            w.failed.connect(lambda _e: setattr(self, '_presence_scanning', False))
        except Exception:
            pass
        self.window._run(w, desc='Debloat: cihazda kurulu paketler taraniyor')

    def _set_present(self, res):
        if isinstance(res, dict):
            self._present = set(res.get('present', ()))
            self._disabled = set(res.get('disabled', ()))
        else:
            self._present = set(res or [])
            self._disabled = set()
        self._presence_known = True
        self._presence_scanning = False
        self._reload()
        n_shown = self.grid.rowCount()
        self.lbl_summary.setText(
            'Cihazda {} paket kurulu, {} devre dışı — {} listeleniyor (yalnızca cihaz).'.format(
                len(self._present), len(self._disabled), n_shown))

    def set_present(self, pkgs):
        """Cihazdaki tum paketleri (Uygulamalar taramasindan) alir."""
        if isinstance(pkgs, dict):
            self._present = set(pkgs.get('present', ()))
            self._disabled = set(pkgs.get('disabled', ()))
        else:
            self._present = set(pkgs or [])
        self._presence_known = True
        self._presence_scanning = False
        self._reload()

    def scan_if_needed(self):
        """Baglanti sonrasi cagrilir: varlik bilinmiyorsa tara, varsa tazele."""
        try:
            if not self._presence_known and not self._presence_scanning:
                self._scan_presence()
            elif self._presence_known:
                self._scan_presence()
        except Exception:
            pass

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
