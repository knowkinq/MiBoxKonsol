# -*- coding: utf-8 -*-
"""Ana pencere: baglanti cubugu + sekmeler + canli log."""
import datetime
import os
import re
import threading

from collections import deque

from PySide6.QtCore import Qt, QTimer, QObject, QMutex
from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTabWidget,
    QPlainTextEdit, QMessageBox, QStatusBar, QCheckBox,
    QSplitter, QScrollArea,
)

from .. import APP_NAME, __version__
from ..config import LOG_DIR
from ..workers import Worker
from .apps_tab import AppsTab
from .debloat_tab import DebloatTab
from .flowlayout import FlowLayout
from .files_tab import FilesTab
from .health_tab import HealthTab
from .history_tab import HistoryTab
from .install_tab import InstallTab
from .logcat_tab import LogcatTab
from .network_tab import NetworkTab
from .remote_tab import RemoteTab
from .settings_tab import SettingsTab
from .theme import qss_for, level_colors_for, colors_for, conn_style

IP_RE = re.compile(r'^\d{1,3}(\.\d{1,3}){3}:\d+$')
# VERBOSE: probe/yoklama satirlari (pidof negatif vb). Varsayilan KAPALI,
# tik acilmadikca panele basilmaz ve tampona DA yazilmaz (gürültü yok).
LEVELS = ('INFO', 'WARN', 'ERROR', 'ADB', 'VERBOSE')
LOG_CAPACITY = 2000  # Canli Log halka tamponu (tik degisiminde yeniden cizilir)


class LogBus(QObject):
    """Thread-guvenli log dagitici: her thread'den enqueue(), UI'da flush().

    appendHtml dogrudan worker/ADB iz thread'inden cagrilamazdi (crash).
    Tum loglar once buraya kuyruklanir, 120 ms'lik QTimer ile UI thread'de
    toplu basilir. Filtre tikleri sadece GORUNUMU degistirir; kayitlar
    tampona yazilmaya devam eder, tik acilinca gecmis geri gelir.
    """

    def __init__(self, capacity=LOG_CAPACITY):
        super().__init__()
        self._mutex = QMutex()
        self._pending = deque()
        self._store = deque(maxlen=capacity)

    def enqueue(self, msg, level):
        try:
            self._mutex.lock()
            try:
                # kayit zamani KUYRUGA GIRISTE alinir (ms hassasiyet):
                # flush toplu bassa bile her satir kendi zamanini tasir.
                ts = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
                self._pending.append((ts, str(msg), str(level or 'INFO')))
            finally:
                self._mutex.unlock()
        except Exception:
            pass

    def drain(self):
        """Bekleyenleri store'a al, tum store kopyasini dondur."""
        try:
            self._mutex.lock()
            try:
                while self._pending:
                    self._store.append(self._pending.popleft())
                return list(self._store)
            finally:
                self._mutex.unlock()
        except Exception:
            return []

    def drain_new(self):
        """Bekleyenleri store'a al; (yeni kayitlar, toplam uzunluk) dondur."""
        try:
            self._mutex.lock()
            try:
                new_items = []
                while self._pending:
                    rec = self._pending.popleft()
                    self._store.append(rec)
                    new_items.append(rec)
                return new_items, len(self._store)
            finally:
                self._mutex.unlock()
        except Exception:
            return [], 0

    def snapshot(self):
        try:
            self._mutex.lock()
            try:
                return list(self._store)
            finally:
                self._mutex.unlock()
        except Exception:
            return []

    def clear(self):
        try:
            self._mutex.lock()
            try:
                self._pending.clear()
                self._store.clear()
            finally:
                self._mutex.unlock()
        except Exception:
            pass


class MainWindow(QMainWindow):
    def __init__(self, core):
        super().__init__()
        self.core = core
        self.setWindowTitle('{} v{}'.format(APP_NAME, __version__))
        # Ekranin %94'u kadar acil, ortala; kucuk ekranda tasmaz.
        try:
            avail = QGuiApplication.primaryScreen().availableGeometry()
            w = min(1480, int(avail.width() * 0.94))
            h = min(960, int(avail.height() * 0.94))
            self.resize(w, h)
            self.move(avail.center() - self.rect().center())
        except Exception:
            self.resize(1360, 860)
        self.setMinimumSize(1024, 640)
        self._level_colors = level_colors_for(self.core.config.dark_mode)
        self._palette = colors_for(self.core.config.dark_mode)
        self._workers = []
        self._closing = False
        self._selftest = False  # main.py --selftest modunda True: watchdog is uretmez
        self._log_filter = set(LEVELS)
        self._logbus = LogBus()
        # Gunluk log dosyasi: yol + gun onbellek (her satirda makedirs yok)
        # ve yazma kilidi (append_log her thread'den cagrilabilir).
        self._log_file_day = None
        self._log_file_path = None
        self._log_file_lock = threading.Lock()
        self._log_timer = QTimer(self)
        self._log_timer.timeout.connect(self._flush_logs)
        self._log_timer.start(120)
        self._last_drawn = 0
        self._build()
        self._connect_signals()
        self.apply_theme()
        self.refresh_history_combo()

    def apply_theme(self):
        """Tema degisince: QSS + palet + baglanti gostergeleri + log yeniden cizim."""
        dark = self.core.config.dark_mode
        self.setStyleSheet(qss_for(dark))
        self._level_colors = level_colors_for(dark)
        self._palette = colors_for(dark)
        # baglanti gostergelerini yeni palete gecir (durumu koru)
        try:
            self._set_link(self.core.connected)
            self.lbl_status.setStyleSheet(conn_style(dark, bool(self.core.connected)))
        except (RuntimeError, AttributeError):
            pass
        # log gorunumunu yeni renklerle bastan ciz
        try:
            self._rebuild_log_view()
        except (RuntimeError, AttributeError):
            pass
        # alt sekmelerdeki sabit renkler (tablo on renkleri, ipucu etiketleri)
        try:
            from .kit import refresh_theme
            refresh_theme(self.centralWidget())
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # --- Baglanti cubugu (tek satir: hedef + baglan + durum) ---
        conn = QWidget()
        conn_layout = QHBoxLayout(conn)
        conn_layout.setContentsMargins(6, 6, 6, 6)
        conn_layout.setSpacing(6)
        self.lbl_conn_dot = QLabel('●')
        self.lbl_conn_dot.setStyleSheet(
            'color: {}; font-size: 14pt;'.format(colors_for(self.core.config.dark_mode)['danger']))
        self.lbl_conn_dot.setToolTip('Baglanti durumu')
        self.txt_target = QLineEdit(self.core.target or '')
        self.txt_target.setPlaceholderText('IP:PORT  ornek: 192.0.2.1:5555')
        self.txt_target.setMinimumWidth(170)
        self.txt_target.setMaximumWidth(220)
        self.btn_connect = QPushButton('Baglan')
        self.btn_connect.setProperty('accent', True)
        self.btn_disconnect = QPushButton('Kopar')
        self.btn_disconnect.setProperty('danger', True)
        self.btn_disconnect.setEnabled(False)
        self.lbl_status = QLabel('Bagli degil')
        self.lbl_status.setStyleSheet(conn_style(self.core.config.dark_mode, False))
        self.cmb_devices = QComboBox()
        self.cmb_devices.setPlaceholderText('Cihaz')
        self.cmb_devices.setToolTip('Bagli cihazlar (adb devices)')
        self.cmb_devices.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.cmb_history = QComboBox()
        self.cmb_history.setPlaceholderText('Gecmis')
        self.cmb_history.setToolTip('Gecmis hedefler')
        self.cmb_history.setEditable(False)
        self.cmb_history.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        conn_layout.addWidget(self.lbl_conn_dot)
        conn_layout.addWidget(self.txt_target)
        conn_layout.addWidget(self.btn_connect)
        conn_layout.addWidget(self.btn_disconnect)
        conn_layout.addWidget(self.lbl_status)
        conn_layout.addWidget(QLabel('Cihaz:'))
        conn_layout.addWidget(self.cmb_devices, 1)
        conn_layout.addWidget(QLabel('Gecmis:'))
        conn_layout.addWidget(self.cmb_history, 1)
        root.addWidget(conn)

        # --- Sekmeler + log (splitter: log paneli kapatilabilir) ---
        self.splitter = QSplitter(Qt.Vertical)
        self.tabs = QTabWidget()
        self.tab_apps = AppsTab(self.core, self)
        self.tab_remote = self._scroll_wrap(RemoteTab(self.core, self))
        self.tab_remote_inner = self.tab_remote.widget()
        self.tab_debloat = DebloatTab(self.core, self)
        self.tab_network = self._scroll_wrap(NetworkTab(self.core, self))
        self.tab_network_inner = self.tab_network.widget()
        self.tab_settings = self._scroll_wrap(SettingsTab(self.core, self))
        self.tab_settings_inner = self.tab_settings.widget()
        self.tab_health = self._scroll_wrap(HealthTab(self.core, self))
        self.tab_health_inner = self.tab_health.widget()
        self.tab_history = HistoryTab(self.core, self)
        self.tab_logcat = LogcatTab(self.core, self)
        self.tab_files = self._scroll_wrap(FilesTab(self.core, self))
        self.tab_files_inner = self.tab_files.widget()
        self.tab_install = self._scroll_wrap(InstallTab(self.core, self))
        self.tab_install_inner = self.tab_install.widget()
        self.tabs.addTab(self.tab_apps, u'▦ Uygulamalar')
        self.tabs.addTab(self.tab_remote, u'▣ Kumanda')
        self.tabs.addTab(self.tab_debloat, u'🧹 Debloat')
        self.tabs.addTab(self.tab_health, u'♥ Sağlık')
        self.tabs.addTab(self.tab_history, u'🕘 Geçmiş')
        self.tabs.addTab(self.tab_logcat, u'≡ Logcat')
        self.tabs.addTab(self.tab_files, u'🗀 Dosyalar')
        self.tabs.addTab(self.tab_install, u'⭳ Kurulum')
        self.tabs.addTab(self.tab_network, u'🌐 Ağ')
        self.tabs.addTab(self.tab_settings, u'⚙ Ayarlar')
        self.splitter.addWidget(self.tabs)

        # --- Canli log (collapsible) ---
        log_box = QWidget()
        log_v = QVBoxLayout(log_box)
        log_v.setContentsMargins(6, 6, 6, 6)
        log_v.setSpacing(4)
        self.lbl_log_title = QLabel('Canli Log')
        self.lbl_log_title.setStyleSheet('font-weight: bold;')
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMinimumHeight(60)
        self.txt_log.setMaximumHeight(160)
        self.btn_clear_log = QPushButton('Temizle')
        self.btn_clear_log.setProperty('flat', True)
        self.btn_clear_log.setMaximumWidth(90)
        self.btn_save_log = QPushButton('Kaydet')
        self.btn_save_log.setProperty('flat', True)
        self.btn_save_log.setMaximumWidth(90)
        self.btn_hide_log = QPushButton('Goster')
        self.btn_hide_log.setProperty('flat', True)
        self.btn_hide_log.setMaximumWidth(70)
        self.btn_hide_log.setCheckable(True)
        self.btn_hide_log.setChecked(True)  # acilista log KAPALI
        self.btn_hide_log.toggled.connect(self._toggle_log)
        self.chk_info = QCheckBox('INFO')
        self.chk_info.setChecked(True)
        self.chk_warn = QCheckBox('WARN')
        self.chk_warn.setChecked(True)
        self.chk_err = QCheckBox('ERROR')
        self.chk_err.setChecked(True)
        self.chk_adb = QCheckBox('ADB')
        self.chk_adb.setChecked(True)
        self.chk_adb.setToolTip('Her calistirilan ADB komutunu goster (suruculu, sureli)')
        self.chk_verbose = QCheckBox('Ayrinti')
        self.chk_verbose.setChecked(False)
        self.chk_verbose.setToolTip('Yoklama satirlari (pidof negatif vb). Acinca gürültü artar.')
        self.chk_info.toggled.connect(lambda on: self._toggle_level('INFO', on))
        self.chk_warn.toggled.connect(lambda on: self._toggle_level('WARN', on))
        self.chk_err.toggled.connect(lambda on: self._toggle_level('ERROR', on))
        self.chk_adb.toggled.connect(lambda on: self._toggle_level('ADB', on))
        self.chk_verbose.toggled.connect(lambda on: self._toggle_level('VERBOSE', on))
        self._log_filter.discard('VERBOSE')
        log_top = QHBoxLayout()
        log_top.setSpacing(4)
        log_top.addWidget(self.lbl_log_title)
        log_top.addWidget(self.chk_info)
        log_top.addWidget(self.chk_warn)
        log_top.addWidget(self.chk_err)
        log_top.addWidget(self.chk_adb)
        log_top.addWidget(self.chk_verbose)
        log_top.addStretch()
        log_top.addWidget(self.btn_hide_log)
        log_top.addWidget(self.btn_save_log)
        log_top.addWidget(self.btn_clear_log)
        log_v.addLayout(log_top)
        log_v.addWidget(self.txt_log)
        self.log_box = log_box
        self.splitter.addWidget(log_box)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setCollapsible(1, True)
        log_box.setVisible(False)  # acilista kapali; butonla acilir
        try:
            self.btn_hide_log.blockSignals(True)
            self.btn_hide_log.setChecked(True)
            self.btn_hide_log.setText('Goster')
            self.btn_hide_log.blockSignals(False)
        except Exception:
            pass
        root.addWidget(self.splitter, 1)

        # --- Log ac/kapa dugmesi (baglanti cubugunda, hep gorunur) ---
        self.btn_log_toggle = QPushButton('Log')
        self.btn_log_toggle.setToolTip('Canli Log panelini ac/kapa')
        self.btn_log_toggle.setCheckable(True)
        self.btn_log_toggle.setChecked(False)
        self.btn_log_toggle.setMaximumWidth(70)
        self.btn_log_toggle.toggled.connect(self._toggle_log_panel)
        conn_layout.addWidget(self.btn_log_toggle)
        # --- Durdur: calisan arka plan islerini iptal et (Faz 3) ---
        self.btn_stop = QPushButton('Durdur')
        self.btn_stop.setToolTip('Calisan arka plan islerini durdur')
        self.btn_stop.setProperty('danger', True)
        self.btn_stop.setMaximumWidth(70)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.cancel_workers)
        conn_layout.addWidget(self.btn_stop)

        # --- Status bar: solda SON KULLANICI ISLEMI, sagda sistem ---
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.lbl_last_action = QLabel('Hazir')
        self.lbl_last_action.setToolTip('Kullanicinin yaptigi son islem')
        self.status.addWidget(self.lbl_last_action, 1)
        self.lbl_clock = QLabel('')
        self.status.addPermanentWidget(self.lbl_clock)
        self.lbl_adb = QLabel('ADB: ' + (self.core.adb_path or 'bulunamadi'))
        self.lbl_adb.setToolTip(self.core.adb_path or '')
        self.lbl_target = QLabel('Hedef: ' + (self.core.target or '-'))
        self.lbl_link = QLabel(u'● Çevrimdışı')
        self.lbl_link.setStyleSheet(conn_style(self.core.config.dark_mode, False))
        self.status.showMessage('Hazir')
        self.status.addPermanentWidget(self.lbl_adb)
        self.status.addPermanentWidget(self.lbl_target)
        self.status.addPermanentWidget(self.lbl_link)

        # Saat + kalici log (arka planda; gosterge shop yok)
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick_clock)
        self._clock.start(1000)
        self._tick_clock()
        # Bağlantı bekçisi: 15 sn'de bir sessiz yoklama, kopmuşsa yeniden bağlan.
        self._watch = QTimer(self)
        self._watch.timeout.connect(self._watchdog)
        self._watch.start(15000)
        self._watch_fail = 0
        QTimer.singleShot(3000, self._watchdog)
        # append_log hem tamponu hem gunluk dosyasini besler; burada ikinci
        # kez _write_log_line cagrilmasi baslangic satirini duplike ediyordu.
        self.append_log('{} v{} baslatildi.'.format(APP_NAME, __version__), 'INFO')
        if not self.core.adb_path:
            QMessageBox.warning(self, 'ADB', self.core.engine_error or 'ADB bulunamadi.')
        # NOT: acilis OTOMATIK BAGLANTI YOK (v8.3). Kullanici Baglan'a basar.
        # Hedef kutusu kayitli degerle dolar ama baglanti kurulmaz.

    def _auto_connect_startup(self):
        # LEGACY: cagrilmiyor; eski davranis burada durur (geri donus icin).
        return

    @staticmethod
    def _scroll_wrap(widget):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setWidget(widget)
        return area

    def _toggle_log(self, hidden):
        """Paneli ac/kapa (canli log kutusu tamami). hidden=True -> kapali."""
        try:
            self.log_box.setVisible(not hidden)
            self.btn_hide_log.setText('Goster' if hidden else 'Gizle')
        except RuntimeError:
            pass
        # ust cubuktaki Log dugmesiyle senkron tut
        try:
            if self.btn_log_toggle.isChecked() != bool(hidden):
                self.btn_log_toggle.blockSignals(True)
                self.btn_log_toggle.setChecked(bool(hidden))
                self.btn_log_toggle.blockSignals(False)
        except (RuntimeError, AttributeError):
            pass

    def _toggle_log_panel(self, show):
        """Baglanti cubugundaki Log dugmesi: acildiginda tam paneli goster."""
        try:
            self.log_box.setVisible(bool(show))
            self.btn_hide_log.setText('Gizle' if show else 'Goster')
            self.btn_hide_log.blockSignals(True)
            self.btn_hide_log.setChecked(not show)
            self.btn_hide_log.blockSignals(False)
        except (RuntimeError, AttributeError):
            pass
        if show:
            # acilinca gecmis tampondan gorunsun
            try:
                self._rebuild_log_view()
            except Exception:
                pass

    def _toggle_level(self, level, on):
        if on:
            self._log_filter.add(level)
        else:
            self._log_filter.discard(level)
        # gorunumu tamponun tamamindan yeniden kur (kayip yok)
        self._rebuild_log_view()

    def _clear_log_view(self):
        """Temizle: hem paneli hem tamponu bosalt (dosya gunlugu korunur)."""
        try:
            self._logbus.clear()
        except Exception:
            pass
        self._last_drawn = 0
        try:
            self.txt_log.clear()
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    def _daily_log_path(self):
        """Gunluk log yolu (gun bazli onbellekli).

        Ayni gun icin makedirs + tarih hesabi YALNIZCA BIR kez yapilir
        (her satirda dosya acma maliyeti Faz6'da azaltildi).
        """
        now = datetime.datetime.now()
        day = now.strftime('%Y%m%d')
        if self._log_file_day == day and self._log_file_path:
            return self._log_file_path
        with self._log_file_lock:
            if self._log_file_day == day and self._log_file_path:
                return self._log_file_path
            try:
                os.makedirs(LOG_DIR, exist_ok=True)
                path = os.path.join(
                    LOG_DIR, 'mibox-{}.log'.format(now.strftime('%Y%m%d')))
                self._log_file_day = day
                self._log_file_path = path
                return path
            except OSError:
                return None

    def _write_log_line(self, msg, level='INFO'):
        if not self.core.config.log_to_file:
            return
        path = self._daily_log_path()
        if not path:
            return
        try:
            ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            with self._log_file_lock:
                with open(path, 'a', encoding='utf-8') as f:
                    f.write('[{}] [{}] {}\n'.format(ts, level, msg))
        except OSError:
            pass

    def _tick_clock(self):
        try:
            self.lbl_clock.setText(datetime.datetime.now().strftime('%H:%M:%S'))
        except (RuntimeError, AttributeError):
            pass

    def set_last_action(self, text):
        """Kullanicinin yaptigi son islemi durum cubugunda goster + logla."""
        try:
            self.lbl_last_action.setText(u'• {}'.format(text))
        except RuntimeError:
            pass
        try:
            self.append_log(u'Kullanici: {}'.format(text), 'INFO')
        except Exception:
            pass

    def save_log_to_file(self):
        """TAMPONUN TAMAMINI (filtreli gorunum degil) gunluk dosyaya ekle."""
        path = self._daily_log_path()
        if not path:
            QMessageBox.warning(self, 'Log', 'Log klasoru yazilabilir degil.')
            return
        try:
            records = self._logbus.snapshot()
        except Exception:
            records = []
        try:
            ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            with open(path, 'a', encoding='utf-8') as f:
                f.write('\n--- Canli log tamponsu ({} kayit) ---\n'.format(len(records)))
                for rec in records:
                    if len(rec) == 3:
                        rec_ts, msg, level = rec
                    else:
                        msg, level = rec
                        rec_ts = ts
                    f.write('[{}] [{}] {}\n'.format(rec_ts, level, msg))
        except OSError as e:
            QMessageBox.critical(self, 'Log', str(e))
            return
        self.status.showMessage('Log kaydedildi: ' + path, 8000)
        self.append_log('Log dosyaya kaydedildi: {} ({} kayit)'.format(path, len(records)), 'INFO')

    def _connect_signals(self):
        self.btn_connect.clicked.connect(self.on_connect)
        self.btn_disconnect.clicked.connect(self.on_disconnect)
        self.txt_target.editingFinished.connect(self._sync_target)
        self.btn_clear_log.clicked.connect(self._clear_log_view)
        self.btn_save_log.clicked.connect(self.save_log_to_file)
        self.cmb_devices.currentIndexChanged.connect(self._on_device_picked)
        self.cmb_history.currentIndexChanged.connect(self._on_history_picked)
        self.core.log.connect(self.append_log)
        self.core.connection_changed.connect(self.on_connection_changed)
        try:
            self.core.adb_trace.connect(self._on_adb_trace)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _sync_target(self):
        t = self.txt_target.text().strip()
        if IP_RE.match(t):
            self.core.set_target(t)
            self.lbl_target.setText('Hedef: ' + t)
        elif t:
            self.lbl_target.setText('Hedef: (gecersiz)')

    def on_connect(self):
        t = self.txt_target.text().strip()
        if not IP_RE.match(t):
            QMessageBox.warning(self, 'Hedef', 'Adres IP:PORT biciminde olmali.\nOrnek: 192.0.2.1:5555')
            return
        self.core.set_target(t)
        self.core.config.push_history(t)
        self.refresh_history_combo()
        self.btn_connect.setEnabled(False)
        self.append_log('Baglanti deneniyor: ' + t, 'INFO')
        self._run(Worker(lambda: self.core.connect()),
                   on_ok=self._after_connect, on_fail=self._after_connect_fail)

    def _auto_refresh_after_connect(self, why='baglanti kuruldu'):
        """Baglanti sonrasi Uygulamalar sekmesini otomatik yenile (tek nokta)."""
        try:
            if getattr(self.tab_apps, '_busy', False):
                self.append_log('Otomatik yenileme atlandi ({}, tarama suruyor).'.format(why), 'WARN')
                return
            self.tabs.setCurrentWidget(self.tab_apps)
            self.tab_apps.refresh()
            # Debloat da yalnizca-cihaz varligini tazelesin
            try:
                self.tab_debloat.scan_if_needed()
            except Exception:
                pass
        except Exception as e:
            self.append_log('Otomatik yenileme baslatilamadi: {}'.format(e), 'WARN')

    def _after_connect(self, _):
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(True)
        self.refresh_device_combo()
        self.append_log('Baglandi: ' + self.core.target, 'INFO')
        # Baglanti sonrasi Uygulamalar sekmesini otomatik yenile
        self._auto_refresh_after_connect('baglanti kuruldu')

    def _after_connect_fail(self, err):
        self.btn_connect.setEnabled(True)
        self.append_log('Baglanti hatasi: ' + err, 'ERROR')
        QMessageBox.critical(self, 'Baglanti', err)

    def on_disconnect(self):
        self._run(Worker(lambda: self.core.disconnect()),
                  on_ok=lambda _: self.append_log('Baglanti kesildi.', 'INFO'),
                  on_fail=self.append_log)

    def on_connection_changed(self, connected, target):
        self.btn_disconnect.setEnabled(connected)
        self.lbl_status.setText('Bagli: ' + target if connected else 'Bagli degil')
        dark = self.core.config.dark_mode
        self.lbl_status.setStyleSheet(conn_style(dark, bool(connected)))
        self.lbl_target.setText('Hedef: ' + target)
        self._set_link(connected)

    def _set_link(self, online):
        # baglanti noktasi + durum etiketi birlikte guncellenir
        dark = self.core.config.dark_mode
        pal = colors_for(dark)
        dot = pal['success'] if online else pal['danger']
        try:
            self.lbl_conn_dot.setStyleSheet(
                'color: {}; font-size: 14pt;'.format(dot))
            self.lbl_conn_dot.setToolTip(
                u'Çevrimiçi' if online else u'Çevrimdışı')
        except RuntimeError:
            pass
        try:
            self.lbl_link.setText(u'● Çevrimiçi' if online else u'● Çevrimdışı')
            self.lbl_link.setStyleSheet(conn_style(dark, bool(online)))
        except (RuntimeError, AttributeError):
            pass

    def _watchdog(self):
        """15 sn bekçi: hedefe sessizce dokun, kopmuşsa yeniden bağlan."""
        if self._closing or getattr(self, '_selftest', False):
            return
        target = (self.core.target or '').strip()
        if not target or any(w.isRunning() for w in self._workers):
            return

        def do():
            try:
                self.core.engine.connect(target, timeout=8)
                return True
            except Exception:
                return False

        def done(ok):
            if self._closing:
                return
            if ok:
                self._watch_fail = 0
                reconnected = not self.core.connected
                if reconnected:
                    self.core.connected = True
                    self.core.connection_changed.emit(True, target)
                self._set_link(True)
                if reconnected:
                    # kopmustu -> tekrar gelince listeyi tazele
                    self._auto_refresh_after_connect('bekci yeniden baglandi')
            else:
                self._watch_fail += 1
                self._set_link(False)
                if self.core.connected and self._watch_fail >= 2:
                    self.core.connected = False
                    self.core.connection_changed.emit(False, target)
                    self.append_log('Bekçi: bağlantı koptu, yeniden deneniyor: ' + target, 'WARN')

        w = Worker(do)
        w.finished_ok.connect(done)
        self._run(w)

    # ------------------------------------------------------------------
    def refresh_history_combo(self):
        cur = self.txt_target.text().strip()
        self.cmb_history.blockSignals(True)
        self.cmb_history.clear()
        self.cmb_history.addItem('Gecmis...', '')
        for h in self.core.config.device_history:
            self.cmb_history.addItem(h, h)
        if cur:
            for i in range(self.cmb_history.count()):
                if self.cmb_history.itemData(i) == cur:
                    self.cmb_history.setCurrentIndex(i)
                    break
        self.cmb_history.blockSignals(False)

    def _on_history_picked(self, idx):
        d = self.cmb_history.itemData(idx)
        if d:
            self.txt_target.setText(d)
            self._sync_target()

    def refresh_device_combo(self):
        """Adb cihaz listesini yeniler (arka plan)."""
        try:
            engine = self.core.engine
        except Exception as e:
            self.append_log(str(e), 'ERROR')
            return

        def do():
            return engine.devices()
        self._run(Worker(do), on_ok=self._fill_device_combo)

    def _fill_device_combo(self, devs):
        if self._closing:
            return
        try:
            cur = self.txt_target.text().strip()
        except (RuntimeError, AttributeError):
            return
        self.cmb_devices.blockSignals(True)
        self.cmb_devices.clear()
        self.cmb_devices.addItem('Sec...', '')
        for d in devs:
            self.cmb_devices.addItem('{}  [{}]'.format(d['id'], d['state']), d['id'])
        if cur:
            for i in range(self.cmb_devices.count()):
                if self.cmb_devices.itemData(i) == cur:
                    self.cmb_devices.setCurrentIndex(i)
                    break
        self.cmb_devices.blockSignals(False)

    def _on_device_picked(self, idx):
        d = self.cmb_devices.itemData(idx)
        if d:
            self.txt_target.setText(d)
            self._sync_target()

    # ------------------------------------------------------------------
    def append_log(self, msg, level='INFO'):
        """Her thread'den cagrilabilir: kuyruga atar, UI timer basar.

        Filtre tikleri kayitlari SILMEZ; sadece gorunumu degistirir.
        Tik kapatilirsa dosya gunlugune yazilmaya devam eder.
        """
        if self._closing:
            return
        try:
            lvl = str(level or 'INFO')
            self._write_log_line(msg, lvl)
            self._logbus.enqueue(msg, lvl)
        except Exception:
            pass

    def _flush_logs(self):
        """120 ms'de bir: YALNIZCA yeni kayitlari panele bas.

        drain() tum store kopyasi donduruyordu (2000 satir x 8/sn gereksiz
        kopya + dilimleme). Simdi drain_new() yalnizca bekleyenleri verir;
        store uzunlugu _last_drawn ile izlenir (halka tasmasinda sifirlanir).
        """
        try:
            new_items, total = self._logbus.drain_new()
        except Exception:
            return
        if total < self._last_drawn:
            # halka tampon tasti, eski kayitlar dustu -> sayaci esitle
            self._last_drawn = total
            return
        if not new_items:
            return
        try:
            html = []
            for rec in new_items:
                if len(rec) == 3:
                    ts, msg, level = rec
                else:  # eski (msg, level) kuyruk kayitlariyla uyumluluk
                    msg, level = rec
                    ts = '??:??:??.???'
                if level not in self._log_filter:
                    continue
                pal = getattr(self, '_palette', None) or colors_for(self.core.config.dark_mode)
                color = self._level_colors.get(level, pal['text'])
                html.append(
                    '<span style="color:{};">[{}]</span> '
                    '<span style="color:{};">[{}]</span> '
                    '<span style="color:{};">{}</span>'.format(
                        pal['faint'], self._esc(str(ts)), color, self._esc(level),
                        pal['text'], self._esc(msg)))
            if html:
                # tek appendHtml: 147 satirlik tik degisiminde bile tek duzen
                self.txt_log.appendHtml('<br>'.join(html))
                self.txt_log.moveCursor(QTextCursor.End)
            self._last_drawn = total
        except RuntimeError:
            # pencere kapanirken widget silinmis olabilir
            pass
        except Exception:
            pass

    def _rebuild_log_view(self):
        """Tik degisiminde: snapshot'tan filtreyle bastan ciz.

        drain_new() tuketimlidir; rebuild dogrudan snapshot okur, sayaci
        gunceller. Boylece tik ac/kapa sonrasi kayip olmaz.
        """
        try:
            self.txt_log.clear()
        except RuntimeError:
            return
        try:
            records = self._logbus.snapshot()
        except Exception:
            records = []
        try:
            html = []
            for rec in records:
                # eski (msg, level) kayitlariyla geriye uyumlu
                if len(rec) == 3:
                    ts, msg, level = rec
                else:
                    msg, level = rec
                    ts = '??:??:??.???'
                if level not in self._log_filter:
                    continue
                pal = getattr(self, '_palette', None) or colors_for(self.core.config.dark_mode)
                color = self._level_colors.get(level, pal['text'])
                html.append(
                    '<span style="color:{};">[{}]</span> '
                    '<span style="color:{};">[{}]</span> '
                    '<span style="color:{};">{}</span>'.format(
                        pal['faint'], self._esc(str(ts)), color, self._esc(level),
                        pal['text'], self._esc(msg)))
            if html:
                self.txt_log.appendHtml('<br>'.join(html))
                self.txt_log.moveCursor(QTextCursor.End)
            self._last_drawn = len(records)
        except RuntimeError:
            pass
        except Exception:
            pass

    @staticmethod
    def _esc(s):
        return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))

    @staticmethod
    def _short_cmd(cmd):
        """ADB komutunu okunabilir kisa bicime indir (hedef tekrarini at)."""
        parts = [str(a) for a in (cmd or [])]
        # ['-s', hedef, 'shell', ...] -> 'shell ...'
        if len(parts) >= 3 and parts[0] == '-s' and parts[2] == 'shell':
            parts = parts[3:]
        elif len(parts) >= 2 and parts[0] == '-s':
            parts = [parts[1]] + parts[2:]
        text = ' '.join(parts)
        if len(text) > 160:
            text = text[:157] + '...'
        return 'adb ' + text

    def _on_adb_trace(self, cmd, ok, ms, err, probe=False):
        if self._closing:
            return
        # probe (pidof negatif vb): Ayrinti tiki kapaliysa TAMAMEN atla
        # (tampana bile yazilmaz — 147 paket x pidof gürültüsü biter).
        if probe and 'VERBOSE' not in self._log_filter:
            return
        try:
            line = u'{}  {}ms{}'.format(
                self._short_cmd(cmd), ms,
                '' if ok else u'  HATA: {}'.format(err or 'exit!=0'))
            if probe:
                self.append_log(line, 'VERBOSE')
            else:
                self.append_log(line, 'ADB' if ok else 'ERROR')
        except Exception:
            pass

    def cancel_workers(self):
        """Calisan tum worker'lara iptal bayragi koy (Faz 3 disiplini).

        Worker'lar faz gecislerinde check_cancel()/isInterruptionRequested
        gorur; iptal edilen is 'kullanici durdurdu' raporu uretir.
        """
        running = [w for w in list(self._workers) if w.isRunning()]
        if not running:
            return
        try:
            self.append_log(u'⏹ Durdur istendi ({} is).'.format(len(running)), 'WARN')
        except Exception:
            pass
        for w in running:
            try:
                if hasattr(w, 'cancel'):
                    w.cancel()
                else:
                    w.requestInterruption()
            except Exception:
                pass

    def _run(self, worker, on_ok=None, on_fail=None, desc=None):
        """Worker'i baslatir ve sonuclerini baglar. Worker'i bellekte tutar.

        desc: Canli Log'a yazilacak insan-dili aciklama
              (örn: 'Uygulamalar taraniyor'). Verilmezse job_name kullanilir.
        """
        if self._closing:
            # thread baslamadi; deleteLater yeterli (QThread-destroyed yok)
            try:
                worker.deleteLater()
            except Exception:
                pass
            return
        try:
            label = desc or getattr(worker, 'job_name', None) or type(worker).__name__
            self.append_log(u'▶ İstek: {}'.format(label), 'INFO')
        except Exception:
            pass
        if on_ok:
            worker.finished_ok.connect(on_ok)

        def _handle_fail(err):
            self.append_log(str(err), 'ERROR')
            if on_fail:
                on_fail(str(err))
        worker.failed.connect(_handle_fail)
        if hasattr(worker, 'log'):
            try:
                worker.log.connect(lambda m: self.append_log(m, 'INFO'))
            except Exception:
                pass
        if hasattr(worker, 'progress'):
            try:
                worker.progress.connect(
                    lambda cur, total: self.status.showMessage(
                        'Islem: {}/{}'.format(cur, total), 3000))
            except Exception:
                pass

        def _cleanup(_=None):
            if worker in self._workers:
                self._workers.remove(worker)
            try:
                worker.deleteLater()
            except Exception:
                pass
            try:
                alive = any(w.isRunning() for w in self._workers)
                if not alive and hasattr(self, 'btn_stop'):
                    self.btn_stop.setEnabled(False)
            except Exception:
                pass
        try:
            worker.finished.connect(_cleanup)
        except Exception:
            pass
        self._workers.append(worker)
        try:
            if hasattr(self, 'btn_stop'):
                self.btn_stop.setEnabled(True)
        except Exception:
            pass
        worker.start()

    def closeEvent(self, e):
        if self._closing:
            e.accept()
            return
        self._closing = True
        # timer'lari durdur (kapanis sirasinda panele/sinyale dokunulmasin)
        for _t in (getattr(self, '_log_timer', None),
                   getattr(self, '_clock', None),
                   getattr(self, '_watch', None)):
            try:
                if _t is not None:
                    _t.stop()
            except Exception:
                pass
        # worker'lari durdur ve bitmelerini bekle (sinyal/widget yarisi olmasin)
        for w in list(self._workers):
            try:
                if w.isRunning():
                    w.requestInterruption()
            except Exception:
                pass
        for w in list(self._workers):
            try:
                if w.isRunning():
                    w.wait(3000)
            except Exception:
                pass
        # Son savunma: hala ayakta kalan thread varsa zorla durdur.
        # 'QThread: Destroyed while thread is still running' -> process
        # C0000409 ile coker; kapanista asla paylasilmamali.
        for w in list(self._workers):
            try:
                if w.isRunning():
                    w.requestInterruption()
                    if not w.wait(2000):
                        w.terminate()
                        w.wait(1000)
            except RuntimeError:
                pass  # zaten yok edilmis
            except Exception:
                pass
        # ADB ve Core sinyallerini kapat (kapanis sirasinda yeni UI isi
        # baslamasin ve silinen widget'lara callback gitmesin).
        for signal, slot in (
                (self.core.adb_trace, self._on_adb_trace),
                (self.core.log, self.append_log),
                (self.core.connection_changed, self.on_connection_changed)):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        try:
            self.core.config.save()
            self.core.config.save_known_apps()
        except Exception:
            pass
        e.accept()


def make_flow(parent=None):
    """Islem cubuklari icin disari acik FlowLayout kurucu."""
    return FlowLayout(parent)
