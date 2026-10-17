# -*- coding: utf-8 -*-
"""apps_tab: uygulama listesi, filtreler, paket islemleri ve disa aktarim."""
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QMenu,
    QMessageBox,
    QTextEdit,
)

import mibox_app.ui.apps_tab as app_mod
import mibox_app.ui.dialogs as dialogs_mod
import mibox_app.workers as workers_mod
from mibox_app.ui.apps_tab import (
    COL_CHECK,
    COL_NAME,
    COL_PKG,
    COL_STATE,
    STATUS_ACTIVE,
    STATUS_ALL,
    STATUS_DISABLED,
    STATUS_REMOVED,
    STATUS_RUNNING,
    AppsTab,
)
from mibox_app.workers import CancelledError


class _Motor:
    def __init__(self):
        self.calls = []
        self.detail = {
            'package': 'com.a.one', 'versionName': '1.2', 'versionCode': '3',
            'installer': 'adb', 'firstInstall': '2024-01-01',
            'lastUpdate': '2024-02-02', 'enabled': True,
            'codePath': '/data/app/x.apk', 'dataDir': '/data/data/com.a.one'}
        self.size = 2048
        self.size_patlak = False
        self.detail_patlak = False

    def connect(self, target, cancel_check=None):
        self.calls.append(('connect', target))

    def app_detail(self, target, pkg):
        self.calls.append(('app_detail', target, pkg))
        if self.detail_patlak:
            raise RuntimeError('detay yok')
        return dict(self.detail)

    def app_size(self, target, pkg):
        self.calls.append(('app_size', target, pkg))
        if self.size_patlak:
            raise RuntimeError('boyut yok')
        return self.size


class _Yapilandirma:
    def __init__(self):
        self.show_removed = False
        self.save_sayaci = 0
        self.protected = set()
        self.friendly = {}

    def save(self):
        self.save_sayaci += 1

    def friendly_name(self, package):
        return self.friendly.get(package, package)

    def is_protected(self, package):
        return package in self.protected


class _KaydetPatlak(_Yapilandirma):
    def save(self):
        raise RuntimeError('kaydedilemedi')


class _Debloat:
    def __init__(self):
        self.received = []

    def set_present(self, info):
        self.received.append(info)


class _DebloatPatlak(_Debloat):
    def set_present(self, info):
        raise RuntimeError('debloat yok')


class _Remote:
    def __init__(self):
        self.paketler = []

    def populate_apps(self, apps):
        self.paketler.append(apps)


class _RemotePatlak(_Remote):
    def populate_apps(self, apps):
        raise RuntimeError('remote yok')


class _Pencere:
    def __init__(self):
        self.runs = []
        self._workers = ()
        self._connection_busy = False
        self._closing = False
        self._close_pending = False
        self.run_patlak = False
        self.son_islem = None
        self.tab_debloat = _Debloat()
        self.tab_remote = _Remote()

    def _run(self, worker, desc=None):
        if self.run_patlak:
            raise RuntimeError('calistirilamadi')
        self.runs.append((worker, desc))

    def set_last_action(self, text):
        self.son_islem = text


class _Cekirdek(QObject):
    connection_changed = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.connected = True
        self.target = 'tv-1'
        self._engine = _Motor()
        self.engine_patlak = False
        self.config = _Yapilandirma()

    @property
    def engine(self):
        if self.engine_patlak:
            raise RuntimeError('motor yok')
        return self._engine


class _SahteIsci(QObject):
    finished_ok = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)
    finished = Signal()
    presence = Signal(object)

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.args = args
        self.kwargs = kwargs
        self.job_name = ''
        self.tamamlandi = False
        self.cancel_calls = 0

    def cancel(self):
        self.cancel_calls += 1

    def isFinished(self):
        return self.tamamlandi


def _olaylar():
    QApplication.processEvents()


def _app(pkg, ad='', **extra):
    a = {'package': pkg, 'status': '', 'running': 'Hayir', 'enabled': True,
         'installed_user0': True, 'system': False, 'label': ad,
         'name': ad or pkg}
    a.update(extra)
    return a


@pytest.fixture
def uygulamalar(qtbot):
    core = _Cekirdek()
    win = _Pencere()
    tab = AppsTab(core, win)
    qtbot.addWidget(tab)
    return tab, core, win


def test_kurulum(uygulamalar):
    tab, _core, win = uygulamalar
    assert tab.grid.columnCount() == 4
    assert [tab.grid.horizontalHeaderItem(c).text()
            for c in range(4)] == ['Seç', 'Uygulama', 'Paket', 'Durum']
    assert tab.grid.isSortingEnabled() is False
    assert tab.cmb_status.count() == 5
    veriler = [tab.cmb_status.itemData(i) for i in range(5)]
    assert veriler == [STATUS_ALL, STATUS_ACTIVE, STATUS_DISABLED,
                       STATUS_REMOVED, STATUS_RUNNING]
    assert tab.btn_system.isChecked() is True
    assert tab.btn_system.text() == '✓ Sistem (0)'
    assert tab.lbl_summary.text() == 'Liste boş. "Yenile" ile başlayın.'
    assert tab.lbl_sel.text() == 'Seçili: 0/0'
    assert tab.grid.empty_title == 'TV bağlantısı bekleniyor'
    assert tab.grid.empty_description == (
        'Üstteki bağlantı alanından TV’ye bağlanın, ardından Yenile’yi seçin.')
    assert len(tab._more_actions) == 5
    for action, button in tab._more_actions:
        assert button.isHidden() is True
        assert action.isEnabled() is False
    assert tab.btn_select_all.isEnabled() is False
    assert tab.chk_inv.isEnabled() is False
    assert tab._filter_timer.isSingleShot() is True
    assert tab._filter_timer.interval() == 250
    assert tab._scanned_with_system is False
    assert tab.txt_search.placeholderText() == 'Ara: ad veya paket...'
    assert tab.btn_export.text() == 'CSV'
    assert tab.btn_reset_filters.text() == 'Filtreleri sıfırla'
    assert tab.btn_clear.toolTip() == 'Uygulama verilerini kalıcı olarak siler'

    # Ic uzak sekme: tab_remote_inner varsa o kullanilir
    win.tab_remote_inner = win.tab_remote
    assert tab._remote_tab() is win.tab_remote
    win.tab_remote_inner = None
    assert tab._remote_tab() is win.tab_remote


def test_kurulum_kaldirilmis_gorunumu(qtbot):
    core = _Cekirdek()
    core.config = SimpleNamespace(show_removed=True)
    tab = AppsTab(core, _Pencere())
    qtbot.addWidget(tab)
    assert tab.cmb_status.currentData() == STATUS_REMOVED

    # show_removed okunamazsa varsayilan filtre korunur
    core2 = _Cekirdek()
    core2.config = SimpleNamespace()
    tab2 = AppsTab(core2, _Pencere())
    qtbot.addWidget(tab2)
    assert tab2.cmb_status.currentData() == STATUS_ALL


def test_filtre_listesi(uygulamalar):
    tab, core, _win = uygulamalar
    tab._apps = [
        _app('com.a.one', 'Bir Uygulama'),
        _app('com.b.two', 'İki Uygulama', enabled=False),
        _app('com.sys.rom', 'Sistem Aracı', system=True),
        _app('com.gone.old', 'Eski', installed_user0=False),
        _app('com.run.app', 'Çalışan', running='Evet'),
    ]
    tab._apply_filter_now()
    assert tab.grid.rowCount() == 4
    assert tab.lbl_summary.text() == (
        'Gösterilen: 4  |  Kullanıcı: 3  |  Sistem: 1  |  '
        '(1 kaldırılmış gizli — "Kaldırılmış" seçeneğiyle göster)')

    paketler = [tab.grid.item(r, COL_PKG).text() for r in range(4)]
    assert paketler == ['com.a.one', 'com.b.two', 'com.sys.rom', 'com.run.app']
    ad = tab.grid.item(1, COL_NAME)
    assert ad.font().strikeOut() is True
    assert ad.toolTip() == 'Devre dışı: com.b.two'
    assert tab.grid.item(1, COL_STATE).text() == 'Devre dışı'
    assert tab.grid.item(0, COL_STATE).text() == 'Etkin'
    assert tab.grid.item(0, COL_CHECK).flags() & Qt.ItemIsUserCheckable
    assert tab.grid.item(0, COL_NAME).data(Qt.UserRole) == 'com.a.one'

    # Arama: Turkce harfler katlanir, ad ve paket birlikte aranir
    tab.txt_search.setText('İKİ')
    tab._apply_filter_now()
    assert tab.grid.rowCount() == 1
    assert tab.grid.item(0, COL_PKG).text() == 'com.b.two'

    tab.txt_search.setText('gone.old')
    tab.cmb_status.setCurrentIndex(tab.cmb_status.findData(STATUS_REMOVED))
    assert tab.grid.rowCount() == 1
    assert tab.grid.item(0, COL_STATE).text() == 'Kaldırılmış'
    assert tab.grid.item(0, COL_STATE).toolTip().startswith(
        'Ana Android kullanıcısı için kaldırılmış')
    tab.txt_search.clear()
    tab.cmb_status.setCurrentIndex(tab.cmb_status.findData(STATUS_ALL))

    # Isaret yeniden uygulamada korunur; preserve_checks=False temizler
    tab._apply_filter_now()
    tab.grid.item(0, COL_CHECK).setCheckState(Qt.Checked)
    tab._apply_filter_now()
    assert tab.grid.item(0, COL_CHECK).checkState() == Qt.Checked
    tab._apply_filter_now(preserve_checks=False)
    assert tab.grid.item(0, COL_CHECK).checkState() == Qt.Unchecked

    # Son tarama bilgisi ozete eklenir
    tab._apps = [_app('com.a.one', 'Bir Uygulama')]
    tab._last_scan_at = '2024-05-01 10:00:00 +0300'
    tab._apply_filter_now()
    assert tab.lbl_summary.text() == (
        'Gösterilen: 1  |  Kullanıcı: 1  |  Sistem: 0  |  '
        'Son tarama: 2024-05-01 10:00:00 +0300')

    # Eslesmeyen arama
    tab.txt_search.setText('zzz')
    tab._apply_filter_now()
    assert tab.grid.empty_title == 'Eşleşen uygulama yok'
    assert tab.grid.empty_description == (
        'Arama metnini veya durum filtresini değiştirin.')
    tab.txt_search.clear()

    # Bos liste: bagliyken beklenti, kopukken uyari
    tab._apps = []
    tab._apply_filter_now()
    assert tab.grid.empty_title == 'Henüz uygulama listesi yok'
    assert tab.grid.empty_description == (
        'Cihazdaki uygulamaları görmek için Yenile’yi seçin.')
    core.connected = False
    tab._apply_filter_now()
    assert tab.grid.empty_title == 'TV bağlantısı bekleniyor'


def test_durum_filtresi(uygulamalar):
    tab, core, _win = uygulamalar
    tab._apps = [
        _app('com.a.one', 'Bir'),
        _app('com.b.two', 'İki', enabled=False),
        _app('com.gone.old', 'Eski', installed_user0=False),
        _app('com.run.app', 'Çalışan', running='Evet'),
    ]
    tab._apply_filter_now()
    assert tab.grid.rowCount() == 3

    # Devre disi
    tab.cmb_status.setCurrentIndex(tab.cmb_status.findData(STATUS_DISABLED))
    assert [tab.grid.item(r, COL_PKG).text()
            for r in range(tab.grid.rowCount())] == ['com.b.two']

    # Etkin: yalnizca etkin ve kurulu paketler
    tab.cmb_status.setCurrentIndex(tab.cmb_status.findData(STATUS_ACTIVE))
    assert [tab.grid.item(r, COL_PKG).text()
            for r in range(tab.grid.rowCount())] == ['com.a.one', 'com.run.app']

    # Kaldirilmis: ayar kalici hale gelir
    tab.cmb_status.setCurrentIndex(tab.cmb_status.findData(STATUS_REMOVED))
    assert core.config.show_removed is True
    assert core.config.save_sayaci == 1
    assert tab.grid.rowCount() == 1
    assert tab.grid.item(0, COL_PKG).text() == 'com.gone.old'
    assert tab.lbl_summary.text() == 'Gösterilen: 1  |  Kullanıcı: 1  |  Sistem: 0'

    tab.cmb_status.setCurrentIndex(tab.cmb_status.findData(STATUS_ALL))
    assert core.config.show_removed is False
    assert core.config.save_sayaci == 2
    assert tab.grid.rowCount() == 3

    # Ayar kaydedilemese bile filtre uygulanir
    core.config = _KaydetPatlak()
    tab.cmb_status.setCurrentIndex(tab.cmb_status.findData(STATUS_REMOVED))
    assert tab.grid.rowCount() == 1
    tab.cmb_status.setCurrentIndex(tab.cmb_status.findData(STATUS_ALL))
    assert tab.grid.rowCount() == 3

    # Calisan surec filtresi
    tab.cmb_status.setCurrentIndex(tab.cmb_status.findData(STATUS_RUNNING))
    assert [tab.grid.item(r, COL_PKG).text()
            for r in range(tab.grid.rowCount())] == ['com.run.app']

    # Surec bilgisi alinamadiysa bos durum aciklamasi degisir
    tab._apps[3]['running'] = 'Bilinmiyor'
    tab._apply_filter_now()
    assert tab.grid.rowCount() == 0
    assert tab.grid.empty_title == 'Çalışma durumu bilinmiyor'
    assert tab.grid.empty_description.startswith('ADB süreç bilgisi alınamadı.')

    # Hicbir surec calismiyorsa ayri metin
    tab._apps[3]['running'] = 'Hayir'
    tab._apply_filter_now()
    assert tab.grid.empty_title == 'Çalışan süreç yok'

    # Filtreyle eslesen uygun aday yok
    tab.txt_search.setText('zzz')
    tab._apply_filter_now()
    assert tab.grid.empty_title == 'Eşleşen uygulama yok'
    assert tab.grid.empty_description == (
        'Bu arama ve süreç filtresiyle eşleşen etkin, kurulu uygulama yok.')
    tab.txt_search.clear()
    tab.cmb_status.setCurrentIndex(tab.cmb_status.findData(STATUS_ALL))


def test_sistem_dugmesi(uygulamalar, monkeypatch):
    tab, _core, _win = uygulamalar
    tab._apps = [
        _app('com.a.one', 'Bir'),
        _app('com.sys.rom', 'Sistem', system=True),
    ]
    tab._apply_filter_now()
    assert tab.btn_system.text() == '✓ Sistem (1)'
    assert tab.btn_system.toolTip() == (
        'Sistem uygulamaları dahil (gösteriliyor — 1 paket).\n'
        'Yalnızca kullanıcı uygulamalarını görmek için tıklayın.')

    tab.btn_system.setChecked(False)
    assert tab.btn_system.text() == '○ Sistem: Gizli (1)'
    assert tab.btn_system.toolTip() == (
        'Sistem uygulamaları gizlendi (1 paket gizli).\n'
        'Sistem uygulamalarını listeye dahil etmek için tıklayın.')
    assert tab.grid.rowCount() == 1
    assert tab.grid.item(0, COL_PKG).text() == 'com.a.one'

    tab.btn_system.setChecked(True)
    assert tab.grid.rowCount() == 2

    # Koyu/acik palet stilleri ayri dallardir
    monkeypatch.setattr(app_mod.kit, 'dark_from', lambda *a, **k: True)
    tab._update_system_btn()
    assert '#38457c' in tab.btn_system.styleSheet()
    tab.btn_system.setChecked(False)
    assert '#636b7b' in tab.btn_system.styleSheet()

    monkeypatch.setattr(app_mod.kit, 'dark_from', lambda *a, **k: False)
    tab.btn_system.setChecked(True)
    assert '#5365d8' in tab.btn_system.styleSheet()
    tab.btn_system.setChecked(False)
    assert '#e8ebf3' in tab.btn_system.styleSheet()


def test_siralama_ve_sifirlama(uygulamalar):
    tab, core, _win = uygulamalar
    tab._apps = [
        _app('com.c.three', 'Cem'),
        _app('com.a.one', 'Ayşe'),
        _app('com.b.two', 'Bora', enabled=False),
    ]
    tab._apply_filter_now()

    tab._sort_by(COL_NAME, Qt.AscendingOrder)
    assert [tab.grid.item(r, COL_NAME).text() for r in range(3)] == [
        'Ayşe', 'Bora', 'Cem']
    tab._sort_by(COL_NAME, Qt.DescendingOrder)
    assert [tab.grid.item(r, COL_NAME).text() for r in range(3)] == [
        'Cem', 'Bora', 'Ayşe']
    tab._sort_by(COL_PKG, Qt.AscendingOrder)
    assert [tab.grid.item(r, COL_PKG).text() for r in range(3)] == [
        'com.a.one', 'com.b.two', 'com.c.three']
    tab._sort_by(COL_STATE, Qt.AscendingOrder)
    assert tab.grid.item(0, COL_PKG).text() == 'com.b.two'

    # Gecersiz sutun (Sec): siralama degismez, ozyineleme yok
    onceki = [tab.grid.item(r, COL_PKG).text() for r in range(3)]
    tab._sort_by(COL_CHECK, Qt.AscendingOrder)
    assert [tab.grid.item(r, COL_PKG).text() for r in range(3)] == onceki

    # Filtreleri sifirla: arama, durum ve sistem birlikte doner
    tab.txt_search.setText('Cem')
    tab.cmb_status.setCurrentIndex(tab.cmb_status.findData(STATUS_REMOVED))
    tab.btn_system.setChecked(False)
    assert core.config.show_removed is True
    tab._reset_filters()
    assert tab.txt_search.text() == ''
    assert tab.cmb_status.currentData() == STATUS_ALL
    assert tab.btn_system.isChecked() is True
    assert core.config.show_removed is False
    assert tab.grid.rowCount() == 3

    # Zamanlayici tabanli filtre tetikleyicisi
    tab._filter_timer.stop()
    tab._apply_filter()
    assert tab._filter_timer.isActive() is True
    tab._filter_timer.stop()


def test_tema(uygulamalar, monkeypatch):
    tab, _core, _win = uygulamalar

    def tema_patlak(*_a, **_k):
        raise RuntimeError('tema yok')

    monkeypatch.setattr(app_mod.kit, 'dark_from', tema_patlak)
    tab.apply_theme()  # ilk blok hata verir; sessizce cikilir

    monkeypatch.setattr(app_mod.kit, 'dark_from', lambda *a, **k: True)

    def filtre_patlak(*_a, **_k):
        raise RuntimeError('filtre yok')

    monkeypatch.setattr(tab, '_apply_filter_now', filtre_patlak)
    tab.apply_theme()

    def filtre_bozuk(*_a, **_k):
        raise ValueError('beklenmeyen')

    monkeypatch.setattr(tab, '_apply_filter_now', filtre_bozuk)
    tab.apply_theme()

    # Normal yol: secim etiketi ve sistem dugmesi yeni palete gecer
    monkeypatch.undo()
    monkeypatch.setattr(app_mod.kit, 'dark_from', lambda *a, **k: True)
    monkeypatch.setattr(app_mod.kit, 'faint', lambda dark: 'TEMA({})'.format(dark))
    tab.apply_theme()
    assert tab.lbl_sel.styleSheet() == 'TEMA(True)'
    assert '#38457c' in tab.btn_system.styleSheet()


def test_secim_isaretleri(uygulamalar):
    tab, core, _win = uygulamalar
    tab._apps = [
        _app('com.a.one', 'Bir'),
        _app('com.b.two', 'İki'),
        _app('com.c.three', 'Üç'),
        _app('com.d.four', 'Dört'),
    ]
    core.config.protected = {'com.d.four'}
    tab._apply_filter_now()
    assert tab.grid.rowCount() == 4

    # Korunan satir isaretlenemez; uyari ipucu ve renk tasir
    korunan = tab.grid.item(3, COL_CHECK)
    assert not (korunan.flags() & Qt.ItemIsUserCheckable)
    assert korunan.toolTip() == 'Koruma listesinde (işlem için secilemez)'
    assert tab.grid.item(3, COL_NAME).toolTip() == (
        'Koruma listesinde (işlem için secilemez)')

    # Tek satir isaretle: sayim, secim listesi ve dugmeler
    tab.grid.item(0, COL_CHECK).setCheckState(Qt.Checked)
    assert tab.lbl_sel.text() == 'Seçili: 1/4'
    assert tab._selected_packages() == ['com.a.one']
    assert tab.btn_launch.isEnabled() is True
    assert tab._more_actions[0][0].isEnabled() is True
    assert tab._more_actions[0][1].isHidden() is True

    # Tumunu sec: korunan satir atlanir, baslik isaretlenir
    tab.btn_select_all.click()
    assert tab.lbl_sel.text() == 'Seçili: 3/4'
    tab._toggle_all(False)
    assert tab.lbl_sel.text() == 'Seçili: 0/4'
    assert tab.grid.horizontalHeaderItem(COL_CHECK).text() == 'Seç'

    # Ters cevir: korunan yine atlanir
    tab.chk_inv.click()
    assert tab.lbl_sel.text() == 'Seçili: 3/4'
    tab.chk_inv.click()
    assert tab.lbl_sel.text() == 'Seçili: 0/4'

    # Yalnizca satir secimi: '(satır)' isaretlenir ve liste secimden gelir
    tab.grid.selectRow(1)
    assert tab.lbl_sel.text() == 'Seçili: 1/4 (satır)'
    assert tab._selected_packages() == ['com.b.two']
    tab.btn_clear_selection.click()
    assert tab.lbl_sel.text() == 'Seçili: 0/4'
    assert tab.btn_launch.isEnabled() is False

    # Baslik tiklamasi: bos -> tumu, tumu -> birak; diger sutun yok sayilir
    tab._on_header_clicked(COL_CHECK)
    assert tab.lbl_sel.text() == 'Seçili: 3/4'
    assert tab.grid.horizontalHeaderItem(COL_CHECK).text() == '☑ Seç'
    tab._on_header_clicked(COL_CHECK)
    assert tab.lbl_sel.text() == 'Seçili: 0/4'
    tab._on_header_clicked(COL_NAME)
    assert tab.lbl_sel.text() == 'Seçili: 0/4'

    # Mesguliyette islem dugmeleri kapanir, bitince geri acilir
    tab.grid.item(0, COL_CHECK).setCheckState(Qt.Checked)
    assert tab.btn_launch.isEnabled() is True
    tab._set_busy(True)
    assert tab.btn_launch.isEnabled() is False
    assert tab._more_actions[0][0].isEnabled() is False
    tab._set_busy(False)
    assert tab.btn_launch.isEnabled() is True


def test_isaret_koruma_ve_dayaniklilik(uygulamalar):
    tab, core, _win = uygulamalar
    tab._apps = [_app('com.a.one', 'Bir'), _app('com.b.two', 'İki')]
    core.config.protected = {'com.b.two'}
    tab._apply_filter_now()

    # Yeniden giris kilidi: es zamanli ikinci cagri erken doner, bayrak korunur
    tab._in_item_changed = True
    tab._on_item_changed(None)
    assert tab._in_item_changed is True
    tab._in_item_changed = False

    # Yanlis sutun ve None oge sessizce yok sayilir
    tab._on_item_changed(tab.grid.item(0, COL_NAME))
    tab._on_item_changed(None)

    # Satir siniri disindaki oge yok sayilir
    tab._on_item_changed(SimpleNamespace(column=lambda: COL_CHECK, row=lambda: 99))

    # Paket sutunu olmayan satir: bayrak duzeltmesi yapilmaz
    tab.grid.insertRow(tab.grid.rowCount())
    eksik_satir = tab.grid.rowCount() - 1
    tab._on_item_changed(SimpleNamespace(column=lambda: COL_CHECK,
                                         row=lambda: eksik_satir))
    tab.grid.setRowCount(tab.grid.rowCount() - 1)

    # Bayrak uyusmazligi: isaret kutusu korunan paket icin kapatilir
    korunan = tab.grid.item(1, COL_CHECK)
    tab.grid.blockSignals(True)
    korunan.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
    tab.grid.blockSignals(False)
    tab._on_item_changed(korunan)
    assert korunan.flags() == (Qt.ItemIsEnabled | Qt.ItemIsSelectable)

    # Beklenen bayraktaysa hicbir sey degismez
    duzgun = tab.grid.item(0, COL_CHECK)
    onceki = duzgun.flags()
    tab._on_item_changed(duzgun)
    assert duzgun.flags() == onceki

    # Bozuk ogeler: RuntimeError ve beklenmeyen hata yutulur
    class _PatlakOge:
        def column(self):
            raise RuntimeError('oge yok')

    tab._on_item_changed(_PatlakOge())

    class _BozukOge:
        def column(self):
            raise ValueError('bozuk')

    tab._on_item_changed(_BozukOge())

    # Sayim ve toplu islemler bozuk tabloda sessiz kalir
    class _RowPatlak:
        def rowCount(self):
            raise RuntimeError('yok')

    AppsTab._update_sel_count(SimpleNamespace(grid=_RowPatlak()))
    AppsTab._on_header_clicked(SimpleNamespace(grid=_RowPatlak()), COL_CHECK)

    class _BasliksizGrid:
        def blockSignals(self, _flag):
            return False

        def rowCount(self):
            return 0

        def horizontalHeaderItem(self, _col):
            raise RuntimeError('yok')

    AppsTab._toggle_all(SimpleNamespace(grid=_BasliksizGrid(),
                                        _update_sel_count=lambda: None), True)


def test_bozuk_kombolar():
    # _restore_status_from_config: sinyal acma adimi patlarsa yutulur
    class _Kombo:
        def findData(self, _v):
            return 1

        def currentIndex(self):
            return 0

        def blockSignals(self, flag):
            if flag is False:
                raise RuntimeError('yok')

        def setCurrentIndex(self, _idx):
            pass

    fake = SimpleNamespace(
        core=SimpleNamespace(config=SimpleNamespace(show_removed=True)),
        cmb_status=_Kombo())
    AppsTab._restore_status_from_config(fake)

    # _on_status_combo: veri okunamazsa sessizce cikilir
    class _KomboPatlak:
        def currentData(self):
            raise RuntimeError('yok')

    AppsTab._on_status_combo(SimpleNamespace(cmb_status=_KomboPatlak()))


def test_secili_paketler_dayaniklilik():
    class _RowPatlak:
        def rowCount(self):
            raise RuntimeError('yok')

    assert AppsTab._selected_packages(SimpleNamespace(grid=_RowPatlak())) == []

    class _ItemPatlak:
        def rowCount(self):
            return 1

        def item(self, r, c):
            raise RuntimeError('yok')

        def selectedIndexes(self):
            return []

    assert AppsTab._selected_packages(SimpleNamespace(grid=_ItemPatlak())) == []

    class _SecimPatlak:
        def rowCount(self):
            return 1

        def item(self, r, c):
            return None

        def selectedIndexes(self):
            raise RuntimeError('yok')

    assert AppsTab._selected_packages(SimpleNamespace(grid=_SecimPatlak())) == []

    class _SahteOge:
        def __init__(self, state=Qt.Unchecked):
            self._state = state

        def flags(self):
            return Qt.ItemIsUserCheckable | Qt.ItemIsEnabled

        def checkState(self):
            return self._state

        def text(self):
            return ''

    class _PkgPatlak:
        """Isaret sutunu okunur ama paket sutunu her erisimde patlar."""

        def rowCount(self):
            return 1

        def item(self, r, c):
            if c == COL_CHECK:
                return _SahteOge(state=Qt.Checked)
            raise RuntimeError('pkg yok')

        def selectedIndexes(self):
            return [SimpleNamespace(row=lambda: 0)]

    assert AppsTab._selected_packages(SimpleNamespace(grid=_PkgPatlak())) == []


def test_baglanma_degisimi(uygulamalar):
    tab, core, win = uygulamalar
    tab._apps = [_app('com.a.one', 'Bir')]
    tab._last_scan_at = 'simdi'
    tab._presence = {'x'}

    # Bagli: yalnizca nesil artar, liste korunur
    core.connection_changed.emit(True, 'tv-1')
    assert tab._connection_generation == 1
    assert tab._apps != []
    assert tab._last_scan_at == 'simdi'

    # Kopma: isciler iptal edilir, veriler temizlenir
    isci = _SahteIsci()
    eksik = object()  # cancel yok -> AttributeError yutulur

    class _PatlakIptal(_SahteIsci):
        def cancel(self):
            raise RuntimeError('iptal yok')

    patlak = _PatlakIptal()
    tab._device_workers.add(isci)
    tab._device_workers.add(eksik)
    tab._device_workers.add(patlak)
    core.connection_changed.emit(False, '')
    assert tab._connection_generation == 2
    assert isci.cancel_calls == 1
    assert patlak.cancel_calls == 0
    assert tab._apps == []
    assert tab._presence == set()
    assert tab._last_scan_at is None
    assert tab.lbl_summary.text() == (
        'Bağlı cihaz yok. Cihaza bağlanıp listeyi yenileyin.')
    assert win.tab_remote.paketler[-1] == []
    assert win.tab_debloat.received[-1] == set()

    # Debloat tarafi hata verse de ozet yazilir (hata yutulur)
    win.tab_debloat = _DebloatPatlak()
    core.connection_changed.emit(False, '')
    assert tab.lbl_summary.text() == (
        'Bağlı cihaz yok. Cihaza bağlanıp listeyi yenileyin.')

    # Uzak sekme de patlarsa yine sessiz kalinir
    win.tab_debloat = _Debloat()
    win.tab_remote = _RemotePatlak()
    core.connection_changed.emit(False, '')
    assert tab.lbl_summary.text() == (
        'Bağlı cihaz yok. Cihaza bağlanıp listeyi yenileyin.')

    # Izlenen isci bitince kayittan duser
    takip = _SahteIsci()
    tab._track_device_worker(takip)
    assert takip in tab._device_workers
    takip.finished.emit()
    assert takip not in tab._device_workers

    # Baglam kapilari
    assert tab._device_context() == (core.engine, 'tv-1',
                                     tab._connection_generation)
    win._connection_busy = True
    assert tab._device_context() is None
    win._connection_busy = False
    core.connected = False
    assert tab._device_context() is None
    core.connected = True
    core.target = None
    assert tab._device_context() is None
    core.target = 'tv-1'
    core.engine_patlak = True
    assert tab._device_context() is None
    core.engine_patlak = False

    baglam = tab._device_context()
    assert tab._device_context_current(baglam) is True
    assert tab._device_context_current(None) is False
    core.target = 'tv-9'
    assert tab._device_context_current(baglam) is False
    core.target = 'tv-1'
    win._connection_busy = True
    assert tab._device_context_current(baglam) is False
    win._connection_busy = False
    core.connected = False
    assert tab._device_context_current(baglam) is False
    core.connected = True
    tab._connection_generation += 1
    assert tab._device_context_current(baglam) is False
    tab._connection_generation -= 1
    core.engine_patlak = True
    assert tab._device_context_current(baglam) is False
    core.engine_patlak = False
    assert tab._device_context_current(baglam) is True


def test_yenileme(uygulamalar, monkeypatch):
    tab, core, win = uygulamalar
    monkeypatch.setattr(app_mod, 'AppScanWorker', _SahteIsci)

    # Mesgulken ikinci tarama baslamaz
    tab._busy = True
    assert tab.refresh() is False
    assert tab.lbl_summary.text() == 'Devam eden işlem var; bitmesini bekleyin.'
    tab._busy = False

    # Baglantisiz: on_fail bilgilendirilir
    hatalar = []
    core.connected = False
    assert tab.refresh(on_fail=hatalar.append) is False
    assert hatalar == ['cihaz bağlı değil']
    assert tab.lbl_summary.text() == (
        "Bağlı cihaz yok. Uygulamaları listelemek için önce TV'ye bağlanın.")
    core.connected = True

    # Baglanti mesgul: baglam yok
    win._connection_busy = True
    hatalar.clear()
    assert tab.refresh(on_fail=hatalar.append) is False
    assert hatalar == ['cihaz bağlantısı değişti']
    assert tab.lbl_summary.text() == 'Tarama başarısız: cihaz bağlantısı değişti.'
    win._connection_busy = False

    # Basarili baslangic: isci kurulur, sayfa kilitlenir
    tamam = []
    assert tab.refresh(on_done=tamam.append) is True
    w = win.runs[-1][0]
    assert isinstance(w, _SahteIsci)
    assert w.args == (core.engine, 'tv-1', True)
    assert w.kwargs == {}
    assert win.runs[-1][1] == 'Uygulamalar Yenile: tv-1 taraniyor'
    assert tab._scanned_with_system is True
    assert tab._scan_generation == 1
    assert tab._scan_worker is w
    assert tab._busy is True
    assert tab.lbl_summary.text() == 'Taraniyor...'
    assert tab.grid.empty_title == 'Uygulamalar taranıyor'

    # Ilerleme: guncel baglamda yazilir, bayat baglamda yutulur
    w.progress.emit(5, 20)
    assert tab.lbl_summary.text() == '5/20 kontrol ediliyor...'
    core.target = 'tv-9'
    w.progress.emit(6, 20)
    assert tab.lbl_summary.text() == '5/20 kontrol ediliyor...'
    core.target = 'tv-1'

    # Varlik sinyali guncel baglamda islenir
    w.presence.emit({'present': {'p'}, 'disabled': set()})
    assert tab._presence == {'p'}

    # Sonuc: ad tamamlanir, uzak sekmelere yazilir, on_done cagirilir
    tab._last_scan_at = None
    w.finished_ok.emit([_app('com.a.one', 'Bir Uygulama')])
    assert tamam and tamam[-1][0]['package'] == 'com.a.one'
    assert tab._apps[0]['name'] == 'Bir Uygulama'
    assert tab._last_scan_at is not None
    assert tab.grid.rowCount() == 1
    assert win.tab_remote.paketler[-1] is tamam[-1]
    assert win.tab_debloat.received[-1] == {'present': {'p'}, 'disabled': set()}

    # Bitis: kilit acilir
    w.tamamlandi = True
    w.finished.emit()
    assert tab._scan_worker is None
    assert tab._busy is False

    # Bayat nesilde sonuc yansitilmaz
    tamam2 = []
    assert tab.refresh(on_done=tamam2.append) is True
    w2 = win.runs[-1][0]
    tab._scan_generation += 1
    w2.finished_ok.emit([_app('x.y')])
    w2.presence.emit({'present': set(), 'disabled': set()})
    assert tamam2 == []
    tab._scan_generation -= 1
    w2.tamamlandi = True
    w2.finished.emit()
    assert tab._scan_worker is None

    # Tarama hatasi: ozet ve on_fail
    hatalar.clear()
    assert tab.refresh(on_fail=hatalar.append) is True
    w3 = win.runs[-1][0]
    w3.failed.emit('adbsiz')
    assert hatalar == ['adbsiz']
    assert tab.lbl_summary.text() == 'Tarama başarısız: adbsiz'
    w3.tamamlandi = True
    w3.finished.emit()

    # Bayat neslin hatasi yansitilmaz
    assert tab.refresh(on_fail=hatalar.append) is True
    w4 = win.runs[-1][0]
    tab._scan_generation += 1
    w4.failed.emit('bayat')
    assert hatalar == ['adbsiz']
    tab._scan_generation -= 1
    w4.tamamlandi = True
    w4.finished.emit()

    # Bos tabloda hata: kalici bos durum metni gosterilir
    tab._apps = []
    tab.grid.setRowCount(0)
    assert tab.refresh(on_fail=hatalar.append) is True
    w5 = win.runs[-1][0]
    w5.failed.emit('yok')
    assert tab.grid.empty_title == 'Uygulama listesi alınamadı'
    assert tab.grid.empty_description == (
        'Bağlantıyı kontrol edin ve Yenile ile tekrar deneyin.')
    w5.tamamlandi = True
    w5.finished.emit()

    # Isci calistirilamazsa kilit acilir ve hata bildirilir
    win.run_patlak = True
    hatalar.clear()
    assert tab.refresh(on_fail=hatalar.append) is False
    assert hatalar == ['calistirilamadi']
    assert tab.lbl_summary.text() == 'Tarama başarısız: calistirilamadi'
    assert tab._scan_worker is None
    assert tab._busy is False
    win.run_patlak = False


def test_tarama_sonuclari(uygulamalar):
    tab, core, win = uygulamalar
    core.config.friendly = {'com.b.two': 'Bilinen Ad'}
    apps = [
        _app('com.a.one', 'Cihaz Adı'),
        _app('com.b.two'),                       # etiket yok -> dost ad
        _app('com.c.three', None, enabled=False),
        _app('com.gone.old', 'Eski', installed_user0=False),
    ]
    tab._on_scan_done(apps)
    assert apps[0]['name'] == 'Cihaz Adı'
    assert apps[1]['name'] == 'Bilinen Ad'
    assert apps[2]['name'] == 'com.c.three'
    assert tab._last_scan_at is not None
    assert win.tab_remote.paketler[-1] is apps
    assert win.tab_debloat.received[-1] == {
        'present': {'com.a.one', 'com.b.two', 'com.c.three'},
        'disabled': {'com.c.three'}}
    assert tab.grid.rowCount() == 3

    # Varlik bilgisi onceden geldiyse yeniden hesaplanmaz
    tab._on_presence({'present': {'p'}, 'disabled': set()})
    tab._on_scan_done([_app('com.x.y', 'X')])
    assert win.tab_debloat.received[-1] == {
        'present': {'p'}, 'disabled': set()}

    # Uzak sekme patlarsa yutulur, debloat yine guncellenir
    win.tab_remote = _RemotePatlak()
    tab._on_scan_done([_app('com.z.z', 'Z')])
    assert win.tab_debloat.received[-1] == {
        'present': {'p'}, 'disabled': set()}

    # Debloat patlarsa sessiz kalinir, liste yine islenir
    win.tab_debloat = _DebloatPatlak()
    tab._on_scan_done([_app('com.w.w', 'W')])
    assert tab._apps[-1]['package'] == 'com.w.w'

    # Ic uzak sekme varsa o kullanilir
    ic = _Remote()
    win.tab_remote_inner = ic
    tab._on_scan_done([_app('com.v.v', 'V')])
    assert ic.paketler[-1][0]['package'] == 'com.v.v'

    # Varlik bildirimi debloat tarafina yazilamazsa sessiz kalinir
    win.tab_debloat = _DebloatPatlak()
    tab._on_presence(['q'])
    assert tab._presence == {'q'}

    # _on_presence: liste bicimi mevcut set'leri sifirlar
    win.tab_debloat = _Debloat()
    tab._on_presence(['x', 'y'])
    assert tab._presence == {'x', 'y'}
    assert tab._disabled_presence == set()
    assert tab._presence_info == {'present': {'x', 'y'}, 'disabled': set()}
    assert win.tab_debloat.received[-1] == tab._presence_info

    # Dogrudan yardimcilar
    tab._on_progress(3, 9)
    assert tab.lbl_summary.text() == '3/9 kontrol ediliyor...'
    tab._on_scan_fail('kopuk')
    assert tab.lbl_summary.text() == 'Tarama başarısız: kopuk'


def test_paket_islemi_cercevesi(uygulamalar, monkeypatch):
    tab, core, win = uygulamalar
    context = tab._device_context()

    # Kapilar: mesgul, bayat baglam, kapanan pencere
    tab._busy = True
    assert tab._start_package_operation(
        _SahteIsci(), context, lambda res: None) is False
    assert tab.lbl_summary.text() == (
        'İşlem başlatılamadı; bağlantıyı ve devam eden işlemleri kontrol edin.')
    tab._busy = False

    eski = tab._device_context()
    tab._connection_generation += 1
    assert tab._start_package_operation(
        _SahteIsci(), eski, lambda res: None) is False
    tab._connection_generation -= 1

    win._closing = True
    assert tab._start_package_operation(
        _SahteIsci(), context, lambda res: None) is False
    win._closing = False
    win._close_pending = True
    assert tab._start_package_operation(
        _SahteIsci(), context, lambda res: None) is False
    win._close_pending = False

    # Basarili baslangic: sinyaller baglanir, sayfa kilitlenir
    sonuc = []
    yenilendi = []
    monkeypatch.setattr(tab, 'refresh',
                        lambda *a, **k: yenilendi.append(True) or True)
    w = _SahteIsci()
    assert tab._start_package_operation(
        w, context, sonuc.append, refresh_after=True) is True
    assert tab._operation_worker is w
    assert tab._busy is True
    assert w in tab._device_workers
    assert win.runs[-1][0] is w

    # Ilerleme: guncel baglamda yazilir, bayat baglamda yutulur
    w.progress.emit(2, 5)
    assert tab.lbl_summary.text() == '2/5 paket işleniyor…'
    core.target = 'tv-9'
    w.progress.emit(3, 5)
    assert tab.lbl_summary.text() == '2/5 paket işleniyor…'
    core.target = 'tv-1'

    # Baska iscinin bitisi kendi kaydini gormezden gelir
    yerine = _SahteIsci()
    tab._operation_worker = yerine
    w.finished.emit()
    assert tab._operation_worker is yerine
    assert tab._busy is True
    tab._operation_worker = w

    # Basarili bitis: yenileme + on_ok, kilit acilir
    w.finished_ok.emit({'ok': 1})
    w.tamamlandi = True
    w.finished.emit()
    assert sonuc == [{'ok': 1}]
    assert yenilendi == [True]
    assert tab._operation_worker is None
    assert tab._busy is False

    # Hata: son hata mesaji ozete yazilir, on_ok cagirilmaz
    hatali = _SahteIsci()
    assert tab._start_package_operation(hatali, context, sonuc.append) is True
    hatali.failed.emit('yetki yok')
    hatali.tamamlandi = True
    hatali.finished.emit()
    assert tab.lbl_summary.text() == 'İşlem başarısız: yetki yok'
    assert sonuc == [{'ok': 1}]

    # Sinyalsiz bitis: genel mesaj
    bos = _SahteIsci()
    assert tab._start_package_operation(bos, context, sonuc.append) is True
    bos.tamamlandi = True
    bos.finished.emit()
    assert tab.lbl_summary.text() == 'İşlem tamamlanamadı.'

    # Bitis aninda baglam bayatlarsa sonuc yazilmaz
    bayat = _SahteIsci()
    assert tab._start_package_operation(bayat, context, sonuc.append) is True
    bayat.finished_ok.emit({'ok': 2})
    core.target = 'tv-9'
    bayat.tamamlandi = True
    bayat.finished.emit()
    core.target = 'tv-1'
    assert sonuc == [{'ok': 1}]
    assert tab._operation_worker is None
    assert tab._busy is False

    # Bitis aninda pencere kapaniyorsa sonuc yazilmaz
    kapanan = _SahteIsci()
    assert tab._start_package_operation(kapanan, context, sonuc.append) is True
    kapanan.finished_ok.emit({'ok': 3})
    win._closing = True
    kapanan.tamamlandi = True
    kapanan.finished.emit()
    win._closing = False
    assert sonuc == [{'ok': 1}]

    # Isci calistirilamazsa kayit temizlenir ve hata bildirilir
    win.run_patlak = True
    patlak = _SahteIsci()
    assert tab._start_package_operation(patlak, context, sonuc.append) is False
    win.run_patlak = False
    assert tab.lbl_summary.text() == 'İşlem başlatılamadı: calistirilamadi'
    assert patlak not in tab._device_workers
    assert tab._operation_worker is None
    assert tab._busy is False


@pytest.mark.parametrize('full,change_target', [(False, False), (True, False), (True, True)])
def test_uninstall_choice_forwarded(uygulamalar, monkeypatch, full, change_target):
    tab, core, win = uygulamalar
    started = []

    def confirm(*args, **kwargs):
        kwargs['uninstall_options']['full_uninstall'] = full
        if change_target:
            core.target = 'other-device'
        return True

    monkeypatch.setattr(dialogs_mod, 'confirm_action', confirm)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a: None)
    monkeypatch.setattr(app_mod, 'PackageActionWorker',
                        lambda *a, **k: started.append((a, k)) or object())
    monkeypatch.setattr(tab, '_start_package_operation', lambda *a, **k: True)
    tab._pkg_action('uninstall', packages=['com.a.one', 'com.b.two'])
    if change_target:
        assert started == []
    else:
        assert started[0][0][2] == ['com.a.one', 'com.b.two']
        assert started[0][1] == ({'full_uninstall': True} if full else {})


def test_paket_aksiyonlari(uygulamalar, monkeypatch):
    tab, core, win = uygulamalar
    kutular = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: kutular.append(('info', a[1], a[2])))
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: kutular.append(('uyari', a[1], a[2])))
    onaylar = []

    def onayla(*a, **k):
        onaylar.append(a + (k.get('extra'),))
        return True

    monkeypatch.setattr(dialogs_mod, 'confirm_action', onayla)
    monkeypatch.setattr(dialogs_mod, 'ACTION_TR', {'enable': 'Etkinleştir'})
    isciler = []

    def isci_yap(*args, **kwargs):
        w = _SahteIsci(*args, **kwargs)
        isciler.append(w)
        return w

    monkeypatch.setattr(app_mod, 'PackageActionWorker', isci_yap)
    monkeypatch.setattr(workers_mod, 'format_action_result',
                        lambda res: 'RAPOR:' + res.get('x', '?'))
    monkeypatch.setattr(tab, 'refresh', lambda *a, **k: True)

    # Mesgulken yeni islem baslatilmaz
    tab._busy = True
    tab._pkg_action('enable', packages=['com.a.one'])
    assert tab.lbl_summary.text() == (
        'Devam eden işlem bitmeden yeni paket işlemi başlatılamaz.')
    tab._busy = False

    # Secim yoksa bilgilendirme
    tab._pkg_action('enable')
    assert kutular[-1] == ('info', 'Seçim', 'Önce uygulama seçin.')

    # Korunanlarin tamami (stop disinda) reddedilir
    core.config.protected = {'com.p.one', 'com.p.two'}
    core.config.friendly = {'com.p.one': 'Korunan Bir'}
    tab._pkg_action('disable', packages=['com.p.one', 'com.p.two'])
    assert kutular[-1][0] == 'uyari'
    assert kutular[-1][1] == 'Koruma'
    assert kutular[-1][2] == (
        'Seçilenlerin TAMAMI koruma listesinde; işlem yapılmadı:\n\n'
        '• Korunan Bir\n• com.p.two')
    assert isciler == []

    # 'stop' koruma gerekcesini atlar; onaydan sonra isci kurulur
    core.config.protected = {'com.p.one'}
    onaylar.clear()
    tab._pkg_action('stop', packages=['com.p.one'])
    assert onaylar and onaylar[-1][1] == 'stop'
    assert onaylar[-1][3].__name__ == 'friendly_name'
    assert onaylar[-1][4] == 'Cihaz: tv-1 · Android kullanıcısı: 0'
    w_stop = isciler[-1]
    assert w_stop.args[2] == ['com.p.one']
    assert w_stop.args[3] == 'stop'
    assert w_stop.args[4] == {'com.p.one'}
    w_stop.tamamlandi = True
    w_stop.finished.emit()

    # Baglanti yokken bilgilendirme
    core.config.protected = set()
    win._connection_busy = True
    tab._pkg_action('enable', packages=['com.a.one'])
    assert kutular[-1] == ('info', 'Bağlantı Yok', 'Önce cihaza bağlanın.')
    win._connection_busy = False

    # Onay reddi: islem baslamaz
    def reddet(*a, **k):
        onaylar.append(a + (k.get('extra'),))
        return False

    monkeypatch.setattr(dialogs_mod, 'confirm_action', reddet)
    onaylar.clear()
    onceki = len(isciler)
    tab._pkg_action('uninstall', packages=['com.a.one'])
    assert onaylar and onaylar[-1][1] == 'uninstall'
    assert len(isciler) == onceki

    # Onay sonrasi baglanti degisirse islem baslatilmaz
    def onayla_degistir(*a, **k):
        onaylar.append(a + (k.get('extra'),))
        core.target = 'tv-2'
        return True

    monkeypatch.setattr(dialogs_mod, 'confirm_action', onayla_degistir)
    tab._pkg_action('disable', packages=['com.a.one'])
    assert kutular[-1] == (
        'uyari', 'Paket işlemi',
        'Cihaz bağlantısı değişti. İşlem başlatılmadı; yeniden deneyin.')
    core.target = 'tv-1'

    # Basarili akis: son islem kaydi, isci argumanlari ve tamamlanma bildirimi
    monkeypatch.setattr(dialogs_mod, 'confirm_action', onayla)
    tab._apps = [_app('com.a.one', 'Bir')]
    tab._apply_filter_now()
    tab._pkg_action('enable', packages=[
        'com.a.one', 'com.b.two', 'com.c.three', 'com.d.four'])
    assert win.son_islem == (
        '4 uygulamaya Etkinleştir: com.a.one, com.b.two, com.c.three… paket')
    isci = isciler[-1]
    assert isci.args == (
        core.engine, 'tv-1',
        ['com.a.one', 'com.b.two', 'com.c.three', 'com.d.four'],
        'enable', core.config.protected)
    assert win.runs[-1][0] is isci
    isci.finished_ok.emit({'x': 'v'})
    isci.tamamlandi = True
    isci.finished.emit()
    assert kutular[-1] == ('info', 'Tamam', 'RAPOR:v')

    # Son islem kaydi patlarsa islem yine surer
    def kayit_patlak(_text):
        raise RuntimeError('kayit yok')

    win.set_last_action = kayit_patlak
    tab._pkg_action('enable', packages=['com.x.x'])
    isci2 = isciler[-1]
    assert isci2.args[2] == ['com.x.x']
    isci2.tamamlandi = True
    isci2.finished.emit()

    # Tek paketli akis (sag tik menusu) ayni yoldan gecer
    sayi = len(isciler)
    tab._pkg_action_single('launch', 'com.a.one')
    assert len(isciler) == sayi + 1
    assert isciler[-1].args[2] == ['com.a.one']
    assert isciler[-1].args[3] == 'launch'
    isciler[-1].tamamlandi = True
    isciler[-1].finished.emit()


class _Kutu(QMessageBox):
    """Shiboken tuzagi: ornek exec'i sinif duzeyinde ezmek ise yaramiyor;
    modul adini bu alt sinifla degistiriyoruz."""

    kayitlar = []
    tikla = False

    def exec(self):
        _Kutu.kayitlar.append(self)
        return 0

    def clickedButton(self):
        if _Kutu.tikla:
            for btn in self.buttons():
                if btn.text() == 'Klasörü aç':
                    return btn
        return None


def test_apk_yedekleme(uygulamalar, monkeypatch):
    tab, core, win = uygulamalar
    kutular = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: kutular.append(('info', a[1], a[2])))
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: kutular.append(('uyari', a[1], a[2])))
    isciler = []

    def isci_yap(*args, **kwargs):
        w = _SahteIsci(*args, **kwargs)
        isciler.append(w)
        return w

    monkeypatch.setattr(app_mod, 'ApkBackupWorker', isci_yap)
    monkeypatch.setattr(tab, 'refresh', lambda *a, **k: True)

    # Secim yoksa bilgilendirme
    tab._backup_apk()
    assert kutular[-1] == (
        'info', 'Seçim', 'Önce APK yedeklenecek uygulamaları seçin.')

    # Baglanti yokken bilgilendirme
    win._connection_busy = True
    tab._backup_packages(['com.a.one'])
    assert kutular[-1] == ('info', 'Bağlantı Yok', 'Önce cihaza bağlanın.')
    win._connection_busy = False

    # Mesgulken yedekleme baslamaz
    tab._busy = True
    tab._backup_packages(['com.a.one'])
    assert tab.lbl_summary.text() == (
        'Devam eden işlem bitmeden APK yedeklemesi başlatılamaz.')
    tab._busy = False

    # Isaretli satirlar yedekleme iscisine gider
    tab._apps = [_app('com.a.one', 'Bir'), _app('com.b.two', 'İki')]
    tab._apply_filter_now()
    tab.grid.item(0, COL_CHECK).setCheckState(Qt.Checked)
    tab.grid.item(1, COL_CHECK).setCheckState(Qt.Checked)
    tab._backup_apk()
    w = isciler[-1]
    assert w.args == (core.engine, 'tv-1', ['com.a.one', 'com.b.two'],
                      app_mod.APK_DIR)
    assert win.runs[-1][0] is w
    w.tamamlandi = True
    w.finished.emit()

    # Sonuc kutusu: satirlar, ayrinti metni ve piktogram
    monkeypatch.setattr(app_mod, 'QMessageBox', _Kutu)
    _Kutu.kayitlar = []
    _Kutu.tikla = False
    acilan = []
    monkeypatch.setattr(tab, '_open_apk_dir', lambda: acilan.append(True))
    tab._on_backup_done({
        'ok': 2, 'fail': 3, 'cancelled': 1,
        'details': [('a', True, 'tamam'), ('b', False, 'izin yok'),
                    ('c', False, 'yol yok'), ('d', False, 'diger')]})
    kutu = _Kutu.kayitlar[-1]
    assert kutu.windowTitle() == 'Yedekleme sonucu'
    assert kutu.text() == '\n'.join([
        '2 uygulamanın APK yedeği alındı.',
        '2 uygulama yedeklenemedi.',
        '1 uygulamanın yedeklemesi durduruldu.',
        '• b: izin yok', '• c: yol yok', '• d: diger',
        '\nKonum: ' + app_mod.APK_DIR])
    assert kutu.detailedText() == (
        'a — Tamam: tamam\nb — Yedeklenmedi: izin yok\n'
        'c — Yedeklenmedi: yol yok\nd — Yedeklenmedi: diger')
    assert kutu.icon() == _Kutu.Warning
    assert acilan == []

    # Ayrintisiz sonuc: bilgi piktogrami; 'Klasörü aç' tiklanirsa klasor acilir
    _Kutu.tikla = True
    acilan.clear()
    tab._on_backup_done({'ok': 1})
    assert _Kutu.kayitlar[-1].icon() == _Kutu.Information
    assert _Kutu.kayitlar[-1].detailedText() == ''
    assert acilan == [True]
    _Kutu.tikla = False


def test_apk_klasoru(uygulamalar, monkeypatch, tmp_path):
    tab, _core, _win = uygulamalar
    hedef = tmp_path / 'yedekler'
    monkeypatch.setattr(app_mod, 'APK_DIR', str(hedef))
    cagrilar = []
    monkeypatch.setattr(os, 'startfile', cagrilar.append, raising=False)
    tab._open_apk_dir()
    assert hedef.is_dir()
    assert cagrilar == [str(hedef)]

    # Acilamazsa uyari kutusu cikar
    kutular = []
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: kutular.append((a[1], a[2])))

    def patlak(_path):
        raise OSError('olmadi')

    monkeypatch.setattr(os, 'startfile', patlak)
    tab._open_apk_dir()
    assert kutular[-1] == ('Hata', 'Klasör açılamadı: olmadi')

    # win32 disi dal: xdg-open cagrisi
    cagrilar.clear()
    monkeypatch.setattr(sys, 'platform', 'linux')
    ppen = []
    monkeypatch.setattr(subprocess, 'Popen', ppen.append)
    tab._open_apk_dir()
    assert ppen == [['xdg-open', str(hedef)]]


def test_csv_aktarimi(uygulamalar, monkeypatch, tmp_path):
    tab, _core, _win = uygulamalar
    kutular = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: kutular.append(('info', a[1], a[2])))
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: kutular.append(('kritik', a[1], a[2])))

    # Liste bosken aktarim yok
    tab._export_csv()
    assert kutular[-1] == ('info', 'Aktar', 'Önce listeyi yenileyin.')

    dosyalar = []

    class _DosyaDiyalogu:
        cevap = ('', '')

        @staticmethod
        def getSaveFileName(*a, **k):
            dosyalar.append(a)
            return _DosyaDiyalogu.cevap

    monkeypatch.setattr(app_mod, 'QFileDialog', _DosyaDiyalogu)

    tab._apps = [_app('com.a.one', 'Bir Uygulama'),
                 _app('com.b.two', '=Formül', enabled=False)]
    tab._apply_filter_now()

    # Iptal: dosya secilmezse sessizce cikilir
    tab._export_csv()
    assert dosyalar and dosyalar[-1][1] == 'CSV Kaydet'
    assert dosyalar[-1][2] == 'mibox-uygulamalar.csv'
    assert kutular[-1] == ('info', 'Aktar', 'Önce listeyi yenileyin.')

    # Basarili yazim: basliklar ve satirlar BOM'lu UTF-8
    hedef = tmp_path / 'liste.csv'
    _DosyaDiyalogu.cevap = (str(hedef), 'CSV (*.csv)')
    tab._export_csv()
    icerik = hedef.read_text(encoding='utf-8-sig')
    assert icerik.splitlines() == [
        'Ad,Paket,Durum',
        'Bir Uygulama,com.a.one,Etkin',
        "'=Formül,com.b.two,Devre dışı",
    ]
    assert kutular[-1] == ('info', 'Tamam', 'Aktarıldı:\n' + str(hedef))

    # Yazilamayan yol: hata kutusu
    _DosyaDiyalogu.cevap = (str(tmp_path / 'yok' / 'x.csv'), 'CSV (*.csv)')
    tab._export_csv()
    assert kutular[-1][0] == 'kritik'
    assert kutular[-1][1] == 'Hata'


class _Diyalog(QDialog):
    """exec() cagrisini durduran ince alt sinif (Shiboken tuzagi)."""

    baslik = None
    kayit = None

    def exec(self):
        _Diyalog.baslik = self.windowTitle()
        _Diyalog.kayit = self.findChildren(QTextEdit)[0]
        return 0


def test_detay_penceresi(uygulamalar, monkeypatch):
    tab, core, win = uygulamalar
    kutular = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: kutular.append(('info', a[1], a[2])))

    # Baglanti yokken bilgilendirme
    win._connection_busy = True
    tab._show_detail('com.a.one')
    assert kutular[-1] == ('info', 'Bağlantı Yok', 'Önce cihaza bağlanın.')
    win._connection_busy = False

    monkeypatch.setattr(app_mod, 'QDialog', _Diyalog)
    monkeypatch.setattr(app_mod, 'Worker', _SahteIsci)
    tab._show_detail('com.a.one')
    assert _Diyalog.baslik == 'Uygulama Detayi - com.a.one'
    txt = _Diyalog.kayit
    assert txt.isReadOnly() is True
    assert txt.toPlainText() == 'Yükleniyor...'
    w = win.runs[-1][0]
    assert isinstance(w, _SahteIsci)
    assert w in tab._device_workers

    sonuc = w.args[0]()
    assert core._engine.calls[-2:] == [
        ('app_detail', 'tv-1', 'com.a.one'),
        ('app_size', 'tv-1', 'com.a.one')]
    assert sonuc[0]['package'] == 'com.a.one'
    assert sonuc[1] == 2048
    w.finished_ok.emit(sonuc)
    assert txt.toPlainText() == (
        'Paket: com.a.one\n'
        'Ad: com.a.one\n'
        'Surum: 1.2 (3)\n'
        'Kurucu: adb\n'
        'İlk kurulum: 2024-01-01\n'
        'Son güncelleme: 2024-02-02\n'
        'Aktif: Evet\n'
        'Veri boyutu: 2.0 MB\n'
        'APK yolu: /data/app/x.apk\n'
        'Veri klasoru: /data/data/com.a.one\n')

    # Boyut alinamazsa 'olcumulemedi'
    core._engine.size_patlak = True
    w.finished_ok.emit(w.args[0]())
    assert 'Veri boyutu: olcumulemedi' in txt.toPlainText()
    core._engine.size_patlak = False

    # Pasif uygulama 'Hayir' yazar
    core._engine.detail['enabled'] = False
    w.finished_ok.emit(w.args[0]())
    assert 'Aktif: Hayir' in txt.toPlainText()
    core._engine.detail['enabled'] = True

    # Bitis aninda baglam bayatlarsa ayrinti gosterilmez
    core.target = 'tv-9'
    w.finished_ok.emit(sonuc)
    assert txt.toPlainText() == 'Cihaz bağlantısı değişti; ayrıntılar gösterilmedi.'
    core.target = 'tv-1'

    # Hata yollari: guncel ve bayat baglam
    w.failed.emit('hata')
    assert txt.toPlainText() == 'Hata: hata'
    core.target = 'tv-9'
    w.failed.emit('hata')
    assert txt.toPlainText() == 'Cihaz bağlantısı değişti; ayrıntılar gösterilmedi.'

    # Islev baglam bayatlarsa iptal eder
    with pytest.raises(CancelledError):
        w.args[0]()
    core.target = 'tv-1'

    # Cift tik: paket sutunu varsa detay acilir, yoksa sessiz kalinir
    cagrilar = []
    monkeypatch.setattr(tab, '_show_detail', cagrilar.append)
    tab._apps = [_app('com.a.one', 'Bir')]
    tab._apply_filter_now()
    tab._on_double_click(SimpleNamespace(row=lambda: 0))
    assert cagrilar == ['com.a.one']
    tab.grid.setRowCount(0)
    tab._on_double_click(SimpleNamespace(row=lambda: 0))
    assert cagrilar == ['com.a.one']


class _Menu(QMenu):
    """exec() durdurulur; istenirse tek bir eylem tetiklenir."""

    son = None
    tetikle = None

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        _Menu.son = self

    def exec(self, *a, **k):
        if _Menu.tetikle is not None:
            for act in self.actions():
                if act.text() == _Menu.tetikle:
                    act.trigger()
                    break
        return None


def test_sag_tik_menusu(uygulamalar, monkeypatch):
    tab, core, win = uygulamalar
    monkeypatch.setattr(app_mod, 'QMenu', _Menu)
    tab._apps = [_app('com.a.one', 'Bir')]
    tab._apply_filter_now()

    # Satir disi tik: menu acilmaz
    _Menu.son = None
    tab._context_menu(QPoint(0, -100))
    assert _Menu.son is None

    # Paket hucresi okunamayan satir: menu acilmaz
    oge = tab.grid.takeItem(0, COL_PKG)
    tab._context_menu(QPoint(0, 0))
    assert _Menu.son is None
    tab.grid.setItem(0, COL_PKG, oge)

    # Bozuk tablo: RuntimeError ve beklenmeyen hata yutulur
    class _PatlakGrid:
        def rowAt(self, _y):
            raise RuntimeError('yok')

    AppsTab._context_menu(SimpleNamespace(grid=_PatlakGrid()), QPoint(0, 0))

    class _BozukGrid:
        def rowAt(self, _y):
            raise ValueError('bozuk')

    AppsTab._context_menu(SimpleNamespace(grid=_BozukGrid()), QPoint(0, 0))

    # Menu icerigi ve sira
    nokta = tab.grid.visualItemRect(tab.grid.item(0, COL_PKG)).center()
    _Menu.son = None
    tab._context_menu(nokta)
    assert [act.text() for act in _Menu.son.actions()] == [
        '📋 Paket Adını Kopyala', '', 'Detay', 'Aç', 'Zorla durdur',
        'Veriyi Sil', 'Devre dışı bırak', 'Aktif et', 'Kaldır',
        'Geri Yükle', 'APK Yedekle']

    # Eylemler: detay, tekli islem ve yedekleme
    cagrilar = []
    monkeypatch.setattr(tab, '_show_detail',
                        lambda pkg: cagrilar.append(('detay', pkg)))
    monkeypatch.setattr(tab, '_pkg_action_single',
                        lambda action, pkg: cagrilar.append((action, pkg)))
    monkeypatch.setattr(tab, '_backup_packages',
                        lambda pkgs: cagrilar.append(('apk', list(pkgs))))

    _Menu.tetikle = 'Detay'
    tab._context_menu(nokta)
    assert cagrilar[-1] == ('detay', 'com.a.one')

    _Menu.tetikle = 'Aç'
    tab._context_menu(nokta)
    assert cagrilar[-1] == ('launch', 'com.a.one')

    _Menu.tetikle = 'APK Yedekle'
    tab._context_menu(nokta)
    assert cagrilar[-1] == ('apk', ['com.a.one'])
    _Menu.tetikle = None

    # Mesgulken cihaz eylemi reddedilir
    tab._busy = True
    cagrilar.clear()
    _Menu.tetikle = 'Aç'
    tab._context_menu(nokta)
    assert cagrilar == []
    assert tab.lbl_summary.text() == (
        'Bağlantı veya işlem durumu değişti; menüyü yeniden açın.')
    tab._busy = False
    _Menu.tetikle = None

    # Paket adini kopyala: dogrudan panoya yazar
    _Menu.tetikle = '📋 Paket Adını Kopyala'
    tab._context_menu(nokta)
    assert QApplication.clipboard().text() == 'com.a.one'
    _Menu.tetikle = None

    # Kaldirilmis satir: basa kalin 'Geri Yükle (önerilen)' eylemi eklenir
    tab._apps = [_app('com.gone.old', 'Eski', installed_user0=False)]
    tab.cmb_status.setCurrentIndex(tab.cmb_status.findData(STATUS_REMOVED))
    nokta = tab.grid.visualItemRect(tab.grid.item(0, COL_PKG)).center()
    _Menu.son = None
    tab._context_menu(nokta)
    ilk = _Menu.son.actions()[0]
    assert ilk.text() == 'Geri Yükle (önerilen)'
    assert ilk.font().bold() is True

    cagrilar.clear()
    _Menu.tetikle = 'Geri Yükle (önerilen)'
    tab._context_menu(nokta)
    assert cagrilar[-1] == ('restore', 'com.gone.old')
    _Menu.tetikle = None
