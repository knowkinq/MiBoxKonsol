# -*- coding: utf-8 -*-
"""dialogs: paket listesi satirlari ve islem onayi metinleri."""
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from mibox_app.ui import dialogs


@pytest.mark.parametrize('checked,accepted,expected', [
    (False, True, False), (True, True, True), (True, False, False),
])
def test_uninstall_data_choice(qtbot, checked, accepted, expected):
    options = {}

    def answer():
        box = QApplication.activeModalWidget()
        assert isinstance(box, QMessageBox)
        assert box.defaultButton() is box.button(QMessageBox.No)
        assert not box.checkBox().isChecked()
        assert 'tüm Android' in box.informativeText()
        assert 'com.example.app' in box.text()
        box.checkBox().setChecked(checked)
        box.button(QMessageBox.Yes if accepted else QMessageBox.No).click()

    QTimer.singleShot(0, answer)
    assert dialogs.confirm_action(
        None, 'uninstall', ['com.example.app'], lambda p: p,
        uninstall_options=options) is accepted
    assert options == {'full_uninstall': expected}


class _Soru:
    """QMessageBox.question yerine cagrilari kaydeden sahte."""

    def __init__(self, cevap):
        self.cevap = cevap
        self.cagrilar = []

    def __call__(self, parent, title, body, buttons, default):
        self.cagrilar.append((parent, title, body, buttons, default))
        return self.cevap


def test_pkg_lines_dost_ad_ve_sade_paket():
    adlar = {'com.a': 'Alfa', 'com.c': 'Charlie'}
    lines = dialogs.pkg_lines(
        ['com.a', 'com.b', 'com.c'], lambda p: adlar.get(p, p))

    assert lines == ['• Alfa (com.a)', '• com.b', '• Charlie (com.c)']


def test_pkg_lines_limit_ve_fazlasi_ozetlenir():
    paketler = ['com.p{}'.format(i) for i in range(10)]

    lines = dialogs.pkg_lines(paketler, lambda p: p)

    assert lines[:8] == ['• com.p{}'.format(i) for i in range(8)]
    assert lines[8] == '… ve 2 tane daha'

    kisa = dialogs.pkg_lines(['a', 'b', 'c'], lambda p: p, limit=2)
    assert kisa == ['• a', '• b', '… ve 1 tane daha']


def test_pkg_lines_ad_hatasi_ve_bos_ad_pakete_duser():
    def patlak_ad(pkg):
        raise RuntimeError('ad yok')

    assert dialogs.pkg_lines(['com.a'], patlak_ad) == ['• com.a']
    assert dialogs.pkg_lines(['com.a'], lambda p: '') == ['• com.a']


def test_confirm_action_tek_paket_veri_silme(monkeypatch):
    soru = _Soru(QMessageBox.Yes)
    monkeypatch.setattr(dialogs.QMessageBox, 'question', soru)

    sonuc = dialogs.confirm_action(
        None, 'clear', ['com.a'], lambda p: 'Alfa' if p == 'com.a' else p)

    assert sonuc is True
    parent, title, body, buttons, default = soru.cagrilar[0]
    assert parent is None
    assert title == 'Onay — Veri silme'
    assert body == ('Veri silme\n\n• Alfa (com.a)\n\n'
                    'Uygulama verileri kalıcı olarak silinir. '
                    'Durum kaydı bu verileri geri getirmez.')
    assert buttons == QMessageBox.Yes | QMessageBox.No
    assert default == QMessageBox.No


def test_confirm_action_cok_paket_kaldirma_ve_ek_not(monkeypatch):
    soru = _Soru(QMessageBox.No)
    monkeypatch.setattr(dialogs.QMessageBox, 'question', soru)

    sonuc = dialogs.confirm_action(
        None, 'uninstall', ['com.a', 'com.b'], lambda p: p,
        extra='Notlar burada.')

    assert sonuc is False
    body = soru.cagrilar[0][2]
    assert body.startswith('2 uygulama — Kullanıcı için kaldırma:')
    assert '• com.a\n• com.b' in body
    assert 'Bu işlem bir veri yedeği değildir' in body
    assert body.endswith('\n\nNotlar burada.')


def test_confirm_action_bilinmeyen_eylem_notsuz_govde(monkeypatch):
    soru = _Soru(QMessageBox.Yes)
    monkeypatch.setattr(dialogs.QMessageBox, 'question', soru)

    sonuc = dialogs.confirm_action(None, 'hayali', ['com.a'], lambda p: p)

    assert sonuc is True
    assert soru.cagrilar[0][1] == 'Onay — hayali'
    assert soru.cagrilar[0][2] == 'hayali\n\n• com.a'
