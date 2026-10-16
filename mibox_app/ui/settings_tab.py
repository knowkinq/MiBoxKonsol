# -*- coding: utf-8 -*-
"""Ayarlar sekmesi: tema, koruma listesi, bilinen uygulama adlari, genel."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QListWidget,
    QListWidgetItem, QMessageBox, QFileDialog, QPlainTextEdit, QApplication,
    QDialog, QDialogButtonBox,
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
        info_layout.addWidget(kit.hint_label(
            'Bilgi yerel dosya yolları ve kullanıcı adınızı içerebilir; kopyalayıp paylaşmadan önce gözden geçirin.'))
        self.txt_info = QPlainTextEdit()
        self.txt_info.setReadOnly(True)
        self.txt_info.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.txt_info.setMaximumHeight(112)
        self.txt_info.setStyleSheet(kit.mono_style())
        info_layout.addWidget(self.txt_info)
        info_actions = kit.action_bar()
        self.btn_share_info = QPushButton('Paylaşım özeti')
        self.btn_share_info.setProperty('role', 'primary')
        self.btn_share_info.setToolTip('Dosya yolu ve cihaz bilgisi içermeyen sürüm özetini önizleyin.')
        self.btn_share_info.clicked.connect(self._show_support_summary)
        self.btn_copy_info = QPushButton('Tam bilgiyi kopyala')
        self.btn_copy_info.setProperty('role', 'secondary')
        self.btn_copy_info.clicked.connect(self._copy_info)
        self.btn_refresh_info = QPushButton('Yenile')
        self.btn_refresh_info.setProperty('role', 'quiet')
        self.btn_refresh_info.clicked.connect(self._refresh_info)
        info_actions.addWidget(self.btn_share_info)
        info_actions.addWidget(self.btn_copy_info)
        info_actions.addWidget(self.btn_refresh_info)
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
        protected_search_row = QHBoxLayout()
        protected_search_row.setSpacing(6)
        self.txt_protected_search = QLineEdit()
        self.txt_protected_search.setPlaceholderText('Koruma listesinde ara')
        self.txt_protected_search.setClearButtonEnabled(True)
        self.txt_protected_search.textChanged.connect(self._filter_protected_list)
        protected_search_row.addWidget(self.txt_protected_search, 1)
        self.lbl_protected_count = kit.hint_label()
        self.lbl_protected_count.setWordWrap(False)
        self.lbl_protected_count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        protected_search_row.addWidget(self.lbl_protected_count)
        protected_layout.addLayout(protected_search_row)
        self.lst_protected = QListWidget()
        self.lst_protected.setMaximumHeight(96)
        self.lst_protected.setMinimumHeight(54)
        self.lst_protected.itemSelectionChanged.connect(
            self._update_protected_remove_state)
        protected_layout.addWidget(self.lst_protected)
        protected_actions = QHBoxLayout()
        self.txt_prot = QLineEdit()
        self.txt_prot.setPlaceholderText('Paket adı, ör. com.example.app')
        self.txt_prot.returnPressed.connect(self._add_protected)
        btn_add = QPushButton('Ekle')
        btn_add.setProperty('role', 'secondary')
        btn_add.clicked.connect(self._add_protected)
        self.btn_rm_protected = QPushButton('Kaldır')
        self.btn_rm_protected.setProperty('role', 'quiet')
        self.btn_rm_protected.setToolTip('Seçili paketi koruma listesinden kaldır')
        self.btn_rm_protected.setEnabled(False)
        self.btn_rm_protected.clicked.connect(self._rm_protected)
        protected_actions.addWidget(self.txt_prot, 1)
        protected_actions.addWidget(btn_add)
        protected_actions.addWidget(self.btn_rm_protected)
        protected_layout.addLayout(protected_actions)
        self._refresh_protected_list()
        bottom_row.addWidget(protected_card, 1)

        backup_card = QGroupBox()
        backup_card.setObjectName('settingsCard')
        backup_layout = QVBoxLayout(backup_card)
        backup_layout.setSpacing(8)
        backup_title = QLabel('Ayar yedeği · Kaydet')
        backup_title.setObjectName('cardTitle')
        backup_layout.addWidget(backup_title)
        backup_layout.addWidget(kit.hint_label(
            'Tercih değişiklikleri hemen kaydedilir. “Ayarları Kaydet” geçerli yapılandırmayı elle kaydeder; JSON yedeğini dışa veya içe aktarabilirsiniz.'))

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
        else:
            for package in packages:
                item = QListWidgetItem(package)
                item.setData(Qt.UserRole, package)
                self.lst_protected.addItem(item)
        self._filter_protected_list()

    def _filter_protected_list(self, *_):
        query = self.txt_protected_search.text().strip().casefold()
        packages = self.core.config.protected
        visible = 0
        for row in range(self.lst_protected.count()):
            item = self.lst_protected.item(row)
            package = item.data(Qt.UserRole)
            if package is None:
                item.setHidden(bool(query) or bool(packages))
                continue
            matches = query in package.casefold()
            item.setHidden(not matches)
            if matches:
                visible += 1
        self.lbl_protected_count.setText(
            'Görünen: {}/{} paket'.format(visible, len(packages)))
        self._update_protected_remove_state()

    def _update_protected_remove_state(self):
        selected = self.lst_protected.selectedItems()
        package = selected[0].data(Qt.UserRole) if len(selected) == 1 else None
        removable = (isinstance(package, str)
                     and package in self.core.config.protected
                     and not selected[0].isHidden()) if package is not None else False
        self.btn_rm_protected.setEnabled(removable)

    def _copy_info(self):
        QApplication.clipboard().setText(self.txt_info.toPlainText())
        QMessageBox.information(self, 'Tamam', 'Kurulum bilgisi panoya kopyalandi.')

    def _show_support_summary(self):
        from .. import diagnostics
        try:
            summary = diagnostics.paylasim_metni()
        except Exception:
            QMessageBox.warning(self, 'Destek özeti', 'Sürüm özeti hazırlanamadı. Yeniden deneyin.')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Paylaşım için destek özeti')
        layout = QVBoxLayout(dialog)
        explanation = QLabel(
            'Yalnızca uygulama ve ortam sürümleri. Kullanıcı adı, dosya yolları, '
            'cihaz adresleri ve günlük kayıtları eklenmez.')
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(summary)
        preview.setAccessibleName('Paylaşılacak destek özeti')
        layout.addWidget(preview, 1)
        result = QLabel('Kopyalamadan önce içeriği inceleyebilirsiniz.')
        result.setWordWrap(True)
        layout.addWidget(result)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText('Kapat')
        buttons.rejected.connect(dialog.reject)
        copy = buttons.addButton('Özeti kopyala', QDialogButtonBox.ActionRole)

        def copy_summary():
            QApplication.clipboard().setText(preview.toPlainText())
            result.setText('Destek özeti panoya kopyalandı.')
        copy.clicked.connect(copy_summary)
        layout.addWidget(buttons)
        available = self.screen().availableGeometry()
        dialog.resize(min(620, available.width() - 32), min(380, available.height() - 48))
        dialog.exec()

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
        selected = self.lst_protected.selectedItems()
        package = selected[0].data(Qt.UserRole) if len(selected) == 1 else None
        if (not isinstance(package, str)
                or package not in self.core.config.protected
                or selected[0].isHidden()):
            self._update_protected_remove_state()
            return
        self.core.config.protected = [
            p for p in self.core.config.protected if p != package]
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
        import os
        import tempfile
        path, _ = QFileDialog.getSaveFileName(self, 'Ayar Yedegi', 'mibox-ayar-yedek.json',
                                              'JSON (*.json)')
        if not path:
            return
        temp_path = None
        try:
            data = self.core.config.to_dict()
            destination_dir = os.path.dirname(os.path.abspath(path))
            with tempfile.NamedTemporaryFile(
                    mode='w', encoding='utf-8', dir=destination_dir,
                    prefix='.mibox-ayar-yedek-', suffix='.tmp',
                    delete=False) as f:
                temp_path = f.name
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
            temp_path = None
            QMessageBox.information(self, 'Tamam', 'Yedeklendi:\n' + path)
        except (OSError, TypeError, ValueError) as e:
            QMessageBox.critical(self, 'Hata', str(e))
        finally:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

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
            candidate.update(type(config).validated_values(data, strict=True)[0])
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
            for widget, value in (
                    (self.chk_dark, config.dark_mode),
                    (self.chk_log, config.log_to_file),
                    (self.chk_keyboard_nav, config.keyboard_nav),
                    (self.chk_grant_perms, config.install_grant_perms)):
                previous = widget.blockSignals(True)
                widget.setChecked(bool(value))
                widget.blockSignals(previous)
            install_tab = getattr(self.window, 'tab_install_inner', None)
            install_grant = getattr(install_tab, 'chk_grant_perms', None)
            if install_grant is not None:
                install_grant.setChecked(bool(config.install_grant_perms))
            if original.get('dark_mode') != config.dark_mode:
                apply_theme = getattr(self.window, 'apply_theme', None)
                if callable(apply_theme):
                    apply_theme()
            self._refresh_protected_list()
            QMessageBox.information(self, 'Tamam', 'Ayar yedeği içe aktarıldı.')
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, 'Hata', str(e))
