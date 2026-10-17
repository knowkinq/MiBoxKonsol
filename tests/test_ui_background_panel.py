# -*- coding: utf-8 -*-
"""background_panel: tarama, filtre, toplu kısıtlama ve durum islemleri."""
import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QBoxLayout

from mibox_app.ui import background_panel as bg
from mibox_app.ui import kit
from mibox_app.workers import AppScanWorker, BulkActionWorker


class _Ayar:
    def __init__(self, protected=()):
        self.protected = set(protected)
        self.adlar = {}

    def friendly_name(self, pkg):
        return self.adlar.get(pkg, pkg)


class _Cekirdek(QObject):
    connection_changed = Signal(bool, object)

    def __init__(self):
        super().__init__()
        self.connected = True
        self.target = 'tv-1'
        self.engine = object()
        self.config = _Ayar()


class _Pencere:
    def __init__(self):
        self._connection_busy = False
        self._workers = []
        self.baslatilan = []
        self.hata = None

    def _run(self, worker, desc=None):
        if self.hata is not None:
            raise self.hata
        self.baslatilan.append((worker, desc))


class _SahteIsci:
    def __init__(self):
        self.iptal = 0

    def cancel(self):
        self.iptal += 1


def _app(pkg, system=False, status='serbest', running='evet',
         label=None, **extra):
    veri = {'package': pkg, 'system': system, 'status': status,
            'running': running, 'installed_user0': True, 'enabled': True}
    if label is not None:
        veri['label'] = label
    veri.update(extra)
    return veri


@pytest.fixture
def panel(qtbot):
    core = _Cekirdek()
    win = _Pencere()
    p = bg.BackgroundPanel(core, win)
    qtbot.addWidget(p)
    return p, core, win


def _satir_bul(p, pkg):
    for row in range(p.grid.rowCount()):
        if p.grid.item(row, 2).text() == pkg:
            return row
    raise AssertionError('satir yok: ' + pkg)


def test_kurulum_ogeleri(panel):
    p, _core, _win = panel

    assert p.category_tabs.tabText(0) == 'Kullanıcı (—)'
    assert p.category_tabs.tabText(1) == 'Sistem (—)'
    assert p.category_tabs.currentIndex() == 0
    assert p.search.placeholderText() == 'Uygulama veya paket ara…'
    assert p.grid.columnCount() == 5
    assert p.grid.horizontalHeaderItem(0).text() == 'Seç'
    assert p.grid.horizontalHeaderItem(4).text() == 'Çalışıyor'
    assert p.grid.isSortingEnabled() is True
    assert p.btn_refresh.text() == 'Yenile'
    assert p.btn_restrict.text() == 'Seçilenleri Kısıtla'
    assert p.btn_free.text() == 'Seçilenleri Serbest Bırak'
    assert p.status.text() == 'Henüz tarama yapılmadı. Cihaza bağlanıp Yenile’ye basın.'


def test_resize_darbe_yonu_degistirir(panel):
    p, _core, _win = panel
    filtre = p._filter_layout

    p.show()
    p.resize(500, 300)
    assert filtre.direction() == QBoxLayout.TopToBottom

    p.resize(800, 300)
    assert filtre.direction() == QBoxLayout.LeftToRight

    del p._filter_layout
    p.resize(700, 300)  # yerlesim yoksa sessizce gecilmeli


def test_ready_kapilari(panel):
    p, core, win = panel

    p._busy = True
    assert p._ready() is False
    p._busy = False

    core.connected = False
    assert p._ready() is False
    assert p.status.text() == 'Önce cihaza bağlanın.'

    p.refresh()  # hazir degilken isci baslatilmamali
    assert win.baslatilan == []

    core.connected = True
    core.target = ''
    assert p._ready() is False

    core.target = 'tv-1'
    win._connection_busy = True
    assert p._ready() is False

    win._connection_busy = False
    assert p._ready() is True


def test_refresh_akisi_yukleme_ve_temizlik(panel):
    p, core, win = panel

    p.refresh()

    assert p.status.text() == 'Arka plan izinleri okunuyor…'
    assert len(win.baslatilan) == 1
    isci, desc = win.baslatilan[0]
    assert isinstance(isci, AppScanWorker)
    assert isci._target == core.target
    assert isci._include_system is True
    assert desc == isci.job_name
    assert p._busy is True
    assert p._worker is isci
    assert p.btn_refresh.isEnabled() is False
    assert p.btn_restrict.isEnabled() is False
    assert p.btn_free.isEnabled() is False

    isci.finished_ok.emit([
        _app('com.a'),
        _app('com.b', system=True),
        _app('com.c', installed_user0=False),
    ])

    assert [a['package'] for a in p._apps] == ['com.a', 'com.b']
    assert p._has_scan is True
    assert p.category_tabs.tabText(0) == 'Kullanıcı (1)'
    assert p.category_tabs.tabText(1) == 'Sistem (1)'
    assert p.status.text() == ('2 paket incelendi. Seçerek kısıtlayabilir veya '
                               'serbest bırakabilirsiniz.')
    assert p.grid.rowCount() == 1

    isci.finished.emit()
    assert p._busy is False
    assert p._worker is None
    assert p.btn_refresh.isEnabled() is True
    assert p.btn_restrict.isEnabled() is True
    assert p.btn_free.isEnabled() is True

    p._cleanup(object())  # baska isci: hicbir sey degismemeli
    assert p._busy is False


def test_eski_nesil_sonucu_yok_sayilir(panel):
    p, core, win = panel

    p.refresh()
    isci = win.baslatilan[0][0]

    p._generation += 1
    isci.finished_ok.emit([_app('com.a')])
    assert p._apps == []
    assert p.status.text() == 'Arka plan izinleri okunuyor…'

    isci.failed.emit('gec kalan hata')
    assert 'tamamlanamadı' not in p.status.text()

    p._generation -= 1
    isci.failed.emit('patladi')
    assert p.status.text() == 'İşlem tamamlanamadı: patladi'

    core.target = 'baska-hedef'
    isci.finished_ok.emit([_app('com.b')])
    assert p._apps == []


def test_baslatma_hatasi_temizler(panel):
    p, _core, win = panel
    win.hata = RuntimeError('patladi')

    p.refresh()

    assert p.status.text() == 'İşlem başlatılamadı: patladi'
    assert p._busy is False
    assert p._worker is None
    assert p.btn_refresh.isEnabled() is True
    assert win.baslatilan == []


def test_baglanti_degisimi_sifirlar(panel):
    p, core, _win = panel
    sahte = _SahteIsci()
    p._worker = sahte
    p._apps = [_app('com.a')]
    p._has_scan = True
    p._generation = 5

    core.connection_changed.emit(False, None)

    assert p._generation == 6
    assert sahte.iptal == 1
    assert p._apps == []
    assert p._has_scan is False
    assert p.category_tabs.tabText(0) == 'Kullanıcı (—)'
    assert p.status.text() == 'Bağlantı değişti. Yeniden tarayın.'


def test_render_filtreler_siniflar_ve_rozetler(panel):
    p, core, _win = panel
    core.config.adlar = {'com.kisitli': 'Dost Kısıtlı'}
    core.config.protected = {'com.korunan'}
    p._apps = [
        _app('com.user', status='serbest', running='evet', label='Kullanıcı Uygulaması'),
        _app('com.kisitli', status='kisitli', running='hayir'),
        _app('com.sys', system=True, status='kısıtlı', running='hayır'),
        _app('com.bilinmeyen', status='', running=''),
        _app('com.korunan', status='serbest', running='evet'),
        _app('com.turk', status='serbest', running='EVET'),
        _app('com.hayir', status='serbest', running=' Hayır '),
        _app('com.kapali', enabled=False),
    ]
    p._has_scan = True

    p._render()

    assert p.category_tabs.tabText(0) == 'Kullanıcı (7)'
    assert p.category_tabs.tabText(1) == 'Sistem (1)'
    assert p.grid.rowCount() == 7
    assert p.grid.isSortingEnabled() is True
    palette = kit.colors(p)

    row = _satir_bul(p, 'com.kisitli')
    assert p.grid.item(row, 1).text() == 'Dost Kısıtlı'
    assert p.grid.item(row, 3).text() == 'Kısıtlı'
    assert p.grid.item(row, 3).foreground().color().name() == palette['danger']
    assert p.grid.item(row, 4).text() == 'Hayır'
    assert p.grid.item(row, 4).foreground().color().name() == palette['muted']

    row = _satir_bul(p, 'com.user')
    assert p.grid.item(row, 1).text() == 'Kullanıcı Uygulaması'
    assert p.grid.item(row, 3).text() == 'Serbest'
    assert p.grid.item(row, 3).foreground().color().name() == palette['success']
    assert p.grid.item(row, 4).text() == 'Evet'
    assert p.grid.item(row, 4).foreground().color().name() == palette['success']

    row = _satir_bul(p, 'com.bilinmeyen')
    assert p.grid.item(row, 3).text() == 'Bilinmiyor'
    assert p.grid.item(row, 3).foreground().color().name() == palette['warning']
    assert p.grid.item(row, 4).text() == 'Bilinmiyor'
    assert p.grid.item(row, 4).foreground().color().name() == palette['warning']

    row = _satir_bul(p, 'com.korunan')
    sec = p.grid.item(row, 0)
    assert not (sec.flags() & Qt.ItemIsUserCheckable)
    assert sec.toolTip() == 'Korunan veya devre dışı paket'

    row = _satir_bul(p, 'com.kapali')
    assert not (p.grid.item(row, 0).flags() & Qt.ItemIsUserCheckable)

    row = _satir_bul(p, 'com.hayir')
    assert p.grid.item(row, 4).text() == 'Hayır'

    row = _satir_bul(p, 'com.turk')
    assert p.grid.item(row, 4).text() == 'Evet'

    p.category_tabs.setCurrentIndex(1)
    assert p.grid.rowCount() == 1
    assert p.grid.item(0, 2).text() == 'com.sys'

    p.category_tabs.setCurrentIndex(0)
    p.search.setText('kısıtlı')
    assert p.grid.rowCount() == 1
    assert p.grid.item(0, 2).text() == 'com.kisitli'

    p.search.setText('zzz')
    assert p.grid.rowCount() == 0
    assert p.grid.empty_title == 'Uygulama bulunamadı'

    p.grid.setSortingEnabled(False)
    p._render()
    assert p.grid.isSortingEnabled() is False


def test_apply_kapilari_ve_iscisi(panel, monkeypatch):
    p, core, win = panel

    core.connected = False
    p._apply(True)
    assert p.status.text() == 'Önce cihaza bağlanın.'

    core.connected = True
    win._workers = [object()]
    p._apply(True)
    assert p.status.text() == 'Diğer işlemlerin bitmesini bekleyin.'

    win._workers = []
    p._apps = [_app('com.a'), _app('com.korunan')]
    core.config.protected = {'com.korunan'}
    p._has_scan = True
    p._render()
    p._apply(True)
    assert p.status.text() == 'Önce değiştirilecek uygulamaları seçin.'

    p.grid.item(_satir_bul(p, 'com.a'), 0).setCheckState(Qt.Checked)
    monkeypatch.setattr(bg, 'confirm_action', lambda *a, **k: False)
    p._apply(True)
    assert win.baslatilan == []

    monkeypatch.setattr(bg, 'confirm_action', lambda *a, **k: True)
    p._apply(True)

    assert len(win.baslatilan) == 1
    isci = win.baslatilan[0][0]
    assert isinstance(isci, BulkActionWorker)
    assert isci._packages == ('com.a',)
    assert isci._restrict is True
    assert isci._protected == {'com.korunan'}
    assert isci._validate_packages is True
    assert p.status.text() == 'Seçilen paketler işleniyor…'
    assert p.btn_refresh.isEnabled() is False

    def degistiren(*_a, **_k):
        core.connected = False
        return True

    p._busy = False
    p._worker = None
    monkeypatch.setattr(bg, 'confirm_action', degistiren)
    p._apply(False)
    assert p.status.text() == 'Bağlantı veya işlem durumu değişti. Yeniden deneyin.'
    assert len(win.baslatilan) == 1


def test_applied_sonuclari_islar(panel):
    p, _core, _win = panel
    p._apps = [_app('com.a'), _app('com.b'), _app('com.giden', installed_user0=False)]

    p._applied({
        'action': 'restrict',
        'ok': 1,
        'skip': 1,
        'cancelled': True,
        'details': [('com.a', True, ''), ('com.b', False, 'izin yok')],
        'package_states': {'com.a': {'status': 'kisitli', 'running': 'hayir'}},
    })

    assert [a['package'] for a in p._apps] == ['com.a', 'com.b']
    a0, a1 = p._apps
    assert a0['status'] == 'Kisitli'
    assert a0['running'] == 'hayir'
    assert a1['status'] == 'Bilinmiyor'
    satirlar = p.status.text().split('\n')
    assert satirlar[0] == '1 başarılı · 1 uygulanamadı/atlandı. İşlem durduruldu.'
    assert satirlar[1] == 'com.b: izin yok'

    p._apps = [_app('com.a', status='kisitli')]
    p._applied({
        'action': 'unrestrict',
        'ok': 1,
        'skip': 0,
        'details': [('com.a', True, '')],
        'package_states': {},
    })
    assert p._apps[0]['status'] == 'Serbest'
    assert p.status.text() == '1 başarılı · 0 uygulanamadı/atlandı.'

    p._apps = [_app('com.x')]
    p._applied({
        'action': 'restrict',
        'ok': 0,
        'skip': 8,
        'details': [('c{}'.format(i), False, 'hata {}'.format(i)) for i in range(8)],
        'package_states': {},
    })
    satirlar = p.status.text().split('\n')
    assert len(satirlar) == 7  # ozet + en fazla 6 hata


def test_apply_theme_yeniden_cizer(panel):
    p, _core, _win = panel
    p._apps = [_app('com.a')]
    p._has_scan = True

    p.apply_theme()

    assert p.grid.rowCount() == 1