# -*- coding: utf-8 -*-
r"""Giris noktasi.

Calisma bicimleri (hepsi calisir):
  python -m mibox_app.main      (modul olarak)
  python mibox_app\main.py      (direkt script)
  python mibox.py               (kok dizindeki giris, .exe icin)

--selftest: pencereyi kurar, event isler, mibox-selftest-ok.txt yazar, cikar.
--version : surum + ortam bilgisi yazip cikar (paketleme tani icin).
--check-catalog: katalog indirme adreslerini denetler (bakim/CI; GUI acmaz).
"""
import os
import sys


def _print_info(output_path=None):
    """Surum + ortam bilgisi (tek kaynak: mibox_app.diagnostics).

    .exe penceresiz derlendigi icin ciktiyi gormek uzere yonlendirin:
        MiBoxKonsol.exe --version > bilgi.txt

    Not: burada print() CLI ciktisi icin bilerek kullanilir; GUI log'u degildir.
    """
    try:
        from . import diagnostics
    except ImportError:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in sys.path:
            sys.path.insert(0, root)
        from mibox_app import diagnostics
    text = diagnostics.metin()
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as report:
            report.write(text + '\n')
    stream = sys.stdout
    if stream is None:
        return
    try:
        stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    except (AttributeError, OSError, ValueError):
        pass
    try:
        print(text, file=stream)
    except UnicodeEncodeError:
        encoding = getattr(stream, 'encoding', None) or 'ascii'
        stream.write(text.encode(encoding, errors='backslashreplace')
                     .decode(encoding) + '\n')


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


def _shutdown_selftest_window(win, app):
    """Selftest penceresini worker'lari zorla sonlandirmadan kapat."""
    workers = list(getattr(win, '_workers', []))
    for worker in workers:
        try:
            if worker.isRunning():
                if hasattr(worker, 'cancel'):
                    worker.cancel()
                else:
                    worker.requestInterruption()
        except RuntimeError:
            continue
    # wait() burada timeout'suz kullanilir: QThread.terminate() is parcacigini
    # bellek/ADB islemi ortasinda kesip sureci kararsiz birakabilir. Selftest
    # baslangicinda otomatik cihaz isi baslatmaz; bekleyen bir worker varsa
    # kendi iptal kontrolune ulasmasi beklenir.
    for worker in workers:
        try:
            if worker.isRunning() and not worker.wait():
                return False
        except RuntimeError:
            continue
    app.processEvents()
    if any(worker.isRunning() for worker in workers):
        return False
    if not win.close():
        return False
    app.processEvents()
    return bool(getattr(win, '_closing', False)) and not any(
        worker.isRunning() for worker in list(getattr(win, '_workers', [])))


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


def _prune_old_runtime_logs(logdir, max_age_days=30):
    """Remove expired MiBox operational logs, leaving user history untouched."""
    import re
    import time

    cutoff = time.time() - max_age_days * 24 * 60 * 60
    try:
        names = os.listdir(logdir)
    except OSError:
        return
    for name in names:
        if (name != 'scrcpy.log'
                and not re.fullmatch(r'(?:mibox|scrcpy)-\d{8}\.log', name)):
            continue
        path = os.path.join(logdir, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass


def _install_crash_traps():
    """Crash'i loga dusur: faulthandler + excepthook + Qt mesajlari.

    Qt tarafi cokmeler (segfault ör. widget yarisi) Python'a dusmez; ama
    excepthook yakalanmamis istisnalari, Qt mesaj yakalayici kritik/olumcul
    Qt mesajlarini gunluk dosyasina isler. Boylece 'tik crash' sonrasi
    logs/crash-*.log'da iz olur.

    faulthandler ilk Qt/UI importundan once etkinlestirilir. Temiz cikista
    iceriksiz dosya silinir. Qt Warning (örn. zararsiz 'Cannot find font
    directory') dosyaya yazilmaz; yalnizca Critical/Fatal.
    """
    import atexit
    import datetime
    import faulthandler
    import traceback

    try:
        try:
            from . import config
        except ImportError:
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if root not in sys.path:
                sys.path.insert(0, root)
            from mibox_app import config
        logdir = config.LOG_DIR
        os.makedirs(logdir, exist_ok=True)
        _prune_empty_crash_logs(logdir)
        _prune_old_runtime_logs(logdir)
    except Exception:
        return None

    state = {
        'fh': None, 'path': None, 'fh_enabled': False,
        'hook': None, 'orig_hook': sys.excepthook,
        'qt_installed': False, 'qt_restore': None,
    }

    def _open():
        if state['fh'] is not None:
            return state['fh']
        try:
            path = os.path.join(
                logdir, 'crash-{}-{}.log'.format(
                    datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'), os.getpid()))
            fh = open(path, 'x', encoding='utf-8')
            fh.write('crash traps aktif\n')
            fh.flush()
            state['fh'] = fh
            state['path'] = path
            try:
                faulthandler.enable(file=fh)
                state['fh_enabled'] = True
            except Exception:
                pass
            return fh
        except Exception:
            return None

    def _cleanup_empty():
        # Handler'lari dosya kapanmadan once kaldir.
        if state['qt_installed']:
            try:
                from PySide6.QtCore import qInstallMessageHandler
                qInstallMessageHandler(state['qt_restore'])
                state['qt_installed'] = False
            except Exception:
                pass
        if state['qt_installed']:
            # The Qt callback may still use the file, so leave both alive.
            return
        if state['hook'] is not None and sys.excepthook is state['hook']:
            sys.excepthook = state['orig_hook']

        fh = state['fh']
        path = state['path']
        if fh is None or path is None:
            return
        if state['fh_enabled']:
            try:
                faulthandler.disable()
                state['fh_enabled'] = False
            except Exception:
                # Keep the stream alive if the native handler could not be
                # disabled safely.
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

    # Native faults during the upcoming Qt/UI imports need an already-open
    # stream; a lazy open would miss the first fault entirely.
    _open()

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
                state['orig_hook'](etype, value, tb)
            except Exception:
                pass
        sys.excepthook = _hook
        state['hook'] = _hook

        try:
            from PySide6.QtCore import QtMsgType, qInstallMessageHandler
            logged = {'n': 0}

            def _qtmsg(mode, ctx, msg):
                # YALNIZCA kritik/olumcul: Qt Warning (font dizini vb.
                # zararsiz uyarilar) dosyaya yazilmaz, bos crash birikmez.
                if mode in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
                    try:
                        if logged['n'] < 200:
                            fh = _open()
                            if fh is not None:
                                # int(mode) yerine .value: PySide6 bazi
                                # ortamlarda QtMsgType duz Enum olarak
                                # olusturulur ve int() TypeError atar.
                                fh.write('[QT {}] {}\n'.format(
                                    getattr(mode, 'value', mode), msg))
                                fh.flush()
                                logged['n'] += 1
                    except Exception:
                        pass
            state['qt_restore'] = qInstallMessageHandler(_qtmsg)
            state['qt_installed'] = True
        except Exception:
            pass
        return True
    except Exception:
        return None


def run(selftest=False):
    _install_crash_traps()
    from PySide6.QtWidgets import QApplication

    Core, MainWindow = _import_pkg()
    app = QApplication(sys.argv)
    app.setApplicationName('MiBox Konsol')
    core = Core()
    win = MainWindow(core, selftest=selftest)
    win.show()
    if selftest:
        app.processEvents()
        if not _shutdown_selftest_window(win, app):
            return 2
        try:
            with open(_selftest_path(), 'w', encoding='utf-8') as f:
                f.write('SELFTEST_OK')
        except OSError:
            return 2
        return 0
    return app.exec()


def main(argv=None):
    """CLI dagitimi (hem mibox.py hem .exe ayni yolu kullanir).

    --version / --bilgi : pencere acmadan surum + ortam bilgisi yaz, cik.
    --selftest          : pencereyi offscreen kur, isaretci yaz, cik.
    --check-catalog     : katalog adreslerini denetle, basarisizlikta 1 don.
    --update-hash <id>  : katalog kaydinin guncel sha256'sini hesapla, yazdir.
    (baska)             : normal GUI.
    """
    argv = list(sys.argv if argv is None else argv)
    if '--check-catalog' in argv or '--update-hash' in argv:
        from .catalog_health import main as check_catalog
        return check_catalog(argv)
    if '--version' in argv or '--bilgi' in argv:
        output_path = None
        if '--report-file' in argv:
            index = argv.index('--report-file')
            if index + 1 >= len(argv) or argv[index + 1].startswith('--'):
                return 2
            output_path = argv[index + 1]
        try:
            _print_info(output_path)
        except OSError:
            return 2
        return 0
    return run(selftest='--selftest' in argv)


if __name__ == '__main__':
    sys.exit(main())
