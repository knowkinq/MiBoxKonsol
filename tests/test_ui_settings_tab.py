# -*- coding: utf-8 -*-
"""settings_tab: tercihler, koruma listesi, bilgi paneli ve yedek akislari."""
import json
import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
)

from mibox_app import diagnostics as diag
from mibox_app.config import APK_DIR, LOG_DIR, SHOT_DIR
from mibox_app.ui import kit
from mibox_app.ui.settings_tab import SettingsTab


class _Ayar:
    def __init__(self):
        self.dark_mode = True
        self.log_to_file = False
        self.keyboard_nav = True
        self.install_grant_perms = False
        self.protected = []
        self.save_error = None
        self.save_ok = True
        self.save_count = 0
        self.known_saved = 0

    def save(self):
        self.save_count += 1
        return self.save_ok

    def save_known_apps(self):
        self.known_saved += 1

    def to_dict(self):
        return {'dark_mode': self.dark_mode,
                'log_to_file': self.log_to_file,
                'keyboard_nav': self.keyboard_nav,
                'install_grant_perms': self.install_grant_perms,
                'protected': list(self.protected)}

    @classmethod
    def validated_values(cls, data, strict=True):
        known = {}
        for key in ('dark_mode', 'log_to_file', 'keyboard_nav',
                    'install_grant_perms', 'protected'):
            if key in data:
                known[key] = data[key]
        return known, []


class _Debloat:
    def __init__(self):
        self.sync = 0

    def sync_user_id_from_config(self):
        self.sync += 1


class _Kurulum:
    def __init__(self):
        self.chk_grant_perms = None


class _Cekirdek:
    def __init__(self):
        self.config = _Ayar()


class _Pencere:
    def __init__(self):
        self.tema = 0
        self.tab_debloat = _Debloat()
        self.tab_install_inner = _Kurulum()

    def apply_theme(self):
        self.tema += 1


class _MinimalPencere:
    """Opsiyonel kancalari olmayan pencere."""


@pytest.fixture
def tab(qtbot, monkeypatch):
    monkeypatch.setattr(diag, 'metin', lambda: 'BILGI')
    core = _Cekirdek()
    win = _Pencere()
    win.tab_install_inner.chk_grant_perms = kit.CheckBox()
    t = SettingsTab(core, win)
    qtbot.addWidget(t)
    return t, core, win


def test_kurulum_ogeleri(tab):
    t, core, _win = tab

    assert t.chk_dark.isChecked() is True
    assert t.chk_log.isChecked() is False
    assert t.chk_keyboard_nav.isChecked() is True
    assert t.chk_grant_perms.isChecked() is False
    assert t.chk_auto_connect is None
    assert t.txt_info.toPlainText() == 'BILGI'
    assert t.lbl_paths.text() == 'APK: {}\nEkran: {}\nLog: {}'.format(
        APK_DIR, SHOT_DIR, LOG_DIR)
    assert t.lbl_paths.wordWrap() is True
    assert t.lbl_paths.textInteractionFlags() & Qt.TextSelectableByMouse
    assert t.lbl_paths.styleSheet() == kit.muted(kit.dark_from(t))
    assert t.txt_info.styleSheet() == kit.mono_style()
    assert t.txt_info.isReadOnly() is True
    assert t.txt_info.maximumHeight() == 112
    assert t.btn_share_info.text() == 'Paylaşım özeti'
    assert t.btn_copy_info.text() == 'Tam bilgiyi kopyala'
    assert t.btn_refresh_info.text() == 'Yenile'
    assert t.btn_rm_protected.text() == 'Kaldır'
    assert t.btn_rm_protected.isEnabled() is False
    assert t.btn_export_cfg.text() == 'Dışarı Aktar'
    assert t.btn_import_cfg.text() == 'İçeri Aktar'
    assert t.btn_save.text() == 'Ayarları Kaydet'
    assert core.config.save_count == 0

    bos = t.lst_protected.item(0)
    assert bos.text() == 'Koruma listeniz boş.'
    assert bos.flags() == Qt.NoItemFlags
    assert bos.textAlignment() == Qt.AlignCenter
    assert bos.sizeHint().height() == 44
    assert t.lbl_protected_count.text() == 'Görünen: 0/0 paket'


def test_toggle_tercihleri(tab, monkeypatch):
    t, core, win = tab

    t.chk_dark.setChecked(False)
    assert core.config.dark_mode is False
    assert core.config.save_count == 1
    assert win.tema == 1

    def patla():
        raise RuntimeError('tema yok')

    monkeypatch.setattr(win, 'apply_theme', patla)
    t.chk_dark.setChecked(True)
    assert core.config.dark_mode is True
    assert win.tema == 1  # hata yutuldu

    t.chk_log.setChecked(True)
    assert core.config.log_to_file is True
    t.chk_keyboard_nav.setChecked(False)
    assert core.config.keyboard_nav is False
    t.chk_grant_perms.setChecked(True)
    assert core.config.install_grant_perms is True
    assert core.config.save_count == 5


def test_koruma_listesi_ekleme_ve_filtre(tab):
    t, core, _win = tab

    t._add_protected()  # bos metin
    t.txt_prot.setText('   ')
    t._add_protected()
    assert core.config.protected == []

    t.txt_prot.setText(' com.yeni ')
    t._add_protected()
    assert core.config.protected == ['com.yeni']
    assert t.txt_prot.text() == ''
    assert t.lst_protected.count() == 1
    assert t.lst_protected.item(0).text() == 'com.yeni'
    assert t.lst_protected.item(0).data(Qt.UserRole) == 'com.yeni'
    assert t.lbl_protected_count.text() == 'Görünen: 1/1 paket'

    t.txt_prot.setText('com.yeni')
    t._add_protected()
    assert core.config.protected == ['com.yeni']

    core.config.protected.append('com.yedek')
    t._refresh_protected_list()
    assert t.lst_protected.count() == 2

    t.txt_protected_search.setText('COM.YED')
    assert t.lbl_protected_count.text() == 'Görünen: 1/2 paket'
    assert t.lst_protected.item(0).isHidden() is True
    assert t.lst_protected.item(1).isHidden() is False

    t.txt_protected_search.setText('zzz')
    assert t.lbl_protected_count.text() == 'Görünen: 0/2 paket'


def test_koruma_bos_ogesi_arama_ile_gizlenir(tab):
    t, _core, _win = tab

    assert t.lst_protected.item(0).isHidden() is False
    t.txt_protected_search.setText('x')
    assert t.lst_protected.item(0).isHidden() is True


def test_koruma_kaldirma_ve_secim_durumu(tab):
    t, core, _win = tab
    core.config.protected = ['com.a', 'com.b']
    t._refresh_protected_list()

    t._rm_protected()  # secim yok: sessiz
    assert core.config.protected == ['com.a', 'com.b']
    assert t.btn_rm_protected.isEnabled() is False

    t.lst_protected.item(0).setSelected(True)
    assert t.btn_rm_protected.isEnabled() is True

    t.lst_protected.setSelectionMode(QAbstractItemView.MultiSelection)
    t.lst_protected.item(1).setSelected(True)
    assert len(t.lst_protected.selectedItems()) == 2
    assert t.btn_rm_protected.isEnabled() is False
    t.lst_protected.setSelectionMode(QAbstractItemView.SingleSelection)
    t.lst_protected.clearSelection()

    t.lst_protected.item(1).setSelected(True)
    assert t.btn_rm_protected.isEnabled() is True
    t._rm_protected()
    assert core.config.protected == ['com.a']
    assert t.lst_protected.count() == 1
    assert t.btn_rm_protected.isEnabled() is False

    onceki = core.config.save_count
    t.lst_protected.item(0).setSelected(True)
    assert t.btn_rm_protected.isEnabled() is True
    t.txt_protected_search.setText('zzz')  # secili oge gizlenir
    assert t.btn_rm_protected.isEnabled() is False
    t._rm_protected()  # gizli oge: kaldirilmaz
    assert core.config.protected == ['com.a']
    assert core.config.save_count == onceki


def test_kopyala_tam_bilgi(tab, monkeypatch):
    t, _core, _win = tab
    bilgiler = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgiler.append(a))

    t.btn_copy_info.click()

    assert QApplication.clipboard().text() == 'BILGI'
    assert bilgiler[0][1] == 'Tamam'
    assert bilgiler[0][2] == 'Kurulum bilgisi panoya kopyalandi.'


def test_refresh_info_hata_yolu(tab, monkeypatch):
    t, _core, _win = tab

    def patla():
        raise RuntimeError('yok')

    monkeypatch.setattr(diag, 'metin', patla)
    t.btn_refresh_info.click()
    assert t.txt_info.toPlainText() == 'Bilgi alinamadi: yok'


def test_apply_theme_ve_yutma(tab, monkeypatch):
    t, _core, _win = tab

    t.apply_theme()
    assert t.lbl_paths.styleSheet() == kit.muted(kit.dark_from(t))
    assert t.txt_info.styleSheet() == kit.mono_style()

    def patla(dark=True):
        raise RuntimeError('stil yok')

    monkeypatch.setattr(kit, 'muted', patla)
    t.apply_theme()  # hata sizmamali


def test_destek_ozeti_akisi(tab, monkeypatch):
    t, _core, _win = tab
    monkeypatch.setattr(diag, 'paylasim_metni', lambda: 'ÖZET')
    yakalanan = []

    def sahte_exec(self):
        yakalanan.append(self)
        return 0

    monkeypatch.setattr(QDialog, 'exec', sahte_exec)

    t.btn_share_info.click()

    d = yakalanan[0]
    assert d.windowTitle() == 'Paylaşım için destek özeti'
    assert d.parent() is t
    onizleme = d.findChild(QPlainTextEdit)
    assert onizleme.toPlainText() == 'ÖZET'
    assert onizleme.isReadOnly() is True
    assert onizleme.accessibleName() == 'Paylaşılacak destek özeti'
    aciklama = next(lbl for lbl in d.findChildren(QLabel)
                    if lbl.text().startswith('Yalnızca uygulama ve ortam'))
    assert aciklama.wordWrap() is True
    sonuc = next(lbl for lbl in d.findChildren(QLabel)
                 if lbl.text() == 'Kopyalamadan önce içeriği inceleyebilirsiniz.')

    kutular = d.findChild(QDialogButtonBox)
    assert kutular.button(QDialogButtonBox.Close).text() == 'Kapat'
    kopyala = next(b for b in kutular.buttons() if b.text() == 'Özeti kopyala')
    kopyala.click()
    assert QApplication.clipboard().text() == 'ÖZET'
    assert sonuc.text() == 'Destek özeti panoya kopyalandı.'

    kutular.button(QDialogButtonBox.Close).click()
    assert d.result() == QDialog.Rejected


def test_destek_ozeti_hata(tab, monkeypatch):
    t, _core, _win = tab
    yakalanan = []
    uyarilar = []
    monkeypatch.setattr(QDialog, 'exec',
                        lambda self: yakalanan.append(self))
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: uyarilar.append(a))

    def patla():
        raise RuntimeError('ozet yok')

    monkeypatch.setattr(diag, 'paylasim_metni', patla)
    t.btn_share_info.click()

    assert yakalanan == []
    assert uyarilar[0][1] == 'Destek özeti'
    assert uyarilar[0][2] == 'Sürüm özeti hazırlanamadı. Yeniden deneyin.'


def test_save_basari_ve_hata(tab, monkeypatch):
    t, core, _win = tab
    bilgiler = []
    hatalar = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgiler.append(a))
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: hatalar.append(a))

    t.btn_save.click()
    assert core.config.known_saved == 1
    assert bilgiler[0][1] == 'Kaydedildi'
    assert bilgiler[0][2] == 'Ayarlar kaydedildi.'

    core.config.save_ok = False
    core.config.save_error = 'disk dolu'
    t.btn_save.click()
    assert hatalar[0][1] == 'Kaydedilemedi'
    assert hatalar[0][2] == 'disk dolu'
    assert core.config.known_saved == 1

    core.config.save_error = ''
    t.btn_save.click()
    assert hatalar[1][2] == 'Ayarlar kaydedilemedi.'


def test_export_cfg(tab, monkeypatch, tmp_path):
    t, core, _win = tab
    core.config.protected = ['com.a']
    dosya = tmp_path / 'yedek.json'
    bilgiler = []
    hatalar = []
    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *a, **k: (str(dosya), ''))
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgiler.append(a))
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: hatalar.append(a))

    t.btn_export_cfg.click()

    veri = json.loads(dosya.read_text(encoding='utf-8'))
    assert veri['protected'] == ['com.a']
    assert veri['dark_mode'] is True
    assert bilgiler[0][2] == 'Yedeklendi:\n' + str(dosya)
    assert sorted(p.name for p in tmp_path.iterdir()) == ['yedek.json']

    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *a, **k: ('', ''))
    t.btn_export_cfg.click()
    assert len(bilgiler) == 1
    assert hatalar == []

    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *a, **k: (str(dosya), ''))

    def patlak_to_dict():
        raise TypeError('kotu veri')

    monkeypatch.setattr(core.config, 'to_dict', patlak_to_dict)
    t.btn_export_cfg.click()
    assert hatalar[0][1] == 'Hata'
    assert hatalar[0][2] == 'kotu veri'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['yedek.json']


def test_export_unlink_hatasi_yutulur(tab, monkeypatch, tmp_path):
    t, core, _win = tab
    dosya = tmp_path / 'yedek.json'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *a, **k: (str(dosya), ''))
    monkeypatch.setattr(QMessageBox, 'critical', lambda *a, **k: None)

    def patlak_to_dict():
        return {'kume': {1, 2}}  # set: json.dump TypeError atar

    def patlak_unlink(path):
        raise OSError('silinemedi')

    monkeypatch.setattr(core.config, 'to_dict', patlak_to_dict)
    monkeypatch.setattr(os, 'unlink', patlak_unlink)

    t.btn_export_cfg.click()

    kalan = [p.name for p in tmp_path.iterdir()]
    assert len(kalan) == 1
    assert kalan[0].startswith('.mibox-ayar-yedek-')
    assert dosya.exists() is False


def test_import_cfg_hata_yollari(tab, monkeypatch, tmp_path):
    t, _core, _win = tab
    hatalar = []
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: hatalar.append(a))

    monkeypatch.setattr(QFileDialog, 'getOpenFileName',
                        lambda *a, **k: ('', ''))
    t.btn_import_cfg.click()
    assert hatalar == []

    bozuk = tmp_path / 'bozuk.json'
    bozuk.write_text('{nope', encoding='utf-8')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName',
                        lambda *a, **k: (str(bozuk), ''))
    t.btn_import_cfg.click()
    assert hatalar[0][1] == 'Hata'

    dizi = tmp_path / 'dizi.json'
    dizi.write_text('[1]', encoding='utf-8')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName',
                        lambda *a, **k: (str(dizi), ''))
    t.btn_import_cfg.click()
    assert hatalar[1][2] == 'Geçersiz yedek dosyası.'


def test_import_cfg_basari(tab, monkeypatch, tmp_path):
    t, core, win = tab
    veri = {'dark_mode': False, 'protected': ['com.x'],
            'install_grant_perms': True, 'log_to_file': True,
            'keyboard_nav': False}
    dosya = tmp_path / 'yedek.json'
    dosya.write_text(json.dumps(veri), encoding='utf-8')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName',
                        lambda *a, **k: (str(dosya), ''))
    bilgiler = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgiler.append(a))

    t.btn_import_cfg.click()

    assert core.config.dark_mode is False
    assert core.config.protected == ['com.x']
    assert core.config.save_count == 1
    assert core.config.known_saved == 1
    assert win.tab_debloat.sync == 1
    assert t.chk_dark.isChecked() is False
    assert t.chk_log.isChecked() is True
    assert t.chk_keyboard_nav.isChecked() is False
    assert t.chk_grant_perms.isChecked() is True
    assert win.tab_install_inner.chk_grant_perms.isChecked() is True
    assert win.tema == 1
    assert t.lst_protected.count() == 1
    assert t.lst_protected.item(0).text() == 'com.x'
    assert bilgiler[0][2] == 'Ayar yedeği içe aktarıldı.'

    monkeypatch.setattr(QFileDialog, 'getOpenFileName',
                        lambda *a, **k: (str(dosya), ''))
    t.btn_import_cfg.click()
    assert win.tema == 1  # tema degismedi: yeniden uygulanmaz
    assert core.config.save_count == 2


def test_import_cfg_kayit_hatasinda_geri_alir(tab, monkeypatch, tmp_path):
    t, core, win = tab
    dosya = tmp_path / 'yedek.json'
    dosya.write_text(json.dumps({'dark_mode': False}), encoding='utf-8')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName',
                        lambda *a, **k: (str(dosya), ''))
    hatalar = []
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: hatalar.append(a))
    core.config.save_ok = False
    core.config.save_error = 'yazilamadi'

    t.btn_import_cfg.click()

    assert core.config.dark_mode is True  # geri alindi
    assert hatalar[0][1] == 'Hata'
    assert hatalar[0][2] == 'yazilamadi'
    assert core.config.known_saved == 0
    assert win.tema == 0


def test_import_opsiyonel_kancalar_yok(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(diag, 'metin', lambda: 'BILGI')
    core = _Cekirdek()
    t = SettingsTab(core, _MinimalPencere())
    qtbot.addWidget(t)
    dosya = tmp_path / 'yedek.json'
    dosya.write_text(json.dumps({'dark_mode': False}), encoding='utf-8')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName',
                        lambda *a, **k: (str(dosya), ''))
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: None)

    t.btn_import_cfg.click()

    assert core.config.dark_mode is False
    assert core.config.known_saved == 1
