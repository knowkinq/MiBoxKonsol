# -*- coding: utf-8 -*-
"""stage_dialog: sahne onizleme tablosu, dugmeler ve tema yenileme."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QDialog, QDialogButtonBox

from mibox_app.stage import ACTION_ICON, ACTION_TR
from mibox_app.ui import kit
from mibox_app.ui.stage_dialog import StageDialog


class _Sahne:
    """StageDialog'un bekledigi asgari arayuz: items() + count()."""

    def __init__(self, ogeler):
        self._ogeler = ogeler

    def items(self):
        return list(self._ogeler)

    def count(self):
        return len(self._ogeler)


def test_tablo_satirlari_ikon_not_ve_bayraklar(qtbot):
    sahne = _Sahne([('disable', 'com.a'), ('smart', 'com.b'),
                    ('clear', 'com.c'), ('hayali', 'com.d')])
    dlg = StageDialog(None, sahne)
    qtbot.addWidget(dlg)

    assert dlg.windowTitle() == 'İşlem Önizleme — Sahne'
    assert dlg.grid.rowCount() == 4
    assert dlg.grid.horizontalHeaderItem(0).text() == 'İşlem'
    assert dlg.grid.horizontalHeaderItem(1).text() == 'Paket'
    assert dlg.grid.horizontalHeaderItem(2).text() == 'Not'
    assert dlg.grid.selectionBehavior() == QAbstractItemView.SelectRows
    assert dlg.grid.alternatingRowColors() is True

    beklenen = '{} {}'.format(ACTION_ICON['disable'], ACTION_TR['disable'])
    assert dlg.grid.item(0, 0).text() == beklenen
    assert dlg.grid.item(0, 1).text() == 'com.a'
    assert dlg.grid.item(0, 2).text() == ''
    assert dlg.grid.item(1, 0).text() == '{} {}'.format(
        ACTION_ICON['smart'], ACTION_TR['smart'])
    assert dlg.grid.item(1, 2).text() == '⚠ önce devre dışı, olmazsa kaldır'
    assert dlg.grid.item(2, 2).text() == '⚠ geri dönüşü zor'
    assert dlg.grid.item(3, 0).text() == '• hayali'
    assert dlg.grid.item(3, 2).text() == ''

    bayraklar = dlg.grid.item(0, 0).flags()
    assert bayraklar & Qt.ItemIsEnabled
    assert bayraklar & Qt.ItemIsSelectable
    assert not (bayraklar & Qt.ItemIsEditable)

    assert dlg.lbl.text() == 'Toplam 4 işlem.'


def test_dost_ad_parantez_icinde(qtbot):
    sahne = _Sahne([('disable', 'com.a'), ('disable', 'com.b')])

    def dost(pkg):
        return 'Alfa' if pkg == 'com.a' else pkg

    dlg = StageDialog(None, sahne, friendly=dost)
    qtbot.addWidget(dlg)

    assert dlg.grid.item(0, 1).text() == 'com.a  (Alfa)'
    assert dlg.grid.item(1, 1).text() == 'com.b'


def test_aciklama_ve_ozet_etiketleri(qtbot):
    tam = StageDialog(None, _Sahne([('disable', 'com.a')]),
                      description='Açıklama', summary='Özet')
    qtbot.addWidget(tam)
    bos = StageDialog(None, _Sahne([('disable', 'com.a')]),
                      description='', summary='')
    qtbot.addWidget(bos)

    assert tam._description.text() == 'Açıklama'
    assert tam._summary.text() == 'Özet'
    assert tam._description.styleSheet() != ''
    assert bos._description is None
    assert bos._summary is None


def test_dugmeler_metin_ve_sonuc(qtbot):
    dlg = StageDialog(None, _Sahne([('disable', 'com.a')]))
    qtbot.addWidget(dlg)

    ok = dlg.buttons.button(QDialogButtonBox.Ok)
    iptal = dlg.buttons.button(QDialogButtonBox.Cancel)
    assert ok.text() == 'Uygula'
    assert ok.property('accent') is True
    assert iptal.text() == 'Vazgeç'

    dlg.buttons.accepted.emit()
    assert dlg.result() == QDialog.Accepted

    bos = StageDialog(None, _Sahne([]))
    qtbot.addWidget(bos)
    assert bos.lbl.text() == 'Toplam 0 işlem.'
    bos.buttons.rejected.emit()
    assert bos.result() == QDialog.Rejected


def test_apply_theme_etiket_stillerini_yeniler(qtbot, monkeypatch):
    sade = StageDialog(None, _Sahne([('disable', 'com.a')]))
    qtbot.addWidget(sade)
    tam = StageDialog(None, _Sahne([('disable', 'com.a')]),
                      description='Açıklama', summary='Özet')
    qtbot.addWidget(tam)

    cagrilar = []

    def sahte_muted(dark=True):
        cagrilar.append(dark)
        return 'yeni-stil'

    monkeypatch.setattr(kit, 'muted', sahte_muted)
    sade.apply_theme()
    tam.apply_theme()

    assert cagrilar == [kit.dark_from(sade), kit.dark_from(tam)]
    for dlg in (sade, tam):
        assert dlg._info.styleSheet() == 'yeni-stil'
    assert tam._description.styleSheet() == 'yeni-stil'
    assert tam._summary.styleSheet() == 'yeni-stil'


def test_apply_theme_hatayi_yutar(qtbot, monkeypatch):
    dlg = StageDialog(None, _Sahne([('disable', 'com.a')]))
    qtbot.addWidget(dlg)

    def patla(dark=True):
        raise RuntimeError('tema yok')

    monkeypatch.setattr(kit, 'muted', patla)
    dlg.apply_theme()  # hata sizmamali

    assert dlg._info.styleSheet() != 'yeni-stil'
