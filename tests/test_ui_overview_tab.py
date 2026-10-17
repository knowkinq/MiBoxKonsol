# -*- coding: utf-8 -*-
"""overview_tab: baglanti ozeti, hizli erisim kartlari ve oturum islemleri."""
import re

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea

from mibox_app.ui import kit
from mibox_app.ui.overview_tab import OverviewTab


class _Cekirdek(QObject):
    connection_changed = Signal(bool, object)

    def __init__(self):
        super().__init__()
        self.connected = False
        self.target = ''


class _Sekme:
    def __init__(self):
        self.gorunum = None

    def setCurrentWidget(self, page):
        self.gorunum = page


class _Pencere:
    def __init__(self):
        self._connection_busy = False
        self.tabs = _Sekme()
        self.tab_apps = object()
        self.tab_remote = object()
        self.tab_install = object()
        self.tab_health = object()
        self.tab_files = object()
        self.tab_network = object()
        self.tab_history = object()
        self.olaylar = []

    def focus_target(self):
        self.olaylar.append('focus_target')

    def open_connection_help(self):
        self.olaylar.append('open_connection_help')

    def open_catalog(self):
        self.olaylar.append('open_catalog')

    def open_local_install(self):
        self.olaylar.append('open_local_install')


class _CizikPencere:
    """Sekmesiz, geri cagirisiz pencere: savunma yollari."""

    def __init__(self):
        self._connection_busy = False


class _CizikCekirdek:
    """connection_changed'i olmayan cekirdek."""

    connected = False
    target = ''


class _PatlakSinyal:
    def connect(self, fn):
        raise TypeError('baglanamaz')


class _PatlakCekirdek:
    connected = False
    target = ''
    connection_changed = _PatlakSinyal()


@pytest.fixture
def tab(qtbot):
    core = _Cekirdek()
    win = _Pencere()
    t = OverviewTab(core, win)
    qtbot.addWidget(t)
    return t, core, win


def _kart_basliklari(kart):
    return kart.findChild(QLabel, 'cardTitle').text()


def _kart_dugmeleri(kart):
    return sorted(b.text() for b in kart.findChildren(QPushButton))


KART_BASLIKLARI = ['Uygulamalar', 'Kumanda', 'Uygulama kurulumu',
                   'Sağlık ve bakım', 'Dosyalar', 'Ağ']


def test_kurulum_kartlar_ve_oturum_listesi(tab):
    t, _core, _win = tab

    assert t.objectName() == 'overviewPage'
    assert len(t._cards) == 6
    assert len(t._card_icons) == 6
    for kart, baslik in zip(t._cards, KART_BASLIKLARI):
        assert _kart_basliklari(kart) == baslik
        assert kart.objectName() == 'contentCard'
        assert kart.minimumHeight() == 142

    assert _kart_dugmeleri(t._cards[0]) == ['Uygulamaları aç']
    assert _kart_dugmeleri(t._cards[2]) == ['Kataloğu aç', 'Yerel APK']

    assert t.connection_title.text() == 'Cihaz bağlantısı yok'
    assert t.connection_badge.text() == 'ÇEVRİMDIŞI'
    assert t.connection_target.text() == ''
    assert t.btn_target.isEnabled() is True

    palette = kit.colors(t)
    assert t.connection_dot.styleSheet() == 'color: {};'.format(palette['faint'])

    bos = t.activity_rows.itemAt(0).widget()
    assert isinstance(bos, QLabel)
    assert bos.text() == 'Bu oturumda henüz işlem yapılmadı.'

    assert t._columns in (1, 2, 3)
    assert t.cards_grid.count() == 6


def test_baglanti_ozeti_durumlari(tab):
    t, core, win = tab

    core.connection_changed.emit(True, 'tv-5')
    assert t.connection_title.text() == 'Cihaz bağlı'
    assert t.connection_detail.text() == 'TV yönetim araçları kullanıma hazır.'
    assert t.connection_badge.text() == 'BAĞLI'
    assert t.connection_badge.property('role') == 'badge-success'
    assert t.connection_target.text() == 'Hedef: tv-5'
    palette = kit.colors(t)
    assert t.connection_dot.styleSheet() == 'color: {};'.format(palette['success'])

    win._connection_busy = True
    core.connection_changed.emit(False, 'tv-5')
    assert t.connection_title.text() == 'Bağlantı işlemi sürüyor'
    assert t.connection_badge.text() == 'BEKLEYİN'
    assert t.connection_badge.property('role') == 'badge'
    assert t.btn_target.isEnabled() is False
    assert t.connection_target.text() == 'Hedef: tv-5'

    win._connection_busy = False
    core.connection_changed.emit(False, '')
    assert t.connection_title.text() == 'Cihaz bağlantısı yok'
    assert t.btn_target.isEnabled() is True

    core.connected = True
    core.target = 'tv-9'
    t.refresh()
    assert t.connection_title.text() == 'Cihaz bağlı'
    assert t.connection_target.text() == 'Hedef: tv-9'

    t.apply_theme()
    assert not t._card_icons[0][0].pixmap().isNull()


def test_dugmeler_ve_geri_cagirilar(tab):
    t, _core, win = tab

    for kart, hedef in zip(t._cards,
                           [win.tab_apps, win.tab_remote, None, win.tab_health,
                            win.tab_files, win.tab_network]):
        if hedef is None:
            continue
        dugme = kart.findChildren(QPushButton)[0]
        dugme.click()
        assert win.tabs.gorunum is hedef

    win.tabs.gorunum = None
    t.btn_find_device.click()
    assert win.tabs.gorunum is win.tab_network

    t.btn_target.click()
    t.btn_connection_help.click()
    assert win.olaylar == ['focus_target', 'open_connection_help']

    for dugme in t._cards[2].findChildren(QPushButton):
        dugme.click()
    assert win.olaylar[-2:] == ['open_catalog', 'open_local_install']

    gecmis = t.activity_card.findChild(QPushButton)
    assert gecmis.text() == 'Geçmişi aç'
    gecmis.click()
    assert win.tabs.gorunum is win.tab_history


def test_geri_cagirisiz_pencere_sessiz_kalir(qtbot):
    t = OverviewTab(_CizikCekirdek(), _CizikPencere())
    qtbot.addWidget(t)

    t.btn_target.click()
    t.btn_connection_help.click()
    t.btn_find_device.click()
    for dugme in t._cards[2].findChildren(QPushButton):
        dugme.click()
    t.activity_card.findChild(QPushButton).click()


def test_patlak_sinyal_yutulur(qtbot):
    t = OverviewTab(_PatlakCekirdek(), _Pencere())
    qtbot.addWidget(t)

    assert t.connection_title.text() == 'Cihaz bağlantısı yok'


def test_record_action_siniri_ve_satirlar(tab):
    t, _core, _win = tab

    t.record_action('   ')
    t.record_action('')
    assert t._actions == []

    t.record_action('  İlk işlem  ')
    assert len(t._actions) == 1
    zaman, metin = t._actions[0]
    assert re.fullmatch(r'\d{2}:\d{2}:\d{2}', zaman)
    assert metin == 'İlk işlem'

    satir = t.activity_rows.itemAt(0).widget()
    duzen = satir.layout()
    assert duzen.itemAt(0).widget().text() == zaman
    assert duzen.itemAt(1).widget().text() == 'İlk işlem'

    t.record_action('x' * 300)
    assert len(t._actions[0][1]) == 240

    for i in range(6):
        t.record_action('islem {}'.format(i))
    assert len(t._actions) == 5
    assert t._actions[0][1] == 'islem 5'
    assert t.activity_rows.count() == 5

    t.activity_rows.addStretch(1)
    t._render_actions()
    assert t.activity_rows.count() == 5

    t._actions = []
    t._render_actions()
    bos = t.activity_rows.itemAt(0).widget()
    assert bos.text() == 'Bu oturumda henüz işlem yapılmadı.'


def test_reflow_sutunlari_uretim_sarmalayicisinda(qtbot):
    t = OverviewTab(_Cekirdek(), _Pencere())
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    area.setWidget(t)
    qtbot.addWidget(area)
    area.show()

    area.resize(950, 500)
    qtbot.wait(10)
    assert t._columns == 3
    konumlar = [t.cards_grid.getItemPosition(i)[:2] for i in range(6)]
    assert konumlar == [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)]
    assert t.cards_grid.columnStretch(2) == 1

    area.resize(700, 500)
    qtbot.wait(10)
    assert t._columns == 2
    konumlar = [t.cards_grid.getItemPosition(i)[:2] for i in range(6)]
    assert konumlar == [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)]
    assert t.cards_grid.columnStretch(2) == 0

    area.resize(600, 500)  # ayni esik icinde: erken donus
    qtbot.wait(10)
    assert t._columns == 2

    area.resize(300, 500)
    qtbot.wait(10)
    assert t._columns == 1
    konumlar = [t.cards_grid.getItemPosition(i)[:2] for i in range(6)]
    assert konumlar == [(i, 0) for i in range(6)]
    assert t.cards_grid.columnStretch(0) == 1
    assert t.cards_grid.columnStretch(1) == 0

    area.resize(950, 500)
    qtbot.wait(10)
    assert t._columns == 3


def test_tema_ikonlari_palete_ile_cizilir(tab):
    t, _core, _win = tab

    t.apply_theme()

    ikon, ad = t._card_icons[0]
    assert ad == 'apps'
    assert not ikon.pixmap().isNull()