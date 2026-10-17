# -*- coding: utf-8 -*-
"""main_window: gezinme, baglanti yonetimi, log paneli ve kapanis akislari."""
import datetime
import os
import threading

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QPushButton, QTabWidget, QWidget

import mibox_app.config as config_mod
import mibox_app.ui.main_window as main_mod
from mibox_app.config import Config
from mibox_app.ui.main_window import LogBus, MainWindow
from mibox_app.workers import CancelledError


class _Sonuc:
    def __init__(self, exit_code=0, output='', error=''):
        self.exit_code = exit_code
        self.output = output
        self.error = error


class _Motor:
    """Sahte ADB motoru; yalnizca MainWindow'un dokundugu yuzey."""

    def __init__(self):
        self.calls = []
        self.device_listesi = []
        self.devices_patlak = False
        self.getprop_sonuc = 'TV Model'
        self.getprop_patlak = False
        self.connect_patlak = False
        self.connect_hook = None
        self.adb_path = 'C:/adb/adb.exe'

    def devices(self):
        self.calls.append(('devices',))
        if self.devices_patlak:
            raise RuntimeError('liste yok')
        return list(self.device_listesi)

    def getprop(self, target, prop):
        self.calls.append(('getprop', target, prop))
        if self.getprop_patlak:
            raise RuntimeError('prop yok')
        if prop == 'ro.build.version.release':
            return '12'
        return self.getprop_sonuc

    def connect(self, target, timeout=30, deneme=1, cancel_check=None):
        self.calls.append(('connect', target, timeout, deneme))
        if self.connect_hook is not None:
            self.connect_hook()
        if self.connect_patlak:
            raise RuntimeError('baglanti yok')

    def disconnect(self, target):
        self.calls.append(('disconnect', target))


class _EkranPaneli:
    def __init__(self):
        self.read_calls = 0

    def _has_pending_display_transaction(self):
        return _Sekme.bekleyen_display

    def read_display(self):
        self.read_calls += 1
        _Sekme.kayit.append(('display.read',))


class _Sekme(QWidget):
    """Tum sekme siniflarinin yerine gecen hafif sahte sekme."""

    kayit = []
    bekleyen_display = False
    recording_close = True
    recording_close_hatasi = None
    scrcpy_close = True
    scrcpy_close_hatasi = None
    refresh_hatasi = None

    def __init__(self, core, window):
        super().__init__(window)
        self.core = core
        self.window = window
        self._busy = False
        self._recording_starting = False
        self.display_panel = _EkranPaneli()
        self.subtabs = QTabWidget(self)
        self.subtabs.addTab(QWidget(), 'katalog')
        self.subtabs.addTab(QWidget(), 'yerel')
        self.scroll_performance = QWidget()
        self.performance = QWidget()

    def _kaydet(self, ad, *args):
        _Sekme.kayit.append((ad,) + args)

    def refresh(self):
        if _Sekme.refresh_hatasi is not None:
            raise _Sekme.refresh_hatasi
        self._kaydet('refresh')

    def scan_if_needed(self):
        self._kaydet('scan_if_needed')

    def scan(self):
        self._kaydet('scan')

    def _stop_hold(self):
        self._kaydet('_stop_hold')

    def prepare_recording_disconnect(self):
        self._kaydet('prepare_recording_disconnect')
        if _Sekme.recording_close is None:
            raise RuntimeError('kayit hatasi')

    def prepare_recording_close(self):
        self._kaydet('prepare_recording_close')
        if _Sekme.recording_close_hatasi is not None:
            raise _Sekme.recording_close_hatasi
        return _Sekme.recording_close

    def prepare_scrcpy_close(self):
        self._kaydet('prepare_scrcpy_close')
        if _Sekme.scrcpy_close_hatasi is not None:
            raise _Sekme.scrcpy_close_hatasi
        return _Sekme.scrcpy_close

    def _sync_device_controls(self):
        self._kaydet('_sync_device_controls')

    def _fetch_dns_status(self):
        self._kaydet('_fetch_dns_status')

    def _sync_refresh_button(self):
        self._kaydet('_sync_refresh_button')

    def _refresh_hardware(self):
        self._kaydet('_refresh_hardware')

    def _open_section(self, scroll, page):
        self._kaydet('_open_section', scroll, page)

    def _sync_snap_controls(self):
        self._kaydet('_sync_snap_controls')

    def _update_selection_state(self):
        self._kaydet('_update_selection_state')

    def _update_action_buttons(self):
        self._kaydet('_update_action_buttons')

    def record_action(self, text):
        self._kaydet('record_action', text)

    def _turbo_boost(self):
        self._kaydet('_turbo_boost')

    def _launch_scrcpy(self):
        self._kaydet('_launch_scrcpy')

    def _toggle_screen_recording(self):
        self._kaydet('_toggle_screen_recording')

    def _show_support_summary(self):
        self._kaydet('_show_support_summary')


class _Cekirdek(QObject):
    log = Signal(str, str)
    connection_changed = Signal(bool, str)
    persistence_error = Signal(str)
    adb_trace = Signal(list, bool, int, str, bool)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.target = ''
        self.connected = False
        self._engine = _Motor()
        self.adb = 'C:/adb/adb.exe'
        self.adb_hata = ''
        self.engine_patlak = False
        self.set_target_kayit = []
        self.connect_kayit = []
        self.connect_patlak = None
        self.disconnect_kayit = []

    @property
    def engine(self):
        if self.engine_patlak:
            raise RuntimeError('motor yok')
        return self._engine

    @property
    def engine_error(self):
        return self.adb_hata

    @property
    def adb_path(self):
        return self.adb

    def set_target(self, target):
        degisti = target != self.target
        self.set_target_kayit.append(target)
        self.target = target
        self.config.last_target = target
        self.config.save()
        if degisti:
            self.connected = False
            self.connection_changed.emit(False, target)

    def connect(self, target=None, timeout=30):
        self.connect_kayit.append((target, timeout))
        if self.connect_patlak is not None:
            raise self.connect_patlak
        t = target or self.target
        self.connected = True
        self.connection_changed.emit(True, t)
        self.log.emit('Baglanti kuruldu', 'INFO')

    def disconnect(self):
        self.disconnect_kayit.append(self.target)
        self.connected = False
        self.connection_changed.emit(False, self.target)


class _Kutu:
    kayitlar = []
    cevap = 0

    @staticmethod
    def _kaydet(kind, args):
        _Kutu.kayitlar.append((kind, args[1], args[2]))

    @staticmethod
    def information(*a, **k):
        _Kutu._kaydet('info', a)

    @staticmethod
    def warning(*a, **k):
        _Kutu._kaydet('uyari', a)
        return _Kutu.cevap

    @staticmethod
    def critical(*a, **k):
        _Kutu._kaydet('kritik', a)


class _SahteIsci(QObject):
    finished_ok = Signal(object)
    failed = Signal(str)
    finished = Signal()
    log = Signal(str)
    progress = Signal(int, int)

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.args = args
        self.kwargs = kwargs
        self.job_name = ''
        self.silent = False
        self.iptal = False
        self.cancel_calls = 0
        self.start_calls = 0
        self.silinecek = False
        self.calisiyor = False

    def cancel(self):
        self.cancel_calls += 1
        self.iptal = True

    def requestInterruption(self):
        self.cancel_calls += 1
        self.iptal = True

    def isInterruptionRequested(self):
        return self.iptal

    def check_cancel(self):
        if self.iptal:
            raise CancelledError('kullanıcı durdurdu')

    def isRunning(self):
        return self.calisiyor

    def start(self):
        self.start_calls += 1
        if _SahteIsci.start_hatasi is not None:
            raise _SahteIsci.start_hatasi

    def deleteLater(self):
        self.silinecek = True

    start_hatasi = None


class _Diyalog(QWidget):
    kayitlar = []
    sonuc = 0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.done_sonuc = None

    def reject(self):
        self.reddedildi = True

    def done(self, sonuc):
        self.done_sonuc = sonuc
        _Diyalog.kayitlar.append(('done', sonuc))

    def exec(self):
        _Diyalog.kayitlar.append(('exec', self))
        return _Diyalog.sonuc


class _Eylemler:
    kayitlar = []

    def __init__(self, parent, actions):
        self.parent = parent
        self.actions = actions
        _Eylemler.kayitlar.append(self)

    def setStyleSheet(self, style):
        self.style = style

    def exec(self):
        return 0


class _IptalsizIsci(QObject):
    """cancel/log/progress kanallari olmayan ciplak isci."""

    finished_ok = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.calisiyor = False
        self.cancel_calls = 0
        self.silinecek = False

    def isRunning(self):
        return self.calisiyor

    def requestInterruption(self):
        self.cancel_calls += 1

    def start(self):
        pass

    def deleteLater(self):
        self.silinecek = True


class _KuklaTampon:
    """LogBus yerine gecen sabit anlik goruntu tamponu."""

    def __init__(self, yeni, toplam):
        self._yeni = list(yeni)
        self._toplam = toplam

    def drain_new(self):
        return list(self._yeni), self._toplam

    def snapshot(self):
        return list(self._yeni)

    def clear(self):
        self._yeni = []


class _PatlakYazi:
    """clear/verticalScrollBar cagrilarinda RuntimeError veren log alani."""

    def verticalScrollBar(self):
        raise RuntimeError('yazi yok')

    def clear(self):
        raise RuntimeError('yazi yok')


class _PatlakEtiket:
    def setText(self, _metin):
        raise RuntimeError('etiket yok')


class _DarCekirdek:
    """persistence_error/adb_trace erisiminde patlayan cekirdek sarmalayicisi."""

    def __init__(self, core):
        self._core = core

    def __getattr__(self, ad):
        if ad in ('persistence_error', 'adb_trace'):
            raise AttributeError('sinyal yok')
        return getattr(self._core, ad)


class _CiplakIsci:
    """Yalnizca isRunning tasiyan en ciplak isci."""

    def __init__(self):
        self.calisiyor = True

    def isRunning(self):
        return self.calisiyor


class _SinyalsizIsci(QObject):
    """finished sinyali olmayan isci: temizlik baglantisi yutulur."""

    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.calisiyor = False
        self.start_calls = 0
        self.silinecek = False

    def isRunning(self):
        return self.calisiyor

    def start(self):
        self.start_calls += 1

    def deleteLater(self):
        self.silinecek = True


class _SessizPatlak(QObject):
    """silent atamasi patlayan isci."""

    finished_ok = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.job_name = ''
        self.calisiyor = False
        self.start_calls = 0
        self.silinecek = False

    @property
    def silent(self):
        return False

    @silent.setter
    def silent(self, _deger):
        raise RuntimeError('sessiz yok')

    def isRunning(self):
        return self.calisiyor

    def start(self):
        self.start_calls += 1

    def deleteLater(self):
        self.silinecek = True


class _KanalsizIsci(QObject):
    """log/progress nitelikleri cagrilamaz olan isci (baglama hatasi yutulur)."""

    finished_ok = Signal(object)
    failed = Signal(str)
    finished = Signal()
    log = 42
    progress = 42

    def __init__(self):
        super().__init__()
        self.job_name = ''
        self.calisiyor = False
        self.start_calls = 0
        self.silinecek = False

    def isRunning(self):
        return self.calisiyor

    def start(self):
        self.start_calls += 1

    def deleteLater(self):
        self.silinecek = True


class _PatlakZamanlayici:
    def stop(self):
        raise RuntimeError('sayac yok')

    def setInterval(self, _ms):
        raise RuntimeError('sayac yok')


class _PatlakTepsi:
    def hide(self):
        raise RuntimeError('tepsi yok')


class _PatlakDugme:
    def setEnabled(self, _deger):
        raise RuntimeError('dugme yok')

    def show(self):
        raise RuntimeError('dugme yok')

    def hide(self):
        raise RuntimeError('dugme yok')


class _PatlakOnay:
    def isChecked(self):
        raise RuntimeError('onay yok')


class _SazanKilit:
    """Kilide girildiginde log yolu onbellegini dolduran sahte kilit."""

    def __init__(self, pencere):
        self.pencere = pencere

    def __enter__(self):
        self.pencere._log_file_day = datetime.datetime.now().strftime('%Y%m%d')
        self.pencere._log_file_path = 'onbellek-yol'
        return self

    def __exit__(self, *_args):
        return False


class _HedefsizCore:
    def __init__(self, core):
        self.config = core.config

    @property
    def target(self):
        raise RuntimeError('hedef okunamaz')


class _KopukSinyal:
    def disconnect(self, _slot):
        raise RuntimeError('kopuk sinyal')


class _KopukCore:
    """Sinyal koparma cagrilari patlayan cekirdek."""

    def __init__(self, core):
        self.config = core.config
        self.log = _KopukSinyal()
        self.connection_changed = _KopukSinyal()
        self.adb_trace = _KopukSinyal()


class _BlokluDugme(QPushButton):
    def blockSignals(self, _durum):
        raise RuntimeError('blok yok')


class _Ekransiz:
    @staticmethod
    def primaryScreen():
        return None


def _sifirla():
    _Sekme.kayit = []
    _Sekme.bekleyen_display = False
    _Sekme.recording_close = True
    _Sekme.recording_close_hatasi = None
    _Sekme.scrcpy_close = True
    _Sekme.scrcpy_close_hatasi = None
    _Sekme.refresh_hatasi = None
    _Kutu.kayitlar = []
    _Kutu.cevap = 0
    _Diyalog.kayitlar = []
    _Diyalog.sonuc = 0
    _Eylemler.kayitlar = []
    _SahteIsci.start_hatasi = None


SEKME_ADLARI = (
    'AppsTab', 'RemoteTab', 'DebloatTab', 'NetworkTab', 'SettingsTab', 'HealthTab',
    'HistoryTab', 'LogcatTab', 'FilesTab', 'InstallTab', 'TerminalTab', 'OverviewTab',
)


def _ortam(monkeypatch, tmp_path):
    """Ortak sahte ortam: yollar + sınıflar yamalanır, çekirdek hazırlanır."""
    _sifirla()
    monkeypatch.setattr(config_mod, 'CONFIG_PATH', str(tmp_path / 'ayarlar.json'))
    monkeypatch.setattr(config_mod, 'LEGACY_CONFIG_PATH', str(tmp_path / 'eski.json'))
    monkeypatch.setattr(config_mod, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(main_mod, 'LOG_DIR', str(tmp_path / 'logs'))
    monkeypatch.setattr(main_mod, 'Worker', _SahteIsci)
    monkeypatch.setattr(main_mod, 'QMessageBox', _Kutu)
    monkeypatch.setattr(main_mod, 'QDialog', _Diyalog)
    monkeypatch.setattr(main_mod, 'ActionsDialog', _Eylemler)
    for ad in SEKME_ADLARI:
        monkeypatch.setattr(main_mod, ad, _Sekme)
    return _Cekirdek(Config(load=False))


@pytest.fixture
def pencere(qtbot, monkeypatch, tmp_path):
    core = _ortam(monkeypatch, tmp_path)
    win = MainWindow(core, selftest=True)
    qtbot.addWidget(win)
    win.show()
    return win, core, tmp_path


# --- LogBus ---


def test_logbus_temel_akis():
    bus = LogBus(capacity=5)
    bus.enqueue('ilk', 'INFO')
    bus.enqueue('ikinci', None)
    yeni, toplam = bus.drain_new()
    assert toplam == 2
    assert [kayit[1:] for kayit in yeni] == [('ilk', 'INFO'), ('ikinci', 'INFO')]
    damga = yeni[0][0]
    assert len(damga) == 12 and damga[2] == ':' and damga[8] == '.'
    # bekleyen yokken yeni kayıt dönmez
    assert bus.drain_new() == ([], 2)
    bus.enqueue('ucuncu', 'WARN')
    bus.enqueue('dorduncu', 'ERROR')
    yeni, toplam = bus.drain_new()
    assert toplam == 4
    assert [kayit[1] for kayit in yeni] == ['ucuncu', 'dorduncu']
    assert bus.drain() == bus.snapshot()
    assert len(bus.snapshot()) == 4
    bus.clear()
    assert bus.snapshot() == []
    assert bus.drain_new() == ([], 0)


def test_logbus_halka_tasmasi():
    bus = LogBus(capacity=2)
    bus.enqueue('bir', 'INFO')
    bus.enqueue('iki', 'INFO')
    bus.enqueue('uc', 'INFO')
    yeni, toplam = bus.drain_new()
    assert [kayit[1] for kayit in yeni] == ['iki', 'uc']
    assert toplam == 2
    assert [kayit[1] for kayit in bus.snapshot()] == ['iki', 'uc']


class _BozukKilit:
    def lock(self):
        raise RuntimeError('kilit yok')

    def unlock(self):
        pass


def test_logbus_hata_yutma(monkeypatch):
    bus = LogBus()
    monkeypatch.setattr(bus, '_mutex', _BozukKilit())
    bus.enqueue('x', 'INFO')
    assert bus.drain() == []
    assert bus.drain_new() == ([], 0)
    assert bus.snapshot() == []
    bus.clear()


# --- kurulum ---


def test_pencere_kurulumu(pencere):
    win, core, _tmp = pencere
    assert win.windowTitle() == 'MiBox Konsol v1.5.1'
    assert win.minimumWidth() == 900 and win.minimumHeight() == 600
    assert win.navigation.count() == 12
    assert win.tabs.count() == 12
    assert win.tabs.tabBar().isHidden() is True
    assert win._navigation_order == (
        win.tabs.indexOf(win.tab_overview), win.tabs.indexOf(win.tab_remote),
        win.tabs.indexOf(win.tab_apps), win.tabs.indexOf(win.tab_install),
        win.tabs.indexOf(win.tab_files), win.tabs.indexOf(win.tab_health),
        win.tabs.indexOf(win.tab_network), win.tabs.indexOf(win.tab_debloat_page),
        win.tabs.indexOf(win.tab_history), win.tabs.indexOf(win.tab_logcat),
        win.tabs.indexOf(win.tab_terminal), win.tabs.indexOf(win.tab_settings),
    )
    assert [win.tabs.tabText(i) for i in range(12)] == [
        'Başlangıç', u'▦ Uygulamalar', u'▣ Kumanda', 'Debloat', u'♥ Sağlık',
        u'⚡ Terminal', u'🕘 Geçmiş', u'≡ Logcat', u'🗀 Dosyalar', u'⭳ Kurulum',
        u'🌐 Ağ', u'⚙ Ayarlar',
    ]
    assert win.log_box.isHidden() is True
    assert win.btn_hide_log.isChecked() is True
    assert win.btn_hide_log.text() == 'Göster'
    assert win.btn_log_toggle.isChecked() is False
    assert win.error_box.isHidden() is True
    assert win.activity_box.isHidden() is True
    assert win.lbl_status.text() == 'Bağlı değil'
    assert win.lbl_target.text() == 'Hedef: -'
    assert win.lbl_link.text() == u'● Çevrimdışı'
    assert win.lbl_adb.text() == 'ADB hazır'
    assert len(win.lbl_clock.text()) == 8
    assert win.chk_verbose.isChecked() is False
    assert win._log_filter == {'INFO', 'WARN', 'ERROR', 'ADB'}
    assert win.page_title.text() == 'Başlangıç'
    assert win.page_subtitle.text() == 'TV’niz için kontrol, uygulamalar ve bakım bir arada.'
    assert win.navigation.currentRow() == 0
    assert win.btn_stop.isHidden() is True
    assert win.btn_stop.isEnabled() is False
    # açılış satırı tampona yazıldı
    win._flush_logs()
    assert 'MiBox Konsol v1.5.1 başlatıldı.' in win.txt_log.toPlainText()


# --- gezinme ---


def test_sayfa_gezintisi(pencere):
    win, _core, _tmp = pencere
    win.navigation.setCurrentRow(1)
    assert win.tabs.currentWidget() is win.tab_remote
    win.tabs.setCurrentWidget(win.tab_history)
    assert win.page_title.text() == 'Geçmiş'
    assert win.page_subtitle.text() == 'İşlem kayıtları ve geri dönüş noktaları.'
    hedef = win._navigation_order.index(win.tabs.indexOf(win.tab_history))
    assert win.navigation.currentRow() == hedef
    # geçersiz sayfa indeksi yok sayılır
    baslik = win.page_title.text()
    win._page_changed(-1)
    win._page_changed(99)
    assert win.page_title.text() == baslik
    # _navigate_row: boş satır güvenli, geçerli satır sekmeyi değiştirir
    win._navigate_row(99)
    win._navigate_row(0)
    assert win.tabs.currentWidget() is win.tab_overview
    win.navigation.setCurrentRow(-1)
    assert win.tabs.currentWidget() is win.tab_overview


def test_kisayollar(pencere):
    from PySide6.QtGui import QShortcut
    win, _core, _tmp = pencere
    tuslar = {s.key().toString() for s in win.findChildren(QShortcut)}
    for beklenen in ('Ctrl+Home', 'Ctrl+1', 'Ctrl+,', 'Ctrl+Shift+O', 'Ctrl+K',
                     'F5', 'Ctrl+L', 'Ctrl+Shift+B', 'Ctrl+Shift+S',
                     'Ctrl+Shift+R', 'Ctrl+Shift+T', 'Ctrl+Shift+N'):
        assert beklenen in tuslar, beklenen


def test_hizli_erisim(pencere, monkeypatch):
    win, _core, _tmp = pencere
    win.btn_quick.click()
    assert len(_Eylemler.kayitlar) == 1
    dlg = _Eylemler.kayitlar[-1]
    assert dlg.parent is win
    assert dlg.style == win.styleSheet()
    actions = dlg.actions
    assert len(actions) == 21
    assert actions[0][0] == 'Başlangıç'
    assert actions[0][1] == 'TV’niz için kontrol, uygulamalar ve bakım bir arada.'
    assert actions[0][3]() is True
    basliklar = [a[0] for a in actions]
    assert basliklar[12:21] == [
        'Popüler TV uygulamaları', 'Yerel APK kurulumu', 'Performans ve bakım',
        'Sayfayı yenile', 'Cihaz adresine git', 'Bağlantı yardımı',
        "Ağdaki TV'leri ara", 'İşlem günlüğü', 'Destek özeti',
    ]
    # sayfa eylemi sekmeyi değiştirir
    actions[basliklar.index('Kumanda')][2]()
    assert win.tabs.currentWidget() is win.tab_remote
    # yenileme koşulu ve eylemi (bağlı yöntem listeye alınırken yakalanır)
    yenile = actions[basliklar.index('Sayfayı yenile')]
    assert yenile[3]() is True
    _Sekme.kayit.clear()
    yenile[2]()
    assert ('refresh',) in _Sekme.kayit
    # adres alanı eylemi etkinken odağı adrese taşır
    adres = actions[basliklar.index('Cihaz adresine git')]
    assert adres[3]() is True
    adres[2]()
    assert win.txt_target.isEnabled() is True
    # katalog ve yerel kurulum eylemleri
    actions[basliklar.index('Popüler TV uygulamaları')][2]()
    assert win.tabs.currentWidget() is win.tab_install
    assert win.tab_install_inner.subtabs.currentIndex() == 0
    actions[basliklar.index('Yerel APK kurulumu')][2]()
    assert win.tab_install_inner.subtabs.currentIndex() == 1
    # performans eylemi
    actions[basliklar.index('Performans ve bakım')][2]()
    assert win.tabs.currentWidget() is win.tab_health
    assert ('_open_section',) in [(k[0],) for k in _Sekme.kayit]


def test_tema_ve_gostergeler(pencere, monkeypatch):
    from mibox_app.ui.theme import colors_for, level_colors_for
    win, core, _tmp = pencere
    core.config.dark_mode = False
    win.apply_theme()
    assert win._palette == colors_for(False)
    assert win._level_colors == level_colors_for(False)
    # geçici olarak sayfa detayları yoksa ikon güncellemesi atlanır
    detaylar = win._page_details
    del win._page_details
    win.apply_theme()
    win._page_details = detaylar
    # bozuk bağlantı göstergesi yutulur
    win.lbl_conn_dot.setStyleSheet = lambda *a: (_ for _ in ()).throw(RuntimeError('yok'))
    win.apply_theme()
    # log yeniden çizimi ve tema tazeleme hataları yutulur
    monkeypatch.setattr(win, '_rebuild_log_view',
                        lambda: (_ for _ in ()).throw(RuntimeError('yok')))
    monkeypatch.setattr(main_mod.kit, 'refresh_theme',
                        lambda *a: (_ for _ in ()).throw(RuntimeError('yok')))
    win.apply_theme()


# --- log paneli ---

def test_log_panel_anahtari(pencere):
    win, _core, _tmp = pencere
    win.btn_log_toggle.setChecked(True)
    assert win.log_box.isVisible() is True
    assert win.btn_hide_log.text() == 'Gizle'
    assert win.btn_hide_log.isChecked() is False
    win._toggle_log(True)
    assert win.log_box.isVisible() is False
    assert win.btn_hide_log.text() == 'Göster'
    assert win.btn_log_toggle.isChecked() is False
    # btn_hide_log sinyaliyle kapat/aç (durum değişikliği sinyal üretmelidir)
    win.btn_hide_log.setChecked(True)
    assert win.log_box.isVisible() is False
    assert win.btn_log_toggle.isChecked() is False
    win.btn_hide_log.setChecked(False)
    assert win.log_box.isVisible() is True
    # bozuk kutu: setVisible RuntimeError yutulur, üst düğme eşitlenir
    class _PatlakKutu:
        def setVisible(self, _goster):
            raise RuntimeError('yok')
    orijinal = win.log_box
    win.log_box = _PatlakKutu()
    win._toggle_log(False)
    win._toggle_log(True)
    win.log_box = orijinal
    # log_box özniteliği yoksa _toggle_log_panel hata yutar
    del win.log_box
    win._toggle_log_panel(True)
    win._toggle_log_panel(False)
    win.log_box = orijinal
    assert win.log_box.isVisible() is True


# --- sayfa yenileme ---

def test_sayfa_yenileme(pencere):
    win, core, _tmp = pencere
    # yenilenebilir eylem yok -> durum mesajı
    bos = QWidget()
    win.tabs.addTab(bos, 'bos')
    win.tabs.setCurrentWidget(bos)
    win.refresh_current_page()
    assert win.status.currentMessage() == 'Bu sayfada yenilenecek liste yok.'
    # bağlantı gerekli sayfa + bağlantısız -> uyarı ve odak
    win.tabs.setCurrentWidget(win.tab_apps)
    core.connected = False
    _Sekme.kayit.clear()
    win.refresh_current_page()
    assert win.status.currentMessage() == 'Yenilemek için önce cihaza bağlanın.'
    assert ('refresh',) not in _Sekme.kayit
    # bağlantı var -> callback çağrılır
    core.connected = True
    win.refresh_current_page()
    assert ('refresh',) in _Sekme.kayit
    # meşgulken çağrılmaz
    win.tab_apps._busy = True
    _Sekme.kayit.clear()
    win.refresh_current_page()
    assert ('refresh',) not in _Sekme.kayit
    win.tab_apps._busy = False
    # kaydırma alanına sarılı sayfa da yenilenir
    win.tabs.setCurrentWidget(win.tab_remote)
    _Sekme.kayit.clear()
    win.refresh_current_page()
    assert ('refresh',) in _Sekme.kayit


# --- bağlantı yardımı ---

def test_baglanti_yardimi(pencere):
    from PySide6.QtWidgets import QLabel
    win, _core, _tmp = pencere
    _Diyalog.sonuc = 0
    win.open_connection_help()
    tur, dlg = _Diyalog.kayitlar[-1]
    assert tur == 'exec'
    assert dlg.windowTitle() == 'TV’ye bağlanma'
    assert dlg.parent() is win
    assert len(dlg.findChildren(QLabel)) == 8
    # sonuç 10: adres alanına odak
    odak = []
    win.focus_target = lambda: odak.append(1)
    _Diyalog.sonuc = 10
    win.open_connection_help()
    assert odak == [1]
    # sonuç 11: ağ sayfasına geç
    _Diyalog.sonuc = 11
    win.open_connection_help()
    assert win.tabs.currentWidget() is win.tab_network
    _Diyalog.sonuc = 0


# --- hata şeridi + aktivite ---

def test_hata_seridi(pencere):
    win, _core, _tmp = pencere
    win._show_error('Etiket', 'kisa hata')
    assert win.error_box.isVisible() is True
    assert win.lbl_error.text() == 'Etiket: kisa hata'
    assert win.lbl_error.toolTip() == 'Etiket: kisa hata'
    uzun = 'x' * 400
    win._show_error('Etiket', uzun)
    assert win.lbl_error.text() == 'Etiket: ' + 'x' * 352 + '…'
    assert win.lbl_error.toolTip() == 'Etiket: ' + 'x' * 400
    # kapanışta yok sayılır
    win._closing = True
    win._show_error('Etiket', 'yeni')
    assert 'yeni' not in win.lbl_error.text()
    win._closing = False
    win._on_persistence_error('kayit hatasi')
    assert 'Etiket: ' not in win.lbl_error.text()
    assert 'Ayarlar kaydedilemedi: kayit hatasi' in win.lbl_error.text()
    assert win.error_box.isVisible() is True
    win.error_box.hide()


def test_aktivite_gostergesi(pencere):
    win, _core, _tmp = pencere
    win._update_activity()
    assert win.activity_box.isHidden() is True
    win._activity[1] = ('Tarama', 3, 10)
    win._activity[2] = ('Kurulum', 0, 0)
    win._update_activity()
    assert win.activity_box.isVisible() is True
    assert win.lbl_activity.text() == 'Kurulum · 2 işlem çalışıyor'
    assert win.activity_progress.maximum() == 0
    win._activity.pop(2)
    win._activity[1] = ('Tarama', 3, 10)
    win._update_activity()
    assert win.lbl_activity.text() == 'Tarama'
    assert win.activity_progress.maximum() == 10
    assert win.activity_progress.value() == 3
    win._activity[1] = ('Tarama', 15, 10)
    win._update_activity()
    assert win.activity_progress.value() == 10
    win._activity[3] = ('X', 0, 1)
    win._closing = True
    win._update_activity()
    assert win.activity_box.isHidden() is True
    win._closing = False
    win._activity.clear()


# --- uyarı yolları (özelleştirilmiş kurulum) ---

def test_adb_uyarisi_selftest(qtbot, monkeypatch, tmp_path):
    core = _ortam(monkeypatch, tmp_path)
    core.adb = None
    core.adb_hata = 'ADB bulunamadı.'
    win = MainWindow(core, selftest=True)
    qtbot.addWidget(win)
    win.show()
    win._flush_logs()
    metin = win.txt_log.toPlainText()
    assert 'ADB selftest sırasında kullanılamıyor: ADB bulunamadı.' in metin
    assert not _Kutu.kayitlar


def test_adb_uyarisi_kutu(qtbot, monkeypatch, tmp_path):
    core = _ortam(monkeypatch, tmp_path)
    core.adb = None
    core.adb_hata = 'ADB bulunamadı.'
    win = MainWindow(core, selftest=False)
    qtbot.addWidget(win)
    win.show()
    assert ('uyari', 'ADB', 'ADB bulunamadı.') in _Kutu.kayitlar
    win._closing = True
    win.close()


def test_ayar_uyarisi(qtbot, monkeypatch, tmp_path):
    core = _ortam(monkeypatch, tmp_path)
    core.config.load_warning = 'geçersiz değer atlandı\nikinci satır'
    win = MainWindow(core, selftest=True)
    qtbot.addWidget(win)
    win.show()
    win._flush_logs()
    assert 'Ayar kurtarma: geçersiz değer atlandı · ikinci satır' in \
        win.txt_log.toPlainText()
    assert win.error_box.isVisible() is True
    assert win.lbl_error.text() == 'Ayar kurtarma: geçersiz değer atlandı\nikinci satır'


# --- hedef yardımcıları ---

def test_gecerli_hedef_kontrolu(pencere):
    win, _core, _tmp = pencere
    for iyi in ('192.0.2.1:5555', '[fe80::1]:5555', '[::1]:5555',
                'tv.local:5555', 'x:1'):
        assert win._valid_target(iyi), iyi
    for kotu in ('', '192.0.2.1', '192.0.2.1:0', '192.0.2.1:70000', 'a:b:5555',
                 ':5555', '1.2.3:5555', 'h hubby:5555', 'fe80::1:5555',
                 'tv.local:abc'):
        assert not win._valid_target(kotu), kotu


def test_gecerli_seri_kontrolu(pencere):
    win, _core, _tmp = pencere
    assert win._valid_device_serial('a.b.c:d_1')
    assert win._valid_device_serial('emulator-5554')
    for kotu in ('', '  ', '-x1', '-'):
        assert not win._valid_device_serial(kotu), kotu


def test_serilere_benzerlik(pencere):
    win, _core, _tmp = pencere
    assert win._looks_like_device_serial('emulator-5554')
    assert win._looks_like_device_serial('TV_BOX1')  # alt çizgili
    assert win._looks_like_device_serial('A1B2C3D4E5F')  # büyük harf + rakam
    for hayir in ('a.b.c', 'tv', 'tv-x', 'ab1'):
        assert not win._looks_like_device_serial(hayir), hayir
    assert win._is_ipv4_address('127.0.0.1')
    assert not win._is_ipv4_address('127.0.0.256')
    assert not win._is_ipv4_address('')


def test_hedef_alanlari_ata(pencere):
    win, _core, _tmp = pencere
    win._set_target_fields('192.0.2.1:5555')
    assert win.txt_target.text() == '192.0.2.1'
    assert win.txt_port.text() == '5555'
    assert win._target_kind == 'network'
    win._set_target_fields('emulator-5554')
    assert win.txt_target.text() == 'emulator-5554'
    assert win.txt_port.text() == ''
    assert win._target_kind == 'serial'
    win._set_target_fields('192.0.2.9')
    assert win.txt_port.text() == '5555'
    assert win._target_kind == 'network'
    win._set_target_fields('MY-TV1')
    assert win._target_kind == 'serial'
    win._set_target_fields('')
    assert win.txt_target.text() == ''
    assert win._target_kind is None
    win._set_target_fields('192.168.1.x:5555')
    assert win._target_kind is None
    assert win.txt_target.text() == ''
    win._target_address_edited('x')
    assert win._target_kind is None


def test_hedef_alandan_cikarma(pencere, monkeypatch):
    win, _core, _tmp = pencere
    # boş alan
    win._set_target_fields('')
    assert win._target_from_fields() == ''
    # ayrı adres + boş port -> 5555 tamamlanır
    win._set_target_fields('192.0.2.1')
    win._target_address_edited('x')  # kind temizi
    assert win._target_from_fields() == '192.0.2.1:5555'
    assert win.txt_port.text() == '5555'
    assert win._target_kind == 'network'
    # yapıştırılmış adres:PORT bölünür (kind None iken)
    win._target_address_edited('x')
    win.txt_target.setText('192.0.2.2:6666')
    assert win._target_from_fields() == '192.0.2.2:6666'
    assert win.txt_target.text() == '192.0.2.2'
    assert win.txt_port.text() == '6666'
    # network kind + geçersiz adres, portsuz -> aday geri döner
    win._target_kind = 'network'
    win.txt_target.setText('lahuta')
    win.txt_port.setText('')
    assert win._target_from_fields() == 'lahuta'
    assert win._target_kind == 'network'
    # portsuz ama DEVICE_SERIAL_RE'a uyan adres seriye döner (listedede yok)
    win._target_kind = None
    monkeypatch.setattr(win, '_is_ipv4_address', lambda _a: False)
    win.txt_target.setText('a.b.c')
    assert win._target_from_fields() == 'a.b.c'
    assert win._target_kind == 'serial'
    # emulator kalıbı (kind sıfırlanarak) lookslike yoluyla seriye döner
    win._target_kind = None
    win.txt_target.setText('emulator-99')
    assert win._target_from_fields() == 'emulator-99'
    assert win._target_kind == 'serial'
    # listede bulunan seriler seriye döner
    win._target_kind = None
    win.txt_target.setText('dev.x')
    win.cmb_devices.clear()
    win.cmb_devices.addItem('dev · dev.x', 'dev.x')
    assert win._target_from_fields() == 'dev.x'
    assert win._target_kind == 'serial'
    # serial kind korunur
    win._target_kind = 'serial'
    win.txt_target.setText('A1B2C3D4E5F')
    assert win._target_from_fields() == 'A1B2C3D4E5F'
    assert win._target_kind == 'serial'
    # geçersiz aday aynen döner
    win._target_kind = None
    win.txt_target.setText('@@@')
    assert win._target_from_fields() == '@@@'
    assert win._target_kind is None


def test_hedef_esitleme(pencere, monkeypatch):
    win, core, _tmp = pencere
    win._set_target_fields('')
    # boş alan: bir şey yapmaz
    core.set_target_kayit.clear()
    win._sync_target()
    assert not core.set_target_kayit
    # geçerli ad + boşta çalışma -> adres çekirdeğe yazılır
    win._set_target_fields('192.0.2.1')
    core.set_target_kayit.clear()
    win._sync_target()
    assert core.set_target_kayit == ['192.0.2.1:5555']
    assert win.lbl_target.text() == 'Hedef: 192.0.2.1:5555'
    assert core.config.last_target == '192.0.2.1:5555'
    # bağlıyken farklı ad: yalnız durum mesajı
    core.connected = True
    win.txt_target.setText('192.0.2.7')
    win.txt_port.setText('5556')
    core.set_target_kayit.clear()
    win._sync_target()
    assert core.set_target_kayit == []
    assert core.target == '192.0.2.1:5555'
    assert win.status.currentMessage() == \
        'Yeni adres hazır. Geçiş için Bağlan düğmesine basın.'
    # meşgulken de adrese dokunulmaz
    core.connected = False
    win._connection_busy = True
    win.txt_target.setText('192.0.2.7')
    win.txt_port.setText('5556')
    core.set_target_kayit.clear()
    win._sync_target()
    assert core.set_target_kayit == []
    assert core.target == '192.0.2.1:5555'
    win._connection_busy = False
    # çalışan iş varken de bekleme mesajı
    w = _SahteIsci(lambda: None)
    w.calisiyor = True
    win._workers.append(w)
    win.txt_target.setText('192.0.2.8')
    win.txt_port.setText('5557')
    core.set_target_kayit.clear()
    win._sync_target()
    assert core.set_target_kayit == []
    assert 'Yeni adres' in win.status.currentMessage()
    win._workers.clear()
    # geçersiz ad: ipucu mesajı
    monkeypatch.setattr(win, '_target_from_fields', lambda: 'lahuta')
    win._sync_target()
    assert win.status.currentMessage().startswith('IP/host:PORT')


def test_cihaz_durum_bildirimi(pencere):
    win, _core, _tmp = pencere
    assert win._device_state_info('device')[0] == 'Hazır'
    assert win._device_state_info('unauthorized')[0] == 'Yetki bekliyor'
    assert win._device_state_info('offline')[0] == 'Çevrimdışı'
    assert win._device_state_info('no permissions')[0] == 'Erişim izni yok'
    assert win._device_state_info('bootloader')[0] == 'Önyükleyici'
    assert win._device_state_info('recovery')[0] == 'Kurtarma modu'
    assert win._device_state_info('sideload')[0] == 'Yan yükleme modu'
    assert win._device_state_info('rescue')[0] == 'Kurtarma modu'
    assert win._device_state_info('weird')[0] == 'Bilinmeyen durum'


# --- cihaz ve geçmiş listeleri ---

def test_gecmis_kutusu(pencere):
    win, core, _tmp = pencere
    core.config.device_history = ['192.0.2.1:5555', '192.0.2.2:5555']
    core.target = '192.0.2.2:5555'
    core.config.last_target = core.target
    win.txt_target.setText('192.0.2.2')
    win.txt_port.setText('5555')
    core.set_target_kayit.clear()
    win.refresh_history_combo()
    assert win.cmb_history.count() == 3
    assert win.cmb_history.itemText(0) == 'Geçmiş...'
    assert win.cmb_history.itemData(2) == '192.0.2.2:5555'
    # mevcut hedef eşleşen öğede seçilir
    assert win.cmb_history.currentIndex() == 2
    # seçim alanları doldurur
    win._on_history_picked(1)
    assert win.txt_target.text() == '192.0.2.1'
    assert core.set_target_kayit == ['192.0.2.1:5555']
    # verisi boş öğe etkisizdir
    core.set_target_kayit.clear()
    win._on_history_picked(0)
    assert core.set_target_kayit == []


def test_cihaz_listesi_doldurma(pencere):
    win, core, _tmp = pencere
    devs = [{'id': '192.0.2.1:5555', 'state': 'device'},
            {'id': 'emulator-5554', 'state': 'unauthorized'},
            {'id': 'x:5555', 'state': 'offline'}]
    core._engine.device_listesi = devs
    win.refresh_device_combo()
    isci = win._device_list_worker
    assert isci is not None
    assert win.lbl_device_hint.text() == 'ADB cihaz listesi yenileniyor…'
    veri = isci.args[0]()
    assert ('devices',) in core._engine.calls
    isci.finished_ok.emit(veri)
    isci.finished.emit()
    assert win._device_list_worker is None  # finished temizliği
    assert win.cmb_devices.count() == 4
    assert win.cmb_devices.itemText(0) == 'Cihaz seçin'
    assert win.cmb_devices.itemData(1) == '192.0.2.1:5555'
    assert 'Hazır · 192.0.2.1:5555' == win.cmb_devices.itemText(1)
    assert 'Yetki bekliyor · emulator-5554' == win.cmb_devices.itemText(2)
    # boş listenin ipucu
    core._engine.device_listesi = []
    win.refresh_device_combo()
    win._device_list_worker.finished_ok.emit([])
    win._device_list_worker.finished.emit()
    assert win.cmb_devices.itemText(0) == 'Cihaz bulunamadı'
    assert 'ADB listesinde cihaz yok' in win.lbl_device_hint.text()
    # listeden seçim
    core._engine.device_listesi = devs
    win.refresh_device_combo()
    isci3 = win._device_list_worker
    isci3.finished_ok.emit(isci3.args[0]())
    isci3.finished.emit()
    assert win._device_list_worker is None
    win._on_device_picked(2)
    assert win.txt_target.text() == 'emulator-5554'
    assert win.txt_port.text() == ''
    assert 'TV ekranındaki USB hata ayıklama iznini onaylayın' in \
        win.lbl_device_hint.text()
    # meşgulken seçim yok sayılır
    win._connection_busy = True
    win.txt_target.setText('farkli')
    win._on_device_picked(1)
    assert win.txt_target.text() == 'farkli'
    win._connection_busy = False
    # boş veri etkisiz
    win.txt_target.setText('ayni')
    win._on_device_picked(0)
    assert win.txt_target.text() == 'ayni'


def test_cihaz_listesi_otomatik_secim(pencere):
    win, core, _tmp = pencere
    core._engine.device_listesi = [{'id': '192.0.2.3:5555', 'state': 'device'}]
    core.connected = False
    core.set_target_kayit.clear()
    win.refresh_device_combo(auto_select=True)
    isci = win._device_list_worker
    isci.finished_ok.emit(isci.args[0]())
    # alanlar doldurulur; iş sürdüğünden çekirdek güncellenmez (durum uyarısı
    # önceki msajın yerini 'Cihaz listesini yenileme tamamlandı.' alır)
    assert win.txt_target.text() == '192.0.2.3'
    assert win.txt_port.text() == '5555'
    assert core.set_target_kayit == []
    assert win.status.currentMessage() == \
        'Cihaz listesini yenileme tamamlandı.'


def test_cihaz_listesi_hatalar(pencere, monkeypatch):
    win, core, _tmp = pencere
    # motor yoksa hata günlüğe yazılır
    core.engine_patlak = True
    win.refresh_device_combo()
    assert getattr(win, '_device_list_worker', None) is None
    # liste işi başarısızsa ipucu değişir
    core.engine_patlak = False
    win.refresh_device_combo()
    win._device_list_worker.failed.emit('listede yok')
    assert 'Cihaz listesi okunamadı' in win.lbl_device_hint.text()
    # iş zaten sürerken yenisi başlamaz
    elem = object()
    win._device_list_worker = elem
    win.refresh_device_combo()
    assert win._device_list_worker is elem
    win._device_list_worker = None
    # başlatma hatası temizlenip yeniden yükseltilir
    _SahteIsci.start_hatasi = RuntimeError('başlamaz')
    with pytest.raises(RuntimeError):
        win.refresh_device_combo()
    _SahteIsci.start_hatasi = None
    assert win._device_list_worker is None
    # kapanışta doldurma etkisizdir
    win._closing = True
    win._fill_device_combo([{'id': 'x:5555', 'state': 'device'}])
    win._closing = False
    # geçersiz hedef çözümü: doldurma erken çıkar
    monkeypatch.setattr(win, '_target_from_fields',
                        lambda: (_ for _ in ()).throw(RuntimeError('yok')))
    win._fill_device_combo([{'id': 'y:5555', 'state': 'device'}])
    # liste hiç doldurulmadı: kutu boş kalır
    assert win.cmb_devices.count() == 0


# --- bağlantı akışı ---

def test_baglanti_akisi(pencere):
    win, core, _tmp = pencere
    win._set_target_fields('192.0.2.5')
    win.on_connect()
    assert core.set_target_kayit == ['192.0.2.5:5555']
    assert core.config.device_history == ['192.0.2.5:5555']
    assert win._connection_busy is True
    assert win.btn_connect.text() == 'Bağlanıyor…'
    assert win.lbl_status.text() == 'TV yanıtı bekleniyor…'
    assert win.btn_connect.isEnabled() is False
    assert win.btn_disconnect.isEnabled() is False
    assert win.txt_target.isEnabled() is False
    assert win.cmb_devices.isEnabled() is False
    assert _Sekme.kayit == [('refresh',), ('_sync_device_controls',)]
    assert len(win._workers) == 1
    isci = win._workers[-1]
    isci.args[0]()
    assert core.connect_kayit == [('192.0.2.5:5555', 30)]
    isci.finished_ok.emit({'ok': True})
    assert win._connection_busy is False
    assert win.btn_connect.text() == 'Bağlan'
    assert win.lbl_status.text() == 'Bağlı: 192.0.2.5:5555'
    assert win.btn_connect.isEnabled() is True
    assert win.btn_disconnect.isEnabled() is True
    assert win.txt_target.isEnabled() is True
    assert win._reconnect_target == '192.0.2.5:5555'
    # auto refresh + durum yardımcıları çağrıldı
    assert ('refresh',) in _Sekme.kayit
    assert '_update_action_buttons' in [k[0] for k in _Sekme.kayit]
    assert '_sync_refresh_button' in [k[0] for k in _Sekme.kayit]
    assert '_sync_snap_controls' in [k[0] for k in _Sekme.kayit]
    assert '_update_selection_state' in [k[0] for k in _Sekme.kayit]
    assert '_sync_device_controls' in [k[0] for k in _Sekme.kayit]
    assert '_fetch_dns_status' in [k[0] for k in _Sekme.kayit]
    assert '_refresh_hardware' in [k[0] for k in _Sekme.kayit]
    assert ('display.read',) in _Sekme.kayit


def test_baglanti_gecersiz_hedef(pencere):
    win, core, _tmp = pencere
    win.txt_target.setText('h hubby')
    win.on_connect()
    assert _Kutu.kayitlar[0][0] == 'uyari'
    assert _Kutu.kayitlar[0][1] == 'Hedef'
    assert not win._workers
    # meşgulken erken dönüş
    win._connection_busy = True
    _Kutu.kayitlar.clear()
    win.on_connect()
    assert not _Kutu.kayitlar
    win._connection_busy = False
    # çalışan işler engel olur
    isci = _SahteIsci(lambda: None)
    isci.calisiyor = True
    win._workers.append(isci)
    win.txt_target.setText('192.0.2.4')
    win.txt_port.setText('')
    _Kutu.kayitlar.clear()
    win.on_connect()
    assert win.lbl_error.text() == \
        ('Bağlantı başlatılamadı: Çalışan işlemlerin bitmesini bekleyin '
         'veya Durdur düğmesini kullanın.')
    win._workers.clear()
    win.error_box.hide()


def test_baglanti_kurulum_hatasi(pencere):
    win, core, _tmp = pencere
    win._set_target_fields('192.0.2.5')
    _SahteIsci.start_hatasi = RuntimeError('başlatılamadı')
    win.on_connect()
    _SahteIsci.start_hatasi = None
    assert win._connection_busy is False
    assert win.btn_connect.text() == 'Bağlan'
    assert win.btn_connect.isEnabled() is True
    assert win.lbl_error.text() == 'Bağlantı başlatılamadı: başlatılamadı'
    win.error_box.hide()
    # başarısızlık geri çağrımı
    win._set_target_fields('192.0.2.5')
    win.on_connect()
    win._workers[-1].failed.emit('usb yok')
    assert win._connection_busy is False
    assert win.btn_connect.text() == 'Bağlan'
    assert win.btn_connect.isEnabled() is True


# --- bağlantı kesme ---

def test_baglanti_kesme(pencere):
    win, core, _tmp = pencere
    core.connected = True
    core.target = '192.0.2.5:5555'
    win._set_target_fields('192.0.2.5')
    win.on_disconnect()
    assert ('prepare_recording_disconnect',) in _Sekme.kayit
    assert win._disconnect_pending is False  # doğrudan başlatıldı
    assert win._disconnect_in_progress is True
    assert win._connection_busy is True
    assert win.lbl_status.text() == 'İşlemler durduruluyor…'
    assert win.btn_disconnect.text() == 'Kesiliyor…'
    assert win.btn_disconnect.isEnabled() is False
    assert len(win._workers) == 1
    isci = win._workers[-1]
    assert getattr(isci, '_allow_during_disconnect', False) is True
    isci.args[0]()
    assert core.disconnect_kayit == ['192.0.2.5:5555']
    isci.finished_ok.emit(None)
    assert win._disconnect_in_progress is False
    assert win._connection_busy is False
    assert win.btn_disconnect.text() == 'Bağlantıyı kes'
    win._flush_logs()
    assert 'Bağlantı kesildi.' in win.txt_log.toPlainText()


def test_baglanti_kesme_kapilari(pencere):
    win, core, _tmp = pencere
    # meşgulken erken dönüş
    win._connection_busy = True
    win.on_disconnect()
    assert ('prepare_recording_disconnect',) not in _Sekme.kayit
    win._connection_busy = False
    # kapanışta erken dönüş
    win._closing = True
    win.on_disconnect()
    assert ('prepare_recording_disconnect',) not in _Sekme.kayit
    win._closing = False
    # kayıt hazırlığı patlarsa yutulur ve akış sürer
    _Sekme.recording_close = None  # prepare_recording_disconnect patlatır
    win.on_disconnect()
    _Sekme.recording_close = True
    assert win._disconnect_pending is False
    assert win._disconnect_in_progress is True
    assert len(win._workers) == 1
    win._flush_logs()
    assert 'Ekran kaydı durdurulurken hata' in win.txt_log.toPlainText()
    # kesme işini bitir
    win._workers[-1].finished_ok.emit(None)


def test_baglanti_kesme_geciktirme(pencere):
    win, core, _tmp = pencere
    core.connected = True
    core.target = 'tv-target'
    isci = _SahteIsci(lambda: None)
    isci.calisiyor = True
    korunmus = _SahteIsci(lambda: None)
    korunmus.calisiyor = True
    korunmus._preserve_from_cancel = True
    win._workers.extend([isci, korunmus])
    win.on_disconnect()
    assert isci.cancel_calls == 1
    assert korunmus.cancel_calls == 0
    assert win._disconnect_pending is True
    assert win._disconnect_in_progress is True
    # cihaz işleri sürerken kesme başlatılmaz
    assert len(win._workers) == 2
    # işler bitince bekçi kesmeyi başlatır
    isci.calisiyor = False
    korunmus.calisiyor = False
    isci.finished.emit()
    assert win._disconnect_pending is False
    assert win._disconnect_in_progress is True
    assert len(win._workers) == 3


def test_kesme_yardimcilari(pencere):
    win, core, _tmp = pencere
    # bayrak yoksa erken dönüş
    win._start_disconnect()
    assert not win._workers
    # kapanışta da başlamaz
    win._disconnect_pending = True
    win._closing = True
    win._start_disconnect()
    assert not win._workers
    win._closing = False
    # cihaz işi sürerken bekler
    isci = _SahteIsci(lambda: None)
    isci.calisiyor = True
    win._workers.append(isci)
    win._start_disconnect()
    assert win._disconnect_pending is True
    assert len(win._workers) == 1
    win._workers.clear()
    # başlatma hatası: geri sarma + şerit
    _SahteIsci.start_hatasi = RuntimeError('kesilemez')
    win._start_disconnect()
    _SahteIsci.start_hatasi = None
    assert win._disconnect_pending is False
    assert win._connection_busy is False
    assert win.lbl_error.text() == 'Bağlantı kesme başlatılamadı: kesilemez'
    win.error_box.hide()


# --- bekçi ---

def test_bekci_isci_kontrolleri(pencere):
    win, _core, _tmp = pencere
    assert win._watchdog_is_running() is False
    patlak = _SahteIsci(lambda: None)
    patlak.isRunning = lambda: (_ for _ in ()).throw(RuntimeError('silindi'))
    win._watchdog_worker = patlak
    assert win._watchdog_is_running() is False
    assert win._watchdog_worker is None
    kosan = _SahteIsci(lambda: None)
    kosan.calisiyor = True
    win._watchdog_worker = kosan
    assert win._watchdog_is_running() is True
    win._watchdog_worker = None
    # kesme beklerken boşta kalan bekçi işi kesmeyi başlatır
    win._disconnect_pending = True
    win._watchdog_worker_finished()
    assert win._disconnect_pending is False
    assert len(win._workers) == 1


def test_cihaz_iscileri_kontrolu(pencere):
    win, _core, _tmp = pencere
    assert win._device_workers_running() is False
    win.tab_remote_inner._recording_starting = True
    assert win._device_workers_running() is True
    win.tab_remote_inner._recording_starting = False
    _Sekme.bekleyen_display = True
    assert win._device_workers_running() is True
    _Sekme.bekleyen_display = False
    # ekran paneli sorgusu patlarsa yutulur
    win.tab_health_inner.display_panel._has_pending_display_transaction = \
        lambda: (_ for _ in ()).throw(AttributeError('yok'))
    assert win._device_workers_running() is False
    # koşan işçi engel sayılır
    isci = _SahteIsci(lambda: None)
    isci.calisiyor = True
    win._workers.append(isci)
    assert win._device_workers_running() is True
    # RuntimeError veren işçi atlanır
    isci.calisiyor = False
    isci.isRunning = lambda: (_ for _ in ()).throw(RuntimeError('yok'))
    assert win._device_workers_running() is False


def test_bekci_akisi(pencere):
    win, core, _tmp = pencere
    win._selftest = False
    core.target = '192.0.2.5:5555'
    win._reconnect_target = core.target
    core.connected = True
    win._watchdog()
    isci = win._watchdog_worker
    assert isci is not None
    assert isci.args[0]() is True
    assert ('connect', '192.0.2.5:5555', 8, 2) == core._engine.calls[-1]
    isci.finished_ok.emit(True)
    assert win._watch_fail == 0
    assert core.connected is True
    # kopmuşken başarı: yeniden bağlanma haberi verilir
    isci.calisiyor = True
    win._workers.append(isci)  # rozet işi sayısı karışmasın diye elle tut
    core.connected = False
    win._watchdog()
    isci2 = win._watchdog_worker
    isci2.args[0]()
    isci2.finished_ok.emit(True)
    assert core.connected is True
    assert win._watch_fail == 0
    # ardışık hata: sayaç artar, ikincide kopma ilan edilir
    core._engine.connect_patlak = True
    win._watch_fail = 0
    core.connected = True
    win._watchdog()
    isci3 = win._watchdog_worker
    assert isci3.args[0]() is False
    isci3.finished_ok.emit(False)
    assert win._watch_fail == 1
    assert core.connected is True
    win._watchdog()
    isci4 = win._watchdog_worker
    isci4.args[0]()
    isci4.finished_ok.emit(False)
    assert win._watch_fail == 2
    assert core.connected is False
    win._flush_logs()
    assert 'Bekçi: bağlantı koptu, yeniden deneniyor' in win.txt_log.toPlainText()
    # sonraki testlerin kapanışına çalışan iş bırakma
    for _w in list(win._workers):
        _w.calisiyor = False
    win._workers.clear()


def test_bekci_erken_donusler(pencere):
    win, core, _tmp = pencere
    win._selftest = False
    core.target = 't:1'
    win._reconnect_target = 't:1'
    for ayar in ('_closing', '_close_pending', '_connection_busy',
                 '_disconnect_pending', '_disconnect_in_progress'):
        setattr(win, ayar, True)
        win._watchdog()
        setattr(win, ayar, False)
        assert win._watchdog_worker is None
    # selftest kipinde bekçi çalışmaz
    win._selftest = True
    win._watchdog()
    assert win._watchdog_worker is None
    win._selftest = False
    # hedef yok / eşleşmiyor / cihaz işi sürüyor
    core.target = ''
    win._watchdog()
    assert win._watchdog_worker is None
    core.target = 't:1'
    win._reconnect_target = 'baska:1'
    win._watchdog()
    assert win._watchdog_worker is None
    win._reconnect_target = 't:1'
    isci = _SahteIsci(lambda: None)
    isci.calisiyor = True
    win._workers.append(isci)
    win._watchdog()
    assert win._watchdog_worker is None
    win._workers.clear()
    # başlatma hatası: günlüğe yazılır, işaretçi temizlenir
    _SahteIsci.start_hatasi = RuntimeError('bekci baslamaz')
    win._watchdog()
    _SahteIsci.start_hatasi = None
    assert win._watchdog_worker is None
    win._flush_logs()
    assert 'Bağlantı yoklaması başlatılamadı: bekci baslamaz' in \
        win.txt_log.toPlainText()


def test_baglanti_degisim_gostergeleri(pencere):
    win, core, _tmp = pencere
    core.connection_changed.emit(False, '192.0.2.5:5555')
    assert win.lbl_status.text() == 'Bağlı değil'
    assert win.btn_disconnect.isEnabled() is False
    assert win.lbl_link.text() == u'● Çevrimdışı'
    assert win.lbl_target.text() == 'Hedef: 192.0.2.5:5555'
    assert win.lbl_device_badge.isHidden() is True
    assert win.lbl_conn_dot.toolTip() == u'Çevrimdışı'
    core.target = '192.0.2.5:5555'
    core.connected = True
    core.connection_changed.emit(True, '192.0.2.5:5555')
    assert win.lbl_status.text() == 'Bağlı: 192.0.2.5:5555'
    assert win.btn_disconnect.isEnabled() is True
    assert win.lbl_link.text() == u'● Çevrimiçi'
    assert win.lbl_conn_dot.toolTip() == u'Çevrimiçi'
    isci = win._workers[-1]
    model, surum = isci.args[0]()
    assert (model, surum) == ('TV Model', '12')
    isci.finished_ok.emit((model, surum))
    assert win.lbl_device_badge.text() == '📺 TV Model (Android 12)'
    assert win.lbl_device_badge.isHidden() is False
    # bayat hedef: rozet güncellenmez
    core.connection_changed.emit(True, '192.0.2.7:5555')
    isci2 = win._workers[-1]
    core.target = '192.0.2.9:5555'
    isci2.finished_ok.emit(('Baska', '11'))
    assert win.lbl_device_badge.text() == '📺 TV Model (Android 12)'
    # model okunamazsa hedef adı gösterilir, sürüm boş kalır
    core.target = '192.0.2.8:5555'
    core._engine.getprop_patlak = True
    core.connection_changed.emit(True, '192.0.2.8:5555')
    isci3 = win._workers[-1]
    isci3.finished_ok.emit(isci3.args[0]())
    assert win.lbl_device_badge.text() == '📺 192.0.2.8:5555'
    # meşgulken bağlantı kes düğmesi kapalı kalır
    win._connection_busy = True
    core.connection_changed.emit(True, '192.0.2.8:5555')
    assert win.btn_disconnect.isEnabled() is False
    win._connection_busy = False
    # kopunca rozet gizlenir
    core.connection_changed.emit(False, '192.0.2.8:5555')
    assert win.lbl_device_badge.isHidden() is True


# --- çalıştırıcı (_run) ---

def test_run_kapilari(pencere):
    win, _core, _tmp = pencere
    win._closing = True
    isci = _SahteIsci(lambda: None)
    win._run(isci)
    assert isci.start_calls == 0
    assert isci.silinecek is True
    assert not win._workers
    win._closing = False
    win._close_pending = True
    isci2 = _SahteIsci(lambda: None)
    win._run(isci2)
    assert isci2.start_calls == 0
    assert not win._workers
    win._close_pending = False
    # bağlantı kesilirken: kalıcı iptal + bekçiye bağlanır
    win._disconnect_in_progress = True
    isci3 = _SahteIsci(lambda: None)
    win._run(isci3)
    assert isci3.iptal is True
    assert isci3.start_calls == 1
    win._disconnect_in_progress = False
    # kesme sırasında izinli iş iptal edilmez
    win._disconnect_in_progress = True
    isci4 = _SahteIsci(lambda: None)
    isci4._allow_during_disconnect = True
    win._run(isci4)
    assert isci4.iptal is False
    win._disconnect_in_progress = False
    assert len(win._workers) == 2


def test_run_etiketleri(pencere):
    win, _core, _tmp = pencere
    # dize kolaylığı: açıklama olur
    isci = _SahteIsci(lambda: None)
    win._run(isci, 'Uygulamalar taranıyor')
    assert win._activity[id(isci)][0] == 'Uygulamalar taranıyor'
    assert win.btn_stop.isEnabled() is True
    assert win.btn_stop.isVisible() is True
    win._flush_logs()
    assert '▶ İstek: Uygulamalar taranıyor' in win.txt_log.toPlainText()
    # iş adı yedek etiket olur
    isimli = _SahteIsci(lambda: None)
    isimli.job_name = 'Sessiz tarama'
    win._run(isimli)
    assert win._activity[id(isimli)][0] == 'Sessiz tarama'
    # önceden sessiz işaretli işçi izlenmez
    onceden = _SahteIsci(lambda: None)
    onceden.silent = True
    win._run(onceden, 'Gizli iş')
    assert id(onceden) not in win._activity
    # 'Tuş:' benzeri etiketler sessiz sayılır
    for etiket in ('Tuş: yukarı', 'Ses Seviyesi %10', 'Ses: kıs'):
        tus = _SahteIsci(lambda: None)
        win._run(tus, etiket)
        assert tus.silent is True
        assert id(tus) not in win._activity


def test_run_basari_ve_temizlik(pencere):
    win, _core, _tmp = pencere
    isci = _SahteIsci(lambda: None)
    win._run(isci, 'İşlem')
    isci.finished_ok.emit('veri')
    assert win.status.currentMessage() == 'İşlem tamamlandı.'
    assert ('record_action', 'İşlem tamamlandı.') in _Sekme.kayit
    # 'Arka plan isi' etiketi: durum mesajı var, kayıt yok
    duz = _SahteIsci(lambda: None)
    duz.job_name = 'Arka plan isi'
    win._run(duz)
    _Sekme.kayit.clear()
    duz.finished_ok.emit(None)
    assert win.status.currentMessage() == 'Arka plan isi tamamlandı.'
    assert not [k for k in _Sekme.kayit if k[0] == 'record_action']
    # temizlik: etkinlikten düşer, silinir
    isci.finished.emit()
    assert id(isci) not in win._activity
    assert isci not in win._workers
    assert isci.silinecek is True
    # kesme beklerken temizlik bekçiyi planlar
    bekleyen = _SahteIsci(lambda: None)
    win._run(bekleyen, 'İş')
    win._disconnect_pending = True
    bekleyen.finished.emit()
    win._disconnect_pending = False
    assert bekleyen.silinecek is True


def test_run_hata_akislari(pencere):
    win, _core, _tmp = pencere
    hatalar = []
    isci = _SahteIsci(lambda: None)
    win._run(isci, 'İşlem', on_fail=hatalar.append)
    isci.failed.emit('patladı')
    assert hatalar == ['patladı']
    assert win.lbl_error.text() == 'İşlem: patladı'
    assert win.error_box.isVisible() is True
    assert ('record_action', 'İşlem başarısız.') in _Sekme.kayit
    win._flush_logs()
    assert '✘ İşlem başarısız: patladı' in win.txt_log.toPlainText()
    # kullanıcı iptali / bağlantı değişimi şerit göstermez
    win.error_box.hide()
    iptal = _SahteIsci(lambda: None)
    win._run(iptal, 'İşlem')
    iptal.failed.emit('Kullanıcı durdurdu')
    assert win.error_box.isHidden() is True
    iptal.failed.emit('Bağlantı değişti: yeniden kurun')
    assert win.error_box.isHidden() is True
    # sessiz iş: şerit yok ama geri çağrım çalışır
    sessiz = _SahteIsci(lambda: None)
    hatalar.clear()
    win._run(sessiz, 'Tuş: aşağı', on_fail=hatalar.append)
    sessiz.failed.emit('olmadı')
    assert hatalar == ['olmadı']
    assert 'olmadı' not in win.lbl_error.text()


def test_run_gunluk_ve_ilerleme(pencere):
    win, _core, _tmp = pencere
    isci = _SahteIsci(lambda: None)
    win._run(isci, 'Tarama')
    isci.log.emit('ara adım')
    win._flush_logs()
    assert 'ara adım' in win.txt_log.toPlainText()
    onceki = win.txt_log.toPlainText()
    isci.log.emit('✘ özet satırı')
    win._flush_logs()
    assert win.txt_log.toPlainText() == onceki
    # ilerleme etkinliğe işlenir
    isci.progress.emit(3, 10)
    assert win._activity[id(isci)] == ('Tarama', 3, 10)
    isci.progress.emit(-5, -2)
    assert win._activity[id(isci)] == ('Tarama', 0, 0)
    win._closing = True
    isci.progress.emit(9, 10)
    assert win._activity[id(isci)][1] == 0
    win._closing = False
    # sinyalsiz işçi: günlük/ilerleme kanalları yok
    yalin = _IptalsizIsci()
    win._run(yalin, 'Yalın')
    assert id(yalin) in win._activity
    yalin.finished_ok.emit(None)
    yalin.finished.emit()
    assert id(yalin) not in win._activity
    assert yalin.silinecek is True


def test_durdurma(pencere):
    win, _core, _tmp = pencere
    win.cancel_workers()
    assert ('_stop_hold',) in _Sekme.kayit
    isci = _SahteIsci(lambda: None)
    isci.calisiyor = True
    korunmus = _SahteIsci(lambda: None)
    korunmus.calisiyor = True
    korunmus._preserve_from_cancel = True
    iptalsiz = _IptalsizIsci()
    iptalsiz.calisiyor = True
    patlak = _SahteIsci(lambda: None)
    patlak.calisiyor = True
    patlak.cancel = lambda: (_ for _ in ()).throw(RuntimeError('yok'))
    win._workers.extend([isci, korunmus, iptalsiz, patlak])
    win.cancel_workers()
    assert isci.cancel_calls == 1
    assert korunmus.cancel_calls == 0
    assert iptalsiz.cancel_calls == 1  # requestInterruption yolu
    assert win.lbl_activity.text() == 'İşlemler durduruluyor…'
    win._flush_logs()
    assert '⏹ Durdur istendi (3 is).' in win.txt_log.toPlainText()
    win._workers.clear()


# --- log paneli içerikleri ---

def test_log_filtreleri(pencere):
    win, _core, _tmp = pencere
    win.txt_log.clear()
    win._logbus.clear()
    win._last_drawn = 0
    win.append_log('bilgi satırı', 'INFO')
    win.append_log('uyarı satırı', 'WARN')
    win.append_log('hata satırı', 'ERROR')
    win._flush_logs()
    metin = win.txt_log.toPlainText()
    assert 'bilgi satırı' in metin and 'hata satırı' in metin
    # düzey kapatma yalnız görünümü değiştirir
    win.chk_warn.setChecked(False)
    assert 'uyarı satırı' not in win.txt_log.toPlainText()
    win.chk_warn.setChecked(True)
    assert 'uyarı satırı' in win.txt_log.toPlainText()
    # ayrıntı düzeyi açılınca eski VERBOSE kaydı geri gelir
    win.chk_verbose.setChecked(True)
    win.append_log('yoklama satırı', 'VERBOSE')
    win._flush_logs()
    assert 'yoklama satırı' in win.txt_log.toPlainText()
    win.chk_verbose.setChecked(False)
    assert 'yoklama satırı' not in win.txt_log.toPlainText()


def test_log_akisi(pencere):
    win, _core, _tmp = pencere
    win.txt_log.clear()
    win._logbus.clear()
    win._last_drawn = 0
    # takip kapalıyken yeni kayıtlar panele yazılmaz
    win.chk_log_follow.setChecked(False)
    win.append_log('saklı kayıt', 'INFO')
    win._flush_logs()
    assert win.txt_log.toPlainText() == ''
    # takip açılınca geçmiş yeniden çizilir
    win.chk_log_follow.setChecked(True)
    assert 'saklı kayıt' in win.txt_log.toPlainText()
    # halka taşması: sayaç eşitlenir, eski çizim korunur
    win._logbus = LogBus(capacity=2)
    win._last_drawn = 10
    win._logbus.enqueue('kayit-alfa', 'INFO')
    win._logbus.enqueue('kayit-beta', 'INFO')
    win._flush_logs()
    assert win._last_drawn == 2
    assert 'kayit-alfa' not in win.txt_log.toPlainText()
    win._logbus.enqueue('kayit-gama', 'INFO')
    win._flush_logs()
    assert 'kayit-gama' in win.txt_log.toPlainText()
    # eski (msg, level) biçimi de desteklenir
    win._logbus = _KuklaTampon([('eski biçim', 'INFO')], 3)
    win._last_drawn = 2
    win._flush_logs()
    assert 'eski biçim' in win.txt_log.toPlainText()
    assert '??:??:??.???' in win.txt_log.toPlainText() or win._last_drawn == 3
    # tampon hatası: sessizce döner
    win._logbus = _KuklaTampon([], 5)
    win._logbus.drain_new = lambda: (_ for _ in ()).throw(RuntimeError('yok'))
    win._flush_logs()


def test_log_yeniden_cizim(pencere):
    win, _core, _tmp = pencere
    win._logbus = _KuklaTampon([('eski kayıt', 'INFO')], 1)
    win._last_drawn = 0
    win._rebuild_log_view()
    assert 'eski kayıt' in win.txt_log.toPlainText()
    assert '??:??:??.???' in win.txt_log.toPlainText()
    assert win._last_drawn == 1
    # anlık görüntü hatası yutulur
    win._logbus = _KuklaTampon([], 0)
    win._logbus.snapshot = lambda: (_ for _ in ()).throw(RuntimeError('yok'))
    win._rebuild_log_view()
    assert win._last_drawn == 0
    # metin alanı silinmişse erken dönülür
    yazi = win.txt_log
    win.txt_log = _PatlakYazi()
    win._rebuild_log_view()
    win._flush_logs()  # bekleyen kayıt yok: erken dönüş
    win.txt_log = yazi
    # çizim hatası (RuntimeError) yutulur
    win._logbus = _KuklaTampon([('x', 'INFO')], 2)
    win._last_drawn = 1
    win.txt_log = _PatlakYazi()
    win._flush_logs()
    win.txt_log = yazi


def test_log_temizle_ve_kopyala(pencere):
    from PySide6.QtGui import QGuiApplication
    win, _core, _tmp = pencere
    win.append_log('kopyalanacak satır', 'INFO')
    win._flush_logs()
    assert win.txt_log.toPlainText() != ''
    win._copy_visible_log()
    assert 'kopyalanacak satır' in QGuiApplication.clipboard().text()
    assert win.status.currentMessage() == 'Görünen günlük kayıtları kopyalandı.'
    win._clear_log_view()
    assert win.txt_log.toPlainText() == ''
    assert win._logbus.snapshot() == []
    assert win._last_drawn == 0
    # temizleme hatası yutulur
    yazi = win.txt_log
    win.txt_log = _PatlakYazi()
    win._clear_log_view()
    win.txt_log = yazi


def test_log_arama(pencere):
    win, _core, _tmp = pencere
    win._logbus.clear()
    win._last_drawn = 0
    win.append_log('Paket kuruldu', 'INFO')
    win.append_log('Ağ hatası oluştu', 'ERROR')
    win._flush_logs()
    win.txt_log_search.setText('hata')
    win._rebuild_log_view()
    metin = win.txt_log.toPlainText()
    assert 'Ağ hatası oluştu' in metin
    assert 'Paket kuruldu' not in metin
    win.txt_log_search.setText('')
    win._rebuild_log_view()
    assert 'Paket kuruldu' in win.txt_log.toPlainText()
    # eşleşme kuralı doğrudan
    assert win._log_matches('12:00:00.000', 'Paket kuruldu', 'INFO') is True
    assert win._log_matches('12:00:00.000', 'Paket kuruldu', 'VERBOSE') is False


def test_esc_ve_kisa_komut(pencere):
    win, _core, _tmp = pencere
    assert win._esc('a<b>&c') == 'a&lt;b&gt;&amp;c'
    assert win._short_cmd(['-s', '1.2.3.4:5555', 'shell', 'getprop', 'x']) == \
        'adb getprop x'
    assert win._short_cmd(['-s', 'serial', 'install', 'a.apk']) == \
        'adb install a.apk'
    assert win._short_cmd(['connect', '1.2.3.4:5555']) == 'adb connect ******'
    assert win._short_cmd(['pair', '1.2.3.4:5555']) == 'adb pair ******'
    assert win._short_cmd(['disconnect', '1.2.3.4:5555']) == \
        'adb disconnect ******'
    assert win._short_cmd(['devices']) == 'adb devices'
    assert win._short_cmd(None) == 'adb '
    uzun = win._short_cmd(['shell'] + ['x' * 40] * 5)
    assert uzun.startswith('adb shell ')
    assert uzun.endswith('...')
    assert len(uzun) == 4 + 157 + 3


def test_adb_izi(pencere):
    win, core, _tmp = pencere
    core.adb_trace.emit(['-s', '1.2.3.4:5555', 'shell', 'getprop', 'x'],
                        True, 5, '', False)
    win._flush_logs()
    metin = win.txt_log.toPlainText()
    assert 'adb getprop x 5ms' in metin
    assert '1.2.3.4' not in metin
    # hatalı komut ERROR olarak yazılır
    core.adb_trace.emit(['devices'], False, 9, 'kapalı', False)
    win._flush_logs()
    assert 'HATA: kapalı' in win.txt_log.toPlainText()
    # yoklama satırı ayrıntı kapalıyken hiç yazılmaz
    onceki = win.txt_log.toPlainText()
    core.adb_trace.emit(['shell', 'pidof'], True, 3, '', True)
    win._flush_logs()
    assert win.txt_log.toPlainText() == onceki
    # ayrıntı açıkken görünür
    win.chk_verbose.setChecked(True)
    core.adb_trace.emit(['shell', 'pidof'], True, 3, '', True)
    win._flush_logs()
    assert 'pidof' in win.txt_log.toPlainText()
    win.chk_verbose.setChecked(False)
    # kapanışta yok sayılır
    win._closing = True
    core.adb_trace.emit(['devices'], True, 1, '', False)
    win._flush_logs()
    win._closing = False


def test_son_eylem_ve_saat(pencere):
    win, _core, _tmp = pencere
    win.set_last_action('TV yeniden başlatıldı')
    assert win.lbl_last_action.text() == u'• TV yeniden başlatıldı'
    assert ('record_action', 'TV yeniden başlatıldı') in _Sekme.kayit
    win._flush_logs()
    assert 'Kullanıcı: TV yeniden başlatıldı' in win.txt_log.toPlainText()
    # bozuk gösterge: hata yutulur
    win.lbl_last_action = _PatlakEtiket()
    win.set_last_action('X')
    # günlük yazımı patlarsa da yutulur
    gercek_log = win.append_log
    win.append_log = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('log yok'))
    win.set_last_action('Y')
    win.append_log = gercek_log
    win._tick_clock()
    assert len(win.lbl_clock.text()) == 8
    # saat göstergesi silinmişse yutulur
    win.lbl_clock = None
    win._tick_clock()


def test_logbus_drain_kuyrugu():
    bus = LogBus()
    bus.enqueue('kuyruktan', 'INFO')
    kayitlar = bus.drain()
    assert [k[1] for k in kayitlar] == ['kuyruktan']


# --- başlangıç hedefi ve kurulum yan yolları ---

def test_baslangic_hedef_cesitleri(qtbot, monkeypatch, tmp_path):
    core = _ortam(monkeypatch, tmp_path)
    core.target = '192.168.1.x:5555'
    win = MainWindow(core, selftest=True)
    qtbot.addWidget(win)
    assert win.txt_target.text() == '' and win.txt_port.text() == ''
    assert win._target_kind is None
    assert core.target == ''
    core2 = _Cekirdek(Config(load=False))
    core2.target = '192.0.2.5:5555'
    win2 = MainWindow(core2, selftest=True)
    qtbot.addWidget(win2)
    assert win2.txt_target.text() == '192.0.2.5'
    assert win2.txt_port.text() == '5555'
    assert win2._target_kind == 'network'
    core3 = _Cekirdek(Config(load=False))
    core3.target = '192.0.2.5'
    win3 = MainWindow(core3, selftest=True)
    qtbot.addWidget(win3)
    assert win3.txt_target.text() == '192.0.2.5'
    assert win3.txt_port.text() == '5555'
    assert win3._target_kind == 'network'


def test_ekran_yoksa_pencere(qtbot, monkeypatch, tmp_path):
    core = _ortam(monkeypatch, tmp_path)
    monkeypatch.setattr(main_mod, 'QGuiApplication', _Ekransiz)
    win = MainWindow(core, selftest=True)
    qtbot.addWidget(win)
    assert win.minimumWidth() == 900
    assert win._closing is False


def test_blok_signals_yok(qtbot, monkeypatch, tmp_path):
    core = _ortam(monkeypatch, tmp_path)
    monkeypatch.setattr(main_mod, 'QPushButton', _BlokluDugme)
    win = MainWindow(core, selftest=True)
    qtbot.addWidget(win)
    assert win.btn_hide_log.text() == 'Göster'


def test_sinyal_baglama_hatalari(qtbot, monkeypatch, tmp_path):
    core = _ortam(monkeypatch, tmp_path)
    dar = _DarCekirdek(core)
    win = MainWindow(dar, selftest=True)
    qtbot.addWidget(win)
    assert win._closing is False
    # log/connection_changed gerçek sinyallere bağlandı; kapanış temizliği
    # için sağlıklı çekirdekle devam et ve adb_trace bağını da kur
    win.core = core
    core.adb_trace.connect(win._on_adb_trace)
    win._finalize_close()
    assert win._closing is True


def test_tema_baglanti_hatalari(pencere):
    win, _core, _tmp = pencere
    gercek_durum = win.lbl_status
    gercek_link = win.lbl_link

    class _PatlakDurum:
        def setStyleSheet(self, _stil):
            raise RuntimeError('durum yok')

    win.lbl_status = _PatlakDurum()
    win.apply_theme()
    win.lbl_status = gercek_durum
    win.lbl_link = _PatlakEtiket()
    win._set_link(True)
    win.lbl_link = gercek_link
    assert win.lbl_link.text() == u'● Çevrimdışı'


def test_destek_ozeti(pencere):
    win, _core, _tmp = pencere
    win.open_support_summary()
    assert ('_show_support_summary',) in _Sekme.kayit


def test_append_log_dallari(pencere):
    win, _core, _tmp = pencere
    # kapanışta günlük yok sayılır
    win._closing = True
    win._logbus.clear()
    win.append_log('kapanista-yazilmaz', 'INFO')
    win._closing = False
    assert win._logbus.snapshot() == []
    # dosya yazımı patlarsa yutulur
    win._write_log_line = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('yazma yok'))
    win.append_log('kaydolmaz', 'INFO')
    del win._write_log_line
    win._flush_logs()
    assert 'kaydolmaz' not in win.txt_log.toPlainText()


def test_kalici_hata_kapanista(pencere):
    win, core, _tmp = pencere
    win._closing = True
    core.persistence_error.emit('kayit yok')
    assert win._error_text == ''
    win._closing = False


def test_log_paneli_hata_dallari(pencere, monkeypatch):
    win, _core, _tmp = pencere
    gercek_onay = win.btn_log_toggle
    win.btn_log_toggle = _PatlakOnay()
    win._toggle_log(False)
    win._toggle_log_panel(False)
    win.btn_log_toggle = gercek_onay
    # açılışta yeniden çizim patlarsa yutulur
    monkeypatch.setattr(win, '_rebuild_log_view',
                        lambda: (_ for _ in ()).throw(RuntimeError('cizim yok')))
    win._toggle_log_panel(True)
    # tampon temizleme patlarsa yutulur
    win._logbus = _KuklaTampon([('a', 'INFO')], 1)
    win._logbus.clear = lambda: (_ for _ in ()).throw(RuntimeError('temizleme yok'))
    win._clear_log_view()
    assert win._last_drawn == 0


def test_hedef_cozumleme_ek_dallar(pencere):
    win, _core, _tmp = pencere
    # ağ türünde yapıştırılmış tam adres alanları ayırır
    win._target_kind = 'network'
    win.txt_target.setText('192.0.2.9:5555')
    win.txt_port.setText('')
    assert win._target_from_fields() == '192.0.2.9:5555'
    assert win.txt_target.text() == '192.0.2.9'
    assert win.txt_port.text() == '5555'
    # nokta içeren ve listede olan seri: cihaz kimliği sayılır
    win._target_kind = None
    win.txt_target.setText('ab.cd')
    win.txt_port.setText('')
    win.cmb_devices.addItem('Cihaz seçin', '')
    win.cmb_devices.addItem('sahte', 'ab.cd')
    assert win._device_is_listed('ab.cd') is True
    assert win._target_from_fields() == 'ab.cd'
    assert win._target_kind == 'serial'


def test_cihaz_listesi_arama_hatasi(pencere):
    win, _core, _tmp = pencere
    gercek = win.cmb_devices
    win.cmb_devices = object()
    assert win._device_is_listed('x') is False
    win.cmb_devices = gercek


def test_gecersiz_sayisal_port(pencere):
    win, _core, _tmp = pencere
    assert win._valid_target('tv:²') is False


def test_cihaz_kutusu_secim_vurgusu(pencere):
    win, _core, _tmp = pencere
    win._fill_device_combo([{'id': 'x:1', 'state': 'device'},
                            {'id': 'y:5555', 'state': 'device'}])
    assert win.cmb_devices.currentIndex() == -1
    win._target_kind = 'network'
    win.txt_target.setText('y:5555')
    win.txt_port.setText('')
    win._fill_device_combo([{'id': 'x:1', 'state': 'device'},
                            {'id': 'y:5555', 'state': 'device'}])
    assert win.cmb_devices.currentIndex() == 2
    assert win.cmb_devices.itemData(2) == 'y:5555'


def test_baglanti_bitirme_dallari(pencere):
    win, _core, _tmp = pencere
    win._closing = True
    win._connection_busy = True
    win._finish_connection_request()
    assert win._connection_busy is False
    win._watch_fail = 3
    win._after_connect(None)
    assert win._watch_fail == 3
    win._closing = False


def test_otomatik_yenileme(pencere):
    win, core, _tmp = pencere
    core.config.user_id = 0
    win.tab_apps._busy = True
    win._auto_refresh_after_connect()
    win._flush_logs()
    assert 'Otomatik yenileme atlandı' in win.txt_log.toPlainText()
    win.tab_apps._busy = False
    core.config.user_id = 7
    _Sekme.kayit.clear()
    win._auto_refresh_after_connect()
    assert ('scan_if_needed',) in _Sekme.kayit
    # debloat taraması patlarsa yutulur
    win.tab_debloat.scan_if_needed = \
        lambda: (_ for _ in ()).throw(RuntimeError('debloat yok'))
    win._auto_refresh_after_connect()
    del win.tab_debloat.scan_if_needed
    # uygulamalar yenilemesi patlarsa uyarı yazılır
    _Sekme.refresh_hatasi = RuntimeError('patladi')
    win._auto_refresh_after_connect()
    _Sekme.refresh_hatasi = None
    win._flush_logs()
    assert 'Otomatik yenileme baslatilamadi: patladi' in win.txt_log.toPlainText()


def test_kesme_yan_yollari(pencere):
    win, _core, _tmp = pencere
    gercek_log = win.append_log

    def cengel(msg, level='INFO'):
        if str(msg).startswith('Ekran kaydı durdurulurken'):
            raise RuntimeError('log yok')
        return gercek_log(msg, level)

    win.append_log = cengel
    _Sekme.recording_close = None
    win.on_disconnect()
    _Sekme.recording_close = True
    win.append_log = gercek_log
    assert win._disconnect_in_progress is True
    win._workers[-1].finished_ok.emit(None)
    # iptal/bağlama hataları yutulur, kesme bekler
    isci = _SahteIsci(lambda: None)
    isci.calisiyor = True
    isci.cancel = lambda: (_ for _ in ()).throw(RuntimeError('iptal yok'))
    ciplak = _CiplakIsci()
    win._workers.extend([isci, ciplak])
    win.on_disconnect()
    assert win._disconnect_pending is True
    isci.calisiyor = False
    ciplak.calisiyor = False
    win._workers.clear()
    win._disconnect_pending = False
    win._disconnect_in_progress = False


def test_bekci_zamanlayici_hatalari(pencere):
    win, core, _tmp = pencere
    win._selftest = False
    core.target = 't:1'
    core.connected = True
    win._reconnect_target = 't:1'
    win._watch = _PatlakZamanlayici()
    win._watchdog()
    isci = win._watchdog_worker
    assert isci.args[0]() is True
    isci.finished_ok.emit(True)
    assert win._watch_fail == 0
    # kapanış koruması: sonuç yok sayılır
    win._watchdog()
    isci2 = win._watchdog_worker
    isci2.args[0]()
    win._closing = True
    isci2.finished_ok.emit(True)
    assert win._watch_fail == 0
    win._closing = False
    # hata yolu: aralık güncellenemese de sayaç işler
    core._engine.connect_patlak = True
    win._watchdog()
    isci3 = win._watchdog_worker
    assert isci3.args[0]() is False
    isci3.finished_ok.emit(False)
    assert win._watch_fail == 1
    core._engine.connect_patlak = False
    for isci_kalan in list(win._workers):
        isci_kalan.calisiyor = False
    win._workers.clear()


def test_gunluk_dosya_yolu_dallari(pencere, monkeypatch, tmp_path):
    win, _core, _tmp = pencere
    win._log_file_day = None
    win._log_file_path = None
    ilk = win._daily_log_path()
    assert ilk is not None and ilk.endswith('.log')
    assert win._daily_log_path() == ilk
    # kilit içinde önbellek dolmuşsa doğrudan döner
    win._log_file_day = None
    win._log_file_path = None
    win._log_file_lock = _SazanKilit(win)
    assert win._daily_log_path() == 'onbellek-yol'
    # klasör açılamazsa None döner
    win._log_file_day = None
    win._log_file_path = None
    win._log_file_lock = threading.Lock()
    kilit_dosya = tmp_path / 'klasor-degil'
    kilit_dosya.write_text('x', encoding='utf-8')
    monkeypatch.setattr(main_mod, 'LOG_DIR', str(kilit_dosya))
    assert win._daily_log_path() is None


def test_gunluk_dosya_yazim_dallari(pencere, monkeypatch, tmp_path):
    win, core, _tmp = pencere
    win._log_file_day = None
    win._log_file_path = None
    core.config.log_to_file = True
    core.target = '192.0.2.77:5555'
    win.append_log('hedef 192.0.2.77:5555 ile konuşuldu', 'INFO')
    yol = win._log_file_path
    assert yol is not None and os.path.exists(yol)
    icerik = open(yol, encoding='utf-8').read()
    assert 'ile konuşuldu' in icerik
    assert '192.0.2.77' not in icerik
    # dosyaya yazma kapalıyken yazılmaz
    core.config.log_to_file = False
    win.append_log('dosyaya-gitmez', 'INFO')
    assert 'dosyaya-gitmez' not in open(yol, encoding='utf-8').read()
    core.config.log_to_file = True
    # yol bulunamazsa sessiz geçilir
    win._log_file_day = None
    win._log_file_path = None
    kilit_dosya = tmp_path / 'kilit2'
    kilit_dosya.write_text('x', encoding='utf-8')
    monkeypatch.setattr(main_mod, 'LOG_DIR', str(kilit_dosya))
    win.append_log('yolsuz-satir', 'INFO')
    # dosya açılamazsa OSError yutulur
    monkeypatch.setattr(win, '_daily_log_path',
                        lambda: str(tmp_path / 'yok-klasor' / 'g.log'))
    win.append_log('acilamaz-satir', 'INFO')
    # hedef okunamazsa maskeleme atlanır
    gercek_core = win.core
    win.core = _HedefsizCore(core)
    win.append_log('maskelemesiz-satir', 'INFO')
    win.core = gercek_core
    win._flush_logs()
    assert 'maskelemesiz-satir' in win.txt_log.toPlainText()


def test_log_kaydetme(pencere, monkeypatch, tmp_path):
    win, _core, _tmp = pencere
    win._log_file_day = None
    win._log_file_path = None
    win.append_log('kayda-girecek', 'INFO')
    win._logbus.drain()  # bekleyen kayıtları depoya al (3'lü kayıt yolu)
    yol = win._daily_log_path()
    _Kutu.kayitlar = []
    win.save_log_to_file()
    assert win.status.currentMessage().startswith('Log kaydedildi: ')
    icerik = open(yol, encoding='utf-8').read()
    assert '--- Canli log tamponsu' in icerik
    assert 'kayda-girecek' in icerik
    win._flush_logs()
    assert 'Log dosyaya kaydedildi: ' in win.txt_log.toPlainText()
    assert not [k for k in _Kutu.kayitlar if k[0] in ('uyari', 'kritik')]
    # anlık görüntü hatası: boş liste yazılır
    win._logbus.snapshot = lambda: (_ for _ in ()).throw(RuntimeError('yok'))
    win.save_log_to_file()
    assert '(0 kayıt)' in open(yol, encoding='utf-8').read()
    del win._logbus.snapshot
    # eski (msg, level) kayıtları da yazılır
    win._logbus = _KuklaTampon([('eski-kayit', 'WARN')], 1)
    win.save_log_to_file()
    assert 'eski-kayit' in open(yol, encoding='utf-8').read()
    # yol yoksa uyarı kutusu
    kilit = tmp_path / 'kilit'
    kilit.write_text('x', encoding='utf-8')
    monkeypatch.setattr(main_mod, 'LOG_DIR', str(kilit))
    win._log_file_day = None
    win._log_file_path = None
    win.save_log_to_file()
    assert ('uyari', 'Log', 'Log klasoru yazilabilir degil.') in _Kutu.kayitlar
    # yazma hatası: kritik kutu
    monkeypatch.setattr(win, '_daily_log_path',
                        lambda: str(tmp_path / 'yok-klasor' / 'g.log'))
    win.save_log_to_file()
    assert any(k[0] == 'kritik' and k[1] == 'Log' for k in _Kutu.kayitlar)


def test_tepsi_simgesi(qtbot, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QSystemTrayIcon
    core = _ortam(monkeypatch, tmp_path)
    monkeypatch.setattr(main_mod.QSystemTrayIcon, 'isSystemTrayAvailable',
                        staticmethod(lambda: False))
    win = MainWindow(core, selftest=True)
    qtbot.addWidget(win)
    assert not hasattr(win, 'tray_icon')
    monkeypatch.setattr(main_mod.QSystemTrayIcon, 'isSystemTrayAvailable',
                        staticmethod(lambda: True))
    win._setup_tray_icon()
    assert hasattr(win, 'tray_icon')
    assert win.tray_icon.toolTip() == 'MiBox Konsol v1.5.1'
    menu = win.tray_icon.contextMenu()
    eylemler = [a for a in menu.actions() if a.text()]
    assert eylemler[0].text() == '📺 MiBox Konsol v1.5.1'
    assert eylemler[0].isEnabled() is False
    assert eylemler[-1].text() == 'Çıkış'
    for eylem in eylemler:
        if eylem.text() == '⚡ Turbo Hızlandır (RAM Temizle)':
            eylem.trigger()
    assert ('_turbo_boost',) in _Sekme.kayit
    win.show()
    # tepsi tetiklemesi pencereyi gizler/gösterir
    win._on_tray_activated(QSystemTrayIcon.Trigger)
    assert win.isHidden() is True
    win._on_tray_activated(QSystemTrayIcon.Context)
    assert win.isHidden() is True
    win._on_tray_activated(QSystemTrayIcon.Trigger)
    assert win.isVisible() is True
    # simge durumundayken öne getirilir
    win.isMinimized = lambda: True
    win._toggle_window_visibility()
    assert win.isVisible() is True
    del win.isMinimized
    win._toggle_window_visibility()
    assert win.isHidden() is True
    win._toggle_window_visibility()
    assert win.isVisible() is True
    # çıkış: pencere kapanır
    win._tray_quit()
    assert win._closing is True


def test_kisayol_eylemleri(pencere):
    from PySide6.QtGui import QShortcut
    win, _core, _tmp = pencere
    tuslar = {s.key().toString(): s for s in win.findChildren(QShortcut)}
    tuslar['Ctrl+Shift+B'].activated.emit()
    assert ('_turbo_boost',) in _Sekme.kayit
    tuslar['Ctrl+Shift+S'].activated.emit()
    assert ('_launch_scrcpy',) in _Sekme.kayit
    tuslar['Ctrl+Shift+R'].activated.emit()
    assert ('_toggle_screen_recording',) in _Sekme.kayit
    tuslar['Ctrl+Shift+T'].activated.emit()
    assert win.tabs.currentWidget() is win.tab_terminal
    tuslar['Ctrl+Shift+N'].activated.emit()
    assert win.tabs.currentWidget() is win.tab_network
    tuslar['Ctrl+Shift+O'].activated.emit()
    assert win.tabs.currentWidget() is win.tab_health
    tuslar['Ctrl+Home'].activated.emit()
    assert win.tabs.currentWidget() is win.tab_overview
    tuslar['Ctrl+K'].activated.emit()
    assert _Eylemler.kayitlar
    tuslar['F5'].activated.emit()
    tuslar['Ctrl+L'].activated.emit()
    tuslar['Ctrl+,'].activated.emit()
    assert win.tabs.currentWidget() is win.tab_settings
    tuslar['Ctrl+1'].activated.emit()
    assert win.tabs.currentWidget() is win.tab_apps
    # kumanda sekmesi yoksa hızlı eylemler güvenli
    kumanda = win.tab_remote_inner
    win.tab_remote_inner = None
    win._quick_turbo_boost()
    win._quick_scrcpy()
    win._quick_record_toggle()
    win.tab_remote_inner = kumanda


def test_kisayol_kurulum_hatasi(pencere, monkeypatch):
    win, _core, _tmp = pencere
    monkeypatch.setattr(
        main_mod, 'QShortcut',
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError('kisayol yok')))
    win._setup_window_shortcuts()


def test_run_sarmalama_hatalari(pencere):
    win, _core, _tmp = pencere
    # kapanışta deleteLater patlarsa yutulur
    win._closing = True
    isci = _SahteIsci(lambda: None)
    isci.deleteLater = lambda: (_ for _ in ()).throw(RuntimeError('silinmez'))
    win._run(isci)
    assert not win._workers
    win._closing = False
    # bağlantı kesilirken cancel patlarsa yutulur
    win._disconnect_in_progress = True
    iptal_patlak = _SahteIsci(lambda: None)
    iptal_patlak.cancel = lambda: (_ for _ in ()).throw(RuntimeError('iptal yok'))
    win._run(iptal_patlak)
    assert iptal_patlak.start_calls == 1
    win._disconnect_in_progress = False
    # sessiz ataması patlarsa yutulur
    sessiz = _SessizPatlak()
    win._run(sessiz, 'Tuş: yukarı')
    assert sessiz.start_calls == 1
    assert id(sessiz) not in win._activity
    # '▶ İstek' günlüğü patlarsa yutulur
    gercek_log = win.append_log
    win.append_log = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('log yok'))
    isci2 = _SahteIsci(lambda: None)
    win._run(isci2, 'İş')
    win.append_log = gercek_log
    assert isci2.start_calls == 1
    isci2.finished.emit()


def test_run_kanal_hatalari(pencere):
    win, _core, _tmp = pencere
    # log/progress kanalları çağrılamaz: bağlama hataları yutulur
    kanalsiz = _KanalsizIsci()
    win._run(kanalsiz, 'İş')
    assert kanalsiz.start_calls == 1
    kanalsiz.finished.emit()
    assert id(kanalsiz) not in win._activity
    # finished sinyali olmayan işçi: temizlik bağlanamaz ama başlar
    sinyalsiz = _SinyalsizIsci()
    win._run(sinyalsiz, 'İş')
    assert sinyalsiz.start_calls == 1
    # temizlikte deleteLater hatası yutulur
    silinmez = _SahteIsci(lambda: None)
    silinmez.deleteLater = lambda: (_ for _ in ()).throw(RuntimeError('yok'))
    win._run(silinmez, 'İş')
    silinmez.finished.emit()
    assert id(silinmez) not in win._activity
    # isRunning hatası canlı kontrolünde yutulur
    patlak = _SahteIsci(lambda: None)
    patlak.isRunning = lambda: (_ for _ in ()).throw(RuntimeError('yok'))
    win._workers.append(patlak)
    baska = _SahteIsci(lambda: None)
    win._run(baska, 'İş')
    baska.finished.emit()
    win._workers.remove(patlak)
    # btn_stop hatası yutulur, iş yine başlar
    gercek_stop = win.btn_stop
    win.btn_stop = _PatlakDugme()
    dugmeli = _SahteIsci(lambda: None)
    win._run(dugmeli, 'İş')
    assert dugmeli.start_calls == 1
    win.btn_stop = gercek_stop
    dugmeli.finished.emit()


def test_log_cizim_hatalari(pencere, monkeypatch):
    win, _core, _tmp = pencere
    # eşleşmeyen kayıt çizilmez
    win._logbus.clear()
    win._last_drawn = 0
    win.chk_info.setChecked(False)
    win.append_log('filtre-disi', 'INFO')
    win._flush_logs()
    assert 'filtre-disi' not in win.txt_log.toPlainText()
    win.chk_info.setChecked(True)
    # takip kapalıyken yeniden çizim kaydırma konumuna döner
    win.chk_log_follow.setChecked(False)
    win._logbus.clear()
    win._last_drawn = 0
    win.append_log('donus-noktasi', 'INFO')
    win._logbus.drain()
    win._rebuild_log_view()
    assert 'donus-noktasi' in win.txt_log.toPlainText()
    # akışta ikinci kontrol kapalıysa kaydırma korunur
    cagrilar = {'n': 0}

    def dalgali():
        cagrilar['n'] += 1
        return cagrilar['n'] == 1

    win.chk_log_follow.isChecked = dalgali
    win.append_log('kaydirma-korumasi', 'INFO')
    win._flush_logs()
    del win.chk_log_follow.isChecked
    win.chk_log_follow.setChecked(True)
    assert 'kaydirma-korumasi' in win.txt_log.toPlainText()
    # akışta beklenmeyen hata yutulur
    win._logbus.clear()
    win._last_drawn = 0
    win.append_log('hata-dallari', 'INFO')
    monkeypatch.setattr(win, '_log_matches',
                        lambda *a: (_ for _ in ()).throw(ValueError('yok')))
    win._flush_logs()
    # yeniden çizimde RuntimeError yutulur
    monkeypatch.setattr(win, '_log_matches',
                        lambda *a: (_ for _ in ()).throw(RuntimeError('yok2')))
    win._rebuild_log_view()
    # yeniden çizimde beklenmeyen hata yutulur
    monkeypatch.setattr(win, '_log_matches',
                        lambda *a: (_ for _ in ()).throw(ValueError('yok3')))
    win._rebuild_log_view()


def test_trace_ve_durdurma_hatalari(pencere):
    win, core, _tmp = pencere
    # iz kısaltma hatası yutulur
    win._short_cmd = lambda *a: (_ for _ in ()).throw(RuntimeError('kisaltma yok'))
    core.adb_trace.emit(['devices'], True, 1, '', False)
    del win._short_cmd
    # durdur kaydı yazılamazsa yutulur
    isci = _SahteIsci(lambda: None)
    isci.calisiyor = True
    win._workers.append(isci)
    gercek_log = win.append_log
    win.append_log = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('log yok'))
    win.cancel_workers()
    win.append_log = gercek_log
    assert isci.cancel_calls == 1
    win._workers.clear()


# --- kapanış ---

def test_kapanis_akisi(pencere):
    win, _core, _tmp = pencere
    # bekleyen kapanış varken yeni istek yok sayılır
    win._close_pending = True
    e0 = QCloseEvent()
    win.closeEvent(e0)
    assert e0.isAccepted() is False
    win._close_pending = False
    assert win._closing is False
    # çalışan iş yoksa doğrudan kapanır
    e = QCloseEvent()
    win.closeEvent(e)
    assert e.isAccepted() is True
    assert win._closing is True
    assert win._close_pending is False
    assert win._close_scheduled is False
    # ikinci istek doğrudan kabul edilir
    e2 = QCloseEvent()
    win.closeEvent(e2)
    assert e2.isAccepted() is True


def test_kapanis_bekleyen_ekran_islemi(pencere):
    win, _core, _tmp = pencere
    _Sekme.bekleyen_display = True
    e = QCloseEvent()
    win.closeEvent(e)
    assert e.isAccepted() is False
    assert win.tab_health_inner.display_panel._close_after_transaction is True
    assert 'güvenle tamamlanınca' in win.status.currentMessage()
    _Sekme.bekleyen_display = False
    # ekran sorgusu patlarsa kapanış sürer
    win.tab_health_inner.display_panel._has_pending_display_transaction = \
        lambda: (_ for _ in ()).throw(AttributeError('yok'))
    e2 = QCloseEvent()
    win.closeEvent(e2)
    assert e2.isAccepted() is True


def test_kapanis_kayit_beklemesi(pencere):
    win, _core, _tmp = pencere
    _Sekme.recording_close = False
    e = QCloseEvent()
    win.closeEvent(e)
    assert e.isAccepted() is False
    _Sekme.recording_close = True


def test_kapanis_kayit_hazirlik_hatasi(pencere):
    win, _core, _tmp = pencere
    _Sekme.recording_close_hatasi = RuntimeError('kayit yok')
    e = QCloseEvent()
    win.closeEvent(e)
    assert e.isAccepted() is True
    win._flush_logs()
    assert 'Ekran kaydı kapanış hazırlığında hata: kayit yok' in \
        win.txt_log.toPlainText()


def test_kapanis_scrcpy_beklemesi(pencere):
    win, _core, _tmp = pencere
    _Sekme.scrcpy_close = False
    e = QCloseEvent()
    win.closeEvent(e)
    assert e.isAccepted() is False
    assert 'Scrcpy kapatılıyor' in win.status.currentMessage()
    _Sekme.scrcpy_close = True


def test_kapanis_scrcpy_hatalari(pencere):
    win, _core, _tmp = pencere
    _Sekme.scrcpy_close_hatasi = RuntimeError('scrcpy yok')
    e = QCloseEvent()
    win.closeEvent(e)
    assert e.isAccepted() is True
    win._flush_logs()
    metin = win.txt_log.toPlainText()
    assert 'Scrcpy kapanışında hata: scrcpy yok' in metin
    assert 'Scrcpy 4 saniyede kapanmadı' in metin


def test_kapanis_calisan_isciler(pencere):
    win, _core, _tmp = pencere
    normal = _SahteIsci(lambda: None)
    normal.calisiyor = True
    iptalsiz = _IptalsizIsci()
    iptalsiz.calisiyor = True
    patlak = _SahteIsci(lambda: None)
    patlak.calisiyor = True
    patlak.cancel = lambda: (_ for _ in ()).throw(RuntimeError('iptal yok'))
    for sinyalli in (normal, iptalsiz, patlak):
        sinyalli.finished_ok.connect(lambda *a: None)
        sinyalli.failed.connect(lambda *a: None)
    ciplak = _CiplakIsci()
    win._workers.extend([normal, iptalsiz, patlak, ciplak])
    e = QCloseEvent()
    win.closeEvent(e)
    assert e.isAccepted() is False
    assert win._close_pending is True
    assert win._watchdog_generation == 1
    assert win.isEnabled() is False
    assert normal.iptal is True
    assert iptalsiz.cancel_calls == 1
    assert 'Çalışan işler durduruluyor' in win.status.currentMessage()
    win._flush_logs()
    assert 'Kapanış istendi; çalışan işler iptal ediliyor.' in \
        win.txt_log.toPlainText()
    # işler bitince kapanış sürer
    for isci in (normal, iptalsiz, patlak, ciplak):
        isci.calisiyor = False
    win._finish_close_when_workers_stop()
    assert win._closing is True


def test_kapanis_korunan_aktarim(pencere):
    win, _core, _tmp = pencere
    aktarim = _SahteIsci(lambda: None)
    aktarim.calisiyor = True
    aktarim.preserve_on_close = True
    aktarim.finished_ok.connect(lambda *a: None)
    aktarim.failed.connect(lambda *a: None)
    win._workers.append(aktarim)
    e = QCloseEvent()
    win.closeEvent(e)
    assert e.isAccepted() is False
    assert aktarim.cancel_calls == 0
    aktarim.failed.emit('disk dolu')
    win._flush_logs()
    assert 'Kapanış sırasında aktarım başarısız: disk dolu' in \
        win.txt_log.toPlainText()
    aktarim.calisiyor = False
    aktarim.finished.emit()
    assert win._closing is True


def test_kapanis_temizlik_hatalari(pencere, monkeypatch):
    win, core, _tmp = pencere
    patlak_zaman = _PatlakZamanlayici()
    win._log_timer = patlak_zaman
    win._clock = patlak_zaman
    win._watch = patlak_zaman
    win.tab_remote_inner._scrcpy_poll_timer = patlak_zaman
    win.tab_remote_inner._stop_hold = \
        lambda: (_ for _ in ()).throw(RuntimeError('tut yok'))
    monkeypatch.setattr(core.config, 'save',
                        lambda: (_ for _ in ()).throw(RuntimeError('kayit yok')))
    win.tray_icon = _PatlakTepsi()
    win._finalize_close()
    assert win._closing is True
    # sinyal koparma hatası yutulur
    gercek_core = win.core
    win.core = _KopukCore(core)
    win._finalize_close()
    win.core = gercek_core


def test_kapanis_isciler_bitince(pencere):
    win, _core, _tmp = pencere
    # kapanış yokken erken dönülür
    win._finish_close_when_workers_stop()
    assert win._closing is False
    win._close_pending = True
    isci = _SahteIsci(lambda: None)
    isci.calisiyor = True
    win._workers.append(isci)
    win._finish_close_when_workers_stop()
    assert win._close_scheduled is False
    assert win._closing is False
    isci.calisiyor = False
    win._finish_close_when_workers_stop()
    assert win._closing is True
    win._finish_close_when_workers_stop()


def test_kapanis_patlak_isci_atlanir(pencere):
    win, _core, _tmp = pencere
    win._close_pending = True
    patlak = _SahteIsci(lambda: None)
    patlak.isRunning = lambda: (_ for _ in ()).throw(RuntimeError('yok'))
    win._workers.append(patlak)
    win._finish_close_when_workers_stop()
    assert win._closing is True


def test_baslangic_cihaz_kontrolu(pencere):
    win, core, _tmp = pencere
    # kapanışta atlanır
    win._closing = True
    win._startup_device_check()
    assert getattr(win, '_device_list_worker', None) is None
    win._closing = False
    # ADB yolu yoksa atlanır
    gercek_adb = core.adb
    core.adb = None
    win._startup_device_check()
    assert getattr(win, '_device_list_worker', None) is None
    core.adb = gercek_adb
    # ADB varsa liste yenilenir
    win._startup_device_check()
    isci = win._device_list_worker
    assert isci is not None
    isci.finished_ok.emit([])
    isci.finished.emit()
    assert win._device_list_worker is None


def test_tepsi_kurulum_hatasi(qtbot, monkeypatch, tmp_path):
    core = _ortam(monkeypatch, tmp_path)

    class _PatlakTepsiSinifi:
        @staticmethod
        def isSystemTrayAvailable():
            raise RuntimeError('tepsi yok')

    monkeypatch.setattr(main_mod, 'QSystemTrayIcon', _PatlakTepsiSinifi)
    win = MainWindow(core, selftest=True)
    qtbot.addWidget(win)
    assert not hasattr(win, 'tray_icon')


def test_kapanis_hazirlik_log_hatalari(pencere):
    win, core, _tmp = pencere
    _Sekme.recording_close_hatasi = RuntimeError('kayit yok')
    _Sekme.scrcpy_close_hatasi = RuntimeError('scrcpy yok')
    gercek_log = win.append_log
    # bağlı yöntemi bırak, patlayan kancayı bağla: koparmada uyarı çıkmasın
    core.log.disconnect(gercek_log)

    def cengel(*_a, **_k):
        raise RuntimeError('log yok')

    win.append_log = cengel
    core.log.connect(cengel)
    e = QCloseEvent()
    win.closeEvent(e)
    win.append_log = gercek_log
    assert e.isAccepted() is True
    assert win._closing is True


def test_kapanis_durdurma_log_hatasi(pencere):
    win, _core, _tmp = pencere
    isci = _SahteIsci(lambda: None)
    isci.calisiyor = True
    isci.finished_ok.connect(lambda *a: None)
    isci.failed.connect(lambda *a: None)
    win._workers.append(isci)
    win.tab_remote_inner._stop_hold = \
        lambda: (_ for _ in ()).throw(RuntimeError('tut yok'))
    gercek_log = win.append_log
    win.append_log = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('log yok'))
    e = QCloseEvent()
    win.closeEvent(e)
    win.append_log = gercek_log
    assert e.isAccepted() is False
    assert win._close_pending is True
    assert isci.iptal is True
    isci.calisiyor = False
    win._finish_close_when_workers_stop()
    assert win._closing is True


def test_kapanis_korunan_sinyalsiz(pencere):
    win, _core, _tmp = pencere
    aktarim = _SinyalsizIsci()
    aktarim.calisiyor = True
    aktarim.preserve_on_close = True
    aktarim.finished_ok.connect(lambda *a: None)
    aktarim.failed.connect(lambda *a: None)
    win._workers.append(aktarim)
    e = QCloseEvent()
    win.closeEvent(e)
    assert e.isAccepted() is False
    aktarim.calisiyor = False
    win._finish_close_when_workers_stop()
    assert win._closing is True


