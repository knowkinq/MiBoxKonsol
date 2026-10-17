# -*- coding: utf-8 -*-
"""terminal_tab: komut kapisi, worker akisi, cikti bicimleme ve gecmis."""
import pytest
from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMessageBox,
    QPushButton,
)

from mibox_app.ui.terminal_tab import TerminalTab
from mibox_app.workers import CancelledError


class _Sonuc:
    def __init__(self, output='', error='', exit_code=0):
        self.output = output
        self.error = error
        self.exit_code = exit_code


class _SonucEski:
    def __init__(self, returncode):
        self.output = ''
        self.error = ''
        self.returncode = returncode


class _Motor:
    def __init__(self):
        self.cagrilar = []
        self.sonuc = _Sonuc()
        self.hata = None

    def shell(self, target, cmd, timeout=None, preserve_output_whitespace=False,
              hide_from_trace=False, cancel_check=None):
        self.cagrilar.append((target, cmd, timeout, preserve_output_whitespace,
                              hide_from_trace, callable(cancel_check)))
        if self.hata is not None:
            raise self.hata
        return self.sonuc


class _Cekirdek(QObject):
    connection_changed = Signal(bool, object)

    def __init__(self):
        super().__init__()
        self.connected = True
        self.target = 'tv-1'
        self.engine = _Motor()


class _CizikCekirdek:
    """connection_changed'i olmayan cekirdek."""

    connected = True
    target = 'tv-1'

    def __init__(self):
        self.engine = _Motor()


class _Pencere:
    def __init__(self):
        self._connection_busy = False
        self.isler = []

    def _run(self, worker, **kwargs):
        self.isler.append(worker)


@pytest.fixture
def tab(qtbot):
    core = _Cekirdek()
    win = _Pencere()
    t = TerminalTab(core, win)
    qtbot.addWidget(t)
    return t, core, win


def _tus(tus, mod=Qt.NoModifier):
    return QKeyEvent(QEvent.KeyPress, tus, mod)


def _calistir(t, win, cmd):
    t.txt_cmd.setText(cmd)
    t._run_cmd()
    return win.isler[-1]


def test_kurulum_konsol_ve_onayarlar(tab):
    t, _core, _win = tab

    ipuclari = {b.toolTip() for b in t.findChildren(QPushButton) if b.toolTip()}
    assert ipuclari == {
        'dumpsys cpuinfo', 'dumpsys meminfo -s', 'df -h /data /sdcard',
        'dumpsys battery', 'wm size', 'ip route', 'getprop ro.product.model',
        'pm list packages -3', 'logcat -d -t 40', 'dumpsys wifi',
        'Terminal konsol geçmişini bir .txt dosyasına kaydeder',
    }
    assert t.txt_output.objectName() == 'terminalView'
    assert t.txt_output.isReadOnly() is True
    assert t.txt_output.maximumBlockCount() == 5000
    assert t.lbl_prompt.text() == 'adb shell $'
    assert 'MiBox Konsol — Gelişmiş ADB Shell Terminali' in t.txt_output.toPlainText()
    assert t.lbl_status.text().startswith('Hazır')
    assert t.btn_clear.text() == 'Temizle'
    assert t.btn_copy.text() == 'Kopyala'


def test_kurulum_baglantisiz_cekirdekle(qtbot):
    t = TerminalTab(_CizikCekirdek(), _Pencere())
    qtbot.addWidget(t)

    assert t._connection_generation == 0


def test_baglanti_sinyali_nesli_artirir(tab):
    t, core, _win = tab
    nesil = t._connection_generation

    core.connection_changed.emit(True, 'tv-1')
    assert t._connection_generation == nesil + 1

    t._busy = True
    core.connection_changed.emit(False, None)
    assert t.lbl_status.text() == (
        'Cihaz bağlantısı değişti; eski komut sonucu atlanacak.')


def test_target_is_current_kapilari(tab):
    t, core, win = tab
    nesil = t._connection_generation

    assert t._target_is_current(core.target, nesil) is True
    assert t._target_is_current(core.target, nesil + 1) is False
    core.connected = False
    assert t._target_is_current(core.target, nesil) is False
    core.connected = True
    assert t._target_is_current('baska', nesil) is False
    win._connection_busy = True
    assert t._target_is_current(core.target, nesil) is False


def test_onayar_dugmesi_busy_kilidi_ve_calistirma(tab):
    t, core, win = tab
    dugme = next(b for b in t.findChildren(QPushButton)
                 if b.toolTip() == 'wm size')

    dugme.click()
    assert len(win.isler) == 1
    assert 'wm size' in t.txt_output.toPlainText()
    assert t._busy is True
    assert t.btn_run.isEnabled() is False

    t._busy = True
    dugme.click()
    assert t.lbl_status.text() == 'Önce çalışan komutun tamamlanmasını bekleyin.'

    win.isler[0].run()
    assert t._busy is False
    assert t.btn_run.isEnabled() is True
    assert core.engine.cagrilar[-1][1] == 'wm size'


def test_run_cmd_kapilari(tab, monkeypatch):
    t, core, win = tab

    t._busy = True
    t.txt_cmd.setText('getprop')
    t._run_cmd()
    assert win.isler == []
    t._busy = False

    win._connection_busy = True
    t._run_cmd()
    assert t.lbl_status.text() == (
        'Bağlantı işlemi sürüyor; tamamlanınca yeniden deneyin.')
    win._connection_busy = False

    onceki = t.lbl_status.text()
    t.txt_cmd.setText('   ')
    t._run_cmd()
    assert t.lbl_status.text() == onceki

    core.connected = False
    t.txt_cmd.setText('getprop')
    t._run_cmd()
    assert t.lbl_status.text() == 'Önce bir TV cihazına bağlanın.'

    core.connected = True
    core.target = ''
    t._run_cmd()
    assert t.lbl_status.text() == 'Önce bir TV cihazına bağlanın.'
    core.target = 'tv-1'

    uyarilar = []
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: uyarilar.append(a))
    t.txt_cmd.setText('rm -rf /')
    t._run_cmd()
    assert win.isler == []
    assert uyarilar[0][1] == 'Komut engellendi'
    assert 'Komut: rm -rf /' in uyarilar[0][2]


def test_onay_sorulari_ve_hedef_kapisi(tab, monkeypatch):
    t, core, win = tab
    sorular = []

    def reddet(*args, **kwargs):
        sorular.append(args)
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, 'question', reddet)
    t.txt_cmd.setText('am force-stop com.x')
    t._run_cmd()
    assert win.isler == []
    assert t.lbl_status.text() == 'Komut iptal edildi.'
    assert sorular[0][1] == 'Komut onayı'
    assert 'am force-stop com.x' in sorular[0][2]

    def onayla_hedefi_degistir(*args, **kwargs):
        core.target = 'baska-cihaz'
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, 'question', onayla_hedefi_degistir)
    t.txt_cmd.setText('wm density 320')
    t._run_cmd()
    assert win.isler == []
    assert t.lbl_status.text() == (
        'Hedef veya bağlantı değişti; komut çalıştırılmadı.')
    core.target = 'tv-1'

    monkeypatch.setattr(QMessageBox, 'question',
                        lambda *a, **k: QMessageBox.Yes)
    t.txt_cmd.setText('settings put global x 1')
    t._run_cmd()
    assert len(win.isler) == 1
    assert t._busy is True


def test_gecmis_kaydi_ve_tekrar_engeli(tab):
    t, _core, win = tab

    _calistir(t, win, 'getprop')
    assert t._history == ['getprop']
    assert t._history_idx == 1
    assert t._history_draft == ''
    assert t.txt_cmd.text() == ''
    assert t.lbl_status.text() == 'Komut çalıştırılıyor...'
    win.isler[-1].run()  # mesguliyeti temizle

    _calistir(t, win, 'getprop')
    assert t._history == ['getprop']
    win.isler[-1].run()

    t._history = ['c{}'.format(i) for i in range(100)]
    _calistir(t, win, 'ls /sdcard')
    assert len(t._history) == 100
    assert t._history[-1] == 'ls /sdcard'
    win.isler[-1].run()


def test_worker_basarili_akis(tab):
    t, core, win = tab
    motor = core.engine

    isci = _calistir(t, win, 'getprop')
    isci.run()

    assert motor.cagrilar[-1] == ('tv-1', 'getprop', 30, True, True, True)
    assert '(Çıktı yok — Kod: 0)' in t.txt_output.toPlainText()
    assert t.lbl_status.text() == 'Tamamlandı (Kod: 0)'
    assert t._busy is False

    motor.sonuc = _Sonuc(output='merhaba \x1b[31mDÜNYA\x1b[0m', error='uyarı')
    isci = _calistir(t, win, 'dumpsys battery')
    isci.run()

    duz = t.txt_output.toPlainText()
    assert 'merhaba DÜNYA' in duz
    assert '[HATA] uyarı' in duz
    assert t.lbl_status.text() == 'Tamamlandı (Kod: 0)'

    motor.sonuc = _Sonuc(exit_code=3)
    _calistir(t, win, 'df -h').run()
    assert '(Çıktı yok — Kod: 3)' in t.txt_output.toPlainText()
    assert t.lbl_status.text() == 'Hata kodu ile bitti (Kod: 3)'

    motor.sonuc = _SonucEski(returncode=5)
    _calistir(t, win, 'uptime').run()
    assert '(Çıktı yok — Kod: 5)' in t.txt_output.toPlainText()


def test_worker_eski_hedef_ve_hata_yollari(tab):
    t, core, win = tab
    motor = core.engine

    isci = _calistir(t, win, 'getprop')
    core.target = 'yeni-cihaz'
    isci.run()
    assert t.lbl_status.text() == (
        'Hedef değişti; eski cihazın komut çıktısı gösterilmedi.')
    core.target = 'tv-1'

    motor.hata = RuntimeError('patladi')
    _calistir(t, win, 'ls /sdcard').run()
    assert '[BAŞARISIZ] RuntimeError: patladi' in t.txt_output.toPlainText()
    assert t.lbl_status.text() == 'Hata: RuntimeError: patladi'

    motor.hata = RuntimeError('gec hata')
    isci = _calistir(t, win, 'uptime')
    core.target = 'yeni-cihaz'
    isci.run()
    assert t.lbl_status.text() == (
        'Hedef değişti; eski cihazın komut hatası gösterilmedi.')
    core.target = 'tv-1'

    motor.hata = CancelledError('x')
    _calistir(t, win, 'getprop').run()
    assert t.lbl_status.text() == 'Komut durduruldu.'

    isci = _calistir(t, win, 'getprop')
    isci.failed.emit('kullanici durdurdu')
    assert t.lbl_status.text() == 'Komut durduruldu.'


def test_format_terminal_cikti_temizleme():
    assert TerminalTab._format_terminal_output('') == ''
    assert TerminalTab._format_terminal_output(None) == ''

    cikti = TerminalTab._format_terminal_output('a\x1b[2Jb\x1b[Hc\x1b[?25ld')
    assert 'abcd' in cikti
    assert '\x1b' not in cikti

    satirlar = TerminalTab._format_terminal_output('x\r\ny\rz\n\n\n\nw')
    assert 'x\nyz\n\nw' in satirlar


def test_format_terminal_cikti_renkleri():
    koyu = TerminalTab._format_terminal_output('\x1b[31mK\x1b[0mS', dark=True)
    assert '<span style="color: #f87171;">' in koyu
    assert koyu.count('</span>') == koyu.count('<span') == 1
    assert koyu.endswith('</pre>')

    acik = TerminalTab._format_terminal_output('\x1b[31mK', dark=False)
    assert '#1e293b' in acik
    assert acik.count('</span>') == acik.count('<span') == 1

    vurgu = TerminalTab._format_terminal_output('\x1b[1mA\x1b[7mB\x1b[0mC')
    assert vurgu.count('<span') == 2
    assert vurgu.count('</span>') == 2
    assert 'font-weight: bold' in vurgu

    bos_reset = TerminalTab._format_terminal_output('\x1b[32mX\x1b[mY')
    assert bos_reset.count('<span') == 1
    assert bos_reset.count('</span>') == 1

    bilinmeyen = TerminalTab._format_terminal_output('\x1b[99mZ')
    assert '<span' not in bilinmeyen

    kacis = TerminalTab._format_terminal_output('<tag> & "x"')
    assert '&lt;tag&gt; &amp;' in kacis


def test_kopyala_davranisi(tab):
    t, _core, _win = tab
    t.txt_output.clear()

    onceki = t.lbl_status.text()
    t._copy_output()
    assert t.lbl_status.text() == onceki

    t.txt_output.appendPlainText('satır 1')
    t._copy_output()
    assert t.lbl_status.text() == 'Terminal çıktısı panoya kopyalandı.'
    assert QApplication.clipboard().text() == t.txt_output.toPlainText()


def test_kaydet_davranislari(tab, monkeypatch, tmp_path):
    t, _core, _win = tab
    t.txt_output.clear()

    bilgi = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgi.append(a))
    t._save_output()
    assert bilgi[0][1] == 'Boş Terminal'

    t.txt_output.appendPlainText('satır-1')
    dosya = tmp_path / 'log.txt'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *a, **k: (str(dosya), ''))
    t._save_output()
    assert dosya.read_text(encoding='utf-8') == t.txt_output.toPlainText()
    assert t.lbl_status.text() == 'Terminal günlüğü kaydedildi: {}'.format(dosya)

    t.lbl_status.setText('once')
    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *a, **k: ('', ''))
    t._save_output()
    assert t.lbl_status.text() == 'once'

    hatalar = []
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: hatalar.append(a))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *a, **k: (str(tmp_path), ''))
    t._save_output()
    assert hatalar[0][1] == 'Hata'


def test_event_filter_gecmis_gezinme(tab):
    t, _core, _win = tab

    assert t.eventFilter(t.txt_cmd, _tus(Qt.Key_Up)) is False

    t._history = ['bir', 'iki']
    t._history_idx = 2
    t.txt_cmd.setText('taslak')

    assert t.eventFilter(t.txt_cmd, _tus(Qt.Key_Up)) is True
    assert t._history_draft == 'taslak'
    assert t.txt_cmd.text() == 'iki'
    assert t.txt_cmd.cursorPosition() == 3

    t.eventFilter(t.txt_cmd, _tus(Qt.Key_Up))
    assert t.txt_cmd.text() == 'bir'
    t.eventFilter(t.txt_cmd, _tus(Qt.Key_Up))
    assert t.txt_cmd.text() == 'bir'
    assert t._history_idx == 0

    t.eventFilter(t.txt_cmd, _tus(Qt.Key_Down))
    assert t.txt_cmd.text() == 'iki'
    t.eventFilter(t.txt_cmd, _tus(Qt.Key_Down))
    assert t.txt_cmd.text() == 'taslak'
    t.eventFilter(t.txt_cmd, _tus(Qt.Key_Down))
    assert t.txt_cmd.text() == 'taslak'

    assert t.eventFilter(t.txt_cmd, _tus(Qt.Key_Up, Qt.ControlModifier)) is False
    assert t.eventFilter(t.txt_output, _tus(Qt.Key_Up)) is False
    assert t.eventFilter(t.txt_cmd, QEvent(QEvent.FocusIn)) is False