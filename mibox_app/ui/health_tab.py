# -*- coding: utf-8 -*-
"""Sağlık sekmesi: depolama/RAM çubukları + tek tıkla güvenli temizlik."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QLabel,
    QPushButton, QProgressBar, QMessageBox, QCheckBox, QLineEdit, QSizePolicy,
    QHeaderView,
)

from ..workers import HealthWorker, PackageActionWorker, Worker
from . import kit
from .flowlayout import FlowLayout


def _fmt_kb(kb):
    try:
        kb = int(kb)
    except (TypeError, ValueError):
        return '?'
    if kb >= 1024 * 1024:
        return '{:.1f} GB'.format(kb / (1024 * 1024))
    if kb >= 1024:
        return '{:.0f} MB'.format(kb / 1024)
    return '{} KB'.format(kb)


class HealthTab(QWidget):
    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._build()

    def _build(self):
        # 2 sutunlu kompakt izgara: tek butonlu gruplar devasa gorunmez.
        # Sol: durum + temizlik + onbellek + bakim. Sag: avci + izin + otobaslat.
        from PySide6.QtWidgets import QGridLayout
        root = kit.page(self)

        left = QVBoxLayout()
        left.setSpacing(kit.SPACING)
        right = QVBoxLayout()
        right.setSpacing(kit.SPACING)

        g = QGroupBox('Cihaz Sağlığı')
        gv = QVBoxLayout(g)
        gv.setSpacing(4)
        self.lbl_disk = QLabel('Depolama: ?')
        self.bar_disk = QProgressBar()
        self.bar_disk.setRange(0, 100)
        self.lbl_mem = QLabel('RAM: ?')
        self.bar_mem = QProgressBar()
        self.bar_mem.setRange(0, 100)
        self.lbl_pkg = QLabel('Paketler: ?')
        gv.addWidget(self.lbl_disk)
        gv.addWidget(self.bar_disk)
        gv.addWidget(self.lbl_mem)
        gv.addWidget(self.bar_mem)
        gv.addWidget(self.lbl_pkg)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self.btn_refresh = QPushButton('Yenile')
        self.btn_refresh.setProperty('accent', True)
        self.btn_refresh.clicked.connect(self.refresh)
        btn_row.addWidget(self.btn_refresh)
        btn_row.addStretch()
        gv.addLayout(btn_row)
        left.addWidget(g)

        g2 = QGroupBox('Güvenli Temizlik (tek tık)')
        v2 = QVBoxLayout(g2)
        v2.setSpacing(4)
        self._info_clean = QLabel('Yalnızca Güvenli kategorideki, korumalı OLMAYAN ve '
                      'şu an ÇALIŞMAYAN paketlerin verisi temizlenir. '
                      'Paket silinmez, devre dışı bırakılmaz.')
        self._info_clean.setWordWrap(True)
        self._info_clean.setStyleSheet(kit.muted(kit.dark_from(self)))
        v2.addWidget(self._info_clean)
        self.chk_disable_too = QCheckBox('Verisi temizlenenleri ayrıca devre dışı bırak')
        v2.addWidget(self.chk_disable_too)
        flow = FlowLayout()
        self.btn_clean = QPushButton('Güvenli Temizliği Başlat')
        self.btn_clean.setProperty('accent', True)
        self.btn_clean.clicked.connect(self._safe_clean)
        flow.addWidget(self.btn_clean)
        v2.addLayout(flow)
        self.lbl_clean = QLabel('')
        self.lbl_clean.setWordWrap(True)
        v2.addWidget(self.lbl_clean)
        left.addWidget(g2)

        g3 = QGroupBox('Önbellek')
        v3 = QVBoxLayout(g3)
        v3.setSpacing(4)
        self.btn_trim = QPushButton('Önbelleği Temizle')
        self.btn_trim.setToolTip('trim-caches: tum uygulama onbellekleri')
        self.btn_trim.clicked.connect(self._trim)
        kit.fit_buttons(self.btn_trim)
        trim_row = QHBoxLayout()
        trim_row.addWidget(self.btn_trim)
        trim_row.addStretch()
        v3.addLayout(trim_row)
        left.addWidget(g3)

        g7 = QGroupBox('Otomatik Bakım')
        v7 = QVBoxLayout(g7)
        v7.setSpacing(4)
        self.chk_maint = QCheckBox('Otomatik bakım açık (açılışta sağlık + önbellek)')
        try:
            self.chk_maint.setChecked(bool(self.core.config.auto_maint))
        except AttributeError:
            self.core.config.auto_maint = False
        self.chk_maint.toggled.connect(self._maint_toggle)
        self.btn_maint_now = QPushButton('Şimdi Çalıştır')
        self.btn_maint_now.setToolTip('Otomatik bakimi hemen çalıştır')
        self.btn_maint_now.clicked.connect(self._maint_now)
        kit.fit_buttons(self.btn_maint_now)
        mrow = QHBoxLayout()
        mrow.setSpacing(4)
        mrow.addWidget(self.chk_maint, 1)
        mrow.addWidget(self.btn_maint_now)
        v7.addLayout(mrow)
        self.lbl_maint = QLabel('')
        self.lbl_maint.setWordWrap(True)
        v7.addWidget(self.lbl_maint)
        left.addWidget(g7)

        g4 = QGroupBox('Depolama Avcısı (en çok yer kaplayanlar)')
        v4 = QVBoxLayout(g4)
        v4.setSpacing(4)
        self.btn_top = QPushButton('Top-15 Tara')
        self.btn_top.clicked.connect(self._storage_top)
        kit.fit_buttons(self.btn_top)
        top_row = QHBoxLayout()
        top_row.addWidget(self.btn_top)
        top_row.addStretch()
        v4.addLayout(top_row)
        self.grid_top = kit.make_table(2, ['Klasör', 'Boyut'])
        self.grid_top.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.grid_top.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.grid_top.setMaximumHeight(150)
        v4.addWidget(self.grid_top)
        right.addWidget(g4)

        g5 = QGroupBox('Uygulama İzinleri')
        v5 = QVBoxLayout(g5)
        v5.setSpacing(4)
        prow = QHBoxLayout()
        prow.setSpacing(4)
        self.txt_perm_pkg = QLineEdit()
        self.txt_perm_pkg.setPlaceholderText('paket adı (örn: ar.tvplayer.tv)...')
        self.btn_perm = QPushButton('İzinleri Göster')
        self.btn_perm.clicked.connect(self._show_perms)
        kit.fit_buttons(self.btn_perm)
        prow.addWidget(self.txt_perm_pkg, 1)
        prow.addWidget(self.btn_perm)
        v5.addLayout(prow)
        self.lbl_perms = QLabel('')
        self.lbl_perms.setWordWrap(True)
        self.lbl_perms.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v5.addWidget(self.lbl_perms)
        right.addWidget(g5)

        g6 = QGroupBox('Otomatik Başlayanlar (BOOT_COMPLETED dinleyenler)')
        v6 = QVBoxLayout(g6)
        v6.setSpacing(4)
        self.btn_autorun = QPushButton('Tara')
        self.btn_autorun.clicked.connect(self._autorun_scan)
        kit.fit_buttons(self.btn_autorun)
        auto_row = QHBoxLayout()
        auto_row.addWidget(self.btn_autorun)
        auto_row.addStretch()
        v6.addLayout(auto_row)
        self.grid_auto = kit.make_table(2, ['Paket', 'Kısıtla'])
        self.grid_auto.itemChanged.connect(self._auto_item_guard)
        self.grid_auto.itemChanged.connect(lambda _it: self._update_auto_count())
        self.grid_auto.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.grid_auto.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.grid_auto.setMaximumHeight(150)
        v6.addWidget(self.grid_auto)
        self.btn_autorun_restrict = QPushButton('Seçilenleri Kısıtla')
        self.btn_autorun_restrict.setProperty('accent', True)
        self.btn_autorun_restrict.clicked.connect(self._autorun_restrict)
        kit.fit_buttons(self.btn_autorun_restrict)
        self.btn_auto_all = QPushButton('Tümünü Seç')
        self.btn_auto_all.clicked.connect(lambda: self._auto_toggle_all(True))
        self.btn_auto_none = QPushButton('Seçimi Bırak')
        self.btn_auto_none.clicked.connect(lambda: self._auto_toggle_all(False))
        self.lbl_auto_sel = QLabel('')
        self.lbl_auto_sel.setStyleSheet(kit.faint(kit.dark_from(self)))
        kit.fit_buttons(self.btn_auto_all, self.btn_auto_none)
        flow6 = QHBoxLayout()
        flow6.addWidget(self.btn_auto_all)
        flow6.addWidget(self.btn_auto_none)
        flow6.addWidget(self.btn_autorun_restrict)
        flow6.addWidget(self.lbl_auto_sel)
        flow6.addStretch()
        v6.addLayout(flow6)
        right.addWidget(g6)

        left.addStretch()
        right.addStretch()
        for box in (g, g2, g3, g7, g4, g5, g6):
            try:
                box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            except (RuntimeError, AttributeError):
                pass
        cols = QGridLayout()
        cols.setSpacing(8)
        cols.setAlignment(Qt.AlignTop)
        cols.addLayout(left, 0, 0, Qt.AlignTop)
        cols.addLayout(right, 0, 1, Qt.AlignTop)
        cols.setColumnStretch(0, 9)
        cols.setColumnStretch(1, 11)
        root.addLayout(cols)

    def apply_theme(self):
        """Tema degisince: bilgi/seçim etiketleri yeni palete gecer."""
        try:
            dark = kit.dark_from(self)
            self._info_clean.setStyleSheet(kit.muted(dark))
            self.lbl_auto_sel.setStyleSheet(kit.faint(dark))
        except (RuntimeError, AttributeError):
            pass

    # ------------------------------------------------------------------
    def refresh(self):
        w = HealthWorker(self.core.engine, self.core.target)
        w.finished_ok.connect(self._show)
        self.window._run(w, desc='Sağlık Yenile: depolama/RAM/paket olculuyor')

    def _show(self, h):
        if 'disk_pct' in h:
            self.bar_disk.setValue(h['disk_pct'])
            self.lbl_disk.setText('Depolama (/data): %{} dolu — {} / {} boş: {}'.format(
                h['disk_pct'], _fmt_kb(h.get('disk_total_kb')), _fmt_kb(h.get('disk_avail_kb')),
                _fmt_kb(h.get('disk_avail_kb'))))
            self.bar_disk.setFormat('%p%')
        else:
            self.lbl_disk.setText('Depolama: okunamadı')
        if 'mem_pct' in h:
            self.bar_mem.setValue(h['mem_pct'])
            self.lbl_mem.setText('RAM: %{} kullanımda — toplam: {}'.format(
                h['mem_pct'], _fmt_kb(h.get('mem_total_kb'))))
        else:
            self.lbl_mem.setText('RAM: okunamadı')
        if 'pkg_total' in h:
            self.lbl_pkg.setText('Paketler: {} toplam, {} devre dışı, {} kaldırılmış (user 0)'.format(
                h.get('pkg_total', '?'), h.get('pkg_disabled', '?'), h.get('pkg_removed_u0', '?')))
        else:
            self.lbl_pkg.setText('Paketler: okunamadı')

    def _trim(self):
        w = Worker(lambda: self.core.engine.trim_caches(self.core.target))
        w.job_name = 'Önbellek temizleme'
        w.finished_ok.connect(lambda _: (self.lbl_clean.setText('Önbellek temizlendi.'),
                                         self.refresh()))
        self.window._run(w, desc='Sağlık: önbellek temizleniyor')

    def _storage_top(self):
        def do():
            return self.core.engine.storage_top(self.core.target)
        w = Worker(do)
        w.job_name = 'Depolama Top-N'
        w.finished_ok.connect(self._show_top)
        self.window._run(w, desc='Sağlık: depolama Top-N hesaplaniyor')

    def _show_top(self, items):
        from PySide6.QtWidgets import QTableWidgetItem as _TWI
        from PySide6.QtCore import Qt as _Qt
        self.grid_top.setRowCount(0)
        for e in items:
            r = self.grid_top.rowCount()
            self.grid_top.insertRow(r)
            pi = _TWI(e['path'])
            si = _TWI(_fmt_kb(e['kb']))
            for it in (pi, si):
                it.setFlags(_Qt.ItemIsEnabled | _Qt.ItemIsSelectable)
            self.grid_top.setItem(r, 0, pi)
            self.grid_top.setItem(r, 1, si)
        if not items:
            self.grid_top.setRowCount(1)
            self.grid_top.setItem(0, 0, _TWI('(bulunamadı)'))

    def _show_perms(self):
        pkg = self.txt_perm_pkg.text().strip()
        if not pkg:
            QMessageBox.information(self, 'İzinler', 'Önce paket adı yazın.')
            return

        def do():
            return self.core.engine.app_permissions(self.core.target, pkg)
        w = Worker(do)
        w.job_name = 'İzin okuma'
        w.finished_ok.connect(lambda res, p=pkg: self._render_perms(p, res))
        self.window._run(w, desc='Sağlık: izinler okunuyor: ' + pkg)

    def _autorun_scan(self):
        def do():
            self.core.engine.connect(self.core.target)
            return self.core.engine.autorun_receivers(self.core.target)
        w = Worker(do)
        w.job_name = 'Otomatik baslayan tarama'
        w.finished_ok.connect(self._show_autorun)
        self.window._run(w, desc='Sağlık: otomatik baslayanlar taraniyor')

    def _show_autorun(self, found):
        from PySide6.QtWidgets import QTableWidgetItem as _TWI3
        from PySide6.QtCore import Qt as _Qt3
        pkgs = sorted(found)
        self.grid_auto.setRowCount(0)
        for p in pkgs:
            r = self.grid_auto.rowCount()
            self.grid_auto.insertRow(r)
            pi = _TWI3('{}{}'.format(p, '' if len(found[p]) <= 1 else '  ({} alıcı)'.format(len(found[p]))))
            pi.setData(_Qt3.UserRole, p)
            pi.setFlags(_Qt3.ItemIsEnabled | _Qt3.ItemIsSelectable)
            ci = _TWI3()
            ci.setFlags(_Qt3.ItemIsUserCheckable | _Qt3.ItemIsEnabled)
            ci.setCheckState(_Qt3.Unchecked)
            self.grid_auto.setItem(r, 0, pi)
            self.grid_auto.setItem(r, 1, ci)
        self.lbl_maint.setText('{} otomatik başlayan paket bulundu.'.format(len(pkgs)))
        self._update_auto_count()

    def _auto_toggle_all(self, on):
        from PySide6.QtCore import Qt as _Qt
        st = _Qt.Checked if on else _Qt.Unchecked
        self.grid_auto.blockSignals(True)
        try:
            for row in range(self.grid_auto.rowCount()):
                it = self.grid_auto.item(row, 1)
                if it and (it.flags() & _Qt.ItemIsUserCheckable):
                    if it.checkState() != st:
                        it.setCheckState(st)
        finally:
            try:
                self.grid_auto.blockSignals(False)
            except (RuntimeError, AttributeError):
                pass
        self._update_auto_count()

    def _update_auto_count(self):
        from PySide6.QtCore import Qt as _Qt
        try:
            n = sum(1 for row in range(self.grid_auto.rowCount())
                    for _it in [self.grid_auto.item(row, 1)]
                    if _it is not None and (_it.flags() & _Qt.ItemIsUserCheckable)
                    and _it.checkState() == _Qt.Checked)
            self.lbl_auto_sel.setText('Seçili: {}/{}'.format(n, self.grid_auto.rowCount()))
        except (RuntimeError, AttributeError):
            pass

    def _auto_item_guard(self, item):
        # AppsTab'daki stack-overflow dersinden: sinyal yarisi olursa kilitle.
        # Bu tabloda bayrak degisimi yok; olasi ic-ice cagriyi kes.
        try:
            self.grid_auto.blockSignals(True)
        except (RuntimeError, AttributeError):
            pass
        finally:
            try:
                self.grid_auto.blockSignals(False)
            except (RuntimeError, AttributeError):
                pass

    def _autorun_restrict(self):
        from ..workers import BulkActionWorker
        from PySide6.QtCore import Qt as _Qt4
        pkgs = []
        for row in range(self.grid_auto.rowCount()):
            ci = self.grid_auto.item(row, 1)
            pi = self.grid_auto.item(row, 0)
            if ci and ci.checkState() == _Qt4.Checked and pi:
                pkgs.append(pi.data(_Qt4.UserRole))
        if not pkgs:
            QMessageBox.information(self, 'Seçim', 'Önce Kısıtla sütununda işaretleyin.')
            return
        from .dialogs import confirm_action
        if not confirm_action(self, 'restrict', pkgs,
                              self.core.config.friendly_name):
            return
        w = BulkActionWorker(self.core.engine, self.core.target, pkgs, True,
                             self.core.config.protected)
        w.finished_ok.connect(lambda res: QMessageBox.information(
            self, 'Tamam', '{} başarılı, {} atlandı.'.format(res.get('ok', 0), res.get('skip', 0))))
        self.window._run(w, desc='Sağlık: {} paket kısıtlanıyor'.format(len(pkgs)))

    def _maint_toggle(self, on):
        self.core.config.auto_maint = bool(on)
        self.core.config.save()
        self.lbl_maint.setText('Otomatik bakım {}.'.format('açık' if on else 'kapalı'))

    def _maint_now(self):
        def do():
            eng = self.core.engine
            t = self.core.target
            eng.connect(t)
            eng.trim_caches(t)
            return eng.health(t)
        w = Worker(do)
        w.job_name = 'Otomatik bakim'
        w.finished_ok.connect(self._maint_done)
        self.window._run(w, desc='Sağlık: otomatik bakim çalışıyor')

    def _maint_done(self, h):
        self._show(h)
        try:
            last = self.core.config.maint_last or 'hiç'
        except AttributeError:
            last = 'hiç'
            self.core.config.maint_last = ''
        import datetime as _dt
        self.core.config.maint_last = _dt.datetime.now().strftime('%Y-%m-%d %H:%M')
        self.core.config.save()
        self.lbl_maint.setText('Bakım tamamlandı (önbellek + sağlık). Önceki: {}'.format(last))

    def _render_perms(self, pkg, res):
        perms = res.get('all', [])
        if not perms:
            self.lbl_perms.setText(pkg + ': izin bilgisi okunamadı.')
            return
        risky = {'CAMERA', 'RECORD_AUDIO', 'ACCESS_FINE_LOCATION', 'ACCESS_COARSE_LOCATION',
                 'READ_CONTACTS', 'READ_CALL_LOG', 'READ_SMS', 'READ_PHONE_STATE'}
        lines = ['{}: {} izin ({} verilmiş)'.format(pkg, len(perms), len(res.get('granted', [])))]
        for p in perms:
            short = p['perm'].rsplit('.', 1)[-1]
            flag = ''
            if any(r in short for r in risky):
                flag = ' ⚠'
            lines.append('{} {}{}'.format('✓' if p['granted'] else '✗', short, flag))
        self.lbl_perms.setText('\n'.join(lines))

    def _safe_clean(self):
        from ..debloat_db import package_to_category

        def do():
            eng = self.core.engine
            t = self.core.target
            eng.connect(t)
            det = eng.list_packages_detailed(t, True)
            running_raw = eng.running_processes(t)
            pkgs_all = [e['package'] for e in det]
            running = eng.parse_running_packages(running_raw, pkgs_all)
            cands = []
            for e in det:
                p = e['package']
                if package_to_category(p) != 'guvenli':
                    continue
                if p in self.core.config.protected:
                    continue
                if p in running:
                    continue
                if not e.get('installed_user0', True):
                    continue
                cands.append(p)
            return cands

        def start(cands):
            if not cands:
                self.lbl_clean.setText('Temizlenecek güvenli paket bulunamadı.')
                return
            from .dialogs import confirm_action
            extra = 'Veri temizlenir' + (' + devre dışı birakilir.'
                                         if self.chk_disable_too.isChecked() else '.')
            if not confirm_action(self, 'clear', cands,
                                  self.core.config.friendly_name, extra):
                return
            acts = ['clear'] + (['disable'] if self.chk_disable_too.isChecked() else [])
            self._clean_queue = [(a, p) for a in acts for p in cands]
            self._clean_ok = 0
            self._clean_fail = 0
            self._run_next_clean()

        w = Worker(do)
        w.job_name = 'Güvenli temizlik adaylari'
        w.finished_ok.connect(start)
        self.window._run(w, desc='Sağlık: temizlik adaylari araniyor')

    def _run_next_clean(self):
        if not self._clean_queue:
            self.lbl_clean.setText('Temizlik tamam: {} başarılı, {} başarısız.'.format(
                self._clean_ok, self._clean_fail))
            self.refresh()
            try:
                self.window.tab_apps.refresh()
            except Exception:
                pass
            return
        action, pkg = self._clean_queue.pop(0)
        w = PackageActionWorker(self.core.engine, self.core.target, [pkg],
                                action, self.core.config.protected)
        w.finished_ok.connect(lambda res: self._clean_done(res))
        self.window._run(w, on_ok=lambda _: self._run_next_clean())

    def _clean_done(self, res):
        if isinstance(res, dict):
            self._clean_ok += res.get('ok', 0)
            self._clean_fail += res.get('fail', 0)
