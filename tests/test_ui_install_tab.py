# -*- coding: utf-8 -*-
"""install_tab: katalog, kuyruk kurulumu, HOME ayari ve komut konsolu."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtWidgets import QPlainTextEdit, QWidget

import mibox_app.snapshot as snapshot_mod
import mibox_app.ui.install_tab as install_mod
from mibox_app.catalog import get_catalog
from mibox_app.ui.install_tab import (
    InstallTab,
    _DropQueueList,
    _is_store_item,
    _SnapshotEngineView,
)
from mibox_app.workers import CancelledError


class _Motor:
    """Sahte cihaz motoru; cagrilar kaydedilir, davranislar ayarlanabilir."""

    def __init__(self):
        self.calls = []
        self.paketler = []
        self.meta = {}
        self.varsayilan_meta = {}
        self.meta_patlak = False
        self.connect_patlak = False
        self.connect_hook = None
        self.install_apk_hook = None
        self.install_multiple_hook = None
        self.installed = set()
        self.is_installed_cevap = {}
        self.invalidate_patlak = False
        self.shell_result = SimpleNamespace(exit_code=0, output='', error='')
        self.shell_patlak = False
        self.launcher_listesi = []
        self.home = 'com.stok/.Main'
        self.last_home_notes = []
        self.launch_sonuc = 'ok'
        self.store_sonuc = 'ok'
        self.liste_patlak = False

    def connect(self, target, cancel_check=None):
        self.calls.append(('connect', target))
        if self.connect_hook is not None:
            self.connect_hook()
        if self.connect_patlak:
            raise RuntimeError('baglanti yok')

    def read_apk_metadata(self, path):
        self.calls.append(('read_apk_metadata', path))
        if self.meta_patlak:
            raise RuntimeError('meta yok')
        if path in self.meta:
            return dict(self.meta[path])
        return dict(self.varsayilan_meta)

    def install_apk(self, target, path, **kwargs):
        self.calls.append(('install_apk', target, path, dict(kwargs)))
        if self.install_apk_hook is not None:
            hata = self.install_apk_hook(target, path)
            if hata is not None:
                raise hata
        return SimpleNamespace(output='ok')

    def install_multiple(self, target, path, **kwargs):
        self.calls.append(('install_multiple', target, path, dict(kwargs)))
        if self.install_multiple_hook is not None:
            hata = self.install_multiple_hook(target, path)
            if hata is not None:
                raise hata
        return SimpleNamespace(output='ok')

    def invalidate_pkg_cache(self, target):
        self.calls.append(('invalidate_pkg_cache', target))
        if self.invalidate_patlak:
            raise RuntimeError('onbellek yok')

    def is_installed(self, target, pkg):
        self.calls.append(('is_installed', target, pkg))
        return self.is_installed_cevap.get(pkg, pkg in self.installed)

    def list_packages(self, target, include_system=True):
        self.calls.append(('list_packages', target, include_system))
        if self.liste_patlak:
            raise RuntimeError('liste yok')
        return list(self.paketler)

    def launch_app(self, target, pkg):
        self.calls.append(('launch_app', target, pkg))
        return self.launch_sonuc

    def open_play_store(self, target, pkg):
        self.calls.append(('open_play_store', target, pkg))
        return self.store_sonuc

    def launcher_apps(self, target):
        self.calls.append(('launcher_apps', target))
        return list(self.launcher_listesi)

    def home_activity(self, target):
        self.calls.append(('home_activity', target))
        return self.home

    def set_home_activity(self, target, comp):
        self.calls.append(('set_home_activity', target, comp))
        self.home = comp

    def shell(self, target, *parts, **kwargs):
        self.calls.append(('shell', target) + tuple(parts) + (dict(kwargs),))
        if self.shell_patlak:
            raise RuntimeError('shell yok')
        return self.shell_result


class _Yapilandirma:
    def __init__(self):
        self.install_grant_perms = True
        self.friendly = {}
        self.protected = []

    def friendly_name(self, pkg):
        return self.friendly.get(pkg, pkg)

    def is_protected(self, pkg):
        return pkg in self.protected


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


class _Uygulamalar:
    def __init__(self):
        self.refresh_sayaci = 0

    def refresh(self):
        self.refresh_sayaci += 1


class _UygulamalarPatlak:
    def refresh(self):
        raise RuntimeError('liste yok')


class _Pencere:
    def __init__(self):
        self.runs = []
        self._connection_busy = False
        self._closing = False
        self._close_pending = False
        self.run_patlak = False
        self.tab_apps = _Uygulamalar()

    def _run(self, worker, desc=None):
        if self.run_patlak:
            self.run_patlak = False
            raise RuntimeError('calistirilamadi')
        self.runs.append((worker, desc))


class _Dugme:
    def __init__(self, text, role):
        self.text = text
        self.role = role
        self.props = {}

    def setProperty(self, name, value):
        self.props[name] = value


class _Kutu:
    """QMessageBox sahtesi: statik sorular kayda gecer, cevap/_hook ile oynanir."""

    Yes = 1
    No = 0
    AcceptRole = 2
    RejectRole = 3
    kayitlar = []
    cevap = 0
    tiklama = None
    hook = None
    exec_hook = None
    son_ornek = None

    def __init__(self, parent=None):
        self.parent = parent
        self.title = ''
        self.text = ''
        self.buttons = {}
        self._clicked = None
        type(self).son_ornek = self

    def setWindowTitle(self, t):
        self.title = t

    def setText(self, t):
        self.text = t

    def addButton(self, text, role):
        b = _Dugme(text, role)
        self.buttons[text] = b
        return b

    def exec(self):
        if type(self).exec_hook is not None:
            type(self).exec_hook()
        if type(self).tiklama is not None:
            self._clicked = self.buttons.get(type(self).tiklama)
        return 0

    def clickedButton(self):
        return self._clicked

    @staticmethod
    def _kaydet(kind, args):
        _Kutu.kayitlar.append((kind, args[1], args[2]))

    @staticmethod
    def information(*a, **k):
        _Kutu._kaydet('info', a)

    @staticmethod
    def warning(*a, **k):
        _Kutu._kaydet('uyari', a)
        if _Kutu.hook is not None:
            _Kutu.hook()
        return _Kutu.cevap

    @staticmethod
    def critical(*a, **k):
        _Kutu._kaydet('kritik', a)

    @staticmethod
    def question(*a, **k):
        _Kutu._kaydet('soru', a)
        if _Kutu.hook is not None:
            _Kutu.hook()
        return _Kutu.cevap


class _Dosyalar:
    acik = ([], None)
    klasor = ''
    tek = ('', None)
    kayitlar = []

    @staticmethod
    def getOpenFileNames(*a, **k):
        _Dosyalar.kayitlar.append(('cok', a))
        return _Dosyalar.acik

    @staticmethod
    def getExistingDirectory(*a, **k):
        _Dosyalar.kayitlar.append(('dir', a))
        return _Dosyalar.klasor

    @staticmethod
    def getOpenFileName(*a, **k):
        _Dosyalar.kayitlar.append(('tek', a))
        return _Dosyalar.tek


class _SahteIsci(QObject):
    finished_ok = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)
    finished = Signal()
    log = Signal(str)

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.args = args
        self.kwargs = kwargs
        self.job_name = ''
        self.cancel_calls = 0
        self.iptal = False

    def cancel(self):
        self.cancel_calls += 1
        self.iptal = True

    def isInterruptionRequested(self):
        return self.iptal

    def check_cancel(self):
        if self.iptal:
            raise CancelledError('kullanıcı durdurdu')


class _Diyalog(QWidget):
    """QDialog sahtesi: gercek QWidget gibi davranir, exec kaydeder."""

    kayitlar = []

    def __init__(self, parent=None):
        super().__init__(parent)

    def reject(self):
        self.reddedildi = True

    def exec(self):
        _Diyalog.kayitlar.append(self)
        return 0


class _Url:
    def __init__(self, local=True, yol='C:/x.apk'):
        self._local = local
        self.yol = yol

    def isLocalFile(self):
        return self._local

    def toLocalFile(self):
        return self.yol


class _Mime:
    def __init__(self, urls):
        self._urls = urls

    def hasUrls(self):
        return bool(self._urls)

    def urls(self):
        return self._urls


class _Olay:
    def __init__(self, mime):
        self._mime = mime
        self.kabul = False
        self.yok = False

    def mimeData(self):
        return self._mime

    def acceptProposedAction(self):
        self.kabul = True

    def ignore(self):
        self.yok = True


def _oge(**kw):
    oge = {
        'id': 'x1',
        'name': 'X Uygulama',
        'category': 'Medya & Video',
        'badge': 'Test',
        'icon': '▶',
        'package': 'com.x.one',
        'author': 'X',
        'description': 'Açıklama',
        'url': 'https://x.example/a.apk',
        'website': 'https://x.example',
        'alt_packages': [],
    }
    oge.update(kw)
    return oge


def _katalog_yamala(monkeypatch, items):
    kayit = []

    def sahte(category=None, search=None):
        kayit.append((category, search))
        out = list(items)
        if category and category != 'Tümü':
            out = [o for o in out if o['category'] == category]
        if search:
            s = search.lower()
            out = [o for o in out if s in o['name'].lower()]
        return out

    monkeypatch.setattr(install_mod, 'get_catalog', sahte)
    return kayit


def _dugme_metinleri(cell):
    return [cell.layout().itemAt(i).widget().text() for i in range(cell.layout().count())]


def _sifirla():
    _Kutu.kayitlar = []
    _Kutu.cevap = _Kutu.No
    _Kutu.tiklama = None
    _Kutu.hook = None
    _Kutu.exec_hook = None
    _Kutu.son_ornek = None
    _Dosyalar.kayitlar = []
    _Dosyalar.acik = ([], None)
    _Dosyalar.tek = ('', None)
    _Dosyalar.klasor = ''
    _Diyalog.kayitlar = []


@pytest.fixture
def kurulum(qtbot, monkeypatch):
    _sifirla()
    core = _Cekirdek()
    win = _Pencere()
    monkeypatch.setattr(install_mod, 'Worker', _SahteIsci)
    monkeypatch.setattr(install_mod, 'QMessageBox', _Kutu)
    monkeypatch.setattr(install_mod, 'QFileDialog', _Dosyalar)
    tab = InstallTab(core, win)
    qtbot.addWidget(tab)
    return tab, core, win


# --- kurulum ve katalog tablosu ---


def test_kurulum_yapisi(kurulum):
    tab, core, win = kurulum
    assert tab.subtabs.count() == 3
    assert [tab.subtabs.tabText(i) for i in range(3)] == [
        '🌟 Popüler TV Uygulamaları',
        '📦 Yerel APK ve ana ekran',
        '⌨ Gelişmiş Komut Konsolu',
    ]
    assert tab.table_catalog.columnCount() == 6
    assert tab.table_catalog.rowCount() == len(get_catalog())
    assert tab.chk_reinstall.isChecked() is True
    assert tab.chk_grant_perms.isChecked() is True
    assert tab.btn_retry_failed.isEnabled() is False
    assert tab.lbl_queue.text() == 'Kuyruk: 0'
    assert tab.lbl_meta.isHidden() is True
    assert tab.lbl_inst.isHidden() is True
    assert tab.lbl_catalog_status.text() == (
        'Hazır. İstediğiniz popüler TV uygulamasını tek tıkla indirip TV’nize yükleyin.')
    assert len(win.runs) == 1
    w, desc = win.runs[0]
    assert desc == 'Katalog: kurulu TV uygulamaları taranıyor'
    assert w.job_name == 'TV Uygulama Durumu'
    motor = core._engine
    assert motor.calls == []
    motor.paketler = ['org.smarttube.stable']
    sonuc = w.args[0]()
    assert sonuc == {'org.smarttube.stable'}
    w.finished_ok.emit(sonuc)
    assert tab._installed_pkgs == {'org.smarttube.stable'}
    assert tab._catalog_status_known is True
    assert 'TV’de kurulu: 1' in tab.lbl_catalog_summary.text()
    row = next(r for r in range(tab.table_catalog.rowCount())
               if tab.table_catalog.item(r, 0).data(Qt.UserRole)['package'] == 'org.smarttube.stable')
    assert tab.table_catalog.item(row, 4).text() == "✓ TV'de Kurulu"


def test_kurulum_sinyalsiz(monkeypatch, qtbot):
    _sifirla()
    core = SimpleNamespace(connected=False, target=None, engine=_Motor(), config=_Yapilandirma())
    win = _Pencere()
    monkeypatch.setattr(install_mod, 'Worker', _SahteIsci)
    monkeypatch.setattr(install_mod, 'QMessageBox', _Kutu)
    monkeypatch.setattr(install_mod, 'QFileDialog', _Dosyalar)
    tab = InstallTab(core, win)
    qtbot.addWidget(tab)
    assert win.runs == []
    assert tab.table_catalog.rowCount() == len(get_catalog())


def test_katalog_filtreleri(kurulum):
    tab, _core, _win = kurulum
    tab.cmb_catalog_cat.setCurrentIndex(tab.cmb_catalog_cat.findText('TV Mağazası'))
    assert tab.table_catalog.rowCount() == len(get_catalog(category='TV Mağazası'))
    tab.cmb_catalog_cat.setCurrentIndex(tab.cmb_catalog_cat.findText('Tümü'))
    tab.txt_catalog_search.setText('kodi')
    beklenen = get_catalog(search='kodi')
    assert len(beklenen) >= 1
    assert tab.table_catalog.rowCount() == len(beklenen)
    adlar = [tab.table_catalog.item(r, 0).text() for r in range(tab.table_catalog.rowCount())]
    assert any('Kodi' in ad for ad in adlar)
    tab.btn_catalog_reset.click()
    assert tab.cmb_catalog_cat.currentText() == 'Tümü'
    assert tab.txt_catalog_search.text() == ''
    assert tab.table_catalog.rowCount() == len(get_catalog())
    tab.txt_catalog_search.setText('zzz-yok')
    assert tab.table_catalog.rowCount() == 0
    assert tab.lbl_catalog_summary.text() == 'Aramayla eşleşen uygulama yok.'
    assert tab.table_catalog.empty_title == 'Eşleşen uygulama yok'


def test_katalog_tablo_durumlari(kurulum, monkeypatch):
    tab, core, _win = kurulum
    _katalog_yamala(monkeypatch, [
        _oge(),
        _oge(id='x2', name='Store Uygulama', package='com.s.one', type='store'),
    ])
    core.connected = False
    tab._populate_catalog_table()
    assert tab.table_catalog.item(0, 4).text() == 'Bağlantı yok'
    assert tab.lbl_catalog_summary.text() == (
        'Filtrede 2 uygulama · Kurulum durumunu görmek için TV’ye bağlanın.')
    core.connected = True
    tab._catalog_status_known = False
    tab._catalog_status_error_target = None
    tab._populate_catalog_table()
    assert tab.table_catalog.item(0, 4).text() == 'Kontrol bekleniyor'
    assert tab.table_catalog.item(0, 4).toolTip() == 'Kontrol bekleniyor'
    assert tab.lbl_catalog_summary.text() == 'Filtrede 2 uygulama · Kurulum durumu kontrol bekliyor.'
    tab._catalog_status_error_target = 'tv-1'
    tab._populate_catalog_table()
    assert tab.table_catalog.item(0, 4).text() == 'Kontrol başarısız'
    assert 'sorgulanamadı' in tab.table_catalog.item(0, 4).toolTip()
    assert 'Yeni kurulum durumu sorgulanamadı' in tab.lbl_catalog_summary.text()
    assert '“Kurulum Durumunu Güncelle” ile yeniden deneyin.' in tab.lbl_catalog_summary.text()
    tab._catalog_status_error_target = None
    tab._catalog_status_known = True
    tab._catalog_status_target = 'tv-1'
    tab._installed_pkgs = {'com.x.one'}
    tab._populate_catalog_table()
    assert tab.table_catalog.item(0, 4).text() == "✓ TV'de Kurulu"
    assert tab.table_catalog.item(1, 4).text() == 'Kurulu Değil'
    assert tab.lbl_catalog_summary.text() == 'Filtrede 2 uygulama · TV’de kurulu: 1'
    # kolon 0 verisi sözlük; tooltip alanları dolu
    item = tab.table_catalog.item(0, 0).data(Qt.UserRole)
    assert item['id'] == 'x1'
    assert 'Geliştirici: X' in tab.table_catalog.item(0, 0).toolTip()
    assert 'Web: https://x.example' in tab.table_catalog.item(0, 0).toolTip()
    assert tab.table_catalog.item(0, 1).text() == 'Medya & Video · Test'
    assert tab.table_catalog.item(0, 3).text() == 'X'


def test_katalog_satir_eylemleri(kurulum, monkeypatch):
    tab, _core, _win = kurulum
    _katalog_yamala(monkeypatch, [
        _oge(),
        _oge(id='x2', name='Store Uygulama', package='com.s.one', type='store'),
    ])
    cagrilar = []
    monkeypatch.setattr(tab, '_launch_catalog_app', lambda it: cagrilar.append(('launch', it['id'])))
    monkeypatch.setattr(tab, '_open_catalog_store', lambda it: cagrilar.append(('store', it['id'])))
    monkeypatch.setattr(tab, '_install_catalog_app',
                        lambda it, require_installed=False: cagrilar.append(('install', it['id'], require_installed)))
    tab._catalog_status_known = True
    tab._catalog_status_target = 'tv-1'
    tab._installed_pkgs = {'com.x.one'}

    def tikla(row, metin):
        cell = tab.table_catalog.cellWidget(row, 5)
        for i in range(cell.layout().count()):
            b = cell.layout().itemAt(i).widget()
            if b.text() == metin:
                b.click()
                return
        raise AssertionError('düğme yok: ' + metin)

    tab._populate_catalog_table()
    assert _dugme_metinleri(tab.table_catalog.cellWidget(0, 5)) == ["TV'de Aç", 'Yeniden Kur']
    assert _dugme_metinleri(tab.table_catalog.cellWidget(1, 5)) == ["Play Store'da Aç"]
    tikla(0, "TV'de Aç")
    tikla(0, 'Yeniden Kur')
    tikla(1, "Play Store'da Aç")
    tab._installed_pkgs = set()
    tab._populate_catalog_table()
    assert _dugme_metinleri(tab.table_catalog.cellWidget(0, 5)) == ["İndir ve TV'ye Kur"]
    tikla(0, "İndir ve TV'ye Kur")
    tab._installed_pkgs = {'com.s.one'}
    tab._populate_catalog_table()
    assert _dugme_metinleri(tab.table_catalog.cellWidget(1, 5)) == ["TV'de Aç", 'Mağazada Aç']
    tikla(1, 'Mağazada Aç')
    assert cagrilar == [
        ('launch', 'x1'),
        ('install', 'x1', True),
        ('store', 'x2'),
        ('install', 'x1', False),
        ('store', 'x2'),
    ]


def test_katalog_dugmeleri_kilit(kurulum, monkeypatch):
    tab, _core, win = kurulum
    _katalog_yamala(monkeypatch, [_oge()])

    def kilitli_mi():
        cell = tab.table_catalog.cellWidget(0, 5)
        return all(not cell.layout().itemAt(i).widget().isEnabled()
                   for i in range(cell.layout().count()))

    tab._populate_catalog_table()
    assert kilitli_mi() is False
    win._connection_busy = True
    tab._populate_catalog_table()
    assert kilitli_mi() is True
    win._connection_busy = False
    tab._installing = True
    tab._populate_catalog_table()
    assert kilitli_mi() is True
    tab._installing = False
    tab._catalog_worker = object()
    tab._populate_catalog_table()
    assert kilitli_mi() is True
    tab._catalog_worker = None


def test_katalog_detay_diyalogu(kurulum, monkeypatch):
    tab, _core, _win = kurulum
    _katalog_yamala(monkeypatch, [_oge(description='Uzun açıklama', website='https://a.b')])
    monkeypatch.setattr(install_mod, 'QDialog', _Diyalog)
    tab._populate_catalog_table()
    tab._show_catalog_details(SimpleNamespace(row=lambda: 0))
    assert len(_Diyalog.kayitlar) == 1
    dlg = _Diyalog.kayitlar[-1]
    assert dlg.windowTitle() == 'Uygulama Ayrıntıları — X Uygulama'
    assert dlg.accessibleName() == 'Uygulama ayrıntıları: X Uygulama'
    metin = dlg.findChild(QPlainTextEdit).toPlainText()
    assert 'Açıklama:\nUzun açıklama' in metin
    assert 'Kategori: Medya & Video' in metin
    assert 'Rozet: Test' in metin
    assert 'Geliştirici: X' in metin
    assert 'Resmî web sitesi: https://a.b' in metin
    # sözlük olmayan veri sessizce döner
    tab.table_catalog.item(0, 0).setData(Qt.UserRole, 'x')
    tab._show_catalog_details(SimpleNamespace(row=lambda: 0))
    assert len(_Diyalog.kayitlar) == 1
    # boş alanlar varsayılana düşer
    _katalog_yamala(monkeypatch, [{'id': 'y', 'name': 'Y', 'category': '', 'badge': '',
                                   'icon': '•', 'package': 'com.y', 'author': '',
                                   'description': '', 'url': 'https://y/a.apk', 'website': ''}])
    tab._populate_catalog_table()
    tab._show_catalog_details(SimpleNamespace(row=lambda: 0))
    metin = _Diyalog.kayitlar[-1].findChild(QPlainTextEdit).toPlainText()
    assert 'Açıklama:\nBelirtilmemiş' in metin
    assert 'Kategori: Belirtilmemiş' in metin
    assert 'Rozet: Belirtilmemiş' in metin
    assert 'Geliştirici: Belirtilmemiş' in metin
    assert 'Resmî web sitesi: Belirtilmemiş' in metin


# --- kuyruk ---


def test_kuyruk_ekleme(kurulum, tmp_path):
    tab, core, _win = kurulum
    motor = core._engine
    apk = tmp_path / 'uygulama.apk'
    apk.write_bytes(b'x')
    ek = tmp_path / 'paket.apks'
    ek.write_bytes(b'x')
    gecersiz = tmp_path / 'notlar.txt'
    gecersiz.write_text('x')
    bos_dizin = tmp_path / 'bos'
    bos_dizin.mkdir()
    dolu_dizin = tmp_path / 'split'
    dolu_dizin.mkdir()
    (dolu_dizin / 'base.apk').write_bytes(b'x')
    motor.meta[str(apk)] = {'label': 'Uygulama', 'version_name': '1.0'}

    eklendi, red = tab._add_paths(['', str(gecersiz), str(tmp_path / 'yok.apk'), str(bos_dizin)])
    assert (eklendi, red) == (0, 4)
    assert tab.lbl_inst.text() == '0 eklendi, 4 geçersiz öğe atlandı.'
    assert tab.lbl_inst.isHidden() is False

    eklendi, red = tab._add_paths([str(apk), str(ek), str(dolu_dizin)])
    assert (eklendi, red) == (3, 0)
    assert tab.lbl_inst.text() == '3 eklendi.'
    assert tab.lbl_queue.text() == ('Kuyruk: 3  ·  Bekliyor: 3  ·  Kuruluyor: 0  ·  '
                                    'Kuruldu: 0  ·  Başarısız: 0  ·  İptal: 0')

    # yinelenen yol ne eklenir ne reddedilir
    assert tab._add_paths([str(apk), str(apk)]) == (0, 0)
    assert tab.lst.count() == 3

    metinler = [tab.lst.item(i).text() for i in range(tab.lst.count())]
    assert metinler[0] == 'Uygulama v1.0 (uygulama.apk)  —  Bekliyor'
    assert metinler[1] == 'paket.apks  —  Bekliyor'
    assert metinler[2] == 'split  —  Bekliyor'
    assert tab.lst.item(0).data(Qt.UserRole) == str(apk)
    assert tab.lst.item(0).toolTip() == str(apk)
    assert tab.lbl_apk_empty.isHidden() is True

    # kurulum sürerken ekleme yok sayılır
    tab._installing = True
    assert tab._add_paths([str(apk)]) == (0, 1)
    tab._installing = False


def test_kuyruk_secim_ve_meta(kurulum, tmp_path):
    tab, core, _win = kurulum
    motor = core._engine
    apk = tmp_path / 'a.apk'
    apk.write_bytes(b'x')
    motor.meta[str(apk)] = {
        'package': 'com.a.one', 'label': 'Bir <Uygulama>', 'version_name': '2.0',
        'version_code': '20', 'min_sdk': '21'}
    tab._add_paths([str(apk)])
    tab.lst.setCurrentRow(0)
    tab._on_queue_selection_changed()
    assert tab.lbl_meta.isHidden() is False
    metin = tab.lbl_meta.text()
    assert 'com.a.one' in metin
    assert 'v2.0 (20)' in metin
    assert 'Min SDK: 21' in metin
    assert 'Bir &lt;Uygulama&gt;' in metin
    # paket alanı olmayan meta gizler
    motor.meta[str(apk)] = {'label': 'X'}
    tab._meta_cache.clear()
    tab._on_queue_selection_changed()
    assert tab.lbl_meta.isHidden() is True
    # okuma hatası boş önbelleğe yazılır ve gizler
    motor.meta_patlak = True
    tab._meta_cache.clear()
    tab._on_queue_selection_changed()
    assert tab.lbl_meta.isHidden() is True
    assert tab._meta_cache[str(apk)] == {}
    # seçim yokken gizler
    tab.lst.clearSelection()
    tab._on_queue_selection_changed()
    assert tab.lbl_meta.isHidden() is True


def test_kuyruk_ozeti_ve_durum_metinleri(kurulum, tmp_path):
    tab, _core, _win = kurulum
    tab._refresh_queue_summary()
    assert tab.lbl_queue.text() == 'Kuyruk: 0'
    apk = tmp_path / 'a.apk'
    apk.write_bytes(b'x')
    tab._add_paths([str(apk)])
    key = tab._path_key(str(apk))
    tab._statuses[key] = 'bilinmeyen'
    tab._refresh_queue_summary()
    assert tab.lbl_queue.text() == ('Kuyruk: 1  ·  Bekliyor: 0  ·  Kuruluyor: 0  ·  '
                                    'Kuruldu: 0  ·  Başarısız: 0  ·  İptal: 0')
    tab._statuses[key] = 'success'
    tab._refresh_list()
    assert tab.lst.item(0).text().endswith('Kuruldu')
    assert 'Kuruldu: 1' in tab.lbl_queue.text()
    assert tab._path_key(str(apk)) == tab._path_key(str(apk))
    for durum, metin in (('queued', 'Bekliyor'), ('installing', 'Kuruluyor'),
                         ('success', 'Kuruldu'), ('failed', 'Başarısız'),
                         ('cancelled', 'İptal edildi'), ('x', 'x')):
        assert tab._status_text(durum) == metin


def test_kuyruk_cikarma(kurulum, tmp_path):
    tab, _core, _win = kurulum
    a = tmp_path / 'a.apk'
    a.write_bytes(b'x')
    b = tmp_path / 'b.apk'
    b.write_bytes(b'x')
    tab._add_paths([str(a), str(b)])
    tab.lst.setCurrentRow(0)
    tab._remove_sel()
    assert tab._files == [str(b)]
    assert tab._statuses.get(tab._path_key(str(a))) is None
    # kurulum sürerken çıkarma yok
    tab._installing = True
    tab._remove_sel()
    assert tab._files == [str(b)]
    tab._installing = False
    # listedeki yol kuyrukta değilse atlanır
    tab._files.pop()
    tab.lst.setCurrentRow(1)
    tab._remove_sel()
    assert tab._files == []
    assert tab.lst.count() == 0


def test_dosya_diyaloglari(kurulum, tmp_path):
    tab, _core, _win = kurulum
    a = tmp_path / 'a.apk'
    a.write_bytes(b'x')
    d = tmp_path / 'split'
    d.mkdir()
    (d / 'x.apk').write_bytes(b'x')
    _Dosyalar.acik = ([str(a)], 'APK')
    tab._add_files()
    assert tab._files == [str(a)]
    assert _Dosyalar.kayitlar[-1][0] == 'cok'
    _Dosyalar.klasor = str(d)
    tab._add_dir()
    assert tab.lst.count() == 2
    assert _Dosyalar.kayitlar[-1][0] == 'dir'
    # boş seçim eklemez
    _Dosyalar.klasor = ''
    tab._add_dir()
    assert tab.lst.count() == 2
    # kurulum sürerken diyalog açılmaz
    _Dosyalar.kayitlar = []
    tab._installing = True
    tab._add_files()
    tab._add_dir()
    assert _Dosyalar.kayitlar == []
    tab._installing = False


def test_retry_failed(kurulum, monkeypatch, tmp_path):
    tab, _core, _win = kurulum
    a = tmp_path / 'a.apk'
    a.write_bytes(b'x')
    b = tmp_path / 'b.apk'
    b.write_bytes(b'x')
    tab._add_paths([str(a), str(b)])
    tab._statuses[tab._path_key(str(b))] = 'failed'
    tab._refresh_list()
    assert tab._failed_queue_files() == (str(b),)
    assert tab.btn_retry_failed.isEnabled() is True
    # dosya silinirse uygun değil
    b.unlink()
    tab._update_retry_failed_enabled()
    assert tab._failed_queue_files() == ()
    assert tab.btn_retry_failed.isEnabled() is False
    # yeniden denenecek dosya yok mesajı
    mesaj_oncesi = len(_Kutu.kayitlar)
    tab._retry_failed()
    assert len(_Kutu.kayitlar) == mesaj_oncesi
    assert 'Yeniden denenecek başarısız paket yok' in tab.lbl_inst.text()
    # klasör (split) uygun sayılır
    diz = tmp_path / 'split'
    diz.mkdir()
    (diz / 'base.apk').write_bytes(b'x')
    tab._add_paths([str(diz)])
    tab._statuses[tab._path_key(str(diz))] = 'failed'
    b.write_bytes(b'x')
    tab._statuses[tab._path_key(str(b))] = 'failed'
    tab._update_retry_failed_enabled()
    assert tab.btn_retry_failed.isEnabled() is True
    assert tab._failed_queue_files() == (str(b), str(diz))
    baslat = []
    monkeypatch.setattr(tab, '_start_install', lambda *a, **k: baslat.append((a, k)))
    tab._retry_failed()
    assert baslat == [((tuple([str(b), str(diz)]), 'batch'), {})]
    # kurulum işçisi varken yok sayılır
    tab._catalog_worker = object()
    tab._retry_failed()
    assert len(baslat) == 1
    tab._catalog_worker = None
    tab._installing = True
    tab._retry_failed()
    assert len(baslat) == 1
    tab._installing = False
    # düğme kilidi
    tab._catalog_worker = object()
    tab._update_retry_failed_enabled()
    assert tab.btn_retry_failed.isEnabled() is False
    tab._catalog_worker = None
    tab._update_retry_failed_enabled()
    assert tab.btn_retry_failed.isEnabled() is True


def test_install_all_kapilari(kurulum, monkeypatch, tmp_path):
    tab, _core, win = kurulum
    baslat = []
    monkeypatch.setattr(tab, '_start_install', lambda *a, **k: baslat.append((a, k)))
    tab._install_all()
    assert _Kutu.kayitlar[-1] == ('info', 'Kurulum', 'Önce APK ekleyin.')
    win._connection_busy = True
    tab._install_all()
    assert tab.lbl_inst.text() == 'Bağlantı işlemi sürüyor; tamamlanınca kurulumu başlatın.'
    win._connection_busy = False
    a = tmp_path / 'a.apk'
    a.write_bytes(b'x')
    tab._add_paths([str(a)])
    tab._install_all()
    assert baslat[-1][0] == ((str(a),), 'batch')
    tab._installing = True
    tab._install_all()
    assert len(baslat) == 1
    tab._installing = False
    tab._catalog_worker = object()
    tab._install_all()
    assert len(baslat) == 1
    tab._catalog_worker = None


def test_install_single_kapilari(kurulum, monkeypatch, tmp_path):
    tab, core, win = kurulum
    baslat = []
    monkeypatch.setattr(tab, '_start_install', lambda *a, **k: baslat.append((a, k)))
    tab._installing = True
    tab._install_single()
    assert baslat == []
    tab._installing = False
    core.connected = False
    tab._install_single()
    assert tab.lbl_inst.text() == 'Kurulum için önce cihaza bağlanın.'
    assert _Kutu.kayitlar[-1] == ('info', 'Kurulum', 'Kurulumdan önce cihaza bağlanın.')
    core.connected = True
    _Dosyalar.tek = ('', '')
    tab._install_single()
    assert baslat == []
    metin = tmp_path / 'x.txt'
    metin.write_text('x')
    _Dosyalar.tek = (str(metin), 'APK')
    tab._install_single()
    assert tab.lbl_inst.text() == 'Geçerli bir APK dosyası seçin.'
    apk = tmp_path / 'a.apk'
    apk.write_bytes(b'x')
    _Dosyalar.tek = (str(apk), 'APK')
    tab._install_single()
    ((files, mode, target, gen), _k) = baslat[-1]
    assert files == (str(apk),)
    assert mode == 'single'
    assert target == 'tv-1'
    assert gen == tab._connection_generation
    # bağlantı meşgul
    win._connection_busy = True
    once = len(baslat)
    tab._install_single()
    assert len(baslat) == once
    assert tab.lbl_inst.text() == 'Bağlantı işlemi sürüyor; tamamlanınca kurulumu başlatın.'
    win._connection_busy = False
    # bekleyen işçi
    tab._catalog_worker = object()
    tab._install_single()
    assert len(baslat) == once
    tab._catalog_worker = None


# --- kurulum akışları ---


def test_start_install_kapilari(kurulum, tmp_path):
    tab, core, win = kurulum
    a = tmp_path / 'a.apk'
    a.write_bytes(b'x')
    once = len(win.runs)
    tab._start_install((str(a),), 'batch', 'tv-9', tab._connection_generation)
    assert tab.lbl_inst.text() == 'Hedef veya bağlantı değişti. Kurulumu yeniden başlatın.'
    assert _Kutu.kayitlar[-1] == ('info', 'Kurulum', 'Hedef veya bağlantı değişti; kurulum başlatılmadı.')
    tab._start_install((str(a),), 'batch', 'tv-1', tab._connection_generation + 1)
    assert _Kutu.kayitlar[-1][0] == 'info'
    core.connected = False
    tab._start_install((str(a),), 'batch')
    assert _Kutu.kayitlar[-1] == ('info', 'Kurulum', 'Kurulumdan önce cihaza bağlanın.')
    core.connected = True
    _Kutu.cevap = _Kutu.No
    tab._start_install((str(a),), 'batch')
    assert _Kutu.kayitlar[-1][0] == 'soru'
    assert _Kutu.kayitlar[-1][1] == 'Onay — Kuyruktakileri Kur'
    assert len(win.runs) == once
    _Kutu.cevap = _Kutu.Yes
    win._closing = True
    tab._start_install((str(a),), 'batch')
    assert _Kutu.kayitlar[-1] == ('info', 'Kurulum', 'Hedef veya bağlantı değişti; kurulum başlatılmadı.')
    win._closing = False
    win._connection_busy = True
    tab._start_install((str(a),), 'batch')
    assert tab.lbl_inst.text() == 'Bağlantı işlemi sürüyor; tamamlanınca kurulumu başlatın.'
    win._connection_busy = False
    tab._installing = True
    tab._start_install((str(a),), 'batch')
    tab._installing = False
    tab._catalog_worker = object()
    tab._start_install((str(a),), 'batch')
    tab._catalog_worker = None
    core.engine_patlak = True
    tab._start_install((str(a),), 'batch')
    assert tab.lbl_inst.text() == 'ADB motoru açılamadı: motor yok'
    core.engine_patlak = False
    assert len(win.runs) == once


def test_start_install_kalabalik_kuyruk(kurulum, tmp_path):
    tab, _core, _win = kurulum
    dosyalar = []
    for i in range(9):
        p = tmp_path / 'p{}.apk'.format(i)
        p.write_bytes(b'x')
        dosyalar.append(str(p))
    _Kutu.cevap = _Kutu.No
    tab._start_install(tuple(dosyalar), 'batch')
    metin = _Kutu.kayitlar[-1][2]
    assert '9 kuyruk paketi kurulsun mu?' in metin
    assert '… ve 1 tane daha' in metin


def test_start_install_akisi(kurulum, monkeypatch, tmp_path):
    tab, core, win = kurulum
    motor = core._engine
    a = tmp_path / 'a.apk'
    a.write_bytes(b'x')
    b = tmp_path / 'b.apks'
    b.write_bytes(b'x')
    monkeypatch.setattr(snapshot_mod, 'take', lambda engine, target: ('snap-1', 7))
    _Kutu.cevap = _Kutu.Yes
    win.runs.clear()
    tab._start_install((str(a), str(b)), 'batch')
    assert _Kutu.kayitlar[-1] == (
        'soru', 'Onay — Kuyruktakileri Kur',
        '2 kuyruk paketi kurulsun mu?\n\n• a.apk\n• b.apks')
    w, desc = win.runs[-1]
    assert desc == 'Kurulum: kuyruktaki 2 paket kuruluyor'
    assert w.job_name == 'APK kuyruk kurulumu'
    assert tab._installing is True
    assert tab.btn_install.isEnabled() is False
    assert tab.lbl_inst.text() == 'Kuyruk kurulumu hazırlanıyor…'
    assert tab._statuses[tab._path_key(str(a))] == 'queued'
    res = w.args[0]()
    assert res['successes'] == [str(a), str(b)]
    assert res['failures'] == []
    assert res['snap'] == 'snap-1'
    assert res['cancelled'] is False
    assert motor.calls[0][:3] == ('install_apk', 'tv-1', str(a))
    assert motor.calls[0][3]['reinstall'] is True
    assert motor.calls[0][3]['grant_perms'] is True
    assert motor.calls[0][3]['allow_downgrade'] is False
    assert any(c[:3] == ('install_multiple', 'tv-1', str(b)) for c in motor.calls)
    assert ('invalidate_pkg_cache', 'tv-1') in motor.calls
    w.finished_ok.emit(res)
    assert tab._install_result is res
    win.tab_apps.refresh_sayaci = 0
    w.finished.emit()
    assert tab._installing is False
    assert tab.btn_install.isEnabled() is True
    assert win.tab_apps.refresh_sayaci == 1
    kutu = _Kutu.kayitlar[-1]
    assert kutu[0] == 'info'
    assert 'Kuyruk sonucu: 2 kuruldu, 0 başarısız.' in kutu[2]
    assert 'Paket durumu snapshot’ı: snap-1 (uygulama verileri yedeklenmez).' in kutu[2]
    assert '+ a.apk' in kutu[2]
    assert tab.lbl_inst.text() == kutu[2]
    assert win.runs[-1][1] == 'Katalog: kurulu TV uygulamaları taranıyor'


def test_start_install_tek_apk(kurulum, monkeypatch, tmp_path):
    tab, _core, win = kurulum
    a = tmp_path / 'a.apk'
    a.write_bytes(b'x')
    monkeypatch.setattr(snapshot_mod, 'take', lambda engine, target: ('snap-2', 3))
    _Kutu.cevap = _Kutu.Yes
    win.runs.clear()
    tab._start_install((str(a),), 'single')
    assert _Kutu.kayitlar[-1] == (
        'soru', 'Onay — Tek APK Kur', 'Bu APK kurulsun mu?\n\n• a.apk')
    w, desc = win.runs[-1]
    assert desc == 'Kurulum: tek APK kuruluyor: a.apk'
    assert w.job_name == 'Tek APK kurma'
    assert tab.lbl_inst.text() == 'Tek APK kurulumu hazırlanıyor…'
    res = w.args[0]()
    assert res['mode'] == 'single'
    w.finished_ok.emit(res)
    win.tab_apps.refresh_sayaci = 0
    w.finished.emit()
    assert win.tab_apps.refresh_sayaci == 1
    assert 'Tek APK kuruldu: a.apk' in tab.lbl_inst.text()


def _prepare_orphan_recovery(tab, motor, path, answer=_Kutu.Yes):
    motor.varsayilan_meta = {'package': 'ar.tvplayer.tv'}
    state = {'attempts': 0, 'checks': 0, 'uninstalls': [], 'answer': answer}

    def install(target, apk_path):
        state['attempts'] += 1
        if state['attempts'] == 1:
            return RuntimeError('Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]')
        return None

    def orphan_check(target, package, cancel_check=None):
        state['checks'] += 1
        if cancel_check is not None:
            cancel_check()
        return True

    def uninstall(target, package, cancel_check=None):
        if cancel_check is not None:
            cancel_check()
        state['uninstalls'].append((target, package))

    motor.install_apk_hook = install
    motor.is_orphaned_package_registration = orphan_check
    motor.uninstall_package_full = uninstall
    _Kutu.cevap = _Kutu.Yes

    def answer_dialog():
        if _Kutu.kayitlar[-1][1] == 'Kayıtlı Paket Çakışması':
            _Kutu.cevap = state['answer']

    _Kutu.hook = answer_dialog
    return state


def test_single_install_orphan_refusal_keeps_package_and_data(kurulum, tmp_path):
    tab, core, win = kurulum
    path = tmp_path / 'orphan.apk'
    path.write_bytes(b'x')
    state = _prepare_orphan_recovery(tab, core._engine, path, _Kutu.No)
    win.runs.clear()

    tab._start_install((str(path),), 'single')
    worker = win.runs[-1][0]
    result = worker.args[0]()

    assert result['successes'] == []
    assert result['failures'] == [str(path)]
    assert state['attempts'] == 1
    assert state['checks'] == 1
    assert state['uninstalls'] == []
    prompt = next(row for row in _Kutu.kayitlar
                  if row[1] == 'Kayıtlı Paket Çakışması')
    assert 'tüm uygulama verilerini' in prompt[2]
    assert _Kutu.cevap == _Kutu.No


def test_single_install_does_not_offer_repair_for_protected_package(kurulum, tmp_path):
    tab, core, win = kurulum
    path = tmp_path / 'protected.apk'
    path.write_bytes(b'x')
    state = _prepare_orphan_recovery(tab, core._engine, path)
    core.config.protected = ['ar.tvplayer.tv']
    win.runs.clear()

    tab._start_install((str(path),), 'single')
    result = win.runs[-1][0].args[0]()

    assert result['failures'] == [str(path)]
    assert state['attempts'] == 1
    assert state['checks'] == 0
    assert state['uninstalls'] == []
    assert all(row[1] != 'Kayıtlı Paket Çakışması' for row in _Kutu.kayitlar)


def test_single_install_rechecks_protection_after_user_consent(kurulum, tmp_path):
    tab, core, win = kurulum
    path = tmp_path / 'protected-after-consent.apk'
    path.write_bytes(b'x')
    state = _prepare_orphan_recovery(tab, core._engine, path)

    def protect_after_prompt():
        if _Kutu.kayitlar[-1][1] == 'Kayıtlı Paket Çakışması':
            core.config.protected = ['ar.tvplayer.tv']

    _Kutu.hook = protect_after_prompt
    win.runs.clear()

    tab._start_install((str(path),), 'single')
    result = win.runs[-1][0].args[0]()

    assert result['failures'] == [str(path)]
    assert state['checks'] == 1
    assert state['attempts'] == 1
    assert state['uninstalls'] == []
    assert any(row[1] == 'Kayıtlı Paket Çakışması' for row in _Kutu.kayitlar)


def test_single_install_non_orphan_does_not_prompt_or_remove(kurulum, tmp_path):
    tab, core, win = kurulum
    path = tmp_path / 'normal.apk'
    path.write_bytes(b'x')
    state = _prepare_orphan_recovery(tab, core._engine, path)
    core._engine.is_orphaned_package_registration = lambda *a, **k: False
    win.runs.clear()

    tab._start_install((str(path),), 'single')
    worker = win.runs[-1][0]
    result = worker.args[0]()

    assert result['failures'] == [str(path)]
    assert state['attempts'] == 1
    assert state['uninstalls'] == []
    assert all(row[1] != 'Kayıtlı Paket Çakışması' for row in _Kutu.kayitlar)


def test_single_install_true_orphan_rechecks_after_consent_then_retries(kurulum, tmp_path):
    tab, core, win = kurulum
    path = tmp_path / 'orphan.apk'
    path.write_bytes(b'x')
    state = _prepare_orphan_recovery(tab, core._engine, path)
    win.runs.clear()

    tab._start_install((str(path),), 'single')
    worker = win.runs[-1][0]
    result = worker.args[0]()

    assert result['successes'] == [str(path)]
    assert result['failures'] == []
    assert state['checks'] == 2
    assert state['attempts'] == 2
    assert state['uninstalls'] == [('tv-1', 'ar.tvplayer.tv')]
    assert any('yeniden denendi' in msg for msg in result['msgs'])


def test_single_install_refuses_if_registration_changes_after_consent(kurulum, tmp_path):
    tab, core, win = kurulum
    path = tmp_path / 'changed.apk'
    path.write_bytes(b'x')
    state = _prepare_orphan_recovery(tab, core._engine, path)

    def changed_after_consent(target, package, cancel_check=None):
        state['checks'] += 1
        if state['checks'] == 1:
            return True
        return False

    core._engine.is_orphaned_package_registration = changed_after_consent
    win.runs.clear()
    tab._start_install((str(path),), 'single')
    result = win.runs[-1][0].args[0]()

    assert result['failures'] == [str(path)]
    assert state['attempts'] == 1
    assert state['uninstalls'] == []
    assert state['checks'] == 2


def test_single_install_target_change_during_recheck_prevents_uninstall(kurulum, tmp_path):
    tab, core, win = kurulum
    path = tmp_path / 'target.apk'
    path.write_bytes(b'x')
    state = _prepare_orphan_recovery(tab, core._engine, path)

    def target_changes(target, package, cancel_check=None):
        state['checks'] += 1
        if state['checks'] == 1:
            return True
        core.target = 'tv-2'
        if cancel_check is not None:
            cancel_check()
        return True

    core._engine.is_orphaned_package_registration = target_changes
    win.runs.clear()
    tab._start_install((str(path),), 'single')
    result = win.runs[-1][0].args[0]()

    assert result['cancelled'] is True
    assert state['uninstalls'] == []
    core.target = 'tv-1'


def test_single_install_probe_error_never_prompts_or_removes(kurulum, tmp_path):
    tab, core, win = kurulum
    path = tmp_path / 'probe-error.apk'
    path.write_bytes(b'x')
    state = _prepare_orphan_recovery(tab, core._engine, path)

    def probe_error(*args, **kwargs):
        raise RuntimeError('probe failed')

    core._engine.is_orphaned_package_registration = probe_error
    win.runs.clear()
    tab._start_install((str(path),), 'single')
    result = win.runs[-1][0].args[0]()

    assert result['failures'] == [str(path)]
    assert state['uninstalls'] == []
    assert all(row[1] != 'Kayıtlı Paket Çakışması' for row in _Kutu.kayitlar)
    assert 'güvenli onarım yapılamadı' in result['msgs'][0]


def test_single_install_cancellation_during_failure_never_prompts(kurulum, tmp_path):
    tab, core, win = kurulum
    path = tmp_path / 'cancel.apk'
    path.write_bytes(b'x')
    state = _prepare_orphan_recovery(tab, core._engine, path)
    win.runs.clear()
    tab._start_install((str(path),), 'single')
    worker = win.runs[-1][0]

    def cancel_then_fail(target, apk_path):
        worker.cancel()
        return RuntimeError('Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]')

    core._engine.install_apk_hook = cancel_then_fail
    result = worker.args[0]()

    assert result['cancelled'] is True
    assert state['uninstalls'] == []
    assert all(row[1] != 'Kayıtlı Paket Çakışması' for row in _Kutu.kayitlar)


def test_single_install_retry_failure_is_attempted_once_and_reported(kurulum, tmp_path):
    tab, core, win = kurulum
    path = tmp_path / 'retry-fails.apk'
    path.write_bytes(b'x')
    state = _prepare_orphan_recovery(tab, core._engine, path)

    def both_fail(target, apk_path):
        state['attempts'] += 1
        return RuntimeError('INSTALL_FAILED_UPDATE_INCOMPATIBLE'
                            if state['attempts'] == 1 else 'retry failed')

    core._engine.install_apk_hook = both_fail
    win.runs.clear()
    tab._start_install((str(path),), 'single')
    result = win.runs[-1][0].args[0]()

    assert result['failures'] == [str(path)]
    assert state['attempts'] == 2
    assert state['uninstalls'] == [('tv-1', 'ar.tvplayer.tv')]
    assert 'retry failed' in result['msgs'][0]


def test_start_install_basarisizlik(kurulum, monkeypatch, tmp_path):
    tab, core, win = kurulum
    motor = core._engine
    a = tmp_path / 'a.apk'
    a.write_bytes(b'x')
    b = tmp_path / 'b.apk'
    b.write_bytes(b'x')
    tab._files = [str(a), str(b)]
    monkeypatch.setattr(snapshot_mod, 'take', lambda engine, target: ('snap', 2))
    motor.install_apk_hook = lambda target, path: RuntimeError('kurulamadi')
    _Kutu.cevap = _Kutu.Yes
    win.runs.clear()
    tab._start_install((str(a), str(b)), 'batch')
    w = win.runs[-1][0]
    res = w.args[0]()
    assert res['successes'] == []
    assert res['failures'] == [str(a), str(b)]
    assert res['msgs'] == ['X a.apk: kurulamadi', 'X b.apk: kurulamadi']
    motor.install_apk_hook = None
    w.finished_ok.emit(res)
    w.finished.emit()
    assert tab._statuses[tab._path_key(str(a))] == 'failed'
    assert tab._statuses[tab._path_key(str(b))] == 'failed'
    assert tab.btn_retry_failed.isEnabled() is True
    assert tab._files == [str(a), str(b)]
    assert 'Kuyruk sonucu: 0 kuruldu, 2 başarısız.' in tab.lbl_inst.text()


def test_start_install_iptaller(kurulum, monkeypatch, tmp_path):
    tab, core, win = kurulum
    motor = core._engine
    a = tmp_path / 'a.apk'
    a.write_bytes(b'x')
    b = tmp_path / 'b.apk'
    b.write_bytes(b'x')
    monkeypatch.setattr(snapshot_mod, 'take', lambda engine, target: ('snap', 2))
    _Kutu.cevap = _Kutu.Yes

    win.runs.clear()
    tab._start_install((str(a),), 'batch')
    w = win.runs[-1][0]
    w.cancel()
    res = w.args[0]()
    assert res['cancelled'] is True
    assert res['cancel_reason'] == 'Kullanıcı durdurdu.'
    w.finished_ok.emit(res)
    w.finished.emit()

    win.runs.clear()
    tab._start_install((str(a), str(b)), 'batch')
    w2 = win.runs[-1][0]
    motor.install_apk_hook = lambda target, path: w2.cancel()
    res = w2.args[0]()
    assert res['successes'] == [str(a)]
    assert res['cancelled'] is True
    assert res['cancel_reason'] == ('Durdurma isteği geldi; başlamış kurulum tamamlandı, '
                                    'kalan paketler kuyrukta bırakıldı.')
    w2.finished_ok.emit(res)
    w2.finished.emit()

    win.runs.clear()
    tab._start_install((str(a),), 'batch')
    w3 = win.runs[-1][0]
    motor.install_apk_hook = lambda target, path: w3.cancel()
    res = w3.args[0]()
    assert res['cancel_reason'] == 'Durdurma isteği geldi; başlamış son kurulum tamamlandı.'
    w3.finished_ok.emit(res)
    w3.finished.emit()

    win.runs.clear()
    tab._start_install((str(a), str(b)), 'batch')
    w4 = win.runs[-1][0]
    motor.install_apk_hook = lambda target, path: CancelledError('kullanıcı durdurdu')
    res = w4.args[0]()
    assert res['cancel_reason'] == 'Kullanıcı durdurdu; kalanlar kuyrukta.'
    w4.finished_ok.emit(res)
    w4.finished.emit()

    win.runs.clear()
    tab._start_install((str(a),), 'batch')
    w5 = win.runs[-1][0]

    def patlat_iptal(target, path):
        w5.cancel()
        return RuntimeError('kurulamadi')

    motor.install_apk_hook = patlat_iptal
    res = w5.args[0]()
    assert res['failures'] == [str(a)]
    assert res['cancel_reason'] == ('Durdurma isteği geldi; başlayan son kurulum başarısız oldu, '
                                    'başarısız paket kuyrukta tutuldu.')
    w5.finished_ok.emit(res)
    w5.finished.emit()

    win.runs.clear()
    tab._start_install((str(a), str(b)), 'batch')
    w6 = win.runs[-1][0]

    def iptal_hata(target, path):
        w6.cancel()
        return RuntimeError('kurulamadi')

    motor.install_apk_hook = iptal_hata
    res = w6.args[0]()
    assert res['cancel_reason'] == ('Durdurma isteği geldi; başlayan kurulum başarısız oldu, '
                                    'başarısız ve kalan paketler kuyrukta tutuldu.')
    motor.install_apk_hook = None
    w6.finished_ok.emit(res)
    w6.finished.emit()
    assert tab._statuses[tab._path_key(str(a))] == 'failed'
    assert tab._statuses[tab._path_key(str(b))] == 'cancelled'
    assert 'Durdurma isteği geldi' in tab.lbl_inst.text()


def test_start_install_hedef_degisimi(kurulum, monkeypatch, tmp_path):
    tab, core, win = kurulum
    motor = core._engine
    a = tmp_path / 'a.apk'
    a.write_bytes(b'x')
    b = tmp_path / 'b.apk'
    b.write_bytes(b'x')
    monkeypatch.setattr(snapshot_mod, 'take', lambda engine, target: ('snap', 2))
    _Kutu.cevap = _Kutu.Yes
    win.runs.clear()
    tab._start_install((str(a), str(b)), 'batch')
    w = win.runs[-1][0]
    motor.install_apk_hook = lambda target, path: setattr(core, 'target', 'tv-9')
    res = w.args[0]()
    assert res['successes'] == [str(a)]
    assert res['cancelled'] is True
    assert res['cancel_reason'] == 'Hedef veya bağlantı değişti; kalan paketler korunuyor.'
    w.finished_ok.emit(res)
    w.finished.emit()
    motor.install_apk_hook = None
    core.target = 'tv-1'

    win.runs.clear()
    tab._start_install((str(a),), 'batch')
    w2 = win.runs[-1][0]
    core.target = 'tv-2'
    res = w2.args[0]()
    assert res['cancelled'] is True
    assert res['cancel_reason'] == 'Hedef veya bağlantı değişti; paketler korunuyor.'
    core.target = 'tv-1'


def test_start_install_run_hatasi(kurulum, tmp_path):
    tab, _core, win = kurulum
    a = tmp_path / 'a.apk'
    a.write_bytes(b'x')
    _Kutu.cevap = _Kutu.Yes
    win.run_patlak = True
    win.runs.clear()
    with pytest.raises(RuntimeError, match='calistirilamadi'):
        tab._start_install((str(a),), 'batch')
    assert tab._installing is False
    assert tab._install_worker is None
    assert tab.btn_install.isEnabled() is True
    assert len(win.runs) == 1
    assert win.runs[-1][1] == 'Katalog: kurulu TV uygulamaları taranıyor'


def test_install_progress(kurulum, tmp_path):
    tab, _core, _win = kurulum
    tab._install_progress(1, 2)
    a = tmp_path / 'a.apk'
    a.write_bytes(b'x')
    b = tmp_path / 'b.apk'
    b.write_bytes(b'x')
    tab._files = [str(a), str(b)]
    tab._installing = True
    tab._install_snapshot = (str(a), str(b))
    tab._install_operation = {'mode': 'batch', 'successes': [str(a)], 'failures': [str(b)]}
    tab._install_progress(2, 2)
    assert tab._statuses[tab._path_key(str(a))] == 'success'
    assert tab._statuses[tab._path_key(str(b))] == 'installing'
    assert tab.lbl_inst.text() == '2/2 kuyruk paketi kuruluyor: b.apk'
    # önceki dosya başarısızsa durumu yansır
    tab._install_operation = {'mode': 'batch', 'successes': [], 'failures': [str(a)]}
    tab._install_progress(2, 2)
    assert tab._statuses[tab._path_key(str(a))] == 'failed'
    tab._install_operation = {'mode': 'single'}
    tab._install_snapshot = (str(a),)
    tab._install_progress(1, 1)
    assert tab.lbl_inst.text() == 'Tek APK kuruluyor: a.apk'
    # boş anlık görüntü: sessizce döner
    tab._install_snapshot = ()
    tab._install_progress(1, 1)
    # işlem kaydı yokken ve tam sayı olmayan ilerlemede de çöker değil
    tab._install_snapshot = (str(a),)
    tab._install_operation = None
    tab._install_progress(0.9, 1)
    tab._installing = False


def test_install_failed_ve_done(kurulum):
    tab, _core, _win = kurulum
    isci = _SahteIsci()
    op = {'cancelled': False, 'cancel_reason': ''}
    isci.iptal = True
    tab._install_failed(op, 'Kullanıcı durdurdu', isci)
    assert op['cancelled'] is True
    assert op['cancel_reason'] == 'İşlem başlamadan durduruldu; paketler kuyrukta korundu.'
    op2 = {'cancelled': False, 'cancel_reason': ''}
    tab._install_failed(op2, 'adb koptu', isci)
    assert op2['worker_error'] == 'adb koptu'
    tab._install_failed(op2, 'hata', None)
    assert op2['worker_error'] == 'hata'
    tab._install_done({'a': 1})
    assert tab._install_result == {'a': 1}


def test_install_complete_varyantlari(kurulum, tmp_path):
    tab, _core, win = kurulum
    a = tmp_path / 'a.apk'
    a.write_bytes(b'x')
    b = tmp_path / 'b.apk'
    b.write_bytes(b'x')
    tab._files = [str(a), str(b)]
    tab._installing = True
    tab._install_snapshot = (str(a),)
    tab._install_complete({'mode': 'single', 'successes': [str(a)], 'failures': []})
    assert tab._installing is False
    assert 'Tek APK kuruldu: a.apk' in tab.lbl_inst.text()
    assert _Kutu.kayitlar[-1][1] == 'Kurulum'
    # tek APK iptal (dosya listesiyle)
    tab._installing = True
    tab._install_snapshot = (str(a),)
    tab._install_complete({'mode': 'single', 'successes': [], 'failures': [],
                           'cancelled': True, 'cancel_reason': 'Kullanıcı durdurdu.',
                           'files': [str(a)]})
    metin = tab.lbl_inst.text()
    assert 'Tek APK kurulumu iptal edildi: a.apk' in metin
    assert 'Kullanıcı durdurdu.' in metin
    # tek APK iptal (dosya bilgisi yok -> APK)
    tab._installing = True
    tab._install_snapshot = (str(a),)
    tab._install_complete({'mode': 'single', 'successes': [], 'failures': [],
                           'cancelled': True, 'cancel_reason': 'Kurulum iptal edildi.'})
    assert 'Tek APK kurulumu iptal edildi: APK' in tab.lbl_inst.text()
    # tek APK hatası (başarısızlar listesinden)
    tab._installing = True
    tab._install_snapshot = (str(b),)
    tab._install_complete({'mode': 'single', 'successes': [], 'failures': [str(b)]})
    assert 'Tek APK kurulamadı: b.apk' in tab.lbl_inst.text()
    # tek APK hatası (dosya bilgisi yok -> APK)
    tab._installing = True
    tab._install_snapshot = (str(b),)
    tab._install_complete({'mode': 'single', 'successes': [], 'failures': []})
    assert 'Tek APK kurulamadı: APK' in tab.lbl_inst.text()
    # kuyruk: başarılılar düşer, başarısızlar kalır; işçi hatası + mesaj kırpma
    tab._files = [str(a), str(b)]
    tab._statuses = {}
    tab._installing = True
    tab._install_snapshot = (str(a), str(b))
    win.tab_apps.refresh_sayaci = 0
    tab._install_complete({'mode': 'batch', 'successes': [str(a)], 'failures': [str(b)],
                           'snap': 'snap-9', 'worker_error': 'baglanti koptu',
                           'msgs': ['+ a.apk', 'X b.apk: hata'] + ['+ {}.apk'.format(i) for i in range(20)]})
    metin = tab.lbl_inst.text()
    assert 'Kuyruk sonucu: 1 kuruldu, 1 başarısız.' in metin
    assert 'Başarılılar kuyruktan kaldırıldı; başarısızlar kuyrukta tutuldu.' in metin
    assert 'Paket durumu snapshot’ı: snap-9 (uygulama verileri yedeklenmez).' in metin
    assert 'İşlem hatası: baglanti koptu' in metin
    assert tab._files == [str(b)]
    assert tab._statuses[tab._path_key(str(b))] == 'failed'
    assert len(metin.splitlines()) == 4 + 15
    assert win.tab_apps.refresh_sayaci == 1


def test_install_complete_kapanis_ve_isci(kurulum, tmp_path):
    tab, _core, win = kurulum
    a = tmp_path / 'a.apk'
    a.write_bytes(b'x')
    # kapanırken erken çıkış: kutu yok
    tab._installing = True
    tab._install_snapshot = (str(a),)
    win._closing = True
    once = len(_Kutu.kayitlar)
    tab._install_complete({'mode': 'batch', 'successes': [], 'failures': []})
    assert len(_Kutu.kayitlar) == once
    assert tab._installing is False
    win._closing = False
    # farklı işçi verilirse _install_worker korunur
    tab._installing = True
    tab._install_worker = 'baska'
    tab._install_snapshot = (str(a),)
    tab._install_complete({'mode': 'batch', 'successes': [], 'failures': []}, worker='x')
    assert tab._install_worker == 'baska'
    tab._install_worker = None
    # komşu sekme tazeleme hatası yutulur
    win.tab_apps = _UygulamalarPatlak()
    tab._installing = True
    tab._install_snapshot = (str(a),)
    tab._install_complete({'mode': 'single', 'successes': [str(a)], 'failures': []})
    assert 'Tek APK kuruldu: a.apk' in tab.lbl_inst.text()


def test_katalog_kurulum_kapilari(kurulum, monkeypatch):
    tab, core, win = kurulum
    cagrilar = []
    monkeypatch.setattr(tab, '_open_catalog_store', lambda it: cagrilar.append(('store', it['id'])))
    alisveris = _oge(id='x2', name='Store Uygulama', package='com.s.one', type='store')
    tab._install_catalog_app(alisveris)
    assert cagrilar == [('store', 'x2')]
    item = _oge()
    tab._catalog_worker = object()
    tab._install_catalog_app(item)
    assert tab.lbl_catalog_status.text() == 'Devam eden işlem bitmeden yeni kurulum başlatılamaz.'
    tab._catalog_worker = None
    tab._installing = True
    tab._install_catalog_app(item)
    assert tab.lbl_catalog_status.text() == 'Devam eden işlem bitmeden yeni kurulum başlatılamaz.'
    tab._installing = False
    for attr in ('_connection_busy', '_closing', '_close_pending'):
        setattr(win, attr, True)
        tab.lbl_catalog_status.setText('')
        tab._install_catalog_app(item)
        assert tab.lbl_catalog_status.text() == 'Devam eden işlem bitmeden yeni kurulum başlatılamaz.'
        setattr(win, attr, False)
    core.connected = False
    tab._install_catalog_app(item)
    assert _Kutu.kayitlar[-1] == (
        'info', 'Bağlantı Yok', 'Uygulama kurmak için önce bir TV cihazına bağlanın.')
    core.connected = True
    # require_installed: durum doğrulanmadı
    tab._catalog_status_known = False
    tab._install_catalog_app(item, require_installed=True)
    assert tab.lbl_catalog_status.text() == 'Kurulum durumu doğrulanmadı; yeniden kurma başlatılmadı.'
    # zaten kuruluyor
    tab._catalog_status_known = True
    tab._catalog_status_target = 'tv-1'
    tab._installed_pkgs = {'com.x.one'}
    tab._catalog_installing.add('x1')
    tab._install_catalog_app(item, require_installed=True)
    assert tab.lbl_catalog_status.text() == 'X Uygulama için kurulum zaten sürüyor.'
    tab._catalog_installing.discard('x1')
    # onay reddi
    _Kutu.cevap = _Kutu.No
    once = len(win.runs)
    tab._install_catalog_app(item)
    assert _Kutu.kayitlar[-1][0] == 'uyari'
    assert _Kutu.kayitlar[-1][1] == 'Üçüncü Taraf APK Kurulumu'
    assert len(win.runs) == once
    # onay sonrası hedef değişirse
    _Kutu.cevap = _Kutu.Yes
    _Kutu.hook = lambda: setattr(core, 'target', 'tv-9')
    tab._install_catalog_app(item)
    assert tab.lbl_catalog_status.text() == 'Hedef veya işlem durumu değişti; kurulum başlatılmadı.'
    _Kutu.hook = None
    core.target = 'tv-1'


def test_katalog_kurulum_basarili(kurulum, monkeypatch, tmp_path):
    tab, core, win = kurulum
    motor = core._engine
    item = _oge(id='x1', name='X Uygulama', package='com.x.one')
    indirilen = tmp_path / 'indirilen.apk'
    indirilen.write_bytes(b'x')
    motor.varsayilan_meta = {'package': 'com.x.one'}
    motor.installed = {'com.x.one'}
    monkeypatch.setattr(install_mod, 'download_apk', lambda *a, **k: str(indirilen))
    _Kutu.cevap = _Kutu.Yes
    win.runs.clear()
    tab._install_catalog_app(item)
    uyari = _Kutu.kayitlar[-1]
    assert uyari[0] == 'uyari'
    assert 'Kaynak: https://x.example' in uyari[2]
    assert 'Paket: com.x.one' in uyari[2]
    assert 'Tüm çalışma zamanı izinleri otomatik verilecek.' in uyari[2]
    assert tab._catalog_worker is not None
    assert tab.lbl_catalog_status.text() == 'X Uygulama indiriliyor ve kuruluyor...'
    assert tab.progress_catalog.isHidden() is False
    assert tab.progress_catalog.maximum() == 0
    assert tab.btn_catalog_refresh.isEnabled() is False
    assert tab.btn_add.isEnabled() is False
    w, desc = win.runs[-1]
    assert desc == 'Kurulum: X Uygulama indiriliyor ve kuruluyor'
    assert w.job_name == 'X Uygulama Kurulumu'

    # ilerleme: bilinmeyen toplam
    w.progress.emit(10, 0)
    assert tab.progress_catalog.maximum() == 0
    assert tab.lbl_catalog_status.text() == 'X Uygulama indiriliyor...'
    # bilinen toplam
    w.progress.emit(50, 100)
    assert tab.progress_catalog.maximum() == 100
    assert tab.progress_catalog.value() == 50
    assert 'X Uygulama indiriliyor: 0.0 / 0.0 MB (%50)' == tab.lbl_catalog_status.text()
    w.progress.emit(100, 100)
    assert tab.lbl_catalog_status.text() == "X Uygulama TV'ye yükleniyor (ADB)..."

    res = w.args[0]()
    assert res == {'installed': True, 'output': 'ok', 'package': 'com.x.one',
                   'cancel_requested': False}
    w.finished_ok.emit(res)
    w.finished.emit()
    assert tab._catalog_worker is None
    assert tab.btn_catalog_refresh.isEnabled() is True
    assert tab.lbl_catalog_status.text() == "✓ X Uygulama TV'ye başarıyla kuruldu!"
    assert tab.progress_catalog.isHidden() is True
    assert 'com.x.one' in tab._installed_pkgs
    assert tab._catalog_status_target == 'tv-1'
    kutu = _Kutu.son_ornek
    assert kutu.title == 'Kurulum Başarılı'
    assert 'X Uygulama' in kutu.text

    # başlat düğmesine tıklanır
    _Kutu.tiklama = "TV'de Başlat"
    baslatilan = []
    monkeypatch.setattr(tab, '_launch_catalog_app', lambda it: baslatilan.append(it['id']))
    tab._install_catalog_app(item)
    w2 = win.runs[-1][0]
    res2 = w2.args[0]()
    w2.finished_ok.emit(res2)
    w2.finished.emit()
    assert baslatilan == ['x1']
    _Kutu.tiklama = None

    # tıklama anında hedef değişirse başlatılmaz
    _Kutu.tiklama = "TV'de Başlat"
    _Kutu.exec_hook = lambda: setattr(core, 'target', 'tv-9')
    tab._install_catalog_app(item)
    w3 = win.runs[-1][0]
    res3 = w3.args[0]()
    w3.finished_ok.emit(res3)
    w3.finished.emit()
    assert tab.lbl_catalog_status.text() == 'Hedef veya bağlantı değişti; uygulama başlatılmadı.'
    _Kutu.exec_hook = None
    _Kutu.tiklama = None
    core.target = 'tv-1'

    # durdurma isteğiyle biten kurulum: kutu yok
    sayi = len(_Kutu.kayitlar)
    tab._install_catalog_app(item)
    w4 = win.runs[-1][0]
    res4 = dict(w4.args[0]())
    res4['cancel_requested'] = True
    w4.finished_ok.emit(res4)
    w4.finished.emit()
    assert tab.lbl_catalog_status.text() == (
        'X Uygulama kuruldu ve doğrulandı; durdurma isteği başlamış kurulumu geri almadı.')
    assert len(_Kutu.kayitlar) == sayi + 1


def test_katalog_kurulum_hatalari(kurulum, monkeypatch, tmp_path):
    tab, core, win = kurulum
    motor = core._engine
    item = _oge(id='x1', name='X Uygulama', package='com.x.one')
    indirilen = tmp_path / 'i.apk'
    indirilen.write_bytes(b'x')
    _Kutu.cevap = _Kutu.Yes
    win.runs.clear()

    # işçi çalıştırılamazsa hata üzerinden işlenir
    win.run_patlak = True
    tab._install_catalog_app(item)
    assert tab._catalog_worker is None
    assert tab.lbl_catalog_status.text() == 'Kurulum başarısız: calistirilamadi'
    assert _Kutu.kayitlar[-1][0] == 'kritik'
    assert _Kutu.kayitlar[-1][2].startswith('X Uygulama\n')

    # indirme sırasında kullanıcı durdurdu
    win.runs.clear()

    def patlak_indir(*a, **k):
        raise RuntimeError('kullanıcı durdurdu')

    monkeypatch.setattr(install_mod, 'download_apk', patlak_indir)
    tab._install_catalog_app(item)
    w = win.runs[-1][0]
    with pytest.raises(RuntimeError):
        w.args[0]()
    w.failed.emit('kullanıcı durdurdu')
    w.finished.emit()
    assert tab.lbl_catalog_status.text() == 'Kurulum durduruldu; indirilmiş APK yerelde kalabilir.'

    # genel hata + kritik kutu
    monkeypatch.setattr(install_mod, 'download_apk', lambda *a, **k: str(indirilen))
    tab._install_catalog_app(item)
    w = win.runs[-1][0]
    w.failed.emit('adb koptu')
    w.finished.emit()
    assert tab.lbl_catalog_status.text() == 'Kurulum başarısız: adb koptu'
    assert _Kutu.kayitlar[-1] == ('kritik', 'Kurulum Hatası', 'X Uygulama\nadb koptu')

    # sonuç ya da hata yok
    tab._install_catalog_app(item)
    w = win.runs[-1][0]
    w.finished.emit()
    assert tab.lbl_catalog_status.text() == 'Kurulum başarısız: Kurulum tamamlanamadı.'

    # doğrulanamayan sonuç
    tab._install_catalog_app(item)
    w = win.runs[-1][0]
    w.finished_ok.emit('bozuk')
    w.finished.emit()
    assert tab.lbl_catalog_status.text() == 'Kurulum başarısız: TV üzerinde kurulum doğrulanamadı.'

    # indirme sonrası hedef değişti
    monkeypatch.setattr(install_mod, 'download_apk',
                        lambda *a, **k: (setattr(core, 'target', 'tv-9'), str(indirilen))[1])
    tab._install_catalog_app(item)
    w = win.runs[-1][0]
    with pytest.raises(RuntimeError, match='Hedef veya bağlantı değişti'):
        w.args[0]()
    core.target = 'tv-1'
    w.failed.emit('Hedef veya bağlantı değişti; APK kurulmadı.')
    w.finished.emit()
    assert tab.lbl_catalog_status.text() == 'Kurulum başarısız: Hedef veya bağlantı değişti; APK kurulmadı.'

    # meta paket kimliği uyuşmuyor
    monkeypatch.setattr(install_mod, 'download_apk', lambda *a, **k: str(indirilen))
    motor.varsayilan_meta = {'package': 'com.baska'}
    tab._install_catalog_app(item)
    w = win.runs[-1][0]
    with pytest.raises(RuntimeError, match='beklenen paket kimliğine sahip değil'):
        w.args[0]()
    w.failed.emit('İndirilen APK beklenen paket kimliğine sahip değil.')
    w.finished.emit()

    # kurulum doğrulanamıyor
    motor.varsayilan_meta = {'package': 'com.x.one'}
    motor.installed = set()
    tab._install_catalog_app(item)
    w = win.runs[-1][0]
    with pytest.raises(RuntimeError, match='kurulduğu doğrulanamadı'):
        w.args[0]()
    w.failed.emit('com.x.one paketinin TV\'ye kurulduğu doğrulanamadı.')
    w.finished.emit()

    # önbellek temizleme hatası yutulur, kurulum yine doğrulanır
    motor.invalidate_patlak = True
    motor.installed = {'com.x.one'}
    tab._install_catalog_app(item)
    w = win.runs[-1][0]
    res = w.args[0]()
    assert res['installed'] is True
    w.finished_ok.emit(res)
    w.finished.emit()
    motor.invalidate_patlak = False

    # ilerleme sırasında hedef değişirse
    tab._install_catalog_app(item)
    w = win.runs[-1][0]
    w.progress.connect(lambda cur, total: setattr(core, 'target', 'tv-9')
                       if (cur, total) == (100, 100) else None)
    with pytest.raises(RuntimeError, match='Hedef veya bağlantı değişti'):
        w.args[0]()
    core.target = 'tv-1'
    w.failed.emit('Hedef veya bağlantı değişti; APK kurulmadı.')
    w.finished.emit()

    # bayat tamamlanma: hiçbir şey güncellenmez
    tab._install_catalog_app(item)
    w = win.runs[-1][0]
    durum = tab.lbl_catalog_status.text()
    core.target = 'tv-9'
    w.finished_ok.emit({'installed': True, 'package': 'com.x.one'})
    w.finished.emit()
    assert tab._catalog_worker is None
    assert tab.lbl_catalog_status.text() == durum
    core.target = 'tv-1'

    # kapanışta sonuç işlenmez
    tab._install_catalog_app(item)
    w = win.runs[-1][0]
    durum = tab.lbl_catalog_status.text()
    win._closing = True
    w.finished_ok.emit({'installed': True, 'package': 'com.x.one'})
    w.finished.emit()
    win._closing = False
    assert tab.lbl_catalog_status.text() == durum

    # bekleyen tazeleme tamamlanınca durum taraması başlar
    tab._install_catalog_app(item)
    w = win.runs[-1][0]
    tab._catalog_refresh_pending = True
    sayi = len(win.runs)
    w.finished.emit()
    assert len(win.runs) == sayi + 1
    assert win.runs[-1][1] == 'Katalog: kurulu TV uygulamaları taranıyor'


def test_katalog_baslat(kurulum):
    tab, core, win = kurulum
    motor = core._engine
    item = _oge(id='x1', name='X Uygulama', package='com.x.one', alt_packages=['com.x.alt'])
    tab._catalog_worker = object()
    tab._launch_catalog_app(item)
    tab._catalog_worker = None
    win._connection_busy = True
    tab._launch_catalog_app(item)
    win._connection_busy = False
    tab._installing = True
    tab._launch_catalog_app(item)
    tab._installing = False
    core.connected = False
    tab._launch_catalog_app(item)
    assert _Kutu.kayitlar[-1] == (
        'info', 'Bağlantı Yok', 'Uygulamayı başlatmak için önce cihaza bağlanın.')
    core.connected = True
    tab._catalog_status_known = False
    tab._launch_catalog_app(item)
    assert _Kutu.kayitlar[-1] == (
        'info', 'Kurulum Durumu Bilinmiyor',
        'Uygulama durumu bu TV için doğrulanmadı. Kurulum durumunu güncelleyin.')
    tab._catalog_status_known = True
    tab._catalog_status_target = 'tv-1'
    tab._installed_pkgs = {'com.x.alt'}
    win.runs.clear()
    tab._launch_catalog_app(item)
    w, desc = win.runs[-1]
    assert desc == 'Katalog: X Uygulama TV ekranında başlatılıyor'
    assert w.job_name == 'X Uygulama Başlatma'
    sonuc = w.args[0]()
    assert ('launch_app', 'tv-1', 'com.x.alt') in motor.calls
    core.target = 'tv-9'
    with pytest.raises(CancelledError):
        w.args[0]()
    core.target = 'tv-1'
    w.finished_ok.emit(sonuc)
    assert tab.lbl_catalog_status.text() == 'X Uygulama için başlatma komutu gönderildi.'
    w.failed.emit('acilamadi')
    assert _Kutu.kayitlar[-1] == ('uyari', 'Başlatma Uyarısı', 'Uygulama açılamadı:\nacilamadi')
    # bayat bağlamda ileti yok
    core.target = 'tv-9'
    sayi = len(_Kutu.kayitlar)
    w.failed.emit('yine')
    w.finished_ok.emit(sonuc)
    assert len(_Kutu.kayitlar) == sayi
    core.target = 'tv-1'


def test_katalog_magaza(kurulum):
    tab, core, win = kurulum
    motor = core._engine
    item = _oge(id='x2', name='Store Uygulama', package='com.s.one', type='store')
    core.connected = False
    tab._open_catalog_store(item)
    assert _Kutu.kayitlar[-1] == (
        'info', 'Bağlantı Yok', 'Play Store sayfasını açmak için önce cihaza bağlanın.')
    core.connected = True
    tab._catalog_worker = object()
    tab._open_catalog_store(item)
    tab._catalog_worker = None
    win._connection_busy = True
    tab._open_catalog_store(item)
    win._connection_busy = False
    tab._installing = True
    tab._open_catalog_store(item)
    tab._installing = False
    win.runs.clear()
    tab._open_catalog_store(item)
    w, desc = win.runs[-1]
    assert desc == 'Katalog: Store Uygulama Play Store sayfası açılıyor'
    assert w.job_name == 'Store Uygulama Mağaza'
    w.args[0]()
    assert ('open_play_store', 'tv-1', 'com.s.one') in motor.calls
    w.finished_ok.emit(None)
    assert tab.lbl_catalog_status.text() == "Store Uygulama için Play Store sayfası TV'de açıldı."
    w.failed.emit('yok')
    assert _Kutu.kayitlar[-1][0] == 'uyari'
    assert _Kutu.kayitlar[-1][1] == 'Mağaza Açılamadı'
    assert "TV'de Play Store uygulaması kurulu ve güncel olmalıdır." in _Kutu.kayitlar[-1][2]
    core.target = 'tv-9'
    with pytest.raises(CancelledError):
        w.args[0]()
    sayi = len(_Kutu.kayitlar)
    w.failed.emit('yine')
    w.finished_ok.emit(None)
    assert len(_Kutu.kayitlar) == sayi
    core.target = 'tv-1'


def test_katalog_durum_yenileme(kurulum):
    tab, core, win = kurulum
    motor = core._engine
    tab._catalog_worker = object()
    tab._refresh_catalog_statuses()
    assert tab._catalog_refresh_pending is True
    tab._catalog_worker = None
    tab._installing = True
    tab._refresh_catalog_statuses()
    assert tab._catalog_refresh_pending is True
    tab._installing = False
    tab._catalog_refresh_pending = False
    win.runs.clear()
    # bağlı değil: durum sıfırlanır, işçi kurulmaz
    core.connected = False
    tab._catalog_status_known = True
    tab._catalog_status_target = 'tv-1'
    tab._refresh_catalog_statuses()
    assert tab._catalog_status_known is False
    assert tab._catalog_status_target is None
    assert tab._installed_pkgs == set()
    assert win.runs == []
    core.connected = True
    # hedef değişti: sıfırlanır ve tarama başlar
    tab._catalog_status_target = 'tv-9'
    tab._refresh_catalog_statuses()
    assert tab._catalog_status_target is None
    assert len(win.runs) == 1
    w = win.runs[-1][0]
    assert w.job_name == 'TV Uygulama Durumu'
    motor.paketler = ['org.x', 'com.y']
    sonuc = w.args[0]()
    assert sonuc == {'org.x', 'com.y'}
    w.finished_ok.emit(sonuc)
    assert tab._installed_pkgs == {'org.x', 'com.y'}
    assert tab._catalog_status_known is True
    assert tab._catalog_status_target == 'tv-1'
    assert tab._catalog_status_error_target is None
    # bayat istek yok sayılır
    tab._catalog_status_known = False
    tab._refresh_catalog_statuses()
    w2 = win.runs[-1][0]
    tab._catalog_refresh_generation += 1
    w2.finished_ok.emit({'a'})
    assert tab._catalog_status_known is False
    # hedef değişince sonuç yok sayılır
    tab._refresh_catalog_statuses()
    w3 = win.runs[-1][0]
    core.target = 'tv-2'
    w3.finished_ok.emit({'b'})
    assert tab._catalog_status_known is False
    core.target = 'tv-1'
    # hata hedefi işaretler ve özet uyarır
    tab._refresh_catalog_statuses()
    w4 = win.runs[-1][0]
    w4.failed.emit('hata')
    assert tab._catalog_status_error_target == 'tv-1'
    assert 'sorgulanamadı' in tab.lbl_catalog_summary.text()
    # bayat hatada hedef işaretlenmez
    tab._catalog_status_error_target = None
    tab._refresh_catalog_statuses()
    w5 = win.runs[-1][0]
    tab._catalog_refresh_generation += 1
    w5.failed.emit('hata')
    assert tab._catalog_status_error_target is None


def test_refresh_ve_show(kurulum):
    tab, core, win = kurulum
    win.runs.clear()
    tab.refresh()
    assert len(win.runs) == 1
    assert win.runs[-1][1] == 'Katalog: kurulu TV uygulamaları taranıyor'
    core.connected = False
    tab.refresh()
    assert len(win.runs) == 1
    core.connected = True
    tab.showEvent(QShowEvent())
    assert len(win.runs) == 2
    assert tab._catalog_layout_timer.isActive() is True


def test_baglanti_degisimi(kurulum):
    tab, core, win = kurulum
    tab._catalog_status_known = True
    tab._catalog_status_target = 'tv-1'
    tab._installed_pkgs = {'org.x'}
    tab.cmb_launch.addItem('X ok', 'org.x/Act')
    tab._launchers_target = 'tv-1'
    tab.lbl_home.setText('Mevcut HOME: org.x/Act')
    tab._catalog_installing.add('x1')
    tab._connection_generation = 5
    win.runs.clear()
    # aynı hedefe yeniden bağlantı: durum korunur, launcher temizlenir
    tab._on_connection_changed(True, 'tv-1')
    assert tab._connection_generation == 6
    assert tab._catalog_status_known is True
    assert tab.cmb_launch.count() == 0
    assert tab._launchers_target is None
    assert tab.lbl_home.text() == 'Mevcut HOME: —'
    assert tab._catalog_installing
    assert tab.lbl_catalog_status.text() == 'Hedef değişti; önceki cihazın kurulum sonucu gösterilmeyecek.'
    assert tab.progress_catalog.isHidden() is True
    assert len(win.runs) == 1
    # kurulum sürerken hedef değişirse işçi iptal edilir ve durum sıfırlanır
    win.runs.clear()
    tab._catalog_worker = _SahteIsci()
    tab._on_connection_changed(True, 'tv-2')
    assert tab._catalog_worker.cancel_calls == 1
    assert tab._catalog_status_known is False
    assert tab._installed_pkgs == set()
    tab._catalog_worker = None
    # bağlantı yok: işçi kurulmaz, tablo yeniden çizilir
    win.runs.clear()
    core.connected = False
    tab._on_connection_changed(False, None)
    assert win.runs == []
    assert tab._catalog_status_target is None


def test_hedef_ve_durum_dogrulamalari(kurulum):
    tab, core, win = kurulum
    gen = tab._connection_generation
    assert tab._target_is_current('tv-1', gen) is True
    assert tab._target_is_current('tv-1', gen + 1) is False
    core.connected = False
    assert tab._target_is_current('tv-1', gen) is False
    core.connected = True
    assert tab._target_is_current('tv-9', gen) is False
    win._connection_busy = True
    assert tab._target_is_current('tv-1', gen) is False
    win._connection_busy = False
    tab._catalog_status_known = True
    tab._catalog_status_target = 'tv-1'
    assert tab._catalog_status_known_for('tv-1') is True
    assert tab._catalog_status_known_for('tv-9') is False
    item = _oge(id='x1', package='com.x.one', alt_packages=['com.x.alt'])
    tab._installed_pkgs = {'com.x.alt'}
    assert tab._is_catalog_item_installed(item) is True
    assert tab._get_installed_pkg(item) == 'com.x.alt'
    assert tab._catalog_item_verified_installed(item) is True
    tab._installed_pkgs = set()
    assert tab._catalog_item_verified_installed(item) is False
    assert tab._get_installed_pkg(item) == 'com.x.one'
    assert _is_store_item({'type': ' Store '}) is True
    assert _is_store_item({'type': 'STORE'}) is True
    assert _is_store_item({}) is False


def test_tablo_kolonlari_timer_ve_olaylar(kurulum):
    tab, _core, _win = kurulum
    tab._update_catalog_columns()
    assert tab.table_catalog.columnWidth(2) >= 300
    tablo = tab.table_catalog
    del tab.table_catalog
    tab._update_catalog_columns()
    tab.table_catalog = tablo
    assert tab._catalog_layout_timer.isSingleShot() is True
    tab.resizeEvent(QResizeEvent(QSize(500, 400), QSize(100, 100)))
    assert tab._catalog_layout_timer.isActive() is True
    tab.eventFilter(tab.table_catalog.viewport(), QEvent(QEvent.Resize))
    assert tab._catalog_layout_timer.isActive() is True
    tab.eventFilter(tab.table_catalog.viewport(), QEvent(QEvent.Show))
    tab.eventFilter(tab, QEvent(QEvent.Resize))
    tab.eventFilter(tab.table_catalog.viewport(), QEvent(QEvent.MouseButtonPress))


def test_tema(kurulum, monkeypatch):
    tab, _core, _win = kurulum
    tab._catalog_status_known = True
    tab._catalog_status_target = 'tv-1'
    tab._installed_pkgs = {'org.smarttube.stable'}
    tab._populate_catalog_table()
    tab.apply_theme()
    row = next(r for r in range(tab.table_catalog.rowCount())
               if tab.table_catalog.item(r, 0).data(Qt.UserRole)['package'] == 'org.smarttube.stable')
    assert tab.table_catalog.item(row, 4).data(Qt.UserRole) is True

    def patlak(*a, **k):
        raise AttributeError('yok')

    monkeypatch.setattr(install_mod.kit, 'dark_from', patlak)
    tab.apply_theme()


def test_surukle_birak(qtbot):
    kayit = []
    lst = _DropQueueList(lambda paths: kayit.append(list(paths)))
    qtbot.addWidget(lst)
    ev = _Olay(_Mime([_Url(True, 'C:/x.apk')]))
    lst.dragEnterEvent(ev)
    assert ev.kabul is True
    ev = _Olay(_Mime([_Url(False)]))
    lst.dragEnterEvent(ev)
    assert ev.yok is True
    ev = _Olay(_Mime([]))
    lst.dragEnterEvent(ev)
    assert ev.yok is True
    ev = _Olay(_Mime([_Url(True, 'C:/x.apk'), _Url(False, 'http://y')]))
    lst.dropEvent(ev)
    assert kayit == [['C:/x.apk']]
    assert ev.kabul is True
    ev = _Olay(_Mime([_Url(False)]))
    lst.dropEvent(ev)
    assert ev.yok is True


def test_snapshot_gorunumu():
    motor = _Motor()
    motor.paketler = ['org.a']
    view = _SnapshotEngineView(motor, 'tv-1')
    assert view.list_packages('tv-1') == ['org.a']
    view.connect('tv-1')
    with pytest.raises(ValueError):
        view.connect('tv-2')
    with pytest.raises(CancelledError):
        view.connect('tv-1', cancel_check=lambda: True)
    view.connect('tv-1', cancel_check=lambda: False)
    assert not any(call[0] == 'connect' for call in motor.calls)


def test_katalog_tablosuz_yenileme(kurulum):
    tab, _core, _win = kurulum
    cmb = tab.cmb_catalog_cat
    txt = tab.txt_catalog_search
    del tab.cmb_catalog_cat
    del tab.txt_catalog_search
    tab._populate_catalog_table()
    tab.cmb_catalog_cat = cmb
    tab.txt_catalog_search = txt
    assert tab.table_catalog.rowCount() == len(get_catalog())


# --- konsol ---


def test_konsol_komutlari(kurulum):
    tab, core, win = kurulum
    motor = core._engine
    core.connected = False
    tab.txt_cmd.setText('getprop')
    tab._run_cmd()
    assert 'Komut için önce bir cihaza bağlanın.' in tab.txt_out.toPlainText()
    core.connected = True
    tab.txt_cmd.setText('   ')
    once = tab.txt_out.toPlainText()
    tab._run_cmd()
    assert tab.txt_out.toPlainText() == once
    tab.txt_cmd.setText('rm -rf /')
    tab._run_cmd()
    assert _Kutu.kayitlar[-1][0] == 'kritik'
    assert _Kutu.kayitlar[-1][1] == 'Kapı'
    assert 'REDDEDİLDİ (yıkıcı komut).' in tab.txt_out.toPlainText()
    win.runs.clear()
    tab.txt_cmd.setText('getprop ro.product.model')
    tab._run_cmd()
    assert _Kutu.kayitlar[-1][0] != 'soru'
    w, desc = win.runs[-1]
    assert desc == 'Kurulum konsolu komutu'
    assert w.job_name == 'Konsol komutu'
    _Kutu.cevap = _Kutu.No
    tab.txt_cmd.setText('pm disable-user --user 0 com.x')
    tab._run_cmd()
    assert _Kutu.kayitlar[-1][0] == 'soru'
    assert _Kutu.kayitlar[-1][2] == ('[CHANGE] pm disable-user --user 0 com.x\n\n'
                                     'Cihazda değişiklik yapar. Çalıştırılsın mı?')
    _Kutu.cevap = _Kutu.Yes
    win.runs.clear()
    tab.txt_cmd.setText('settings put global animator_duration_scale 0')
    tab._run_cmd()
    w = win.runs[-1][0]
    motor.shell_result = SimpleNamespace(exit_code=0, output='deger', error='')
    cikti = w.args[0]()
    assert cikti == '[SETTING] exit=0\ndeger\n'
    assert ('connect', 'tv-1') in motor.calls
    shelllar = [c for c in motor.calls if c[0] == 'shell']
    assert shelllar[-1][1:7] == ('tv-1', 'settings', 'put', 'global',
                                 'animator_duration_scale', '0')
    assert shelllar[-1][-1]['timeout'] == 30
    assert shelllar[-1][-1]['hide_from_trace'] is True
    w.finished_ok.emit(cikti)
    assert ('$ settings put global animator_duration_scale 0\n'
            '[SETTING] exit=0\ndeger\n') in tab.txt_out.toPlainText()
    motor.shell_result = SimpleNamespace(exit_code=2, output='', error='hata')
    assert w.args[0]() == '[SETTING] exit=2\nhata'
    motor.shell_result = SimpleNamespace(exit_code=1, output='cikti', error='err')
    assert w.args[0]() == '[SETTING] exit=1\ncikti\nerr'
    # bayat hedefte ne çalışır ne yazılır
    once = tab.txt_out.toPlainText()
    core.target = 'tv-9'
    w.finished_ok.emit('yeni')
    with pytest.raises(RuntimeError):
        w.args[0]()
    assert tab.txt_out.toPlainText() == once
    core.target = 'tv-1'
    # onaydan sonra hedef değişirse
    _Kutu.hook = lambda: setattr(core, 'target', 'tv-9')
    win.runs.clear()
    tab.txt_cmd.setText('settings put global x 1')
    tab._run_cmd()
    assert 'Hedef veya bağlantı değişti; komut çalıştırılmadı.' in tab.txt_out.toPlainText()
    assert win.runs == []
    _Kutu.hook = None
    core.target = 'tv-1'


def test_konsol_isci_yollari(kurulum):
    tab, core, win = kurulum
    motor = core._engine
    _Kutu.cevap = _Kutu.Yes
    win.runs.clear()
    tab.txt_cmd.setText('getprop ro.product.model')
    tab._run_cmd()
    w = win.runs[-1][0]
    w.iptal = True
    with pytest.raises(CancelledError):
        w.args[0]()
    w.iptal = False
    motor.connect_patlak = True
    with pytest.raises(RuntimeError, match='baglanti yok'):
        w.args[0]()
    motor.connect_hook = lambda: setattr(w, 'iptal', True)
    with pytest.raises(CancelledError):
        w.args[0]()
    w.iptal = False
    motor.connect_hook = None
    motor.connect_patlak = False
    motor.shell_patlak = True
    with pytest.raises(RuntimeError, match='shell yok'):
        w.args[0]()
    motor.shell_patlak = False


# --- HOME ---


def test_home_tarama_ve_gosterim(kurulum):
    tab, core, win = kurulum
    motor = core._engine
    core.connected = False
    tab._scan_launchers()
    assert _Kutu.kayitlar[-1] == ('info', 'Launcher', 'Önce bir TV cihazına bağlanın.')
    core.connected = True
    win.runs.clear()
    motor.launcher_listesi = ['com.b/.Act', 'com.a/.Main', 'com.a/.Main']
    tab._scan_launchers()
    w, desc = win.runs[-1]
    assert desc == 'Kurulum: launcherlar taraniyor'
    assert w.job_name == 'Launcher tarama'
    sonuc = w.args[0]()
    assert ('connect', 'tv-1') in motor.calls
    assert sonuc == ['com.b/.Act', 'com.a/.Main', 'com.a/.Main']
    w.finished_ok.emit(sonuc)
    assert tab.cmb_launch.count() == 2
    assert tab.cmb_launch.itemData(0) == 'com.a/.Main'
    assert tab.cmb_launch.itemText(0) == 'com.a'
    assert tab.cmb_launch.itemData(0, Qt.ToolTipRole) == 'com.a/.Main'
    assert tab._launchers_target == 'tv-1'
    core.config.friendly = {'com.b': 'B Uygulaması'}
    w.finished_ok.emit(sonuc)
    assert tab.cmb_launch.itemText(1) == 'B Uygulaması · com.b'

    def patlak(pkg):
        raise RuntimeError('yok')

    core.config.friendly_name = patlak
    w.finished_ok.emit(sonuc)
    assert tab.cmb_launch.itemText(1) == 'com.b'
    del core.config.friendly_name
    w.finished_ok.emit([])
    assert tab.cmb_launch.count() == 1
    assert tab.cmb_launch.itemText(0) == '(bulunamadı)'
    assert tab.cmb_launch.itemData(0) == ''
    core.target = 'tv-9'
    w.finished_ok.emit(sonuc)
    assert tab.cmb_launch.count() == 1
    core.target = 'tv-1'


def test_home_okuma_ve_ayarlama(kurulum):
    tab, core, win = kurulum
    motor = core._engine
    core.connected = False
    tab._show_home()
    assert _Kutu.kayitlar[-1] == ('info', 'HOME', 'Önce bir TV cihazına bağlanın.')
    core.connected = True
    win.runs.clear()
    motor.home = 'com.stok/.Main'
    tab._show_home()
    w, desc = win.runs[-1]
    assert desc == 'Kurulum: mevcut HOME okunuyor'
    assert w.job_name == 'HOME okuma'
    assert w.args[0]() == 'com.stok/.Main'
    w.finished_ok.emit('com.stok/.Main')
    assert tab.lbl_home.text() == 'Mevcut HOME: com.stok/.Main'
    core.target = 'tv-9'
    w.finished_ok.emit('com.baska/.X')
    assert tab.lbl_home.text() == 'Mevcut HOME: com.stok/.Main'
    core.target = 'tv-1'

    tab.cmb_launch.clear()
    tab._set_home()
    assert _Kutu.kayitlar[-1] == ('info', 'HOME', 'Önce Launcherları Tara ile seçin.')
    tab._show_launchers(['com.a/.Main'], 'tv-1', tab._connection_generation)
    tab._launchers_target = 'tv-9'
    tab._set_home()
    assert _Kutu.kayitlar[-1] == (
        'info', 'HOME', 'Hedef değişti; launcherları bu cihazda yeniden tarayın.')
    tab._show_launchers(['com.a/.Main'], 'tv-1', tab._connection_generation)
    tab.cmb_launch.setCurrentIndex(0)
    _Kutu.cevap = _Kutu.No
    win.runs.clear()
    tab._set_home()
    assert _Kutu.kayitlar[-1][0] == 'soru'
    assert _Kutu.kayitlar[-1][1] == 'Onay — Varsayılan Ana Ekran Yap'
    assert '• com.a' in _Kutu.kayitlar[-1][2]
    assert 'Stok launcher korunur.' in _Kutu.kayitlar[-1][2]
    assert win.runs == []
    _Kutu.cevap = _Kutu.Yes
    _Kutu.hook = lambda: tab.cmb_launch.setCurrentIndex(-1)
    tab._set_home()
    assert _Kutu.kayitlar[-1] == (
        'info', 'HOME', 'Hedef veya launcher seçimi değişti; HOME ayarlanmadı.')
    _Kutu.hook = None
    tab.cmb_launch.setCurrentIndex(0)
    win.runs.clear()
    motor.last_home_notes = ['Kurulum sihirbazı kapatıldı']
    tab._set_home()
    w, desc = win.runs[-1]
    assert desc == 'Kurulum: HOME ayarlaniyor: com.a/.Main'
    assert w.job_name == 'HOME ayarlama'
    res = w.args[0]()
    assert ('set_home_activity', 'tv-1', 'com.a/.Main') in motor.calls
    assert res == {'home': 'com.a/.Main', 'notes': ['Kurulum sihirbazı kapatıldı']}
    w.finished_ok.emit(res)
    assert tab.lbl_home.text() == 'Mevcut HOME: com.a/.Main'
    kutu = _Kutu.kayitlar[-1]
    assert kutu[1] == 'Tamam'
    assert kutu[2].startswith('Yeni HOME: com.a/.Main')
    assert 'Yapılan ek işlemler:\n- Kurulum sihirbazı kapatıldı' in kutu[2]
    tab._home_done('com.x/.Y', 'tv-1', tab._connection_generation)
    assert tab.lbl_home.text() == 'Mevcut HOME: com.x/.Y'
    assert _Kutu.kayitlar[-1][2] == 'Yeni HOME: com.x/.Y'
    sayi = len(_Kutu.kayitlar)
    core.target = 'tv-9'
    tab._home_done('com.z/.W', 'tv-1', tab._connection_generation)
    assert len(_Kutu.kayitlar) == sayi
    core.target = 'tv-1'
    # görünen ad alınamazsa bileşen adına düşülür
    tab._show_launchers(['com.b/.Act'], 'tv-1', tab._connection_generation)
    tab.cmb_launch.setCurrentIndex(0)

    def patlak_text():
        raise RuntimeError('yok')

    tab.cmb_launch.currentText = patlak_text
    win.runs.clear()
    tab._set_home()
    assert win.runs[-1][1] == 'Kurulum: HOME ayarlaniyor: com.b/.Act'
    del tab.cmb_launch.currentText


# --- kapsam kalanları ---


def test_kuyruk_etiketli_gorunum(kurulum, tmp_path):
    tab, core, _win = kurulum
    motor = core._engine
    apk = tmp_path / 'etiket.apk'
    apk.write_bytes(b'x')
    motor.meta[str(apk)] = {'label': 'Sadece Ad'}
    tab._add_paths([str(apk)])
    assert tab.lst.item(0).text() == 'Sadece Ad (etiket.apk)  —  Bekliyor'


def test_start_install_snapshot_ve_onbellek_hatasi(kurulum, monkeypatch, tmp_path):
    tab, core, win = kurulum
    motor = core._engine
    a = tmp_path / 'a.apk'
    a.write_bytes(b'x')

    def patlak_take(engine, target):
        raise RuntimeError('snapshot yok')

    monkeypatch.setattr(snapshot_mod, 'take', patlak_take)
    motor.invalidate_patlak = True
    _Kutu.cevap = _Kutu.Yes
    win.runs.clear()
    tab._start_install((str(a),), 'batch')
    w = win.runs[-1][0]
    res = w.args[0]()
    assert res['snap'] is None
    assert res['successes'] == [str(a)]
    motor.invalidate_patlak = False


def test_start_install_dongu_iptali(kurulum, monkeypatch, tmp_path):
    tab, _core, win = kurulum
    a = tmp_path / 'a.apk'
    a.write_bytes(b'x')
    b = tmp_path / 'b.apk'
    b.write_bytes(b'x')
    monkeypatch.setattr(snapshot_mod, 'take', lambda engine, target: ('snap', 2))
    _Kutu.cevap = _Kutu.Yes
    win.runs.clear()
    tab._start_install((str(a), str(b)), 'batch')
    w = win.runs[-1][0]
    sayac = {'n': 0}

    def sayacli():
        sayac['n'] += 1
        if sayac['n'] >= 3:
            raise CancelledError('kullanıcı durdurdu')

    w.check_cancel = sayacli
    res = w.args[0]()
    assert res['successes'] == [str(a)]
    assert res['cancelled'] is True
    assert res['cancel_reason'] == 'Kullanıcı durdurdu; kalanlar kuyrukta.'


def test_start_install_check_cancel_hatasi(kurulum, monkeypatch, tmp_path):
    tab, _core, win = kurulum
    a = tmp_path / 'a.apk'
    a.write_bytes(b'x')
    monkeypatch.setattr(snapshot_mod, 'take', lambda engine, target: ('snap', 1))
    _Kutu.cevap = _Kutu.Yes
    win.runs.clear()
    tab._start_install((str(a),), 'batch')
    w = win.runs[-1][0]

    def patlak_check():
        raise ValueError('tuhaf')

    w.check_cancel = patlak_check
    with pytest.raises(ValueError, match='tuhaf'):
        w.args[0]()


def test_katalog_bayat_geri_cagrimlar(kurulum, monkeypatch, tmp_path):
    tab, core, win = kurulum
    motor = core._engine
    item = _oge(id='x1', name='X Uygulama', package='com.x.one')
    indirilen = tmp_path / 'i.apk'
    indirilen.write_bytes(b'x')
    motor.varsayilan_meta = {'package': 'com.x.one'}
    motor.installed = {'com.x.one'}
    monkeypatch.setattr(install_mod, 'download_apk', lambda *a, **k: str(indirilen))
    _Kutu.cevap = _Kutu.Yes
    win.runs.clear()
    tab._install_catalog_app(item)
    w = win.runs[-1][0]
    res = w.args[0]()
    w.finished_ok.emit(res)
    gercek = tab._target_is_current
    sira = {'n': 0}

    def sahte(target, generation):
        sira['n'] += 1
        return sira['n'] == 1

    monkeypatch.setattr(tab, '_target_is_current', sahte)
    durum = tab.lbl_catalog_status.text()
    w.finished.emit()
    assert tab._catalog_worker is None
    assert tab.lbl_catalog_status.text() == durum
    monkeypatch.setattr(tab, '_target_is_current', gercek)
    # aynı hile on_fail için
    tab._install_catalog_app(item)
    w2 = win.runs[-1][0]
    w2.failed.emit('hata')
    monkeypatch.setattr(tab, '_target_is_current', sahte)
    sira['n'] = 0
    durum = tab.lbl_catalog_status.text()
    w2.finished.emit()
    assert tab.lbl_catalog_status.text() == durum
    monkeypatch.setattr(tab, '_target_is_current', gercek)
    # ikinci finished çağrısı yok sayılır
    tab._install_catalog_app(item)
    w3 = win.runs[-1][0]
    w3.finished.emit()
    assert tab._catalog_worker is None
    w3.finished.emit()
    assert tab._catalog_worker is None


def test_katalog_indirme_ilerlemesi(kurulum, monkeypatch, tmp_path):
    tab, core, win = kurulum
    motor = core._engine
    item = _oge(id='x1', name='X Uygulama', package='com.x.one')
    indirilen = tmp_path / 'i.apk'
    indirilen.write_bytes(b'x')
    motor.varsayilan_meta = {'package': 'com.x.one'}
    motor.installed = {'com.x.one'}

    def indir(it, progress_cb=None, check_cancel=None):
        progress_cb(10, 100)
        return str(indirilen)

    monkeypatch.setattr(install_mod, 'download_apk', indir)
    _Kutu.cevap = _Kutu.Yes
    win.runs.clear()
    tab._install_catalog_app(item)
    w = win.runs[-1][0]
    assert w.job_name == 'X Uygulama Kurulumu'
    res = w.args[0]()
    assert res['installed'] is True
    # indirme geri çağrısı ve do() sonundaki (100, 100) ilerlemesi işlendi
    assert tab.progress_catalog.value() == 100
    w.finished_ok.emit(res)
    w.finished.emit()
    # bayat hedefte ilerleme yansıtılmaz
    tab._install_catalog_app(item)
    w2 = win.runs[-1][0]
    core.target = 'tv-9'
    deger = tab.progress_catalog.value()
    w2.progress.emit(80, 100)
    assert tab.progress_catalog.value() == deger
    w2.finished.emit()
    core.target = 'tv-1'


def test_konsol_ikinci_hedef_kontrolu(kurulum):
    tab, core, win = kurulum
    motor = core._engine
    _Kutu.cevap = _Kutu.Yes
    win.runs.clear()
    tab.txt_cmd.setText('getprop ro.product.model')
    tab._run_cmd()
    w = win.runs[-1][0]
    motor.connect_hook = lambda: setattr(core, 'target', 'tv-9')
    with pytest.raises(RuntimeError, match='Hedef veya bağlantı değişti'):
        w.args[0]()
    motor.connect_hook = None
    core.target = 'tv-1'
