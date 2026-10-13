# -*- coding: utf-8 -*-
r"""Giris noktasi.

Calisma bicimleri (hepsi calisir):
  python -m mibox_app.main      (modul olarak)
  python mibox_app\main.py      (direkt script)
  python mibox.py               (kok dizindeki giris, .exe icin)

--selftest: pencereyi kurar, event isler, mibox-selftest-ok.txt yazar, cikar.
--version : surum + ortam bilgisi yazip cikar (paketleme tani icin).
"""
import os
import sys


def _print_info():
    """Surum + ortam bilgisi (tek kaynak: mibox_app.diagnostics).

    .exe penceresiz derlendigi icin ciktiyi gormek uzere yonlendirin:
        MiBoxKonsol.exe --version > bilgi.txt

    Not: burada print() BILEREK kullanilir (CLI ciktisi, GUI log'u degil);
    tools/kalite_tara.py bu dosyada print() uyarisi uretmez:
    kalite_tara: print-serbest
    """
    from . import diagnostics
    print(diagnostics.metin())


def _import_pkg():
    """Relative import dener; script modunda absolute fallback."""
    try:
        from .core import Core
        from .ui.main_window import MainWindow
        return Core, MainWindow
    except ImportError:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in sys.path:
            sys.path.insert(0, root)
        from mibox_app.core import Core
        from mibox_app.ui.main_window import MainWindow
        return Core, MainWindow


def _selftest_path():
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, 'mibox-selftest-ok.txt')


def _prune_empty_crash_logs(logdir, keep=20):
    """Bosa biriken crash dosyalarini temizle.

    Eski davranis her acilista 'crash traps aktif' iceren BOS dosya
    birakiyordu (logs/ altinda 60+ dosya). Gercek icerigi olmayan
    (header + zararsiz Qt font uyarisi disinda satir yok) dosyalari sil,
    en yeni `keep` dosyayi birak.
    """
    try:
        names = sorted(n for n in os.listdir(logdir)
                       if n.startswith('crash-') and n.endswith('.log'))
    except OSError:
        return
    # once bos/gurultu dosyalari ele
    for name in names:
        path = os.path.join(logdir, name)
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                body = f.read()
        except OSError:
            continue
        meaningful = [ln for ln in body.splitlines()
                      if ln.strip()
                      and ln.strip() != 'crash traps aktif'
                      and 'Cannot find font directory' not in ln
                      and 'Qt no longer ships fonts' not in ln
                      and not ln.startswith('[QT 1]')]
        if not meaningful:
            try:
                os.remove(path)
            except OSError:
                pass
    try:
        names = sorted(n for n in os.listdir(logdir)
                       if n.startswith('crash-') and n.endswith('.log'))
        for old in names[:-keep]:
            try:
                os.remove(os.path.join(logdir, old))
            except OSError:
                pass
    except OSError:
        pass


def _install_crash_traps():
    """Crash'i loga dusur: faulthandler + excepthook + Qt mesajlari.

    Qt tarafi cokmeler (segfault ör. widget yarisi) Python'a dusmez; ama
    excepthook yakalanmamis istisnalari, Qt mesaj yakalayici kritik/olumcul
    Qt mesajlarini gunluk dosyasina isler. Boylece 'tik crash' sonrasi
    logs/crash-*.log'da iz olur.

    Faz 1 duzeltmesi: dosya TEMBEL acilir — normal calismada hic crash
    dosyasi olusmaz (eski kod her acilista bos dosya birakiyordu).
    Temiz cikista iceriksiz dosya kalirsa silinir. Qt Warning (örn. zararsiz
    'Cannot find font directory') dosyaya yazilmaz; yalnizca Critical/Fatal.
    """
    import atexit
    import datetime
    import faulthandler
    import traceback

    try:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        logdir = os.path.join(base, 'logs')
        os.makedirs(logdir, exist_ok=True)
        _prune_empty_crash_logs(logdir)
    except Exception:
        return None

    state = {'fh': None, 'path': None}

    def _open():
        if state['fh'] is not None:
            return state['fh']
        try:
            path = os.path.join(
                logdir, 'crash-{}.log'.format(
                    datetime.datetime.now().strftime('%Y%m%d-%H%M%S')))
            fh = open(path, 'w', encoding='utf-8')
            fh.write('crash traps aktif\n')
            fh.flush()
            state['fh'] = fh
            state['path'] = path
            try:
                faulthandler.enable(file=fh)
            except Exception:
                pass
            return fh
        except Exception:
            return None

    def _cleanup_empty():
        # temiz cikis: gercek icerik yoksa dosyayi kaldirma
        fh = state['fh']
        path = state['path']
        if fh is None or path is None:
            return
        try:
            fh.flush()
        except Exception:
            pass
        try:
            fh.close()
        except Exception:
            pass
        state['fh'] = None
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                body = f.read()
        except OSError:
            return
        meaningful = [ln for ln in body.splitlines()
                      if ln.strip()
                      and ln.strip() != 'crash traps aktif'
                      and 'Cannot find font directory' not in ln
                      and 'Qt no longer ships fonts' not in ln
                      and not ln.startswith('[QT 1]')]
        if not meaningful:
            try:
                os.remove(path)
            except OSError:
                pass
    try:
        atexit.register(_cleanup_empty)
    except Exception:
        pass

    try:
        def _hook(etype, value, tb):
            try:
                fh = _open()
                if fh is not None:
                    fh.write('\n--- UNCAUGHT {} ---\n'.format(
                        datetime.datetime.now().strftime('%H:%M:%S')))
                    traceback.print_exception(etype, value, tb, file=fh)
                    fh.flush()
            except Exception:
                pass
            try:
                orig_hook(etype, value, tb)
            except Exception:
                pass
        orig_hook = sys.excepthook
        sys.excepthook = _hook

        try:
            from PySide6.QtCore import qInstallMessageHandler, QtMsgType
            logged = {'n': 0}

            def _qtmsg(mode, ctx, msg):
                # YALNIZCA kritik/olumcul: Qt Warning (font dizini vb.
                # zararsiz uyarilar) dosyaya yazilmaz, bos crash birikmez.
                if mode in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
                    try:
                        if logged['n'] < 200:
                            fh = _open()
                            if fh is not None:
                                fh.write('[QT {}] {}\n'.format(int(mode), msg))
                                fh.flush()
                                logged['n'] += 1
                    except Exception:
                        pass
            qInstallMessageHandler(_qtmsg)
        except Exception:
            pass
        return True
    except Exception:
        return None


def run(selftest=False):
    from PySide6.QtWidgets import QApplication

    Core, MainWindow = _import_pkg()
    _install_crash_traps()
    app = QApplication(sys.argv)
    app.setApplicationName('MiBox Konsol')
    core = Core()
    win = MainWindow(core)
    if selftest:
        # Selftest: hicbir otomatik is baslamasın (watchdog connect worker'i
        # 8 sn surebilir; process bu beklemede takilir/cura kapatir).
        try:
            win._selftest = True
            win._watch.stop()
        except Exception:
            pass
    win.show()
    if selftest:
        app.processEvents()
        # acilista baslayan worker'lari bekle (QThread-destroyed uyarisi olmasin)
        try:
            for w in list(getattr(win, '_workers', [])):
                if w.isRunning():
                    w.wait(8000)
            app.processEvents()
        except Exception:
            pass
        try:
            with open(_selftest_path(), 'w', encoding='utf-8') as f:
                f.write('SELFTEST_OK')
        except OSError:
            pass
        try:
            win.close()
            app.processEvents()
        except Exception:
            pass
        # closeEvent sonrasinda da hala ayakta kalan worker kalmis mi?
        # kalmissa bekle; 'QThread Destroyed' -> C0000409 crash onlenir.
        try:
            pending = [w for w in list(getattr(win, '_workers', []))
                       if w.isRunning()]
            for w in pending:
                w.requestInterruption()
                if not w.wait(5000):
                    w.terminate()
                    w.wait(2000)
        except Exception:
            pass
        return 0
    return app.exec()


def main(argv=None):
    """CLI dagitimi (hem mibox.py hem .exe ayni yolu kullanir).

    --version / --bilgi : pencere acmadan surum + ortam bilgisi yaz, cik.
    --selftest          : pencereyi offscreen kur, isaretci yaz, cik.
    (baska)             : normal GUI.
    """
    argv = list(sys.argv if argv is None else argv)
    if '--version' in argv or '--bilgi' in argv:
        _print_info()
        return 0
    return run(selftest='--selftest' in argv)


if __name__ == '__main__':
    sys.exit(main())