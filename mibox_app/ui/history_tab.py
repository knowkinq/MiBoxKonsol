# -*- coding: utf-8 -*-
"""Geçmiş sekmesi: kalıcı işlem kayıtları + tek tıkla geri alma + snapshot."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QAbstractItemView, QMessageBox,
    QComboBox, QFileDialog,
)

from ..workers import PackageActionWorker, SnapshotWorker, Worker
from . import kit
from .flowlayout import FlowLayout

COL_TS = 0
COL_ACTION = 1
COL_PKG = 2
COL_METHOD = 3
COL_OK = 4

ACTION_TR = {
    'uninstall': 'Kaldırma', 'disable': 'Devre dışı', 'enable': 'Aktif',
    'restore': 'Geri yükleme', 'restrict': 'Kısıtla', 'unrestrict': 'Serbest',
    'smart': 'Akıllı kaldırma', 'snapshot': 'Snapshot', 'clear': 'Veri silme',
    'stop': 'Force stop', 'launch': 'Açma',
}


class HistoryTab(QWidget):
    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._records = []
        self._build()

    def _build(self):
        root = kit.page(self)

        self._hint = QLabel('Her başarılı işlem buraya yazılır. Geri alınabilir satırı seçip '
                      'Geri Al ile tersini uygula. Snapshot: cihaz durumunu kaydet, '
                      'OTA sonrası Farkları Göster/Uygula.')
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(kit.muted(kit.dark_from(self)))
        root.addWidget(self._hint)

        row0 = FlowLayout()
        self.cmb_snap = QComboBox()
        self.cmb_snap.setMinimumWidth(260)
        self.cmb_snap.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.btn_snap_refresh = QPushButton('Yenile')
        self.btn_snap_refresh.clicked.connect(self.refresh_snaps)
        self.btn_snap_take = QPushButton('Snapshot Al')
        self.btn_snap_take.setProperty('accent', True)
        self.btn_snap_take.clicked.connect(self._snap_take)
        self.btn_snap_diff = QPushButton('Farkları Göster')
        self.btn_snap_diff.clicked.connect(self._snap_diff)
        self.btn_snap_apply = QPushButton('Snapshot Uygula')
        self.btn_snap_apply.setProperty('danger', True)
        self.btn_snap_apply.clicked.connect(self._snap_apply)
        self.btn_snap_del = QPushButton('Sil')
        self.btn_snap_del.clicked.connect(self._snap_delete)
        row0.addWidget(QLabel('Snapshot:'))
        row0.addWidget(self.cmb_snap)
        row0.addWidget(self.btn_snap_refresh)
        row0.addWidget(self.btn_snap_take)
        row0.addWidget(self.btn_snap_diff)
        row0.addWidget(self.btn_snap_apply)
        row0.addWidget(self.btn_snap_del)
        kit.fit_buttons(self.btn_snap_refresh, self.btn_snap_take, self.btn_snap_diff,
                        self.btn_snap_apply, self.btn_snap_del)
        root.addLayout(row0)

        row0b = FlowLayout()
        self.btn_snap_export = QPushButton('Dışa Aktar (klonlama)')
        self.btn_snap_export.setToolTip('Snapshotu dosyaya kaydet, başka TV ye taşı')
        self.btn_snap_export.clicked.connect(self._snap_export)
        self.btn_snap_import = QPushButton('İçe Aktar')
        self.btn_snap_import.clicked.connect(self._snap_import)
        self.lbl_clone = QLabel('Klonlama: A cihazında Snapshot Al → Dışa Aktar → B cihazında İçe Aktar → Uygula.')
        self.lbl_clone.setWordWrap(True)
        self.lbl_clone.setStyleSheet(kit.muted(kit.dark_from(self)))
        row0b.addWidget(self.btn_snap_export)
        row0b.addWidget(self.btn_snap_import)
        row0b.addWidget(self.lbl_clone)
        root.addLayout(row0b)

        self.grid = kit.make_table(5, ['Zaman', 'İşlem', 'Paket', 'Yöntem', 'Sonuç'])
        hdr = self.grid.horizontalHeader()
        hdr.setSectionResizeMode(COL_PKG, QHeaderView.Stretch)
        for c in (COL_TS, COL_ACTION, COL_METHOD, COL_OK):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        root.addWidget(self.grid, 1)

        flow = FlowLayout()
        self.btn_refresh = QPushButton('Geçmişi Yenile')
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_undo = QPushButton('Seçiliyi Geri Al')
        self.btn_undo.setProperty('accent', True)
        self.btn_undo.clicked.connect(self._undo_selected)
        self.btn_export = QPushButton('CSV Aktar')
        self.btn_export.clicked.connect(self._export_csv)
        self.btn_clear = QPushButton('Geçmişi Temizle')
        self.btn_clear.setProperty('danger', True)
        self.btn_clear.clicked.connect(self._clear)
        for b in (self.btn_refresh, self.btn_undo, self.btn_export, self.btn_clear):
            flow.addWidget(b)
        kit.fit_buttons(self.btn_refresh, self.btn_undo, self.btn_export, self.btn_clear)
        root.addLayout(flow)

        self.lbl_summary = kit.status_label('')
        root.addWidget(self.lbl_summary)
        self.refresh()
        self.refresh_snaps()

    def apply_theme(self):
        """Tema degisince: bilgi etiketleri yeni palete gecer."""
        try:
            dark = kit.dark_from(self)
            self._hint.setStyleSheet(kit.muted(dark))
            self.lbl_clone.setStyleSheet(kit.muted(dark))
        except (RuntimeError, AttributeError):
            pass

    # ------------------------------------------------------------------
    def refresh(self):
        from .. import history as histmod
        self._records = histmod.read_all()
        self.grid.setRowCount(0)
        for rec in self._records:
            r = self.grid.rowCount()
            self.grid.insertRow(r)
            inv = histmod.inverse_of(rec.get('action', ''))
            undoable = 'Evet' if (inv and rec.get('ok')) else ('Hayır' if not inv else 'başarısızdı')
            cells = [
                rec.get('ts', ''),
                ACTION_TR.get(rec.get('action', ''), rec.get('action', '')),
                rec.get('package', ''),
                rec.get('method', '') or '-',
                ('Başarılı' if rec.get('ok') else 'Başarısız') + ' / geri: ' + undoable,
            ]
            for c, txt in enumerate(cells):
                it = QTableWidgetItem(txt)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                it.setData(Qt.UserRole, rec)
                self.grid.setItem(r, c, it)
        self.lbl_summary.setText('{} kayıt.'.format(len(self._records)))

    def _selected_records(self):
        rows = sorted({i.row() for i in self.grid.selectedIndexes()})
        out = []
        for r in rows:
            it = self.grid.item(r, COL_PKG)
            if it:
                rec = it.data(Qt.UserRole)
                if isinstance(rec, dict):
                    out.append(rec)
        return out

    def _undo_selected(self):
        from .. import history as histmod
        recs = self._selected_records()
        if not recs:
            QMessageBox.information(self, 'Seçim', 'Önce satır seçin.')
            return
        # işlem -> ters işlem grupları
        groups = {}
        skipped = []
        for rec in recs:
            if not rec.get('ok'):
                skipped.append((rec.get('package', ''), 'işlem zaten başarısızdı'))
                continue
            inv = histmod.inverse_of(rec.get('action', ''))
            if not inv:
                skipped.append((rec.get('package', ''), 'geri alınamaz işlem: ' + rec.get('action', '')))
                continue
            groups.setdefault(inv, []).append(rec.get('package', ''))
        if not groups:
            QMessageBox.information(self, 'Geri Al',
                                    'Seçili satırların hiçbiri geri alınamaz.\n' +
                                    '\n'.join('X {}: {}'.format(p, m) for p, m in skipped))
            return
        # Onayda HANGI uygulamalar: grup basina ilk 8 paket adi
        lines = []
        for k, v in groups.items():
            lines.append('{} ({} paket):'.format(k, len(v)))
            for p in v[:8]:
                try:
                    nm = self.core.config.friendly_name(p)
                except Exception:
                    nm = p
                lines.append(u'  • {}'.format('{} ({})'.format(nm, p) if nm != p else p))
            if len(v) > 8:
                lines.append(u'  … ve {} tane daha'.format(len(v) - 8))
        summary = '\n'.join(lines)
        if skipped:
            summary += '\n\nAtlanacak:\n' + '\n'.join('X {}: {}'.format(p, m) for p, m in skipped[:10])
        if QMessageBox.question(self, u'Onay — Geri Al', summary + '\n\nUygulansın mı?',
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        # sırayla uygula (tek worker zinciri yerine gruplu)
        self._undo_queue = [(a, p) for a, pkgs in groups.items() for p in pkgs]
        self._undo_fail = list(skipped)
        self._run_next_undo()

    def _run_next_undo(self):
        if not self._undo_queue:
            self.refresh()
            try:
                self.window.tab_apps.refresh()
            except Exception:
                pass
            return
        action, pkg = self._undo_queue.pop(0)
        real = 'uninstall' if action == 'smart' else action
        # smart geri alımı: restore dene (smart_remove ters işlem kayıtta method olarak var)
        w = PackageActionWorker(self.core.engine, self.core.target, [pkg],
                                real if real != 'smart' else 'restore',
                                self.core.config.protected)
        w.finished_ok.connect(lambda res, a=real, p=pkg: self._undo_done(res, a, p))
        self.window._run(w, on_ok=lambda _: self._run_next_undo())

    def _undo_done(self, res, action, pkg):
        if not isinstance(res, dict) or res.get('fail'):
            self._undo_fail.append((pkg, 'geri alma başarısız'))

    def _export_csv(self):
        import csv
        if not self._records:
            QMessageBox.information(self, 'Aktar', 'Kayıt yok.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'CSV Kaydet', 'mibox-gecmis.csv', 'CSV (*.csv)')
        if not path:
            return
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(['Zaman', 'Hedef', 'İşlem', 'Paket', 'Yöntem', 'Sonuç'])
                for rec in self._records:
                    w.writerow([rec.get('ts', ''), rec.get('target', ''), rec.get('action', ''),
                                rec.get('package', ''), rec.get('method', ''),
                                'ok' if rec.get('ok') else 'fail'])
            QMessageBox.information(self, 'Tamam', 'Aktarıldı:\n' + path)
        except OSError as e:
            QMessageBox.critical(self, 'Hata', str(e))

    def _clear(self):
        from .. import history as histmod
        if QMessageBox.question(self, 'Temizle', 'İşlem geçmişi silinsin mi?') != QMessageBox.Yes:
            return
        histmod.clear()
        self.refresh()

    # --- snapshot ---
    def refresh_snaps(self):
        from .. import snapshot as snapmod
        self.cmb_snap.blockSignals(True)
        self.cmb_snap.clear()
        for name in snapmod.list_snapshots():
            self.cmb_snap.addItem(name, name)
        self.cmb_snap.blockSignals(False)
        if self.cmb_snap.count() == 0:
            self.cmb_snap.addItem('(snapshot yok)', '')

    def _snap_take(self):
        w = SnapshotWorker(self.core.engine, self.core.target, 'take')
        w.finished_ok.connect(self._snap_taken)
        self.window._run(w, desc='Gecmis: snapshot aliniyor')

    def _snap_taken(self, res):
        self.refresh_snaps()
        QMessageBox.information(self, 'Snapshot',
                                '{} paket kaydedildi:\n{}'.format(res.get('count', 0), res.get('name', '')))

    def _snap_diff(self):
        name = self.cmb_snap.currentData()
        if not name:
            QMessageBox.information(self, 'Snapshot', 'Önce snapshot seçin.')
            return

        def do():
            from .. import snapshot as snapmod
            snap = snapmod.load(name)
            return snapmod.diff_current(self.core.engine, self.core.target, snap)
        w = Worker(do)
        w.job_name = 'Snapshot fark'
        w.finished_ok.connect(self._show_diff)
        self.window._run(w, desc='Gecmis: snapshot farki hesaplaniyor')

    def _show_diff(self, diffs):
        if not diffs:
            QMessageBox.information(self, 'Fark', 'Fark yok: cihaz snapshot ile aynı durumda.')
            return
        lines = ['{} paket farklı:'.format(len(diffs))]
        for pkg, _w, _h, act in diffs[:40]:
            lines.append('{} -> {}'.format(pkg, act))
        if len(diffs) > 40:
            lines.append('... ve {} tane daha'.format(len(diffs) - 40))
        QMessageBox.information(self, 'Fark', '\n'.join(lines))

    def _snap_apply(self):
        name = self.cmb_snap.currentData()
        if not name:
            QMessageBox.information(self, 'Snapshot', 'Önce snapshot seçin.')
            return
        # Onayda snapshot ICERIGI ozeti: kac paket, hangi islemler
        try:
            from .. import snapshot as _snapmod
            _snap = _snapmod.load(name)
            _pkgs = _snap.get('packages', {}) or {}
            _n = len(_pkgs)
            _cnt = {}
            for _e in _pkgs.values():
                _s = str(_e.get('state', '?') if isinstance(_e, dict) else _e)
                _cnt[_s] = _cnt.get(_s, 0) + 1
            _detail = '{} paket ({}).'.format(
                _n, ', '.join('{}: {}'.format(k, v) for k, v in sorted(_cnt.items())))
        except Exception:
            _detail = '(icerik okunamadi)'
        if QMessageBox.question(
                self, u'Onay — Snapshot Uygula',
                u'{}\n{}\n\nCihaza uygulanacak. Devam edilsin mi?'.format(name, _detail),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes:
            return
        w = SnapshotWorker(self.core.engine, self.core.target, 'apply',
                           snapshot_name=name, protected=self.core.config.protected)
        w.progress.connect(lambda c, t: self.lbl_summary.setText('Snapshot: {}/{}'.format(c, t)))
        w.finished_ok.connect(self._snap_applied)
        self.window._run(w, on_ok=lambda _: self.refresh())

    def _snap_applied(self, res):
        from ..workers import format_action_result
        QMessageBox.information(self, 'Snapshot',
                                format_action_result(res, self.core.config.friendly_name))
        try:
            self.window.tab_apps.refresh()
        except Exception:
            pass

    def _snap_delete(self):
        from .. import snapshot as snapmod
        name = self.cmb_snap.currentData()
        if not name:
            return
        if QMessageBox.question(self, u'Onay — Snapshot Sil',
                                u'Silinsin mi? (Geri alınamaz!)\n\n• {}'.format(name),
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        snapmod.delete(name)
        self.refresh_snaps()

    def _snap_export(self):
        import shutil
        from .. import snapshot as snapmod
        name = self.cmb_snap.currentData()
        if not name:
            QMessageBox.information(self, 'Snapshot', 'Önce snapshot seçin.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Snapshot Dışa Aktar', name, 'JSON (*.json)')
        if not path:
            return
        try:
            shutil.copy(snapmod.snapshot_path(name), path)
            QMessageBox.information(self, 'Tamam', 'Aktarıldı:\n' + path)
        except OSError as e:
            QMessageBox.critical(self, 'Hata', str(e))

    def _snap_import(self):
        import json
        import shutil
        from .. import snapshot as snapmod
        path, _ = QFileDialog.getOpenFileName(self, 'Snapshot İçe Aktar', '', 'JSON (*.json)')
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict) or 'packages' not in data:
                raise ValueError('Geçersiz snapshot dosyası.')
            import datetime as _dt
            name = 'mibox-snapshot-klon-{}.json'.format(_dt.datetime.now().strftime('%Y%m%d-%H%M%S'))
            shutil.copy(path, snapmod.snapshot_path(name))
            self.refresh_snaps()
            QMessageBox.information(self, 'Tamam',
                                    'İçe aktarıldı:\n{}\nKlon hedefe bağlanıp Uygula ile kurun.'.format(name))
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, 'Hata', str(e))
