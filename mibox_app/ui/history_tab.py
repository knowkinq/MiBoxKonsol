# -*- coding: utf-8 -*-
"""Geçmiş sekmesi: kalıcı işlem kayıtları + tek tıkla geri alma + durum kaydı."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..action_labels import ACTION_TR_LOG as ACTION_TR  # gecmis/durum kisa adi
from ..workers import PackageActionWorker, SmartRemoveWorker, SnapshotWorker, Worker
from . import kit
from .actions_dialog import search_key

COL_TS = 0
COL_TARGET = 1
COL_USER = 2
COL_ACTION = 3
COL_PKG = 4
COL_METHOD = 5
COL_OK = 6


class HistoryTab(QWidget):
    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._records = []
        self._snap_worker = None
        self._undo_worker = None
        self._undo_queue = []
        self._connection_generation = 0
        connection_changed = getattr(self.core, 'connection_changed', None)
        if connection_changed is not None:
            connection_changed.connect(self._on_connection_changed)
        self._build()

    def _on_connection_changed(self, *_):
        self._connection_generation += 1
        if hasattr(self, 'cmb_snap'):
            self._sync_snap_controls()
        if hasattr(self, 'btn_undo'):
            self._update_selection_state()

    def _target_is_current(self, target, generation):
        return (generation == self._connection_generation
                and getattr(self.core, 'connected', False)
                and getattr(self.core, 'target', None) == target
                and not getattr(self.window, '_connection_busy', False))

    def _build(self):
        root = kit.page(self)

        self._hint = QLabel(
            'İşlem geçmişinde başarılı ve geri alınabilir kayıtları seçin. Durum kaydı paketlerin '
            'kurulu/etkin ve arka plan kısıtlama ayarlarını saklar; uygulama verilerini yedeklemez.')
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(kit.muted(kit.dark_from(self)))
        root.addWidget(self._hint)

        snap_box = kit.section('Cihaz durum kayıtları')
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
        self.btn_snap_take = QPushButton('Durum kaydı al')
        self.btn_snap_take.setProperty('accent', True)
        self.btn_snap_take.clicked.connect(self._snap_take)
        self.btn_snap_diff = QPushButton('Farkları Göster')
        self.btn_snap_diff.clicked.connect(self._snap_diff)
        self.btn_snap_apply = QPushButton('Durum kaydını uygula')
        self.btn_snap_apply.setProperty('danger', True)
        self.btn_snap_apply.clicked.connect(self._snap_apply)
        self.btn_snap_del = QPushButton('Sil')
        self.btn_snap_del.clicked.connect(self._snap_delete)
        self.btn_snap_export = QPushButton('Dışa aktar')
        self.btn_snap_export.setToolTip('Paket durum kaydını JSON dosyasına aktarın ve başka cihaza taşıyın.')
        self.btn_snap_export.clicked.connect(self._snap_export)
        self.btn_snap_import = QPushButton('İçe Aktar')
        self.btn_snap_import.clicked.connect(self._snap_import)

        self.btn_snap_more = QToolButton()
        self.btn_snap_more.setText('Diğer')
        self.btn_snap_more.setToolTip('Durum kayıtlarını içe/dışa aktarma, uygulama ve silme')
        self.btn_snap_more.setPopupMode(QToolButton.InstantPopup)
        snap_menu = QMenu(self.btn_snap_more)
        snap_menu.addSection('Başka cihaza taşıma')
        self._snap_menu_actions = []
        for button in (self.btn_snap_export, self.btn_snap_import):
            action = snap_menu.addAction(button.text())
            action.setToolTip(button.toolTip())
            action.triggered.connect(
                lambda _checked=False, target=button: target.click())
            self._snap_menu_actions.append((button, action))
        snap_menu.addSection('Cihaz işlemleri')
        for button in (self.btn_snap_apply, self.btn_snap_del):
            action = snap_menu.addAction(button.text())
            action.setToolTip(button.toolTip())
            action.triggered.connect(
                lambda _checked=False, target=button: target.click())
            self._snap_menu_actions.append((button, action))
        self.btn_snap_more.setMenu(snap_menu)
        self.cmb_snap.currentIndexChanged.connect(self._sync_snap_controls)
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

        self.lbl_clone = QLabel(
            'Taşıma: Bu cihazda durum kaydı alıp dışa aktarın; diğer cihazda içe aktarın ve uygulayın.')
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
        self.grid.setSortingEnabled(False)

        search_row = QHBoxLayout()
        search_row.setSpacing(kit.SPACING)
        self.search_history = QLineEdit()
        self.search_history.setPlaceholderText('Geçmişte ara: paket, işlem, hedef, kullanıcı…')
        self.search_history.setClearButtonEnabled(False)
        self.search_history.textChanged.connect(self._apply_history_filter)
        self.btn_search_clear = QPushButton('Temizle')
        self.btn_search_clear.setToolTip('Arama metnini temizle')
        self.btn_search_clear.clicked.connect(self.search_history.clear)
        self.btn_search_clear.setEnabled(False)
        search_row.addWidget(self.search_history, 1)
        search_row.addWidget(self.btn_search_clear)
        root.addLayout(search_row)

        root.addWidget(self.grid, 1)

        self.lbl_record_detail = kit.status_label('Bir kayıt seçerek sonucunu ve geri alma bilgisini görün.')
        root.addWidget(self.lbl_record_detail)

        flow = QHBoxLayout()
        flow.setSpacing(kit.SPACING)
        self.btn_refresh = QPushButton('Geçmişi Yenile')
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_undo = QPushButton('Seçiliyi Geri Al')
        self.btn_undo.setProperty('accent', True)
        self.btn_undo.setEnabled(False)
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
        self.grid.itemSelectionChanged.connect(self._update_selection_state)
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

    @classmethod
    def _undo_record_status(cls, histmod, rec):
        if not isinstance(rec, dict):
            return None, 'kayıt tanınmıyor'
        if not rec.get('ok'):
            return None, 'işlem başarısız olmuş'
        user_id = rec.get('user_id', 0)
        if type(user_id) is not int or not 0 <= user_id <= 21474:
            return None, 'kullanıcı kimliği geçersiz'
        inverse = cls._inverse_for_record(histmod, rec)
        if not inverse:
            return None, 'bu işlem için geri alma eşlemesi yok'
        package = rec.get('package')
        if type(package) is not str or not package.strip():
            return None, 'paket bilgisi geçersiz'
        target = rec.get('target')
        if type(target) is not str or not target.strip():
            return None, 'kayıtlı cihaz bilgisi yok'
        return inverse, ''

    def _record_explanation(self, histmod, rec, current_context=True):
        status = 'Başarılı' if rec.get('ok') else 'Başarısız'
        inverse, problem = self._undo_record_status(histmod, rec)
        if problem:
            return '{} · Geri alınamaz: {}.'.format(status, problem)
        explanation = '{} · Geri alınabilir: {}.'.format(
            status, ACTION_TR.get(inverse, inverse))
        if current_context:
            target = rec.get('target')
            if getattr(self.window, '_connection_busy', False):
                explanation += ' Bağlantı işlemi sürüyor.'
            elif not getattr(self.core, 'connected', False):
                explanation += ' Geri almak için {} cihazına bağlanın.'.format(target)
            elif getattr(self.core, 'target', None) != target:
                explanation += ' Şu an başka cihaz bağlı; {} hedefine bağlanın.'.format(target)
        return explanation

    def refresh(self):
        from .. import history as histmod
        self._records = histmod.read_all()
        self.grid.setRowCount(0)
        for record_index, rec in enumerate(self._records):
            r = self.grid.rowCount()
            self.grid.insertRow(r)
            inverse, problem = self._undo_record_status(histmod, rec)
            undo_label = 'Geri alınabilir' if inverse and not problem else 'Geri alınamaz'
            result = 'Başarılı' if rec.get('ok') else 'Başarısız'
            user_id = rec.get('user_id', 0)
            action = rec.get('action', '')
            cells = [
                rec.get('ts', ''),
                str(rec.get('target') or ''),
                'user {}'.format(user_id) if type(user_id) is int else '?',
                ACTION_TR.get(action, action) if type(action) is str else str(action),
                rec.get('package', ''),
                rec.get('method', '') or '-',
                '{} · {}'.format(result, undo_label),
            ]
            for c, txt in enumerate(cells):
                it = QTableWidgetItem('' if txt is None else str(txt))
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                # Keep only the stable original index in Qt item data. QVariant
                # may copy dicts on round-trip, so object identity is not safe.
                it.setData(Qt.UserRole, record_index)
                if c == COL_OK:
                    it.setToolTip(self._record_explanation(histmod, rec, current_context=False))
                self.grid.setItem(r, c, it)
        kit.empty_state(self.grid, 'Henüz işlem yok',
                        'Cihaz işlemleri tamamlandıkça kayıtlar bu tabloda görünür.')
        self._apply_history_filter()
        self._update_selection_state()

    def _apply_history_filter(self, *_):
        terms = search_key(self.search_history.text()).split()
        visible = 0
        for row in range(self.grid.rowCount()):
            text = ' '.join(
                self.grid.item(row, col).text()
                for col in range(self.grid.columnCount())
                if self.grid.item(row, col) is not None)
            matches = all(term in search_key(text) for term in terms)
            self.grid.setRowHidden(row, not matches)
            visible += int(matches)
        self.btn_search_clear.setEnabled(bool(self.search_history.text()))
        if terms:
            self.lbl_summary.setText('{} / {} kayıt gösteriliyor.'.format(
                visible, len(self._records)))
        else:
            self.lbl_summary.setText('{} kayıt.'.format(len(self._records)))
        self._update_selection_state()

    def _selected_record_entries(self):
        rows = sorted({index.row() for index in self.grid.selectedIndexes()
                       if not self.grid.isRowHidden(index.row())})
        records = []
        for row in rows:
            item = self.grid.item(row, COL_PKG)
            if item is None:
                return None
            record_index = item.data(Qt.UserRole)
            if type(record_index) is not int or not 0 <= record_index < len(self._records):
                return None
            records.append(self._records[record_index])
        return records

    def _selected_records(self):
        records = self._selected_record_entries()
        return records if records is not None else []

    def _update_selection_state(self, *_):
        from .. import history as histmod
        records = self._selected_record_entries()
        can_undo = bool(records)
        if records is None:
            self.lbl_record_detail.setText('Seçili kayıt tanınmıyor; geçmişi yenileyin.')
            can_undo = False
        elif not records:
            self.lbl_record_detail.setText(
                'Bir kayıt seçerek sonucunu ve geri alma bilgisini görün.')
        else:
            explanations = [self._record_explanation(histmod, rec) for rec in records]
            if len(records) == 1:
                self.lbl_record_detail.setText(explanations[0])
            else:
                succeeded = sum(bool(rec.get('ok')) for rec in records)
                undoable = sum(not self._undo_record_status(histmod, rec)[1]
                               for rec in records)
                lines = ['{} kayıt seçili · başarılı: {} · başarısız: {} · geri alınabilir: {}.'.format(
                    len(records), succeeded, len(records) - succeeded, undoable)]
                lines.extend('• ' + explanation for explanation in explanations[:2])
                if len(records) > 2:
                    lines.append('• … {} kayıt daha'.format(len(records) - 2))
                self.lbl_record_detail.setText('\n'.join(lines))

            if can_undo:
                current_target = getattr(self.core, 'target', None)
                if (not getattr(self.core, 'connected', False)
                        or not current_target
                        or getattr(self.window, '_connection_busy', False)):
                    can_undo = False
                else:
                    can_undo = all(
                        not self._undo_record_status(histmod, rec)[1]
                        and rec.get('target') == current_target
                        for rec in records)
        self.btn_undo.setEnabled(can_undo and not self._snapshot_busy())

    def _undo_selected(self):
        if self._snapshot_busy():
            self.lbl_summary.setText('Devam eden durum kaydı veya geri alma işleminin bitmesini bekleyin.')
            return
        from .. import history as histmod
        self._update_selection_state()
        recs = self._selected_records()
        if not recs:
            QMessageBox.information(self, 'Seçim', 'Önce satır seçin.')
            return
        # Validate every record that could be undone before scheduling any work.
        undoable = []
        skipped = []
        for rec in recs:
            inverse, problem = self._undo_record_status(histmod, rec)
            if problem == 'işlem başarısız olmuş':
                skipped.append((rec.get('package', ''), 'işlem zaten başarısızdı'))
                continue
            if problem:
                skipped.append((rec.get('package', ''), problem))
                continue
            user_id = rec.get('user_id', 0)
            undoable.append((rec, inverse, user_id))
        if not undoable:
            QMessageBox.information(self, 'Geri Al',
                                    'Seçili satırların hiçbiri geri alınamaz.\n' +
                                    '\n'.join('X {}: {}'.format(p, m) for p, m in skipped))
            return
        if not self.core.connected:
            QMessageBox.warning(self, 'Geri Al',
                                'Geri alma için cihaza bağlı olmanız gerekir.')
            return
        if getattr(self.window, '_connection_busy', False):
            QMessageBox.warning(self, 'Geri Al',
                                'Bağlantı işlemi sürüyor; tamamlanınca yeniden deneyin.')
            return
        current_target = self.core.target
        connection_generation = self._connection_generation
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
        if self._snapshot_busy() or not self._target_is_current(current_target, connection_generation):
            QMessageBox.warning(self, 'Geri Al',
                                'Hedef veya bağlantı değişti; geri alma başlatılmadı.')
            return
        # sırayla uygula (tek worker zinciri yerine gruplu)
        self._undo_queue = [(action, pkg, user_id)
                            for (action, user_id), packages in groups.items()
                            for pkg in packages]
        self._undo_fail = list(skipped)
        self._undo_target = current_target
        self._undo_connection_generation = connection_generation
        self._run_next_undo()

    def _run_next_undo(self):
        if (getattr(self, '_undo_queue', None)
                and not self._target_is_current(
                    self._undo_target, self._undo_connection_generation)):
            self._undo_fail.extend(
                (pkg, 'hedef veya bağlantı değişti; işlem uygulanmadı')
                for _action, pkg, _user_id in self._undo_queue)
            self._undo_queue.clear()
        if not self._undo_queue:
            self._sync_snap_controls()
            self._update_selection_state()
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
        target = self._undo_target
        generation = self._undo_connection_generation
        if action == 'smart':
            if user_id != 0:
                w = Worker(self._run_user_undo, 'smart', pkg, user_id, target)
                w.job_name = 'Geçmiş geri alma'
            else:
                w = SmartRemoveWorker(self.core.engine, target, [pkg],
                                      self.core.config.protected, user_id=user_id)
            real = action
        elif user_id == 0 and action not in ('restrict', 'unrestrict'):
            real = action
            w = PackageActionWorker(self.core.engine, target, [pkg],
                                    real,
                                    self.core.config.protected)
        else:
            real = action
            w = Worker(self._run_user_undo, real, pkg, user_id, target)
            w.job_name = 'Geçmiş geri alma'
        w.finished_ok.connect(
            lambda res, a=real, p=pkg, t=target, g=generation:
            self._undo_done(res, a, p, t, g))
        self._undo_worker = w
        self._sync_snap_controls()
        self._update_selection_state()

        def failed(error):
            self._undo_fail.append((pkg, str(error)))
            self._undo_fail.extend((pending, 'önceki işlem tamamlanamadı; uygulanmadı')
                                   for _action, pending, _uid in self._undo_queue)
            self._undo_queue.clear()

        def finished():
            if self._undo_worker is not w:
                return
            self._undo_worker = None
            if (getattr(self.window, '_closing', False)
                    or getattr(self.window, '_close_pending', False)):
                self._undo_queue.clear()
                return
            self._sync_snap_controls()
            self._update_selection_state()
            self._run_next_undo()

        w.failed.connect(failed)
        w.finished.connect(finished)
        try:
            self.window._run(w)
        except Exception as error:
            failed(error)
            finished()

    def _run_user_undo(self, action, pkg, user_id, target):
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
            engine.connect(target)
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
                    method(target, pkg, user_id=user_id)
                    try:
                        engine.invalidate_pkg_cache(target)
                    except Exception:
                        pass
                    histmod.append(target, action, pkg, ok=True, user_id=user_id)
                    return {'ok': 1, 'fail': 0}
                if index == len(methods[action]) - 1 and user_id == 0:
                    method(target, pkg)
                    try:
                        engine.invalidate_pkg_cache(target)
                    except Exception:
                        pass
                    histmod.append(target, action, pkg, ok=True, user_id=user_id)
                    return {'ok': 1, 'fail': 0}
                positional = [p for p in parameters.values()
                              if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                            inspect.Parameter.POSITIONAL_OR_KEYWORD)]
                if index < len(methods[action]) - 1 and len(positional) >= 3:
                    method(target, pkg, user_id)
                    try:
                        engine.invalidate_pkg_cache(target)
                    except Exception:
                        pass
                    histmod.append(target, action, pkg, ok=True, user_id=user_id)
                    return {'ok': 1, 'fail': 0}
            raise RuntimeError('user {} için geri alma API’si desteklenmiyor.'.format(user_id))
        except Exception as error:  # noqa: BLE001
            histmod.append(target, action, pkg, ok=False, user_id=user_id)
            return {'ok': 0, 'fail': 1, 'details': [(pkg, False, str(error))]}

    def _undo_done(self, res, action, pkg, target=None, generation=None):
        if (target is not None and generation is not None
                and not self._target_is_current(target, generation)):
            return
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
                    w.writerow([kit.csv_cell(rec.get('ts', '')), kit.csv_cell(rec.get('target', '')),
                                rec.get('user_id', 0), rec.get('action', ''),
                                kit.csv_cell(rec.get('package', '')), kit.csv_cell(rec.get('method', '')),
                                'ok' if rec.get('ok') else 'fail'])
            QMessageBox.information(self, 'Tamam', 'Aktarıldı:\n' + path)
        except OSError as e:
            QMessageBox.critical(self, 'Hata', str(e))

    def _clear(self):
        from .. import history as histmod
        if QMessageBox.question(self, 'Temizle', 'İşlem geçmişi silinsin mi?') != QMessageBox.Yes:
            return
        try:
            histmod.clear()
        except OSError as exc:
            QMessageBox.warning(
                self, 'Silinemedi',
                'İşlem geçmişi dosyası silinemedi:\n{}'.format(exc))
            return
        self.refresh()

    # --- snapshot ---
    def refresh_snaps(self):
        from .. import snapshot as snapmod
        selected = self.cmb_snap.currentData()
        self.cmb_snap.blockSignals(True)
        self.cmb_snap.clear()
        for name in snapmod.list_snapshots():
            self.cmb_snap.addItem(name, name)
        if selected:
            index = self.cmb_snap.findData(selected)
            if index >= 0:
                self.cmb_snap.setCurrentIndex(index)
        self.cmb_snap.blockSignals(False)
        if self.cmb_snap.count() == 0:
            self.cmb_snap.addItem('(durum kaydı yok)', '')
        self._sync_snap_controls()

    def _snapshot_busy(self):
        return bool(self._snap_worker is not None or self._undo_worker is not None
                    or self._undo_queue)

    def _snapshot_context(self):
        if (self._snapshot_busy() or not getattr(self.core, 'connected', False)
                or not getattr(self.core, 'target', None)
                or getattr(self.window, '_connection_busy', False)
                or getattr(self.window, '_closing', False)
                or getattr(self.window, '_close_pending', False)):
            self.lbl_summary.setText('Bağlantıyı ve devam eden işlemleri kontrol edin; işlem başlatılmadı.')
            return None
        return self.core.engine, self.core.target, self._connection_generation

    def _snapshot_context_current(self, context):
        engine, target, generation = context
        return (self._target_is_current(target, generation)
                and self.core.engine is engine)

    def _sync_snap_controls(self, *_):
        has_record = bool(self.cmb_snap.currentData())
        idle = not self._snapshot_busy()
        connected = (bool(getattr(self.core, 'connected', False))
                     and bool(getattr(self.core, 'target', None))
                     and not getattr(self.window, '_connection_busy', False))
        self.cmb_snap.setEnabled(idle)
        self.btn_snap_take.setEnabled(idle and connected)
        self.btn_snap_diff.setEnabled(idle and has_record and connected)
        self.btn_snap_apply.setEnabled(idle and has_record and connected)
        self.btn_snap_del.setEnabled(idle and has_record)
        self.btn_snap_export.setEnabled(idle and has_record)
        self.btn_snap_import.setEnabled(idle)
        for button, action in self._snap_menu_actions:
            action.setEnabled(button.isEnabled())
        self.btn_snap_more.setEnabled(any(action.isEnabled()
                                          for _button, action in self._snap_menu_actions))

    def _start_snapshot_worker(self, worker, context, on_ok, description):
        if (self._snapshot_busy() or not self._snapshot_context_current(context)
                or getattr(self.window, '_closing', False)
                or getattr(self.window, '_close_pending', False)):
            return False
        results, errors = [], []
        worker.finished_ok.connect(results.append)
        worker.failed.connect(errors.append)
        worker.progress.connect(
            lambda c, t: self.lbl_summary.setText('Durum kaydı: {}/{}'.format(c, t))
            if self._snapshot_context_current(context) else None)
        self._snap_worker = worker
        self._sync_snap_controls()
        self._update_selection_state()

        def finished():
            if self._snap_worker is not worker:
                return
            self._snap_worker = None
            self._sync_snap_controls()
            self._update_selection_state()
            if (not self._snapshot_context_current(context)
                    or getattr(self.window, '_closing', False)
                    or getattr(self.window, '_close_pending', False)):
                return
            if results:
                self.lbl_summary.setText('Durum kaydı işlemi tamamlandı; ayrıntılar sonuçta gösterilir.')
                on_ok(results[0])
            else:
                self.lbl_summary.setText('Durum kaydı tamamlanamadı: ' + str(errors[-1])
                                         if errors else 'Durum kaydı tamamlanamadı.')

        worker.finished.connect(finished)
        try:
            self.window._run(worker, desc=description)
        except Exception as error:
            errors.append(str(error))
            finished()
            return False
        return True

    def _snap_take(self):
        context = self._snapshot_context()
        if context is None:
            return
        engine, target, _generation = context
        user_id = int(self.core.config.user_id or 0)
        w = SnapshotWorker(engine, target, 'take', user_id=user_id)
        self._start_snapshot_worker(w, context, self._snap_taken,
                                    'Geçmiş: durum kaydı alınıyor')

    def _snap_taken(self, res):
        self.refresh_snaps()
        index = self.cmb_snap.findData(res.get('name', ''))
        if index >= 0:
            self.cmb_snap.setCurrentIndex(index)
        QMessageBox.information(self, 'Durum kaydı',
                                '{} paket durumu kaydedildi:\n{}'.format(
                                    res.get('count', 0), res.get('name', '')))

    def _snap_diff(self):
        context = self._snapshot_context()
        if context is None:
            return
        name = self.cmb_snap.currentData()
        if not name:
            QMessageBox.information(self, 'Durum kaydı', 'Önce bir durum kaydı seçin.')
            return
        try:
            from .. import snapshot as snapmod
            snap = snapmod.load(name)
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, 'Durum kaydı', str(error))
            return
        engine, target, _generation = context

        def do():
            w.check_cancel()
            if not self._snapshot_context_current(context):
                from ..workers import CancelledError
                raise CancelledError('bağlantı değişti')
            result = snapmod.diff_current(engine, target, snap)
            w.check_cancel()
            return result

        w = Worker(do)
        w.job_name = 'Durum kaydı farkı'
        self._start_snapshot_worker(w, context, self._show_diff,
                                    'Geçmiş: durum kaydı farkı hesaplanıyor')

    def _show_diff(self, diffs):
        if not diffs:
            QMessageBox.information(self, 'Fark', 'Fark yok: cihaz durum kaydıyla aynı durumda.')
            return
        lines = ['{} paket farklı:'.format(len(diffs))]
        for pkg, _w, _h, act in diffs[:40]:
            action_text = ' → '.join(act) if isinstance(act, (tuple, list)) else act
            lines.append('{} -> {}'.format(pkg, action_text))
        if len(diffs) > 40:
            lines.append('... ve {} tane daha'.format(len(diffs) - 40))
        QMessageBox.information(self, 'Fark', '\n'.join(lines))

    def _snap_apply(self):
        context = self._snapshot_context()
        if context is None:
            return
        name = self.cmb_snap.currentData()
        if not name:
            QMessageBox.information(self, 'Durum kaydı', 'Önce bir durum kaydı seçin.')
            return
        try:
            from .. import snapshot as snapmod
            snap = snapmod.load(name)
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, 'Durum kaydı', 'Kayıt okunamadı; işlem yapılmadı:\n' + str(error))
            return
        engine, target, _generation = context
        user_id = snap.get('user_id', 0)
        packages = snap['packages']
        counts = {}
        for entry in packages.values():
            if not entry['installed_user0']:
                state = 'kullanıcı için kaldırılmış'
            elif not entry['enabled']:
                state = 'devre dışı'
            elif entry['restricted']:
                state = 'arka plan kısıtlı'
            else:
                state = 'etkin'
            counts[state] = counts.get(state, 0) + 1
        detail = '{} paket ({}).'.format(
            len(packages), ', '.join('{}: {}'.format(k, v) for k, v in sorted(counts.items())))
        body = ('{}\n{}\n\nKayıt kaynağı: {}\nHedef cihaz: {}\nAndroid kullanıcısı: {}'
                '\n\nPaketlerin kurulum ve etkinlik durumu değişebilir. '
                'Uygulama verileri geri yüklenmez. Korunan paketler atlanır.'
                '\n\nBu kaydı hedef cihaza uygulamak istiyor musunuz?').format(
                    name, detail, snap['target'], target, user_id)
        if QMessageBox.question(self, 'Onay — Durum Kaydını Uygula', body,
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        if self._snapshot_busy() or not self._snapshot_context_current(context):
            QMessageBox.warning(self, 'Durum kaydı',
                                'Bağlantı veya işlem durumu değişti; işlem başlatılmadı.')
            return
        w = SnapshotWorker(engine, target, 'apply', snapshot_name=name,
                           protected=self.core.config.protected, user_id=user_id,
                           snapshot_data=snap)
        self._start_snapshot_worker(w, context, self._snap_applied,
                                    'Geçmiş: durum kaydı uygulanıyor')

    def _snap_applied(self, res):
        from ..workers import format_action_result
        self.refresh()
        try:
            self.window.tab_apps.refresh()
        except Exception:
            pass
        QMessageBox.information(self, 'Durum kaydı',
                                format_action_result(res, self.core.config.friendly_name))

    def _snap_delete(self):
        if self._snapshot_busy():
            return
        from .. import snapshot as snapmod
        name = self.cmb_snap.currentData()
        if not name:
            return
        if QMessageBox.question(self, u'Onay — Durum Kaydını Sil',
                                u'Silinsin mi? (Geri alınamaz!)\n\n• {}'.format(name),
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        if self._snapshot_busy():
            return
        if not snapmod.delete(name):
            QMessageBox.critical(self, 'Durum kaydı', 'Kayıt silinemedi; dosya erişimini kontrol edin.')
        self.refresh_snaps()

    def _snap_export(self):
        if self._snapshot_busy():
            return
        from .. import snapshot as snapmod
        name = self.cmb_snap.currentData()
        if not name:
            QMessageBox.information(self, 'Durum kaydı', 'Önce bir durum kaydı seçin.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Durum Kaydını Dışa Aktar', name, 'JSON (*.json)')
        if not path:
            return
        try:
            if self._snapshot_busy():
                return
            snapmod.export_snapshot(name, path)
            QMessageBox.information(self, 'Tamam', 'Aktarıldı:\n' + path)
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, 'Hata', str(e))

    def _snap_import(self):
        if self._snapshot_busy():
            return
        from .. import snapshot as snapmod
        path, _ = QFileDialog.getOpenFileName(self, 'Durum Kaydını İçe Aktar', '', 'JSON (*.json)')
        if not path:
            return
        try:
            if self._snapshot_busy():
                return
            name, count = snapmod.import_snapshot(path)
            self.refresh_snaps()
            QMessageBox.information(self, 'Tamam',
                                    '{} paket durumu içe aktarıldı:\n{}\nDiğer cihaza bağlanıp Uygula ile uygulayın.'.format(count, name))
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, 'Hata', str(e))
