# -*- coding: utf-8 -*-
"""files_tab: gezinme, liste/filtre, aktarim ve dosya islemleri."""
import os
from types import SimpleNamespace

import pytest
from PySide6.QtCore import (
    QMimeData,
    QObject,
    QPoint,
    QPointF,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
)

from mibox_app.ui import files_tab as files_mod
from mibox_app.ui.files_tab import (
    COL_MTIME,
    COL_NAME,
    COL_SIZE,
    FilesTab,
)
from mibox_app.workers import CancelledError


class _Motor:
    def __init__(self):
        self.calls = []
        self.listeler = []
        self.list_patlak = False
        self.push_patlak = False
        self.push_kanca = None
        self.pull_patlak = False
        self.pull_kanca = None
        self.pull_yaz = True
        self.pull_sil = False
        self.pull_boyut = 3
        self.usb = []
        self.usb_patlak = False

    def file_list(self, target, cwd):
        self.calls.append(('file_list', target, cwd))
        if self.list_patlak:
            raise RuntimeError('liste alinamadi')
        return self.listeler.pop(0) if self.listeler else []

    def usb_storages(self, target):
        self.calls.append(('usb_storages', target))
        if self.usb_patlak:
            raise RuntimeError('usb yok')
        return list(self.usb)

    def push(self, target, path, remote, cancel_check=None):
        self.calls.append(('push', target, path, remote))
        if self.push_patlak:
            if self.push_kanca is not None:
                self.push_kanca()
            raise RuntimeError('push patladi')
        return {'ok': True}

    def pull(self, target, remote, staged, cancel_check=None):
        self.calls.append(('pull', target, remote, staged))
        if self.pull_patlak:
            if self.pull_kanca is not None:
                self.pull_kanca()
            raise RuntimeError('pull patladi')
        if self.pull_yaz:
            with open(staged, 'wb') as f:
                f.write(b'x' * self.pull_boyut)
        if self.pull_sil:
            os.remove(staged)
        return {'ok': True}

    def file_mkdir(self, target, remote):
        self.calls.append(('file_mkdir', target, remote))
        return {'ok': True}

    def file_remove(self, target, full):
        self.calls.append(('file_remove', target, full))
        return {'ok': True}

    def rename_file(self, target, old, new):
        self.calls.append(('rename_file', target, old, new))
        return {'ok': True}

    def install_remote_apk(self, target, remote, grant_perms=True):
        self.calls.append(('install_remote_apk', target, remote, grant_perms))
        return {'result': 'ok'}


class _Yapilandirma:
    def __init__(self):
        self.install_grant_perms = True


class _Cekirdek(QObject):
    connection_changed = Signal(bool, object)

    def __init__(self):
        super().__init__()
        self.connected = True
        self.target = 'tv-1'
        self.engine = _Motor()
        self.config = _Yapilandirma()


class _Pencere:
    def __init__(self):
        self.runs = []
        self._connection_busy = False
        self._closing = False
        self._close_pending = False
        self.patlak_run = False

    def _run(self, worker, desc=None):
        if self.patlak_run:
            raise RuntimeError('patladi')
        self.runs.append((worker, desc))


class _SahteIsci(QObject):
    finished_ok = Signal(object)
    failed = Signal(str)
    finished = Signal()
    progress = Signal(int, int)
    log = Signal(str)

    def __init__(self, func=None, *args, **kwargs):
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs
        self.job_name = ''
        self.iptal_edildi = False
        self.kanca = None
        self.interrupted = False
        self.check_calls = 0
        self.cancel_calls = 0
        self.silindi = 0
        self.loglar = []

    def check_cancel(self):
        self.check_calls += 1
        if self.kanca is not None:
            self.kanca()
        if self.iptal_edildi:
            raise CancelledError('kullanıcı durdurdu')

    def cancel(self):
        self.cancel_calls += 1

    def isInterruptionRequested(self):
        return self.interrupted

    def deleteLater(self):
        self.silindi += 1


class _Dugme:
    def __init__(self):
        self.enabled = None

    def setEnabled(self, value):
        self.enabled = value


class _Satir:
    def __init__(self):
        self.oge = []

    def count(self):
        return len(self.oge)

    def itemAt(self, index):
        return self.oge[index]


@pytest.fixture
def dosya(qtbot, monkeypatch):
    monkeypatch.setattr(files_mod, 'Worker', _SahteIsci)
    core = _Cekirdek()
    win = _Pencere()
    tab = FilesTab(core, win)
    qtbot.addWidget(tab)
    return tab, core, win


def _giris(name='a.txt', dir=False, size=1024, mtime='2026-01-01 10:00'):
    return {'name': name, 'dir': dir, 'size': size, 'mtime': mtime}


def _secili(tab, row):
    tab.grid.selectRow(row)


def test_fmt_size():
    assert files_mod._fmt_size(None) == '?'
    assert files_mod._fmt_size('abc') == '?'
    assert files_mod._fmt_size(500) == '500 B'
    assert files_mod._fmt_size(2048) == '2 KB'
    assert files_mod._fmt_size('1024') == '1 KB'
    assert files_mod._fmt_size(5 * 1024 * 1024) == '5 MB'
    assert files_mod._fmt_size(int(2.5 * 1024 ** 3)) == '2.5 GB'


def test_remote_child():
    assert FilesTab._remote_child('/sdcard', 'a.txt') == '/sdcard/a.txt'
    assert FilesTab._remote_child('/sdcard/', 'a') == '/sdcard/a'
    assert FilesTab._remote_child('/', 'a') == '/a'


def test_kurulum(dosya):
    tab, _core, _win = dosya
    assert tab.txt_path.text() == '/sdcard'
    assert tab.lbl_breadcrumb.text() == ' /  sdcard'
    assert tab.grid.columnCount() == 3
    basliklar = [tab.grid.horizontalHeaderItem(i).text() for i in range(3)]
    assert basliklar == ['Ad', 'Boyut', 'Değişiklik']
    assert tab.btn_back.isEnabled() is False
    assert tab.btn_up.isEnabled() is True
    assert tab.btn_go.isEnabled() is True
    assert tab.btn_refresh.isEnabled() is True
    assert tab.btn_push.isEnabled() is True
    assert tab.btn_mkdir.isEnabled() is True
    assert tab.btn_del.isEnabled() is False
    assert tab.btn_rename.isEnabled() is False
    assert tab.btn_pull.isEnabled() is False
    assert tab.btn_install_remote.isEnabled() is False
    assert tab.progress_transfer.isHidden() is True
    assert tab.btn_stop_transfer.isHidden() is True
    assert tab.lbl_status.text() == 'Hazır. Yenile ile listele.'
    assert tab.lbl_transfer_context.text() == (
        'Seçim: yok\nCihaza yükleme hedefi: /sdcard')
    assert tab.lbl_list_summary.text() == 'Dosya listesi henüz yüklenmedi.'
    assert tab.roots_row.count() == 4
    adlar = [tab.roots_row.itemAt(i).widget().text() for i in range(4)]
    assert adlar == ['Depolama', 'İndirilenler', 'Filmler', 'Kamera']
    assert tab.roots_row.itemAt(0).widget().toolTip() == '/sdcard'


def test_gezinme(dosya):
    tab, _core, win = dosya
    tab._go('/sdcard/Download')
    assert tab._cwd == '/sdcard/Download'
    assert tab._hist == ['/sdcard']
    assert tab.txt_path.text() == '/sdcard/Download'
    assert tab.lbl_breadcrumb.text() == ' /  sdcard  /  Download'
    assert tab._loaded is False
    assert tab._entries == []
    assert tab.grid.rowCount() == 0
    assert tab.lbl_list_summary.text() == 'Dosya listesi henüz yüklenmedi.'
    assert tab.lbl_status.text() == '/sdcard/Download: okunuyor…'
    assert tab.btn_back.isEnabled() is True
    assert tab.btn_up.isEnabled() is True
    assert [desc for _w, desc in win.runs] == ['USB sürücü kontrolü',
                                               'Dosyalar Yenile: liste okunuyor']
    assert win.runs[-1][0]._files_request_context == (
        1, 'tv-1', '/sdcard/Download')

    tab._go('/sdcard/Download')
    assert tab._hist == ['/sdcard']

    tab._back()
    assert tab._cwd == '/sdcard'
    assert tab._hist == []
    assert tab.lbl_breadcrumb.text() == ' /  sdcard'
    assert tab.btn_back.isEnabled() is False

    tab._up()
    assert tab._cwd == '/'
    assert tab.lbl_breadcrumb.text() == '/'
    assert tab.btn_up.isEnabled() is False

    tab._up()
    assert tab._cwd == '/'

    tab.txt_path.setText('x/y')
    tab._go_typed()
    assert tab._cwd == '/x/y'

    tab.txt_path.setText('')
    tab._go_typed()
    assert tab._cwd == '/sdcard'
    assert tab._hist == ['/sdcard', '/', '/x/y']

    tab._operation_busy = True
    tab._go('/a')
    tab._back()
    assert tab._cwd == '/sdcard'
    tab._operation_busy = False

    tab.roots_row.itemAt(1).widget().click()
    assert tab._cwd == '/sdcard/Download'


def test_liste_sonuclari(dosya):
    tab, core, win = dosya
    tab.refresh()
    list_w = win.runs[-1][0]
    core.engine.listeler = [[_giris(name='gercek')]]
    sonuc = list_w._func()
    assert sonuc[0] == 1
    assert sonuc[1] == 'tv-1'
    assert sonuc[2] == '/sdcard'
    assert sonuc[3][0]['name'] == 'gercek'
    assert core.engine.calls[-1] == ('file_list', 'tv-1', '/sdcard')
    entries = [_giris(), _giris(name='Klasör', dir=True, size=0)]
    list_w.finished_ok.emit((1, 'tv-1', '/sdcard', entries))
    assert tab._loaded is True
    assert tab._entries == entries
    assert tab.grid.rowCount() == 2
    assert tab.lbl_status.text() == 'Klasör içeriği güncellendi.'

    list_w.finished_ok.emit((99, 'tv-1', '/sdcard', [_giris(name='yeni')]))
    assert tab._entries == entries

    onceki = tab.lbl_status.text()
    tab._operation_busy = True
    list_w.finished_ok.emit((1, 'tv-1', '/sdcard', entries))
    assert tab.lbl_status.text() == onceki
    tab._operation_busy = False

    onceki = tab.lbl_status.text()
    tab._status_request_floor = 50
    list_w.finished_ok.emit((1, 'tv-1', '/sdcard', entries))
    assert tab.lbl_status.text() == onceki
    tab._status_request_floor = 0

    onceki = tab.lbl_status.text()
    list_w.finished_ok.emit((1, 'tv-9', '/sdcard', entries))
    assert tab.lbl_status.text() == onceki

    tab.refresh()
    yeni_w = win.runs[-1][0]
    yeni_w.failed.emit('kopma')
    assert tab.lbl_status.text() == 'Dosya listesi yüklenemedi: kopma'

    onceki = tab.lbl_status.text()
    tab._show_list_error('sahipsiz')
    assert tab.lbl_status.text() == onceki

    yeni_w.failed.emit('yine kopma')
    assert tab.lbl_status.text() == 'Dosya listesi yüklenemedi: yine kopma'

    tab._loaded = False
    yeni_w.failed.emit('üçüncü kopma')
    assert tab._empty_context[0] == 'Klasör okunamadı'

    tab._operation_busy = True
    onceki = tab.lbl_status.text()
    yeni_w.failed.emit('dördüncü kopma')
    assert tab.lbl_status.text() == onceki
    tab._operation_busy = False

    yeni_w.failed.emit('beşinci kopma')
    assert tab.lbl_status.text() == 'Dosya listesi yüklenemedi: beşinci kopma'


def test_yenileme_sorunlari(dosya):
    tab, core, _win = dosya
    assert tab._connection_problem() == ''
    assert tab._connection_problem('tv-1') == ''
    assert tab._connection_problem('tv-9') == (
        'Bağlı cihaz değişti. Dosya işlemini yeniden başlatın.')

    core.connected = False
    assert tab._connection_problem() == (
        'Cihaz bağlı değil. Dosya işlemleri için önce bağlanın.')
    tab.refresh()
    assert tab._loaded is False
    assert tab._empty_context == (
        'Cihaz bağlı değil',
        'Dosyaları görmek için cihaza bağlanın, ardından Yenile’ye basın.')
    assert tab.lbl_status.text() == (
        'Cihaz bağlı değil. Dosya işlemleri için önce bağlanın.')
    core.connected = True

    _win._connection_busy = True
    assert tab._connection_problem() == (
        'Bağlantı işlemi sürüyor; tamamlanınca yeniden deneyin.')
    assert tab._can_mutate() is False
    assert tab.lbl_status.text() == (
        'Bağlantı işlemi sürüyor; tamamlanınca yeniden deneyin.')
    _win._connection_busy = False

    tab._operation_busy = True
    assert tab._can_mutate() is False
    assert tab.lbl_status.text() == 'Başka bir dosya işlemi sürüyor.'
    tab._operation_busy = False
    assert tab._can_mutate() is True

    core.target = ''
    tab.refresh()
    assert tab._empty_context == ('Dosya listesi bekliyor',
                                  'Bağlı cihaz hedefi bulunamadı.')
    assert tab.lbl_status.text() == 'Bağlı cihaz hedefi bulunamadı.'

    tab._loaded = True
    tab._empty_context = ('Korunmalı', 'değişmemeli')
    tab.refresh()
    assert tab._empty_context == ('Korunmalı', 'değişmemeli')
    tab._loaded = False
    core.target = 'tv-1'

    tab._operation_busy = True
    tab.refresh()
    tab._operation_busy = False

    tab._clear_view('Başlık', 'Açıklama')
    assert tab._loaded is False
    assert tab._empty_context == ('Başlık', 'Açıklama')
    assert tab.grid.rowCount() == 0
    assert tab.lbl_list_summary.text() == 'Dosya listesi henüz yüklenmedi.'


def test_baglanti_degisimi(dosya):
    tab, core, win = dosya
    tab._loaded = True
    core.connection_changed.emit(True, 'tv-2')
    assert tab._connection_generation == 1
    assert tab._loaded is False
    assert tab._empty_context == (
        'Dosyalar henüz yüklenmedi',
        'Bağlantı değişti; yeni cihazın klasör içeriğini Yenile ile alın.')
    assert tab.lbl_status.text() == 'Bağlantı değişti: tv-2. Yenile ile listeleyin.'
    assert win.runs[-1][1] == 'USB sürücü kontrolü'
    assert tab.roots_row.count() == 4

    core.connection_changed.emit(False, None)
    assert tab._empty_context == (
        'Dosyalar henüz yüklenmedi',
        'Cihaza bağlanın ve Yenile ile klasör içeriğini alın.')
    assert tab.lbl_status.text() == 'Cihaz bağlantısı kesildi.'


def test_usb_depolama(dosya):
    tab, core, win = dosya
    core.engine.usb = [
        {'path': '/mnt/usb', 'name': 'Bellek', 'free': 1024 ** 3},
        {'path': ''},
        {'path': '/mnt/usb2'},
    ]
    tab.refresh()
    usb_w = win.runs[-2][0]
    assert usb_w.job_name == 'USB kontrolü'
    assert usb_w._func() == ('tv-1', 0, core.engine.usb)

    usb_w.finished_ok.emit(('tv-1', 0, list(core.engine.usb)))
    assert [b.text() for b in tab._usb_buttons] == ['💾 USB: Bellek',
                                                    '💾 USB: usb2']
    assert tab.roots_row.count() == 6
    assert tab._usb_buttons[0].toolTip() == '/mnt/usb (Boş alan: 1.0 GB)'
    assert tab._usb_buttons[0].isEnabled() is True

    tab._usb_buttons[0].click()
    assert tab._cwd == '/mnt/usb'

    onceki = [b.text() for b in tab._usb_buttons]
    usb_w.finished_ok.emit(('tv-1', 99, list(core.engine.usb)))
    assert [b.text() for b in tab._usb_buttons] == onceki
    usb_w.finished_ok.emit(('tv-9', 0, list(core.engine.usb)))
    assert [b.text() for b in tab._usb_buttons] == onceki

    core.connected = False
    usb_w.finished_ok.emit(('tv-1', 0, list(core.engine.usb)))
    assert [b.text() for b in tab._usb_buttons] == onceki
    core.connected = True

    tab._update_usb_buttons([])
    assert tab._usb_buttons == []
    assert tab.roots_row.count() == 4

    tab._check_usb_storages('')
    tab._check_usb_storages('tv-1')
    assert win.runs[-1][1] == 'USB sürücü kontrolü'

    core.engine.usb_patlak = True
    patlak_w = win.runs[-1][0]
    assert patlak_w._func() == ('tv-1', 0, [])


def test_filtre_ve_ozet(dosya):
    tab, _core, _win = dosya
    entries = [
        _giris(name='Klasör', dir=True, size=0),
        _giris(name='film.mp4', size=2048),
        _giris(name='garip.bin', size=-1),
        _giris(name='boyut.bin', size='abc'),
    ]
    tab._show(entries)
    assert tab._loaded is True
    assert tab.grid.rowCount() == 4
    assert tab.grid.item(0, COL_NAME).text() == '📁 Klasör'
    assert tab.grid.item(0, COL_SIZE).text() == ''
    assert tab.grid.item(1, COL_NAME).text() == '📄 film.mp4'
    assert tab.grid.item(1, COL_SIZE).text() == '2 KB'
    assert tab.grid.item(1, COL_MTIME).text() == '2026-01-01 10:00'
    item = tab.grid.item(1, COL_NAME)
    assert not (item.flags() & Qt.ItemIsEditable)
    assert item.data(Qt.UserRole) == entries[1]
    assert tab.lbl_list_summary.text() == (
        'Yüklenen listede 4 öğe · gösterilen 4 öğe (3 dosya, 2 KB · '
        '2 dosyanın boyutu bilinmiyor)')

    tab.txt_filter.setText('film')
    assert tab.grid.rowCount() == 1
    assert tab.lbl_list_summary.text() == (
        'Yüklenen listede 4 öğe · gösterilen 1 öğe (1 dosya, 2 KB)')

    tab._update_list_summary()
    assert tab.lbl_list_summary.text() == (
        'Yüklenen listede 4 öğe · gösterilen 1 öğe (1 dosya, 2 KB)')

    tab.txt_filter.setText('yokboyle')
    assert tab.grid.rowCount() == 0

    tab.txt_filter.setText('')
    assert tab.grid.rowCount() == 4

    tab._show([])
    assert tab.lbl_list_summary.text() == (
        'Yüklenen listede 0 öğe · gösterilen 0 öğe (0 dosya, 0 B)')

    tab._show(None)
    assert tab._entries == []

    tab._loaded = False
    tab._apply_filter()
    assert tab.lbl_list_summary.text() == 'Dosya listesi henüz yüklenmedi.'
    tab._loaded = True

    FilesTab._update_list_summary(SimpleNamespace())
    tab2 = SimpleNamespace()
    tab2._loaded = False
    tab2.lbl_list_summary = tab.lbl_list_summary
    FilesTab._update_list_summary(tab2)
    assert tab.lbl_list_summary.text() == 'Dosya listesi henüz yüklenmedi.'


def test_secim_ve_dugmeler(dosya):
    tab, _core, _win = dosya
    tab._show([
        _giris(name='Klasör', dir=True, size=0),
        _giris(name='film.mp4', size=2048),
        _giris(name='uygulama.APK', size=4096),
    ])
    _secili(tab, 0)
    assert tab._selected() == tab._entries[0]
    assert tab.lbl_transfer_context.text().startswith('Seçili klasör: Klasör')
    assert tab.btn_pull.isEnabled() is False
    assert tab.btn_install_remote.isEnabled() is False
    assert tab.btn_del.isEnabled() is True
    assert tab.btn_rename.isEnabled() is True

    _secili(tab, 1)
    assert tab.lbl_transfer_context.text() == (
        'Seçili dosya: film.mp4 (2 KB)\nCihaza yükleme hedefi: /sdcard')
    assert tab.btn_pull.isEnabled() is True
    assert tab.btn_install_remote.isEnabled() is False

    _secili(tab, 2)
    assert tab.btn_install_remote.isEnabled() is True
    assert tab.btn_pull.isEnabled() is True

    tab.grid.clearSelection()
    tab.grid.setCurrentCell(-1, -1)
    tab._update_action_buttons()
    assert tab._selected() is None
    assert tab.lbl_transfer_context.text().startswith('Seçim: yok')

    tab.grid.insertRow(0)
    tab.grid.setCurrentCell(0, COL_NAME)
    assert tab._selected() is None

    tab._operation_busy = True
    tab._update_action_buttons()
    assert tab.btn_push.isEnabled() is False
    assert tab.btn_mkdir.isEnabled() is False
    assert tab.btn_del.isEnabled() is False
    assert tab.btn_refresh.isEnabled() is False
    assert tab.btn_back.isEnabled() is False
    assert tab.btn_up.isEnabled() is False
    assert tab.txt_path.isEnabled() is False
    tab._operation_busy = False

    FilesTab._update_transfer_context(SimpleNamespace())

    ns = SimpleNamespace(
        _operation_busy=False, _hist=[], _cwd='/sdcard',
        btn_back=_Dugme(), btn_up=_Dugme(), btn_go=_Dugme(),
        txt_path=_Dugme(), roots_row=_Satir(),
        btn_refresh=_Dugme(), btn_push=_Dugme(), btn_mkdir=_Dugme(),
        btn_del=_Dugme(), btn_pull=_Dugme(), btn_install_remote=_Dugme(),
        _connection_problem=lambda *a: '', _selected=lambda: None,
        _update_transfer_context=lambda: None)
    FilesTab._update_action_buttons(ns)
    assert ns.btn_back.enabled is False
    assert ns.btn_refresh.enabled is True
    assert ns.btn_up.enabled is True
    assert ns.btn_push.enabled is True
    assert ns.btn_del.enabled is False


def test_cift_tiklama(dosya):
    tab, _core, _win = dosya
    tab._show([_giris(name='Klasör', dir=True, size=0), _giris(name='a.txt')])
    tab._on_double(tab.grid.model().index(1, 0))
    assert tab._cwd == '/sdcard'
    tab._on_double(tab.grid.model().index(0, 0))
    assert tab._cwd == '/sdcard/Klasör'
    tab._on_double(tab.grid.model().index(5, 0))
    assert tab._cwd == '/sdcard/Klasör'


def test_mutasyon_cercevesi(dosya):
    tab, core, win = dosya
    kayitlar = []

    tab._operation_busy = True
    w = _SahteIsci(lambda: 42)
    tab._start_mutation(w, 'deneme', lambda r: None)
    assert w.silindi == 1
    assert tab._operation_worker is None
    tab._operation_busy = False

    win._closing = True
    w2 = _SahteIsci(lambda: 42)
    tab._start_mutation(w2, 'deneme', lambda r: None)
    assert w2.silindi == 1
    win._closing = False

    win._close_pending = True
    w3 = _SahteIsci(lambda: 42)
    tab._start_mutation(w3, 'deneme', lambda r: None)
    assert w3.silindi == 1
    win._close_pending = False

    w4 = _SahteIsci(lambda: 42)
    tab._start_mutation(w4, 'işlem sürüyor',
                        lambda r: kayitlar.append(('ok', r)),
                        on_fail=lambda e: kayitlar.append(('fail', e)))
    assert tab._operation_busy is True
    assert tab._operation_worker is w4
    assert tab.progress_transfer.isHidden() is False
    assert tab.btn_stop_transfer.isHidden() is True
    assert tab.lbl_status.text() == 'işlem sürüyor'
    assert w4._args == ()
    assert w4._kwargs == {}
    assert w4._func() == 42

    w4.progress.emit(2, 5)
    assert tab.progress_transfer.maximum() == 5
    assert tab.progress_transfer.value() == 2
    assert tab.progress_transfer.format() == '%v / %m dosya'

    w4.progress.emit(9, 0)
    assert tab.progress_transfer.value() == 2

    tab._operation_worker = None
    w4.progress.emit(4, 5)
    assert tab.progress_transfer.value() == 2
    tab._operation_worker = w4

    w4.finished_ok.emit('S')
    w4.finished.emit()
    assert kayitlar[-1] == ('ok', 'S')
    assert tab._operation_busy is False
    assert tab._operation_worker is None
    assert tab.progress_transfer.isHidden() is True
    assert tab.btn_stop_transfer.isHidden() is True

    kayitlar = []
    w5 = _SahteIsci(lambda: None)
    tab._start_mutation(w5, 'x', lambda r: kayitlar.append(('ok', r)),
                        on_fail=lambda e: kayitlar.append(('fail', e)))
    w5.finished.emit()
    assert kayitlar[-1] == ('fail', 'İşlem tamamlanamadı.')

    w6 = _SahteIsci(lambda: None)
    tab._start_mutation(w6, 'x', lambda r: None)
    w6.failed.emit('hata mesajı')
    w6.finished.emit()
    assert tab.lbl_status.text() == 'Hata: hata mesajı'

    w7 = _SahteIsci(lambda: None)
    tab._start_mutation(w7, 'x', lambda r: None)
    tab._operation_worker = None
    w7.finished.emit()
    tab._operation_busy = False

    kayitlar = []
    w8 = _SahteIsci(lambda: None)
    tab._start_mutation(w8, 'x', lambda r: kayitlar.append(('ok', r)))
    tab._connection_generation += 1
    w8.finished_ok.emit('geç')
    w8.finished.emit()
    assert kayitlar == []
    assert tab._operation_busy is False
    assert tab.lbl_status.text() == 'x'

    w9 = _SahteIsci(lambda: None)
    tab._start_mutation(w9, 'x', lambda r: None)
    tab._connection_generation += 1
    with pytest.raises(CancelledError):
        w9._func()
    w9.finished.emit()
    assert tab._operation_busy is False

    kayitlar = []
    win.patlak_run = True
    w10 = _SahteIsci(lambda: None)
    tab._start_mutation(w10, 'x', lambda r: kayitlar.append(('ok', r)),
                        on_fail=lambda e: kayitlar.append(('fail', e)))
    win.patlak_run = False
    assert kayitlar[-1] == ('fail', 'patladi')
    assert tab._operation_busy is False

    kayitlar = []
    w11 = _SahteIsci(lambda: None)
    tab._start_mutation(w11, 'x', lambda r: kayitlar.append(('ok', r)))
    win._closing = True
    adet = len(kayitlar)
    w11.finished_ok.emit('S')
    w11.finished.emit()
    win._closing = False
    assert len(kayitlar) == adet
    assert tab._operation_busy is False

    tab._operation_worker = None
    tab.btn_stop_transfer.setEnabled(True)
    tab._stop_transfer()

    w12 = _SahteIsci(lambda: None)
    w12._files_transfer = True
    tab._operation_worker = w12
    tab._stop_transfer()
    assert w12.cancel_calls == 1
    assert tab.btn_stop_transfer.isEnabled() is False
    assert tab.lbl_status.text() == (
        'Aktarım durduruluyor; tamamlanmasını bekleyin.')
    tab._operation_worker = None

    w13 = _SahteIsci(lambda: None)
    tab._operation_worker = w13
    tab._stop_transfer()
    assert w13.cancel_calls == 0
    tab._operation_worker = None


def test_push(dosya, monkeypatch, tmp_path):
    tab, core, win = dosya
    kaynak = tmp_path / 'gonder'
    kaynak.mkdir()
    f1 = kaynak / 'bir.txt'
    f1.write_bytes(b'abc')
    f2 = kaynak / 'iki.txt'
    f2.write_bytes(b'de')

    monkeypatch.setattr(QFileDialog, 'getOpenFileNames',
                        lambda *a, **k: ([], ''))
    tab._push()
    assert win.runs == []

    tab._operation_busy = True
    tab._push()
    tab._push_paths([str(f1)])
    assert tab.lbl_status.text() == 'Başka bir dosya işlemi sürüyor.'
    tab._operation_busy = False

    monkeypatch.setattr(QFileDialog, 'getOpenFileNames',
                        lambda *a, **k: ([str(f1), str(f2)], ''))
    tab._push()
    w, desc = win.runs[-1]
    assert desc == 'Dosyalar: 2 dosya yukleniyor -> /sdcard'
    assert w._files_transfer is True
    assert tab.btn_stop_transfer.isHidden() is False
    assert tab._operation_busy is True
    assert w._func() == 2
    assert core.engine.calls[-2:] == [
        ('push', 'tv-1', str(f1), '/sdcard/bir.txt'),
        ('push', 'tv-1', str(f2), '/sdcard/iki.txt')]
    assert tab.progress_transfer.maximum() == 2
    assert tab.progress_transfer.value() == 2

    w.finished_ok.emit(2)
    w.finished.emit()
    assert tab._operation_busy is False
    assert tab.lbl_status.text() == '/sdcard: okunuyor…'

    tab._push()
    w2 = win.runs[-1][0]
    sayac = {'n': 0}

    def target_degistir():
        sayac['n'] += 1
        if sayac['n'] == 2:
            core.target = 'tv-9'

    w2.kanca = target_degistir
    with pytest.raises(RuntimeError):
        w2._func()
    core.target = 'tv-1'
    w2.finished.emit()
    assert tab._operation_busy is False

    loglar = []
    tab._push()
    w3 = win.runs[-1][0]
    w3.log.connect(loglar.append)
    w3.interrupted = True
    core.engine.push_kanca = lambda: setattr(w3, 'iptal_edildi', True)
    core.engine.push_patlak = True
    with pytest.raises(CancelledError):
        w3._func()
    assert loglar == ['Aktarım durduruldu; hedefte kısmi dosya kalmış olabilir.']
    core.engine.push_patlak = False
    core.engine.push_kanca = None
    w3.finished.emit()

    tab._push()
    w4 = win.runs[-1][0]
    core.engine.push_patlak = True
    with pytest.raises(RuntimeError):
        w4._func()
    core.engine.push_patlak = False
    w4.finished.emit()

    tab._push()
    w5 = win.runs[-1][0]
    w5.failed.emit('kullanıcı durdurdu')
    w5.finished.emit()
    assert tab.lbl_status.text() == (
        'Yükleme durduruldu; TV’de tamamlanmış veya kısmi dosyalar kalmış '
        'olabilir.')

    tab._push()
    w6 = win.runs[-1][0]
    w6.failed.emit('ağ koptu')
    w6.finished.emit()
    assert tab.lbl_status.text() == (
        'Yükleme tamamlanamadı: ağ koptu. Bazı dosyalar aktarılmış olabilir.')


def test_push_cakisma_ve_bayat(dosya, monkeypatch, tmp_path):
    tab, _core, win = dosya
    uyari = []
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: uyari.append(a))
    a_klasor = tmp_path / 'a'
    b_klasor = tmp_path / 'b'
    a_klasor.mkdir()
    b_klasor.mkdir()
    (a_klasor / 'ayn.txt').write_bytes(b'1')
    (b_klasor / 'ayn.txt').write_bytes(b'2')

    monkeypatch.setattr(
        QFileDialog, 'getOpenFileNames',
        lambda *a, **k: ([str(a_klasor / 'ayn.txt'),
                          str(b_klasor / 'ayn.txt')], ''))
    tab._push()
    assert win.runs == []
    assert uyari[-1][1] == 'Dosya adları çakışıyor'
    assert 'ayn.txt' in uyari[-1][2]

    monkeypatch.setattr(QFileDialog, 'getOpenFileNames',
                        lambda *a, **k: ([str(tmp_path / 'yok.bin')], ''))
    tab._push()
    assert win.runs == []

    def secim_bayat(*a, **k):
        tab._connection_generation += 1
        return ([str(a_klasor / 'ayn.txt')], '')

    monkeypatch.setattr(QFileDialog, 'getOpenFileNames', secim_bayat)
    tab._push()
    assert win.runs == []
    assert tab.lbl_status.text() == (
        'Bağlantı veya klasör değişti; dosyaları yeniden seçin.')

    gercek_exists = os.path.exists

    def exists_bayat(yol):
        tab._connection_generation += 1
        return gercek_exists(yol)

    monkeypatch.setattr(files_mod.os.path, 'exists', exists_bayat)
    tab._push_paths([str(a_klasor / 'ayn.txt')])
    assert tab.lbl_status.text() == (
        'Bağlantı değişti veya işlem sürüyor; yeniden deneyin.')


def test_pull(dosya, monkeypatch, tmp_path):
    tab, core, win = dosya
    bilgi = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgi.append(a))

    tab._operation_busy = True
    tab._pull()
    assert tab.lbl_status.text() == 'Başka bir dosya işlemi sürüyor.'
    tab._operation_busy = False

    tab._pull()
    assert bilgi[-1][1] == 'Seçim'

    tab._show([_giris(name='Klasör', dir=True, size=0),
               _giris(name='veri.bin', size=3)])
    _secili(tab, 0)
    tab._pull()
    assert bilgi[-1][1] == 'Seçim'

    _secili(tab, 1)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *a, **k: ('', ''))
    tab._pull()
    assert win.runs == []

    hedef = tmp_path / 'veri.bin'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *a, **k: (str(hedef), ''))
    tab._pull()
    w, desc = win.runs[-1]
    assert desc == 'Dosyalar: indiriliyor: veri.bin'
    assert w._files_transfer is True
    assert tab.btn_stop_transfer.isHidden() is False
    assert w._func() == str(hedef)
    assert hedef.read_bytes() == b'xxx'
    cagri = core.engine.calls[-1]
    assert cagri[0] == 'pull'
    assert cagri[1] == 'tv-1'
    assert cagri[2] == '/sdcard/veri.bin'
    assert cagri[3].endswith('.part')
    assert not os.path.exists(cagri[3])
    w.finished_ok.emit(str(hedef))
    w.finished.emit()
    assert tab.lbl_status.text() == 'İndirildi: ' + str(hedef)

    hedef2 = tmp_path / 'veri2.bin'
    core.engine.pull_boyut = 99
    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *a, **k: (str(hedef2), ''))
    tab._pull()
    w2 = win.runs[-1][0]
    with pytest.raises(OSError):
        w2._func()
    assert not hedef2.exists()
    core.engine.pull_boyut = 3
    w2.finished.emit()

    tab._pull()
    w3 = win.runs[-1][0]
    core.engine.pull_sil = True
    with pytest.raises(OSError):
        w3._func()
    core.engine.pull_sil = False
    w3.finished.emit()

    tab._show([_giris(name='veri.bin', size='abc')])
    _secili(tab, 0)
    hedef3 = tmp_path / 'veri3.bin'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *a, **k: (str(hedef3), ''))
    tab._pull()
    w4 = win.runs[-1][0]
    core.engine.pull_boyut = 5
    assert w4._func() == str(hedef3)
    assert hedef3.read_bytes() == b'xxxxx'
    w4.finished.emit()

    tab._pull()
    w5 = win.runs[-1][0]
    loglar = []
    w5.log.connect(loglar.append)
    w5.interrupted = True
    core.engine.pull_kanca = lambda: setattr(w5, 'iptal_edildi', True)
    core.engine.pull_patlak = True
    with pytest.raises(CancelledError):
        w5._func()
    assert loglar == [
        'Aktarım durduruldu; geçici indirme temizlendi, mevcut dosya korundu.']
    core.engine.pull_patlak = False
    core.engine.pull_kanca = None
    w5.finished.emit()

    def kaydet_bayat(*a, **k):
        tab._connection_generation += 1
        return (str(tmp_path / 'x.bin'), '')

    monkeypatch.setattr(QFileDialog, 'getSaveFileName', kaydet_bayat)
    _secili(tab, 0)
    tab._pull()
    assert tab.lbl_status.text() == (
        'Bağlantı değişti veya işlem sürüyor; yeniden deneyin.')

    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *a, **k: (str(tmp_path / 'y.bin'), ''))
    tab._pull()
    w6 = win.runs[-1][0]
    w6.failed.emit('Kullanıcı durdurdu')
    w6.finished.emit()
    assert tab.lbl_status.text() == 'Aktarım durduruldu.'

    tab._pull()
    w7 = win.runs[-1][0]
    w7.failed.emit('ağ koptu')
    w7.finished.emit()
    assert tab.lbl_status.text() == 'Hata: ağ koptu'


def test_mkdir(dosya, monkeypatch):
    tab, core, win = dosya
    uyari = []
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: uyari.append(a))

    tab._operation_busy = True
    tab._mkdir()
    tab._operation_busy = False
    assert win.runs == []
    assert tab.lbl_status.text() == 'Başka bir dosya işlemi sürüyor.'

    monkeypatch.setattr(QInputDialog, 'getText', lambda *a, **k: ('', False))
    tab._mkdir()
    assert win.runs == []

    monkeypatch.setattr(QInputDialog, 'getText', lambda *a, **k: ('   ', True))
    tab._mkdir()
    assert win.runs == []

    for kotu in ('.', '..', 'a/b', 'a\\b', 'kötü\x01ad'):
        monkeypatch.setattr(QInputDialog, 'getText',
                            lambda *a, _ad=kotu, **k: (_ad, True))
        tab._mkdir()
        assert uyari[-1][1] == 'Klasör'
        assert uyari[-1][2] == 'Klasör adı tek bir geçerli ad olmalıdır.'
    assert win.runs == []

    monkeypatch.setattr(QInputDialog, 'getText', lambda *a, **k: ('yeni', True))
    tab._mkdir()
    w, desc = win.runs[-1]
    assert desc == 'Dosyalar: klasör aciliyor: yeni'
    assert w.job_name == 'Klasör olusturma'
    assert tab._operation_busy is True
    assert w._func() == 'yeni'
    assert core.engine.calls[-1] == ('file_mkdir', 'tv-1', '/sdcard/yeni')
    w.finished_ok.emit('yeni')
    w.finished.emit()
    assert tab._operation_busy is False
    assert tab.lbl_status.text() == '/sdcard: okunuyor…'
    assert win.runs[-1][1] == 'Dosyalar Yenile: liste okunuyor'

    def dialog_bayat(*a, **k):
        tab._connection_generation += 1
        return ('yeni2', True)

    monkeypatch.setattr(QInputDialog, 'getText', dialog_bayat)
    tab._mkdir()
    assert tab.lbl_status.text() == (
        'Bağlantı değişti veya işlem sürüyor; yeniden deneyin.')


def test_delete(dosya, monkeypatch):
    tab, core, win = dosya
    bilgi = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgi.append(a))
    sorular = []

    def soru_no(*a, **k):
        sorular.append(a)
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, 'question', soru_no)
    tab._operation_busy = True
    tab._delete()
    assert tab.lbl_status.text() == 'Başka bir dosya işlemi sürüyor.'
    tab._operation_busy = False

    tab._delete()
    assert bilgi[-1][1] == 'Seçim'
    assert bilgi[-1][2] == 'Önce öğe seçin.'

    tab._show([_giris(name='Klasör', dir=True, size=0),
               _giris(name='a.txt')])
    _secili(tab, 0)
    tab._delete()
    assert sorular[-1][1] == 'Onay — Kalıcı Sil'
    assert sorular[-1][2] == (
        'Silinsin mi? (Geri alınamaz!)\n\n• /sdcard/Klasör  [KLASÖR]')
    assert win.runs == []

    _secili(tab, 1)

    def soru_evet(*a, **k):
        sorular.append(a)
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, 'question', soru_evet)
    tab._delete()
    assert sorular[-1][2] == 'Silinsin mi? (Geri alınamaz!)\n\n• /sdcard/a.txt'
    w, desc = win.runs[-1]
    assert desc == 'Dosyalar: siliniyor: /sdcard/a.txt'
    assert w.job_name == 'Dosya silme'
    assert w._func() == '/sdcard/a.txt'
    assert core.engine.calls[-1] == ('file_remove', 'tv-1', '/sdcard/a.txt')
    w.finished_ok.emit('/sdcard/a.txt')
    w.finished.emit()
    assert tab.lbl_status.text() == '/sdcard: okunuyor…'

    def soru_bayat(*a, **k):
        tab._connection_generation += 1
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, 'question', soru_bayat)
    _secili(tab, 1)
    tab._delete()
    assert tab.lbl_status.text() == (
        'Bağlantı değişti veya işlem sürüyor; yeniden deneyin.')


def test_rename(dosya, monkeypatch):
    tab, core, win = dosya
    bilgi, uyari = [], []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgi.append(a))
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: uyari.append(a))
    kayit = {}

    def get_text(*a, **k):
        kayit['args'] = a
        return ('yeni.txt', True)

    monkeypatch.setattr(QInputDialog, 'getText', get_text)

    tab._operation_busy = True
    tab._rename()
    assert tab.lbl_status.text() == 'Başka bir dosya işlemi sürüyor.'
    tab._operation_busy = False

    tab._rename()
    assert bilgi[-1][1] == 'Seçim'
    assert bilgi[-1][2] == 'Önce öğe seçin.'

    tab._show([_giris(name='a.txt')])
    _secili(tab, 0)

    monkeypatch.setattr(QInputDialog, 'getText', lambda *a, **k: ('', False))
    tab._rename()
    assert win.runs == []

    monkeypatch.setattr(QInputDialog, 'getText', lambda *a, **k: ('a.txt', True))
    tab._rename()
    assert win.runs == []

    for kotu in ('.', '..', 'x/y', 'x\\y', 'k\x01'):
        monkeypatch.setattr(QInputDialog, 'getText',
                            lambda *a, _ad=kotu, **k: (_ad, True))
        tab._rename()
        assert uyari[-1][1] == 'Yeniden Adlandır'
        assert uyari[-1][2] == (
            'Yeni ad tek bir geçerli dosya veya klasör adı olmalıdır.')
    assert win.runs == []

    monkeypatch.setattr(QInputDialog, 'getText', get_text)
    tab._rename()
    assert kayit['args'][1] == 'Yeniden Adlandır'
    assert kayit['args'][2] == 'Yeni ad girin:'
    assert kayit['args'][3] == QLineEdit.Normal
    assert kayit['args'][4] == 'a.txt'
    w, desc = win.runs[-1]
    assert desc == 'Dosyalar: yeniden adlandırılıyor: a.txt → yeni.txt'
    assert w.job_name == 'Yeniden adlandirma'
    assert w._func() == 'yeni.txt'
    assert core.engine.calls[-1] == ('rename_file', 'tv-1', '/sdcard/a.txt',
                                     '/sdcard/yeni.txt')
    w.finished_ok.emit('yeni.txt')
    w.finished.emit()
    assert tab.lbl_status.text() == '/sdcard: okunuyor…'

    def dialog_bayat(*a, **k):
        tab._connection_generation += 1
        return ('baska.txt', True)

    monkeypatch.setattr(QInputDialog, 'getText', dialog_bayat)
    _secili(tab, 0)
    tab._rename()
    assert tab.lbl_status.text() == (
        'Bağlantı değişti veya işlem sürüyor; yeniden deneyin.')


def test_install_apk(dosya, monkeypatch):
    tab, core, win = dosya
    bilgi, kritik = [], []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgi.append(a))
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: kritik.append(a))
    sorular = []

    def soru_no(*a, **k):
        sorular.append(a)
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, 'question', soru_no)
    tab._operation_busy = True
    tab._install_remote_apk()
    assert tab.lbl_status.text() == 'Başka bir dosya işlemi sürüyor.'
    tab._operation_busy = False

    tab._install_remote_apk()
    assert bilgi[-1][1] == 'Seçim'
    assert bilgi[-1][2] == 'Kurulacak bir APK dosyası seçin.'

    tab._show([_giris(name='Klasör', dir=True, size=0),
               _giris(name='not.apk.txt'),
               _giris(name='uygulama.apk', size=4096)])
    _secili(tab, 0)
    tab._install_remote_apk()
    assert bilgi[-1][2] == 'Kurulacak bir APK dosyası seçin.'
    _secili(tab, 1)
    tab._install_remote_apk()
    assert bilgi[-1][2] == 'Kurulacak bir APK dosyası seçin.'
    assert win.runs == []

    _secili(tab, 2)
    tab._install_remote_apk()
    assert sorular[-1][1] == 'Onay — Cihazda Kur'
    assert sorular[-1][2] == (
        'Bu APK doğrudan TV üzerinde kurulsun mu?\n\n• /sdcard/uygulama.apk')
    assert win.runs == []

    def soru_evet(*a, **k):
        sorular.append(a)
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, 'question', soru_evet)
    tab._install_remote_apk()
    w, desc = win.runs[-1]
    assert desc == 'Dosyalar: Cihazda kuruluyor: uygulama.apk'
    assert w.job_name == 'Cihazda APK kurma'
    assert w._func() == {'result': 'ok'}
    assert core.engine.calls[-1] == ('install_remote_apk', 'tv-1',
                                     '/sdcard/uygulama.apk', True)
    w.finished_ok.emit({'result': 'ok'})
    w.finished.emit()
    assert tab.lbl_status.text() == "Cihazda kuruldu: {'result': 'ok'}"
    assert bilgi[-1][1] == 'Kurulum Tamamlandı'
    assert 'uygulama.apk' in bilgi[-1][2]

    core.config = SimpleNamespace()
    tab._install_remote_apk()
    w2 = win.runs[-1][0]
    assert w2._func() == {'result': 'ok'}
    assert core.engine.calls[-1][3] is True
    w2.finished.emit()

    tab._install_remote_apk()
    w3 = win.runs[-1][0]
    w3.failed.emit('imza hatası')
    w3.finished.emit()
    assert kritik[-1][1] == 'Kurulum Hatası'
    assert kritik[-1][2] == 'imza hatası'

    def soru_bayat(*a, **k):
        tab._connection_generation += 1
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, 'question', soru_bayat)
    tab._install_remote_apk()
    assert tab.lbl_status.text() == (
        'Bağlantı değişti veya işlem sürüyor; yeniden deneyin.')


def test_baglam_menusu(dosya, monkeypatch):
    tab, core, win = dosya
    menuler = []

    class _Menu(QMenu):
        def exec(self, *a, **k):
            menuler.append(self)

    monkeypatch.setattr(files_mod, 'QMenu', _Menu)
    tiklama = {'oge': None}
    monkeypatch.setattr(tab.grid, 'itemAt', lambda _p: tiklama['oge'])

    core.connected = False
    tab._context_menu(QPoint(5, 5))
    assert menuler == []
    core.connected = True

    tab._context_menu(QPoint(5, 5))
    assert [a.text() for a in menuler[-1].actions()
            if not a.isSeparator()] == ['📁 Yeni Klasör Oluştur',
                                        '📤 Bilgisayardan Dosya Yükle (Push)',
                                        '🔄 Yenile']
    assert tab._selected() is None

    monkeypatch.setattr(QInputDialog, 'getText', lambda *a, **k: ('', False))
    monkeypatch.setattr(QFileDialog, 'getOpenFileNames',
                        lambda *a, **k: ([], ''))
    [a for a in menuler[-1].actions()
     if a.text() == '📁 Yeni Klasör Oluştur'][0].trigger()
    [a for a in menuler[-1].actions()
     if a.text().startswith('📤')][0].trigger()
    assert win.runs == []

    sayi = len(win.runs)
    [a for a in menuler[-1].actions() if a.text() == '🔄 Yenile'][0].trigger()
    assert len(win.runs) == sayi + 2

    tab._show([_giris(name='Klasör', dir=True, size=0),
               _giris(name='uygulama.apk', size=4096),
               _giris(name='rapor.txt')])
    tiklama['oge'] = tab.grid.item(0, COL_NAME)
    tab._context_menu(QPoint(5, 5))
    assert tab.grid.currentRow() == 0
    assert [a.text() for a in menuler[-1].actions()
            if not a.isSeparator()] == ['📂 Klasör Klasörünü Aç',
                                        '📋 Tam Yolu Kopyala',
                                        '✏️ Yeniden Adlandır',
                                        '🗑 Kalıcı Olarak Sil']

    [a for a in menuler[-1].actions()
     if a.text() == '📋 Tam Yolu Kopyala'][0].trigger()
    assert QApplication.clipboard().text() == '/sdcard/Klasör'

    [a for a in menuler[-1].actions()
     if a.text().endswith('Klasörünü Aç')][0].trigger()
    assert tab._cwd == '/sdcard/Klasör'

    tab._cwd = '/sdcard'
    tab._show([_giris(name='Klasör', dir=True, size=0),
               _giris(name='uygulama.apk', size=4096),
               _giris(name='rapor.txt')])
    tiklama['oge'] = tab.grid.item(1, COL_NAME)
    tab._context_menu(QPoint(5, 5))
    assert tab.grid.currentRow() == 1
    metinler = [a.text() for a in menuler[-1].actions() if not a.isSeparator()]
    assert metinler == ['📥 Bilgisayara İndir (Pull)', "🚀 TV'de Kur (APK)",
                        '📋 Tam Yolu Kopyala', '✏️ Yeniden Adlandır',
                        '🗑 Kalıcı Olarak Sil']
    assert all(a.isEnabled() for a in menuler[-1].actions())

    tiklama['oge'] = tab.grid.item(2, COL_NAME)
    tab._context_menu(QPoint(5, 5))
    assert tab.grid.currentRow() == 2
    metinler = [a.text() for a in menuler[-1].actions() if not a.isSeparator()]
    assert "🚀 TV'de Kur (APK)" not in metinler

    sil = [a for a in menuler[-1].actions()
           if a.text() == '🗑 Kalıcı Olarak Sil'][0]
    yad = [a for a in menuler[-1].actions()
           if a.text() == '✏️ Yeniden Adlandır'][0]
    tab._cwd = '/sdcard/Download'
    sil.trigger()
    assert tab.lbl_status.text() == (
        'Bağlantı, klasör veya seçim değişti; menüyü yeniden açın.')
    tab._cwd = '/sdcard'

    tab._operation_busy = True
    yad.trigger()
    assert tab.lbl_status.text() == (
        'Bağlantı, klasör veya seçim değişti; menüyü yeniden açın.')
    tab._context_menu(QPoint(5, 5))
    kopya = [a for a in menuler[-1].actions()
             if a.text() == '📋 Tam Yolu Kopyala'][0]
    assert kopya.isEnabled() is True
    sil2 = [a for a in menuler[-1].actions()
            if a.text() == '🗑 Kalıcı Olarak Sil'][0]
    assert sil2.isEnabled() is False
    tab._operation_busy = False

    monkeypatch.setattr(QInputDialog, 'getText',
                        lambda *a, **k: ('yeni.txt', True))
    tab._context_menu(QPoint(5, 5))
    [a for a in menuler[-1].actions()
     if a.text() == '✏️ Yeniden Adlandır'][0].trigger()
    w = win.runs[-1][0]
    assert w._func() == 'yeni.txt'
    w.finished.emit()
    assert tab._operation_busy is False


def test_surukle_birak(dosya, monkeypatch, tmp_path):
    tab, core, win = dosya
    dosya_yolu = tmp_path / 'kopya.txt'
    dosya_yolu.write_bytes(b'veri')
    yerel = QUrl.fromLocalFile(str(dosya_yolu))
    uzak = QUrl('http://example.com/x.txt')
    grid = tab.grid
    gozcu = QObject()

    veri_yerel = QMimeData()
    veri_yerel.setUrls([yerel])
    veri_uzak = QMimeData()
    veri_uzak.setUrls([uzak])
    veri_bos = QMimeData()

    giris = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, veri_yerel,
                            Qt.LeftButton, Qt.NoModifier)
    assert tab.eventFilter(grid, giris) is True
    assert giris.isAccepted() is True

    giris2 = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, veri_bos,
                             Qt.LeftButton, Qt.NoModifier)
    assert tab.eventFilter(grid.viewport(), giris2) is False

    giris3 = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, veri_uzak,
                             Qt.LeftButton, Qt.NoModifier)
    assert tab.eventFilter(gozcu, giris3) is False

    birak = QDropEvent(QPointF(5, 5), Qt.CopyAction, veri_yerel,
                       Qt.LeftButton, Qt.NoModifier)
    assert tab.eventFilter(grid, birak) is True
    assert birak.isAccepted() is True
    w = win.runs[-1][0]
    assert w._files_transfer is True
    assert w._func() == 1
    assert core.engine.calls[-1] == ('push', 'tv-1', str(dosya_yolu),
                                     '/sdcard/kopya.txt')
    w.finished.emit()

    birak2 = QDropEvent(QPointF(5, 5), Qt.CopyAction, veri_uzak,
                        Qt.LeftButton, Qt.NoModifier)
    assert tab.eventFilter(grid, birak2) is False

    giris4 = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, veri_yerel,
                             Qt.LeftButton, Qt.NoModifier)
    tab.dragEnterEvent(giris4)
    assert giris4.isAccepted() is True

    giris5 = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, veri_bos,
                             Qt.LeftButton, Qt.NoModifier)
    tab.dragEnterEvent(giris5)
    assert giris5.isAccepted() is False

    birak3 = QDropEvent(QPointF(5, 5), Qt.CopyAction, veri_uzak,
                        Qt.LeftButton, Qt.NoModifier)
    tab.dropEvent(birak3)
    assert birak3.isAccepted() is False

    birak4 = QDropEvent(QPointF(5, 5), Qt.CopyAction, veri_yerel,
                        Qt.LeftButton, Qt.NoModifier)
    tab.dropEvent(birak4)
    assert birak4.isAccepted() is True
    w2 = win.runs[-1][0]
    assert w2._files_transfer is True
    w2.finished.emit()

    bos_birak = QDropEvent(QPointF(5, 5), Qt.CopyAction, veri_bos,
                           Qt.LeftButton, Qt.NoModifier)
    tab.dropEvent(bos_birak)
    assert bos_birak.isAccepted() is False
