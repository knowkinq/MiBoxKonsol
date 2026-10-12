# -*- coding: utf-8 -*-
"""Kurulum sekmesi: APK toplu kurma + HOME launcher + hızlandırma + konsol.

Kaynaklar: ADB AppControl (batch install/APKS), tvboxtools (set-home-activity,
animasyon kapatma, command gate), android-tv-debloat-toolkit (launcher akışı).
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox, QFileDialog, QComboBox,
    QLineEdit, QPlainTextEdit, QAbstractItemView,
)

from ..workers import Worker
from . import kit
from .flowlayout import FlowLayout


class InstallTab(QWidget):
    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._files = []
        self._build()

    def _build(self):
        root = kit.page(self)

        # --- APK kurulum ---
        g = QGroupBox('APK Kurulum (toplu)')
        gv = QVBoxLayout(g)
        gv.setSpacing(4)
        self._info = QLabel('APK dosyaları seç, tek tıkla kur. Split-APK (.apks dizini) '
                      'otomatik install-multiple ile kurulur. Kurulum öncesi '
                      'güvenlik snapshot alınır.')
        self._info.setWordWrap(True)
        self._info.setStyleSheet(kit.muted(kit.dark_from(self)))
        gv.addWidget(self._info)
        self.lst = QListWidget()
        self.lst.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.lst.setMaximumHeight(130)
        gv.addWidget(self.lst)
        flow = FlowLayout()
        self.btn_add = QPushButton('APK Ekle')
        self.btn_add.clicked.connect(self._add_files)
        self.btn_add_dir = QPushButton('Klasör Ekle (split)')
        self.btn_add_dir.clicked.connect(self._add_dir)
        self.btn_rm = QPushButton('Seçiliyi Çıkar')
        self.btn_rm.clicked.connect(self._remove_sel)
        self.btn_install = QPushButton('Tümünü Kur')
        self.btn_install.setProperty('accent', True)
        self.btn_install.clicked.connect(self._install_all)
        for b in (self.btn_add, self.btn_add_dir, self.btn_rm, self.btn_install):
            flow.addWidget(b)
        gv.addLayout(flow)
        self.lbl_inst = QLabel('')
        self.lbl_inst.setWordWrap(True)
        gv.addWidget(self.lbl_inst)
        root.addWidget(g)

        # --- HOME launcher ---
        g2 = QGroupBox('HOME Launcher (reboot dayanıklı)')
        v2 = QVBoxLayout(g2)
        v2.setSpacing(4)
        self._info2 = QLabel('tvboxtools yöntemi: cmd package set-home-activity ile kalıcı '
                       'HOME. Stok launcher silinmez, tek tıkla geri dönülür. '
                       'Önce alternatif launcher (Projectivy/FLauncher) kurulu olmalı! '
                       'Google TV kurulum sihirbazı HOME\'u kilitliyorsa (setupwraith) '
                       'engel otomatik çözülür: cihaz "kurulmuş" işaretlenir ve '
                       'sihirbaz devre dışı bırakılır.')
        self._info2.setWordWrap(True)
        self._info2.setStyleSheet(kit.muted(kit.dark_from(self)))
        v2.addWidget(self._info2)
        hrow = QHBoxLayout()
        hrow.setSpacing(4)
        self.cmb_launch = QComboBox()
        self.cmb_launch.setMinimumWidth(260)
        self.btn_launch_scan = QPushButton('Launcherları Tara')
        self.btn_launch_scan.clicked.connect(self._scan_launchers)
        self.btn_home_cur = QPushButton('Mevcut HOME')
        self.btn_home_cur.clicked.connect(self._show_home)
        hrow.addWidget(self.cmb_launch, 1)
        hrow.addWidget(self.btn_launch_scan)
        hrow.addWidget(self.btn_home_cur)
        v2.addLayout(hrow)
        flow2 = FlowLayout()
        self.btn_set_home = QPushButton('HOME Yap')
        self.btn_set_home.setProperty('accent', True)
        self.btn_set_home.clicked.connect(self._set_home)
        flow2.addWidget(self.btn_set_home)
        v2.addLayout(flow2)
        self.lbl_home = QLabel('Mevcut HOME: ?')
        v2.addWidget(self.lbl_home)
        root.addWidget(g2)

        # --- Hızlandırma ---
        g3 = QGroupBox('Hızlandırma (animasyon ölçekleri)')
        v3 = QVBoxLayout(g3)
        v3.setSpacing(4)
        brow = QHBoxLayout()
        brow.setSpacing(4)
        self.cmb_anim = QComboBox()
        self.cmb_anim.addItem('Kapalı (0) — en hızlı', '0')
        self.cmb_anim.addItem('Yarı (0.5)', '0.5')
        self.cmb_anim.addItem('Normal (1)', '1')
        self.btn_anim = QPushButton('Uygula')
        self.btn_anim.setProperty('accent', True)
        self.btn_anim.clicked.connect(self._set_anim)
        self.btn_anim_cur = QPushButton('Mevcut Değerler')
        self.btn_anim_cur.clicked.connect(self._show_anim)
        brow.addWidget(self.cmb_anim)
        brow.addWidget(self.btn_anim)
        brow.addWidget(self.btn_anim_cur)
        brow.addStretch()
        v3.addLayout(brow)
        self.lbl_anim = QLabel('Ölçekler: ?')
        v3.addWidget(self.lbl_anim)
        root.addWidget(g3)

        # --- Konsol (gate'li) ---
        g4 = QGroupBox('Komut Konsolu (kapılı — yıkıcı komutlar reddedilir)')
        v4 = QVBoxLayout(g4)
        v4.setSpacing(4)
        crow = QHBoxLayout()
        crow.setSpacing(4)
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
            QListWidgetItem(os.path.basename(f) + '  —  ' + f, self.lst)

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'APK Seç', '', 'Android Paketi (*.apk *.apks *.apkm *.xapk)')
        for p in paths:
            if p not in self._files:
                self._files.append(p)
        self._refresh_list()

    def _add_dir(self):
        d = QFileDialog.getExistingDirectory(self, 'Split-APK Klasörü Seç')
        if d and d not in self._files:
            self._files.append(d)
        self._refresh_list()

    def _remove_sel(self):
        for it in self.lst.selectedItems():
            full = it.text().rsplit('  —  ', 1)[-1]
            if full in self._files:
                self._files.remove(full)
        self._refresh_list()

    def _install_all(self):
        if not self._files:
            QMessageBox.information(self, 'Kurulum', 'Önce APK ekleyin.')
            return
        shown = '\n'.join(u'• ' + os.path.basename(f) for f in self._files[:8])
        if len(self._files) > 8:
            shown += u'\n… ve {} tane daha'.format(len(self._files) - 8)
        if QMessageBox.question(self, u'Onay — APK Kur',
                                u'{} dosya kurulsun mu?\n\n{}'.format(len(self._files), shown),
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        from .. import snapshot as snapmod

        def do():
            eng = self.core.engine
            t = self.core.target
            eng.connect(t)
            try:
                sname, _c = snapmod.take(eng, t)
            except Exception:
                sname = None
            ok, fail, msgs = 0, 0, []
            total = len(self._files)
            for i, f in enumerate(list(self._files), 1):
                try:
                    if os.path.isdir(f) or f.lower().endswith(('.apks', '.apkm', '.xapk')):
                        eng.install_multiple(t, f)
                    else:
                        eng.install_apk(t, f)
                    ok += 1
                    msgs.append('+ ' + os.path.basename(f))
                except Exception as e:
                    fail += 1
                    msgs.append('X {}: {}'.format(os.path.basename(f), e))
            try:
                eng.invalidate_pkg_cache(t)
            except Exception:
                pass
            return {'ok': ok, 'fail': fail, 'msgs': msgs, 'snap': sname}
        w = Worker(do)
        w.job_name = 'APK toplu kurma'
        w.finished_ok.connect(self._install_done)
        self.window._run(w, desc='Kurulum: {} dosya kuruluyor'.format(len(self._files)))

    def _install_done(self, res):
        lines = ['{} kuruldu, {} başarısız.'.format(res.get('ok', 0), res.get('fail', 0))]
        if res.get('snap'):
            lines.append('Güvenlik snapshot: {}'.format(res['snap']))
        lines += res.get('msgs', [])[:15]
        self.lbl_inst.setText('\n'.join(lines))
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
            self.cmb_launch.addItem('{}  ({})'.format(name, c), c)

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
        if QMessageBox.question(self, u'Onay — HOME Yap',
                                u'Kalıcı HOME yapılsın mı?\n\n• {}\n\n'
                                u'Stok launcher korunur, tek tıkla geri dönülür.\n'
                                u'Gerekirse Google TV kurulum sihirbazı (setupwraith) '
                                u'devre dışı bırakılıp cihaz "kurulmuş" işaretlenir.'.format(disp),
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

    # --- animasyon ---
    def _show_anim(self):
        def do():
            self.core.engine.connect(self.core.target)
            return self.core.engine.animator_scales(self.core.target)
        w = Worker(do)
        w.job_name = 'Animasyon okuma'
        w.finished_ok.connect(lambda d: self.lbl_anim.setText(
            'Ölçekler: pencere={} geçiş={} süre={}'.format(
                d.get('window_animation_scale'), d.get('transition_animation_scale'),
                d.get('animator_duration_scale'))))
        self.window._run(w, desc='Kurulum: animasyon olcekleri okunuyor')

    def _set_anim(self):
        val = self.cmb_anim.currentData()

        def do():
            eng = self.core.engine
            eng.connect(self.core.target)
            eng.set_animator_scales(self.core.target, val)
            return eng.animator_scales(self.core.target)
        w = Worker(do)
        w.job_name = 'Animasyon ayarlama'
        w.finished_ok.connect(lambda d: (self.lbl_anim.setText(
            'Ölçekler: pencere={} geçiş={} süre={}'.format(
                d.get('window_animation_scale'), d.get('transition_animation_scale'),
                d.get('animator_duration_scale'))),
            QMessageBox.information(self, 'Tamam', 'Animasyon ölçeği: ' + val)))
        self.window._run(w, desc='Kurulum: animasyon olcegi yaziliyor: ' + val)

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
