# -*- coding: utf-8 -*-
"""actions_dialog: arama anahtari, filtreleme, etkinlestirme ve tus filtresi."""
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QDialog

from mibox_app.ui.actions_dialog import ActionsDialog, search_key


@pytest.mark.parametrize('ham,beklenen', [
    ('İstanbul', 'istanbul'),
    ('Iğdır', 'igdir'),
    ('MÜZİK', 'muzik'),
    ('ııı', 'iii'),
    (42, '42'),
])
def test_search_key_turkce_harfleri_sadelestirir(ham, beklenen):
    assert search_key(ham) == beklenen


def _tus(tus, mod=Qt.NoModifier):
    return QKeyEvent(QEvent.KeyPress, tus, mod)


def test_kurulum_liste_ve_bos_etiket(qtbot):
    kayit = []
    eylemler = [
        ('Uygulamalar', 'kurulu uygulama listesi',
         lambda: kayit.append('Uygulamalar'), lambda: True),
        ('Ayarlar', 'tema ve tercihler',
         lambda: kayit.append('Ayarlar'), lambda: True),
    ]
    dlg = ActionsDialog(None, eylemler)
    qtbot.addWidget(dlg)

    assert dlg.windowTitle() == 'Hızlı erişim'
    assert dlg.results.count() == 2
    ilk = dlg.results.item(0)
    assert ilk.text() == 'Uygulamalar\nkurulu uygulama listesi'
    assert ilk.toolTip() == 'kurulu uygulama listesi'
    assert ilk.data(Qt.UserRole) == 0
    assert ilk.sizeHint().height() >= 66
    assert dlg.empty.isVisibleTo(dlg) is False
    assert dlg.results.currentRow() == 0


def test_filtre_baslik_ve_aciklamada_arar(qtbot):
    eylemler = [
        ('Uygulamalar', 'kurulu uygulama listesi', lambda: None, lambda: True),
        ('İstanbul', 'şehir rehberi', lambda: None, lambda: True),
        ('Ayarlar', 'tema ve tercihler', lambda: None, lambda: True),
    ]
    dlg = ActionsDialog(None, eylemler)
    qtbot.addWidget(dlg)

    dlg.search.setText('uygulama')
    assert dlg.results.count() == 1
    assert dlg.results.item(0).text().startswith('Uygulamalar')

    dlg.search.setText('istanbul')
    assert dlg.results.count() == 1
    assert dlg.results.item(0).text().startswith('İstanbul')

    dlg.search.setText('tema tercih')
    assert dlg.results.count() == 1
    assert dlg.results.item(0).text().startswith('Ayarlar')

    dlg.search.setText('zzz bulunamaz')
    assert dlg.results.count() == 0
    assert dlg.empty.isVisibleTo(dlg) is True
    assert dlg.results.currentRow() == -1


def test_etkin_olmayan_eylem_secilemez_ve_atlanir(qtbot):
    kayit = []
    durumlar = [[False], [True]]
    eylemler = [
        ('Kapalı', 'erişilemez',
         lambda: kayit.append('kapali'), lambda: durumlar[0][0]),
        ('Açık', 'erişilebilir',
         lambda: kayit.append('acik'), lambda: durumlar[1][0]),
    ]
    dlg = ActionsDialog(None, eylemler)
    qtbot.addWidget(dlg)

    kapali = dlg.results.item(0)
    assert not (kapali.flags() & Qt.ItemIsEnabled)
    assert not (kapali.flags() & Qt.ItemIsSelectable)
    assert dlg.results.currentRow() == 1

    dlg._activate(kapali)
    assert kayit == []
    assert dlg.result() != QDialog.Accepted

    hepsi_kapali = ActionsDialog(None, [
        ('X', 'x', lambda: kayit.append('x'), lambda: False)])
    qtbot.addWidget(hepsi_kapali)
    assert hepsi_kapali.results.currentRow() == -1


def test_activate_kosullari(qtbot):
    kayit = []
    durum = [True]
    dlg = ActionsDialog(None, [
        ('X', 'x', lambda: kayit.append('x'), lambda: durum[0])])
    qtbot.addWidget(dlg)

    dlg._activate()
    assert kayit == ['x']
    assert dlg.result() == QDialog.Accepted

    durum2 = [True]
    dlg2 = ActionsDialog(None, [
        ('Y', 'y', lambda: kayit.append('y'), lambda: durum2[0])])
    qtbot.addWidget(dlg2)
    durum2[0] = False
    dlg2._activate()
    assert kayit == ['x']
    assert dlg2.result() != QDialog.Accepted

    dlg3 = ActionsDialog(None, [
        ('Z', 'z', lambda: kayit.append('z'), lambda: True)])
    qtbot.addWidget(dlg3)
    dlg3.results.setCurrentRow(-1)
    dlg3._activate()
    assert kayit == ['x']
    assert dlg3.result() != QDialog.Accepted


def test_event_filter_enter_ve_diger_tuslar(qtbot):
    kayit = []
    dlg = ActionsDialog(None, [
        ('X', 'x', lambda: kayit.append('x'), lambda: True)])
    qtbot.addWidget(dlg)

    assert dlg.eventFilter(dlg.results, _tus(Qt.Key_Return)) is True
    assert kayit == ['x']
    assert dlg.result() == QDialog.Accepted

    dlg2 = ActionsDialog(None, [
        ('Y', 'y', lambda: kayit.append('y'), lambda: True)])
    qtbot.addWidget(dlg2)

    assert dlg2.eventFilter(dlg2.results, _tus(Qt.Key_Enter)) is True
    assert kayit == ['x', 'y']

    assert dlg2.eventFilter(dlg2.results, _tus(Qt.Key_A)) is False
    assert dlg2.eventFilter(dlg2.search, _tus(Qt.Key_A)) is False


def test_event_filter_yon_tuslari_etkin_satira_ziplar(qtbot):
    durumlar = [[False], [True], [False], [True]]
    eylemler = [
        ('A', 'a', lambda: None, lambda d=durumlar[0]: d[0]),
        ('B', 'b', lambda: None, lambda d=durumlar[1]: d[0]),
        ('C', 'c', lambda: None, lambda d=durumlar[2]: d[0]),
        ('D', 'd', lambda: None, lambda d=durumlar[3]: d[0]),
    ]
    dlg = ActionsDialog(None, eylemler)
    qtbot.addWidget(dlg)

    assert dlg.results.currentRow() == 1

    assert dlg.eventFilter(dlg.search, _tus(Qt.Key_Down)) is True
    assert dlg.results.currentRow() == 3

    assert dlg.eventFilter(dlg.search, _tus(Qt.Key_Down)) is True
    assert dlg.results.currentRow() == 3

    assert dlg.eventFilter(dlg.search, _tus(Qt.Key_Up)) is True
    assert dlg.results.currentRow() == 1


def test_resize_satirlari_yeniden_boyutlandirir(qtbot):
    uzun = 'uzun açıklama metni ' * 30
    dlg = ActionsDialog(None, [('Başlık', uzun, lambda: None, lambda: True)])
    qtbot.addWidget(dlg)
    dlg.show()

    dlg.resize(700, 400)
    qtbot.wait(10)
    genis = dlg.results.item(0).sizeHint().height()

    dlg.resize(220, 400)
    qtbot.wait(10)
    dlg._size_results()
    dar = dlg.results.item(0).sizeHint().height()

    assert genis >= 66
    assert dar > genis
