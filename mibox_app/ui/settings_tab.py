# -*- coding: utf-8 -*-
"""Ayarlar sekmesi: tema, koruma listesi, bilinen uygulama adlari, genel."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QCheckBox, QPushButton, QListWidget,
    QListWidgetItem, QMessageBox, QFileDialog,
)

from . import kit

from ..config import APK_DIR, SHOT_DIR, LOG_DIR


class SettingsTab(QWidget):
    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._build()

    def _build(self):
        root = kit.page(self)

        # --- Gorunum ---
        g_theme = QGroupBox('Gorunum')
        tf = QFormLayout(g_theme)
        self.chk_dark = QCheckBox('Koyu tema (kapatinca acik tema)')
        self.chk_dark.setChecked(self.core.config.dark_mode)
        self.chk_dark.toggled.connect(self._on_dark)
        tf.addRow(self.chk_dark)
        root.addWidget(g_theme)

        # --- Genel ---
        g_gen = QGroupBox('Genel')
        gf = QFormLayout(g_gen)
        self.chk_log = QCheckBox('Logu dosyaya yaz (logs/)')
        self.chk_log.setChecked(self.core.config.log_to_file)
        self.chk_log.toggled.connect(self._on_log_toggle)
        gf.addRow(self.chk_log)
        self.lbl_paths = QLabel('APK: {}\nEkran: {}\nLog: {}'.format(APK_DIR, SHOT_DIR, LOG_DIR))
        self.lbl_paths.setStyleSheet(kit.muted(kit.dark_from(self)))
        self.lbl_paths.setTextInteractionFlags(Qt.TextSelectableByMouse)
        gf.addRow(self.lbl_paths)
        root.addWidget(g_gen)

        # --- Koruma listesi ---
        g_prot = QGroupBox('Koruma Listesi (bu paketlere islem uygulanmaz)')
        gp = QVBoxLayout(g_prot)
        self.lst_protected = QListWidget()
        for p in self.core.config.protected:
            self.lst_protected.addItem(QListWidgetItem(p))
        gp.addWidget(self.lst_protected)
        row = QHBoxLayout()
        self.txt_prot = QLineEdit()
        self.txt_prot.setPlaceholderText('Paket ekle (orn: com.example.app)')
        self.txt_prot.returnPressed.connect(self._add_protected)
        btn_add = QPushButton('Ekle')
        btn_add.clicked.connect(self._add_protected)
        btn_rm = QPushButton('Kaldir')
        btn_rm.clicked.connect(self._rm_protected)
        row.addWidget(self.txt_prot)
        row.addWidget(btn_add)
        row.addWidget(btn_rm)
        gp.addLayout(row)
        root.addWidget(g_prot)

        # --- Yedek / geri yukleme ---
        g_bak = QGroupBox('Ayar Yedegi')
        bak = QHBoxLayout(g_bak)
        self.btn_export_cfg = QPushButton('Ayarlari Disari Aktar')
        self.btn_export_cfg.clicked.connect(self._export_cfg)
        self.btn_import_cfg = QPushButton('Ayarlari Ice Aktar')
        self.btn_import_cfg.clicked.connect(self._import_cfg)
        bak.addWidget(self.btn_export_cfg)
        bak.addWidget(self.btn_import_cfg)
        bak.addStretch()
        root.addWidget(g_bak)

        root.addStretch()

        # --- Kaydet ---
        self.btn_save = QPushButton('Ayarlari Kaydet')
        self.btn_save.setProperty('accent', True)
        self.btn_save.clicked.connect(self._save)
        root.addWidget(self.btn_save)

    def apply_theme(self):
        """Tema degisince: yol etiketi yeni palete gecer."""
        try:
            self.lbl_paths.setStyleSheet(kit.muted(kit.dark_from(self)))
        except (RuntimeError, AttributeError):
            pass

    # ------------------------------------------------------------------
    def _on_dark(self, on):
        self.core.config.dark_mode = bool(on)
        self.core.config.save()
        try:
            self.window.apply_theme()
        except Exception:
            pass

    def _on_log_toggle(self, on):
        self.core.config.log_to_file = bool(on)
        self.core.config.save()

    def _add_protected(self):
        p = self.txt_prot.text().strip()
        if not p:
            return
        if p not in self.core.config.protected:
            self.core.config.protected.append(p)
            self.lst_protected.addItem(QListWidgetItem(p))
            self.core.config.save()
        self.txt_prot.clear()

    def _rm_protected(self):
        it = self.lst_protected.currentItem()
        if it:
            self.core.config.protected = [p for p in self.core.config.protected if p != it.text()]
            self.lst_protected.takeItem(self.lst_protected.row(it))
            self.core.config.save()

    def _save(self):
        self.core.config.save()
        # kalinti temizligi: eski bilinen-ad dosyasi varsa silinir
        self.core.config.save_known_apps()
        QMessageBox.information(self, 'Kaydedildi', 'Ayarlar kaydedildi.')

    def _export_cfg(self):
        import json
        path, _ = QFileDialog.getSaveFileName(self, 'Ayar Yedegi', 'mibox-ayar-yedek.json',
                                              'JSON (*.json)')
        if not path:
            return
        try:
            data = self.core.config.to_dict()
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, 'Tamam', 'Yedeklendi:\n' + path)
        except OSError as e:
            QMessageBox.critical(self, 'Hata', str(e))

    def _import_cfg(self):
        import json
        path, _ = QFileDialog.getOpenFileName(self, 'Ayar Yedegi Sec', '', 'JSON (*.json)')
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError('Gecersiz yedek dosyasi.')
            for k in ('protected', 'device_history'):
                if k in data and isinstance(data[k], list):
                    setattr(self.core.config, k, [str(x) for x in data[k]])
            for k in ('include_system', 'dark_mode', 'log_to_file',
                      'screenshot_hd', 'auto_maint', 'show_unlisted', 'show_removed'):
                if k in data:
                    setattr(self.core.config, k, bool(data[k]))
            for k in ('last_target', 'maint_last'):
                if k in data:
                    setattr(self.core.config, k, str(data[k]))
            if 'auto_refresh_min' in data:
                try:
                    self.core.config.auto_refresh_min = int(data['auto_refresh_min'])
                except (TypeError, ValueError):
                    pass
            if 'user_id' in data:
                try:
                    self.core.config.user_id = int(data['user_id'])
                except (TypeError, ValueError):
                    pass
            self.core.config.save()
            self.core.config.save_known_apps()
            self.lst_protected.clear()
            for p in self.core.config.protected:
                self.lst_protected.addItem(QListWidgetItem(p))
            QMessageBox.information(self, 'Tamam', 'Ayarlar geri yuklendi. Programi yeniden baslatin.')
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, 'Hata', str(e))
