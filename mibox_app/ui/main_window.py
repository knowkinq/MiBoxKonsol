# -*- coding: utf-8 -*-
"""Ana pencere: baglanti cubugu + sekmeler + canli log."""
import datetime
import os
import re
import threading
import ipaddress

from collections import deque

from PySide6.QtCore import Qt, QTimer, QObject, QMutex, QSize
from PySide6.QtGui import QGuiApplication, QTextCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTabWidget,
    QPlainTextEdit, QMessageBox, QStatusBar,
    QSplitter, QScrollArea, QListWidget, QListWidgetItem, QProgressBar, QSizePolicy,
    QSystemTrayIcon, QMenu,
)

from .. import APP_NAME, __version__
from ..adb_engine import watchdog_interval
from ..config import LOG_DIR
from ..workers import Worker
from . import kit
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
from .terminal_tab import TerminalTab
from .theme import qss_for, level_colors_for, colors_for, conn_style
from .icons import line_icon
from .actions_dialog import ActionsDialog

HOST_RE = re.compile(
    r'^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)'
    r'(?:\.(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?))*$')
DEVICE_SERIAL_RE = re.compile(r'^[A-Za-z0-9._:-]+$')
# VERBOSE: probe/yoklama satirlari (pidof negatif vb). Varsayilan KAPALI,
# tik acilmadikca panele basilmaz ve tampona DA yazilmaz (gürültü yok).
LEVELS = ('INFO', 'WARN', 'ERROR', 'ADB', 'VERBOSE')
LOG_CAPACITY = 2000  # Canli Log halka tamponu (tik degisiminde yeniden cizilir)
WATCHDOG_BASE_MS = 15000  # baglanti bekcisi temel araligi (ardisik hatada uzar)


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
        self._pending = deque(maxlen=capacity)
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
    def __init__(self, core, selftest=False):
        super().__init__()
        self.core = core
        self.setWindowTitle('{} v{}'.format(APP_NAME, __version__))
        self.setWindowIcon(line_icon('tv', color='#6366f1', size=32))
        # Ekranin %94'u kadar acil, ortala; kucuk ekranda tasmaz.
        try:
            avail = QGuiApplication.primaryScreen().availableGeometry()
            w = min(1480, int(avail.width() * 0.94))
            h = min(960, int(avail.height() * 0.94))
            self.resize(w, h)
            self.move(avail.center() - self.rect().center())
        except Exception:
            self.resize(1360, 860)
        self.setMinimumSize(900, 600)
        self._level_colors = level_colors_for(self.core.config.dark_mode)
        self._palette = colors_for(self.core.config.dark_mode)
        self._workers = []
        self._activity = {}
        self._error_text = ''
        self._closing = False
        self._close_pending = False
        self._close_scheduled = False
        self._reconnect_target = None
        self._connection_busy = False
        self._watchdog_generation = 0
        self._watchdog_worker = None
        self._disconnect_pending = False
        self._disconnect_in_progress = False
        self._selftest = bool(selftest)  # kurulum selftest'inde watchdog is uretmez
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
        self._setup_tray_icon()
        self._setup_window_shortcuts()

    def apply_theme(self):
        """Tema degisince: QSS + palet + baglanti gostergeleri + log yeniden cizim."""
        dark = self.core.config.dark_mode
        self.setStyleSheet(qss_for(dark))
        self._level_colors = level_colors_for(dark)
        self._palette = colors_for(dark)
        if hasattr(self, '_page_details'):
            for index, (_, _, icon_name) in enumerate(self._page_details):
                self.navigation.item(index).setIcon(line_icon(icon_name, self._palette['muted']))
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
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(188)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 18, 14, 14)
        side.setSpacing(6)
        brand_header = QWidget(sidebar)
        brand_header.setObjectName('sidebarHeader')
        brand_layout = QVBoxLayout(brand_header)
        brand_layout.setContentsMargins(2, 0, 2, 0)
        brand_layout.setSpacing(3)
        brand = QLabel('MiBox Konsol')
        brand.setObjectName('brandTitle')
        brand_layout.addWidget(brand)
        tagline = QLabel('Android TV Yönetim Merkezi')
        tagline.setObjectName('brandSubtitle')
        tagline.setWordWrap(True)
        brand_layout.addWidget(tagline)
        side.addWidget(brand_header)
        side.addSpacing(10)
        self.navigation = QListWidget()
        self.navigation.setObjectName('navigation')
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.navigation.setAccessibleName('Sayfalar')
        self.navigation.setIconSize(QSize(19, 19))
        self.navigation.setSpacing(4)
        side.addWidget(self.navigation, 1)
        self.btn_log_toggle = QPushButton('Log')
        self.btn_log_toggle.setObjectName('sidebarLogToggle')
        self.btn_log_toggle.setMinimumHeight(36)
        self.btn_log_toggle.setToolTip('İşlem günlüğünü aç / kapat')
        self.btn_log_toggle.setCheckable(True)
        self.btn_log_toggle.toggled.connect(self._toggle_log_panel)
        side.addWidget(self.btn_log_toggle)
        footer = QLabel('MiBox Konsol  ·  v{}'.format(__version__))
        footer.setObjectName('sidebarFooter')
        side.addWidget(footer)
        shell.addWidget(sidebar)
        workspace = QWidget()
        workspace.setObjectName('workspace')
        root = QVBoxLayout(workspace)
        root.setContentsMargins(22, 18, 22, 12)
        root.setSpacing(8)
        shell.addWidget(workspace, 1)
        page_header = QWidget()
        page_header.setObjectName('pageHeader')
        page_header_layout = QVBoxLayout(page_header)
        page_header_layout.setContentsMargins(0, 0, 0, 0)
        page_header_layout.setSpacing(4)
        self.page_title = QLabel('Uygulamalar')
        self.page_title.setObjectName('pageTitle')
        self.page_subtitle = QLabel('Uygulamalarınızı inceleyin, düzenleyin ve yönetin.')
        self.page_subtitle.setObjectName('pageSubtitle')
        self.page_subtitle.setWordWrap(True)
        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(12)
        heading.addWidget(self.page_title, 1)
        self.btn_quick = QPushButton('Hızlı erişim  ·  Ctrl+K')
        self.btn_quick.setObjectName('quickActionsButton')
        self.btn_quick.setProperty('role', 'quiet')
        self.btn_quick.clicked.connect(self.open_quick_actions)
        heading.addWidget(self.btn_quick)
        page_header_layout.addLayout(heading)
        page_header_layout.addWidget(self.page_subtitle)
        root.addWidget(page_header)

        # --- Baglanti cubugu (tek satir: hedef + baglan + durum) ---
        conn = QWidget()
        conn.setObjectName('connectionCard')
        connection_root = QHBoxLayout(conn)
        connection_root.setContentsMargins(12, 10, 12, 10)
        connection_root.setSpacing(10)
        conn_controls = QWidget()
        conn_controls.setObjectName('connectionControls')
        conn_layout = FlowLayout(conn_controls, hspacing=6, vspacing=6)
        connection_root.addWidget(conn_controls, 1)
        self.lbl_conn_dot = QLabel('●')
        self.lbl_conn_dot.setObjectName('connectionIndicator')
        self.lbl_conn_dot.setStyleSheet(
            'color: {}; font-size: 14pt;'.format(colors_for(self.core.config.dark_mode)['danger']))
        self.lbl_conn_dot.setToolTip('Bağlantı durumu')
        initial_target = self.core.target or ''
        initial_host = initial_target.rpartition(':')[0] if ':' in initial_target else initial_target
        if initial_host.endswith('.x'):
            address = ''
            initial_port = ''
            self._target_kind = None
            self.core.target = ''
            self.core.config.last_target = ''
            self.core.config.save()
        elif self._valid_target(initial_target):
            address, _separator, initial_port = initial_target.rpartition(':')
            self._target_kind = 'network'
        else:
            address, initial_port = initial_target, ''
            if self._is_ipv4_address(address):
                initial_port = '5555'
                self._target_kind = 'network'
            else:
                self._target_kind = 'serial' if initial_target else None
        self.txt_target = QLineEdit(address)
        self.txt_target.setObjectName('targetInput')
        self.txt_target.setPlaceholderText('IP/host veya cihaz kimliği')
        self.txt_target.setAccessibleName('Cihaz IP adresi, host adı veya seri numarası')
        self.txt_target.setMinimumWidth(150)
        self.txt_target.setMaximumWidth(190)
        self.txt_port = QLineEdit(initial_port or ('5555' if not initial_target else ''))
        self.txt_port.setObjectName('targetPortInput')
        self.txt_port.setAccessibleName('ADB bağlantı portu')
        self.txt_port.setMaximumWidth(68)
        self.txt_port.setMaxLength(5)
        self.txt_port.setPlaceholderText('5555')
        self.btn_connect = QPushButton('Bağlan')
        self.btn_connect.setObjectName('connectButton')
        self.btn_connect.setProperty('accent', True)
        self.btn_disconnect = QPushButton('Bağlantıyı kes')
        self.btn_disconnect.setObjectName('disconnectButton')
        self.btn_disconnect.setProperty('role', 'quiet')
        self.btn_disconnect.setEnabled(False)
        self.lbl_status = QLabel('Bağlı değil')
        self.lbl_status.setObjectName('connectionStatus')
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setMinimumWidth(112)
        self.lbl_status.setStyleSheet(conn_style(self.core.config.dark_mode, False))
        self.cmb_devices = QComboBox()
        self.cmb_devices.setPlaceholderText('Cihaz')
        self.cmb_devices.setToolTip('Bağlı cihazlar (adb devices)')
        self.cmb_devices.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.cmb_history = QComboBox()
        self.cmb_history.setPlaceholderText('Geçmiş')
        self.cmb_history.setToolTip('Geçmiş hedefler')
        self.cmb_history.setEditable(False)
        self.cmb_history.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        conn_layout.addWidget(self.lbl_conn_dot)
        conn_layout.addWidget(self.txt_target)
        conn_layout.addWidget(QLabel(':'))
        conn_layout.addWidget(self.txt_port)
        conn_layout.addWidget(self.btn_connect)
        conn_layout.addWidget(self.btn_disconnect)
        conn_layout.addWidget(self.lbl_status)
        self.lbl_device_badge = QLabel('')
        self.lbl_device_badge.setObjectName('connectedDeviceBadge')
        self.lbl_device_badge.setProperty('role', 'badge-accent')
        self.lbl_device_badge.hide()
        conn_layout.addWidget(self.lbl_device_badge)
        self.btn_device_options = QPushButton('Cihaz seç')
        self.btn_device_options.setObjectName('deviceOptionsButton')
        self.btn_device_options.setProperty('role', 'quiet')
        self.btn_device_options.setCheckable(True)
        self.btn_device_options.setToolTip('Bağlı cihazlar ve önceki adresler')
        conn_layout.addWidget(self.btn_device_options)
        self.btn_scan_network = QPushButton('🔍 Ağda Ara')
        self.btn_scan_network.setObjectName('networkScanButton')
        self.btn_scan_network.setProperty('role', 'quiet')
        self.btn_scan_network.setToolTip('Yerel ağdaki (Wi-Fi) açık ADB portlu TV cihazlarını otomatik arar')
        self.btn_scan_network.clicked.connect(self._jump_to_network_scan)
        conn_layout.addWidget(self.btn_scan_network)
        self.device_options = QWidget()
        self.device_options.setObjectName('deviceOptionsPanel')
        self.device_options.setMaximumWidth(470)
        options_layout = QHBoxLayout(self.device_options)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(8)
        for title, combo in (('Bağlı cihazlar', self.cmb_devices),
                             ('Son adresler', self.cmb_history)):
            group = QWidget()
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(3)
            group_layout.addWidget(QLabel(title))
            combo.setMinimumWidth(175)
            combo.setMaximumWidth(215)
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            group_layout.addWidget(combo)
            options_layout.addWidget(group, 1)
        self.device_options.hide()
        self.btn_device_options.toggled.connect(self.device_options.setVisible)
        self.btn_device_options.toggled.connect(
            lambda visible: self.refresh_device_combo() if visible else None)
        connection_root.addWidget(self.device_options, 0, Qt.AlignVCenter)
        root.addWidget(conn)

        # --- Sekmeler + log (splitter: log paneli kapatilabilir) ---
        self.splitter = QSplitter(Qt.Vertical)
        self.tabs = QTabWidget()
        self.tab_apps = AppsTab(self.core, self)
        self.tab_remote = self._scroll_wrap(RemoteTab(self.core, self))
        self.tab_remote.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tab_remote_inner = self.tab_remote.widget()
        self.tab_debloat = DebloatTab(self.core, self)
        self.tab_debloat_page = self._scroll_wrap(self.tab_debloat)
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
        self.tab_terminal = TerminalTab(self.core, self)
        self.tabs.addTab(self.tab_apps, u'▦ Uygulamalar')
        self.tabs.addTab(self.tab_remote, u'▣ Kumanda')
        self.tabs.addTab(self.tab_debloat_page, 'Debloat')
        self.tabs.addTab(self.tab_health, u'♥ Sağlık')
        self.tabs.addTab(self.tab_terminal, u'⚡ Terminal')
        self.tabs.addTab(self.tab_history, u'🕘 Geçmiş')
        self.tabs.addTab(self.tab_logcat, u'≡ Logcat')
        self.tabs.addTab(self.tab_files, u'🗀 Dosyalar')
        self.tabs.addTab(self.tab_install, u'⭳ Kurulum')
        self.tabs.addTab(self.tab_network, u'🌐 Ağ')
        self.tabs.addTab(self.tab_settings, u'⚙ Ayarlar')
        self.tabs.tabBar().hide()
        self._page_details = [
            ('Uygulamalar', 'TV uygulamalarınızı tek yerden yönetin.', 'apps'),
            ('Kumanda', 'Gezinme, ses, oynatma ve canlı ekran.', 'remote'),
            ('Debloat', 'Gereksiz paketleri inceleyin, güvenlik düzeyine göre karar verin.', 'cleanup'),
            ('Sağlık', 'Cihaz durumu, performans ve arka plan yönetimi.', 'health'),
            ('Terminal', 'Doğrudan ADB Shell komut satırı ve sistem teşhisleri.', 'terminal'),
            ('Geçmiş', 'İşlem kayıtları ve geri dönüş noktaları.', 'history'),
            ('Logcat', 'Canlı cihaz günlükleri ve filtreler.', 'logs'),
            ('Dosyalar', 'TV dosyalarına göz atın ve aktarın.', 'files'),
            ('Kurulum', 'Tek APK veya çoklu paket yükleme ve TV mağazası.', 'install'),
            ('Ağ', 'Cihaz keşfi, LAN taraması ve bağlantı araçları.', 'network'),
            ('Ayarlar', 'Görünüm, korumalar ve tercihler.', 'settings'),
        ]
        for index, (title, subtitle, icon) in enumerate(self._page_details):
            item = QListWidgetItem(line_icon(icon, self._palette['muted']), title)
            item.setSizeHint(QSize(148, 38))
            item.setToolTip(subtitle)
            self.navigation.addItem(item)
            shortcut = QShortcut(QKeySequence('Ctrl+{}'.format((index + 1) % 10)), self)
            shortcut.activated.connect(lambda i=index: self.tabs.setCurrentIndex(i))
        self.navigation.currentRowChanged.connect(self.tabs.setCurrentIndex)
        self.tabs.currentChanged.connect(self._page_changed)
        self.navigation.setCurrentRow(0)
        self._page_changed(0)
        shortcut = QShortcut(QKeySequence('Ctrl+Shift+O'), self)
        shortcut.activated.connect(self.open_performance)
        for key, callback in (('Ctrl+K', self.open_quick_actions),
                              ('F5', self.refresh_current_page),
                              ('Ctrl+L', self.focus_target)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
        self.splitter.addWidget(self.tabs)

        # --- Canli log (collapsible) ---
        log_box = QWidget()
        log_box.setObjectName('logCard')
        log_v = QVBoxLayout(log_box)
        log_v.setContentsMargins(6, 6, 6, 6)
        log_v.setSpacing(4)
        self.lbl_log_title = QLabel('İşlem günlüğü')
        self.lbl_log_title.setStyleSheet('font-weight: bold;')
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(LOG_CAPACITY)
        self.txt_log.setMinimumHeight(60)
        self.txt_log.setMaximumHeight(160)
        self.btn_clear_log = QPushButton('Temizle')
        self.btn_clear_log.setProperty('flat', True)
        self.btn_clear_log.setMaximumWidth(90)
        self.btn_save_log = QPushButton('Kaydet')
        self.btn_save_log.setProperty('flat', True)
        self.btn_save_log.setMaximumWidth(90)
        self.btn_hide_log = QPushButton('Göster')
        self.btn_hide_log.setProperty('flat', True)
        self.btn_hide_log.setMaximumWidth(70)
        self.btn_hide_log.setCheckable(True)
        self.btn_hide_log.setChecked(True)  # acilista log KAPALI
        self.btn_hide_log.toggled.connect(self._toggle_log)
        self.chk_info = kit.CheckBox('INFO')
        self.chk_info.setChecked(True)
        self.chk_warn = kit.CheckBox('WARN')
        self.chk_warn.setChecked(True)
        self.chk_err = kit.CheckBox('ERROR')
        self.chk_err.setChecked(True)
        self.chk_adb = kit.CheckBox('ADB')
        self.chk_adb.setChecked(True)
        self.chk_adb.setToolTip('Her calistirilan ADB komutunu göster (suruculu, sureli)')
        self.chk_verbose = kit.CheckBox('Ayrıntı')
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
            self.btn_hide_log.setText('Göster')
            self.btn_hide_log.blockSignals(False)
        except Exception:
            pass
        root.addWidget(self.splitter, 1)

        self.error_box = QWidget()
        self.error_box.setObjectName('errorBanner')
        error_layout = QHBoxLayout(self.error_box)
        error_layout.setContentsMargins(10, 6, 10, 6)
        self.lbl_error = QLabel()
        self.lbl_error.setWordWrap(True)
        self.lbl_error.setTextFormat(Qt.PlainText)
        self.lbl_error.setTextInteractionFlags(Qt.TextSelectableByMouse)
        error_layout.addWidget(self.lbl_error, 1)
        details = QPushButton('Günlüğü aç')
        details.clicked.connect(lambda: self._toggle_log_panel(True))
        error_layout.addWidget(details)
        dismiss = QPushButton('Kapat')
        dismiss.clicked.connect(self.error_box.hide)
        error_layout.addWidget(dismiss)
        self.error_box.hide()
        root.addWidget(self.error_box)

        # --- Durdur: calisan arka plan islerini iptal et (Faz 3) ---
        self.btn_stop = QPushButton('Durdur')
        self.btn_stop.setToolTip('Çalışan arka plan islerini durdur')
        self.btn_stop.setProperty('role', 'secondary')
        self.btn_stop.setMinimumWidth(80)
        self.btn_stop.setEnabled(False)
        self.btn_stop.hide()
        self.btn_stop.clicked.connect(self.cancel_workers)
        conn_layout.addWidget(self.btn_stop)

        # --- Status bar: solda SON KULLANICI ISLEMI, sagda aktivite ve sistem ---
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.lbl_last_action = QLabel('Hazır')
        self.lbl_last_action.setToolTip('Kullanicinin yaptigi son işlem')
        self.status.addWidget(self.lbl_last_action, 1)

        self.activity_box = QWidget()
        self.activity_box.setObjectName('statusActivity')
        activity_layout = QHBoxLayout(self.activity_box)
        activity_layout.setContentsMargins(4, 0, 4, 0)
        activity_layout.setSpacing(6)
        self.lbl_activity = QLabel()
        self.lbl_activity.setTextFormat(Qt.PlainText)
        self.activity_progress = QProgressBar()
        self.activity_progress.setMaximumWidth(130)
        self.activity_progress.setMinimumWidth(80)
        self.activity_progress.setMaximumHeight(14)
        self.activity_progress.setRange(0, 0)
        self.activity_progress.setTextVisible(False)
        activity_layout.addWidget(self.lbl_activity)
        activity_layout.addWidget(self.activity_progress)
        self.activity_box.hide()
        self.status.addPermanentWidget(self.activity_box)

        self.lbl_clock = QLabel('')
        self.status.addPermanentWidget(self.lbl_clock)
        self.lbl_adb = QLabel('ADB hazır' if self.core.adb_path else 'ADB bulunamadı')
        self.lbl_adb.setToolTip(self.core.adb_path or '')
        self.lbl_target = QLabel('Hedef: ' + (self.core.target or '-'))
        self.lbl_link = QLabel(u'● Çevrimdışı')
        self.lbl_link.setStyleSheet(conn_style(self.core.config.dark_mode, False))
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
        if not self._selftest:
            self._watch.start(WATCHDOG_BASE_MS)
        self._watch_fail = 0
        if not self._selftest:
            QTimer.singleShot(3000, self._watchdog)
        # append_log hem tamponu hem gunluk dosyasini besler; burada ikinci
        # kez _write_log_line cagrilmasi baslangic satirini duplike ediyordu.
        self.append_log('{} v{} başlatıldı.'.format(APP_NAME, __version__), 'INFO')
        config_warning = getattr(self.core.config, 'load_warning', '')
        if config_warning:
            self.append_log('Ayar kurtarma: ' + config_warning.replace('\n', ' · '), 'WARN')
            self._show_error('Ayar kurtarma', config_warning)
        if not self.core.adb_path:
            adb_warning = self.core.engine_error or 'ADB bulunamadı.'
            if self._selftest:
                self.append_log('ADB selftest sırasında kullanılamıyor: ' + adb_warning, 'WARN')
            else:
                QMessageBox.warning(self, 'ADB', adb_warning)
        if not self._selftest:
            QTimer.singleShot(600, self._startup_device_check)

    def _startup_device_check(self):
        if self._closing or not self.core.adb_path:
            return
        def do():
            try:
                return self.core.engine.devices()
            except Exception:
                return []
        def done(devs):
            if self._closing:
                return
            self._fill_device_combo(devs)
            target = (self.core.target or '').strip()
            if not target and len(devs) == 1 and devs[0].get('state') == 'device':
                cand = devs[0].get('id')
                if cand:
                    self._set_target_fields(cand)
                    self._sync_target()
                    self.append_log('Tek bağlı cihaz algılandı: ' + cand, 'INFO')
        self._run(Worker(do), on_ok=done)

    @staticmethod
    def _scroll_wrap(widget):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        area.setWidget(widget)
        return area

    def _toggle_log(self, hidden):
        """Paneli ac/kapa (canli log kutusu tamami). hidden=True -> kapali."""
        try:
            self.log_box.setVisible(not hidden)
            self.btn_hide_log.setText('Göster' if hidden else 'Gizle')
        except RuntimeError:
            pass
        # ust cubuktaki Log dugmesiyle senkron tut
        try:
            if self.btn_log_toggle.isChecked() != (not hidden):
                self.btn_log_toggle.blockSignals(True)
                self.btn_log_toggle.setChecked(not hidden)
                self.btn_log_toggle.blockSignals(False)
        except (RuntimeError, AttributeError):
            pass

    def _page_changed(self, index):
        if not 0 <= index < len(self._page_details):
            return
        title, subtitle, _ = self._page_details[index]
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)
        if self.navigation.currentRow() != index:
            self.navigation.setCurrentRow(index)

    def focus_target(self):
        if self.txt_target.isEnabled():
            self.txt_target.setFocus()
            self.txt_target.selectAll()

    def _refresh_action(self):
        page = self.tabs.currentWidget()
        if isinstance(page, QScrollArea):
            page = page.widget()
        for name in ('refresh', '_refresh_info', '_refresh_list'):
            callback = getattr(page, name, None)
            if callable(callback):
                return callback
        return None

    def refresh_current_page(self):
        callback = self._refresh_action()
        if callback is None:
            self.status.showMessage('Bu sayfada yenilenecek liste yok.', 4000)
            return
        if self.tabs.currentIndex() in (0, 3, 6) and not self.core.connected:
            self.status.showMessage('Yenilemek için önce cihaza bağlanın.', 4000)
            self.focus_target()
            return
        page = self.tabs.currentWidget()
        if isinstance(page, QScrollArea):
            page = page.widget()
        if not getattr(page, '_busy', False):
            callback()

    def open_quick_actions(self):
        actions = []
        for index, (title, subtitle, _) in enumerate(self._page_details):
            actions.append((title, subtitle,
                            lambda i=index: self.tabs.setCurrentIndex(i), lambda: True))
        actions.extend([
            ('Performans ve bakım', 'Sağlık içindeki bakım araçları · Ctrl+Shift+O',
             self.open_performance, lambda: True),
            ('Sayfayı yenile', 'Geçerli sayfanın listesini yenile · F5',
             self.refresh_current_page, lambda: self._refresh_action() is not None),
            ('Cihaz adresine git', 'Bağlanılacak adresi düzenle · Ctrl+L',
             self.focus_target, lambda: self.txt_target.isEnabled()),
            ('Ağdaki TV\'leri ara', 'Açık portlu Android TV\'leri otomatik tara · Ctrl+Shift+N',
             self._jump_to_network_scan, lambda: True),
            ('İşlem günlüğü', 'Son işlemleri ve hataları görüntüle',
             lambda: self._toggle_log_panel(True), lambda: True),
        ])
        dialog = ActionsDialog(self, actions)
        dialog.setStyleSheet(self.styleSheet())
        dialog.exec()

    def open_performance(self):
        self.tabs.setCurrentWidget(self.tab_health)
        health = self.tab_health_inner
        health._open_section(health.scroll_performance, health.performance)

    def _show_error(self, label, error):
        if self._closing:
            return
        self._error_text = '{}: {}'.format(label, error)
        self.lbl_error.setText(self._error_text[:360] + ('…' if len(self._error_text) > 360 else ''))
        self.lbl_error.setToolTip(self._error_text)
        self.error_box.show()

    def _on_persistence_error(self, error):
        if self._closing:
            return
        self.append_log('Ayarlar kaydedilemedi: ' + str(error), 'ERROR')
        self._show_error('Ayarlar kaydedilemedi', error)

    def _update_activity(self):
        active = list(self._activity.values())
        self.activity_box.setVisible(bool(active) and not self._closing)
        if not active:
            return
        label, current, total = active[-1]
        extra = ' · {} işlem çalışıyor'.format(len(active)) if len(active) > 1 else ''
        self.lbl_activity.setText(label + extra)
        if total > 0:
            self.activity_progress.setRange(0, total)
            self.activity_progress.setValue(min(current, total))
        else:
            self.activity_progress.setRange(0, 0)

    def _toggle_log_panel(self, show):
        """Baglanti cubugundaki Log dugmesi: acildiginda tam paneli goster."""
        try:
            self.btn_log_toggle.blockSignals(True)
            self.btn_log_toggle.setChecked(bool(show))
            self.btn_log_toggle.blockSignals(False)
            self.log_box.setVisible(bool(show))
            self.btn_hide_log.setText('Gizle' if show else 'Göster')
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
            self.append_log(u'Kullanıcı: {}'.format(text), 'INFO')
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
                f.write('\n--- Canli log tamponsu ({} kayıt) ---\n'.format(len(records)))
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
        self.append_log('Log dosyaya kaydedildi: {} ({} kayıt)'.format(path, len(records)), 'INFO')

    def _connect_signals(self):
        self.btn_connect.clicked.connect(self.on_connect)
        self.btn_disconnect.clicked.connect(self.on_disconnect)
        self.txt_target.editingFinished.connect(self._sync_target)
        self.txt_port.editingFinished.connect(self._sync_target)
        self.txt_target.textEdited.connect(self._target_address_edited)
        self.btn_clear_log.clicked.connect(self._clear_log_view)
        self.btn_save_log.clicked.connect(self.save_log_to_file)
        self.cmb_devices.currentIndexChanged.connect(self._on_device_picked)
        self.cmb_history.currentIndexChanged.connect(self._on_history_picked)
        self.core.log.connect(self.append_log)
        self.core.connection_changed.connect(self.on_connection_changed)
        try:
            self.core.persistence_error.connect(self._on_persistence_error)
        except Exception:
            pass
        try:
            self.core.adb_trace.connect(self._on_adb_trace)
        except Exception:
            pass

    def _setup_tray_icon(self):
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                return
            self.tray_icon = QSystemTrayIcon(line_icon('tv', color='#6366f1', size=32), self)
            self.tray_icon.setToolTip('{} v{}'.format(APP_NAME, __version__))

            tray_menu = QMenu(self)
            title_action = tray_menu.addAction('📺 {} v{}'.format(APP_NAME, __version__))
            title_action.setEnabled(False)
            tray_menu.addSeparator()

            act_boost = tray_menu.addAction('⚡ Turbo Hızlandır (RAM Temizle)')
            act_boost.triggered.connect(self._quick_turbo_boost)

            act_scrcpy = tray_menu.addAction('🚀 Scrcpy Ekranını Başlat')
            act_scrcpy.triggered.connect(self._quick_scrcpy)

            act_record = tray_menu.addAction('🎥 Video Kaydını Başlat / Bitir')
            act_record.triggered.connect(self._quick_record_toggle)

            tray_menu.addSeparator()

            act_toggle = tray_menu.addAction('Pencereyi Göster / Gizle')
            act_toggle.triggered.connect(self._toggle_window_visibility)

            act_quit = tray_menu.addAction('Çıkış')
            act_quit.triggered.connect(self._tray_quit)

            self.tray_icon.setContextMenu(tray_menu)
            self.tray_icon.activated.connect(self._on_tray_activated)
            self.tray_icon.show()
        except Exception:
            pass

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._toggle_window_visibility()

    def _toggle_window_visibility(self):
        if self.isVisible():
            if self.isMinimized():
                self.showNormal()
                self.activateWindow()
            else:
                self.hide()
        else:
            self.showNormal()
            self.activateWindow()

    def _tray_quit(self):
        self.showNormal()
        self.close()

    def _setup_window_shortcuts(self):
        try:
            QShortcut(QKeySequence('Ctrl+Shift+B'), self, self._quick_turbo_boost)
            QShortcut(QKeySequence('Ctrl+Shift+S'), self, self._quick_scrcpy)
            QShortcut(QKeySequence('Ctrl+Shift+R'), self, self._quick_record_toggle)
            QShortcut(QKeySequence('Ctrl+Shift+T'), self, lambda: self.tabs.setCurrentWidget(self.tab_terminal))
            QShortcut(QKeySequence('Ctrl+Shift+N'), self, self._jump_to_network_scan)
        except Exception:
            pass

    def _jump_to_network_scan(self):
        self.tabs.setCurrentWidget(self.tab_network)
        net_tab = getattr(self, 'tab_network_inner', None)
        if net_tab and hasattr(net_tab, 'scan'):
            QTimer.singleShot(250, net_tab.scan)

    def _quick_turbo_boost(self):
        remote = getattr(self, 'tab_remote_inner', None)
        if remote and hasattr(remote, '_turbo_boost'):
            remote._turbo_boost()

    def _quick_scrcpy(self):
        remote = getattr(self, 'tab_remote_inner', None)
        if remote and hasattr(remote, '_launch_scrcpy'):
            remote._launch_scrcpy()

    def _quick_record_toggle(self):
        remote = getattr(self, 'tab_remote_inner', None)
        if remote and hasattr(remote, '_toggle_screen_recording'):
            remote._toggle_screen_recording()

    # ------------------------------------------------------------------
    def _sync_target(self):
        t = self._target_from_fields()
        if (self._valid_target(t)
                or (self._target_kind == 'serial' and self._valid_device_serial(t))):
            if not self.core.connected and not self._connection_busy and not self._workers:
                self.core.set_target(t)
                self.lbl_target.setText('Hedef: ' + t)
            elif t != self.core.target:
                self.status.showMessage('Yeni adres hazır. Geçiş için Bağlan düğmesine basın.', 5000)
        elif t:
            self.status.showMessage(
                'IP/host:PORT veya ADB listesindeki USB/emülatör cihaz kimliğini girin.', 5000)

    def _target_from_fields(self):
        """Read separate IP/port fields and accept a pasted legacy IP:port."""
        address = self.txt_target.text().strip()
        port = self.txt_port.text().strip()
        if not address:
            return ''
        if self._target_kind == 'serial' and self._valid_device_serial(address):
            return address
        if self._target_kind == 'network':
            if self._valid_target(address):
                address, _separator, port = address.rpartition(':')
                self.txt_target.setText(address)
                self.txt_port.setText(port)
                return '{}:{}'.format(address, port)
            candidate = '{}:{}'.format(address, port) if port else address
            return candidate
        candidate = '{}:{}'.format(address, port) if port else address
        if self._valid_target(address):
            address, _separator, port = address.rpartition(':')
            self.txt_target.setText(address)
            self.txt_port.setText(port)
            self._target_kind = 'network'
            return '{}:{}'.format(address, port)
        if self._looks_like_device_serial(address):
            self._target_kind = 'serial'
            return address
        if self._valid_device_serial(address) and self._device_is_listed(address):
            self._target_kind = 'serial'
            return address
        if self._valid_target(candidate):
            self._target_kind = 'network'
            return candidate
        if not port:
            if self._is_ipv4_address(address):
                self.txt_port.setText('5555')
                self._target_kind = 'network'
                return '{}:5555'.format(address)
        if self._valid_device_serial(address):
            self._target_kind = 'serial'
            return address
        return candidate

    def _target_address_edited(self, _text):
        self._target_kind = None

    def _device_is_listed(self, target):
        try:
            return self.cmb_devices.findData(target) > 0
        except (AttributeError, RuntimeError):
            return False

    @staticmethod
    def _looks_like_device_serial(target):
        target = str(target or '').strip()
        return bool(
            re.fullmatch(r'emulator-\d+', target, re.I)
            or (re.fullmatch(r'[A-Za-z0-9_-]+', target)
                and ('_' in target
                     or (len(target) >= 6 and any(char.isdigit() for char in target)
                         and target.upper() == target))))

    def _set_target_fields(self, target):
        target = str(target or '').strip()
        target_host = target.rpartition(':')[0] if ':' in target else target
        if target_host.endswith('.x'):
            address, port = '', ''
            self._target_kind = None
        elif self._valid_target(target):
            address, _separator, port = target.rpartition(':')
            self._target_kind = 'network'
        else:
            address, port = target, ''
            if self._is_ipv4_address(address):
                port = '5555'
                self._target_kind = 'network'
            else:
                self._target_kind = 'serial' if target else None
        self.txt_target.setText(address)
        self.txt_port.setText(port)

    @staticmethod
    def _is_ipv4_address(address):
        try:
            return ipaddress.ip_address(str(address or '')).version == 4
        except ValueError:
            return False

    @staticmethod
    def _valid_target(target):
        target = str(target or '').strip()
        if ':' not in target:
            return False
        address, port = target.rsplit(':', 1)
        try:
            if not port.isdigit() or not 1 <= int(port) <= 65535:
                return False
            if address.startswith('[') and address.endswith(']'):
                return ipaddress.ip_address(address[1:-1]).version == 6
            try:
                return ipaddress.ip_address(address).version == 4
            except ValueError:
                if ':' in address or re.fullmatch(r'[0-9.]+', address):
                    return False
                return bool(HOST_RE.fullmatch(address))
        except ValueError:
            return False

    @staticmethod
    def _valid_device_serial(target):
        target = str(target or '').strip()
        return bool(target and not target.startswith('-')
                    and DEVICE_SERIAL_RE.fullmatch(target))

    def on_connect(self):
        if self._connection_busy:
            return
        t = self._target_from_fields()
        if not (self._valid_target(t)
                or (self._target_kind == 'serial' and self._valid_device_serial(t))):
            QMessageBox.warning(
                self, 'Hedef',
                'Bir IP/host:PORT adresi veya USB/emülatör cihaz kimliği girin.\n'
                'Örnek: 192.0.2.1:5555, tv.local:5555 ya da emulator-5554')
            return
        if t != self.core.target and self._workers:
            self._show_error('Cihaz değiştirilemedi', 'Çalışan işlemlerin bitmesini bekleyin veya Durdur düğmesini kullanın.')
            return
        if t != self.core.target:
            self._reconnect_target = None
        self.core.set_target(t)
        self.core.config.push_history(t)
        self.refresh_history_combo()
        self._connection_busy = True
        self.btn_connect.setEnabled(False)
        self.btn_disconnect.setEnabled(False)
        self.txt_target.setEnabled(False)
        self.txt_port.setEnabled(False)
        self.cmb_devices.setEnabled(False)
        self.cmb_history.setEnabled(False)
        self.append_log('Bağlantı deneniyor: ' + t, 'INFO')
        self._run(Worker(lambda: self.core.connect(t)),
                   on_ok=self._after_connect, on_fail=self._after_connect_fail)

    def _auto_refresh_after_connect(self, why='baglanti kuruldu'):
        """Baglanti sonrasi Uygulamalar sekmesini otomatik yenile (tek nokta)."""
        try:
            if getattr(self.tab_apps, '_busy', False):
                self.append_log('Otomatik yenileme atlandı ({}, tarama suruyor).'.format(why), 'WARN')
                return
            self.tab_apps.refresh()
            # Debloat sekmesi için: seçili kullanıcı 0'dan farklıysa özel tarama yapsın,
            # aksi halde AppScanWorker zaten tüm sistem/kullanıcı paketlerini (present + disabled)
            # tek seferde tarayıp debloat sekmesine eksiksiz aktarır.
            try:
                if int(self.core.config.user_id or 0) != 0:
                    self.tab_debloat.scan_if_needed()
            except Exception:
                pass
        except Exception as e:
            self.append_log('Otomatik yenileme baslatilamadi: {}'.format(e), 'WARN')

    def _after_connect(self, _):
        self._finish_connection_request()
        self._reconnect_target = self.core.target
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(True)
        self.refresh_device_combo()
        self.append_log('Baglandi: ' + self.core.target, 'INFO')
        # Baglanti sonrasi Uygulamalar sekmesini otomatik yenile
        self._auto_refresh_after_connect('baglanti kuruldu')

    def _after_connect_fail(self, _err):
        self._finish_connection_request()
        self.btn_connect.setEnabled(True)

    def on_disconnect(self):
        if self._connection_busy:
            return
        self._reconnect_target = None
        self._watchdog_generation += 1
        self._disconnect_pending = True
        self._disconnect_in_progress = True
        self._connection_busy = True
        # Stop device jobs before dispatching the disconnect request, so a
        # queued scan or a multi-package action cannot reconnect afterwards.
        # cancel() cannot stop an ADB subprocess already in flight; wait for
        # every tracked worker before disconnecting the shared ADB target.
        for worker in list(self._workers):
            try:
                worker.cancel()
            except (AttributeError, RuntimeError):
                pass
            try:
                worker.finished.connect(self._watchdog_worker_finished)
            except (AttributeError, RuntimeError):
                pass
        self.btn_connect.setEnabled(False)
        self.btn_disconnect.setEnabled(False)
        self.txt_target.setEnabled(False)
        self.txt_port.setEnabled(False)
        self.cmb_devices.setEnabled(False)
        self.cmb_history.setEnabled(False)
        if self._device_workers_running():
            return
        self._start_disconnect()

    def _device_workers_running(self):
        for worker in list(self._workers):
            try:
                if worker.isRunning():
                    return True
            except RuntimeError:
                continue
        return False

    def _watchdog_is_running(self):
        worker = self._watchdog_worker
        if worker is None:
            return False
        try:
            return worker.isRunning()
        except RuntimeError:
            self._watchdog_worker = None
            return False

    def _watchdog_worker_finished(self):
        if not self._watchdog_is_running():
            self._watchdog_worker = None
        if self._disconnect_pending and not self._device_workers_running():
            self._start_disconnect()

    def _start_disconnect(self):
        if not self._disconnect_pending or self._closing:
            return
        if self._device_workers_running():
            return
        self._disconnect_pending = False
        worker = Worker(lambda: self.core.disconnect())
        worker._allow_during_disconnect = True
        self._run(worker,
                  on_ok=self._after_disconnect,
                  on_fail=self._after_disconnect_fail)

    def _finish_connection_request(self):
        self._connection_busy = False
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(self.core.connected)
        self.txt_target.setEnabled(True)
        self.txt_port.setEnabled(True)
        self.cmb_devices.setEnabled(True)
        self.cmb_history.setEnabled(True)
        self.tab_files_inner._update_action_buttons()

    def _after_disconnect(self, _):
        self._disconnect_in_progress = False
        self._finish_connection_request()
        self.append_log('Bağlantı kesildi.', 'INFO')

    def _after_disconnect_fail(self, err):
        self._disconnect_in_progress = False
        self._finish_connection_request()

    def on_connection_changed(self, connected, target):
        if target != self._reconnect_target and not connected:
            self._reconnect_target = None
        self.btn_disconnect.setEnabled(connected and not self._connection_busy)
        self.lbl_status.setText('Bağlı: ' + target if connected else 'Bağlı değil')
        dark = self.core.config.dark_mode
        self.lbl_status.setStyleSheet(conn_style(dark, bool(connected)))
        self.lbl_target.setText('Hedef: ' + target)
        self._set_link(connected)
        if connected and target:
            def _fetch_badge():
                try:
                    model = self.core.engine.getprop(target, 'ro.product.model') or target
                    rel = self.core.engine.getprop(target, 'ro.build.version.release') or ''
                    return model, rel
                except Exception:
                    return target, ''

            def _show_badge(res):
                if not self.core.connected or self.core.target != target:
                    return
                model, rel = res
                disp = model
                if rel:
                    disp += ' (Android {})'.format(rel)
                if hasattr(self, 'lbl_device_badge'):
                    self.lbl_device_badge.setText('📺 ' + disp)
                    self.lbl_device_badge.show()

            bw = Worker(_fetch_badge)
            bw.finished_ok.connect(_show_badge)
            self._run(bw)
        else:
            if hasattr(self, 'lbl_device_badge'):
                self.lbl_device_badge.hide()

    def _set_link(self, online):
        # baglanti noktasi + durum etiketi birlikte guncellenir
        dark = self.core.config.dark_mode
        pal = colors_for(dark)
        dot = pal['success'] if online else pal['faint']
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
        if (not target or target != self._reconnect_target
                or any(w.isRunning() for w in self._workers)):
            return
        generation = self._watchdog_generation

        def do():
            try:
                # Bekci: zaman asimi/ag hatasi gecici sayilir, bir kez tekrar dener.
                self.core.engine.connect(target, timeout=8, deneme=2)
                return True
            except Exception:
                return False

        def done(ok):
            if (self._closing or generation != self._watchdog_generation
                    or target != self._reconnect_target or target != self.core.target):
                return
            if ok:
                self._watch_fail = 0
                try:
                    self._watch.setInterval(WATCHDOG_BASE_MS)
                except RuntimeError:
                    pass
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
                # Uyku/ag dalgalanmasinda her 15 sn'de ADB'ye vurmayalim:
                # ardisik hatada yoklama araligi kademeli uzar (15 -> 30 -> 60).
                try:
                    self._watch.setInterval(watchdog_interval(self._watch_fail) * 1000)
                except RuntimeError:
                    pass
                if self.core.connected and self._watch_fail >= 2:
                    self.core.connected = False
                    self.core.connection_changed.emit(False, target)
                    self.append_log('Bekçi: bağlantı koptu, yeniden deneniyor: ' + target, 'WARN')

        w = Worker(do)
        self._watchdog_worker = w
        w.finished_ok.connect(done)
        w.finished.connect(self._watchdog_worker_finished)
        self._run(w)

    # ------------------------------------------------------------------
    def refresh_history_combo(self):
        cur = self._target_from_fields()
        self.cmb_history.blockSignals(True)
        self.cmb_history.clear()
        self.cmb_history.addItem('Geçmiş...', '')
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
            self._set_target_fields(d)
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
            cur = self._target_from_fields()
        except (RuntimeError, AttributeError):
            return
        self.cmb_devices.blockSignals(True)
        self.cmb_devices.clear()
        self.cmb_devices.addItem('Seç...', '')
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
            self._set_target_fields(d)
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
                self.txt_log.appendHtml(''.join('<p>{}</p>'.format(line) for line in html))
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
                self.txt_log.appendHtml(''.join('<p>{}</p>'.format(line) for line in html))
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
        self.tab_remote_inner._stop_hold()
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
        self.lbl_activity.setText('İşlemler durduruluyor…')

    def _run(self, worker, on_ok=None, on_fail=None, desc=None, silent=False):
        """Worker'i baslatir ve sonuclerini baglar. Worker'i bellekte tutar.

        desc: Canli Log'a yazilacak insan-dili aciklama
              (örn: 'Uygulamalar taraniyor'). Verilmezse job_name kullanilir.
        """
        if isinstance(on_ok, str) and desc is None:
            desc = on_ok
            on_ok = None

        if self._closing or self._close_pending:
            # thread baslamadi; deleteLater yeterli (QThread-destroyed yok)
            try:
                worker.deleteLater()
            except Exception:
                pass
            return
        if (self._disconnect_in_progress
                and not getattr(worker, '_allow_during_disconnect', False)):
            # A queued refresh/action can arrive after on_disconnect() has
            # captured its worker list. Make it sticky-cancelled and include
            # its completion in the disconnect barrier before it can connect.
            try:
                worker.cancel()
                worker.finished.connect(self._watchdog_worker_finished)
            except (AttributeError, RuntimeError):
                pass
        label = desc or getattr(worker, 'job_name', None) or type(worker).__name__
        label_str = str(label)
        is_silent = (silent or getattr(worker, 'silent', False)
                     or label_str.startswith(('Tuş:', 'Tus:', 'Tuş: ', 'Tus: ', 'Ses Seviyesi', 'Ses:', 'Ses Oku', 'Ses Ayarla')))
        if is_silent:
            try:
                worker.silent = True
            except Exception:
                pass
        track = not is_silent
        token = id(worker)
        if track:
            self._activity[token] = (label_str, 0, 0)
            QTimer.singleShot(250, lambda: self._update_activity() if token in self._activity else None)
            try:
                self.append_log(u'▶ İstek: {}'.format(label_str), 'INFO')
            except Exception:
                pass
        if on_ok:
            worker.finished_ok.connect(on_ok)
        if track:
            worker.finished_ok.connect(lambda _result: self.status.showMessage('{} tamamlandı.'.format(label_str), 4000)
                                       if not self._closing and track else None)

        def _handle_fail(err):
            if not is_silent:
                self.append_log('✘ {} başarısız: {}'.format(label_str, str(err)), 'ERROR')
                if 'kullanıcı durdurdu' not in str(err).lower():
                    self._show_error(label_str, str(err))
            if on_fail:
                on_fail(str(err))
        worker.failed.connect(_handle_fail)
        if hasattr(worker, 'log') and not is_silent:
            try:
                def _worker_log(message):
                    # BaseWorker emits the failure summary immediately before
                    # failed; the common handler below records the same error
                    # once at ERROR level with the operation label.
                    if str(message).startswith('✘ '):
                        return
                    self.append_log(message, 'INFO')
                worker.log.connect(_worker_log)
            except Exception:
                pass
        if hasattr(worker, 'progress') and track:
            try:
                def _progress(cur, total):
                    if token in self._activity and not self._closing:
                        self._activity[token] = (label_str, max(0, int(cur)), max(0, int(total)))
                        self._update_activity()
                worker.progress.connect(_progress)
            except Exception:
                pass

        def _cleanup(_=None):
            self._activity.pop(token, None)
            self._update_activity()
            if worker in self._workers:
                self._workers.remove(worker)
            try:
                worker.deleteLater()
            except Exception:
                pass
            try:
                alive = any(w.isRunning() for w in self._workers if not getattr(w, 'silent', False))
                if not alive and hasattr(self, 'btn_stop'):
                    self.btn_stop.setEnabled(False)
                    self.btn_stop.hide()
            except Exception:
                pass
        try:
            worker.finished.connect(_cleanup)
        except Exception:
            pass
        self._workers.append(worker)
        if not is_silent:
            try:
                if hasattr(self, 'btn_stop'):
                    self.btn_stop.setEnabled(True)
                    self.btn_stop.show()
            except Exception:
                pass
        worker.start()

    def _finalize_close(self):
        """Workers are stopped; release UI timers and save settings before closing."""
        self._closing = True
        self._close_pending = False
        self._close_scheduled = False

        # 1. Timer'ları durdur (kapanış sırasında panele/sinyale dokunulmasın)
        for _t in (getattr(self, '_log_timer', None),
                   getattr(self, '_clock', None),
                   getattr(self, '_watch', None)):
            try:
                if _t is not None:
                    _t.stop()
            except Exception:
                pass

        # 2. Kumanda basılı tutma timer'ını durdur
        try:
            self.tab_remote_inner._stop_hold()
        except Exception:
            pass

        # 3. ADB ve Core sinyallerini kapat
        for signal, slot in (
                (self.core.adb_trace, self._on_adb_trace),
                (self.core.log, self.append_log),
                (self.core.connection_changed, self.on_connection_changed)):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

        # 4. Ayarları kaydet
        try:
            self.core.config.save()
            self.core.config.save_known_apps()
        except Exception:
            pass

        # 5. Sistem tepsisi simgesini gizle
        try:
            if hasattr(self, 'tray_icon') and self.tray_icon:
                self.tray_icon.hide()
        except Exception:
            pass

    def _finish_close_when_workers_stop(self):
        if not self._close_pending or self._close_scheduled:
            return
        running = []
        for w in list(self._workers):
            try:
                if w.isRunning():
                    running.append(w)
            except RuntimeError:
                pass
        if not running:
            self._close_scheduled = True
            self._finalize_close()
            QTimer.singleShot(0, self.close)
        else:
            QTimer.singleShot(50, self._finish_close_when_workers_stop)

    def closeEvent(self, e):
        if self._closing:
            e.accept()
            return

        # Kapanış iptali sürerken tekrar [X]'e basılırsa beklemeyi bozma.
        if self._close_pending:
            e.ignore()
            return

        # Finish an active device recording before the window and its worker
        # registry are torn down.
        try:
            if getattr(self.tab_remote_inner, '_recording_remote_path', None):
                self.tab_remote_inner._stop_screen_recording(show_saved_dialog=False)
        except Exception:
            pass

        running = []
        for worker in list(self._workers):
            try:
                if worker.isRunning():
                    running.append(worker)
            except RuntimeError:
                pass

        if running:
            self._close_pending = True
            self.status.showMessage(
                'Çalışan işler durduruluyor; tamamlanınca pencere kapanacak.')
            try:
                self.append_log(
                    'Kapanış istendi; çalışan işler iptal ediliyor.', 'WARN')
            except Exception:
                pass
            try:
                self.tab_remote_inner._stop_hold()
            except Exception:
                pass
            for worker in running:
                try:
                    worker.finished_ok.disconnect()
                except (AttributeError, RuntimeError, TypeError):
                    pass
                try:
                    worker.failed.disconnect()
                except (AttributeError, RuntimeError, TypeError):
                    pass
                if getattr(worker, 'preserve_on_close', False):
                    try:
                        worker.finished.connect(self._finish_close_when_workers_stop)
                    except (AttributeError, RuntimeError):
                        pass
                    continue
                try:
                    if hasattr(worker, 'cancel'):
                        worker.cancel()
                    else:
                        worker.requestInterruption()
                except (AttributeError, RuntimeError):
                    pass
                try:
                    worker.finished.connect(self._finish_close_when_workers_stop)
                except (AttributeError, RuntimeError):
                    pass

            # Uzun işler iptali güvenli bir aşamada işler; tamamlanana kadar
            # pencereyi ve uygulama kaynaklarını canlı tut.
            self.setEnabled(False)
            QTimer.singleShot(50, self._finish_close_when_workers_stop)
            e.ignore()
            return

        self._finalize_close()
        e.accept()


def make_flow(parent=None):
    """Islem cubuklari icin disari acik FlowLayout kurucu."""
    return FlowLayout(parent)
