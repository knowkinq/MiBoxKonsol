# -*- coding: utf-8 -*-
"""Ayarlar sekmesi: tema, koruma listesi, bilinen uygulama adlari, genel."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QListWidget,
    QListWidgetItem, QMessageBox, QFileDialog, QPlainTextEdit, QApplication,
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
        root.setSpacing(8)

        preferences = QGroupBox()
        preferences.setObjectName('settingsCard')
        pref_layout = QVBoxLayout(preferences)
        pref_layout.setSpacing(8)
        pref_title = QLabel('Görünüm ve günlük')
        pref_title.setObjectName('cardTitle')
        pref_layout.addWidget(pref_title)
        self.chk_dark = kit.CheckBox('Koyu tema kullan')
        self.chk_dark.setChecked(self.core.config.dark_mode)
        self.chk_dark.toggled.connect(self._on_dark)
        self.chk_log = kit.CheckBox('Günlük kayıtlarını logs/ klasörüne yaz')
        self.chk_log.setChecked(self.core.config.log_to_file)
        self.chk_log.toggled.connect(self._on_log_toggle)
        self.chk_keyboard_nav = kit.CheckBox('Kumanda sekmesinde klavye ok tuşları ile yönetim')
        self.chk_keyboard_nav.setChecked(getattr(self.core.config, 'keyboard_nav', True))
        self.chk_keyboard_nav.toggled.connect(lambda on: (setattr(self.core.config, 'keyboard_nav', on), self.core.config.save()))
        self.chk_grant_perms = kit.CheckBox('APK kurulumunda tüm izinleri otomatik ver (-g) · dikkat')
        self.chk_grant_perms.setChecked(getattr(self.core.config, 'install_grant_perms', False))
        self.chk_grant_perms.toggled.connect(lambda on: (setattr(self.core.config, 'install_grant_perms', on), self.core.config.save()))
        self.chk_auto_connect = None
        pref_layout.addWidget(self.chk_dark)
        pref_layout.addWidget(self.chk_log)
        pref_layout.addWidget(self.chk_keyboard_nav)
        pref_layout.addWidget(self.chk_grant_perms)
        self.lbl_paths = QLabel('APK: {}\nEkran: {}\nLog: {}'.format(APK_DIR, SHOT_DIR, LOG_DIR))
        self.lbl_paths.setProperty('semanticRole', 'muted')
        self.lbl_paths.setStyleSheet(kit.muted(kit.dark_from(self)))
        self.lbl_paths.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_paths.setWordWrap(True)
        pref_layout.addWidget(self.lbl_paths)
        root.addWidget(preferences)

        info_card = QGroupBox()
        info_card.setObjectName('settingsCard')
        info_layout = QVBoxLayout(info_card)
        info_layout.setSpacing(8)
        info_title = QLabel('Sürüm ve kurulum bilgisi')
        info_title.setObjectName('cardTitle')
        info_layout.addWidget(info_title)
        info_layout.addWidget(kit.hint_label('Destek isterken bu bilgiyi kopyalayıp paylaşabilirsiniz.'))
        self.txt_info = QPlainTextEdit()
        self.txt_info.setReadOnly(True)
        self.txt_info.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.txt_info.setMaximumHeight(112)
        self.txt_info.setStyleSheet(kit.mono_style())
        info_layout.addWidget(self.txt_info)
        info_actions = QHBoxLayout()
        self.btn_copy_info = QPushButton('Panoya Kopyala')
        self.btn_copy_info.setProperty('role', 'secondary')
        self.btn_copy_info.clicked.connect(self._copy_info)
        self.btn_refresh_info = QPushButton('Yenile')
        self.btn_refresh_info.setProperty('role', 'quiet')
        self.btn_refresh_info.clicked.connect(self._refresh_info)
        info_actions.addWidget(self.btn_copy_info)
        info_actions.addWidget(self.btn_refresh_info)
        info_actions.addStretch(1)
        info_layout.addLayout(info_actions)
        root.addWidget(info_card)
        self._refresh_info()

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(kit.SPACING)

        protected_card = QGroupBox()
        protected_card.setObjectName('settingsCard')
        protected_layout = QVBoxLayout(protected_card)
        protected_layout.setSpacing(8)
        protected_title = QLabel('Koruma listesi')
        protected_title.setObjectName('cardTitle')
        protected_layout.addWidget(protected_title)
        protected_layout.addWidget(kit.hint_label(
            'Listedeki paketlere uygulama işlemleri uygulanmaz.'))
        self.lst_protected = QListWidget()
        self.lst_protected.setMaximumHeight(110)
        self.lst_protected.setMinimumHeight(60)
        self._refresh_protected_list()
        protected_layout.addWidget(self.lst_protected)
        protected_actions = QHBoxLayout()
        self.txt_prot = QLineEdit()
        self.txt_prot.setPlaceholderText('Paket adı, ör. com.example.app')
        self.txt_prot.returnPressed.connect(self._add_protected)
        btn_add = QPushButton('Ekle')
        btn_add.setProperty('role', 'secondary')
        btn_add.clicked.connect(self._add_protected)
        btn_rm = QPushButton('Kaldır')
        btn_rm.setProperty('role', 'quiet')
        btn_rm.clicked.connect(self._rm_protected)
        protected_actions.addWidget(self.txt_prot, 1)
        protected_actions.addWidget(btn_add)
        protected_actions.addWidget(btn_rm)
        protected_layout.addLayout(protected_actions)
        bottom_row.addWidget(protected_card, 1)

        backup_card = QGroupBox()
        backup_card.setObjectName('settingsCard')
        backup_layout = QVBoxLayout(backup_card)
        backup_layout.setSpacing(8)
        backup_title = QLabel('Ayar yedeği · Kaydet')
        backup_title.setObjectName('cardTitle')
        backup_layout.addWidget(backup_title)
        backup_layout.addWidget(kit.hint_label(
            'Yapılandırmayı JSON olarak dışa aktarın, geri yükleyin veya kaydedin.'))

        backup_actions = QHBoxLayout()
        backup_actions.setSpacing(8)
        self.btn_export_cfg = QPushButton('Dışarı Aktar')
        self.btn_export_cfg.setProperty('role', 'secondary')
        self.btn_export_cfg.clicked.connect(self._export_cfg)
        self.btn_import_cfg = QPushButton('İçeri Aktar')
        self.btn_import_cfg.setProperty('role', 'secondary')
        self.btn_import_cfg.clicked.connect(self._import_cfg)
        backup_actions.addWidget(self.btn_export_cfg)
        backup_actions.addWidget(self.btn_import_cfg)
        backup_layout.addLayout(backup_actions)

        backup_layout.addStretch(1)

        self.btn_save = QPushButton('Ayarları Kaydet')
        self.btn_save.setProperty('role', 'primary')
        self.btn_save.setFixedHeight(34)
        self.btn_save.clicked.connect(self._save)
        backup_layout.addWidget(self.btn_save)

        bottom_row.addWidget(backup_card, 1)
        root.addLayout(bottom_row)
        root.addStretch(1)

    def apply_theme(self):
        """Tema degisince: yol etiketi + bilgi paneli yeni palete gecer."""
        try:
            self.lbl_paths.setStyleSheet(kit.muted(kit.dark_from(self)))
            self.txt_info.setStyleSheet(kit.mono_style())
        except (RuntimeError, AttributeError):
            pass

    # ------------------------------------------------------------------
    def _refresh_info(self):
        """Surum/kurulum bilgisini yeniden oku (tek kaynak: diagnostics)."""
        from .. import diagnostics
        try:
            self.txt_info.setPlainText(diagnostics.metin())
        except Exception as e:  # noqa: BLE001
            self.txt_info.setPlainText('Bilgi alinamadi: {}'.format(e))

    def _refresh_protected_list(self):
        self.lst_protected.clear()
        packages = self.core.config.protected
        if not packages:
            empty_item = QListWidgetItem('Koruma listeniz boş.')
            empty_item.setFlags(Qt.NoItemFlags)
            empty_item.setTextAlignment(Qt.AlignCenter)
            empty_item.setSizeHint(QSize(0, 44))
            self.lst_protected.addItem(empty_item)
            self.lst_protected.setMaximumHeight(60)
            return

        self.lst_protected.setMaximumHeight(110)
        for package in packages:
            self.lst_protected.addItem(QListWidgetItem(package))

    def _copy_info(self):
        QApplication.clipboard().setText(self.txt_info.toPlainText())
        QMessageBox.information(self, 'Tamam', 'Kurulum bilgisi panoya kopyalandi.')

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
            self._refresh_protected_list()
            self.core.config.save()
        self.txt_prot.clear()

    def _rm_protected(self):
        it = self.lst_protected.currentItem()
        if it:
            self.core.config.protected = [p for p in self.core.config.protected if p != it.text()]
            self._refresh_protected_list()
            self.core.config.save()

    def _save(self):
        if not self.core.config.save():
            QMessageBox.critical(
                self, 'Kaydedilemedi',
                self.core.config.save_error or 'Ayarlar kaydedilemedi.')
            return
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
        path, _ = QFileDialog.getOpenFileName(self, 'Ayar Yedegi Seç', '', 'JSON (*.json)')
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError('Geçersiz yedek dosyası.')
            config = self.core.config
            original = config.to_dict()
            candidate = dict(original)
            for k in ('protected', 'device_history'):
                if k in data:
                    if type(data[k]) is not list or any(type(x) is not str for x in data[k]):
                        raise ValueError('Yedekte {} listesi geçersiz.'.format(k))
                    candidate[k] = list(data[k])
            for k in ('include_system', 'dark_mode', 'log_to_file',
                      'screenshot_hd', 'auto_maint', 'show_unlisted', 'show_removed',
                      'keyboard_nav', 'install_grant_perms', 'auto_connect_last'):
                if k in data:
                    if type(data[k]) is not bool:
                        raise ValueError('Yedekte {} değeri true/false olmalıdır.'.format(k))
                    candidate[k] = data[k]
            for k in ('last_target', 'maint_last'):
                if k in data:
                    if type(data[k]) is not str:
                        raise ValueError('Yedekte {} metin olmalıdır.'.format(k))
                    candidate[k] = data[k]
            if 'auto_refresh_min' in data:
                if type(data['auto_refresh_min']) is not int or data['auto_refresh_min'] < 0:
                    raise ValueError('Yedekte auto_refresh_min negatif olmayan tam sayı olmalıdır.')
                candidate['auto_refresh_min'] = data['auto_refresh_min']
            if 'user_id' in data:
                if type(data['user_id']) is not int or not 0 <= data['user_id'] <= 21474:
                    raise ValueError('Yedekte user_id geçersiz.')
                candidate['user_id'] = data['user_id']
            for key, value in candidate.items():
                setattr(config, key, list(value) if isinstance(value, list) else value)
            if not config.save():
                for key, value in original.items():
                    setattr(config, key, list(value) if isinstance(value, list) else value)
                message = config.save_error or 'Ayar yedeği kaydedilemedi.'
                QMessageBox.critical(self, 'Hata', message)
                return
            config.save_known_apps()
            debloat = getattr(self.window, 'tab_debloat', None)
            sync_user = getattr(debloat, 'sync_user_id_from_config', None)
            if callable(sync_user):
                sync_user()
            self._refresh_protected_list()
            QMessageBox.information(self, 'Tamam', 'Ayar yedeği içe aktarıldı.')
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, 'Hata', str(e))
