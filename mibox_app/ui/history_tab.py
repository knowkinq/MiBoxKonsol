# -*- coding: utf-8 -*-
"""Geçmiş sekmesi: kalıcı işlem kayıtları + tek tıkla geri alma + snapshot."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QMessageBox,
    QComboBox, QFileDialog, QMenu, QToolButton,
)

from ..workers import PackageActionWorker, SmartRemoveWorker, SnapshotWorker, Worker
from . import kit

COL_TS = 0
COL_TARGET = 1
COL_USER = 2
COL_ACTION = 3
COL_PKG = 4
COL_METHOD = 5
COL_OK = 6

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

        self._hint = QLabel('İşlem geçmişinden geri alınabilir kayıtları seçin. Snapshotlar cihaz '
                            'durumunu saklar ve daha sonra karşılaştırmaya yardımcı olur.')
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(kit.muted(kit.dark_from(self)))
        root.addWidget(self._hint)

        snap_box = kit.section('Cihaz snapshotları')
        snap_layout = QVBoxLayout(snap_box)
        snap_layout.setContentsMargins(10, 18, 10, 8)
        row0 = QHBoxLayout()
        row0.setSpacing(kit.SPACING)
        self.cmb_snap = QComboBox()
        self.cmb_snap.setMinimumWidth(210)
        self.cmb_snap.setMaximumWidth(260)
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
        self.btn_snap_export = QPushButton('Dışa Aktar (klonlama)')
        self.btn_snap_export.setToolTip('Snapshotu dosyaya kaydet, başka TV ye taşı')
        self.btn_snap_export.clicked.connect(self._snap_export)
        self.btn_snap_import = QPushButton('İçe Aktar')
        self.btn_snap_import.clicked.connect(self._snap_import)

        self.btn_snap_more = QToolButton()
        self.btn_snap_more.setText('Diğer')
        self.btn_snap_more.setToolTip('Snapshot içe/dışa aktarma, uygulama ve silme')
        self.btn_snap_more.setPopupMode(QToolButton.InstantPopup)
        snap_menu = QMenu(self.btn_snap_more)
        snap_menu.addSection('Klonlama')
        for button in (self.btn_snap_export, self.btn_snap_import):
            action = snap_menu.addAction(button.text())
            action.setToolTip(button.toolTip())
            action.triggered.connect(
                lambda _checked=False, target=button: target.click())
        snap_menu.addSection('Cihaz işlemleri')
        for button in (self.btn_snap_apply, self.btn_snap_del):
            action = snap_menu.addAction(button.text())
            action.setToolTip(button.toolTip())
            action.triggered.connect(
                lambda _checked=False, target=button: target.click())
        self.btn_snap_more.setMenu(snap_menu)
        for button in (self.btn_snap_export, self.btn_snap_import,
                       self.btn_snap_apply, self.btn_snap_del):
            button.setParent(self)
            button.hide()

        row0.addWidget(self.cmb_snap, 1)
        row0.addWidget(self.btn_snap_refresh)
        row0.addWidget(self.btn_snap_take)
        row0.addWidget(self.btn_snap_diff)
        row0.addWidget(self.btn_snap_more)
        snap_layout.addLayout(row0)

        self.lbl_clone = QLabel('Klonlama: A cihazında Snapshot Al → Dışa Aktar → B cihazında İçe Aktar → Uygula.')
        self.lbl_clone.setWordWrap(True)
        self.lbl_clone.setStyleSheet(kit.muted(kit.dark_from(self)))
        snap_layout.addWidget(self.lbl_clone)
        root.addWidget(snap_box)

        self.grid = kit.make_table(
            7, ['Zaman', 'Hedef', 'Kullanıcı', 'İşlem', 'Paket', 'Yöntem', 'Sonuç'])
        hdr = self.grid.horizontalHeader()
        hdr.setSectionResizeMode(COL_PKG, QHeaderView.Stretch)
        for c in (COL_TS, COL_TARGET, COL_ACTION, COL_METHOD, COL_OK):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        root.addWidget(self.grid, 1)

        flow = QHBoxLayout()
        flow.setSpacing(kit.SPACING)
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

        self.btn_history_more = QToolButton()
        self.btn_history_more.setText('Diğer işlemler')
        self.btn_history_more.setPopupMode(QToolButton.InstantPopup)
        history_menu = QMenu(self.btn_history_more)
        for button in (self.btn_export, self.btn_clear):
            action = history_menu.addAction(button.text())
            action.setToolTip(button.toolTip())
            action.triggered.connect(
                lambda _checked=False, target=button: target.click())
            button.setParent(self)
            button.hide()
        self.btn_history_more.setMenu(history_menu)

        flow.addWidget(self.btn_refresh)
        flow.addWidget(self.btn_undo)
        flow.addStretch(1)
        flow.addWidget(self.btn_history_more)
        root.addLayout(flow)

        self.lbl_summary = kit.status_label('')
        root.addWidget(self.lbl_summary)
        kit.empty_state(self.grid, 'Henüz işlem yok',
                        'Cihaz işlemleri tamamlandıkça kayıtlar bu tabloda görünür.')
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
    @staticmethod
    def _inverse_for_record(histmod, rec):
        action = rec.get('action', '')
        if type(action) is not str:
            return None
        inverse = histmod.inverse_of(action)
        if inverse or action != 'smart':
            return inverse
        # Smart Remove records retain the concrete method. Only these two
        # known methods have a safe inverse; legacy records without a method
        # remain visible but cannot be undone safely.
        method = rec.get('method')
        if type(method) is not str:
            return None
        return {'disable': 'enable', 'uninstall': 'restore'}.get(method)

    def refresh(self):
        from .. import history as histmod
        self._records = histmod.read_all()
        self.grid.setRowCount(0)
        for rec in self._records:
            r = self.grid.rowCount()
            self.grid.insertRow(r)
            inv = self._inverse_for_record(histmod, rec)
            undoable = 'Evet' if (inv and rec.get('ok')) else ('Hayır' if not inv else 'başarısızdı')
            user_id = rec.get('user_id', 0)
            cells = [
                rec.get('ts', ''),
                str(rec.get('target') or ''),
                'user {}'.format(user_id) if type(user_id) is int else '?',
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
        kit.empty_state(self.grid, 'Henüz işlem yok',
                        'Cihaz işlemleri tamamlandıkça kayıtlar bu tabloda görünür.')

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
        # Validate every record that could be undone before scheduling any work.
        undoable = []
        skipped = []
        for rec in recs:
            if not rec.get('ok'):
                skipped.append((rec.get('package', ''), 'işlem zaten başarısızdı'))
                continue
            user_id = rec.get('user_id', 0)
            if type(user_id) is not int or not 0 <= user_id <= 21474:
                skipped.append((rec.get('package', ''), 'geçersiz kullanıcı kimliği'))
                continue
            inv = self._inverse_for_record(histmod, rec)
            if not inv:
                action = rec.get('action', '')
                skipped.append((rec.get('package', ''),
                                'geri alınamaz işlem: ' + (action if type(action) is str else '?')))
                continue
            undoable.append((rec, inv, user_id))
        if not undoable:
            QMessageBox.information(self, 'Geri Al',
                                    'Seçili satırların hiçbiri geri alınamaz.\n' +
                                    '\n'.join('X {}: {}'.format(p, m) for p, m in skipped))
            return
        if not self.core.connected:
            QMessageBox.warning(self, 'Geri Al',
                                'Geri alma için cihaza bağlı olmanız gerekir.')
            return
        current_target = self.core.target
        mismatched = []
        for rec, _inv, _user_id in undoable:
            recorded_target = rec.get('target')
            if (not isinstance(recorded_target, str) or not recorded_target.strip() or
                    recorded_target != current_target):
                label = recorded_target if isinstance(recorded_target, str) and recorded_target else '(hedef yok)'
                mismatched.append('{}: {}'.format(rec.get('package', ''), label))
        if mismatched:
            QMessageBox.warning(
                self, 'Geri Al',
                'Geri alma durduruldu. Seçili kayıtların hedefi bağlı cihazla eşleşmiyor '
                'veya hedef bilgisi yok:\n' + '\n'.join(mismatched))
            return

        # işlem -> ters işlem grupları
        groups = {}
        for rec, inv, user_id in undoable:
            groups.setdefault((inv, user_id), []).append(rec.get('package', ''))
        # Onayda HANGI uygulamalar: grup basina ilk 8 paket adi
        lines = []
        for (action, user_id), packages in groups.items():
            lines.append('{} (user {}, {} paket):'.format(action, user_id, len(packages)))
            for p in packages[:8]:
                try:
                    nm = self.core.config.friendly_name(p)
                except Exception:
                    nm = p
                lines.append(u'  • {}'.format('{} ({})'.format(nm, p) if nm != p else p))
            if len(packages) > 8:
                lines.append(u'  … ve {} tane daha'.format(len(packages) - 8))
        summary = 'Geri alma hedefi: {}\n\n'.format(current_target) + '\n'.join(lines)
        if skipped:
            summary += '\n\nAtlanacak:\n' + '\n'.join('X {}: {}'.format(p, m) for p, m in skipped[:10])
        if QMessageBox.question(self, u'Onay — Geri Al', summary + '\n\nUygulansın mı?',
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        # sırayla uygula (tek worker zinciri yerine gruplu)
        self._undo_queue = [(action, pkg, user_id)
                            for (action, user_id), packages in groups.items()
                            for pkg in packages]
        self._undo_fail = list(skipped)
        self._run_next_undo()

    def _run_next_undo(self):
        if not self._undo_queue:
            self.refresh()
            if self._undo_fail:
                details = '\n'.join('X {}: {}'.format(pkg, reason)
                                    for pkg, reason in self._undo_fail[:20])
                QMessageBox.warning(self, 'Geri Al', 'Bazı işlemler geri alınamadı:\n' + details)
            try:
                self.window.tab_apps.refresh()
            except Exception:
                pass
            return
        action, pkg, user_id = self._undo_queue.pop(0)
        if action == 'smart':
            w = SmartRemoveWorker(self.core.engine, self.core.target, [pkg],
                                  self.core.config.protected, user_id=user_id)
            real = action
        elif user_id == 0 and action not in ('restrict', 'unrestrict'):
            real = action
            w = PackageActionWorker(self.core.engine, self.core.target, [pkg],
                                    real,
                                    self.core.config.protected)
        else:
            real = action
            w = Worker(self._run_user_undo, real, pkg, user_id)
            w.job_name = 'Geçmiş geri alma'
        w.finished_ok.connect(lambda res, a=real, p=pkg: self._undo_done(res, a, p))
        self.window._run(w, on_ok=lambda _: self._run_next_undo())

    def _run_user_undo(self, action, pkg, user_id):
        """Apply an inverse with a user-aware engine API when available."""
        from .. import history as histmod
        methods = {
            'restore': ('install_existing_user_id', 'install_existing_for_user_id',
                        'install_existing_for_user', 'install_existing'),
            'uninstall': ('uninstall_user_id', 'uninstall_for_user_id',
                          'uninstall_for_user', 'uninstall_user'),
            'enable': ('enable_user_id', 'enable_for_user_id', 'enable_for_user', 'enable'),
            'disable': ('disable_user_id', 'disable_for_user_id',
                        'disable_for_user', 'disable_user'),
            'restrict': ('restrict_user_id', 'restrict_for_user_id',
                         'restrict_for_user', 'restrict'),
            'unrestrict': ('unrestrict_user_id', 'unrestrict_for_user_id',
                           'unrestrict_for_user', 'unrestrict'),
        }
        import inspect
        try:
            if action not in methods:
                raise ValueError('Bilinmeyen geri alma işlemi: {}'.format(action))
            if pkg in (self.core.config.protected or ()):
                raise ValueError('Paket koruma listesinde.')

            engine = self.core.engine
            engine.connect(self.core.target)
            for index, name in enumerate(methods[action]):
                method = getattr(engine, name, None)
                if not callable(method):
                    continue
                try:
                    parameters = inspect.signature(method).parameters
                except (TypeError, ValueError):
                    parameters = {}
                user_parameter = parameters.get('user_id')
                accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD
                                     for p in parameters.values())
                if user_parameter is not None or accepts_kwargs:
                    method(self.core.target, pkg, user_id=user_id)
                    try:
                        engine.invalidate_pkg_cache(self.core.target)
                    except Exception:
                        pass
                    histmod.append(self.core.target, action, pkg, ok=True, user_id=user_id)
                    return {'ok': 1, 'fail': 0}
                if index == len(methods[action]) - 1 and user_id == 0:
                    method(self.core.target, pkg)
                    try:
                        engine.invalidate_pkg_cache(self.core.target)
                    except Exception:
                        pass
                    histmod.append(self.core.target, action, pkg, ok=True, user_id=user_id)
                    return {'ok': 1, 'fail': 0}
                positional = [p for p in parameters.values()
                              if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                            inspect.Parameter.POSITIONAL_OR_KEYWORD)]
                if index < len(methods[action]) - 1 and len(positional) >= 3:
                    method(self.core.target, pkg, user_id)
                    try:
                        engine.invalidate_pkg_cache(self.core.target)
                    except Exception:
                        pass
                    histmod.append(self.core.target, action, pkg, ok=True, user_id=user_id)
                    return {'ok': 1, 'fail': 0}
            raise RuntimeError('user {} için geri alma API’si desteklenmiyor.'.format(user_id))
        except Exception as error:  # noqa: BLE001
            histmod.append(self.core.target, action, pkg, ok=False, user_id=user_id)
            return {'ok': 0, 'fail': 1, 'details': [(pkg, False, str(error))]}

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
                w.writerow(['Zaman', 'Hedef', 'Kullanıcı', 'İşlem',
                            'Paket', 'Yöntem', 'Sonuç'])
                for rec in self._records:
                    w.writerow([rec.get('ts', ''), rec.get('target', ''),
                                rec.get('user_id', 0), rec.get('action', ''),
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
        user_id = int(self.core.config.user_id or 0)
        w = SnapshotWorker(self.core.engine, self.core.target, 'take',
                           user_id=user_id)
        w.finished_ok.connect(self._snap_taken)
        self.window._run(w, desc='Geçmiş: snapshot aliniyor')

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
        self.window._run(w, desc='Geçmiş: snapshot farki hesaplaniyor')

    def _show_diff(self, diffs):
        if not diffs:
            QMessageBox.information(self, 'Fark', 'Fark yok: cihaz snapshot ile aynı durumda.')
            return
        lines = ['{} paket farklı:'.format(len(diffs))]
        for pkg, _w, _h, act in diffs[:40]:
            action_text = ' → '.join(act) if isinstance(act, (tuple, list)) else act
            lines.append('{} -> {}'.format(pkg, action_text))
        if len(diffs) > 40:
            lines.append('... ve {} tane daha'.format(len(diffs) - 40))
        QMessageBox.information(self, 'Fark', '\n'.join(lines))

    def _snap_apply(self):
        name = self.cmb_snap.currentData()
        if not name:
            QMessageBox.information(self, 'Snapshot', 'Önce snapshot seçin.')
            return
        # Onayda snapshot ICERIGI ozeti: kac paket, hangi islemler
        user_id = 0
        try:
            from .. import snapshot as _snapmod
            _snap = _snapmod.load(name)
            user_id = int(_snap.get('user_id', 0))
            _pkgs = _snap.get('packages', {}) or {}
            _n = len(_pkgs)
            _cnt = {}
            for _e in _pkgs.values():
                if not isinstance(_e, dict):
                    _s = 'geçersiz kayıt'
                elif not _e.get('installed_user0', False):
                    _s = 'kullanıcı için kaldırılmış'
                elif not _e.get('enabled', False):
                    _s = 'devre dışı'
                elif _e.get('restricted', False):
                    _s = 'arka plan kısıtlı'
                else:
                    _s = 'etkin'
                _cnt[_s] = _cnt.get(_s, 0) + 1
            _detail = 'user {} • {} paket ({}).'.format(
                user_id,
                _n, ', '.join('{}: {}'.format(k, v) for k, v in sorted(_cnt.items())))
        except Exception:
            _detail = '(içerik okunamadı)'
        if QMessageBox.question(
                self, u'Onay — Snapshot Uygula',
                u'{}\n{}\n\nCihaza uygulanacak. Devam edilsin mi?'.format(name, _detail),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes:
            return
        w = SnapshotWorker(self.core.engine, self.core.target, 'apply',
                           snapshot_name=name, protected=self.core.config.protected,
                           user_id=user_id)
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
        from .. import snapshot as snapmod
        path, _ = QFileDialog.getOpenFileName(self, 'Snapshot İçe Aktar', '', 'JSON (*.json)')
        if not path:
            return
        try:
            name, count = snapmod.import_snapshot(path)
            self.refresh_snaps()
            QMessageBox.information(self, 'Tamam',
                                    '{} paket içe aktarıldı:\n{}\nKlon hedefe bağlanıp Uygula ile kurun.'.format(count, name))
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, 'Hata', str(e))
