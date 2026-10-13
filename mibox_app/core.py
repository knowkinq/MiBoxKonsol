# -*- coding: utf-8 -*-
"""Core: ADB engine + config + UI sinyalleri.

MainWindow ve tum sekmeler bu Core nesnesini paylasiyor.
Core, UI thread'inden ADB cagrisi yapmaz; her islem bir Worker ile
arka plana atilir.

Thread notu: engine ilk kez birden fazla worker thread'inden istenebilir;
olusturma kilitle yapilir ki ADB birden fazla kez aranmasin/tek ornek kalsin.
"""
import threading

from PySide6.QtCore import QObject, Signal

from .adb_engine import AdbEngine, AdbError
from .config import Config


class Core(QObject):
    """Tum sekmeler tarafindan paylasilan merkez."""

    log = Signal(str, str)          # (mesaj, seviye)
    connection_changed = Signal(bool, str)  # (bagli mi, hedef)

    def __init__(self):
        super().__init__()
        self.config = Config()
        self.target = self.config.last_target
        self.connected = False
        self._engine = None
        self._engine_err = None
        self._engine_lock = threading.Lock()
        try:
            self._engine = AdbEngine(trace_cb=self._on_adb_trace)
        except AdbError as e:
            self._engine_err = str(e)

    # --- ADB komut izi -> Canli Log (thread-guvenli sinyal) ---
    adb_trace = Signal(list, bool, int, str, bool)  # (komut, ok, ms, hata, probe)

    def _on_adb_trace(self, cmd, ok, ms, err, probe=False):
        try:
            self.adb_trace.emit(list(cmd), bool(ok), int(ms), str(err), bool(probe))
        except Exception:
            pass

    # ------------------------------------------------------------------
    @property
    def engine(self):
        if self._engine is None:
            # ADB sonradan kurulmus olabilir; tekrar dene (tek olusturma).
            with self._engine_lock:
                if self._engine is None:
                    try:
                        self._engine = AdbEngine(trace_cb=self._on_adb_trace)
                        self._engine_err = None
                    except AdbError as e:
                        self._engine_err = str(e)
                        raise AdbError(self._engine_err or 'ADB hazır degil.')
        # trace baglantisi kopmussa onar
        try:
            if getattr(self._engine, 'trace_cb', None) is None:
                self._engine.trace_cb = self._on_adb_trace
        except Exception:
            pass
        return self._engine

    @property
    def engine_error(self):
        return self._engine_err

    @property
    def adb_path(self):
        return self._engine.adb_path if self._engine else None

    def log_msg(self, msg, level='INFO'):
        self.log.emit(msg, level)

    # ------------------------------------------------------------------
    def set_target(self, target):
        self.target = target
        self.config.last_target = target
        self.config.save()

    def connect(self, target=None, timeout=30):
        """Baglanti kurar. Hata durumunda AdbError atar. UI thread disinda cagirin."""
        t = target or self.target
        self.engine.connect(t, timeout=timeout)
        self.connected = True
        self.connection_changed.emit(True, t)
        self.log_msg('Baglandi: {}'.format(t))

    def disconnect(self):
        try:
            self.engine.disconnect(self.target)
        except AdbError:
            pass
        self.connected = False
        self.connection_changed.emit(False, self.target)
        self.log_msg('Bağlantı kesildi: {}'.format(self.target))
