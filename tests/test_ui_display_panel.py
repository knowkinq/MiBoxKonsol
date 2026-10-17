# -*- coding: utf-8 -*-
"""display_panel: okuma, sifirlama, uygulama, geri alma ve kapanma akislari."""
import pytest
from PySide6.QtCore import QObject, QPoint, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
)

from mibox_app.ui.display_panel import DisplayPanel
from mibox_app.workers import Worker


def _bilgi(**kw):
    info = {'width': 1920, 'height': 1080, 'fps': 60, 'density': 320,
            'sink_name': None, 'overscan': None,
            'override_width': None, 'override_height': None,
            'override_density': None, 'read_errors': []}
    info.update(kw)
    return info


class _Motor:
    def __init__(self):
        self.calls = []
        self.plan = {}
        self.hooks = {}
        self.default = {'display_details': _bilgi()}

    def _call(self, name, *args):
        self.calls.append((name,) + args)
        kuyruk = self.plan.get(name)
        if kuyruk:
            deger = kuyruk.pop(0)
        else:
            deger = self.default.get(name)
        kanca = self.hooks.get(name)
        if kanca:
            kanca()
        if isinstance(deger, Exception):
            raise deger
        return deger

    def display_details(self, target):
        return self._call('display_details', target)

    def set_display_size(self, target, width, height):
        return self._call('set_display_size', target, width, height)

    def reset_display_size(self, target):
        return self._call('reset_display_size', target)

    def set_display_density(self, target, density):
        return self._call('set_display_density', target, density)

    def reset_display_density(self, target):
        return self._call('reset_display_density', target)

    def set_display_overscan(self, target, left, top, right, bottom):
        return self._call('set_display_overscan', target, left, top, right,
                          bottom)

    def reset_display_overscan(self, target):
        return self._call('reset_display_overscan', target)


class _Cekirdek(QObject):
    connection_changed = Signal(bool, object)

    def __init__(self):
        super().__init__()
        self.connected = True
        self.target = 'tv-1'
        self.engine_ready = True
        self._engine = _Motor()

    @property
    def engine(self):
        if not self.engine_ready:
            raise RuntimeError('motor yok')
        return self._engine


class _Pencere:
    def __init__(self):
        self._workers = []
        self.runs = []
        self._closing = False
        self._close_pending = False
        self._connection_busy = False
        self._disconnect_pending = False
        self._disconnect_in_progress = False
        self.close_count = 0
        self.watchdog = 0

    def _run(self, worker, desc=None):
        self.runs.append((worker, desc))
        self._workers.append(worker)

    def close(self):
        self.close_count += 1

    def _watchdog_worker_finished(self):
        self.watchdog += 1


@pytest.fixture
def panel(qtbot):
    core = _Cekirdek()
    win = _Pencere()
    p = DisplayPanel(core, win)
    qtbot.addWidget(p)
    return p, core, win


def _temizle(p):
    p._jobs.clear()
    p._invalidate_read()


def test_kurulum_ve_tekerlek(panel):
    p, _core, _win = panel

    assert p.btn_read.text() == 'Ekranı Sorgula'
    assert p.btn_apply.text() == 'Görüntü Ayarlarını Uygula'
    assert p.btn_apply.property('accent') is True
    assert p.btn_reset_all.text() == 'Tüm Görüntüyü Fabrikaya Sıfırla'
    assert p.btn_reset_all.property('role') == 'quiet'
    for etiket in (p.lbl_res_val, p.lbl_fps_val, p.lbl_dens_val,
                   p.lbl_sink_val):
        assert etiket.text() == '—'
    assert p.lbl_status.text() == ('Mevcut ekran bilgisi henüz okunmadı. '
                                   '"Ekranı Sorgula" ile mevcut değerleri okuyun.')
    metinler = [lbl.text() for lbl in p.findChildren(QLabel)]
    assert 'Çözünürlük (Boyut)' in metinler
    assert 'Yenileme Hızı (Hz)' in metinler
    assert 'Arayüz Ölçeği (DPI)' in metinler
    assert 'Bağlı TV / Monitör' in metinler

    assert p.cmb_res.count() == 5
    assert p.cmb_res.itemData(0) is None
    assert p.cmb_res.itemData(1) == (1920, 1080)
    assert p.cmb_res.itemData(4) == 'reset'
    assert p.cmb_dpi.count() == 6
    assert p.cmb_dpi.itemData(2) == 280
    assert p.cmb_dpi.itemData(5) == 'reset'
    assert p.cmb_ov.count() == 5
    assert p.cmb_ov.itemData(1) == (0, 0, 0, 0)
    assert p.cmb_ov.itemData(2) == (15, 15, 15, 15)
    for combo in (p.cmb_res, p.cmb_dpi, p.cmb_ov):
        assert combo.currentData() is None
        assert combo.minimumHeight() == 34
        assert combo.minimumContentsLength() == 20

    assert p._jobs == set()
    assert p._confirming is False
    assert p._read_worker is None
    assert p._read_token is None
    assert p._close_after_transaction is False

    ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0),
                     QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                     Qt.ScrollUpdate, False)
    p.cmb_res.wheelEvent(ev)
    assert ev.isAccepted() is False

    p.show()
    p.cmb_res.showPopup()
    assert p.cmb_res.view().isVisible() is True
    ev2 = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0),
                      QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                      Qt.ScrollUpdate, False)
    p.cmb_res.wheelEvent(ev2)
    p.cmb_res.hidePopup()

    p.resize(1000, 700)
    assert p._cards.direction() == QBoxLayout.LeftToRight
    p.resize(500, 700)
    assert p._cards.direction() == QBoxLayout.TopToBottom


def test_read_display_akisi(panel, monkeypatch):
    p, core, win = panel
    bilgiler = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgiler.append(a))

    win._closing = True
    p.read_display()
    assert win.runs == []
    win._closing = False

    win._close_pending = True
    p.read_display()
    assert win.runs == []
    win._close_pending = False

    win._connection_busy = True
    p.read_display()
    assert p.lbl_status.text() == ('Bağlantı tamamlanınca ekran bilgileri '
                                   'okunacak.')
    win._connection_busy = False

    core.connected = False
    p.read_display()
    assert bilgiler[0][1] == 'Bağlantı Yok'
    assert bilgiler[0][2] == ('Ekran bilgilerini okumak için önce cihaza '
                              'bağlanın.')
    core.connected = True

    core.engine_ready = False
    p.read_display()
    assert p.lbl_status.text() == 'Cihaz motoru hazır değil: motor yok'
    core.engine_ready = True

    p.read_display()
    isci, desc = win.runs[-1]
    assert isci.job_name == 'Ekran Bilgisi Okuma'
    assert desc == 'Ekran: mevcut çözünürlük ve DPI okunuyor'
    assert p._read_worker is isci
    assert p._read_token is not None
    assert p.lbl_status.text() == 'Mevcut ekran bilgileri okunuyor…'
    p.read_display()
    assert len(win.runs) == 1

    isci.run()
    assert core.engine.calls[-1] == ('display_details', 'tv-1')
    assert p.lbl_res_val.text() == '1920×1080'
    assert p.lbl_fps_val.text() == '60 Hz'
    assert p.lbl_dens_val.text() == '320 DPI'
    assert p.lbl_sink_val.text() == 'Standart TV / Monitör'
    assert p.lbl_status.text() == 'Ekran: 1920×1080 @ 60Hz (320 DPI)'
    isci.finished.emit()
    assert p._read_worker is None

    core.engine.default['display_details'] = _bilgi(
        sink_name='HDMI-1', override_width=1920, override_height=1080,
        override_density=320, overscan='15,15,15,15')
    p.read_display()
    isci = win.runs[-1][0]
    isci.run()
    isci.finished.emit()
    assert p.lbl_sink_val.text() == 'HDMI-1'
    assert p.lbl_status.text() == (
        'Ekran: 1920×1080 @ 60Hz (320 DPI) · Özel ayar etkin · HDMI-1 · '
        'Kenar boşluğu: 15,15,15,15')

    core.engine.default['display_details'] = RuntimeError('okuma yok')
    p.read_display()
    isci = win.runs[-1][0]
    isci.run()
    isci.finished.emit()
    assert p.lbl_status.text() == 'Ekran okunamadı: RuntimeError: okuma yok'
    assert p._read_worker is None

    core.engine.default['display_details'] = _bilgi()
    p.read_display()
    isci = win.runs[-1][0]
    p._generation += 1
    durum = p.lbl_status.text()
    isci.run()
    isci.finished.emit()
    assert p.lbl_status.text() == durum
    assert p._read_worker is None


def test_read_display_baslatma_hatalari(panel, monkeypatch):
    p, _core, win = panel

    def patlak_run(worker, desc=None):
        raise RuntimeError('calistirilamadi')

    monkeypatch.setattr(win, '_run', patlak_run)
    p.read_display()
    assert p.lbl_status.text() == ('Ekran bilgisi okuması başlatılamadı: '
                                   'calistirilamadi')
    assert p._read_worker is None

    def patlak_run2(worker, desc=None):
        win._closing = True
        raise RuntimeError('yine')

    monkeypatch.setattr(win, '_run', patlak_run2)
    p.read_display()
    assert p.lbl_status.text() == 'Mevcut ekran bilgileri okunuyor…'
    assert p._read_worker is None
    win._closing = False


def test_baglanti_degisimi(panel):
    p, core, win = panel
    p.cmb_res.setCurrentIndex(2)
    p.cmb_dpi.setCurrentIndex(3)
    p.cmb_ov.setCurrentIndex(4)

    core.connection_changed.emit(False, None)

    assert p._generation == 1
    for combo in (p.cmb_res, p.cmb_dpi, p.cmb_ov):
        assert combo.currentIndex() == 0
    assert p.lbl_res_val.text() == '—'
    assert p.lbl_fps_val.text() == '—'
    assert p.lbl_dens_val.text() == '—'
    assert p.lbl_sink_val.text() == '—'
    assert p.lbl_status.text() == ('Bağlı cihaz yok. Cihaza bağlanıp ekranı '
                                   'sorgulayın.')
    assert win.runs == []

    core.connection_changed.emit(True, 'tv-1')
    ilk = win.runs[-1][0]
    assert ilk.job_name == 'Ekran Bilgisi Okuma'
    assert p._read_worker is ilk

    core.connection_changed.emit(True, 'tv-1')
    assert ilk.isInterruptionRequested() is True
    yeni = win.runs[-1][0]
    assert yeni is not ilk
    assert p._read_worker is yeni
    assert p._generation == 3


def test_hazir_olma_ve_is_akisi(panel, qtbot, monkeypatch):
    p, core, win = panel

    assert p._ready() is True
    win._closing = True
    assert p._ready() is False
    win._closing = False
    win._close_pending = True
    assert p._ready() is False
    win._close_pending = False

    isaret = object()
    p._jobs.add(isaret)
    assert p._ready() is False
    assert p.lbl_status.text() == ('Devam eden ekran işleminin bitmesini '
                                   'bekleyin.')
    p._jobs.clear()
    p._confirming = True
    assert p._ready() is False
    p._confirming = False
    p._read_worker = isaret
    assert p._ready() is False
    p._read_worker = None
    core.connected = False
    assert p._ready() is False
    assert p.lbl_status.text() == 'Önce bir cihaza bağlanın.'
    core.connected = True
    core.target = ''
    assert p._ready() is False
    core.target = 'tv-1'
    win._connection_busy = True
    assert p._ready() is False
    win._connection_busy = False
    assert p._ready() is True

    assert p._has_pending_display_transaction() is False
    w = Worker(lambda: None)
    w.job_name = 'Baska Is'
    p._run_change(w, 'test isi')
    assert win.runs[-1] == (w, 'test isi')
    assert w in p._jobs
    assert p.btn_apply.isEnabled() is False
    assert p.btn_read.isEnabled() is False
    assert p._has_pending_display_transaction() is False
    w.finished.emit()
    assert w not in p._jobs
    assert p.btn_apply.isEnabled() is True

    p._confirming = True
    assert p._has_pending_display_transaction() is True
    p._confirming = False
    wA = Worker(lambda: None)
    wA.job_name = 'Görüntü Ayarlama'
    p._jobs.add(wA)
    assert p._has_pending_display_transaction() is True
    p._jobs.clear()

    p._close_after_transaction = True
    wB = Worker(lambda: None)
    wB.job_name = 'Görüntü Ayarlama'
    p._run_change(wB, 'b')
    wC = Worker(lambda: None)
    wC.job_name = 'Baska'
    p._run_change(wC, 'c')
    wC.finished.emit()
    qtbot.wait(1)
    assert win.close_count == 0
    assert p._close_after_transaction is True
    wB.finished.emit()
    qtbot.wait(1)
    assert win.close_count == 1
    assert p._close_after_transaction is False

    p._close_after_transaction = True
    p._confirming = True
    wD = Worker(lambda: None)
    wD.job_name = 'Baska'
    p._run_change(wD, 'd')
    wD.finished.emit()
    qtbot.wait(1)
    assert win.close_count == 1
    p._confirming = False
    p._close_after_transaction = False

    win._closing = True
    wE = Worker(lambda: None)
    p._run_change(wE, 'e')
    assert wE not in p._jobs
    win._closing = False

    def kayit_run(worker, desc=None):
        win.runs.append((worker, desc))

    monkeypatch.setattr(win, '_run', kayit_run)
    wF = Worker(lambda: None)
    p._run_change(wF, 'f')
    assert wF not in p._jobs
    assert win.runs[-1] == (wF, 'f')

    def patlak_run(worker, desc=None):
        raise RuntimeError('patladi')

    monkeypatch.setattr(win, '_run', patlak_run)
    wG = Worker(lambda: None)
    p._run_change(wG, 'g')
    assert wG not in p._jobs
    assert p.lbl_status.text() == 'Ekran işlemi başlatılamadı: patladi'

    def patlak_run2(worker, desc=None):
        win._closing = True
        raise RuntimeError('patladi2')

    monkeypatch.setattr(win, '_run', patlak_run2)
    durum = p.lbl_status.text()
    p._run_change(Worker(lambda: None), 'h')
    assert p.lbl_status.text() == durum
    win._closing = False


def test_reset_all_akisi(panel, monkeypatch):
    p, core, win = panel
    bilgiler = []
    hatalar = []
    sorular = []
    soru_cevap = [QMessageBox.No]
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgiler.append(a))
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: hatalar.append(a))

    def soru(*args, **kwargs):
        sorular.append(args)
        return soru_cevap[-1]

    monkeypatch.setattr(QMessageBox, 'question', soru)

    p._jobs.add(object())
    p._reset_all()
    assert sorular == []
    p._jobs.clear()

    core.engine_ready = False
    p._reset_all()
    assert p.lbl_status.text() == 'Cihaz motoru hazır değil: motor yok'
    core.engine_ready = True

    p._reset_all()
    assert sorular[0][1] == 'Görüntüyü sıfırla'
    assert sorular[0][2] == ('Çözünürlük, DPI ve kenar boşlukları fabrika '
                             'değerlerine döndürülsün mü?')
    assert win.runs == []

    soru_cevap[-1] = QMessageBox.Yes

    def hedef_degistir(*args, **kwargs):
        p._generation += 1
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, 'question', hedef_degistir)
    p._reset_all()
    assert win.runs == []
    monkeypatch.setattr(QMessageBox, 'question', soru)

    p._reset_all()
    isci = win.runs[-1][0]
    assert isci.job_name == 'Görüntü Sıfırlama'
    isci.run()
    assert ('reset_display_size', 'tv-1') in core.engine.calls
    assert ('reset_display_density', 'tv-1') in core.engine.calls
    assert ('reset_display_overscan', 'tv-1') in core.engine.calls
    assert bilgiler[-1][1] == 'Görüntü Sıfırlandı'
    assert bilgiler[-1][2] == ('Çözünürlük, DPI ölçeği ve kenar taşması '
                               'fabrika varsayılanına döndürüldü.')
    assert win.runs[-1][0].job_name == 'Ekran Bilgisi Okuma'
    isci.finished.emit()
    _temizle(p)

    core.engine.plan['display_details'] = [_bilgi(
        read_errors=['size', 'density'])]
    p._reset_all()
    win.runs[-1][0].run()
    assert ('Geri alma için mevcut değerler okunamadı: density, size.'
            in hatalar[-1][2])
    _temizle(p)

    core.engine.plan['display_details'] = [_bilgi(
        override_width=1280, override_height=720, override_density=240,
        overscan=None)]
    core.engine.plan['reset_display_density'] = [
        RuntimeError('yoğunluk patladi')]
    p._reset_all()
    win.runs[-1][0].run()
    assert ('set_display_density', 'tv-1', 240) in core.engine.calls
    assert ('set_display_size', 'tv-1', 1280, 720) in core.engine.calls
    assert hatalar[-1][2] == ('Görüntü sıfırlanamadı: RuntimeError: '
                              'yoğunluk patladi')
    _temizle(p)

    core.engine.plan['display_details'] = [_bilgi(
        override_width=1280, override_height=720, override_density=240)]
    core.engine.plan['reset_display_size'] = [RuntimeError('boyut patladi')]
    core.engine.plan['set_display_size'] = [RuntimeError('geri de patladi')]
    p._reset_all()
    win.runs[-1][0].run()
    assert 'Görüntü sıfırlama tamamlanamadı' in hatalar[-1][2]
    assert 'boyut patladi' in hatalar[-1][2]
    assert 'size: geri de patladi' in hatalar[-1][2]
    _temizle(p)

    core.engine.plan['display_details'] = [
        _bilgi(override_width=1280, override_height=720,
               override_density=240, overscan=None),
        RuntimeError('son okuma patladi')]
    p._reset_all()
    win.runs[-1][0].run()
    assert ('Kenar taşmasının işlem öncesi değeri cihazdan okunamadı'
            in hatalar[-1][2])
    _temizle(p)

    core.engine.plan['display_details'] = [_bilgi()]
    core.engine.plan['reset_display_density'] = [RuntimeError('d patladi')]
    p._reset_all()
    win.runs[-1][0].run()
    assert ('reset_display_size', 'tv-1') in core.engine.calls
    assert ('reset_display_density', 'tv-1') in core.engine.calls
    _temizle(p)

    core.engine.plan['display_details'] = [
        _bilgi(overscan=(15, 15, 15, 15)), RuntimeError('son okuma patladi')]
    p._reset_all()
    win.runs[-1][0].run()
    assert ('set_display_overscan', 'tv-1', 15, 15, 15, 15) in \
        core.engine.calls
    _temizle(p)

    core.engine.plan.clear()
    core.engine.default['display_details'] = _bilgi()
    p._reset_all()
    isci = win.runs[-1][0]
    isci.cancel()
    isci.run()
    assert hatalar[-1][2] == 'Görüntü sıfırlanamadı: kullanıcı durdurdu'
    _temizle(p)

    onceki = len(hatalar)
    p._reset_all()
    isci = win.runs[-1][0]
    p._generation += 1
    isci.run()
    assert len(hatalar) == onceki
    _temizle(p)


def test_apply_settings_diyaloglar(panel, monkeypatch, qtbot):
    p, core, win = panel
    bilgiler = []
    hatalar = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgiler.append(a))
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: hatalar.append(a))

    p._jobs.add(object())
    p._apply_settings()
    assert win.runs == []
    p._jobs.clear()

    p._apply_settings()
    assert bilgiler[0][1] == 'Seçim Yapılmadı'
    assert bilgiler[0][2] == ('Uygulamak için çözünürlük, DPI veya kenar '
                              'taşması seçeneklerinden en az birini '
                              'belirleyin.')

    p.cmb_res.setCurrentIndex(1)
    core.engine_ready = False
    p._apply_settings()
    assert p.lbl_status.text() == 'Cihaz motoru hazır değil: motor yok'
    core.engine_ready = True

    yakalanan = []

    def exec_reddet(self):
        yakalanan.append(self)
        return 0

    monkeypatch.setattr(QDialog, 'exec', exec_reddet)

    p.cmb_dpi.setCurrentIndex(3)
    p.cmb_ov.setCurrentIndex(2)
    core.engine.plan['display_details'] = [
        _bilgi(), _bilgi(width=1920, height=1080, density=320)]
    p._apply_settings()
    isci = win.runs[-1][0]
    assert isci.job_name == 'Görüntü Ayarlama'
    isci.run()
    assert ('set_display_size', 'tv-1', 1920, 1080) in core.engine.calls
    assert ('set_display_density', 'tv-1', 320) in core.engine.calls
    assert ('set_display_overscan', 'tv-1', 15, 15, 15, 15) in \
        core.engine.calls
    dlg = yakalanan[0]
    assert dlg.windowTitle() == 'Görüntü Ayarı Onayı'
    assert dlg.minimumWidth() == 380
    mesaj = next(lbl for lbl in dlg.findChildren(QLabel)
                 if lbl.text().startswith('Yeni görüntü ayarı uygulandı!'))
    assert '• Çözünürlük: 1920×1080' in mesaj.text()
    assert '• DPI Ölçeği: 320' in mesaj.text()
    assert ('Cihaz mevcut kenar boşluğunu bildirmediği için overscan '
            'fabrika değerine sıfırlanabilir.') in mesaj.text()
    sayac = next(lbl for lbl in dlg.findChildren(QLabel)
                 if lbl.text().startswith('Kalan süre:'))
    assert sayac.text() == 'Kalan süre: 15 saniye'
    kutular = dlg.findChild(QDialogButtonBox)
    onay = next(b for b in kutular.buttons() if b.text() == 'Ayarları Koru')
    assert onay.property('accent') is True
    geri = next(b for b in kutular.buttons() if b.text() == 'Geri Al')
    assert geri.property('role') is None
    assert p._confirming is False
    assert win.runs[-1][0].job_name == 'Ekran ayarı geri alma'
    assert win.runs[-1][1] == 'Ekran: ayarlar geri alınıyor'
    _temizle(p)

    zamanlayici_ref = []

    def exec_tik(self):
        yakalanan.append(self)
        zamanlayici = self.findChild(QTimer)
        zamanlayici_ref.append(zamanlayici)
        zamanlayici.timeout.emit()
        p._generation += 1
        zamanlayici.timeout.emit()
        return self.result()

    monkeypatch.setattr(QDialog, 'exec', exec_tik)
    core.engine.plan['display_details'] = [_bilgi(), _bilgi()]
    p._apply_settings()
    win.runs[-1][0].run()
    dlg = yakalanan[-1]
    sayac = next(lbl for lbl in dlg.findChildren(QLabel)
                 if lbl.text().startswith('Kalan süre:'))
    assert sayac.text() == 'Kalan süre: 14 saniye'
    assert zamanlayici_ref[-1].isActive() is False
    assert win.runs[-1][0].job_name == 'Ekran ayarı geri alma'
    _temizle(p)

    def exec_geri(self):
        yakalanan.append(self)
        kutular = self.findChild(QDialogButtonBox)
        geri = next(b for b in kutular.buttons() if b.text() == 'Geri Al')
        geri.click()
        return self.result()

    monkeypatch.setattr(QDialog, 'exec', exec_geri)
    core.engine.plan['display_details'] = [
        _bilgi(overscan=(15, 15, 15, 15)), _bilgi()]
    p._apply_settings()
    win.runs[-1][0].run()
    mesaj = next(lbl for lbl in yakalanan[-1].findChildren(QLabel)
                 if lbl.text().startswith('Yeni görüntü ayarı uygulandı!'))
    assert ('Onaylamazsanız görüntü otomatik olarak önceki haline '
            'dönecektir.') in mesaj.text()
    assert win.runs[-1][0].job_name == 'Ekran ayarı geri alma'
    _temizle(p)

    def exec_onay(self):
        yakalanan.append(self)
        kutular = self.findChild(QDialogButtonBox)
        onay = next(b for b in kutular.buttons()
                    if b.text() == 'Ayarları Koru')
        onay.click()
        return self.result()

    monkeypatch.setattr(QDialog, 'exec', exec_onay)
    core.engine.plan['display_details'] = [_bilgi(), _bilgi()]
    p._apply_settings()
    win.runs[-1][0].run()
    assert win.runs[-1][0].job_name == 'Ekran Bilgisi Okuma'
    _temizle(p)

    p.cmb_res.setCurrentIndex(4)
    p.cmb_dpi.setCurrentIndex(5)
    p.cmb_ov.setCurrentIndex(1)
    core.engine.plan['display_details'] = [_bilgi(), _bilgi()]
    core.engine.calls.clear()
    p._apply_settings()
    win.runs[-1][0].run()
    assert ('reset_display_size', 'tv-1') in core.engine.calls
    assert ('reset_display_density', 'tv-1') in core.engine.calls
    assert ('reset_display_overscan', 'tv-1') in core.engine.calls
    assert not any(call[0].startswith('set_display')
                   for call in core.engine.calls)
    assert win.runs[-1][0].job_name == 'Ekran Bilgisi Okuma'
    _temizle(p)

    p.cmb_res.setCurrentIndex(1)
    p.cmb_dpi.setCurrentIndex(3)
    p.cmb_ov.setCurrentIndex(2)
    win._disconnect_pending = True
    core.engine.plan['display_details'] = [_bilgi(), _bilgi()]
    p._apply_settings()
    win.runs[-1][0].run()
    qtbot.wait(1)
    assert win.watchdog == 1
    assert win.runs[-1][0].job_name == 'Ekran ayarı geri alma'
    win._disconnect_pending = False
    _temizle(p)

    def exec_onay_ve_kop(self):
        yakalanan.append(self)
        win._disconnect_pending = True
        kutular = self.findChild(QDialogButtonBox)
        onay = next(b for b in kutular.buttons()
                    if b.text() == 'Ayarları Koru')
        onay.click()
        return self.result()

    monkeypatch.setattr(QDialog, 'exec', exec_onay_ve_kop)
    core.engine.plan['display_details'] = [_bilgi(), _bilgi()]
    p._apply_settings()
    win.runs[-1][0].run()
    qtbot.wait(1)
    assert win.watchdog == 2
    assert win.runs[-1][0].job_name == 'Ekran ayarı geri alma'
    win._disconnect_pending = False
    _temizle(p)


def test_apply_settings_hata_yollari(panel, monkeypatch):
    p, core, win = panel
    hatalar = []
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: hatalar.append(a))
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: None)
    monkeypatch.setattr(QDialog, 'exec', lambda self: 0)

    p.cmb_res.setCurrentIndex(1)
    p.cmb_dpi.setCurrentIndex(3)
    p.cmb_ov.setCurrentIndex(2)

    core.engine.plan['display_details'] = [_bilgi(read_errors=['size'])]
    p._apply_settings()
    win.runs[-1][0].run()
    assert ('Geri alma için mevcut değerler okunamadı: size. Hiçbir ayar '
            'değiştirilmedi.') in hatalar[-1][2]
    assert win.runs[-1][0].job_name == 'Ekran Bilgisi Okuma'
    _temizle(p)

    core.engine.plan['display_details'] = [
        _bilgi(), RuntimeError('son patladi')]
    core.engine.plan['reset_display_overscan'] = [
        RuntimeError('geri de patladi')]
    p._apply_settings()
    win.runs[-1][0].run()
    assert hatalar[-1][1] == 'Görüntü Hatası'
    assert 'son patladi' in hatalar[-1][2]
    assert 'önceki ayarlar tamamen geri yüklenemedi' in hatalar[-1][2]
    assert ('Kenar taşmasının işlem öncesi değeri okunamadı'
            in hatalar[-1][2])
    _temizle(p)

    core.engine.plan.clear()
    core.engine.plan['display_details'] = [
        _bilgi(override_width=1280, override_height=720,
               override_density=240, overscan=(5, 6, 7, 8)),
        RuntimeError('son patladi')]
    p.cmb_ov.setCurrentIndex(3)
    p._apply_settings()
    win.runs[-1][0].run()
    assert ('set_display_size', 'tv-1', 1280, 720) in core.engine.calls
    assert ('set_display_density', 'tv-1', 240) in core.engine.calls
    assert ('set_display_overscan', 'tv-1', 5, 6, 7, 8) in core.engine.calls
    _temizle(p)

    core.engine.plan.clear()
    core.engine.default['display_details'] = _bilgi()
    p._apply_settings()
    isci = win.runs[-1][0]
    isci.cancel()
    isci.run()
    assert hatalar[-1][1] == 'Görüntü Hatası'
    assert hatalar[-1][2] == 'kullanıcı durdurdu'
    _temizle(p)

    onceki = len(hatalar)
    p._apply_settings()
    isci = win.runs[-1][0]
    p._generation += 1
    isci.run()
    assert len(hatalar) == onceki
    _temizle(p)


def test_revert_akisi(panel, monkeypatch):
    p, core, win = panel
    bilgiler = []
    hatalar = []
    uyarilar = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgiler.append(a))
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: hatalar.append(a))
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: uyarilar.append(a))

    core.engine_ready = False
    p._revert(_bilgi(), 'tv-1')
    assert p.lbl_status.text() == ('Görüntü ayarları geri alınamadı: '
                                   'motor yok')
    core.engine_ready = True

    p._revert(_bilgi(override_width=1280, override_height=720,
                     override_density=240, overscan=None), 'tv-1')
    isci = win.runs[-1][0]
    assert isci.job_name == 'Ekran ayarı geri alma'
    assert isci.preserve_on_close is True
    assert isci._allow_during_disconnect is True
    assert isci._preserve_from_cancel is True
    isci.run()
    assert ('set_display_size', 'tv-1', 1280, 720) in core.engine.calls
    assert ('set_display_density', 'tv-1', 240) in core.engine.calls
    assert ('reset_display_overscan', 'tv-1') in core.engine.calls
    assert uyarilar[-1][1] == 'Geri Alma Tamamlandı'
    assert uyarilar[-1][2] == ('Diğer seçili görüntü ayarları geri yüklendi. '
                               'Cihaz önceki kenar boşluğunu bildirmediği '
                               'için overscan fabrika değerine sıfırlandı.')
    assert win.runs[-1][0].job_name == 'Ekran Bilgisi Okuma'
    _temizle(p)

    p._revert(_bilgi(override_width=1280, override_height=720,
                     override_density=240, overscan=(15, 15, 15, 15)),
              'tv-1')
    win.runs[-1][0].run()
    assert ('set_display_overscan', 'tv-1', 15, 15, 15, 15) in \
        core.engine.calls
    assert bilgiler[-1][1] == 'Geri Alındı'
    assert bilgiler[-1][2] == ('Görüntü ayarları önceki durumuna geri '
                               'döndürüldü.')
    _temizle(p)

    core.engine.plan['set_display_density'] = [RuntimeError('yoğunluk yok')]
    p._revert(_bilgi(override_density=240), 'tv-1')
    win.runs[-1][0].run()
    assert hatalar[-1][1] == 'Görüntü geri alınamadı'
    assert hatalar[-1][2] == (
        'RuntimeError: Bazı görüntü ayarları geri alınamadı: '
        'density: yoğunluk yok')
    _temizle(p)

    p._revert(_bilgi(), 'tv-1')
    isci = win.runs[-1][0]
    bilgi_sayisi = len(bilgiler)
    p._generation += 1
    isci.run()
    assert len(bilgiler) == bilgi_sayisi
    _temizle(p)

    p._revert(_bilgi(), 'tv-1')
    isci = win.runs[-1][0]
    isci.cancel()
    isci.run()
    assert hatalar[-1][1] == 'Görüntü geri alınamadı'
    assert hatalar[-1][2] == 'kullanıcı durdurdu'
    _temizle(p)


def test_kesme_ve_eski_nesil_sinyalleri(panel, monkeypatch):
    p, core, win = panel
    monkeypatch.setattr(QMessageBox, 'critical', lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, 'question',
                        lambda *a, **k: QMessageBox.Yes)

    def kanca(ad, islev):
        core.engine.hooks.clear()
        core.engine.hooks[ad] = islev

    def nesil_artir():
        p._generation += 1

    p.read_display()
    isci = win.runs[-1][0]
    sayi = len(win.runs)
    p._generation += 1
    isci.finished_ok.emit(_bilgi())
    assert len(win.runs) == sayi
    isci.finished.emit()
    _temizle(p)

    p.cmb_res.setCurrentIndex(1)
    kanca('display_details', nesil_artir)
    p._apply_settings()
    win.runs[-1][0].run()
    _temizle(p)

    core.engine.hooks.clear()

    class _YanEtkiliListe(list):
        def __iter__(self):
            p._generation += 1
            return super().__iter__()

    core.engine.plan['display_details'] = [
        _bilgi(read_errors=_YanEtkiliListe())]
    p._apply_settings()
    win.runs[-1][0].run()
    _temizle(p)

    kanca('set_display_size', nesil_artir)
    p._apply_settings()
    win.runs[-1][0].run()
    _temizle(p)

    p.cmb_dpi.setCurrentIndex(3)
    kanca('set_display_density', nesil_artir)
    p._apply_settings()
    win.runs[-1][0].run()
    _temizle(p)

    p.cmb_ov.setCurrentIndex(2)
    kanca('set_display_overscan', nesil_artir)
    p._apply_settings()
    win.runs[-1][0].run()
    _temizle(p)

    sayac = [0]

    def ikinci_okumada_artir():
        sayac[0] += 1
        if sayac[0] == 2:
            p._generation += 1

    kanca('display_details', ikinci_okumada_artir)
    p._apply_settings()
    win.runs[-1][0].run()
    _temizle(p)

    core.engine.hooks.clear()
    core.engine.plan.clear()
    core.engine.default['display_details'] = _bilgi()

    kanca('reset_display_size', nesil_artir)
    p._reset_all()
    win.runs[-1][0].run()
    _temizle(p)

    kanca('reset_display_overscan', nesil_artir)
    p._reset_all()
    win.runs[-1][0].run()
    _temizle(p)

    sayac2 = [0]

    def ikinci_okumada_artir2():
        sayac2[0] += 1
        if sayac2[0] == 2:
            p._generation += 1

    kanca('display_details', ikinci_okumada_artir2)
    p._reset_all()
    win.runs[-1][0].run()
    _temizle(p)

    core.engine.hooks.clear()
    p._reset_all()
    isci = win.runs[-1][0]
    sayi = len(win.runs)
    p._generation += 1
    isci.finished_ok.emit(_bilgi())
    assert len(win.runs) == sayi
    isci.finished.emit()
    _temizle(p)








