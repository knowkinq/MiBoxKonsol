# -*- coding: utf-8 -*-
"""logcat_tab: yoklama akisi, dedup, filtre/renk, cokme avcisi ve temizleme."""
import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMessageBox,
)

from mibox_app.ui import kit
from mibox_app.ui.logcat_tab import LEVEL_COLORS, LogcatTab, dedup_new_lines
from mibox_app.ui.theme import logcat_colors_for


class _Motor:
    def __init__(self):
        self.dump_calls = []
        self.dump_text = ''
        self.dump_hata = None
        self.crash_calls = []
        self.crash_text = ''
        self.crash_hata = None
        self.clear_calls = []
        self.clear_hata = None

    def logcat_dump(self, target, lines=120, level=None, tag=None):
        self.dump_calls.append((target, lines, level, tag))
        if self.dump_hata is not None:
            raise self.dump_hata
        return self.dump_text

    def logcat_crash(self, target):
        self.crash_calls.append(target)
        if self.crash_hata is not None:
            raise self.crash_hata
        return self.crash_text

    def logcat_clear(self, target):
        self.clear_calls.append(target)
        if self.clear_hata is not None:
            raise self.clear_hata


class _Cekirdek(QObject):
    connection_changed = Signal(bool, object)

    def __init__(self):
        super().__init__()
        self.connected = True
        self.target = 'tv-1'
        self.engine = _Motor()


class _Pencere:
    def __init__(self):
        self._connection_busy = False
        self.isler = []

    def _run(self, worker, desc=None):
        self.isler.append((worker, desc))


@pytest.fixture
def tab(qtbot):
    core = _Cekirdek()
    win = _Pencere()
    t = LogcatTab(core, win)
    qtbot.addWidget(t)
    return t, core, win


def test_dedup_new_lines():
    assert dedup_new_lines([], ['a', 'b']) == ['a', 'b']
    assert dedup_new_lines(['a', 'b', 'c'], ['b', 'c', 'd']) == ['d']
    assert dedup_new_lines(['x', 'a', 'b'], ['a', 'b', 'c']) == ['c']
    assert dedup_new_lines(['a', 'b'], ['a', 'b']) == []
    assert dedup_new_lines(['p', 'q', 'a', 'b'], ['a', 'b']) == []
    assert dedup_new_lines(['x'], ['a', 'b']) == ['a', 'b']
    assert dedup_new_lines(['a'], []) == []
    assert dedup_new_lines([], []) == []


def test_kurulum_ogeleri(tab):
    t, _core, _win = tab

    assert t.cmb_level.count() == 6
    assert t.cmb_level.currentIndex() == 2
    assert t.cmb_level.accessibleName() == 'Log seviyesi'
    assert t.txt_tag.minimumWidth() == 180
    assert t.btn_start.text() == 'Başlat'
    assert t.btn_start.property('accent') is True
    assert t.chk_follow.isChecked() is True
    assert t.txt_log.isReadOnly() is True
    assert t.txt_log.maximumBlockCount() == 3000
    assert t.txt_log.styleSheet() == kit.mono_style()
    assert t.lbl_count.text() == '0 / 0 kayıt'
    assert t.btn_copy.isEnabled() is False
    assert t.btn_save.isEnabled() is False
    assert t._source_filter_key == ('I', '')
    assert t._level_colors == logcat_colors_for(kit.dark_from(t))
    assert LEVEL_COLORS['F'] == '#ff0000'


def test_level_eslemesi(tab):
    t, _core, _win = tab

    for idx, beklenen in enumerate([None, 'D', 'I', 'W', 'E', 'F']):
        t.cmb_level.setCurrentIndex(idx)
        assert t._level() == beklenen


def test_kaynak_filtresi_degisimi(tab):
    t, _core, win = tab

    t.cmb_level.setCurrentIndex(5)
    assert t._source_filter_key == ('F', '')
    assert t.lbl_status.text() == 'Log ekranı temizlendi.'
    assert win.isler == []

    t._source_filters_changed()  # ayni anahtar: erken donus
    assert t._source_filter_key == ('F', '')

    t._timer.start(3000)
    t.txt_tag.setText('AndroidRuntime')
    t.txt_tag.editingFinished.emit()
    assert t._source_filter_key == ('F', 'AndroidRuntime')
    assert t.lbl_status.text() == 'Kaynak filtresi değişti; yeni kayıtlar bekleniyor…'
    assert len(win.isler) == 1
    assert win.isler[0][0].job_name == 'Logcat okuma'
    t._timer.stop()


def test_toggle_kapilari(tab, monkeypatch):
    t, core, win = tab

    t._clear_busy = True
    t._toggle()
    assert t.lbl_status.text() == ('Cihaz günlüğü temizleniyor; '
                                   'tamamlanınca yeniden başlatın.')
    t._clear_busy = False

    win._connection_busy = True
    t._toggle()
    assert t.lbl_status.text() == ('Bağlantı işlemi sürüyor; '
                                   'tamamlanınca Başlat’a basın.')
    win._connection_busy = False

    bilgi = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgi.append(a))
    core.connected = False
    t._toggle()
    assert bilgi[0][1] == 'Logcat'
    assert bilgi[0][2].startswith('Bağlı cihaz yok.')
    assert t._timer.isActive() is False
    assert win.isler == []

    core.connected = True
    t._toggle()
    assert t._timer.isActive() is True
    assert t.btn_start.text() == 'Durdur'
    assert t.lbl_status.text() == 'Canlı izleniyor...'
    assert len(win.isler) == 1

    t._toggle()
    assert t._timer.isActive() is False
    assert t.btn_start.text() == 'Başlat'
    assert t.lbl_status.text() == 'Durduruldu.'
    assert t._poll_active_request is None


def test_poll_kapilari_ve_basari(tab):
    t, core, win = tab

    t._poll()  # zamanlayici kapali
    assert win.isler == []

    t._timer.start(3000)
    core.connected = False
    t._poll()
    assert win.isler == []
    core.connected = True
    core.target = ''
    t._poll()
    assert win.isler == []
    core.target = 'tv-1'
    win._connection_busy = True
    t._poll()
    assert win.isler == []
    win._connection_busy = False

    t._poll()
    assert len(win.isler) == 1
    isci = win.isler[-1][0]
    assert isci.job_name == 'Logcat okuma'
    assert win.isler[-1][1] is None
    t._poll()  # aktif istek varken yeni yoklama yok
    assert len(win.isler) == 1

    core.engine.dump_text = 'I/bir\nI/iki'
    isci.run()
    assert core.engine.dump_calls[-1] == ('tv-1', 120, 'I', None)
    assert list(t._lines) == ['I/bir', 'I/iki']
    assert t.lbl_status.text() == ('Canlı izleniyor · 3 saniyede bir yenilenir.')
    assert t._poll_active_request is None
    t._timer.stop()


def test_poll_basarisiz_dallari(tab):
    t, core, win = tab
    t._timer.start(3000)

    t._poll()
    isci = win.isler[-1][0]
    t._poll_generation += 1
    core.engine.dump_text = 'I/gec'
    isci.run()
    assert list(t._lines) == []

    t._poll()
    isci = win.isler[-1][0]
    core.engine.dump_hata = RuntimeError('patladi')
    isci.run()
    assert t.lbl_status.text() == 'Logcat okunamadı: RuntimeError: patladi'
    assert t._timer.isActive() is False
    assert t.btn_start.text() == 'Yeniden Başlat'

    t._timer.start(3000)
    t._poll()
    isci = win.isler[-1][0]
    t._poll_generation += 1
    core.engine.dump_hata = RuntimeError('gec')
    onceki = t.lbl_status.text()
    isci.run()
    assert t.lbl_status.text() == onceki

    core.engine.dump_hata = None
    t._timer.start(3000)
    t._poll()
    isci = win.isler[-1][0]
    t._toggle()  # durdur: aktif istek sifirlanir
    durum = t.lbl_status.text()
    core.engine.dump_text = 'I/yeni'
    isci.run()  # done: eski istek yok sayilir
    assert t.lbl_status.text() == durum
    assert list(t._lines) == []

    t._timer.start(3000)
    t._poll()
    isci = win.isler[-1][0]
    t._toggle()  # aktif istek None olur
    durum = t.lbl_status.text()
    core.engine.dump_hata = RuntimeError('sessiz')
    isci.run()  # failed: eski istek yok sayilir
    assert t.lbl_status.text() == durum

    core.engine.dump_hata = None
    t._timer.start(3000)
    t._poll()
    isci = win.isler[-1][0]
    t._timer.stop()
    durum = t.lbl_status.text()
    core.engine.dump_hata = RuntimeError('sessiz2')
    isci.run()  # failed: zamanlayici kapali, durum degismez
    assert t.lbl_status.text() == durum


def test_append_ve_duraklatma(tab):
    t, _core, _win = tab

    t._append('   ')
    assert list(t._lines) == []

    t._append('I/bir\nI/iki')
    assert list(t._lines) == ['I/bir', 'I/iki']
    assert t.lbl_count.text() == '2 / 2 kayıt'

    t._append('I/iki\nI/uc')
    assert list(t._lines) == ['I/bir', 'I/iki', 'I/uc']
    assert t._prev_lines == ['I/iki', 'I/uc']

    t._append('I/iki\nI/uc')  # tamamen tekrar: yeni satir yok
    assert list(t._lines) == ['I/bir', 'I/iki', 'I/uc']

    t.txt_search.setText('yok-boyle')
    t._render_lines()
    t.chk_follow.setChecked(False)
    t._append('I/dort')
    assert list(t._lines) == ['I/bir', 'I/iki', 'I/uc', 'I/dort']
    assert t.lbl_count.text() == '4 kayıt · görünüm duraklatıldı'

    t.txt_search.setText('')
    t.chk_follow.setChecked(True)
    assert t.lbl_count.text() == '4 / 4 kayıt'


def test_render_filtre_ve_renkler(tab):
    t, _core, _win = tab
    t._lines.extend(['E/bir hata', 'I/kısıt bilgisi', 'bagimsiz satir'])
    satirlar = ['V/a', 'D/b', 'I/c', 'W/d', 'E/e', 'F/f']
    t._lines.extend(satirlar)

    t._render_lines()
    assert t.lbl_count.text() == '9 / 9 kayıt'
    assert t.btn_copy.isEnabled() is True

    html = t.txt_log.document().toHtml()
    assert 'color:{};'.format(t._level_colors['E']) in html
    assert 'color:{};'.format(kit.colors(t)['text']) in html

    t.txt_search.setText('kisit')
    t._render_lines()
    assert t.lbl_count.text() == '1 / 9 kayıt'

    t.txt_search.setText('hata yok')
    t._render_lines()
    assert t.lbl_count.text() == '0 / 9 kayıt'
    assert t.btn_copy.isEnabled() is False
    assert t.btn_save.isEnabled() is False

    t.txt_search.setText('')
    t.chk_follow.setChecked(True)
    t._render_lines()
    assert t.txt_log.textCursor().position() == len(t.txt_log.toPlainText())

    t._lines.append('I/<b>&</b>')
    t._render_lines()
    assert '<b>&</b>' in t.txt_log.toPlainText()


def test_esc_kacislari():
    assert LogcatTab._esc('a&b<c>d') == 'a&amp;b&lt;c&gt;d'


def test_kopyala(tab):
    t, _core, _win = tab
    t._lines.append('I/veri')
    t._render_lines()

    t._copy_visible()

    assert QApplication.clipboard().text() == t.txt_log.toPlainText()
    assert t.lbl_status.text() == 'Görünen cihaz kayıtları kopyalandı.'


def test_kaydet(tab, monkeypatch, tmp_path):
    t, _core, _win = tab
    t._lines.append('I/veri')
    t._render_lines()

    dosya = tmp_path / 'logcat.txt'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *a, **k: (str(dosya), ''))
    bilgi = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgi.append(a))
    t._save()
    assert dosya.read_text(encoding='utf-8') == t.txt_log.toPlainText()
    assert bilgi[0][1] == 'Tamam'
    assert bilgi[0][2] == 'Kaydedildi:\n' + str(dosya)

    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *a, **k: ('', ''))
    t._save()  # iptal: sessiz

    hatalar = []
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: hatalar.append(a))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *a, **k: (str(tmp_path), ''))
    t._save()
    assert hatalar[0][1] == 'Hata'


def test_crash_kapilari(tab, monkeypatch):
    t, core, win = tab

    t._clear_busy = True
    t._crash()
    assert t.lbl_status.text() == 'Cihaz günlüğünün temizlenmesini bekleyin.'
    t._clear_busy = False

    win._connection_busy = True
    t._crash()
    assert t.lbl_status.text() == ('Bağlantı işlemi sürüyor; '
                                   'tamamlanınca yeniden deneyin.')
    win._connection_busy = False

    bilgi = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgi.append(a))
    core.connected = False
    t._crash()
    assert bilgi[0][1] == 'Çökme Avcısı'
    assert bilgi[0][2].startswith('Bağlı cihaz yok.')
    assert win.isler == []


def test_crash_akisi_ve_eski_nesil(tab, monkeypatch):
    t, core, win = tab
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: None)

    t._crash()
    isci, desc = win.isler[-1]
    assert isci.job_name == 'Cokme avcisi'
    assert desc == 'Logcat: cokme izleri araniyor'
    assert t._crash_generation == 1

    core.engine.crash_text = ''
    isci.run()
    assert t.lbl_status.text() != 'Son çökme izleri gösteriliyor.'

    core.engine.crash_text = 'F/cokme\nE/iz'
    t._crash()
    isci = win.isler[-1][0]
    isci.run()
    assert core.engine.crash_calls[-1] == 'tv-1'
    assert list(t._lines) == ['F/cokme', 'E/iz']
    assert t.lbl_status.text() == 'Son çökme izleri gösteriliyor.'

    t._crash()
    isci = win.isler[-1][0]
    t._crash_generation += 1
    durum = t.lbl_status.text()
    isci.run()
    assert t.lbl_status.text() == durum

    core.engine.crash_hata = RuntimeError('iz yok')
    t._crash()
    isci = win.isler[-1][0]
    isci.run()
    assert t.lbl_status.text() == 'Çökme kayıtları okunamadı: RuntimeError: iz yok'

    t._crash()
    isci = win.isler[-1][0]
    t._poll_generation += 1
    durum = t.lbl_status.text()
    isci.run()
    assert t.lbl_status.text() == durum

    core.engine.crash_hata = None
    t._toggle()
    assert t._timer.isActive() is True
    t._crash()
    isci = win.isler[-1][0]
    isci.run()
    assert t._timer.isActive() is False
    assert t.btn_start.text() == 'Başlat'
    assert t.lbl_status.text() == 'Son çökme izleri gösteriliyor.'


def test_clear_screen(tab):
    t, _core, _win = tab
    t._lines.append('I/x')
    t._prev_lines = ['I/x']
    nesil = t._poll_generation

    t._clear_screen()

    assert list(t._lines) == []
    assert t._prev_lines == []
    assert t._poll_generation == nesil + 1
    assert t._poll_active_request is None
    assert t.lbl_count.text() == '0 / 0 kayıt'
    assert t.lbl_status.text() == 'Log ekranı temizlendi.'


def test_clear_device_kapilari_ve_akisi(tab, monkeypatch):
    t, core, win = tab

    t._clear_busy = True
    t._clear_device()
    assert win.isler == []
    t._clear_busy = False

    core.connected = False
    t._clear_device()
    assert t.lbl_status.text() == ('Cihaz günlüğünü temizlemek için '
                                   'bağlantının hazır olmasını bekleyin.')
    core.connected = True

    cevaplar = [QMessageBox.No]
    sorular = []

    def soru(*args, **kwargs):
        sorular.append(args)
        return cevaplar[-1]

    monkeypatch.setattr(QMessageBox, 'question', soru)

    t._clear_device()
    assert win.isler == []
    assert sorular[0][1] == 'Cihaz günlüğünü temizle'
    assert sorular[0][2].startswith('TV’nin günlük tamponu silinecek.')

    cevaplar[-1] = QMessageBox.Yes

    def cevapla_hedefi_degistir(*args, **kwargs):
        core.target = 'baska-cihaz'
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, 'question', cevapla_hedefi_degistir)
    t._clear_device()
    assert win.isler == []
    assert t.lbl_status.text() == 'Bağlantı değişti; cihaz günlüğü temizlenmedi.'
    core.target = 'tv-1'

    monkeypatch.setattr(QMessageBox, 'question', soru)
    t._timer.start(3000)
    t._clear_device()

    assert t._timer.isActive() is False
    assert t.btn_start.text() == 'Başlat'
    assert t._clear_busy is True
    assert t.btn_start.isEnabled() is False
    assert t.btn_clear_dev.isEnabled() is False
    assert t.lbl_status.text() == 'Cihaz günlüğü temizleniyor…'
    isci, desc = win.isler[-1]
    assert isci.job_name == 'Logcat temizleme'
    assert desc == 'Logcat: cihaz tamponu temizleniyor'

    isci.run()
    assert core.engine.clear_calls[-1] == 'tv-1'
    assert t._clear_busy is False
    assert t.btn_start.isEnabled() is True
    assert t.lbl_status.text() == 'Cihaz log tamponu ve ekran temizlendi.'

    core.engine.clear_hata = RuntimeError('silinemedi')
    t._clear_device()
    isci = win.isler[-1][0]
    isci.run()
    assert t.lbl_status.text() == ('Cihaz günlüğü temizlenemedi: '
                                   'RuntimeError: silinemedi')

    core.engine.clear_hata = None
    t._clear_device()
    isci = win.isler[-1][0]
    t._poll_generation += 1
    isci.run()
    assert t._clear_busy is False


def test_baglanti_degisimi(tab):
    t, core, _win = tab
    t._toggle()
    assert t._timer.isActive() is True

    core.connection_changed.emit(True, 'tv-1')

    assert t._timer.isActive() is False
    assert t.btn_start.text() == 'Başlat'
    assert t._prev_lines == []
    assert t._poll_active_request is None
    assert t.lbl_status.text() == (
        'Cihaz bağlantısı değişti; canlı izleme durduruldu.')

    core.connection_changed.emit(False, None)
    assert t.lbl_status.text() == (
        'Cihaz bağlantısı kesildi; canlı izleme durduruldu.')


def test_apply_theme_ve_hata_yutma(tab, monkeypatch):
    t, _core, _win = tab
    t._lines.append('I/x')

    t.apply_theme()
    assert t._level_colors == logcat_colors_for(kit.dark_from(t))
    assert t.txt_log.styleSheet() == kit.mono_style()

    def patla():
        raise RuntimeError('stil yok')

    monkeypatch.setattr(kit, 'mono_style', patla)
    t.apply_theme()  # hata sizmamali
