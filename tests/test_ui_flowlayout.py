# -*- coding: utf-8 -*-
"""flowlayout: sigmayan ogelerin alt satira kaymasi ve bos oge atlama."""
from PySide6.QtCore import QRect, QSize
from PySide6.QtWidgets import QPushButton, QWidget

from mibox_app.ui.flowlayout import FlowLayout


def _dugme(parent, ad, genislik=80, yukseklik=24):
    b = QPushButton(ad, parent)
    b.setFixedSize(genislik, yukseklik)
    return b


def test_ekle_say_al_ve_take(qtbot):
    kap = QWidget()
    qtbot.addWidget(kap)
    akis = FlowLayout(kap, margin=0, hspacing=6, vspacing=6)
    b1 = _dugme(kap, 'bir')
    b2 = _dugme(kap, 'iki')
    akis.addWidget(b1)
    akis.addWidget(b2)

    assert akis.count() == 2
    assert akis.itemAt(0).widget() is b1
    assert akis.itemAt(1).widget() is b2
    assert akis.itemAt(2) is None
    assert akis.itemAt(-1) is None

    ilk = akis.takeAt(0)
    assert ilk.widget() is b1
    assert akis.count() == 1
    assert akis.takeAt(9) is None


def test_yonler_ve_yukseklik_sorgusu(qtbot):
    kap = QWidget()
    qtbot.addWidget(kap)
    akis = FlowLayout(kap)
    akis.addWidget(_dugme(kap, 'bir'))

    assert not bool(akis.expandingDirections())
    assert akis.hasHeightForWidth() is True
    assert akis.heightForWidth(150) >= 24


def test_size_hint_minimum_size_ile_ayni(qtbot):
    kap = QWidget()
    qtbot.addWidget(kap)
    akis = FlowLayout(kap, margin=5)
    akis.addWidget(_dugme(kap, 'bir'))

    assert akis.sizeHint() == akis.minimumSize()
    assert akis.minimumSize() == QSize(80 + 10, 24 + 10)


def test_gizli_ogeler_atlanir(qtbot):
    kap = QWidget()
    qtbot.addWidget(kap)
    akis = FlowLayout(kap, margin=5)
    gorunur = _dugme(kap, 'bir')
    gizli = _dugme(kap, 'iki', genislik=200)
    gizli.hide()
    akis.addWidget(gizli)
    akis.addWidget(gorunur)

    assert akis.minimumSize() == QSize(80 + 10, 24 + 10)

    akis.setGeometry(QRect(0, 0, 400, 0))
    assert gorunur.geometry().x() == 5
    assert gizli.geometry() == QRect(0, 0, 200, 24)


def test_set_geometry_satirlari_sarar(qtbot):
    kap = QWidget()
    qtbot.addWidget(kap)
    akis = FlowLayout(kap, margin=0)
    dugmeler = [_dugme(kap, 'd{}'.format(i)) for i in range(3)]
    for b in dugmeler:
        akis.addWidget(b)

    akis.setGeometry(QRect(0, 0, 100, 300))
    y0, y1, y2 = (b.geometry().y() for b in dugmeler)
    assert y0 == 0
    assert y1 > y0
    assert y2 > y1
    assert [b.geometry().x() for b in dugmeler] == [0, 0, 0]

    akis.setGeometry(QRect(0, 0, 600, 300))
    assert dugmeler[1].geometry().y() == dugmeler[0].geometry().y()
    assert dugmeler[1].geometry().x() > dugmeler[0].geometry().x()


def test_del_ogeleri_bosalttir(qtbot):
    kap = QWidget()
    qtbot.addWidget(kap)
    akis = FlowLayout(kap)
    akis.addWidget(_dugme(kap, 'bir'))

    assert akis.count() == 1
    akis.__del__()
    assert akis.count() == 0
    akis.__del__()  # ikinci cagri zararsiz olmali
