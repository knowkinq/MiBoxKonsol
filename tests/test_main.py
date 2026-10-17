# -*- coding: utf-8 -*-
"""Giris noktasi testleri: bilgi ciktisi, paket importu, selftest kapanisi,
log temizligi, crash tuzaklari ve CLI dagitimi.

Agir Qt nesneleri kurulmaz: run() testleri sahte QApplication/MainWindow
kullanir; crash trap testleri gercek PySide6 mesaj yakalayicisini gecici
olarak degistirip temizlikte geri koyar.
"""
import atexit
import builtins
import faulthandler
import importlib.util
import os
import sys
import time

from mibox_app import config, diagnostics
from mibox_app import main as main_mod


def _script_modul():
    """main.py'yi paketsiz (script) mod olarak yukler; relative import
    basarisiz olur ve fallback yollari devreye girer."""
    path = os.path.join(os.path.dirname(main_mod.__file__), 'main.py')
    spec = importlib.util.spec_from_file_location('mibox_main_script', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- _print_info --------------------------------------------------------------

def test_print_info_stdout(capsys):
    main_mod._print_info()
    out = capsys.readouterr().out.replace('\r\n', '\n')
    assert out == diagnostics.metin() + '\n'


def test_print_info_dosyaya_yazar(tmp_path):
    hedef = tmp_path / 'bilgi.txt'
    main_mod._print_info(str(hedef))
    assert hedef.read_text(encoding='utf-8') == diagnostics.metin() + '\n'


def test_print_info_stdout_yok(monkeypatch):
    monkeypatch.setattr(sys, 'stdout', None)
    assert main_mod._print_info() is None


class _KirilganAkis:
    """reconfigure patlar; ilk write UnicodeEncodeError firlatir."""

    def __init__(self):
        self.encoding = 'ascii'
        self.yazilan = []
        self.hata_verildi = False

    def reconfigure(self, **kwargs):
        raise OSError('reconfigure yok')

    def write(self, s):
        if not self.hata_verildi:
            self.hata_verildi = True
            raise UnicodeEncodeError('ascii', s, 0, 1, 'olamaz')
        self.yazilan.append(s)
        return len(s)


def test_print_info_unicode_yedegi(monkeypatch):
    akis = _KirilganAkis()
    monkeypatch.setattr(sys, 'stdout', akis)
    main_mod._print_info()
    beklenen = diagnostics.metin().encode('ascii', 'backslashreplace')
    assert ''.join(akis.yazilan) == beklenen.decode('ascii') + '\n'


def test_print_info_script_yedegi(tmp_path, monkeypatch):
    mod = _script_modul()
    kok = os.path.dirname(os.path.dirname(os.path.abspath(mod.__file__)))
    monkeypatch.setattr(sys, 'path', [p for p in sys.path if p != kok])
    hedef = tmp_path / 'bilgi.txt'
    mod._print_info(str(hedef))
    assert hedef.read_text(encoding='utf-8') == diagnostics.metin() + '\n'


# --- _import_pkg --------------------------------------------------------------

def test_import_pkg_relative():
    Core, MainWindow = main_mod._import_pkg()
    assert Core.__name__ == 'Core'
    assert MainWindow.__name__ == 'MainWindow'


def test_import_pkg_script_yedegi(monkeypatch):
    mod = _script_modul()
    kok = os.path.dirname(os.path.dirname(os.path.abspath(mod.__file__)))
    monkeypatch.setattr(sys, 'path', [p for p in sys.path if p != kok])
    Core, MainWindow = mod._import_pkg()
    assert Core.__name__ == 'Core'
    assert MainWindow.__name__ == 'MainWindow'


# --- _selftest_path -----------------------------------------------------------

def test_selftest_path_normal():
    kok = os.path.dirname(os.path.dirname(os.path.abspath(main_mod.__file__)))
    assert main_mod._selftest_path() == os.path.join(
        kok, 'mibox-selftest-ok.txt')


def test_selftest_path_frozen(monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', r'C:\uygulama\MiBoxKonsol.exe')
    assert main_mod._selftest_path() == (
        r'C:\uygulama\mibox-selftest-ok.txt')


# --- _shutdown_selftest_window ------------------------------------------------

class _SahteWorker:
    def __init__(self, calisiyor=True, bekleme=True, iptal_patlar=False,
                 iptal_etkisiz=False):
        self.calisiyor = calisiyor
        self.bekleme = bekleme
        self.iptal_patlar = iptal_patlar
        self.iptal_etkisiz = iptal_etkisiz
        self.cancel_cagrildi = False

    def isRunning(self):
        return self.calisiyor

    def cancel(self):
        self.cancel_cagrildi = True
        if self.iptal_patlar:
            raise RuntimeError('iptal edilemedi')
        if not self.iptal_etkisiz:
            self.calisiyor = False

    def wait(self):
        return self.bekleme


class _InterruptWorker:
    def __init__(self):
        self.calisiyor = True
        self.interrupt_cagrildi = False

    def isRunning(self):
        return self.calisiyor

    def requestInterruption(self):
        self.interrupt_cagrildi = True
        self.calisiyor = False

    def wait(self):
        return True


class _WaitPatlakWorker(_SahteWorker):
    """Ilk dongude iptal etkisiz kalir; wait() RuntimeError atar."""

    def __init__(self):
        super().__init__(iptal_etkisiz=True)

    def wait(self):
        raise RuntimeError('beklenemez')


class _SahteApp:
    def __init__(self):
        self.process_events_sayaci = 0

    def processEvents(self):
        self.process_events_sayaci += 1


class _SahtePencere:
    def __init__(self, workers=(), kapanir=True, kapaniyor=True):
        self._workers = list(workers)
        self._kapanir = kapanir
        self._closing = kapaniyor
        self.close_sayaci = 0

    def close(self):
        self.close_sayaci += 1
        return self._kapanir


class _WorkersizPencere:
    _closing = True

    def close(self):
        return True


def test_shutdown_selftest_temiz_kapanis():
    worker = _SahteWorker()
    win = _SahtePencere([worker])
    app = _SahteApp()
    assert main_mod._shutdown_selftest_window(win, app) is True
    assert worker.cancel_cagrildi
    assert app.process_events_sayaci == 2
    assert win.close_sayaci == 1


def test_shutdown_selftest_interrupt_yolu():
    worker = _InterruptWorker()
    win = _SahtePencere([worker])
    assert main_mod._shutdown_selftest_window(win, _SahteApp()) is True
    assert worker.interrupt_cagrildi


def test_shutdown_selftest_iptal_patlarsa_calisirsa_false():
    worker = _SahteWorker(iptal_patlar=True)
    win = _SahtePencere([worker])
    assert main_mod._shutdown_selftest_window(win, _SahteApp()) is False


def test_shutdown_selftest_wait_false():
    worker = _SahteWorker(bekleme=False, iptal_etkisiz=True)
    win = _SahtePencere([worker])
    assert main_mod._shutdown_selftest_window(win, _SahteApp()) is False


def test_shutdown_selftest_wait_patlarsa_false():
    worker = _WaitPatlakWorker()
    win = _SahtePencere([worker])
    assert main_mod._shutdown_selftest_window(win, _SahteApp()) is False


def test_shutdown_selftest_close_false():
    win = _SahtePencere([], kapanir=False)
    assert main_mod._shutdown_selftest_window(win, _SahteApp()) is False


def test_shutdown_selftest_closing_false():
    win = _SahtePencere([], kapaniyor=False)
    assert main_mod._shutdown_selftest_window(win, _SahteApp()) is False


def test_shutdown_selftest_workers_yok():
    assert main_mod._shutdown_selftest_window(
        _WorkersizPencere(), _SahteApp()) is True


# --- _prune_empty_crash_logs --------------------------------------------------

def test_prune_empty_crash_logs_dizin_yok(tmp_path):
    assert main_mod._prune_empty_crash_logs(str(tmp_path / 'yok')) is None


def test_prune_empty_crash_logs_icerik_filtreleri(tmp_path):
    bos = tmp_path / 'crash-20240101-000000-000000-1.log'
    bos.write_text('crash traps aktif\n', encoding='utf-8')
    gurultu = tmp_path / 'crash-20240102-000000-000000-2.log'
    gurultu.write_text(
        'crash traps aktif\n'
        'Cannot find font directory /x\n'
        'Qt no longer ships fonts\n'
        '[QT 1] kritik ama sayilmaz\n', encoding='utf-8')
    anlamli = tmp_path / 'crash-20240103-000000-000000-3.log'
    anlamli.write_text(
        'crash traps aktif\n--- UNCAUGHT 12:00:00 ---\n', encoding='utf-8')
    digeri = tmp_path / 'baska.log'
    digeri.write_text('x', encoding='utf-8')
    dizin = tmp_path / 'crash-20240104-000000-000000-4.log'
    dizin.mkdir()

    main_mod._prune_empty_crash_logs(str(tmp_path))

    assert not bos.exists()
    assert not gurultu.exists()
    assert anlamli.exists()
    assert digeri.exists()
    assert dizin.is_dir()


def test_prune_empty_crash_logs_keep_siniri(tmp_path):
    adlar = []
    for i in range(3):
        p = tmp_path / 'crash-2024010{}-000000-000000-{}.log'.format(i, i)
        p.write_text('--- gercek icerik {} ---\n'.format(i), encoding='utf-8')
        adlar.append(p)

    main_mod._prune_empty_crash_logs(str(tmp_path), keep=2)

    assert not adlar[0].exists()
    assert adlar[1].exists()
    assert adlar[2].exists()


def test_prune_empty_crash_logs_keep_silme_hatasi(tmp_path, monkeypatch):
    eski = tmp_path / 'crash-20240101-000000-000000-1.log'
    eski.write_text('--- anlamli eski ---\n', encoding='utf-8')
    yeni = tmp_path / 'crash-20240102-000000-000000-2.log'
    yeni.write_text('--- anlamli yeni ---\n', encoding='utf-8')

    def patlak_remove(path):
        raise OSError('silinemez')

    monkeypatch.setattr(os, 'remove', patlak_remove)
    main_mod._prune_empty_crash_logs(str(tmp_path), keep=1)

    assert eski.exists()
    assert yeni.exists()


def test_prune_empty_crash_logs_silme_hatasi(tmp_path, monkeypatch):
    p = tmp_path / 'crash-20240101-000000-000000-1.log'
    p.write_text('crash traps aktif\n', encoding='utf-8')

    def patlak_remove(path):
        raise OSError('silinemez')

    monkeypatch.setattr(os, 'remove', patlak_remove)
    main_mod._prune_empty_crash_logs(str(tmp_path))
    assert p.exists()


def test_prune_empty_crash_logs_ikinci_listeleme_hatasi(tmp_path, monkeypatch):
    (tmp_path / 'crash-20240101-000000-000000-1.log').write_text(
        '--- icerik ---\n', encoding='utf-8')
    gercek = os.listdir
    sayac = {'n': 0}

    def patlak(path):
        sayac['n'] += 1
        if sayac['n'] >= 2:
            raise OSError('liste yok')
        return gercek(path)

    monkeypatch.setattr(os, 'listdir', patlak)
    main_mod._prune_empty_crash_logs(str(tmp_path))


# --- _prune_old_runtime_logs --------------------------------------------------

def test_prune_old_runtime_logs_dizin_yok(tmp_path):
    assert main_mod._prune_old_runtime_logs(str(tmp_path / 'yok')) is None


def test_prune_old_runtime_logs_yas_filtresi(tmp_path):
    eski = tmp_path / 'mibox-20240101.log'
    eski.write_text('eski', encoding='utf-8')
    eski_scrcpy = tmp_path / 'scrcpy.log'
    eski_scrcpy.write_text('eski', encoding='utf-8')
    yeni = tmp_path / 'mibox-20990101.log'
    yeni.write_text('yeni', encoding='utf-8')
    gecersiz = tmp_path / 'mibox-2024010.log'
    gecersiz.write_text('gecersiz ad', encoding='utf-8')
    kullanici = tmp_path / 'history.jsonl'
    kullanici.write_text('{}', encoding='utf-8')
    eski_zaman = time.time() - 40 * 24 * 60 * 60
    os.utime(eski, (eski_zaman, eski_zaman))
    os.utime(eski_scrcpy, (eski_zaman, eski_zaman))

    main_mod._prune_old_runtime_logs(str(tmp_path))

    assert not eski.exists()
    assert not eski_scrcpy.exists()
    assert yeni.exists()
    assert gecersiz.exists()
    assert kullanici.exists()


def test_prune_old_runtime_logs_mtime_hatasi(tmp_path, monkeypatch):
    p = tmp_path / 'scrcpy.log'
    p.write_text('x', encoding='utf-8')

    def patlak(path):
        raise OSError('zaman yok')

    monkeypatch.setattr(os.path, 'getmtime', patlak)
    main_mod._prune_old_runtime_logs(str(tmp_path))
    assert p.exists()


# --- _install_crash_traps -----------------------------------------------------

def _kur(monkeypatch, tmp_path, register=None):
    """Crash trap kurulumunu izole eder; atexit callback'lerini yakalar.

    sys.excepthook sessiz bir fonksiyonla degistirilir: boylece kurulan
    hook cagrildiginda pytest-qt'nin istisna yakalayicisina ulasmaz.
    """
    kayit = []

    def yakala(fn):
        kayit.append(fn)

    def sessiz_hook(etype, value, tb):
        pass

    monkeypatch.setattr(atexit, 'register', register or yakala)
    monkeypatch.setattr(sys, 'excepthook', sessiz_hook)
    monkeypatch.setattr(config, 'LOG_DIR', str(tmp_path))
    return kayit


def _open_kaydet(monkeypatch):
    """builtins.open'i sarmalar; crash dosya tanitacilarini kaydeder."""
    kapanacaklar = []
    gercek_open = builtins.open

    def kayitli_open(*args, **kwargs):
        fh = gercek_open(*args, **kwargs)
        ad = getattr(fh, 'name', '')
        if isinstance(ad, str) and 'crash-' in ad:
            kapanacaklar.append(fh)
        return fh

    monkeypatch.setattr(builtins, 'open', kayitli_open)
    return kapanacaklar


def _crash_dosyalari(tmp_path):
    return sorted(n for n in os.listdir(tmp_path) if n.startswith('crash-'))


def test_install_crash_traps_temel_akis(monkeypatch, tmp_path):
    kayit = _kur(monkeypatch, tmp_path)
    kapanacaklar = _open_kaydet(monkeypatch)

    assert main_mod._install_crash_traps() is True
    assert len(kayit) == 1

    dosyalar = _crash_dosyalari(tmp_path)
    assert len(dosyalar) == 1
    yol = tmp_path / dosyalar[0]
    assert 'crash traps aktif' in yol.read_text(encoding='utf-8')

    hook = sys.excepthook
    hook(ValueError, ValueError('patlama'), None)
    assert 'UNCAUGHT' in yol.read_text(encoding='utf-8')

    from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    yakalayici = qInstallMessageHandler(None)
    assert yakalayici is not None
    yakalayici(QtMsgType.QtWarningMsg, None, 'zararsiz uyari')
    assert 'zararsiz' not in yol.read_text(encoding='utf-8')
    # QtMsgType bazi ortamlarda (coverage) duz Enum olur; kaynak .value
    # sayesinde seviye numarasi her iki modda da yazilir.
    yakalayici(QtMsgType.QtCriticalMsg, None, 'kritik olay')
    assert '[QT 2] kritik olay' in yol.read_text(encoding='utf-8')

    kayit[0]()
    assert yol.exists()  # anlamli icerik: silinmez
    assert sys.excepthook is not hook
    for fh in kapanacaklar:
        assert fh.closed


def test_install_crash_traps_bos_dosya_temizlenir(monkeypatch, tmp_path):
    kayit = _kur(monkeypatch, tmp_path)
    kapanacaklar = _open_kaydet(monkeypatch)

    assert main_mod._install_crash_traps() is True
    dosyalar = _crash_dosyalari(tmp_path)
    yol = tmp_path / dosyalar[0]

    kayit[0]()
    assert not yol.exists()
    for fh in kapanacaklar:
        assert fh.closed


def test_install_crash_traps_log_dir_dosya(monkeypatch, tmp_path):
    engel = tmp_path / 'engel'
    engel.write_text('x', encoding='utf-8')
    monkeypatch.setattr(config, 'LOG_DIR', str(engel))
    assert main_mod._install_crash_traps() is None


def test_install_crash_traps_temizlik_patlarsa_none(monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'LOG_DIR', str(tmp_path))

    def patlak(logdir):
        raise RuntimeError('temizlik yok')

    monkeypatch.setattr(main_mod, '_prune_empty_crash_logs', patlak)
    assert main_mod._install_crash_traps() is None


def test_install_crash_traps_script_yedegi(monkeypatch, tmp_path):
    mod = _script_modul()
    kok = os.path.dirname(os.path.dirname(os.path.abspath(mod.__file__)))
    monkeypatch.setattr(sys, 'path', [p for p in sys.path if p != kok])
    kayit = _kur(monkeypatch, tmp_path)
    kapanacaklar = _open_kaydet(monkeypatch)

    assert mod._install_crash_traps() is True
    assert len(_crash_dosyalari(tmp_path)) == 1

    kayit[0]()
    assert _crash_dosyalari(tmp_path) == []
    for fh in kapanacaklar:
        assert fh.closed


def test_install_crash_traps_open_hatasi(monkeypatch, tmp_path):
    kayit = _kur(monkeypatch, tmp_path)
    gercek_open = builtins.open

    def patlak_open(*args, **kwargs):
        if args and isinstance(args[0], str) and 'crash-' in args[0]:
            raise OSError('disk dolu')
        return gercek_open(*args, **kwargs)

    monkeypatch.setattr(builtins, 'open', patlak_open)

    assert main_mod._install_crash_traps() is True
    assert _crash_dosyalari(tmp_path) == []
    hook = sys.excepthook
    hook(ValueError, ValueError('x'), None)  # fh yok: sessiz gecmeli
    assert sys.excepthook is hook
    kayit[0]()  # fh None: erken donus


class _FlushPatlak:
    """Ikinci flush cagrisinda patlar (kurulumdaki ilki basarili)."""

    def __init__(self, gercek):
        self._gercek = gercek
        self.flush_sayaci = 0

    def write(self, s):
        return self._gercek.write(s)

    def flush(self):
        self.flush_sayaci += 1
        if self.flush_sayaci >= 2:
            raise OSError('flush yok')
        return self._gercek.flush()

    def close(self):
        return self._gercek.close()


def test_install_crash_traps_flush_hatasi(monkeypatch, tmp_path):
    kayit = _kur(monkeypatch, tmp_path)
    gercek_open = builtins.open
    sahteler = []

    def sahte_open(*args, **kwargs):
        mode = args[1] if len(args) > 1 else kwargs.get('mode', 'r')
        fh = gercek_open(*args, **kwargs)
        if (mode == 'x' and isinstance(getattr(fh, 'name', ''), str)
                and 'crash-' in fh.name):
            sahte = _FlushPatlak(fh)
            sahteler.append(sahte)
            return sahte
        return fh

    monkeypatch.setattr(builtins, 'open', sahte_open)

    assert main_mod._install_crash_traps() is True
    kayit[0]()
    assert _crash_dosyalari(tmp_path) == []
    assert sahteler and sahteler[0].flush_sayaci == 2


def test_install_crash_traps_disable_hatasi(monkeypatch, tmp_path):
    kayit = _kur(monkeypatch, tmp_path)
    kapanacaklar = _open_kaydet(monkeypatch)
    gercek_disable = faulthandler.disable

    def patlak_disable():
        raise RuntimeError('kapatilamaz')

    monkeypatch.setattr(faulthandler, 'disable', patlak_disable)

    assert main_mod._install_crash_traps() is True
    dosyalar = _crash_dosyalari(tmp_path)
    yol = tmp_path / dosyalar[0]

    kayit[0]()  # disable hatasi: fh ve dosya canli kalir
    assert yol.exists()

    monkeypatch.setattr(faulthandler, 'disable', gercek_disable)
    gercek_disable()
    for fh in kapanacaklar:
        fh.close()
    os.remove(str(yol))


class _ClosePatlak:
    def __init__(self, gercek):
        self.gercek = gercek

    def write(self, s):
        return self.gercek.write(s)

    def flush(self):
        return self.gercek.flush()

    def close(self):
        raise OSError('kapanmaz')


def test_install_crash_traps_kapatma_ve_silme_hatasi(monkeypatch, tmp_path):
    kayit = _kur(monkeypatch, tmp_path)
    gercek_open = builtins.open
    kapanacaklar = []

    def sahte_open(*args, **kwargs):
        mode = args[1] if len(args) > 1 else kwargs.get('mode', 'r')
        fh = gercek_open(*args, **kwargs)
        if (mode == 'x' and isinstance(getattr(fh, 'name', ''), str)
                and 'crash-' in fh.name):
            kapanacaklar.append(fh)
            return _ClosePatlak(fh)
        return fh

    monkeypatch.setattr(builtins, 'open', sahte_open)

    assert main_mod._install_crash_traps() is True
    dosyalar = _crash_dosyalari(tmp_path)
    yol = tmp_path / dosyalar[0]

    kayit[0]()
    assert yol.exists()  # close basarisiz -> silme de basarisiz

    for fh in kapanacaklar:
        fh.close()
    os.remove(str(yol))


def test_install_crash_traps_okuma_hatasi(monkeypatch, tmp_path):
    kayit = _kur(monkeypatch, tmp_path)
    kapanacaklar = _open_kaydet(monkeypatch)
    gercek_open = builtins.open

    def okuyamayan_open(*args, **kwargs):
        mode = args[1] if len(args) > 1 else kwargs.get('mode', 'r')
        if (mode == 'r' and args and isinstance(args[0], str)
                and 'crash-' in args[0]):
            raise OSError('okunamaz')
        return gercek_open(*args, **kwargs)

    monkeypatch.setattr(builtins, 'open', okuyamayan_open)

    assert main_mod._install_crash_traps() is True
    dosyalar = _crash_dosyalari(tmp_path)
    yol = tmp_path / dosyalar[0]

    kayit[0]()
    assert yol.exists()
    for fh in kapanacaklar:
        assert fh.closed


def test_install_crash_traps_atexit_hatasi(monkeypatch, tmp_path):
    kayit = []

    def patlak_register(fn):
        kayit.append(fn)
        raise RuntimeError('kayit yok')

    _kur(monkeypatch, tmp_path, register=patlak_register)
    kapanacaklar = _open_kaydet(monkeypatch)

    assert main_mod._install_crash_traps() is True
    assert len(_crash_dosyalari(tmp_path)) == 1

    kayit[0]()
    assert _crash_dosyalari(tmp_path) == []
    for fh in kapanacaklar:
        assert fh.closed


def test_install_crash_traps_qt_yok(monkeypatch, tmp_path):
    kayit = _kur(monkeypatch, tmp_path)
    kapanacaklar = _open_kaydet(monkeypatch)
    monkeypatch.setitem(sys.modules, 'PySide6.QtCore', None)

    assert main_mod._install_crash_traps() is True
    dosyalar = _crash_dosyalari(tmp_path)
    yol = tmp_path / dosyalar[0]

    kayit[0]()
    assert not yol.exists()
    for fh in kapanacaklar:
        assert fh.closed


def test_install_crash_traps_qt_geri_yukleme_hatasi(monkeypatch, tmp_path):
    kayit = _kur(monkeypatch, tmp_path)
    kapanacaklar = _open_kaydet(monkeypatch)

    import PySide6.QtCore as qtc
    gercek_qimh = qtc.qInstallMessageHandler

    assert main_mod._install_crash_traps() is True
    dosyalar = _crash_dosyalari(tmp_path)
    yol = tmp_path / dosyalar[0]

    def patlak_qimh(handler):
        raise RuntimeError('geri yuklenemez')

    monkeypatch.setattr(qtc, 'qInstallMessageHandler', patlak_qimh)
    kayit[0]()
    assert yol.exists()  # erken donus: fh ve dosya canli

    qtc.qInstallMessageHandler = gercek_qimh
    gercek_qimh(None)
    faulthandler.disable()
    for fh in kapanacaklar:
        fh.close()
    os.remove(str(yol))


class _IkinciYazimPatlak:
    """Ilk write basarili; sonraki write cagrilari patlar."""

    def __init__(self, gercek):
        self.gercek = gercek
        self.sayac = 0

    def write(self, s):
        self.sayac += 1
        if self.sayac >= 2:
            raise OSError('yazim yok')
        return self.gercek.write(s)

    def flush(self):
        return self.gercek.flush()

    def close(self):
        return self.gercek.close()


def test_install_crash_traps_hook_ve_qt_yazim_hatalari(monkeypatch, tmp_path):
    kayit = []

    def patlak_register(fn):
        kayit.append(fn)

    def patlak_hook(etype, value, tb):
        raise RuntimeError('orig patladi')

    monkeypatch.setattr(atexit, 'register', patlak_register)
    monkeypatch.setattr(sys, 'excepthook', patlak_hook)
    monkeypatch.setattr(config, 'LOG_DIR', str(tmp_path))

    gercek_open = builtins.open
    kapanacaklar = []

    def sahte_open(*args, **kwargs):
        mode = args[1] if len(args) > 1 else kwargs.get('mode', 'r')
        fh = gercek_open(*args, **kwargs)
        if (mode == 'x' and isinstance(getattr(fh, 'name', ''), str)
                and 'crash-' in fh.name):
            kapanacaklar.append(fh)
            return _IkinciYazimPatlak(fh)
        return fh

    monkeypatch.setattr(builtins, 'open', sahte_open)

    assert main_mod._install_crash_traps() is True
    hook = sys.excepthook
    hook(ValueError, ValueError('x'), None)
    assert sys.excepthook is hook

    from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    yakalayici = qInstallMessageHandler(None)
    yakalayici(QtMsgType.QtCriticalMsg, None, 'kritik')

    kayit[0]()
    assert _crash_dosyalari(tmp_path) == []
    for fh in kapanacaklar:
        assert fh.closed


# --- run ----------------------------------------------------------------------

class _FakeCore:
    pass


class _FakePencere:
    def __init__(self, core, selftest=False):
        self.core = core
        self.selftest = selftest
        self.gosterildi = False
        self._workers = []
        self._closing = True

    def show(self):
        self.gosterildi = True

    def close(self):
        return True


class _FakeQApp:
    instances = []

    @classmethod
    def instance(cls):
        # pytest-qt her testin setup/call/teardown'unda instance() cagirir.
        return None

    def __init__(self, argv):
        self.argv = argv
        self.name = None
        self.exec_cagrildi = False
        self.process_events = 0
        _FakeQApp.instances.append(self)

    def setApplicationName(self, name):
        self.name = name

    def processEvents(self):
        self.process_events += 1

    def exec(self):
        self.exec_cagrildi = True
        return 0


def _run_hazirla(monkeypatch, tmp_path):
    from PySide6 import QtWidgets
    monkeypatch.setattr(main_mod, '_install_crash_traps', lambda: True)
    monkeypatch.setattr(main_mod, '_import_pkg',
                        lambda: (_FakeCore, _FakePencere))
    monkeypatch.setattr(QtWidgets, 'QApplication', _FakeQApp)
    _FakeQApp.instances.clear()
    hedef = tmp_path / 'selftest.txt'
    monkeypatch.setattr(main_mod, '_selftest_path', lambda: str(hedef))
    return hedef


def test_run_selftest_basarili(monkeypatch, tmp_path):
    hedef = _run_hazirla(monkeypatch, tmp_path)
    assert main_mod.run(selftest=True) == 0
    assert hedef.read_text(encoding='utf-8') == 'SELFTEST_OK'
    app = _FakeQApp.instances[-1]
    assert app.name == 'MiBox Konsol'
    assert app.process_events >= 1


def test_run_normal_exec(monkeypatch, tmp_path):
    _run_hazirla(monkeypatch, tmp_path)
    assert main_mod.run(selftest=False) == 0
    assert _FakeQApp.instances[-1].exec_cagrildi


def test_run_selftest_kapanis_hatasi(monkeypatch, tmp_path):
    _run_hazirla(monkeypatch, tmp_path)
    monkeypatch.setattr(main_mod, '_shutdown_selftest_window',
                        lambda win, app: False)
    assert main_mod.run(selftest=True) == 2


def test_run_selftest_yazim_hatasi(monkeypatch, tmp_path):
    hedef = _run_hazirla(monkeypatch, tmp_path)
    hedef.mkdir()
    assert main_mod.run(selftest=True) == 2


# --- main ---------------------------------------------------------------------

def test_main_check_catalog_delege(monkeypatch):
    from mibox_app import catalog_health
    cagri = []

    def sahte_main(argv):
        cagri.append(argv)
        return 1

    monkeypatch.setattr(catalog_health, 'main', sahte_main)
    assert main_mod.main(['prog', '--check-catalog']) == 1
    assert cagri == [['prog', '--check-catalog']]
    assert main_mod.main(['prog', '--update-hash', 'x']) == 1


def test_main_version_print_info(monkeypatch):
    yollar = []
    monkeypatch.setattr(main_mod, '_print_info',
                        lambda output_path=None: yollar.append(output_path))
    assert main_mod.main(['prog', '--version']) == 0
    assert yollar == [None]
    assert main_mod.main(['prog', '--bilgi']) == 0
    assert yollar == [None, None]


def test_main_version_report_file(monkeypatch, tmp_path):
    yollar = []
    monkeypatch.setattr(main_mod, '_print_info',
                        lambda output_path=None: yollar.append(output_path))
    hedef = str(tmp_path / 'rapor.txt')
    assert main_mod.main(['prog', '--version', '--report-file', hedef]) == 0
    assert yollar == [hedef]


def test_main_report_file_eksik_deger(monkeypatch):
    monkeypatch.setattr(main_mod, '_print_info', lambda output_path=None: None)
    assert main_mod.main(['prog', '--version', '--report-file']) == 2
    assert main_mod.main(
        ['prog', '--version', '--report-file', '--selftest']) == 2


def test_main_print_info_oserror(monkeypatch):
    def patlak(output_path=None):
        raise OSError('yazilamaz')

    monkeypatch.setattr(main_mod, '_print_info', patlak)
    assert main_mod.main(['prog', '--version']) == 2


def test_main_varsayilan_run(monkeypatch):
    cagri = []
    monkeypatch.setattr(main_mod, 'run',
                        lambda selftest=False: cagri.append(selftest) or 0)
    assert main_mod.main(['prog']) == 0
    assert main_mod.main(['prog', '--selftest']) == 0
    assert cagri == [False, True]


def test_main_argv_yok(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['mibox.py', '--version'])
    yollar = []
    monkeypatch.setattr(main_mod, '_print_info',
                        lambda output_path=None: yollar.append(output_path))
    assert main_mod.main() == 0
    assert yollar == [None]
