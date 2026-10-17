# -*- coding: utf-8 -*-
"""Debloat sekmesi testleri: kategori listesi, varlik taramasi ve islemler."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QInputDialog, QMessageBox

import mibox_app.ui.debloat_tab as deb_mod
import mibox_app.ui.dialogs as dialogs_mod
import mibox_app.ui.stage_dialog as stage_dialog_mod
import mibox_app.workers as workers_mod
from mibox_app.ui.debloat_tab import (
    COL_CHECK,
    COL_DESC,
    COL_NAME,
    COL_PKG,
    COL_PRESENT,
    COL_SAFETY,
    COL_STATE,
    COL_UAD,
    DebloatTab,
    _NoWheelComboBox,
)
from mibox_app.workers import CancelledError


def _kategoriler():
    return [
        ('guvenli', 'Güvenli (Kaldırılabilir)', [
            ('com.g.one', 'Bir', 'Birinci paket'),
            ('com.g.two', 'İki', 'İkinci paket'),
        ]),
        ('riskli', 'Riskli (Dikkatli)', [
            ('com.r.one', 'Riskli Bir', 'Riskli paket'),
        ]),
        ('dokunma', 'Dokunma (Kritik)', [
            ('com.d.one', 'Kritik Bir', 'Kritik paket'),
        ]),
        ('favoriler', 'Favoriler (Kendin Ekladigin)', [
            ('com.f.one', 'Favori Bir', 'Favori paket'),
        ]),
    ]


class _Motor:
    """Sahte cihaz motoru; cagrilar kaydedilir, ciktilar ayarlanabilir."""

    def __init__(self):
        self.calls = []
        self.packages = []
        self.users = [{'id': 0, 'name': 'Owner', 'running': True}]
        self.connect_patlak = False
        self.connect_hook = None
        self.list_users_hook = None

    def connect(self, target):
        if self.connect_patlak:
            raise RuntimeError('baglanti yok')
        self.calls.append(('connect', target))
        if self.connect_hook is not None:
            self.connect_hook()

    def list_packages_detailed(self, target, include_system=True,
                               use_cache=False, user_id=0):
        self.calls.append(
            ('list_packages_detailed', target, include_system, use_cache, user_id))
        return list(self.packages)

    def list_users(self, target):
        self.calls.append(('list_users', target))
        if self.list_users_hook is not None:
            self.list_users_hook()
        return list(self.users)


class _Yapilandirma:
    def __init__(self):
        self.user_id = 0
        self.show_unlisted = False
        self.protected = set()
        self.friendly = {}
        self.friendly_name = {}
        self.save_calls = 0

    def save(self):
        self.save_calls += 1
        return True


class _Cekirdek(QObject):
    connection_changed = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.connected = True
        self.target = 'tv-1'
        self._engine = _Motor()
        self.config = _Yapilandirma()
        self.engine_patlak = False

    @property
    def engine(self):
        if self.engine_patlak:
            raise RuntimeError('motor yok')
        return self._engine


class _Pencere:
    def __init__(self):
        self.runs = []
        self.logs = []
        self.run_patlak = False

    def _run(self, worker, desc=None, on_ok=None):
        if self.run_patlak:
            raise RuntimeError('calistirilamadi')
        self.runs.append((worker, desc, on_ok))

    def append_log(self, msg, level='INFO'):
        self.logs.append((msg, level))


class _SahteIsci(QObject):
    finished_ok = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, func=None, *args, **kwargs):
        super().__init__()
        self.args = (func,) + args
        self.kwargs = kwargs
        self.cancel_calls = 0
        self.iptal_edildi = False

    def cancel(self):
        self.cancel_calls += 1

    def isInterruptionRequested(self):
        return self.iptal_edildi

    def isFinished(self):
        return False


@pytest.fixture
def debloat(qtbot, monkeypatch):
    monkeypatch.setattr(deb_mod, 'Worker', _SahteIsci)
    monkeypatch.setattr(deb_mod, 'all_categories', _kategoriler)
    core = _Cekirdek()
    win = _Pencere()
    tab = DebloatTab(core, win)
    qtbot.addWidget(tab)
    # Kurulumdaki otomatik varlik taramasi temizlenir.
    tab._invalidate_presence_scan()
    win.runs.clear()
    win.logs.clear()
    return tab, core, win


def test_kurulum(qtbot, monkeypatch):
    monkeypatch.setattr(deb_mod, 'Worker', _SahteIsci)
    monkeypatch.setattr(deb_mod, 'all_categories', _kategoriler)
    core = _Cekirdek()
    win = _Pencere()
    tab = DebloatTab(core, win)
    qtbot.addWidget(tab)

    assert tab.grid.columnCount() == 8
    assert tab.cmb_cat.itemText(0) == 'Tümü'
    assert tab.cmb_cat.itemData(0) == 'all'
    assert tab.cmb_cat.count() == 1 + len(_kategoriler())
    assert tab.cmb_removal.count() == 5
    assert tab.cmb_removal.itemText(1) == 'Önerilen (Recommended)'
    assert tab.cmb_removal.itemData(1) == 'Recommended'
    assert tab.cmb_ulist.count() == 6
    assert tab.cmb_ulist.itemData(1) == 'Google'
    assert tab.cmb_user.itemData(0) == 0
    assert tab.cmb_user.itemText(0) == 'Kullanıcı: Owner (0)'
    assert tab.advanced_filters.isHidden() is True
    assert tab.btn_advanced.isChecked() is False
    assert core.config.show_unlisted is False

    # Kurulum otomatik varlik taramasini baslatir
    w = win.runs[-1][0]
    assert isinstance(w, _SahteIsci)
    assert win.runs[-1][1] == 'Debloat: cihazda kurulu paketler taraniyor'
    assert w.job_name == 'Debloat varlik taramasi'
    assert (w._presence_engine, w._presence_target, w._presence_user_id) == (
        core._engine, 'tv-1', 0)
    assert tab._presence_scanning is True
    assert tab.btn_scan.isEnabled() is False
    assert tab.lbl_presence.text() == 'Cihaz: taranıyor…'
    assert tab.lbl_summary.text() == 'Cihaz varlığı bilinmiyor — taranıyor...'
    assert tab.grid.empty_title == 'Cihaz taranıyor'

    # Isci fonksiyonu: kurulu ve devre disi paketleri ayirir
    core._engine.packages = [
        {'package': 'com.g.one', 'installed_user0': True, 'enabled': True},
        {'package': 'com.g.two', 'installed_user0': True, 'enabled': False},
        {'package': 'com.x.only', 'installed_user0': False},
    ]
    sonuc = w.args[0]()
    assert sonuc == {'present': {'com.g.one', 'com.g.two'},
                     'disabled': {'com.g.two'}}
    assert ('list_packages_detailed', 'tv-1', True, False, 0) in core._engine.calls

    w.finished_ok.emit(sonuc)
    assert tab._presence_known is True
    assert tab._present == {'com.g.one', 'com.g.two'}
    assert tab._disabled == {'com.g.two'}
    assert tab.grid.rowCount() == 2
    assert tab.lbl_summary.text() == (
        'Tümü: 2 / 2 kurulu paket gösteriliyor; cihazda toplam 2 paket kurulu.')
    assert tab._presence_worker is None
    assert tab._presence_scanning is False
    assert tab.btn_scan.isEnabled() is True


def test_kurulum_kayitli_kullanici_ve_listesiz(qtbot, monkeypatch):
    monkeypatch.setattr(deb_mod, 'Worker', _SahteIsci)
    monkeypatch.setattr(deb_mod, 'all_categories', _kategoriler)
    core = _Cekirdek()
    core.config.user_id = 3
    core.config.show_unlisted = True
    tab = DebloatTab(core, _Pencere())
    qtbot.addWidget(tab)
    assert tab.chk_unlisted.isChecked() is True
    assert tab.cmb_user.count() == 1
    assert tab.cmb_user.itemText(0) == (
        'Kullanıcı: 3 (kayıtlı; adını bulmak için tara)')
    assert tab.cmb_user.itemData(0) == 3

    # show_unlisted okunamazsa varsayilan atanir
    core2 = _Cekirdek()
    del core2.config.show_unlisted
    tab2 = DebloatTab(core2, _Pencere())
    qtbot.addWidget(tab2)
    assert core2.config.show_unlisted is False


def test_gelismis_filtreler(debloat):
    tab, core, _win = debloat
    assert tab.advanced_filters.isHidden() is True
    tab.btn_advanced.setChecked(True)
    assert tab.advanced_filters.isHidden() is False
    assert tab.btn_advanced.arrowType() == Qt.DownArrow
    tab.btn_advanced.setChecked(False)
    assert tab.btn_advanced.arrowType() == Qt.RightArrow

    # Filtreleri sifirla: guvenli kategori, temiz arama, listesiz kapanir
    core.config.show_unlisted = True
    tab.chk_unlisted.setChecked(True)
    assert core.config.save_calls == 1
    tab.txt_search.setText('bir')
    tab.cmb_removal.setCurrentIndex(1)
    tab.cmb_ulist.setCurrentIndex(1)
    tab._reset_filters()
    assert tab.cmb_cat.currentData() == 'guvenli'
    assert tab.txt_search.text() == ''
    assert tab.cmb_removal.currentIndex() == 0
    assert tab.cmb_ulist.currentIndex() == 0
    assert tab.chk_unlisted.isChecked() is False
    assert core.config.show_unlisted is False
    assert core.config.save_calls == 2

    # Guvenli kategori yoksa kategori secimi degismez
    tab.cmb_cat.blockSignals(True)
    tab.cmb_cat.clear()
    tab.cmb_cat.addItem('Tümü', 'all')
    tab.cmb_cat.setCurrentIndex(0)
    tab.cmb_cat.blockSignals(False)
    tab._reset_filters()
    assert tab.cmb_cat.currentData() == 'all'


def test_tekerlek_kilidi(qtbot):
    combo = _NoWheelComboBox()
    qtbot.addWidget(combo)

    class _Olay:
        def __init__(self):
            self.ignored = False

        def ignore(self):
            self.ignored = True

    olay = _Olay()
    combo.wheelEvent(olay)      # liste gorunmuyor -> yok sayilir
    assert olay.ignored is True

    class _Gorunur(_NoWheelComboBox):
        super_calls = 0

        def view(self):
            return SimpleNamespace(isVisible=lambda: True)

        def wheelEvent(self, event):
            type(self).super_calls += 1
            return super().wheelEvent(event)

    gorunur = _Gorunur()
    qtbot.addWidget(gorunur)
    gorunur.wheelEvent(QWheelEvent(
        QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
    assert _Gorunur.super_calls == 1


def test_tema(debloat, monkeypatch):
    tab, _core, _win = debloat

    def patlak(*_a, **_k):
        raise RuntimeError('tema yok')

    monkeypatch.setattr(deb_mod.kit, 'dark_from', patlak)
    tab.apply_theme()   # ilk blok hata verir; sessizce cikilir

    monkeypatch.setattr(deb_mod.kit, 'dark_from', lambda *a, **k: True)
    monkeypatch.setattr(deb_mod.kit, 'muted', lambda dark: 'MUT({})'.format(dark))
    monkeypatch.setattr(deb_mod.kit, 'faint', lambda dark: 'FAINT({})'.format(dark))
    monkeypatch.setattr(deb_mod.kit, 'title', lambda dark: 'TITLE({})'.format(dark))
    tab.apply_theme()
    assert tab.lbl_hint.styleSheet() == 'MUT(True)'
    assert tab.lbl_presence.styleSheet() == 'FAINT(True)'
    assert tab.lbl_sel.styleSheet() == 'FAINT(True)'
    assert tab.lbl_stage.styleSheet() == 'TITLE(True)'

    def reload_patlak(*_a, **_k):
        raise RuntimeError('yok')

    monkeypatch.setattr(tab, '_reload', reload_patlak)
    tab.apply_theme()

    def reload_bozuk(*_a, **_k):
        raise ValueError('beklenmeyen')

    monkeypatch.setattr(tab, '_reload', reload_bozuk)
    tab.apply_theme()


def test_varlik_etiketi(debloat):
    tab, core, _win = debloat
    core.connected = False
    tab._presence_scanning = False
    tab._presence_known = False
    tab._update_presence_label()
    assert tab.lbl_presence.text() == 'Cihaz: bağlı değil'

    core.connected = True
    tab._presence_scanning = True
    tab._update_presence_label()
    assert tab.lbl_presence.text() == 'Cihaz: taranıyor…'

    tab._presence_scanning = False
    tab._presence_known = True
    tab._present = {'a', 'b'}
    tab._update_presence_label()
    assert tab.lbl_presence.text() == 'Cihaz: 2 paket kurulu'

    tab._presence_known = False
    tab._update_presence_label()
    assert tab.lbl_presence.text() == 'Cihaz: bilinmiyor'


def test_varlik_taramasi_kapilari(debloat):
    tab, core, win = debloat

    # Baglantisiz: devam eden isci iptal edilir, liste temizlenir
    bekleyen = _SahteIsci()
    tab._presence_worker = bekleyen
    tab._presence_scanning = True
    tab._present = {'a'}
    tab._disabled = {'a'}
    tab._presence_known = True
    core.connected = False
    tab._scan_presence()
    assert bekleyen.cancel_calls == 1
    assert tab._presence_worker is None
    assert tab._present == set()
    assert tab._disabled == set()
    assert tab._presence_known is False
    assert tab._presence_target is None
    assert tab.btn_scan.isEnabled() is True
    assert tab.lbl_presence.text() == 'Cihaz: bağlı değil'
    assert tab.lbl_summary.text() == (
        'Bağlı cihaz yok — bağlanınca paket varlığı taranabilir.')
    assert tab.grid.empty_title == 'Bağlı cihaz yok'

    # Bagli: tarama baslar ve ikinci cagri yeni isci kurmaz
    core.connected = True
    tab._scan_presence()
    assert len(win.runs) == 1
    assert tab._presence_scanning is True
    w1 = win.runs[-1][0]
    tab._scan_presence()
    assert len(win.runs) == 1
    assert tab._presence_worker is w1

    # Bayat kayit: onceki isci iptal edilir, yeni tarama baslar
    w1._presence_target = 'tv-9'
    tab._scan_presence()
    assert w1.cancel_calls == 1
    assert len(win.runs) == 2
    assert win.runs[-1][0] is not w1
    tab._invalidate_presence_scan()

    # Motor erisilemezse hata yolu
    core.engine_patlak = True
    tab._scan_presence()
    assert tab.lbl_summary.text() == 'Paket varlığı taranamadı: motor yok'
    assert tab.grid.empty_title == 'Paketler taranamadı'
    core.engine_patlak = False

    # window._run patlarsa hata yolu islenir, kayit temizlenir
    win.run_patlak = True
    tab._scan_presence()
    assert tab.lbl_summary.text() == 'Paket varlığı taranamadı: calistirilamadi'
    assert tab._presence_worker is None
    assert tab._presence_scanning is False
    win.run_patlak = False


def test_varlik_hazirlik_sonrasi_baglam_bozulmasi(debloat, monkeypatch):
    tab, _core, win = debloat
    once = len(win.runs)
    gercek = tab._presence_context_current
    monkeypatch.setattr(tab, '_presence_context_current', lambda *a, **k: False)
    tab._scan_presence()
    assert len(win.runs) == once
    assert tab._presence_worker is None
    assert tab._presence_scanning is False
    assert tab.btn_scan.isEnabled() is True
    monkeypatch.setattr(tab, '_presence_context_current', gercek)


def test_varlik_iscisi_baglam_kontrolleri(debloat):
    tab, core, _win = debloat
    tab._scan_presence()
    w = tab._presence_worker
    assert w is not None
    assert w.args[0]() == {'present': set(), 'disabled': set()}

    core.target = 'tv-9'
    with pytest.raises(CancelledError):
        w.args[0]()
    core.target = 'tv-1'

    core.config.user_id = 2
    with pytest.raises(CancelledError):
        w.args[0]()
    core.config.user_id = 0

    tab._presence_target = 'tv-9'
    with pytest.raises(CancelledError):
        w.args[0]()
    tab._presence_target = 'tv-1'

    tab._presence_generation += 1
    with pytest.raises(CancelledError):
        w.args[0]()
    tab._presence_generation -= 1

    core.connected = False
    with pytest.raises(CancelledError):
        w.args[0]()
    core.connected = True

    motor = core._engine
    core._engine = _Motor()
    with pytest.raises(CancelledError):
        w.args[0]()
    core._engine = motor

    w.iptal_edildi = True
    with pytest.raises(CancelledError):
        w.args[0]()
    w.iptal_edildi = False

    tab._invalidate_presence_scan()


def test_varlik_sonuc_ve_hata_yollari(debloat):
    tab, core, _win = debloat

    # Basarili sonuc: kume guncellenir
    w = _SahteIsci()
    w._presence_engine = core._engine
    w._presence_target = 'tv-1'
    w._presence_generation = tab._presence_generation
    w._presence_user_id = 0
    tab._presence_worker = w
    tab._presence_scanning = True
    tab._presence_target = 'tv-1'
    tab._presence_scan_succeeded(w, core._engine, 'tv-1',
                                 tab._presence_generation,
                                 {'present': {'com.g.one'}, 'disabled': set()})
    assert tab._present == {'com.g.one'}
    assert tab._presence_known is True
    assert tab._presence_worker is None
    assert tab._presence_scanning is False
    assert tab.btn_scan.isEnabled() is True

    # Bayat basari: hicbir sey degismez, isci kayittan duser
    w2 = _SahteIsci()
    tab._presence_worker = w2
    tab._presence_scanning = True
    core.target = 'tv-9'
    tab._presence_scan_succeeded(w2, core._engine, 'tv-1',
                                 tab._presence_generation,
                                 {'present': {'x.y'}})
    core.target = 'tv-1'
    assert tab._present == {'com.g.one'}
    assert tab._presence_worker is None

    # Basarisiz tarama: ozet + bos durum (bilinmiyor)
    tab._presence_known = False
    w3 = _SahteIsci()
    w3._presence_engine = core._engine
    w3._presence_target = 'tv-1'
    w3._presence_generation = tab._presence_generation
    w3._presence_user_id = 0
    tab._presence_worker = w3
    tab._presence_scanning = True
    tab._presence_target = 'tv-1'
    tab._presence_scan_failed(w3, core._engine, 'tv-1',
                              tab._presence_generation, 'adbsiz')
    assert tab.lbl_summary.text() == 'Paket varlığı taranamadı: adbsiz'
    assert tab.grid.empty_title == 'Paketler taranamadı'
    assert tab._presence_worker is None

    # Bayat hata: ozet degismez, isci yine kayittan duser
    w4 = _SahteIsci()
    tab._presence_worker = w4
    tab._presence_scanning = True
    tab._presence_scan_failed(w4, core._engine, 'tv-1',
                              tab._presence_generation + 1, 'gec')
    assert tab.lbl_summary.text() == 'Paket varlığı taranamadı: adbsiz'
    assert tab._presence_worker is None

    # Bilinen liste varken hata bos durum metnini degistirmez
    tab._presence_known = True
    onceki_baslik = tab.grid.empty_title
    tab._on_presence_fail('x')
    assert tab.lbl_summary.text() == 'Paket varlığı taranamadı: x'
    assert tab.grid.empty_title == onceki_baslik


def test_set_present_bicimleri(debloat):
    tab, _core, _win = debloat
    tab._set_present(['com.g.one', 'com.g.two'])
    assert tab._present == {'com.g.one', 'com.g.two'}
    assert tab._disabled == set()
    assert tab._presence_known is True
    tab._set_present({'present': {'com.g.one'}, 'disabled': {'com.g.one'}})
    assert tab._present == {'com.g.one'}
    assert tab._disabled == {'com.g.one'}
    tab._set_present(None)
    assert tab._present == set()
    assert tab._presence_known is True


def test_set_present_ve_scan_if_needed(debloat):
    tab, core, win = debloat

    # Baglantisiz: sifirlanir ve liste bos gosterilir
    bekleyen = _SahteIsci()
    tab._presence_worker = bekleyen
    tab._presence_scanning = True
    core.connected = False
    tab.set_present({'present': {'a'}})
    assert bekleyen.cancel_calls == 1
    assert tab._present == set()
    assert tab._presence_known is False
    assert tab.lbl_summary.text() == (
        'Bağlı cihaz yok — bağlanınca cihaz uygulamaları listelenecek.')
    core.connected = True

    # Kullanici 0 disinda: disaridan gelen sonuc yok sayilir
    core.config.user_id = 2
    tab._present = {'korunan'}
    tab.set_present({'present': {'a'}})
    assert tab._present == {'korunan'}
    core.config.user_id = 0

    # Sozluk bicimi hedefi de tazeler
    tab.set_present({'present': {'com.g.one'}, 'disabled': {'com.g.one'}})
    assert tab._present == {'com.g.one'}
    assert tab._disabled == {'com.g.one'}
    assert tab._presence_target == 'tv-1'
    assert tab.btn_scan.isEnabled() is True

    # Liste bicimi; _disabled yoksa olusturulur
    del tab._disabled
    tab.set_present(['com.g.two'])
    assert tab._present == {'com.g.two'}
    assert tab._disabled == set()

    # scan_if_needed: zaten taraniyorsa dokunmaz, degilse baslatir
    tab._presence_scanning = True
    tab._presence_worker = _SahteIsci()
    once = len(win.runs)
    tab.scan_if_needed()
    assert len(win.runs) == once
    tab._invalidate_presence_scan()
    once = len(win.runs)
    tab.scan_if_needed()
    assert len(win.runs) == once + 1
    tab._invalidate_presence_scan()


def test_baglanti_degisimi(debloat):
    tab, core, win = debloat
    tab._present = {'a'}
    tab._disabled = {'a'}
    tab._presence_known = True
    eski = _SahteIsci()
    tab._presence_worker = eski
    tab._presence_scanning = True

    core.connection_changed.emit(True, 'tv-2')
    assert eski.cancel_calls == 1
    assert tab._presence_worker is None
    assert tab._presence_scanning is False
    assert tab._present == set()
    assert tab._disabled == set()
    assert tab._presence_known is False
    assert tab._presence_target == 'tv-2'
    assert tab.btn_scan.isEnabled() is True
    assert tab.lbl_presence.text() == 'Cihaz: bilinmiyor'
    assert tab.lbl_summary.text() == (
        'Cihaz varlığı bilinmiyor — tarama bekleniyor...')
    assert tab.grid.empty_title == 'Cihaz taranıyor'

    core.connected = False
    once = len(win.runs)
    core.connection_changed.emit(False, '')
    assert tab._presence_target is None
    assert len(win.runs) == once
    assert tab.lbl_summary.text() == (
        'Bağlı cihaz yok — bağlanınca cihaz uygulamaları listelenecek.')
    assert tab.grid.empty_title == 'Bağlı cihaz yok'


def test_mutasyon_baglami(debloat, monkeypatch):
    tab, core, _win = debloat
    kutular = []
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: kutular.append((a[1], a[2])))

    baglam = tab._capture_mutation_context('X')
    assert baglam == (core._engine, 'tv-1', tab._presence_generation)

    core.connected = False
    assert tab._capture_mutation_context('X') is None
    assert kutular[-1] == ('X', 'Önce bir cihaza bağlanın.')
    core.connected = True

    core.engine_patlak = True
    assert tab._capture_mutation_context('X') is None
    assert kutular[-1] == ('X', 'Cihaz bağlantısı doğrulanamadı: motor yok')
    core.engine_patlak = False

    assert tab._mutation_context_current(None) is False
    assert tab._mutation_context_current(baglam) is True

    core.target = 'tv-9'
    assert tab._mutation_context_current(baglam) is False
    core.target = 'tv-1'
    tab._presence_generation += 1
    assert tab._mutation_context_current(baglam) is False
    tab._presence_generation -= 1
    motor = core._engine
    core._engine = _Motor()
    assert tab._mutation_context_current(baglam) is False
    core._engine = motor
    core.connected = False
    assert tab._mutation_context_current(baglam) is False
    core.connected = True

    assert tab._revalidate_mutation_context(baglam, 'İş') is True
    core.target = 'tv-9'
    assert tab._revalidate_mutation_context(baglam, 'İş') is False
    assert kutular[-1] == (
        'İş',
        'Bağlantı, hedef veya cihaz paket bilgisi değişti. İşlem başlatılmadı; yeniden deneyin.')
    core.target = 'tv-1'


def test_koruma_kontrolu(debloat):
    tab, core, _win = debloat
    assert tab._is_protected('com.g.one') is False
    core.config.protected = {'com.g.one'}
    assert tab._is_protected('com.g.one') is True
    core.config.is_protected = lambda pkg: pkg == 'com.g.two'
    assert tab._is_protected('com.g.two') is True
    assert tab._is_protected('com.g.one') is False


def test_reload_varlik_bilinmiyorken(debloat):
    tab, core, win = debloat
    core.connected = False
    tab._reload()
    assert tab.grid.rowCount() == 0
    assert tab._entries == []
    assert tab.lbl_summary.text() == (
        'Bağlı cihaz yok — bağlanınca cihaz uygulamaları listelenecek.')
    assert tab.grid.empty_title == 'Bağlı cihaz yok'

    core.connected = True
    once = len(win.runs)
    tab._reload()
    assert len(win.runs) == once + 1
    assert tab.lbl_summary.text() == 'Cihaz varlığı bilinmiyor — taranıyor...'
    assert tab.grid.empty_title == 'Cihaz taranıyor'
    tab._invalidate_presence_scan()


def _satir_bul(tab, pkg):
    for r in range(tab.grid.rowCount()):
        if tab.grid.item(r, COL_PKG).text() == pkg:
            return r
    return -1


def test_reload_listesi(debloat, monkeypatch):
    tab, core, _win = debloat
    monkeypatch.setattr(deb_mod, 'uad_removal_of', lambda pkg: {
        'com.g.one': 'Recommended', 'com.g.two': 'Advanced',
        'com.r.one': 'Expert', 'com.d.one': 'Unsafe',
        'com.f.one': 'Advanced', 'com.x.un': 'Pending'}.get(pkg, 'Pending'))
    monkeypatch.setattr(deb_mod, 'uad_list_of', lambda pkg: {
        'com.g.one': 'Google', 'com.g.two': 'Aosp', 'com.r.one': 'Oem',
        'com.d.one': 'Google', 'com.f.one': 'Google',
        'com.x.un': 'Misc'}.get(pkg, 'Misc'))
    monkeypatch.setattr(deb_mod, 'needed_by',
                        lambda pkg: ['Uygulama X'] if pkg == 'com.g.one' else [])
    monkeypatch.setattr(deb_mod, 'cat_colors_for',
                        lambda dark: {'guvenli': '#111111'})
    monkeypatch.setattr(deb_mod, 'removal_colors_for',
                        lambda dark: {'Recommended': '#222222'})
    core.config.protected = {'com.f.one'}
    tab._present = {'com.g.one', 'com.g.two', 'com.r.one',
                    'com.d.one', 'com.f.one'}
    tab._disabled = {'com.g.two'}
    tab._uninstalled = {'com.r.one'}
    tab._presence_known = True
    tab._reload()

    pal = deb_mod.kit.colors(tab)
    assert tab.grid.rowCount() == 5
    assert tab.lbl_summary.text() == (
        'Tümü: 5 / 5 kurulu paket gösteriliyor; cihazda toplam 5 paket kurulu.')

    r = _satir_bul(tab, 'com.g.one')
    chk = tab.grid.item(r, COL_CHECK)
    assert chk.flags() & Qt.ItemIsUserCheckable
    assert chk.checkState() == Qt.Unchecked
    assert chk.data(Qt.UserRole) == 'com.g.one'
    ad = tab.grid.item(r, COL_NAME)
    assert ad.text() == 'Bir'
    assert ad.foreground().color().name() == '#111111'
    assert tab.grid.item(r, COL_PRESENT).text() == 'Evet'
    assert tab.grid.item(r, COL_PRESENT).foreground().color().name() == \
        pal['success']
    assert tab.grid.item(r, COL_STATE).text() == 'Kurulu'
    assert tab.grid.item(r, COL_UAD).text() == 'Önerilen / Google ⚠'
    assert 'BUNA IHTIAC DUYANLAR: Uygulama X' in \
        tab.grid.item(r, COL_UAD).toolTip()
    assert tab.grid.item(r, COL_UAD).foreground().color().name() == '#222222'
    assert tab.grid.item(r, COL_SAFETY).text() == 'Güvenli'

    assert tab.grid.item(_satir_bul(tab, 'com.g.two'), COL_STATE).text() == \
        'Devre dışı'
    assert tab.grid.item(_satir_bul(tab, 'com.r.one'), COL_STATE).text() == \
        'Kaldirilmis'
    assert tab.grid.item(_satir_bul(tab, 'com.r.one'), COL_UAD).text() == \
        'Uzman / Oem'

    # Kritik satir: secilemez, kalin ve tehlike renginde
    r = _satir_bul(tab, 'com.d.one')
    kritik = tab.grid.item(r, COL_CHECK)
    assert not (kritik.flags() & Qt.ItemIsUserCheckable)
    assert kritik.toolTip() == 'Kritik sistem paketi: işlem için seçilemez'
    assert tab.grid.item(r, COL_NAME).font().bold() is True
    assert tab.grid.item(r, COL_NAME).foreground().color().name() == \
        pal['danger']
    assert tab.grid.item(r, COL_SAFETY).text() == 'Dokunma (Kritik)'
    assert tab.grid.item(r, COL_SAFETY).font().bold() is True

    # Korunan satir: secilemez, uyari renkli ve ipuclu
    r = _satir_bul(tab, 'com.f.one')
    korunan = tab.grid.item(r, COL_CHECK)
    assert not (korunan.flags() & Qt.ItemIsUserCheckable)
    assert korunan.toolTip() == 'Koruma listesinde: işlem için seçilemez'
    assert tab.grid.item(r, COL_NAME).foreground().color().name() == \
        pal['warning']
    assert tab.grid.item(r, COL_SAFETY).toolTip().endswith(
        'Koruma listesinde: işlem için seçilemez')

    # Kategori filtresi
    tab.cmb_cat.setCurrentIndex(tab.cmb_cat.findData('riskli'))
    assert tab.grid.rowCount() == 1
    assert tab.grid.item(0, COL_PKG).text() == 'com.r.one'
    assert tab.lbl_summary.text().startswith('Riskli: 1 / 1')
    tab.cmb_cat.setCurrentIndex(0)

    # Arama: ad, aciklama ve paket uzerinde Turkce katlamali
    tab.txt_search.setText('ikinci')
    assert tab.grid.rowCount() == 1
    assert tab.grid.item(0, COL_PKG).text() == 'com.g.two'
    tab.txt_search.setText('com.r')
    assert tab.grid.rowCount() == 1
    assert tab.grid.item(0, COL_PKG).text() == 'com.r.one'
    tab.txt_search.clear()

    # Seviye ve kaynak filtreleri
    tab.cmb_removal.setCurrentIndex(
        tab.cmb_removal.findData('Recommended'))
    assert tab.grid.rowCount() == 1
    assert tab.grid.item(0, COL_PKG).text() == 'com.g.one'
    tab.cmb_removal.setCurrentIndex(0)
    tab.cmb_ulist.setCurrentIndex(tab.cmb_ulist.findData('Google'))
    assert tab.grid.rowCount() == 3
    tab.cmb_ulist.setCurrentIndex(0)

    # Listesiz paketler yalnizca onay kutusuyla eklenir
    tab._present = set(tab._present) | {'com.x.un'}
    tab.chk_unlisted.setChecked(True)
    assert core.config.show_unlisted is True
    assert core.config.save_calls >= 1
    assert tab.grid.rowCount() == 6
    r = _satir_bul(tab, 'com.x.un')
    assert tab.grid.item(r, COL_NAME).text() == 'un'
    assert tab.grid.item(r, COL_DESC).text() == (
        'Listesiz — cihazda kurulu, veritabanında yok')
    assert tab.grid.item(r, COL_SAFETY).text() == 'Listesiz'
    assert tab.grid.item(r, COL_UAD).text() == 'Pending / Misc'
    tab.chk_unlisted.setChecked(False)
    assert tab.grid.rowCount() == 5

    # Bostaki bos durum metinleri
    tab._present = set()
    tab._reload()
    assert tab.grid.rowCount() == 0
    assert tab.grid.empty_title == 'Bu kategoride kurulu paket yok'
    tab._present = {'com.g.one'}
    tab.txt_search.setText('zzz')
    assert tab.grid.rowCount() == 0
    assert tab.grid.empty_title == 'Eşleşen paket yok'
    tab.txt_search.clear()
    assert tab.grid.rowCount() == 1
    assert tab.grid.empty_title == 'Cihaz uygulamaları bekleniyor'


def test_secim_yardimcilari(debloat):
    tab, core, _win = debloat
    core.config.protected = {'com.f.one'}
    tab._present = {'com.g.one', 'com.g.two', 'com.d.one', 'com.f.one'}
    tab._presence_known = True
    tab._reload()
    assert tab.grid.rowCount() == 4

    tab._toggle_all(True)
    assert tab.lbl_sel.text() == 'Seçili: 2/4'
    assert tab._selected_packages() == ['com.g.one', 'com.g.two']
    tab._invert_all()
    assert tab.lbl_sel.text() == 'Seçili: 0/4'
    tab._invert_all()
    assert tab.lbl_sel.text() == 'Seçili: 2/4'
    tab.chk_all.click()
    assert tab.lbl_sel.text() == 'Seçili: 2/4'
    tab.chk_none.click()
    assert tab.lbl_sel.text() == 'Seçili: 0/4'
    tab._toggle_all(True)
    tab.chk_inv.click()
    assert tab.lbl_sel.text() == 'Seçili: 0/4'

    # Yalnizca satir secimi: '(satır)' eklenir ve liste secimden gelir
    tab.grid.selectRow(0)
    assert tab.lbl_sel.text() == 'Seçili: 1/4 (satir)'
    assert tab._selected_packages() == ['com.g.one']
    tab.grid.clearSelection()
    assert tab.lbl_sel.text() == 'Seçili: 0/4'

    # Eksik hucreler toplu islemlerde atlanir
    oge = tab.grid.takeItem(0, COL_CHECK)
    tab._toggle_all(True)
    assert tab.lbl_sel.text() == 'Seçili: 1/4'
    tab._invert_all()
    assert tab.lbl_sel.text() == 'Seçili: 0/4'
    tab.grid.setItem(0, COL_CHECK, oge)

    # Bozuk tablo: sayim sessiz kalir
    class _Patlak:
        def rowCount(self):
            raise RuntimeError('yok')

    DebloatTab._update_sel_count(SimpleNamespace(grid=_Patlak()))


def _kutular(monkeypatch):
    out = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: out.append(('info', a[1], a[2])))
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: out.append(('uyari', a[1], a[2])))
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: out.append(('kritik', a[1], a[2])))
    return out


def test_bulk_kapilari(debloat, monkeypatch):
    tab, core, win = debloat
    kutular = _kutular(monkeypatch)
    onaylar = []
    monkeypatch.setattr(dialogs_mod, 'confirm_action',
                        lambda *a, **k: onaylar.append(a + (k.get('extra'),)) or True)
    isciler = []

    def isci(*a, **k):
        w = _SahteIsci(*a, **k)
        isciler.append(w)
        return w

    monkeypatch.setattr(deb_mod, 'PackageActionWorker', isci)
    monkeypatch.setattr(workers_mod, 'format_action_result',
                        lambda res, name=None: 'RAPOR')

    # Secim yok
    tab._bulk('disable')
    assert kutular[-1] == ('info', 'Seçim', 'Önce paketleri seçin.')

    # Baglanti yok: baglam alinamaz, hicbir islem yapilmaz
    monkeypatch.setattr(tab, '_selected_packages', lambda: ['com.g.one'])
    core.connected = False
    tab._bulk('disable')
    assert kutular[-1] == ('uyari', 'Paket işlemi', 'Önce bir cihaza bağlanın.')
    assert onaylar == [] and isciler == []
    core.connected = True

    # Kismen bloklanan secim: uyari + kalan paketlerle devam
    core.config.protected = {'com.f.koru'}
    monkeypatch.setattr(tab, '_selected_packages',
                        lambda: ['com.d.one', 'com.g.one', 'com.f.koru'])
    tab._bulk('disable')
    assert kutular[-1] == (
        'uyari', 'Paket işlemi',
        'Kritik veya koruma listesindeki paketler işlemden çıkarıldı: '
        'com.d.one, com.f.koru')
    assert onaylar[-1][1] == 'disable'
    assert onaylar[-1][2] == ['com.g.one']
    assert isciler[-1].args[2] == ['com.g.one']

    # Tamamen bloklanan secim: onay cagrilmaz
    onay_sayisi = len(onaylar)
    monkeypatch.setattr(tab, '_selected_packages', lambda: ['com.d.one'])
    tab._bulk('disable')
    assert len(onaylar) == onay_sayisi

    # Onay reddi: isci kurulmaz
    monkeypatch.setattr(tab, '_selected_packages', lambda: ['com.g.one'])
    monkeypatch.setattr(dialogs_mod, 'confirm_action', lambda *a, **k: False)
    isci_sayisi = len(isciler)
    tab._bulk('disable')
    assert len(isciler) == isci_sayisi


def test_bulk_bagimlilik_sorusu(debloat, monkeypatch):
    tab, _core, _win = debloat
    _kutular(monkeypatch)
    monkeypatch.setattr(
        deb_mod, 'needed_by',
        lambda pkg: ['Bagimli Uygulama'] if pkg == 'com.g.one' else [])
    sorular = []

    def sor(*a, **k):
        sorular.append((a[1], a[2]))
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, 'question', sor)
    onaylar = []
    monkeypatch.setattr(dialogs_mod, 'confirm_action',
                        lambda *a, **k: onaylar.append(a) or True)
    monkeypatch.setattr(deb_mod, 'PackageActionWorker',
                        lambda *a, **k: _SahteIsci(*a, **k))

    monkeypatch.setattr(tab, '_selected_packages', lambda: ['com.g.one'])
    tab._bulk('disable')
    assert sorular and sorular[-1][0] == 'Bağımlılık Uyarısı'
    assert 'Bazı paketlere BAŞKALARI ihtiyaç duyuyor (UAD neededBy):' in \
        sorular[-1][1]
    assert 'com.g.one gerekli: Bagimli Uygulama' in sorular[-1][1]
    assert 'Yine de devam edilsin mi?' in sorular[-1][1]
    assert onaylar == []

    # Evet: onaya devam edilir
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(tab, '_selected_packages', lambda: ['com.g.one'])
    tab._bulk('disable')
    assert onaylar and onaylar[-1][1] == 'disable'


def test_bulk_bagimlilik_uyari_kirpma(debloat, monkeypatch):
    tab, _core, _win = debloat
    _kutular(monkeypatch)
    paketler = [('com.p.{:02d}'.format(i), 'P{}'.format(i), 'aciklama')
                for i in range(12)]
    monkeypatch.setattr(
        deb_mod, 'all_categories',
        lambda: [('guvenli', 'Güvenli (Kaldırılabilir)', paketler)])
    monkeypatch.setattr(deb_mod, 'needed_by', lambda pkg: ['Bagimli'])
    sorular = []
    monkeypatch.setattr(QMessageBox, 'question',
                        lambda *a, **k: sorular.append(a[2]) or QMessageBox.No)
    tab._present = {'com.p.{:02d}'.format(i) for i in range(12)}
    tab._presence_known = True
    tab._reload()
    tab._toggle_all(True)
    tab._bulk('disable')
    assert '... ve 2 tane daha' in sorular[-1]


def test_bulk_risk_politikasi(debloat, monkeypatch):
    tab, core, win = debloat
    kutular = _kutular(monkeypatch)
    onaylar = []
    monkeypatch.setattr(dialogs_mod, 'confirm_action',
                        lambda *a, **k: onaylar.append(a + (k.get('extra'),)) or True)
    isciler = []

    def paket_iscisi(*a, **k):
        w = _SahteIsci(*a, **k)
        isciler.append(w)
        return w

    monkeypatch.setattr(deb_mod, 'PackageActionWorker', paket_iscisi)
    akilli = []

    def akilli_iscisi(*a, **k):
        w = _SahteIsci(*a, **k)
        akilli.append(w)
        return w

    monkeypatch.setattr(workers_mod, 'SmartRemoveWorker', akilli_iscisi)
    monkeypatch.setattr(workers_mod, 'format_action_result',
                        lambda res, name=None: 'RAPOR')

    tab._present = {'com.g.one', 'com.r.one'}
    tab._presence_known = True
    tab._reload()

    # Yalnizca riskli secim: smart onayi + akilli kaldirma
    monkeypatch.setattr(tab, '_selected_packages', lambda: ['com.r.one'])
    tab._bulk('uninstall')
    assert onaylar[-1][1] == 'smart'
    assert onaylar[-1][2] == ['com.r.one']
    assert onaylar[-1][4] == (
        'RISKL kategori: Güvenlik politikasi geregi Kaldır yerine '
        'önce Devre dışı denenir (Akilli Kaldır).')
    assert akilli[-1].args == (core._engine, 'tv-1', ['com.r.one'],
                               core.config.protected)
    assert akilli[-1].kwargs == {'user_id': 0}
    assert win.runs[-1][0] is akilli[-1]
    akilli[-1].finished_ok.emit({'ok': 1})
    assert kutular[-1] == ('info', 'Akilli Kaldırma', 'RAPOR')

    # Normal + riskli: once normal isci, bitince akilli kaldirma
    monkeypatch.setattr(tab, '_selected_packages',
                        lambda: ['com.g.one', 'com.r.one'])
    tab._bulk('uninstall')
    assert onaylar[-2][1] == 'uninstall' and onaylar[-2][2] == ['com.g.one']
    assert onaylar[-1][1] == 'smart' and onaylar[-1][2] == ['com.r.one']
    w = isciler[-1]
    assert w.args == (core._engine, 'tv-1', ['com.g.one'], 'uninstall',
                      core.config.protected)
    assert w.kwargs == {'user_id': 0}
    assert win.runs[-1][0] is w
    once_akilli = len(akilli)
    w.finished_ok.emit({'ok': 1})
    assert len(akilli) == once_akilli + 1

    # Iptal edilen sonuc: riskli asamaya gecilmez
    monkeypatch.setattr(tab, '_selected_packages',
                        lambda: ['com.g.one', 'com.r.one'])
    once_akilli = len(akilli)
    tab._bulk('uninstall')
    w = isciler[-1]
    w.finished_ok.emit({'ok': 1, 'cancelled': 1})
    assert len(akilli) == once_akilli

    # Kesinti istegi: gecilmez
    monkeypatch.setattr(tab, '_selected_packages',
                        lambda: ['com.g.one', 'com.r.one'])
    once_akilli = len(akilli)
    tab._bulk('uninstall')
    w = isciler[-1]
    w.iptal_edildi = True
    w.finished_ok.emit({'ok': 1})
    assert len(akilli) == once_akilli

    # Sozluk olmayan sonuc: gecilmez
    monkeypatch.setattr(tab, '_selected_packages',
                        lambda: ['com.g.one', 'com.r.one'])
    once_akilli = len(akilli)
    tab._bulk('uninstall')
    w = isciler[-1]
    w.finished_ok.emit('bozuk')
    assert len(akilli) == once_akilli

    # Smart onayi reddedilirse hicbir isci kurulmaz
    def sadece_smart(a_self, action, pkgs, name_of, extra=None):
        return action != 'smart'

    monkeypatch.setattr(dialogs_mod, 'confirm_action', sadece_smart)
    monkeypatch.setattr(tab, '_selected_packages',
                        lambda: ['com.g.one', 'com.r.one'])
    isci_sayisi = len(isciler)
    once_akilli = len(akilli)
    tab._bulk('uninstall')
    assert len(isciler) == isci_sayisi
    assert len(akilli) == once_akilli

    # _smart_remove: bayat baglam islem baslatmaz
    baglam = tab._capture_mutation_context('X')
    core.target = 'tv-9'
    once_akilli = len(akilli)
    tab._smart_remove(['com.r.one'], baglam, 0)
    assert len(akilli) == once_akilli
    assert kutular[-1] == (
        'uyari', 'Akıllı kaldırma',
        'Bağlantı, hedef veya cihaz paket bilgisi değişti. '
        'İşlem başlatılmadı; yeniden deneyin.')
    core.target = 'tv-1'


def test_bulk_onay_dallari(debloat, monkeypatch):
    tab, core, win = debloat
    kutular = _kutular(monkeypatch)
    onaylar = []
    monkeypatch.setattr(dialogs_mod, 'confirm_action',
                        lambda *a, **k: onaylar.append(a + (k.get('extra'),)) or True)
    isciler = []

    def paket_iscisi(*a, **k):
        w = _SahteIsci(*a, **k)
        isciler.append(w)
        return w

    monkeypatch.setattr(deb_mod, 'PackageActionWorker', paket_iscisi)
    akilli = []

    def akilli_iscisi(*a, **k):
        w = _SahteIsci(*a, **k)
        akilli.append(w)
        return w

    monkeypatch.setattr(workers_mod, 'SmartRemoveWorker', akilli_iscisi)
    monkeypatch.setattr(workers_mod, 'format_action_result',
                        lambda res, name=None: 'RAPOR')

    tab._present = {'com.g.one', 'com.r.one'}
    tab._presence_known = True
    tab._reload()
    tab.cmb_cat.setCurrentIndex(tab.cmb_cat.findData('riskli'))
    monkeypatch.setattr(tab, '_selected_packages', lambda: ['com.r.one'])

    # Riskli kategori + uninstall: uyari ekli smart onayi
    once = len(akilli)
    tab._bulk('uninstall')
    assert onaylar[-1][1] == 'smart'
    assert onaylar[-1][4] == (
        'RISKL kategori: Güvenlik politikasi geregi Kaldır yerine '
        'önce Devre dışı denenir (Akilli Kaldır).')
    assert len(akilli) == once + 1

    # Riskli kategori + disable: uyari ekli onay + normal isci
    sayi = len(isciler)
    tab._bulk('disable')
    assert onaylar[-1][1] == 'disable'
    assert onaylar[-1][4] == 'RISKL kategori — sistem bozulabilir!'
    assert len(isciler) == sayi + 1

    # Riskli kategori + smart: onay sonrasi akilli kaldirma
    once = len(akilli)
    tab._bulk('smart')
    assert onaylar[-1][1] == 'smart'
    assert len(akilli) == once + 1

    # Riskli kategori + restore: duz onay + isci
    sayi = len(isciler)
    tab._bulk('restore')
    assert onaylar[-1][1] == 'restore'
    assert onaylar[-1][4] is None
    assert len(isciler) == sayi + 1

    # 'all' + riskli secili disable: uyari ekli onay
    tab.cmb_cat.setCurrentIndex(0)
    sayi = len(isciler)
    tab._bulk('disable')
    assert onaylar[-1][4] == 'RISKL kategori — sistem bozulabilir!'
    assert len(isciler) == sayi + 1

    # 'all' + riskli secili restore: duz onay
    sayi = len(isciler)
    tab._bulk('restore')
    assert onaylar[-1][4] is None
    assert len(isciler) == sayi + 1

    # Guvenli kategori + uninstall: duz onay
    tab.cmb_cat.setCurrentIndex(tab.cmb_cat.findData('guvenli'))
    monkeypatch.setattr(tab, '_selected_packages', lambda: ['com.g.one'])
    sayi = len(isciler)
    tab._bulk('uninstall')
    assert onaylar[-1][1] == 'uninstall'
    assert onaylar[-1][4] is None
    assert len(isciler) == sayi + 1

    # Isci tamamlaninca sonuc kutusu; on_ok yeniden tarama baslatir
    w = isciler[-1]
    w.finished_ok.emit({'ok': 1})
    assert kutular[-1] == ('info', 'Tamam', 'RAPOR')
    on_ok = win.runs[-1][2]
    once = len(win.runs)
    on_ok({'ok': 1})
    assert len(win.runs) == once + 1
    tab._invalidate_presence_scan()

    # Bayat baglamda sonuc kutusu ve tarama yok
    sayi = len(kutular)
    core.target = 'tv-9'
    w.finished_ok.emit({'ok': 1})
    once = len(win.runs)
    on_ok({'ok': 1})
    assert len(kutular) == sayi
    assert len(win.runs) == once
    core.target = 'tv-1'


def test_sonuc_kutulari(debloat, monkeypatch):
    tab, _core, _win = debloat
    kutular = _kutular(monkeypatch)
    monkeypatch.setattr(workers_mod, 'format_action_result',
                        lambda res, name=None: 'OZET:' + str(res))
    tab._on_done({'ok': 1})
    assert kutular[-1] == ('info', 'Tamam', "OZET:{'ok': 1}")
    tab._on_done_smart({'ok': 2})
    assert kutular[-1] == ('info', 'Akilli Kaldırma', "OZET:{'ok': 2}")


def test_debloat_adi(debloat, monkeypatch):
    tab, _core, _win = debloat
    assert tab._debloat_name('com.g.one') == 'Bir'
    assert tab._debloat_name('com.yok') == 'com.yok'
    monkeypatch.setattr(
        deb_mod, 'all_categories',
        lambda: [('guvenli', 'Güvenli', [('com.g.one', None, 'x')])])
    assert tab._debloat_name('com.g.one') == 'com.g.one'

    def patlak():
        raise RuntimeError('db yok')

    monkeypatch.setattr(deb_mod, 'all_categories', patlak)
    assert tab._debloat_name('com.g.one') == 'com.g.one'


class _SahneDiyalogu:
    karar = 1
    degistirici = None
    kayitlar = []
    Accepted = 1

    def __init__(self, parent, stage, friendly=None, description=None,
                 summary=None):
        self.args = (parent, stage, friendly)
        self.kwargs = {'description': description, 'summary': summary}
        type(self).kayitlar.append(self)

    def exec(self):
        if type(self).degistirici is not None:
            type(self).degistirici()
        return type(self).karar


def test_sahne_islemleri(debloat, monkeypatch):
    tab, core, win = debloat
    kutular = _kutular(monkeypatch)

    # Sahne tembel olusturulur ve pencereye baglanir
    st = tab._stage()
    assert win.stage is st
    assert st.count() == 0
    assert tab.lbl_stage.text() == 'Sahne: 0 işlem'

    # Secim yok: bilgilendirme
    tab._stage_add('disable')
    assert kutular[-1] == ('info', 'Seçim', 'Önce paket seçin.')

    # Secimle ekleme: yeni sayisi ve gunluk
    tab._present = {'com.g.one', 'com.g.two'}
    tab._presence_known = True
    tab._reload()
    tab._toggle_all(True)
    tab._stage_add('disable')
    assert st.count() == 2
    assert tab.lbl_stage.text() == 'Sahne: 2 işlem'
    assert win.logs[-1] == (
        'Sahneye eklendi: disable x 2 (2 yeni)', 'INFO')
    tab._stage_add('disable')
    assert win.logs[-1] == (
        'Sahneye eklendi: disable x 2 (0 yeni)', 'INFO')

    # Temizleme etiketi sifirlar, sahne ayni kalir
    tab._stage_clear()
    assert st.count() == 0
    assert tab.lbl_stage.text() == 'Sahne: 0 işlem'
    assert tab._stage() is st
    assert core.connected is True


def test_sahne_goster(debloat, monkeypatch):
    tab, core, win = debloat
    kutular = _kutular(monkeypatch)

    # Bos sahne
    tab._stage_show()
    assert kutular[-1] == ('info', 'Sahne', 'Sahne boş. Önce işlem ekleyin.')

    # Baglanti yok: baglam alinamaz
    st = tab._stage()
    st.add('disable', 'com.g.one')
    core.connected = False
    tab._stage_show()
    assert kutular[-1] == ('uyari', 'Sahne', 'Önce bir cihaza bağlanın.')
    core.connected = True

    monkeypatch.setattr(stage_dialog_mod, 'StageDialog', _SahneDiyalogu)
    isciler = []

    def stage_iscisi(*a, **k):
        w = _SahteIsci(*a, **k)
        isciler.append(w)
        return w

    monkeypatch.setattr(workers_mod, 'StageWorker', stage_iscisi)
    _SahneDiyalogu.karar = 0
    _SahneDiyalogu.degistirici = None
    _SahneDiyalogu.kayitlar = []

    # Reddedilen diyalog: is kosmaz, diyalog sahneyi alir
    tab._stage_show()
    assert isciler == []
    dlg = _SahneDiyalogu.kayitlar[-1]
    assert dlg.args[1] is st
    assert dlg.args[2] is core.config.friendly_name
    assert dlg.kwargs == {'description': None, 'summary': None}

    # Kabul: isci kurulur ve geri cagri baglanir
    _SahneDiyalogu.karar = 1
    tab._stage_show()
    w = isciler[-1]
    assert w.args == (core._engine, 'tv-1', [('disable', 'com.g.one')],
                      core.config.protected)
    assert w.kwargs == {'user_id': 0}
    assert win.runs[-1][0] is w
    on_ok = win.runs[-1][2]
    assert on_ok is not None

    # Basarisiz paketler sahnede kalir, kalanlar dusurulur
    st.add('disable', 'com.g.two')
    tab._stage_show()
    on_ok = win.runs[-1][2]
    once = len(win.runs)
    on_ok({'failed_items': [['disable', 'com.g.one']]})
    assert st.items() == [('disable', 'com.g.one')]
    assert tab.lbl_stage.text() == 'Sahne: 1 işlem'
    assert len(win.runs) == once + 1

    # Taninmayan sonuc bicimleri sahneyi bozmaz
    for bozuk in ('x', {'a': 1}, [['disable']], [['disable', 5]]):
        on_ok({'failed_items': bozuk})
        assert st.items() == [('disable', 'com.g.one')]
    on_ok('bozuk')
    assert st.items() == [('disable', 'com.g.one')]

    # Bozuk liste ogesi (len patlarsa) yine sahneyi korur
    class _TuhafList(list):
        def __len__(self):
            raise ValueError('bozuk')

    on_ok({'failed_items': [_TuhafList()]})
    assert st.items() == [('disable', 'com.g.one')]

    # Bos basarisiz listesi tum sahneyi supurur
    on_ok({'failed_items': []})
    assert st.items() == []

    # Bayat baglamda sahne degismez
    st.add('disable', 'com.g.two')
    core.target = 'tv-9'
    on_ok({'failed_items': []})
    assert st.items() == [('disable', 'com.g.two')]
    core.target = 'tv-1'

    # Kabul edildikten sonra baglam degisirse isci kurulmaz
    _SahneDiyalogu.degistirici = lambda: setattr(core, 'target', 'tv-9')
    sayi = len(isciler)
    tab._stage_show()
    _SahneDiyalogu.degistirici = None
    assert len(isciler) == sayi
    assert kutular[-1][:2] == ('uyari', 'Sahne')
    core.target = 'tv-1'
    tab._invalidate_presence_scan()


def test_hazir_profiller(debloat, monkeypatch):
    tab, core, win = debloat
    kutular = _kutular(monkeypatch)
    monkeypatch.setattr(deb_mod, 'PROFILES', {
        'hizli': {'label': 'Hızlı Temizlik', 'method': 'disable'}})
    monkeypatch.setattr(deb_mod, 'profile_summary',
                        lambda key: 'Ozet: ' + key)
    monkeypatch.setattr(
        deb_mod, 'validate_profile',
        lambda key: (['com.g.one', 'com.g.two'], ['com.x.red']))

    # Bilinmeyen profil
    tab._apply_profile('yok')
    assert kutular[-1] == ('uyari', 'Hazır profil', 'Profil bulunamadı.')

    # Baglanti yok
    core.connected = False
    tab._apply_profile('hizli')
    assert kutular[-1] == ('uyari', 'Hazır profil', 'Önce bir cihaza bağlanın.')
    core.connected = True

    # Tarama surerken
    tab._presence_scanning = True
    tab._apply_profile('hizli')
    assert kutular[-1][0] == 'info'
    assert kutular[-1][1] == 'Hazır profil'
    assert 'sürüyor' in kutular[-1][2]
    tab._presence_scanning = False

    # Envanter guncel degil: tarama baslatilir + bilgilendirme
    once = len(win.runs)
    tab._apply_profile('hizli')
    assert len(win.runs) == once + 1
    assert kutular[-1][0] == 'info'
    assert 'Tarama başlatıldı' in kutular[-1][2]
    tab._invalidate_presence_scan()

    # Guncel envanter ama uygulanabilir paket yok
    tab._presence_known = True
    tab._presence_target = 'tv-1'
    tab._present = set()
    tab._apply_profile('hizli')
    assert kutular[-1][0] == 'info'
    assert kutular[-1][2].startswith('Uygulanacak: 0 paket')
    assert 'cihazda yok: 2' in kutular[-1][2]
    assert 'Reddedilen: 1' in kutular[-1][2]
    assert 'Ozet: hizli' in kutular[-1][2]

    # Diyalog reddi: isci kurulmaz, ozetler diyaloga gider
    monkeypatch.setattr(stage_dialog_mod, 'StageDialog', _SahneDiyalogu)
    _SahneDiyalogu.karar = 0
    _SahneDiyalogu.degistirici = None
    _SahneDiyalogu.kayitlar = []
    isciler = []

    def stage_iscisi(*a, **k):
        w = _SahteIsci(*a, **k)
        isciler.append(w)
        return w

    monkeypatch.setattr(workers_mod, 'StageWorker', stage_iscisi)
    tab._present = {'com.g.one', 'com.g.two'}
    core.config.protected = {'com.g.two'}
    tab._apply_profile('hizli')
    assert isciler == []
    dlg = _SahneDiyalogu.kayitlar[-1]
    assert dlg.args[2] is core.config.friendly_name
    assert dlg.kwargs['description'] == 'Ozet: hizli'
    assert dlg.kwargs['summary'].startswith('Uygulanacak: 1 paket')
    assert 'koruma listesinde: 1' in dlg.kwargs['summary']

    # Kabul: isci kosar, sonuc kutusu ve yeniden tarama
    _SahneDiyalogu.karar = 1
    monkeypatch.setattr(workers_mod, 'format_action_result',
                        lambda res, name=None: 'SONUC')
    tab._apply_profile('hizli')
    w = isciler[-1]
    assert w.args == (core._engine, 'tv-1', [('disable', 'com.g.one')],
                      core.config.protected)
    assert w.kwargs == {'user_id': 0}
    w.finished_ok.emit({'ok': 1})
    assert kutular[-1][0] == 'info'
    assert kutular[-1][1] == 'Hazır profil sonucu'
    assert kutular[-1][2].startswith('Uygulandı: 1 · Atlandı: 1')
    assert 'SONUC' in kutular[-1][2]

    on_ok = win.runs[-1][2]
    once = len(win.runs)
    on_ok({'ok': 1})
    assert len(win.runs) == once + 1
    tab._invalidate_presence_scan()

    # Bayat baglamda sonuc kutusu cikmaz
    sayi = len(kutular)
    core.target = 'tv-9'
    w.finished_ok.emit({'ok': 1})
    assert len(kutular) == sayi
    core.target = 'tv-1'

    # Kabul sonrasi baglam degisirse isci kurulmaz
    _SahneDiyalogu.degistirici = lambda: setattr(core, 'target', 'tv-9')
    sayi = len(isciler)
    tab._apply_profile('hizli')
    _SahneDiyalogu.degistirici = None
    assert len(isciler) == sayi
    assert kutular[-1][:2] == ('uyari', 'Hazır profil')
    core.target = 'tv-1'


def test_kullanici_secimi(debloat, monkeypatch):
    tab, core, win = debloat
    _kutular(monkeypatch)

    # Negatif indeks yok sayilir
    tab._user_changed(-1)
    assert win.logs == []

    # Ayni kullanici: kalici degilse erken cikis
    tab._user_changed(0)
    assert win.logs == []

    # Kayit basarisiz: WARN + INFO gunlugu ve tarama
    def kaydetme():
        core.config.save_calls += 1
        return False

    core.config.save = kaydetme
    once = len(win.runs)
    tab._activate_user_id(2)
    assert core.config.user_id == 2
    assert win.logs[-2] == (
        'Kullanıcı tercihi bu oturumda uygulandı ancak ayarlara kaydedilemedi.',
        'WARN')
    assert win.logs[-1] == ('İşlem kullanıcısı: user 2', 'INFO')
    assert tab._presence_target == 'tv-1'
    assert tab.lbl_summary.text() == 'user 2 için paket varlığı taranıyor...'
    assert len(win.runs) == once + 1
    tab._invalidate_presence_scan()

    # force ayni kullaniciyi yeniden uygular
    tab._activate_user_id(2, persist=False, force=True)
    assert win.logs[-1] == ('İşlem kullanıcısı: user 2', 'INFO')
    tab._invalidate_presence_scan()
    del core.config.save

    # Bagli degilken liste bekler
    core.connected = False
    tab._activate_user_id(0)
    assert tab._presence_target is None
    assert tab.lbl_summary.text() == (
        'Bağlı cihaz yok — bağlanınca cihaz uygulamaları listelenecek.')
    core.connected = True

    # sync: kayitli kimlik listede yoksa eklenir ve zorla taranir
    core.config.user_id = 5
    once = len(win.runs)
    tab.sync_user_id_from_config()
    assert tab.cmb_user.itemText(0) == (
        'Kullanıcı: 5 (kayıtlı; adını bulmak için tara)')
    assert tab.cmb_user.itemData(0) == 5
    assert tab.cmb_user.currentData() == 5
    assert core.config.user_id == 5
    assert len(win.runs) == once + 1
    tab._invalidate_presence_scan()

    # sync: mevcut kimlik indeksten secilir
    core.config.user_id = 0
    tab.sync_user_id_from_config()
    assert tab.cmb_user.currentData() == 0
    tab._invalidate_presence_scan()


def test_kullanici_tarama(debloat, monkeypatch):
    tab, core, win = debloat
    kutular = _kutular(monkeypatch)

    # Bagli degil
    core.connected = False
    tab._scan_users()
    assert kutular[-1] == (
        'info', 'Kullanıcılar',
        "Bağlı cihaz yok. Kullanıcıları listelemek için önce TV'ye bağlanın.")
    core.connected = True

    # Hedef yok
    core.target = None
    tab._scan_users()
    assert kutular[-1][0] == 'info'
    core.target = 'tv-1'

    # Basarili tarama: isci cihazi gezer ve listeyi doldurur
    core._engine.users = [
        {'id': 0, 'name': 'Owner', 'running': True},
        {'id': 10, 'name': 'Misafir', 'running': False},
    ]
    tab._scan_users()
    w = win.runs[-1][0]
    assert win.runs[-1][1] is None
    users = w.args[0]()
    assert users == core._engine.users
    assert ('connect', 'tv-1') in core._engine.calls
    assert ('list_users', 'tv-1') in core._engine.calls
    w.finished_ok.emit(users)
    assert tab.cmb_user.count() == 2
    assert tab.cmb_user.itemText(0) == 'Kullanıcı: Owner (0) [çalışıyor]'
    assert tab.cmb_user.itemText(1) == 'Kullanıcı: Misafir (10)'
    assert tab.cmb_user.currentData() == 0
    assert win.logs[-1] == ('2 kullanıcı bulundu.', 'INFO')
    assert tab._presence_scanning is True
    tab._invalidate_presence_scan()

    # do() baglam kontrolleri
    tab._scan_users()
    w = win.runs[-1][0]
    core.target = 'tv-9'
    with pytest.raises(CancelledError):
        w.args[0]()
    core.target = 'tv-1'
    core.config.user_id = 3
    with pytest.raises(CancelledError):
        w.args[0]()
    core.config.user_id = 0

    # current() ic bozulmasi taramayi iptal eder
    gercek_mcc = tab._mutation_context_current
    monkeypatch.setattr(
        tab, '_mutation_context_current',
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError('yok')))
    tab._scan_users()
    w = win.runs[-1][0]
    with pytest.raises(CancelledError):
        w.args[0]()
    monkeypatch.setattr(tab, '_mutation_context_current', gercek_mcc)

    # connect hedefi degistirirse ikinci kontrol iptal eder
    motor = core._engine
    motor.connect_hook = lambda: setattr(core, 'target', 'tv-9')
    tab._scan_users()
    w = win.runs[-1][0]
    with pytest.raises(CancelledError):
        w.args[0]()
    motor.connect_hook = None
    core.target = 'tv-1'

    # list_users hedefi degistirirse ucuncu kontrol iptal eder
    motor.list_users_hook = lambda: setattr(core, 'target', 'tv-9')
    tab._scan_users()
    w = win.runs[-1][0]
    with pytest.raises(CancelledError):
        w.args[0]()
    motor.list_users_hook = None
    core.target = 'tv-1'

    # Kimlik listede yoksa 0'a donulur ve kaydedilir
    once_save = core.config.save_calls
    core.config.user_id = 7
    tab._show_users(core._engine.users, 'tv-1', core._engine,
                    tab._presence_generation, 7)
    assert core.config.user_id == 0
    assert core.config.save_calls == once_save + 1
    assert tab.cmb_user.currentData() == 0
    tab._invalidate_presence_scan()

    # Bayat sonuclar yok sayilir
    sayi = tab.cmb_user.count()
    tab._show_users(core._engine.users, 'tv-9', core._engine,
                    tab._presence_generation, 0)
    tab._show_users(core._engine.users, 'tv-1', _Motor(),
                    tab._presence_generation, 0)
    core.connected = False
    tab._show_users(core._engine.users, 'tv-1', core._engine,
                    tab._presence_generation, 0)
    core.connected = True
    tab._show_users(core._engine.users, 'tv-1', core._engine,
                    tab._presence_generation + 1, 0)
    core.config.user_id = 9
    tab._show_users(core._engine.users, 'tv-1', core._engine,
                    tab._presence_generation, 0)
    core.config.user_id = 0
    assert tab.cmb_user.count() == sayi

    # Bagli degilken liste guncellenir ama tarama baslamaz
    core.connected = False
    once = len(win.runs)
    tab._show_users(core._engine.users, None, None, None, None)
    assert len(win.runs) == once
    assert tab.cmb_user.count() == 2
    core.connected = True


class _DosyaDiyalogu:
    cevap = ('', '')
    kayitlar = []

    @staticmethod
    def getSaveFileName(*a, **k):
        _DosyaDiyalogu.kayitlar.append(a)
        return _DosyaDiyalogu.cevap

    @staticmethod
    def getOpenFileName(*a, **k):
        _DosyaDiyalogu.kayitlar.append(a)
        return _DosyaDiyalogu.cevap


def test_secim_aktarimi(debloat, monkeypatch, tmp_path):
    tab, _core, _win = debloat
    kutular = _kutular(monkeypatch)
    _DosyaDiyalogu.kayitlar = []
    _DosyaDiyalogu.cevap = ('', '')
    monkeypatch.setattr(deb_mod, 'QFileDialog', _DosyaDiyalogu)

    # Secim yok
    tab._export_selection()
    assert kutular[-1] == ('info', 'Seçim', 'Önce paket seçin.')

    tab._present = {'com.g.one', 'com.g.two'}
    tab._presence_known = True
    tab._reload()
    tab._toggle_all(True)

    # Iptal: kutu cikmaz
    sayi = len(kutular)
    tab._export_selection()
    assert _DosyaDiyalogu.kayitlar[-1][1] == 'Seçimi Dışa Aktar'
    assert len(kutular) == sayi

    # Basarili disa aktarim
    hedef = tmp_path / 'secim.txt'
    _DosyaDiyalogu.cevap = (str(hedef), 'Metin (*.txt)')
    tab._export_selection()
    assert hedef.read_text(encoding='utf-8') == 'com.g.one\ncom.g.two\n'
    assert kutular[-1][0] == 'info'
    assert kutular[-1][1] == 'Tamam'
    assert '2 paket aktarıldı (UAD uyumlu):' in kutular[-1][2]

    # Yazilamayan yol
    _DosyaDiyalogu.cevap = (str(tmp_path / 'yok' / 'x.txt'), 'Metin (*.txt)')
    tab._export_selection()
    assert kutular[-1] == ('kritik', 'Hata', kutular[-1][2])

    # Ice aktarim: yorum satiri atlanir, isaretleme + eksik listesi
    kaynak = tmp_path / 'ice.txt'
    kaynak.write_text('# yorum\ncom.g.one\ncom.g.yok\n', encoding='utf-8')
    _DosyaDiyalogu.cevap = (str(kaynak), 'Metin (*.txt)')
    tab._toggle_all(False)
    tab._import_selection()
    satir = _satir_bul(tab, 'com.g.one')
    assert tab.grid.item(satir, COL_CHECK).checkState() == Qt.Checked
    assert kutular[-1][1] == 'İçe Aktar'
    assert '1 paket işaretlendi.' in kutular[-1][2]
    assert 'Tabloda yok (1): com.g.yok' in kutular[-1][2]

    # Okunamayan dosya
    _DosyaDiyalogu.cevap = (str(tmp_path / 'yok.txt'), 'Metin (*.txt)')
    sayi = len(kutular)
    tab._import_selection()
    assert len(kutular) == sayi + 1
    assert kutular[-1][0] == 'kritik'

    # Iptal: hicbir sey olmaz
    _DosyaDiyalogu.cevap = ('', '')
    sayi = len(kutular)
    tab._import_selection()
    assert len(kutular) == sayi


def test_csv_aktarimi(debloat, monkeypatch, tmp_path):
    tab, _core, _win = debloat
    kutular = _kutular(monkeypatch)
    _DosyaDiyalogu.kayitlar = []
    _DosyaDiyalogu.cevap = ('', '')
    monkeypatch.setattr(deb_mod, 'QFileDialog', _DosyaDiyalogu)

    tab._present = {'com.g.one'}
    tab._presence_known = True
    tab._reload()

    # Iptal
    sayi = len(kutular)
    tab._export_csv()
    assert _DosyaDiyalogu.kayitlar[-1][1] == 'CSV Kaydet'
    assert len(kutular) == sayi

    # Aktarim: basliklar ve satirlar
    hedef = tmp_path / 'debloat.csv'
    _DosyaDiyalogu.cevap = (str(hedef), 'CSV (*.csv)')
    tab._export_csv()
    satirlar = hedef.read_text(encoding='utf-8-sig').splitlines()
    assert satirlar[0] == 'Ad,Paket,Açıklama,Cihazda'
    assert satirlar[1] == 'Bir,com.g.one,Birinci paket,Evet'
    assert kutular[-1] == ('info', 'Tamam', 'Aktarıldı:\n' + str(hedef))

    # Yazilamayan yol
    _DosyaDiyalogu.cevap = (str(tmp_path / 'yok' / 'x.csv'), 'CSV (*.csv)')
    tab._export_csv()
    assert kutular[-1][0] == 'kritik'


def test_favoriler(debloat, monkeypatch):
    tab, core, _win = debloat
    kutular = _kutular(monkeypatch)
    diyaloglar = []
    cevaplar = []

    def metin_al(*a, **k):
        diyaloglar.append(a)
        return cevaplar.pop(0)

    monkeypatch.setattr(QInputDialog, 'getText', metin_al)

    # Ilk diyalog iptal
    cevaplar[:] = [('', False)]
    tab._add_favorite_dialog()
    assert len(diyaloglar) == 1

    # Bos paket adi
    cevaplar[:] = [('   ', True)]
    sayi = len(diyaloglar)
    tab._add_favorite_dialog()
    assert len(diyaloglar) == sayi + 1
    assert cevaplar == []

    # Ikinci diyalog iptal
    cevaplar[:] = [('com.yeni', True), ('Ad', False)]
    tab._add_favorite_dialog()
    assert len(diyaloglar) == sayi + 3

    # Basarili ekleme: dost ad yoksa paket adi kullanilir, reload cagrilir
    kayit = []
    monkeypatch.setattr(
        deb_mod, 'add_user_entry',
        lambda pkg, name, desc: kayit.append((pkg, name, desc)) or True)
    monkeypatch.setattr(tab, 'reload', lambda: kayit.append('reload'))
    cevaplar[:] = [('  com.yeni  ', True), ('', True)]
    tab._add_favorite_dialog()
    assert kayit == [('com.yeni', 'com.yeni', 'Kullanıcı favorisi'), 'reload']

    # Zaten listede
    monkeypatch.setattr(deb_mod, 'add_user_entry', lambda *a: False)
    cevaplar[:] = [('com.var', True), ('X', True)]
    tab._add_favorite_dialog()
    assert kutular[-1] == ('info', 'Favori', 'Bu paket zaten listede.')

    # Kayit hatasi
    def patlak(*a):
        raise ValueError('gecersiz')

    monkeypatch.setattr(deb_mod, 'add_user_entry', patlak)
    cevaplar[:] = [('com.var', True), ('X', True)]
    tab._add_favorite_dialog()
    assert kutular[-1] == ('kritik', 'Favori kaydedilemedi', 'gecersiz')

    # Favori silme: yanlis kategori
    tab.cmb_cat.setCurrentIndex(0)
    tab._remove_favorite_selected()
    assert kutular[-1] == ('info', 'Favori',
                           'Önce "Favoriler" kategorisini seçin.')

    # Secim yok
    tab.cmb_cat.setCurrentIndex(tab.cmb_cat.findData('favoriler'))
    tab._remove_favorite_selected()
    assert kutular[-1] == ('info', 'Seçim', 'Önce paket seçin.')

    # Basarili silme: kayit + reload
    tab._present = {'com.f.one'}
    tab._presence_known = True
    core.config.protected = set()
    tab._reload()
    tab._toggle_all(True)
    silinen = []
    reload_sayisi = []
    monkeypatch.setattr(deb_mod, 'remove_user_entries',
                        lambda pkgs: silinen.append(list(pkgs)))
    monkeypatch.setattr(tab, 'reload', lambda: reload_sayisi.append(True))
    tab._remove_favorite_selected()
    assert silinen == [['com.f.one']]
    assert reload_sayisi == [True]

    # Silme hatasi
    def patlak2(pkgs):
        raise OSError('kilitli')

    monkeypatch.setattr(deb_mod, 'remove_user_entries', patlak2)
    tab._remove_favorite_selected()
    assert kutular[-1] == ('kritik', 'Favoriler kaydedilemedi', 'kilitli')


def test_reload_metodu(debloat, monkeypatch):
    tab, _core, _win = debloat
    kayit = []
    monkeypatch.setattr(tab, '_fill_categories',
                        lambda: kayit.append('kategoriler'))
    monkeypatch.setattr(tab, '_reload', lambda: kayit.append('liste'))
    tab.reload()
    assert kayit == ['kategoriler', 'liste']


def test_savunma_yollari(debloat):
    tab, core, _win = debloat

    # Iptal cagrisi patlarsa yutulur
    class _IptalPatlak:
        def cancel(self):
            raise RuntimeError('yok')

    tab._presence_worker = _IptalPatlak()
    tab._presence_scanning = True
    tab._invalidate_presence_scan()
    assert tab._presence_worker is None
    assert tab._presence_scanning is False

    # Baglam sorgulari motor erisimiyle patlarsa False doner
    w = _SahteIsci()
    w._presence_user_id = 0
    tab._presence_worker = w
    tab._presence_target = 'tv-1'
    core.engine_patlak = True
    assert tab._presence_context_current(
        w, core._engine, 'tv-1', tab._presence_generation) is False
    assert tab._mutation_context_current(
        (core._engine, 'tv-1', tab._presence_generation)) is False
    core.engine_patlak = False

    # Bayat isci kaydi yeni kaydi temizlemez
    yeni = _SahteIsci()
    tab._presence_worker = yeni
    tab._presence_scanning = True
    tab._finish_presence_worker(w)
    assert tab._presence_worker is yeni
    assert tab._presence_scanning is True


def test_reload_yok_durumu(debloat):
    tab, _core, _win = debloat

    class _Ikircikli(set):
        def __init__(self, *a):
            super().__init__(*a)
            self.sayac = 0

        def __contains__(self, item):
            self.sayac += 1
            return self.sayac % 2 == 1

    # Varlik filtresi gecirir ama satir icinde 'yok' gorunur (savunma dali).
    tab._present = _Ikircikli()
    tab._presence_known = True
    tab._presence_target = 'tv-1'
    tab._reload()
    assert tab.grid.rowCount() == 3
    for row in range(3):
        assert tab.grid.item(row, COL_STATE).text() == 'Yok'
        assert tab.grid.item(row, COL_PRESENT).text() == 'Hayir'


def test_bulk_onay_ve_yeniden_dogrulama(debloat, monkeypatch):
    tab, core, _win = debloat
    kutular = _kutular(monkeypatch)
    onaylar = []
    durum = {'mod': 'onay'}

    def onayla(a_self, action, pkgs, name_of, extra=None):
        onaylar.append((action, list(pkgs), extra))
        if durum['mod'] == 'red':
            return False
        if durum['mod'] == 'degistir':
            core.target = 'tv-9'
        return True

    monkeypatch.setattr(dialogs_mod, 'confirm_action', onayla)
    isciler = []
    akilli = []

    def paket_iscisi(*a, **k):
        w = _SahteIsci(*a, **k)
        isciler.append(w)
        return w

    def akilli_iscisi(*a, **k):
        w = _SahteIsci(*a, **k)
        akilli.append(w)
        return w

    monkeypatch.setattr(deb_mod, 'PackageActionWorker', paket_iscisi)
    monkeypatch.setattr(workers_mod, 'SmartRemoveWorker', akilli_iscisi)
    monkeypatch.setattr(workers_mod, 'format_action_result',
                        lambda res, name=None: 'RAPOR')

    tab._present = {'com.g.one', 'com.r.one'}
    tab._presence_known = True
    tab._reload()
    secim = {'pkgs': ['com.g.one', 'com.r.one']}
    monkeypatch.setattr(tab, '_selected_packages',
                        lambda: list(secim['pkgs']))
    uyari = ('uyari', 'Paket işlemi',
             'Bağlantı, hedef veya cihaz paket bilgisi değişti. '
             'İşlem başlatılmadı; yeniden deneyin.')

    def temizle():
        core.target = 'tv-1'

    # Normal onay reddi: hicbir isci kurulmaz
    durum['mod'] = 'red'
    sayi = len(isciler) + len(akilli)
    tab._bulk('uninstall')
    assert onaylar[-1][0] == 'uninstall'
    assert len(isciler) + len(akilli) == sayi

    # Normal onaydan sonra baglam degisirse islem baslamaz
    durum['mod'] = 'degistir'
    tab._bulk('uninstall')
    assert kutular[-1] == uyari
    temizle()
    assert len(isciler) + len(akilli) == sayi

    # Smart onayindan sonra baglam degisirse islem baslamaz
    def degistirici_smart(a_self, action, pkgs, name_of, extra=None):
        onaylar.append((action, list(pkgs), extra))
        if action == 'smart':
            core.target = 'tv-9'
        return True

    durum['mod'] = 'onay'
    monkeypatch.setattr(dialogs_mod, 'confirm_action', degistirici_smart)
    tab._bulk('uninstall')
    assert onaylar[-1][0] == 'smart'
    assert kutular[-1] == uyari
    temizle()
    assert len(isciler) + len(akilli) == sayi

    # 'all' + riskli disable: ek onay reddi ve baglam degisimi
    monkeypatch.setattr(dialogs_mod, 'confirm_action', onayla)
    secim['pkgs'] = ['com.r.one']
    durum['mod'] = 'red'
    sayi = len(isciler)
    tab._bulk('disable')
    assert onaylar[-1][2] == 'RISKL kategori — sistem bozulabilir!'
    assert len(isciler) == sayi

    durum['mod'] = 'degistir'
    tab._bulk('disable')
    assert kutular[-1] == uyari
    temizle()
    assert len(isciler) == sayi

    # 'all' duz onay (restore) sonrasi baglam degisimi
    secim['pkgs'] = ['com.g.one']
    durum['mod'] = 'degistir'
    tab._bulk('restore')
    assert kutular[-1] == uyari
    temizle()
    assert len(isciler) == sayi

    # Riskli kategori + uninstall: smart onay dallari
    tab.cmb_cat.setCurrentIndex(tab.cmb_cat.findData('riskli'))
    secim['pkgs'] = ['com.r.one']
    durum['mod'] = 'red'
    sayi = len(akilli)
    tab._bulk('uninstall')
    assert len(akilli) == sayi

    durum['mod'] = 'degistir'
    tab._bulk('uninstall')
    assert kutular[-1] == uyari
    temizle()
    assert len(akilli) == sayi

    # Riskli kategori + disable: ek onay dallari
    durum['mod'] = 'red'
    sayi = len(isciler)
    tab._bulk('disable')
    assert len(isciler) == sayi

    durum['mod'] = 'degistir'
    tab._bulk('disable')
    assert kutular[-1] == uyari
    temizle()
    assert len(isciler) == sayi

    # Baska kategori + disable: duz onay dallari
    tab.cmb_cat.setCurrentIndex(tab.cmb_cat.findData('guvenli'))
    durum['mod'] = 'red'
    sayi = len(isciler)
    tab._bulk('disable')
    assert len(isciler) == sayi

    durum['mod'] = 'degistir'
    tab._bulk('disable')
    assert kutular[-1] == uyari
    temizle()
    assert len(isciler) == sayi

    # Son yeniden dogrulama hatasi isci kurmayi engeller
    durum['mod'] = 'onay'
    gercek = deb_mod.DebloatTab._revalidate_mutation_context
    sayac = {'n': 0}

    def sayacli(self, context, title):
        sayac['n'] += 1
        if sayac['n'] == 2:
            return False
        return gercek(self, context, title)

    monkeypatch.setattr(deb_mod.DebloatTab,
                        '_revalidate_mutation_context', sayacli)
    sayi = len(isciler)
    tab._bulk('disable')
    assert sayac['n'] >= 2
    assert len(isciler) == sayi

    # Bagimlilik sorusundan sonra baglam degisirse islem baslamaz
    monkeypatch.setattr(deb_mod.DebloatTab,
                        '_revalidate_mutation_context', gercek)
    monkeypatch.setattr(
        deb_mod, 'needed_by',
        lambda pkg: ['Bagimli'] if pkg == 'com.g.one' else [])

    def sor_degistir(*a, **k):
        core.target = 'tv-9'
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, 'question', sor_degistir)
    secim['pkgs'] = ['com.g.one']
    sayi = len(isciler)
    tab._bulk('disable')
    assert kutular[-1] == uyari
    temizle()
    assert len(isciler) == sayi
