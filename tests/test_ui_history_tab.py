# -*- coding: utf-8 -*-
"""history_tab: kayit listesi, filtre, geri alma zinciri ve durum kayitlari."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QMessageBox,
    QTableWidgetItem,
)

from mibox_app import history, snapshot
from mibox_app.ui import history_tab as history_tab_mod
from mibox_app.ui.history_tab import (
    COL_OK,
    COL_PKG,
    COL_TS,
    HistoryTab,
)


def _kayit(**kw):
    rec = {'ts': '2026-01-02 03:04', 'target': 'tv-1', 'user_id': 0,
           'action': 'disable', 'package': 'com.ornek', 'method': '',
           'ok': True}
    rec.update(kw)
    return rec


class _Yapilandirma:
    def __init__(self):
        self.user_id = 0
        self.protected = ['com.korunan']
        self.adlar = {}
        self.patlak = False

    def friendly_name(self, paket):
        if self.patlak:
            raise RuntimeError('ad yok')
        return self.adlar.get(paket, paket)


class _Motor:
    def __init__(self):
        self.calls = []

    def connect(self, target):
        self.calls.append(('connect', target))

    def invalidate_pkg_cache(self, target):
        self.calls.append(('invalidate', target))


class _Cekirdek:
    def __init__(self):
        self.connected = True
        self.target = 'tv-1'
        self.engine = _Motor()
        self.config = _Yapilandirma()


class _CekirdekSinyalli(_Cekirdek, QObject):
    connection_changed = Signal(bool, object)

    def __init__(self):
        QObject.__init__(self)
        _Cekirdek.__init__(self)


class _Uygulamalar:
    def __init__(self):
        self.yenileme = 0
        self.patlak = False

    def refresh(self):
        self.yenileme += 1
        if self.patlak:
            raise RuntimeError('uygulama sekmesi yok')


class _Pencere:
    def __init__(self):
        self.runs = []
        self._connection_busy = False
        self._closing = False
        self._close_pending = False
        self.tab_apps = _Uygulamalar()
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

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.args = args
        self.kwargs = kwargs
        self.job_name = ''
        self.iptal = False

    def cancel(self):
        self.iptal = True

    def check_cancel(self):
        pass


@pytest.fixture
def hist(qtbot, monkeypatch):
    kayitlar = []
    monkeypatch.setattr(history, 'read_all', lambda limit=500: list(kayitlar))
    monkeypatch.setattr(snapshot, 'list_snapshots', lambda: [])
    for isim in ('Worker', 'SmartRemoveWorker', 'PackageActionWorker',
                 'SnapshotWorker'):
        monkeypatch.setattr(history_tab_mod, isim, _SahteIsci)
    core = _Cekirdek()
    win = _Pencere()
    tab = HistoryTab(core, win)
    qtbot.addWidget(tab)
    return tab, core, win, kayitlar


def _secili(tab, satirlar):
    mod = QAbstractItemView.MultiSelection
    if tab.grid.selectionMode() != mod:
        tab.grid.setSelectionMode(mod)
    tab.grid.clearSelection()
    for satir in satirlar:
        tab.grid.selectRow(satir)


def test_kurulum_ve_tema(hist):
    tab, _core, _win, _kayitlar = hist
    assert tab.cmb_snap.count() == 1
    assert tab.cmb_snap.itemData(0) == ''
    assert tab.btn_undo.isEnabled() is False
    assert tab.btn_search_clear.isEnabled() is False
    assert tab.search_history.isClearButtonEnabled() is False
    assert tab.btn_snap_take.property('accent') is True
    assert tab.btn_snap_apply.property('danger') is True
    assert tab.btn_clear.property('danger') is True
    assert tab.grid.columnCount() == 7
    basliklar = [tab.grid.horizontalHeaderItem(i).text() for i in range(7)]
    assert basliklar == ['Zaman', 'Hedef', 'Kullanıcı', 'İşlem', 'Paket',
                         'Yöntem', 'Sonuç']
    assert tab.grid.isSortingEnabled() is False
    assert 'İşlem geçmişinde başarılı' in tab._hint.text()
    assert 'Taşıma: Bu cihazda durum kaydı alıp' in tab.lbl_clone.text()
    assert tab.lbl_record_detail.text() == (
        'Bir kayıt seçerek sonucunu ve geri alma bilgisini görün.')
    assert tab.lbl_summary.text() == '0 kayıt.'
    assert tab.btn_snap_export.isHidden() is True
    assert tab.btn_export.isHidden() is True
    assert {a.text() for _b, a in tab._snap_menu_actions} == {
        'Dışa aktar', 'İçe Aktar', 'Durum kaydını uygula', 'Sil'}

    tab.apply_theme()
    tab._hint = None
    tab.apply_theme()


def test_kurulum_sinyalli_kok(qtbot, monkeypatch):
    monkeypatch.setattr(history, 'read_all', lambda limit=500: [])
    monkeypatch.setattr(snapshot, 'list_snapshots', lambda: [])
    core = _CekirdekSinyalli()
    win = _Pencere()
    tab = HistoryTab(core, win)
    qtbot.addWidget(tab)
    assert tab._connection_generation == 0
    core.connection_changed.emit(False, None)
    assert tab._connection_generation == 1

    sahte = SimpleNamespace(_connection_generation=5)
    HistoryTab._on_connection_changed(sahte, True)
    assert sahte._connection_generation == 6


def test_ters_islem_eslemesi():
    ters = HistoryTab._inverse_for_record
    assert ters(history, {'action': 5}) is None
    assert ters(history, {'action': 'disable'}) == 'enable'
    assert ters(history, {'action': 'clear'}) is None
    assert ters(history, {}) is None
    assert ters(history, {'action': 'smart', 'method': 'disable'}) == 'enable'
    assert ters(history, {'action': 'smart', 'method': 'uninstall'}) == 'restore'
    assert ters(history, {'action': 'smart', 'method': 'stop'}) is None
    assert ters(history, {'action': 'smart', 'method': 7}) is None
    assert ters(history, {'action': 'smart'}) is None


def test_kayit_durumu_ve_aciklama(hist):
    tab, core, win, _kayitlar = hist
    durum = HistoryTab._undo_record_status
    assert durum(history, 'kayit degil') == (None, 'kayıt tanınmıyor')
    assert durum(history, {'ok': False})[1] == 'işlem başarısız olmuş'
    assert durum(history, _kayit(user_id='0'))[1] == (
        'kullanıcı kimliği geçersiz')
    assert durum(history, _kayit(user_id=99999))[1] == (
        'kullanıcı kimliği geçersiz')
    assert durum(history, _kayit(action='clear'))[1] == (
        'bu işlem için geri alma eşlemesi yok')
    assert durum(history, _kayit(package='  '))[1] == 'paket bilgisi geçersiz'
    assert durum(history, _kayit(package=7))[1] == 'paket bilgisi geçersiz'
    assert durum(history, _kayit(target=None))[1] == 'kayıtlı cihaz bilgisi yok'
    assert durum(history, _kayit(target=''))[1] == 'kayıtlı cihaz bilgisi yok'
    assert durum(history, _kayit()) == ('enable', '')

    acik = tab._record_explanation
    assert acik(history, _kayit(ok=False)).startswith(
        'Başarısız · Geri alınamaz: işlem başarısız olmuş.')
    assert acik(history, _kayit()) == 'Başarılı · Geri alınabilir: Aktif.'
    win._connection_busy = True
    assert acik(history, _kayit()).endswith(' Bağlantı işlemi sürüyor.')
    win._connection_busy = False
    core.connected = False
    assert acik(history, _kayit()).endswith(
        ' Geri almak için tv-1 cihazına bağlanın.')
    core.connected = True
    core.target = 'tv-2'
    assert acik(history, _kayit()).endswith(
        ' Şu an başka cihaz bağlı; tv-1 hedefine bağlanın.')


def test_yenileme_tablosu(hist):
    tab, _core, _win, kayitlar = hist
    kayitlar.extend([
        _kayit(ts='t1', user_id=3, action='disable',
               package='com.a', method='', ok=True),
        _kayit(ts='t2', user_id='yok', action='bilinmeyen',
               package='com.b', method='pm', ok=False),
        _kayit(ts='t3', target=None, user_id=0, action=7,
               package='com.c', method=None, ok=True),
    ])
    tab.refresh()
    assert tab.grid.rowCount() == 3
    assert tab.grid.item(0, COL_TS).text() == 't1'
    assert tab.grid.item(0, 2).text() == 'user 3'
    assert tab.grid.item(0, 3).text() == 'Devre dışı'
    assert tab.grid.item(0, 5).text() == '-'
    assert tab.grid.item(0, COL_OK).text() == 'Başarılı · Geri alınabilir'
    assert 'Geri alınabilir: Aktif' in tab.grid.item(0, COL_OK).toolTip()
    assert tab.grid.item(1, 2).text() == '?'
    assert tab.grid.item(1, 3).text() == 'bilinmeyen'
    assert tab.grid.item(1, COL_OK).text() == 'Başarısız · Geri alınamaz'
    assert tab.grid.item(2, 1).text() == ''
    assert tab.grid.item(2, 3).text() == '7'
    assert tab.grid.item(2, 5).text() == '-'
    hucre = tab.grid.item(0, COL_TS)
    assert not (hucre.flags() & Qt.ItemIsEditable)
    assert tab.grid.item(0, COL_PKG).data(Qt.UserRole) == 0


def test_arama_filtresi(hist):
    tab, _core, _win, kayitlar = hist
    kayitlar.extend([
        _kayit(package='com.alpha', action='disable'),
        _kayit(package='com.beta', action='uninstall'),
    ])
    tab.refresh()
    assert tab.lbl_summary.text() == '2 kayıt.'
    tab.search_history.setText('ALPHA')
    assert tab.grid.isRowHidden(0) is False
    assert tab.grid.isRowHidden(1) is True
    assert tab.lbl_summary.text() == '1 / 2 kayıt gösteriliyor.'
    assert tab.btn_search_clear.isEnabled() is True
    tab.search_history.setText('com.alpha devre')
    assert tab.grid.isRowHidden(0) is False
    tab.search_history.setText('com.alpha kaldırma')
    assert tab.grid.isRowHidden(0) is True
    tab.search_history.setText('yok-boyle')
    assert tab.grid.isRowHidden(0) is True
    assert tab.grid.isRowHidden(1) is True
    tab.search_history.setText('')
    assert tab.grid.isRowHidden(0) is False
    assert tab.btn_search_clear.isEnabled() is False
    tab.search_history.setText('kaldırma')
    assert tab.grid.isRowHidden(1) is False
    tab.btn_search_clear.click()
    assert tab.search_history.text() == ''
    assert tab.grid.isRowHidden(1) is False


def test_secim_durumu(hist):
    tab, core, win, kayitlar = hist
    kayitlar.extend([_kayit(package='com.a'), _kayit(package='com.b'),
                     _kayit(package='com.c', ok=False)])
    tab.refresh()
    assert tab.btn_undo.isEnabled() is False
    assert tab.lbl_record_detail.text().startswith('Bir kayıt seçerek')

    _secili(tab, [0])
    assert 'Geri alınabilir: Aktif.' in tab.lbl_record_detail.text()
    assert tab.btn_undo.isEnabled() is True

    _secili(tab, [0, 1])
    detay = tab.lbl_record_detail.text()
    assert detay.startswith('2 kayıt seçili · başarılı: 2 · başarısız: 0 · '
                            'geri alınabilir: 2.')
    assert detay.count('• ') == 2

    _secili(tab, [0, 1, 2])
    detay = tab.lbl_record_detail.text()
    assert '3 kayıt seçili' in detay
    assert '• … 1 kayıt daha' in detay
    assert tab.btn_undo.isEnabled() is False

    win._connection_busy = True
    _secili(tab, [0])
    assert tab.btn_undo.isEnabled() is False
    win._connection_busy = False
    core.connected = False
    _secili(tab, [0])
    assert tab.btn_undo.isEnabled() is False
    core.connected = True
    core.target = None
    _secili(tab, [0])
    assert tab.btn_undo.isEnabled() is False
    core.target = 'tv-2'
    _secili(tab, [0])
    assert tab.btn_undo.isEnabled() is False
    core.target = 'tv-1'

    tab._undo_worker = object()
    _secili(tab, [0])
    assert tab.btn_undo.isEnabled() is False
    tab._undo_worker = None
    _secili(tab, [0])
    assert tab.btn_undo.isEnabled() is True

    tab.grid.item(0, COL_PKG).setData(Qt.UserRole, 'kotu')
    _secili(tab, [0])
    assert tab.lbl_record_detail.text() == (
        'Seçili kayıt tanınmıyor; geçmişi yenileyin.')
    assert tab.btn_undo.isEnabled() is False
    tab.grid.item(0, COL_PKG).setData(Qt.UserRole, 0)

    tab.grid.insertRow(tab.grid.rowCount())
    tab.grid.setItem(tab.grid.rowCount() - 1, COL_TS, QTableWidgetItem('x'))
    _secili(tab, [tab.grid.rowCount() - 1])
    assert tab.lbl_record_detail.text() == (
        'Seçili kayıt tanınmıyor; geçmişi yenileyin.')


def test_geri_alma_gate_ve_onay_ozeti(hist, monkeypatch):
    tab, core, win, kayitlar = hist
    bilgi = []
    uyari = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgi.append(a))
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: uyari.append(a))
    monkeypatch.setattr(QMessageBox, 'question',
                        lambda *a, **k: QMessageBox.No)

    tab._undo_queue = ['x']
    tab._undo_selected()
    assert tab.lbl_summary.text().startswith('Devam eden durum kaydı')
    tab._undo_queue = []

    tab._undo_selected()
    assert bilgi[-1][1] == 'Seçim'
    assert bilgi[-1][2] == 'Önce satır seçin.'

    kayitlar.extend([
        _kayit(package='com.ok', action='disable'),
        _kayit(package='com.fail', action='disable', ok=False),
        _kayit(package='com.none', action='clear'),
    ])
    tab.refresh()
    _secili(tab, [1, 2])
    tab._undo_selected()
    assert bilgi[-1][1] == 'Geri Al'
    metin = bilgi[-1][2]
    assert metin.startswith('Seçili satırların hiçbiri geri alınamaz.')
    assert 'X com.fail: işlem zaten başarısızdı' in metin
    assert 'X com.none: bu işlem için geri alma eşlemesi yok' in metin

    _secili(tab, [0])
    core.connected = False
    tab._undo_selected()
    assert uyari[-1][2] == 'Geri alma için cihaza bağlı olmanız gerekir.'
    core.connected = True
    win._connection_busy = True
    tab._undo_selected()
    assert uyari[-1][2] == ('Bağlantı işlemi sürüyor; tamamlanınca '
                            'yeniden deneyin.')
    win._connection_busy = False

    kayitlar.append(_kayit(package='com.yabanci', action='disable',
                           target=None))
    kayitlar.append(_kayit(package='com.diger', action='disable',
                           target='tv-2'))
    tab.refresh()
    _secili(tab, [3, 4])
    tab._undo_selected()
    assert 'Geri alma durduruldu.' in uyari[-1][2]
    assert 'com.diger: tv-2' in uyari[-1][2]

    kayitlar.append(_kayit(package='com.zengin', action='restore'))
    kayitlar.append(_kayit(package='com.skip', action='disable', ok=False))
    for i in range(9):
        kayitlar.append(_kayit(package='com.enable{}'.format(i),
                               action='enable'))
    core.config.adlar['com.enable0'] = 'Galeri'
    sorular = []

    def sor_fn(*a, **k):
        sorular.append(a)
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, 'question', sor_fn)
    tab.refresh()
    _secili(tab, list(range(5, 16)))
    tab._undo_selected()
    assert sorular[-1][1] == 'Onay — Geri Al'
    metin = sorular[-1][2]
    assert metin.startswith('Geri alma hedefi: tv-1')
    assert 'smart (user 0, 1 paket):' in metin
    assert '  • com.zengin' in metin
    assert 'disable (user 0, 9 paket):' in metin
    assert '  • Galeri (com.enable0)' in metin
    assert '  … ve 1 tane daha' in metin
    assert 'Atlanacak:' in metin
    assert 'X com.skip: işlem zaten başarısızdı' in metin
    assert metin.endswith('Uygulansın mı?')
    assert tab._undo_queue == []

    core.config.patlak = True
    tab._undo_selected()
    assert '  • com.zengin' in sorular[-1][2]
    assert tab._undo_queue == []

    def sor_degistir(*a, **k):
        tab._connection_generation += 1
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, 'question', sor_degistir)
    tab._undo_selected()
    assert uyari[-1][2] == ('Hedef veya bağlantı değişti; geri alma '
                            'başlatılmadı.')
    assert tab._undo_queue == []


def test_geri_alma_zinciri(hist, monkeypatch):
    tab, core, win, kayitlar = hist
    uyari = []
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: uyari.append(a))
    monkeypatch.setattr(QMessageBox, 'question',
                        lambda *a, **k: QMessageBox.Yes)

    kayitlar.extend([
        _kayit(package='com.stok', action='restore'),
        _kayit(package='com.uy', action='disable', user_id=5),
        _kayit(package='com.r', action='unrestrict'),
        _kayit(package='com.ok', action='disable'),
        _kayit(package='com.stok5', action='restore', user_id=5),
    ])
    tab.refresh()
    _secili(tab, [0, 1, 2, 3, 4])
    tab._undo_selected()
    assert tab._undo_queue == [
        ('enable', 'com.uy', 5), ('restrict', 'com.r', 0),
        ('enable', 'com.ok', 0), ('smart', 'com.stok5', 5)]

    w1 = win.runs[-1][0]
    assert w1.args == (core.engine, 'tv-1', ['com.stok'],
                       ['com.korunan'])
    assert w1.kwargs == {'user_id': 0}
    w1.finished_ok.emit({'ok': 1})
    w1.finished.emit()

    w2 = win.runs[-1][0]
    assert w2.args[1:] == ('enable', 'com.uy', 5, 'tv-1')
    assert w2.job_name == 'Geçmiş geri alma'
    w2.finished_ok.emit({'fail': 1})
    w2.finished.emit()
    assert ('com.uy', 'geri alma başarısız') in tab._undo_fail

    w3 = win.runs[-1][0]
    assert w3.args[1:] == ('restrict', 'com.r', 0, 'tv-1')
    assert w3.job_name == 'Geçmiş geri alma'
    w3.finished_ok.emit({'ok': 1})
    w3.finished.emit()

    w4 = win.runs[-1][0]
    assert w4.args == (core.engine, 'tv-1', ['com.ok'], 'enable',
                       ['com.korunan'])
    w4.finished_ok.emit({'ok': 1})
    w4.finished.emit()

    w5 = win.runs[-1][0]
    assert w5.args[1:] == ('smart', 'com.stok5', 5, 'tv-1')
    assert w5.job_name == 'Geçmiş geri alma'
    w5.finished_ok.emit({'ok': 1})
    w5.finished.emit()
    assert tab._undo_worker is None
    assert tab._undo_queue == []
    assert uyari[-1][1] == 'Geri Al'
    assert 'Bazı işlemler geri alınamadı:' in uyari[-1][2]
    assert 'X com.uy: geri alma başarısız' in uyari[-1][2]
    assert win.tab_apps.yenileme == 1


def test_geri_alma_zinciri_hatalar(hist, monkeypatch):
    tab, _core, win, kayitlar = hist
    uyari = []
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: uyari.append(a))

    tab._undo_queue = [('disable', 'com.bekleyen', 0)]
    tab._undo_fail = []
    tab._undo_target = 'tv-1'
    tab._undo_connection_generation = tab._connection_generation + 1
    win.tab_apps.patlak = True
    tab._run_next_undo()
    assert tab._undo_queue == []
    assert ('com.bekleyen',
            'hedef veya bağlantı değişti; işlem uygulanmadı') in \
        tab._undo_fail
    assert 'X com.bekleyen' in uyari[-1][2]
    assert win.tab_apps.yenileme == 1
    win.tab_apps.patlak = False

    kayitlar.extend([_kayit(package='com.a', action='disable'),
                     _kayit(package='com.b', action='disable')])
    tab.refresh()
    tab._undo_fail = []
    tab._undo_target = 'tv-1'
    tab._undo_connection_generation = tab._connection_generation
    tab._undo_queue = [('disable', 'com.a', 0), ('disable', 'com.b', 0)]
    tab._run_next_undo()
    w = win.runs[-1][0]
    w.failed.emit('komut hatası')
    w.finished.emit()
    assert ('com.a', 'komut hatası') in tab._undo_fail
    assert ('com.b',
            'önceki işlem tamamlanamadı; uygulanmadı') in tab._undo_fail
    assert 'X com.a: komut hatası' in uyari[-1][2]

    tab._undo_queue = [('disable', 'com.c', 0)]
    tab._undo_fail = []
    tab._undo_target = 'tv-1'
    tab._undo_connection_generation = tab._connection_generation
    tab._run_next_undo()
    w = win.runs[-1][0]
    tab._undo_worker = None
    w.finished.emit()
    assert tab._undo_queue == []

    tab._undo_queue = [('disable', 'com.e', 0)]
    tab._undo_fail = []
    tab._undo_target = 'tv-1'
    tab._undo_connection_generation = tab._connection_generation
    tab._run_next_undo()
    w2 = win.runs[-1][0]
    win._closing = True
    w2.finished.emit()
    assert tab._undo_queue == []
    win._closing = False

    win.patlak_run = True
    tab._undo_queue = [('disable', 'com.d', 0)]
    tab._undo_fail = []
    tab._undo_target = 'tv-1'
    tab._undo_connection_generation = tab._connection_generation
    tab._run_next_undo()
    assert ('com.d', 'patladi') in tab._undo_fail
    assert tab._undo_queue == []
    win.patlak_run = False


def test_undo_done_dallari(hist):
    tab, _core, _win, _kayitlar = hist
    tab._undo_fail = []
    tab._undo_done({'ok': 1}, 'disable', 'com.a', 'tv-1', 0)
    assert tab._undo_fail == []
    tab._undo_done('kotu', 'disable', 'com.b', 'tv-1', 0)
    assert tab._undo_fail == [('com.b', 'geri alma başarısız')]
    tab._undo_done({'fail': 1}, 'disable', 'com.c')
    assert tab._undo_fail[-1] == ('com.c', 'geri alma başarısız')
    tab._undo_done({'ok': 1}, 'disable', 'com.d', 'tv-1', 99)
    assert tab._undo_fail[-1] == ('com.c', 'geri alma başarısız')


def _motor(**metotlar):
    motor = SimpleNamespace(calls=[], invalidate_hata=False)
    motor.connect = lambda target: motor.calls.append(('connect', target))

    def invalidate(target):
        motor.calls.append(('invalidate', target))
        if motor.invalidate_hata:
            raise RuntimeError('onbellek yok')

    motor.invalidate_pkg_cache = invalidate
    for ad, islev in metotlar.items():
        setattr(motor, ad, islev)
    return motor


def test_run_user_undo_api(hist, monkeypatch):
    tab, core, _win, _kayitlar = hist
    eklenen = []
    monkeypatch.setattr(history, 'append',
                        lambda *a, **k: eklenen.append((a, k)))

    def kos(motor, action='enable', pkg='com.x', user_id=0):
        core.engine = motor
        return tab._run_user_undo(action, pkg, user_id, 'tv-1')

    def kwli(target, pkg, user_id=None):
        return ('kw', target, pkg, user_id)

    def kwargsli(target, pkg, **kwargs):
        return kwargs

    motor = _motor(enable_user_id=kwli)
    motor.invalidate_hata = True
    assert kos(motor) == {'ok': 1, 'fail': 0}
    assert motor.calls[0] == ('connect', 'tv-1')
    assert ('invalidate', 'tv-1') in motor.calls
    assert eklenen[-1][0] == ('tv-1', 'enable', 'com.x')
    assert eklenen[-1][1] == {'ok': True, 'user_id': 0}

    assert kos(_motor(enable_for_user_id=kwargsli)) == {'ok': 1, 'fail': 0}
    assert kos(_motor(enable_user_id=dict.update,
                      enable_for_user_id=kwargsli)) == {'ok': 1, 'fail': 0}
    assert kos(_motor(enable_user_id=5,
                      enable_for_user_id=kwargsli)) == {'ok': 1, 'fail': 0}

    cagrilar = []

    def son(target, pkg):
        cagrilar.append((target, pkg))

    def konumlu(target, pkg, uid):
        cagrilar.append((target, pkg, uid))

    motor = _motor(enable=son)
    motor.invalidate_hata = True
    assert kos(motor) == {'ok': 1, 'fail': 0}
    assert cagrilar == [('tv-1', 'com.x')]

    cagrilar.clear()
    motor = _motor(enable_user_id=konumlu)
    motor.invalidate_hata = True
    assert kos(motor, user_id=7) == {'ok': 1, 'fail': 0}
    assert cagrilar == [('tv-1', 'com.x', 7)]

    sonuc = kos(_motor(enable=son), user_id=7)
    assert sonuc['ok'] == 0
    assert sonuc['fail'] == 1
    assert 'desteklenmiyor' in sonuc['details'][0][2]
    assert eklenen[-1][1] == {'ok': False, 'user_id': 7}

    sonuc = kos(_motor(), action='yokboyle')
    assert sonuc['fail'] == 1
    assert 'Bilinmeyen geri alma işlemi: yokboyle' in sonuc['details'][0][2]

    sonuc = kos(_motor(enable=son), pkg='com.korunan')
    assert sonuc['fail'] == 1
    assert 'Paket koruma listesinde.' in sonuc['details'][0][2]


def test_csv_aktar(hist, monkeypatch, tmp_path):
    tab, _core, _win, kayitlar = hist
    bilgi = []
    hatalar = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgi.append(a))
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: hatalar.append(a))

    tab._export_csv()
    assert bilgi[-1][1] == 'Aktar'
    assert bilgi[-1][2] == 'Kayıt yok.'

    kayitlar.extend([
        _kayit(package='=SUM(A1)', action='disable', ok=True),
        _kayit(user_id=4, action='uninstall', package='com.b',
               method='pm', ok=False),
    ])
    tab.refresh()
    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *a, **k: ('', ''))
    tab._export_csv()
    assert len(bilgi) == 1

    hedef = tmp_path / 'gecmis.csv'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *a, **k: (str(hedef), ''))
    tab._export_csv()
    assert str(hedef) in bilgi[-1][2]
    icerik = hedef.read_text(encoding='utf-8-sig')
    assert icerik.startswith('Zaman,Hedef,Kullanıcı,İşlem,Paket,'
                             'Yöntem,Sonuç')
    assert "'=SUM(A1)" in icerik
    assert 'fail' in icerik
    assert 'uninstall' in icerik

    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *a, **k: (str(tmp_path / 'alt' / 'x.csv'),
                                         ''))
    tab._export_csv()
    assert hatalar[-1][1] == 'Hata'


def test_gecmis_temizle(hist, monkeypatch):
    tab, _core, _win, kayitlar = hist
    uyari = []
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: uyari.append(a))
    monkeypatch.setattr(QMessageBox, 'question',
                        lambda *a, **k: QMessageBox.No)

    temizlendi = []

    def clear_fake():
        if temizlendi:
            raise OSError('dosya kilitli')
        temizlendi.append(1)
        kayitlar.clear()

    monkeypatch.setattr(history, 'clear', clear_fake)
    kayitlar.append(_kayit())
    tab.refresh()
    assert tab.lbl_summary.text() == '1 kayıt.'

    tab._clear()
    assert temizlendi == []

    monkeypatch.setattr(QMessageBox, 'question',
                        lambda *a, **k: QMessageBox.Yes)
    tab._clear()
    assert len(temizlendi) == 1
    assert tab.lbl_summary.text() == '0 kayıt.'
    tab._clear()
    assert uyari[-1][1] == 'Silinemedi'
    assert 'İşlem geçmişi dosyası silinemedi' in uyari[-1][2]


def test_snapshot_kontrolleri(hist, monkeypatch):
    tab, core, win, _kayitlar = hist
    assert tab._snapshot_busy() is False
    tab._undo_worker = object()
    assert tab._snapshot_busy() is True
    tab._undo_worker = None
    tab._undo_queue = [('x',)]
    assert tab._snapshot_busy() is True
    tab._undo_queue = []

    assert tab._snapshot_context() == (core.engine, 'tv-1', 0)
    win._connection_busy = True
    assert tab._snapshot_context() is None
    assert tab.lbl_summary.text().startswith('Bağlantıyı ve devam eden')
    win._connection_busy = False
    core.connected = False
    assert tab._snapshot_context() is None
    core.connected = True
    core.target = ''
    assert tab._snapshot_context() is None
    core.target = 'tv-1'
    win._closing = True
    assert tab._snapshot_context() is None
    win._closing = False
    win._close_pending = True
    assert tab._snapshot_context() is None
    win._close_pending = False
    tab._snap_worker = object()
    assert tab._snapshot_context() is None
    tab._snap_worker = None

    assert tab._snapshot_context_current((core.engine, 'tv-1', 0)) is True
    assert tab._snapshot_context_current((object(), 'tv-1', 0)) is False

    monkeypatch.setattr(snapshot, 'list_snapshots', lambda: ['Kayit A'])
    tab.refresh_snaps()
    assert tab.cmb_snap.count() == 1
    assert tab.cmb_snap.currentData() == 'Kayit A'
    assert tab.btn_snap_diff.isEnabled() is True
    assert tab.btn_snap_apply.isEnabled() is True
    assert tab.btn_snap_del.isEnabled() is True
    assert tab.btn_snap_export.isEnabled() is True
    assert tab.btn_snap_import.isEnabled() is True
    for button, action in tab._snap_menu_actions:
        assert action.isEnabled() == button.isEnabled()
    assert tab.btn_snap_more.isEnabled() is True

    core.connected = False
    tab._sync_snap_controls()
    assert tab.btn_snap_take.isEnabled() is False
    assert tab.btn_snap_diff.isEnabled() is False
    assert tab.btn_snap_del.isEnabled() is True
    core.connected = True

    tab._snap_worker = object()
    tab._sync_snap_controls()
    assert tab.cmb_snap.isEnabled() is False
    assert tab.btn_snap_del.isEnabled() is False
    assert tab.btn_snap_export.isEnabled() is False
    assert tab.btn_snap_import.isEnabled() is False
    tab._snap_worker = None
    tab._sync_snap_controls()

    monkeypatch.setattr(snapshot, 'list_snapshots', lambda: [])
    tab.refresh_snaps()
    assert tab.cmb_snap.itemData(0) == ''
    assert tab.btn_snap_diff.isEnabled() is False
    assert tab.btn_snap_more.isEnabled() is True

    monkeypatch.setattr(snapshot, 'list_snapshots', lambda: ['A', 'B'])
    tab.refresh_snaps()
    tab.cmb_snap.setCurrentIndex(1)
    monkeypatch.setattr(snapshot, 'list_snapshots', lambda: ['B', 'C'])
    tab.refresh_snaps()
    assert tab.cmb_snap.currentData() == 'B'
    assert tab.cmb_snap.findData('B') == 0


def test_snapshot_al_ve_isci(hist, monkeypatch):
    tab, core, win, _kayitlar = hist
    bilgi = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgi.append(a))
    monkeypatch.setattr(snapshot, 'list_snapshots', lambda: ['Kayit A'])
    core.config.user_id = 7

    tab._snap_worker = object()
    tab._snap_take()
    assert win.runs == []
    tab._snap_worker = None

    tab._snap_worker = object()
    assert tab._start_snapshot_worker(_SahteIsci(), ('x',), None,
                                      'd') is False
    tab._snap_worker = None
    ctx = (core.engine, 'tv-1', tab._connection_generation)
    win._closing = True
    assert tab._start_snapshot_worker(_SahteIsci(), ctx, None, 'd') is False
    win._closing = False
    assert tab._start_snapshot_worker(_SahteIsci(), (object(), 'tv-1', 0),
                                      None, 'd') is False

    tab._snap_take()
    w = win.runs[-1][0]
    assert w.args == (core.engine, 'tv-1', 'take')
    assert w.kwargs == {'user_id': 7}
    assert win.runs[-1][1] == 'Geçmiş: durum kaydı alınıyor'
    assert tab._snap_worker is w

    w.progress.emit(2, 5)
    assert tab.lbl_summary.text() == 'Durum kaydı: 2/5'
    tab._connection_generation += 1
    w.progress.emit(3, 5)
    assert tab.lbl_summary.text() == 'Durum kaydı: 2/5'
    tab._connection_generation -= 1

    w.finished_ok.emit({'name': 'Kayit A', 'count': 5})
    w.finished.emit()
    assert tab.lbl_summary.text().startswith('Durum kaydı işlemi tamamlandı')
    assert bilgi[-1][1] == 'Durum kaydı'
    assert bilgi[-1][2] == '5 paket durumu kaydedildi:\nKayit A'
    assert tab._snap_worker is None

    tab._snap_take()
    w = win.runs[-1][0]
    w.failed.emit('komut yok')
    w.finished.emit()
    assert tab.lbl_summary.text() == 'Durum kaydı tamamlanamadı: komut yok'

    tab._snap_take()
    w = win.runs[-1][0]
    w.finished.emit()
    assert tab.lbl_summary.text() == 'Durum kaydı tamamlanamadı.'

    tab._snap_take()
    w = win.runs[-1][0]
    win._closing = True
    w.finished.emit()
    assert tab._snap_worker is None
    win._closing = False

    tab._snap_take()
    w = win.runs[-1][0]
    tab._snap_worker = None
    w.finished.emit()

    win.patlak_run = True
    tab._snap_take()
    assert tab.lbl_summary.text() == 'Durum kaydı tamamlanamadı: patladi'
    assert tab._snap_worker is None
    win.patlak_run = False


def test_snapshot_fark(hist, monkeypatch):
    tab, _core, win, _kayitlar = hist
    bilgi = []
    hatalar = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgi.append(a))
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: hatalar.append(a))

    tab._snap_worker = object()
    tab._snap_diff()
    assert win.runs == []
    tab._snap_worker = None

    tab._snap_diff()
    assert bilgi[-1][1] == 'Durum kaydı'
    assert bilgi[-1][2] == 'Önce bir durum kaydı seçin.'

    monkeypatch.setattr(snapshot, 'list_snapshots', lambda: ['A'])
    tab.refresh_snaps()

    def yukle_patlak(name):
        raise ValueError('bozuk kayit')

    monkeypatch.setattr(snapshot, 'load', yukle_patlak)
    tab._snap_diff()
    assert hatalar[-1][1] == 'Durum kaydı'
    assert hatalar[-1][2] == 'bozuk kayit'

    monkeypatch.setattr(snapshot, 'load', lambda name: {'name': name})
    monkeypatch.setattr(snapshot, 'diff_current',
                        lambda engine, target, snap: [])
    tab._snap_diff()
    w = win.runs[-1][0]
    assert w.job_name == 'Durum kaydı farkı'
    assert win.runs[-1][1] == 'Geçmiş: durum kaydı farkı hesaplanıyor'
    assert w.args[0]() == []

    from mibox_app.workers import CancelledError
    tab._connection_generation += 1
    with pytest.raises(CancelledError):
        w.args[0]()
    tab._connection_generation -= 1

    w.finished_ok.emit([('com.a', 1, 2, 'x')])
    w.finished.emit()
    assert bilgi[-1][2].startswith('1 paket farklı:')

    tab._show_diff([])
    assert bilgi[-1][2] == 'Fark yok: cihaz durum kaydıyla aynı durumda.'
    tab._show_diff([('com.a', 1, 2, ('etkin', 'devre dışı')),
                    ('com.b', 1, 2, 'kaldırıldı')])
    metin = bilgi[-1][2]
    assert metin.startswith('2 paket farklı:')
    assert 'com.a -> etkin → devre dışı' in metin
    assert 'com.b -> kaldırıldı' in metin
    cok = [('p{}'.format(i), 0, 0, 'x') for i in range(45)]
    tab._show_diff(cok)
    assert '... ve 5 tane daha' in bilgi[-1][2]


def test_snapshot_uygula(hist, monkeypatch):
    tab, core, win, _kayitlar = hist
    bilgi = []
    uyari = []
    hatalar = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgi.append(a))
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: uyari.append(a))
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: hatalar.append(a))
    monkeypatch.setattr(QMessageBox, 'question',
                        lambda *a, **k: QMessageBox.No)

    tab._snap_worker = object()
    tab._snap_apply()
    assert win.runs == []
    tab._snap_worker = None
    tab._snap_apply()
    assert bilgi[-1][1] == 'Durum kaydı'
    assert bilgi[-1][2] == 'Önce bir durum kaydı seçin.'

    monkeypatch.setattr(snapshot, 'list_snapshots', lambda: ['A'])
    tab.refresh_snaps()

    def yukle_patlak(name):
        raise OSError('kayit yok')

    monkeypatch.setattr(snapshot, 'load', yukle_patlak)
    tab._snap_apply()
    assert hatalar[-1][1] == 'Durum kaydı'
    assert hatalar[-1][2].startswith('Kayıt okunamadı; işlem yapılmadı:\n')

    kayit = {'name': 'A', 'target': 'tv-1', 'user_id': 2,
             'packages': {
                 'com.a': {'installed_user0': True, 'enabled': True,
                           'restricted': False},
                 'com.b': {'installed_user0': True, 'enabled': False,
                           'restricted': False},
                 'com.c': {'installed_user0': True, 'enabled': True,
                           'restricted': True},
                 'com.d': {'installed_user0': False, 'enabled': True,
                           'restricted': False},
             }}
    monkeypatch.setattr(snapshot, 'load', lambda name: kayit)
    tab._snap_apply()
    assert tab._snap_worker is None

    sorular = []
    monkeypatch.setattr(
        QMessageBox, 'question',
        lambda *a, **k: (sorular.append(a), QMessageBox.Yes)[1])
    tab._snap_apply()
    w = win.runs[-1][0]
    assert w.args == (core.engine, 'tv-1', 'apply')
    assert w.kwargs == {'snapshot_name': 'A',
                        'protected': ['com.korunan'], 'user_id': 2,
                        'snapshot_data': kayit}
    govde = sorular[-1][2]
    assert ('4 paket (arka plan kısıtlı: 1, devre dışı: 1, etkin: 1, '
            'kullanıcı için kaldırılmış: 1).' in govde)
    assert 'Kayıt kaynağı: tv-1' in govde
    assert 'Hedef cihaz: tv-1' in govde
    assert 'Android kullanıcısı: 2' in govde
    assert govde.endswith('Bu kaydı hedef cihaza uygulamak istiyor musunuz?')
    tab._snap_worker = None

    def sor_mesgul(*a, **k):
        tab._undo_queue = ['x']
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, 'question', sor_mesgul)
    tab._snap_apply()
    assert uyari[-1][2] == ('Bağlantı veya işlem durumu değişti; işlem '
                            'başlatılmadı.')
    tab._undo_queue = []
    monkeypatch.setattr(QMessageBox, 'question',
                        lambda *a, **k: QMessageBox.Yes)

    from mibox_app import workers as workers_mod
    monkeypatch.setattr(workers_mod, 'format_action_result',
                        lambda res, ad: 'SONUC')
    tab._snap_apply()
    w = win.runs[-1][0]
    win.tab_apps.patlak = True
    w.finished_ok.emit({'ok': 1})
    w.finished.emit()
    win.tab_apps.patlak = False
    assert win.tab_apps.yenileme == 1
    assert bilgi[-1][1] == 'Durum kaydı'
    assert bilgi[-1][2] == 'SONUC'


def test_snapshot_sil(hist, monkeypatch):
    tab, _core, _win, _kayitlar = hist
    hatalar = []
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: hatalar.append(a))
    monkeypatch.setattr(QMessageBox, 'question',
                        lambda *a, **k: QMessageBox.No)
    monkeypatch.setattr(snapshot, 'list_snapshots', lambda: ['A'])
    tab.refresh_snaps()

    silinen = []
    monkeypatch.setattr(snapshot, 'delete',
                        lambda name: (silinen.append(name), True)[1])

    tab._snap_worker = object()
    tab._snap_delete()
    tab._snap_worker = None

    tab._snap_delete()
    assert silinen == []

    monkeypatch.setattr(QMessageBox, 'question',
                        lambda *a, **k: QMessageBox.Yes)
    tab._snap_delete()
    assert silinen == ['A']

    monkeypatch.setattr(snapshot, 'delete', lambda name: False)
    tab._snap_delete()
    assert hatalar[-1][1] == 'Durum kaydı'
    assert hatalar[-1][2] == 'Kayıt silinemedi; dosya erişimini kontrol edin.'

    def sil_mesgul(*a, **k):
        tab._undo_queue = ['x']
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, 'question', sil_mesgul)
    tab._snap_delete()
    tab._undo_queue = []

    monkeypatch.setattr(snapshot, 'list_snapshots', lambda: [])
    tab.refresh_snaps()
    tab._snap_delete()
    assert silinen == ['A']


def test_snapshot_ice_disa(hist, monkeypatch, tmp_path):
    tab, _core, _win, _kayitlar = hist
    bilgi = []
    hatalar = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgi.append(a))
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: hatalar.append(a))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName',
                        lambda *a, **k: ('', ''))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *a, **k: ('', ''))

    tab._snap_worker = object()
    tab._snap_export()
    tab._snap_import()
    tab._snap_worker = None

    tab._snap_export()
    assert bilgi[-1][2] == 'Önce bir durum kaydı seçin.'
    tab._snap_import()
    assert len(bilgi) == 1

    monkeypatch.setattr(snapshot, 'list_snapshots', lambda: ['A'])
    tab.refresh_snaps()
    sayi = len(bilgi)
    tab._snap_export()
    assert len(bilgi) == sayi
    hedef = tmp_path / 'k.json'
    disa = []
    monkeypatch.setattr(snapshot, 'export_snapshot',
                        lambda name, path: disa.append((name, path)))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *a, **k: (str(hedef), ''))
    tab._snap_export()
    assert disa == [('A', str(hedef))]
    assert bilgi[-1][1] == 'Tamam'
    assert bilgi[-1][2] == 'Aktarıldı:\n' + str(hedef)

    def disa_patlak(name, path):
        raise OSError('disk yok')

    monkeypatch.setattr(snapshot, 'export_snapshot', disa_patlak)
    tab._snap_export()
    assert hatalar[-1][1] == 'Hata'
    assert hatalar[-1][2] == 'disk yok'

    def kaydet_mesgul(*a, **k):
        tab._undo_queue = ['x']
        return (str(hedef), '')

    monkeypatch.setattr(QFileDialog, 'getSaveFileName', kaydet_mesgul)
    tab._snap_export()
    tab._undo_queue = []
    assert disa == [('A', str(hedef))]

    monkeypatch.setattr(QFileDialog, 'getOpenFileName',
                        lambda *a, **k: ('', ''))
    tab._snap_import()
    assert len(hatalar) == 1

    def ic_patlak(path):
        raise ValueError('bozuk')

    monkeypatch.setattr(snapshot, 'import_snapshot', ic_patlak)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName',
                        lambda *a, **k: (str(hedef), ''))
    tab._snap_import()
    assert hatalar[-1][2] == 'bozuk'

    ic = []
    monkeypatch.setattr(snapshot, 'import_snapshot',
                        lambda path: (ic.append(path), ('Yeni', 3))[1])
    monkeypatch.setattr(snapshot, 'list_snapshots', lambda: ['A', 'Yeni'])
    tab._snap_import()
    assert ic == [str(hedef)]
    assert bilgi[-1][1] == 'Tamam'
    assert bilgi[-1][2] == ('3 paket durumu içe aktarıldı:\nYeni\nDiğer '
                            'cihaza bağlanıp Uygula ile uygulayın.')

    def ac_mesgul(*a, **k):
        tab._undo_queue = ['x']
        return (str(hedef), '')

    monkeypatch.setattr(QFileDialog, 'getOpenFileName', ac_mesgul)
    tab._snap_import()
    assert ic == [str(hedef)]
    tab._undo_queue = []
