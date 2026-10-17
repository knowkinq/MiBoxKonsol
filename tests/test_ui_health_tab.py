# -*- coding: utf-8 -*-
"""Saglik sekmesi testleri: olcumler, bolumler, taramalar ve kisitlama."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QMessageBox,
    QPushButton,
)

import mibox_app.ui.dialogs as dialogs_mod
import mibox_app.workers as workers_mod
from mibox_app.ui import health_tab as health_mod
from mibox_app.ui import kit
from mibox_app.ui.health_tab import (
    AUTO_COL_NAME,
    AUTO_COL_PACKAGE,
    AUTO_COL_RESTRICT,
    HealthTab,
    _fmt_kb,
)
from mibox_app.workers import CancelledError


class _Motor:
    """Sahte cihaz motoru; cagrilar kaydedilir, ciktilar ayarlanabilir."""

    def __init__(self):
        self.calls = []
        self.display = {'width': 1920, 'height': 1080, 'fps': 59.94,
                        'density': 320, 'sink_name': 'HDMI'}
        self.cpu = {'soc': 'Amlogic S905X4', 'cores': 4, 'abi': 'arm64-v8a',
                    'temp': 42.5}
        self.top = []
        self.perms = {'all': [], 'granted': []}
        self.autorun = {}
        self.labels = {}
        self.display_patlak = False
        self.cpu_patlak = False
        self.top_patlak = False
        self.perms_patlak = False
        self.autorun_patlak = False
        self.labels_patlak = False

    def display_info(self, target):
        self.calls.append(('display_info', target))
        if self.display_patlak:
            raise RuntimeError('ekran okunamadi')
        return dict(self.display)

    def cpu_info(self, target):
        self.calls.append(('cpu_info', target))
        if self.cpu_patlak:
            raise RuntimeError('islemci okunamadi')
        return dict(self.cpu)

    def storage_top(self, target):
        self.calls.append(('storage_top', target))
        if self.top_patlak:
            raise RuntimeError('tarama patladi')
        return list(self.top)

    def app_permissions(self, target, package):
        self.calls.append(('app_permissions', target, package))
        if self.perms_patlak:
            raise RuntimeError('izin yok')
        return dict(self.perms)

    def autorun_receivers(self, target):
        self.calls.append(('autorun_receivers', target))
        if self.autorun_patlak:
            raise RuntimeError('tarama patladi')
        return dict(self.autorun)

    def app_labels(self, target):
        self.calls.append(('app_labels', target))
        if self.labels_patlak:
            raise RuntimeError('etiket yok')
        return dict(self.labels)


class _Yapilandirma:
    def __init__(self):
        self.protected = set()
        self.isimler = {}
        self.hatali_isimler = set()

    def friendly_name(self, package):
        if package in self.hatali_isimler:
            raise AttributeError('isim yok')
        return self.isimler.get(package, package)


class _Cekirdek(QObject):
    connection_changed = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.connected = True
        self.target = 'tv-1'
        self._engine = _Motor()
        self.motor_patlak = False
        self.motor_taze = False
        self.motor_kanca = None
        self.config = _Yapilandirma()

    @property
    def engine(self):
        if self.motor_patlak:
            raise RuntimeError('motor yok')
        if self.motor_kanca is not None:
            self.motor_kanca()
        if self.motor_taze:
            return _Motor()
        return self._engine

    @engine.setter
    def engine(self, value):
        self._engine = value


class _Pencere:
    def __init__(self):
        self.runs = []
        self._workers = []
        self._closing = False
        self._close_pending = False
        self._connection_busy = False
        self.tab_apps = None
        self.run_patlak = False
        self.run_kanca = None

    def _run(self, worker, desc=None):
        if self.run_kanca is not None:
            self.run_kanca()
        if self.run_patlak:
            raise RuntimeError('calistirilamadi')
        self.runs.append((worker, desc))


class _SahteIsci(QObject):
    finished_ok = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, func=None, *args, **kwargs):
        super().__init__()
        self._func = func
        self.job_name = ''
        self.cancel_calls = 0
        self.check_calls = 0
        self.iptal_edildi = False
        self.tamamlandi = False
        self.kanca = None

    def check_cancel(self):
        self.check_calls += 1
        if self.kanca is not None:
            self.kanca()
        if self.iptal_edildi:
            raise CancelledError('kullanıcı durdurdu')

    def cancel(self):
        self.cancel_calls += 1
        self.iptal_edildi = True

    def isFinished(self):
        return self.tamamlandi


@pytest.fixture
def saglik(qtbot, monkeypatch):
    monkeypatch.setattr(health_mod, 'Worker', _SahteIsci)
    core = _Cekirdek()
    win = _Pencere()
    tab = HealthTab(core, win)
    qtbot.addWidget(tab)
    return tab, core, win


def _olaylar():
    QApplication.processEvents()


def test_fmt_kb():
    assert _fmt_kb('abc') == '?'
    assert _fmt_kb(None) == '?'
    assert _fmt_kb(512) == '512 KB'
    assert _fmt_kb(1024) == '1 MB'
    assert _fmt_kb(2048) == '2 MB'
    assert _fmt_kb(1024 * 1024) == '1.0 GB'
    assert _fmt_kb(3 * 1024 * 1024) == '3.0 GB'


def test_kurulum(saglik, qtbot):
    tab, core, win = saglik
    assert tab.sections.count() == 3
    assert [tab.sections.tabText(i) for i in range(3)] == [
        'Genel durum', 'Cihaz ayarları', 'Bakım ve analiz']
    assert tab.sections.tabToolTip(0) == 'Depolama, bellek ve donanım ölçümleri'
    assert tab.sections.tabToolTip(1) == ('Ekran ayarları ve uygulamaların '
                                          'arka plan izinleri')
    assert tab.sections.tabToolTip(2) == ('Performans işlemleri, depolama ve '
                                          'uygulama taramaları')
    assert tab.scroll_performance is tab.scroll_maintenance
    assert tab.scroll_display is tab.scroll_devices
    assert tab.scroll_bg is tab.scroll_devices
    assert tab.scroll_advanced is tab.scroll_maintenance
    assert tab.lbl_measurement_state.text() == 'Ölçüm alınmadı'
    assert tab.lbl_measurement_summary.text() == (
        'Henüz ölçüm alınmadı. Yenile ile depolama ve bellek değerlerini okuyun.')
    assert tab.btn_refresh.text() == 'Yenile'
    assert tab.btn_refresh.isEnabled() is True
    assert tab.lbl_disk.text() == '—'
    assert tab.lbl_disk_detail.text() == 'Henüz ölçüm alınmadı'
    assert tab.lbl_mem.text() == '—'
    assert tab.lbl_pkg.text() == '—'
    assert tab.lbl_pkg_detail.text() == 'Henüz ölçüm alınmadı'
    assert tab.lbl_display.text() == '—'
    assert tab.lbl_cpu_detail.text() == 'Henüz ölçüm alınmadı'
    assert tab.lbl_overview.isHidden() is True
    assert tab.grid_top.rowCount() == 0
    assert tab.grid_auto.rowCount() == 0
    assert tab.grid_auto.isSortingEnabled() is True
    assert tab.grid_top.maximumHeight() == 130
    assert tab.grid_auto.maximumHeight() == 130
    assert tab.lbl_auto_found.text() == ''
    assert tab.lbl_auto_sel.text() == ''
    assert tab.lbl_perms.isHidden() is True
    assert tab._section_groups[tab.scroll_devices][0][0].isChecked() is True
    assert tab._section_groups[tab.scroll_devices][1][0].isChecked() is False
    assert tab.background.isHidden() is True

    core2 = _Cekirdek()
    win2 = _Pencere()
    win2._connection_busy = True
    tab2 = HealthTab(core2, win2)
    qtbot.addWidget(tab2)
    assert tab2.lbl_measurement_state.text() == 'Bağlantı kuruluyor…'

    core3 = _Cekirdek()
    core3.connected = False
    tab3 = HealthTab(core3, _Pencere())
    qtbot.addWidget(tab3)
    assert tab3.lbl_measurement_state.text() == 'Cihaz bağlı değil'


def test_bolum_gecisleri(saglik):
    tab, _core, _win = saglik
    devices = tab._section_groups[tab.scroll_devices]
    maintenance = tab._section_groups[tab.scroll_maintenance]
    assert len(devices) == 2
    assert len(maintenance) == 2
    assert devices[0][1] is tab.display_panel
    assert devices[1][1] is tab.background
    assert maintenance[0][1] is tab.performance

    tab._open_section(tab.scroll_devices, tab.background)
    assert tab.sections.currentWidget() is tab.scroll_devices
    assert devices[0][0].isChecked() is False
    assert devices[1][0].isChecked() is True
    assert tab.display_panel.isHidden() is True
    assert tab.background.isHidden() is False
    _olaylar()
    assert tab.scroll_devices.verticalScrollBar().value() == 0

    # Sayfa degistirilirse gecikmeli sifirlama lambdasi bos doner
    tab.sections.setCurrentWidget(tab.scroll_overview)
    tab.sections.setCurrentWidget(tab.scroll_devices)
    tab.sections.setCurrentWidget(tab.scroll_overview)
    _olaylar()

    # Genel durum kisayollari
    genel = tab.scroll_overview.widget()
    dugmeler = {d.text(): d for d in genel.findChildren(QPushButton)}
    assert 'Performans ve bakım' in dugmeler
    dugmeler['Ekran ve çözünürlük'].click()
    assert tab.sections.currentWidget() is tab.scroll_devices
    assert tab.display_panel.isHidden() is False
    assert devices[0][0].isChecked() is True

    dugmeler['Arka plan yönetimi'].click()
    assert tab.background.isHidden() is False
    assert tab.display_panel.isHidden() is True

    # Bakim sayfasi baglantilari
    maintenance[1][0].click()
    assert tab.performance.isHidden() is True
    assert maintenance[1][1].isHidden() is False
    maintenance[0][0].click()
    assert tab.performance.isHidden() is False
    assert maintenance[1][1].isHidden() is True


def test_duyarli_yerlesim(saglik):
    tab, _core, _win = saglik
    tab.setFixedSize(500, 400)
    tab.resizeEvent(QResizeEvent(QSize(500, 400), QSize(700, 400)))
    assert tab._overview_metrics.direction() == QBoxLayout.TopToBottom
    assert tab._hardware_metrics.direction() == QBoxLayout.TopToBottom
    assert tab._analysis_cards.direction() == QBoxLayout.TopToBottom

    tab.setFixedSize(700, 400)
    tab.resizeEvent(QResizeEvent(QSize(700, 400), QSize(500, 400)))
    assert tab._overview_metrics.direction() == QBoxLayout.LeftToRight
    assert tab._analysis_cards.direction() == QBoxLayout.TopToBottom

    tab.setFixedSize(1000, 400)
    tab.resizeEvent(QResizeEvent(QSize(1000, 400), QSize(700, 400)))
    assert tab._overview_metrics.direction() == QBoxLayout.LeftToRight
    assert tab._hardware_metrics.direction() == QBoxLayout.LeftToRight
    assert tab._analysis_cards.direction() == QBoxLayout.LeftToRight


def test_tema(saglik, monkeypatch):
    tab, _core, _win = saglik
    monkeypatch.setattr(health_mod.kit, 'dark_from',
                        lambda *_a, **_k: False)
    monkeypatch.setattr(health_mod.kit, 'faint',
                        lambda dark=True: 'FAINT({})'.format(dark))
    tab.apply_theme()
    assert tab.lbl_auto_sel.styleSheet() == 'FAINT(False)'

    def patlak_tema(*_a, **_k):
        raise RuntimeError('tema yok')

    monkeypatch.setattr(health_mod.kit, 'dark_from', patlak_tema)
    tab.apply_theme()
    assert tab.lbl_auto_sel.styleSheet() == 'FAINT(False)'


def test_yenileme_akislari(saglik, monkeypatch):
    tab, core, win = saglik
    yenilemeler = []

    def sahte_refresh():
        yenilemeler.append('perf')

    monkeypatch.setattr(tab.performance, 'refresh', sahte_refresh)

    # Genel durum: donanim okumasi kuyruga girer, ozet 'failure' olur
    tab.refresh()
    assert [d for _w, d in win.runs] == ['Donanım bilgisi']
    hw = win.runs[-1][0]
    assert hw.job_name == 'Donanım bilgisi'
    assert tab._read_workers['Donanım bilgisi'] is hw
    gorunum, islemci = hw._func()
    assert gorunum == core.engine.display
    assert islemci == core.engine.cpu
    assert core.engine.calls[-2:] == [('display_info', 'tv-1'),
                                      ('cpu_info', 'tv-1')]
    assert yenilemeler == ['perf']
    assert tab.lbl_measurement_state.text() == 'Ölçüm alınamadı'
    assert tab.btn_refresh.text() == 'Bekleyin…'
    assert tab.btn_refresh.isEnabled() is False

    # Ikinci yenileme ayni okumayi tekrar kuyruga koymaz
    tab.refresh()
    assert len(win.runs) == 1
    assert yenilemeler == ['perf', 'perf']

    # Donanim sonucu etiketlere yansir; bitince dugme tazelenir
    hw.finished_ok.emit((core.engine.display, core.engine.cpu))
    assert tab.lbl_display.text() == '1920×1080 @ 59.94Hz'
    assert tab.lbl_display_detail.text() == '320 dpi · HDMI: HDMI'
    assert tab.lbl_cpu.text() == 'Amlogic S905X4 (4 Çekirdek)'
    hw.tamamlandi = True
    hw.finished.emit()
    _olaylar()
    assert tab._read_workers.get('Donanım bilgisi') is None
    assert tab.btn_refresh.text() == 'Yenile'
    assert tab.btn_refresh.isEnabled() is True

    # Performans iscisi surerken: yukleniyor + izleme
    perf_w = _SahteIsci()
    perf_w.job_name = 'Cihaz analizi'
    tab.performance._busy = True
    tab.performance._worker = perf_w
    tab.refresh()
    assert tab.lbl_measurement_state.text() == 'Ölçüm alınıyor…'
    tab._watch_measurement_worker(perf_w)  # ayni isci ikinci kez izlenmez
    perf_w.failed.emit('analiz patladi')
    assert tab.lbl_measurement_state.text() == 'Ölçüm alınamadı'
    assert tab.lbl_overview.text() == 'Cihaz analizi: analiz patladi'
    perf_w.finished.emit()
    assert tab._summary_worker is None
    _olaylar()
    tab.performance._busy = False
    tab.performance._worker = None

    # Baglanti kuruluyor / cihaz yok
    win._connection_busy = True
    tab.refresh()
    assert tab.lbl_measurement_state.text() == 'Bağlantı kuruluyor…'
    assert tab.lbl_measurement_summary.text() == (
        'Cihaz bağlantısı tamamlandığında ölçüm alınabilir.')
    win._connection_busy = False

    core.connected = False
    tab.refresh()
    assert tab.lbl_measurement_state.text() == 'Cihaz bağlı değil'
    assert tab.lbl_measurement_summary.text() == 'Ölçüm için bir cihaza bağlanın.'
    core.connected = True
    core.target = ''
    tab.refresh()
    assert tab.lbl_measurement_state.text() == 'Cihaz bağlı değil'
    core.target = 'tv-1'

    # Cihaz ayarlari sayfasi: gorunur panele gore okuma
    okumalar = []
    monkeypatch.setattr(tab.display_panel, 'read_display',
                        lambda: okumalar.append('display'))
    monkeypatch.setattr(tab.background, 'refresh',
                        lambda: okumalar.append('background'))
    tab._open_section(tab.scroll_devices, tab.display_panel)
    tab.refresh()
    assert okumalar == ['display']
    tab._open_section(tab.scroll_devices, tab.background)
    tab.refresh()
    assert okumalar == ['display', 'background']
    tab.display_panel.hide()
    tab.background.hide()
    tab.refresh()
    assert okumalar == ['display', 'background']
    tab.display_panel.show()

    # Performans sayfasi (scroll_performance == scroll_maintenance)
    tab._open_section(tab.scroll_performance, tab.performance)
    tab.refresh()
    assert tab.lbl_measurement_state.text() == 'Ölçüm alınamadı'
    assert yenilemeler == ['perf', 'perf', 'perf']

    # refresh sonrasi isci uretilirse izlemeye alinir
    uretilen = _SahteIsci()
    uretilen.job_name = 'Cihaz analizi'

    def iscili_refresh():
        yenilemeler.append('perf-isci')
        tab.performance._worker = uretilen

    monkeypatch.setattr(tab.performance, 'refresh', iscili_refresh)
    tab.refresh()
    assert tab._summary_worker is uretilen
    tab.performance._worker = None


def test_baglanti_degisimi(saglik):
    tab, core, win = saglik
    tab._refresh_hardware()
    hw = tab._read_workers['Donanım bilgisi']
    tab._show({'disk_pct': 50, 'mem_pct': 40, 'disk_total_kb': 100,
               'disk_avail_kb': 50, 'mem_total_kb': 10, 'mem_avail_kb': 5})
    assert tab._health_measurements['disk_pct'] == 50
    tab.grid_top.insertRow(0)
    tab.grid_auto.insertRow(0)
    tab.lbl_perms.setText('x')
    tab.lbl_auto_found.setText('x')
    tab.lbl_auto_sel.setText('x')
    tab._set_operation_status('x')

    core.connection_changed.emit(True, 'tv-2')
    assert tab._generation == 1
    assert hw.cancel_calls == 1
    assert tab._read_workers.get('Donanım bilgisi') is not hw
    assert tab._health_measurements == {}
    assert tab.lbl_measurement_state.text() == 'Ölçüm alınmadı'
    assert tab.lbl_display.text() == '—'
    assert tab.lbl_display_detail.text() == 'Henüz ölçüm alınmadı'
    assert tab.lbl_cpu.text() == '—'
    assert tab.grid_top.rowCount() == 0
    assert tab.grid_auto.rowCount() == 0
    assert tab.lbl_perms.isHidden() is True
    assert tab.lbl_auto_found.text() == ''
    assert tab.lbl_auto_sel.text() == ''
    assert tab.lbl_overview.isHidden() is True
    assert win.runs[-1][1] == 'Donanım bilgisi'

    core.connection_changed.emit(False, '')
    assert tab._generation == 2
    assert tab.lbl_measurement_state.text() == 'Cihaz bağlı değil'
    assert tab._read_workers == {}


def test_donanim_gosterimi(saglik):
    tab, _core, _win = saglik
    tab._show_hardware((
        {'width': 1920, 'height': 1080, 'fps': 59.94, 'density': 320,
         'sink_name': 'HDMI2'},
        {'soc': 'Amlogic S905X4', 'cores': 4, 'abi': 'arm64-v8a',
         'temp': 42.5}))
    assert tab.lbl_display.text() == '1920×1080 @ 59.94Hz'
    assert tab.lbl_display_detail.text() == '320 dpi · HDMI: HDMI2'
    assert tab.lbl_cpu.text() == 'Amlogic S905X4 (4 Çekirdek)'
    assert tab.lbl_cpu_detail.text() == 'arm64-v8a · 42.5°C'

    # Eksik/kirik alanlar soru isaretine duser
    tab._show_hardware(({'width': 1280, 'height': 720, 'fps': 'abc',
                         'sink_name': 'TV'}, {'soc': 'X', 'cores': 2,
                                              'temp': '38°C'}))
    assert tab.lbl_display.text() == '1280×720 @ ?Hz'
    assert tab.lbl_display_detail.text() == '? dpi · HDMI: TV'
    assert tab.lbl_cpu_detail.text() == ' · 38°C'

    # Sink yoksa varsayilan; ayriç ile gelmis sicaklik korunur
    tab._show_hardware(({'width': 800, 'height': 600, 'fps': 60,
                         'sink_name': ''},
                        {'soc': 'Y', 'cores': 8, 'temp': ' · 40°C'}))
    assert tab.lbl_display.text() == '800×600 @ 60Hz'
    assert tab.lbl_display_detail.text() == '? dpi · HDMI: Android TV'
    assert tab.lbl_cpu_detail.text() == ' · 40°C'

    # temperature_c yedegi ve sifir disi deger
    tab._show_hardware(({'sink_name': 'TV', 'fps': None},
                        {'cores': 4, 'temperature_c': 31}))
    assert tab.lbl_display.text() == '?×? @ ?Hz'
    assert tab.lbl_cpu.text() == 'Bilinmeyen SoC (4 Çekirdek)'
    assert tab.lbl_cpu_detail.text() == ' · 31°C'

    # Bos sozlukler ve None bilgi
    tab._show_hardware(({}, {}))
    assert tab.lbl_display.text() == '—'
    assert tab.lbl_display_detail.text() == 'Ekran bilgisi okunamadı'
    assert tab.lbl_cpu.text() == '—'
    assert tab.lbl_cpu_detail.text() == 'İşlemci bilgisi okunamadı'

    tab._show_hardware((None, {'cores': 4, 'temp': None}))
    assert tab.lbl_display.text() == '—'
    assert tab.lbl_cpu.text() == 'Bilinmeyen SoC (4 Çekirdek)'
    assert tab.lbl_cpu_detail.text() == ''


def test_okuma_cercevesi(saglik):
    tab, core, win = saglik
    sonuclar = []

    def islev(engine, target):
        return ('sonuc', engine, target)

    # Mutlu yol: kayit, baglam ve sonuc iletimi
    tab._read('Test okuma', islev, sonuclar.append)
    w = win.runs[-1][0]
    assert win.runs[-1][1] == 'Test okuma'
    assert w.job_name == 'Test okuma'
    assert tab._read_workers['Test okuma'] is w

    tab._read('Test okuma', islev, sonuclar.append)
    assert len(win.runs) == 1

    # Pencere isleri arasinda ayni adli is suruyorsa atlanir
    mevcut = _SahteIsci()
    mevcut.job_name = 'Kopya is'
    win._workers = [mevcut]
    tab._read('Kopya is', islev, sonuclar.append)
    assert len(win.runs) == 1
    win._workers = []

    assert w._func() == ('sonuc', core.engine, 'tv-1')
    assert w.check_calls == 1

    # Bayat baglamda sonuc ve hata yansitilmaz
    core.target = 'tv-9'
    w.finished_ok.emit('bayat')
    assert sonuclar == []
    w.failed.emit('bayat hata')
    assert tab.lbl_overview.isHidden() is True
    core.target = 'tv-1'
    w.finished_ok.emit('taze')
    assert sonuclar == ['taze']
    w.failed.emit('taze hata')
    assert tab.lbl_overview.text() == 'Test okuma: taze hata'

    # Temizlik: kayit duser, dugme tazelenir
    w.tamamlandi = True
    w.finished.emit()
    assert 'Test okuma' not in tab._read_workers
    assert tab.btn_refresh.text() == 'Yenile'

    # Baska isci kaydin uzerine yazdiysa temizlik dokunmaz
    baska = _SahteIsci()
    tab._read_workers['Test okuma'] = baska
    w.finished.emit()
    assert tab._read_workers.get('Test okuma') is baska
    tab._read_workers.clear()

    # do(): iptal ve baglam degisimi
    tab._read('Iptal okuma', islev, sonuclar.append)
    w2 = win.runs[-1][0]
    w2.iptal_edildi = True
    with pytest.raises(CancelledError):
        w2._func()
    w2.iptal_edildi = False
    core.target = 'tv-2'
    with pytest.raises(CancelledError):
        w2._func()
    core.target = 'tv-1'
    w2.tamamlandi = True
    w2.finished.emit()
    assert tab._read_workers == {}
    temel = len(win.runs)

    # Kapilar: kapanma, baglanti, mesguliyet, motor
    win._closing = True
    tab._read('Kapanmis', islev, sonuclar.append)
    win._closing = False
    win._close_pending = True
    tab._read('Bekleyen kapanma', islev, sonuclar.append)
    win._close_pending = False
    assert len(win.runs) == temel

    core.connected = False
    tab._read('Baglantisiz', islev, sonuclar.append)
    assert tab.lbl_overview.text() == 'Önce cihaza bağlanın.'
    core.connected = True

    core.target = ''
    tab._read('Hedefsiz', islev, sonuclar.append)
    core.target = 'tv-1'

    win._connection_busy = True
    tab._read('Beklemede', islev, sonuclar.append)
    win._connection_busy = False
    assert len(win.runs) == temel

    core.motor_patlak = True
    tab._read('Motorsuz', islev, sonuclar.append)
    core.motor_patlak = False
    assert tab.lbl_overview.text() == 'Cihaz motoru hazır değil: motor yok'
    assert len(win.runs) == temel

    # Motor okunurken pencere kapanirsa okuma baslamaz
    core.motor_kanca = lambda: setattr(win, '_closing', True)
    tab._read('Kapanis ortasi', islev, sonuclar.append)
    core.motor_kanca = None
    win._closing = False
    assert len(win.runs) == temel

    # current(): motor kimligi tazelenirse okuma sessizce durur
    core.motor_taze = True
    tab._read('Taze motor', islev, sonuclar.append)
    core.motor_taze = False
    assert tab.lbl_overview.text() == 'Önce cihaza bağlanın.'
    assert len(win.runs) == temel

    # _run hata verirse kayit temizlenir, durum bildirilir
    win.run_patlak = True
    tab._read('Calistirilamayan', islev, sonuclar.append)
    win.run_patlak = False
    assert tab.lbl_overview.text() == ('Calistirilamayan başlatılamadı: '
                                       'calistirilamadi')
    assert tab._read_workers == {}

    # Hata sonrasi baglam bayatladiysa sessiz kalinir
    etiket = tab.lbl_overview.text()
    win.run_patlak = True
    win.run_kanca = lambda: setattr(core, 'target', 'tv-9')
    tab._read('Sessiz hata', islev, sonuclar.append)
    win.run_patlak = False
    win.run_kanca = None
    core.target = 'tv-1'
    assert tab.lbl_overview.text() == etiket
    assert tab._read_workers == {}


def test_olcum_gosterimi(saglik):
    tab, _core, _win = saglik
    tab._show({'disk_pct': 50, 'disk_total_kb': 1024 * 1024,
               'disk_avail_kb': 1024 * 512, 'mem_pct': 60,
               'mem_total_kb': 2048, 'mem_avail_kb': 1024,
               'pkg_total': 120, 'pkg_disabled': 3, 'pkg_removed_u0': 5})
    assert tab.lbl_measurement_state.text() == 'Ölçüm güncellendi'
    assert tab.lbl_measurement_summary.text() == (
        'Depolama doluluğu: %50. Bellek: %60 kullanım ölçüldü · '
        '1 MB kullanılabilir.')
    assert tab.lbl_disk.text() == '50%'
    assert tab.lbl_disk_detail.text() == (
        '512 MB kullanılıyor · 1.0 GB toplam · 512 MB boş')
    assert tab.bar_disk.value() == 50
    assert tab.lbl_mem.text() == '60%'
    assert tab.lbl_mem_detail.text() == '2 MB toplam · 1 MB kullanılabilir'
    assert tab.bar_mem.value() == 60
    assert tab.lbl_pkg.text() == '120'
    assert tab.lbl_pkg_detail.text() == ('3 devre dışı · 5 kullanıcı 0 için '
                                         'kaldırılmış')
    assert tab._health_measurements == {
        'disk_pct': 50, 'disk_total_kb': 1024 * 1024,
        'disk_avail_kb': 1024 * 512, 'mem_pct': 60,
        'mem_total_kb': 2048, 'mem_avail_kb': 1024}

    # Doluluk uyarilari ve geçersiz kullanılabilir bellek değeri
    tab._show({'disk_pct': 96, 'mem_pct': 91, 'mem_avail_kb': 'abc'})
    assert tab.lbl_measurement_state.text() == 'Ölçüm güncellendi'
    assert tab.lbl_measurement_summary.text() == (
        'Depolama %96 dolu. Büyük klasörleri inceleyip yer açmayı değerlendirin. '
        'Bellek: %91 kullanım ölçüldü.')

    tab._show({'disk_pct': 90})
    assert tab.lbl_measurement_state.text() == 'Kısmi ölçüm'
    assert tab.lbl_measurement_summary.text() == (
        'Depolama %90 dolu. Alan kullanımını gözden geçirin. Bellek ölçümü '
        'okunamadı.')
    assert tab.lbl_mem.text() == '—'
    assert tab.lbl_mem_detail.text() == 'Bellek verisi okunamadı'
    assert tab.bar_mem.value() == 0
    assert tab.bar_disk.value() == 90

    # Gecersiz yuzdeler atilir; hicbir ölçüm kalmaz
    tab._show({'disk_pct': 'abc', 'mem_pct': 150})
    assert tab.lbl_measurement_state.text() == 'Ölçüm alınamadı'
    assert tab.lbl_measurement_summary.text() == (
        'Depolama ve bellek değerleri alınamadı; yeniden deneyin.')
    assert tab.lbl_disk.text() == '—'
    assert tab.lbl_disk_detail.text() == 'Depolama verisi okunamadı'
    assert tab.bar_disk.value() == 0

    # Sifir yuzde gecerli; toplam/kullanilabilir bozuksa ayrinti sade kalir
    tab._show({'disk_pct': 0})
    assert tab.lbl_disk.text() == '0%'
    assert tab.lbl_disk_detail.text() == 'Depolama (/data)'
    assert tab.lbl_pkg.text() == '—'
    assert tab.lbl_pkg_detail.text() == 'Paket verisi okunamadı'

    tab._show({'disk_pct': 10, 'disk_total_kb': 'x', 'disk_avail_kb': 1})
    assert tab.lbl_disk_detail.text() == 'Depolama (/data)'

    # Bellek ölçülüp depolama ölçülemezse kismi durum
    tab._show({'mem_pct': 30})
    assert tab.lbl_measurement_state.text() == 'Kısmi ölçüm'
    assert tab.lbl_measurement_summary.text() == (
        'Depolama ölçümü okunamadı. Bellek: %30 kullanım ölçüldü.')

    # Durum metinleri
    tab._show({'disk_pct': 40}, state='loading')
    assert tab.lbl_measurement_state.text() == 'Ölçüm alınıyor…'
    assert tab.lbl_measurement_summary.text() == (
        'Yeni ölçüm alınıyor; son ölçülen değerler: Depolama doluluğu: %40.')

    tab._show({}, state='loading')
    assert tab.lbl_measurement_summary.text() == (
        'Depolama ve bellek verileri okunuyor.')

    tab._show({'disk_pct': 40}, state='failure')
    assert tab.lbl_measurement_summary.text() == (
        'Yenileme başarısız; son başarılı ölçüm: Depolama doluluğu: %40.')

    tab._show({}, state='failure')
    assert tab.lbl_measurement_summary.text() == (
        'Depolama ve bellek değerleri alınamadı; yeniden deneyin.')

    tab._show({}, state='offline')
    assert tab.lbl_measurement_state.text() == 'Cihaz bağlı değil'
    assert tab.lbl_measurement_summary.text() == 'Ölçüm için bir cihaza bağlanın.'

    tab._show({}, state='connecting')
    assert tab.lbl_measurement_state.text() == 'Bağlantı kuruluyor…'
    assert tab.lbl_measurement_summary.text() == (
        'Cihaz bağlantısı tamamlandığında ölçüm alınabilir.')

    tab._show({}, state='unmeasured')
    assert tab.lbl_measurement_summary.text() == (
        'Henüz ölçüm alınmadı. Yenile ile depolama ve bellek değerlerini okuyun.')

    # Bilinmeyen durum hataya duser
    tab._show({}, state='bilinmeyen')
    assert tab.lbl_measurement_state.text() == 'Ölçüm alınamadı'

    # Ölçüm yoksa 'measured' bile hataya cevrilir
    tab._show({}, state='measured')
    assert tab.lbl_measurement_state.text() == 'Ölçüm alınamadı'
    assert tab.lbl_measurement_state.property('role') == 'badge-accent'
    assert tab.lbl_measurement_summary.text() == (
        'Depolama ve bellek değerleri alınamadı; yeniden deneyin.')


def test_operasyon_durumu(saglik):
    tab, _core, _win = saglik
    tab._set_operation_status('Deneme')
    assert tab.lbl_overview.text() == 'Deneme'
    assert tab.lbl_overview.isHidden() is False
    tab._set_operation_status('')
    assert tab.lbl_overview.isHidden() is True


def test_isci_izleme_ve_dugme(saglik):
    tab, core, win = saglik
    HealthTab._sync_refresh_button(QObject())

    assert tab.btn_refresh.text() == 'Yenile'
    assert tab.btn_refresh.isEnabled() is True

    perf_w = _SahteIsci()
    perf_w.job_name = 'Cihaz analizi'
    tab._watch_measurement_worker(perf_w)
    assert tab._summary_worker is perf_w
    tab._watch_measurement_worker(perf_w)

    # Bayat hedef ve nesilde hata yansitilmaz
    core.target = 'tv-9'
    perf_w.failed.emit('bayat')
    assert tab.lbl_overview.isHidden() is True
    core.target = 'tv-1'
    tab._generation += 1
    perf_w.failed.emit('nesil')
    assert tab.lbl_overview.isHidden() is True
    tab._generation -= 1
    perf_w.failed.emit('guncel')
    assert tab.lbl_overview.text() == 'Cihaz analizi: guncel'

    # Baska iscinin bitisi ozet iscisini degistirmez
    tab._measurement_worker_finished(_SahteIsci())
    assert tab._summary_worker is perf_w
    perf_w.finished.emit()
    assert tab._summary_worker is None
    _olaylar()

    # Performans mesguliyeti dugmeyi bekletir
    tab.performance._busy = True
    tab._sync_refresh_button()
    assert tab.btn_refresh.text() == 'Bekleyin…'
    assert tab.btn_refresh.isEnabled() is False
    tab.performance._busy = False

    # Donanim iscisi bitmemisse bekler
    tab._refresh_hardware()
    hw = tab._read_workers['Donanım bilgisi']
    assert tab.btn_refresh.text() == 'Bekleyin…'
    hw.tamamlandi = True
    tab._sync_refresh_button()
    assert tab.btn_refresh.text() == 'Yenile'
    assert tab.btn_refresh.isEnabled() is True

    # Baglanti mesguliyeti ve hedefsizlik
    win._connection_busy = True
    tab._sync_refresh_button()
    assert tab.btn_refresh.isEnabled() is False
    win._connection_busy = False
    core.target = ''
    tab._sync_refresh_button()
    assert tab.btn_refresh.isEnabled() is False
    assert tab.btn_refresh.text() == 'Yenile'
    core.target = 'tv-1'


def test_depolama_taramasi(saglik):
    tab, core, win = saglik
    core.engine.top = [{'path': '/data/aaa', 'kb': 2048},
                       {'path': '/data/bbb', 'kb': 512}]
    tab._storage_top()
    w = win.runs[-1][0]
    assert win.runs[-1][1] == 'Depolama taraması'
    assert w.job_name == 'Depolama taraması'
    assert w._func() == core.engine.top
    assert core.engine.calls[-1] == ('storage_top', 'tv-1')

    w.finished_ok.emit(core.engine.top)
    assert tab.grid_top.rowCount() == 2
    assert tab.grid_top.item(0, 0).text() == '/data/aaa'
    assert tab.grid_top.item(0, 1).text() == '2 MB'
    assert tab.grid_top.item(1, 1).text() == '512 KB'
    assert not (tab.grid_top.item(0, 0).flags() & Qt.ItemIsEditable)
    w.tamamlandi = True
    w.finished.emit()

    # Bos sonuc ve uzun liste: yukseklik sinirlari
    tab._show_top([])
    assert tab.grid_top.rowCount() == 0
    assert tab.grid_top.maximumHeight() == 130

    tab._show_top([{'path': '/data/x{}'.format(i), 'kb': 10}
                   for i in range(5)])
    assert tab.grid_top.rowCount() == 5
    assert tab.grid_top.maximumHeight() == min(190, 5 * kit.ROW_H + 38)

    tab._show_top([{'path': '/data/y{}'.format(i), 'kb': 10}
                   for i in range(15)])
    assert tab.grid_top.rowCount() == 15
    assert tab.grid_top.maximumHeight() == 190

    # Okuma hatasi sonuc uretmez, durum bildirilir
    core.engine.top_patlak = True
    tab._storage_top()
    w2 = win.runs[-1][0]
    with pytest.raises(RuntimeError):
        w2._func()
    core.engine.top_patlak = False
    w2.failed.emit('tarama patladi')
    assert tab.lbl_overview.text() == 'Depolama taraması: tarama patladi'
    w2.tamamlandi = True
    w2.finished.emit()


def test_izinler(saglik, monkeypatch):
    tab, core, win = saglik
    bilgi = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgi.append(a))

    tab.txt_perm_pkg.setText('  ')
    tab._show_perms()
    assert bilgi[-1][1] == 'İzinler'
    assert bilgi[-1][2] == ('Geçerli bir paket adı yazın '
                            '(ör. org.videolan.vlc).')
    assert win.runs == []

    tab.txt_perm_pkg.setText('org.test.app')
    tab._show_perms()
    w = win.runs[-1][0]
    assert win.runs[-1][1] == 'İzin okuma'
    assert w._func() == {'all': [], 'granted': []}
    assert core.engine.calls[-1] == ('app_permissions', 'tv-1', 'org.test.app')

    w.finished_ok.emit({'all': [], 'granted': []})
    assert tab.lbl_perms.isHidden() is False
    assert tab.lbl_perms.text() == 'org.test.app: izin bilgisi okunamadı.'

    # Dolu liste: riskli izinler isaretlenir
    tab._render_perms('com.x', {
        'all': [{'perm': 'android.permission.CAMERA', 'granted': True},
                {'perm': 'android.permission.INTERNET', 'granted': False},
                {'perm': 'android.permission.ACCESS_FINE_LOCATION',
                 'granted': False}],
        'granted': ['android.permission.CAMERA']})
    satirlar = tab.lbl_perms.text().splitlines()
    assert satirlar[0] == 'com.x: 3 izin (1 verilmiş)'
    assert satirlar[1] == '✓ CAMERA ⚠'
    assert satirlar[2] == '✗ INTERNET'
    assert satirlar[3] == '✗ ACCESS_FINE_LOCATION ⚠'
    w.tamamlandi = True
    w.finished.emit()


def test_otomatik_baslayan(saglik):
    tab, core, win = saglik
    core.engine.autorun = {'com.a.one': True, 'com.b.two': False,
                           'com.c.three': 2, 'com.d.four': 1, 'kötü ad': 3}
    core.engine.labels = {'com.a.one': 'Bir Uygulama', 'com.b.two': '  '}
    win.tab_apps = SimpleNamespace(_apps=[
        'metin',
        {'package': 'com.b.two', 'label': 'İki Uygulama'}])
    core.config.isimler = {'com.c.three': 'Üç Uygulama'}
    core.config.hatali_isimler = {'com.d.four'}
    core.config.protected = {'com.b.two'}

    tab._autorun_scan()
    w = win.runs[-1][0]
    assert win.runs[-1][1] == 'Otomatik başlayan taraması'
    assert w.job_name == 'Otomatik başlayan taraması'
    assert w._func() == (core.engine.autorun, core.engine.labels)
    assert core.engine.calls[-2:] == [('autorun_receivers', 'tv-1'),
                                      ('app_labels', 'tv-1')]

    # Siralama kapaliyken eklenme sirasi korunur
    tab.grid_auto.setSortingEnabled(False)
    w.finished_ok.emit((core.engine.autorun, core.engine.labels))
    assert tab.grid_auto.rowCount() == 4
    isimler = [tab.grid_auto.item(r, AUTO_COL_NAME).text() for r in range(4)]
    assert isimler == ['Bir Uygulama', 'İki Uygulama', 'Üç Uygulama',
                       'com.d.four']
    paket = tab.grid_auto.item(0, AUTO_COL_PACKAGE)
    assert paket.text() == 'com.a.one'
    assert paket.data(Qt.UserRole) == 'com.a.one'
    assert not (paket.flags() & Qt.ItemIsEditable)
    korunan = tab.grid_auto.item(1, AUTO_COL_RESTRICT)
    assert not (korunan.flags() & Qt.ItemIsUserCheckable)
    assert korunan.toolTip() == 'Korunan paket kısıtlanamaz.'
    assert tab.grid_auto.item(0, AUTO_COL_RESTRICT).checkState() == Qt.Unchecked
    assert tab.lbl_auto_found.text() == '4 otomatik başlayan paket bulundu.'
    assert tab.lbl_auto_sel.text() == 'Seçili: 0/4'

    # Toplu isaretleme korunan paketi atlar
    tab._auto_toggle_all(True)
    assert tab.grid_auto.item(0, AUTO_COL_RESTRICT).checkState() == Qt.Checked
    assert korunan.checkState() == Qt.Unchecked
    assert tab.lbl_auto_sel.text() == 'Seçili: 3/4'
    tab._auto_toggle_all(False)
    assert tab.lbl_auto_sel.text() == 'Seçili: 0/4'

    # Sinyal korumasi: normal, ilk ve ikinci blok hatasi
    tab._auto_item_guard(tab.grid_auto.item(0, AUTO_COL_RESTRICT))

    class _Blok:
        def __init__(self, nerede):
            self.n = 0
            self.nerede = nerede

        def blockSignals(self, _flag):
            self.n += 1
            if self.n == self.nerede:
                raise RuntimeError('blok yok')
            return False

    ilk = _Blok(1)
    HealthTab._auto_item_guard(SimpleNamespace(grid_auto=ilk), None)
    assert ilk.n == 2
    ikinci = _Blok(2)
    HealthTab._auto_item_guard(SimpleNamespace(grid_auto=ikinci), None)
    assert ikinci.n == 2
    HealthTab._update_auto_count(SimpleNamespace(grid_auto=_Blok(0)))

    # Toggle kapanis hatasi yutulur
    class _ToggleFake:
        def __init__(self):
            self.n = 0
            self.lbl_auto_sel = SimpleNamespace(setText=lambda _t: None)

        def rowCount(self):
            return 0

        def blockSignals(self, _flag):
            self.n += 1
            if self.n == 2:
                raise RuntimeError('kapanis yok')
            return False

    toggle = _ToggleFake()
    HealthTab._auto_toggle_all(SimpleNamespace(
        grid_auto=toggle, lbl_auto_sel=toggle.lbl_auto_sel,
        _update_auto_count=lambda: None), True)
    assert toggle.n == 2

    # Etiket okumasi patlarsa bos etiketle devam edilir
    w.tamamlandi = True
    w.finished.emit()
    core.engine.autorun = {'com.a.one': 1}
    core.engine.labels = {}
    core.engine.labels_patlak = True
    tab._autorun_scan()
    w2 = win.runs[-1][0]
    bulunan, etiketler = w2._func()
    assert bulunan == {'com.a.one': 1}
    assert etiketler == {}
    core.engine.labels_patlak = False

    # Siralama acikken yeniden siralanir
    tab.grid_auto.setSortingEnabled(True)
    w2.finished_ok.emit((bulunan, etiketler))
    assert tab.grid_auto.isSortingEnabled() is True
    assert tab.grid_auto.rowCount() == 1
    assert tab.grid_auto.item(0, AUTO_COL_NAME).text() == 'com.a.one'

    # Bos, bozuk ve etiketsiz girdiler
    tab._show_autorun((), None)
    assert tab.grid_auto.rowCount() == 0
    assert tab.lbl_auto_found.text() == '0 otomatik başlayan paket bulundu.'
    assert tab.grid_auto.maximumHeight() == 130

    tab._show_autorun(['x'])
    assert tab.grid_auto.rowCount() == 0

    tab._show_autorun({'com.a.one': 1}, labels=['liste'])
    assert tab.grid_auto.rowCount() == 1
    assert tab.grid_auto.item(0, AUTO_COL_NAME).text() == 'com.a.one'
    assert tab.grid_auto.item(0, AUTO_COL_RESTRICT).checkState() == Qt.Unchecked

    # Isim cozumleme yedekleri
    assert tab._autorun_app_name('com.yok', {'com.yok': 'Etiket'}) == 'Etiket'
    assert tab._autorun_app_name('com.yok', {'com.yok': 'com.yok'}) == 'com.yok'
    bos_yardimci = SimpleNamespace(
        window=SimpleNamespace(tab_apps=None),
        core=SimpleNamespace(config=SimpleNamespace()))
    assert HealthTab._autorun_app_name(bos_yardimci, 'com.z.z') == 'com.z.z'
    w2.tamamlandi = True
    w2.finished.emit()


def test_kisitlama(saglik, monkeypatch):
    tab, core, win = saglik
    kutular = []
    onaylar = []
    isciler = []

    class _BulkIsci(QObject):
        finished_ok = Signal(object)
        failed = Signal(str)
        finished = Signal()

        def __init__(self, *args, **kwargs):
            super().__init__()
            self.args = args
            self.kwargs = kwargs
            self.job_name = ''
            self.tamamlandi = False
            isciler.append(self)

        def isFinished(self):
            return self.tamamlandi

    class _Kutu(QMessageBox):
        @staticmethod
        def information(parent, title, text, *args, **kwargs):
            kutular.append(('bilgi', title, text))
            return QMessageBox.Ok

        def exec(self):
            kutular.append(('dialog', self.windowTitle(), self.text(),
                            self.detailedText()))
            return 0

    monkeypatch.setattr(health_mod, 'QMessageBox', _Kutu)
    monkeypatch.setattr(workers_mod, 'BulkActionWorker', _BulkIsci)

    def onayla(*args):
        onaylar.append(args)
        return True

    monkeypatch.setattr(dialogs_mod, 'confirm_action', onayla)

    tab._show_autorun({'com.a.one': 1, 'com.b.two': 1})
    tab._auto_toggle_all(True)
    assert tab.lbl_auto_sel.text() == 'Seçili: 2/2'

    # Kapilar: kapanma, baglanti, mesguliyet, motor
    win._closing = True
    tab._autorun_restrict()
    win._closing = False
    assert win.runs == [] and isciler == []

    core.connected = False
    tab._autorun_restrict()
    assert tab.lbl_overview.text() == 'Önce cihaza bağlanın.'
    core.connected = True

    win._connection_busy = True
    tab._autorun_restrict()
    win._connection_busy = False
    assert isciler == []

    core.motor_patlak = True
    tab._autorun_restrict()
    core.motor_patlak = False
    assert tab.lbl_overview.text() == 'Cihaz motoru hazır değil: motor yok'

    # Motor okunurken pencere kapanirsa sessiz kalinir
    core.motor_kanca = lambda: setattr(win, '_closing', True)
    tab._autorun_restrict()
    core.motor_kanca = None
    win._closing = False
    assert isciler == []

    # Bekleyen pencere isi
    win._workers = [SimpleNamespace(job_name='X', isFinished=lambda: False)]
    tab._autorun_restrict()
    assert tab.lbl_auto_found.text() == (
        'Bağlantının kurulmasını ve diğer işlemlerin bitmesini bekleyin.')
    win._workers = []

    # Secim yok
    tab._auto_toggle_all(False)
    tab._autorun_restrict()
    assert kutular[-1] == ('bilgi', 'Seçim',
                           'Önce Kısıtla sütununda işaretleyin.')
    assert isciler == []

    # Onay reddedilirse isci olusmaz
    tab._auto_toggle_all(True)
    onaylar.clear()
    monkeypatch.setattr(dialogs_mod, 'confirm_action',
                        lambda *a: (onaylar.append(a), False)[1])
    tab._autorun_restrict()
    assert onaylar and onaylar[-1][1] == 'restrict'
    assert set(onaylar[-1][2]) == {'com.a.one', 'com.b.two'}
    assert isciler == []

    # Onay: isci kurulur
    monkeypatch.setattr(dialogs_mod, 'confirm_action', onayla)
    tab._autorun_restrict()
    assert len(isciler) == 1
    isci = isciler[-1]
    assert isci.args[:2] == (core.engine, 'tv-1')
    assert set(isci.args[2]) == {'com.a.one', 'com.b.two'}
    assert isci.args[3] is True
    assert isci.args[4] == set()
    assert isci.kwargs.get('validate_packages') is True
    assert win.runs[-1][1] == 'Sağlık: 2 paket kısıtlanıyor'
    assert tab._read_workers['Otomatik başlama kısıtlaması'] is isci

    # Basari raporu: detaylar satirlara dokulur, bozuk oge atlanir
    isci.finished_ok.emit({'ok': 2, 'skip': 1, 'details': [
        ('com.a.one', True, 'kısıtlandı'),
        ('com.b.two', False, ''),
        'bozuk',
        ('com.c.three', True, 'x')]})
    isci.finished.emit()
    _olaylar()
    assert tab.lbl_auto_found.text() == '2 başarılı, 1 atlandı.'
    assert kutular[-1] == (
        'dialog', 'Tamam', '2 başarılı, 1 atlandı.',
        'com.a.one: başarılı (kısıtlandı)\ncom.b.two: atlandı\n'
        'com.c.three: başarılı (x)')
    assert 'Otomatik başlama kısıtlaması' not in tab._read_workers

    # Hata raporu
    tab._auto_toggle_all(True)
    tab._autorun_restrict()
    isci2 = isciler[-1]
    isci2.failed.emit('yetki yok')
    isci2.finished.emit()
    _olaylar()
    assert tab.lbl_auto_found.text() == 'Kısıtlama başarısız: yetki yok'

    # Sozluk olmayan sonuc
    tab._autorun_restrict()
    isci3 = isciler[-1]
    isci3.finished_ok.emit('metin')
    isci3.finished.emit()
    _olaylar()
    assert tab.lbl_auto_found.text() == 'Kısıtlama sonucu alınamadı.'

    # Ayrintisiz bos sozluk
    tab._autorun_restrict()
    isci4 = isciler[-1]
    isci4.finished_ok.emit({'ok': 0, 'skip': 0})
    isci4.finished.emit()
    _olaylar()
    assert tab.lbl_auto_found.text() == '0 başarılı, 0 atlandı.'
    assert kutular[-1] == ('dialog', 'Tamam', '0 başarılı, 0 atlandı.', '')

    # Onaydan sonra kapanma / baglam degisimi
    def kapanis_onay(*_a):
        win._closing = True
        return True

    monkeypatch.setattr(dialogs_mod, 'confirm_action', kapanis_onay)
    onceki = len(isciler)
    tab._autorun_restrict()
    win._closing = False
    assert len(isciler) == onceki

    def hedef_onay(*_a):
        core.target = 'tv-9'
        return True

    monkeypatch.setattr(dialogs_mod, 'confirm_action', hedef_onay)
    tab._autorun_restrict()
    assert tab.lbl_auto_found.text() == (
        'Bağlantı veya işlem durumu değişti. Yeniden deneyin.')
    assert len(isciler) == onceki
    core.target = 'tv-1'

    # _run hatasi: kayit temizlenir, durum bildirilir
    monkeypatch.setattr(dialogs_mod, 'confirm_action', onayla)
    win.run_patlak = True
    tab._autorun_restrict()
    win.run_patlak = False
    assert len(isciler) == onceki + 1
    assert tab.lbl_auto_found.text() == ('Kısıtlama başlatılamadı: '
                                         'calistirilamadi')
    assert 'Otomatik başlama kısıtlaması' not in tab._read_workers

    # _run hatasi + bayat baglam: sessiz kalinir
    etiket = tab.lbl_auto_found.text()
    win.run_patlak = True
    win.run_kanca = lambda: setattr(core, 'target', 'tv-9')
    tab._autorun_restrict()
    win.run_patlak = False
    win.run_kanca = None
    core.target = 'tv-1'
    assert tab.lbl_auto_found.text() == etiket

    # Rapor aninda bayat baglam: sonuc yazilmaz
    tab._autorun_restrict()
    isci5 = isciler[-1]
    isci5.finished_ok.emit('metin2')
    isci5.finished.emit()
    core.target = 'tv-9'
    _olaylar()
    assert tab.lbl_auto_found.text() == etiket
    core.target = 'tv-1'



