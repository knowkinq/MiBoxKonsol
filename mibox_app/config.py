# -*- coding: utf-8 -*-
"""Yapilandirma ve bilinen uygulama adlari (JSON kalicilik).

Thread notu: Config hem UI thread'inden (hedef degisimi, gecmis, ayar
sekmesi) hem kapanis yolundan yazilir. Okuma/yazma RLock ile korunur;
save() tmp + os.replace ile atomiktir.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import threading


def _base_dir():
    """Ayarlari/exe yanina yazar; .exe dondurulmisse exe klasorunu kullanir."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BASE_DIR = _base_dir()
CONFIG_PATH = os.path.join(BASE_DIR, 'mibox-ayarlar.json')
LOG_DIR = os.path.join(BASE_DIR, 'logs')
SHOT_DIR = os.path.join(BASE_DIR, 'ekran-goruntuleri')
VIDEO_DIR = os.path.join(BASE_DIR, 'ekran-videolari')
APK_DIR = os.path.join(BASE_DIR, 'apk-yedekleri')
DOWNLOADS_DIR = os.path.join(BASE_DIR, 'indirilen-apklar')
# Eski buyuk harfli dosya adiyla geriye uyumluluk (kullanicida varsa oku).
LEGACY_CONFIG_PATH = os.path.join(BASE_DIR, 'MiBox-ayarlar.json')

# Android TV'nin ADB paket listesi çoğu ROM'da yerelleştirilmiş etiketleri
# vermiyor. Cihaz etiketi bulunamadığında bu salt-okunur tablo kullanıcıya
# tanıdık ad gösterir; paket kayıtlarını değiştirmek için kullanılmaz.
DEFAULT_FRIENDLY = {
    'ar.tvplayer.tv': 'TiviMate',
    'com.lagradost.cloudstream3': 'CloudStream',
    'com.spocky.projengmenu': 'Projectivy Launcher',
    'com.spocky.projmenu': 'Projectivy Launcher',
    'me.efdev.flauncher': 'FLauncher',
    'com.teamsmart.videomanager.tv': 'SmartTube',
    'com.liskovsoft.smarttubetv.beta': 'SmartTube Beta',
    'org.smarttube.stable': 'SmartTube',
    'org.smarttube': 'SmartTube (beta)',
    'com.liskovsoft.videomanager': 'SmartTube',
    'org.courville.nova': 'Nova Video Player',
    'com.yablio.sendfilestotv': 'Send Files to TV',
    'cm.aptoidetv.pt': 'Aptoide TV',
    'com.aurora.store': 'Aurora Store',
    'flar2.homebutton': 'Button Mapper',
    'com.google.android.tv': 'Android TV (Launcher)',
    'com.google.android.apps.youtube.tv': 'YouTube TV',
    'com.netflix.ninja': 'Netflix',
    'com.amazon.amazonvideo.livingroom': 'Prime Video',
    'com.disney.disneyplus': 'Disney+',
    'com.hulu': 'Hulu',
    'com.spotify.tv': 'Spotify TV',
    'com.spotify.music': 'Spotify',
    'com.plexapp.plex': 'Plex',
    'com.emby.emby4tv': 'Emby',
    'tv.jellyfin.jellyfin': 'Jellyfin',
    'org.videolan.vlc': 'VLC',
    'com.mxtech.videoplayer.ad': 'MX Player',
    'com.kodi': 'Kodi',
    'com.stremio.tv': 'Stremio TV',
    'com.google.android.gms': 'Google Play Servisleri',
    'com.android.vending': 'Google Play Store',
    'com.google.android.vending': 'Google Play Store',
    'com.google.android.tv.remote.service': 'TV Remote Servisi',
    'com.google.android.tv.startguide': 'TV Start Guide',
    'com.google.android.tv.settings': 'TV Ayarlar',
    'com.android.settings': 'Sistem Ayarlar',
    'com.android.systemui': 'System UI',
    'com.android.launcher': 'Launcher',
    'com.google.android.tv.home': 'TV Home',
    'com.mitv.tvhome.oemtab': 'Mi TV Home',
    'com.xiaomi.mibrand': 'Mi Brand',
    'com.miui.tv': 'Mi UI TV',
    'com.xiaomi.mitv': 'Mi TV',
    'com.xiaomi.mitv.updateservice': 'Mi TV Update Service',
    'com.xm.webcontent': 'Xiaomi TV Web Content',
    'com.manitux.nuviotv': 'Nuvio TV',
    'com.nuvio.tv': 'Nuvio TV',
    'com.google.android.webview': 'WebView',
    'com.android.shell': 'Shell',
    'com.google.android.inputmethod.latin': 'Gboard',
    'com.google.android.documentsui': 'Dosya Secici',
    'com.google.android.feedback': 'Geri Bildirim',
    'com.google.android.feedbacktv': 'TV Geri Bildirim',
    'com.google.android.setupwizard': 'Kurulum Sihirbazi',
    'com.google.android.tts': 'Text-to-Speech',
    'com.google.android.gms.tv': 'Google Play Servisleri (TV)',
    'com.google.android.tv.inputmethod': 'TV Klavye',
    'com.google.android.tv.remotelauncher': 'TV Remote Launcher',
    'com.google.android.tv.remote': 'TV Remote',
    'com.google.android.tv.unifiedsettings': 'TV Unify Ayarlar',
    'com.google.android.wifi.dialog': 'Wi-Fi Diyalog',
    'com.google.android.networkstack': 'Network Stack',
    'com.google.android.captiveportallogin': 'Captive Portal',
    'com.google.android.ext.services': 'Ext Servisler',
    'com.google.android.ext.shared': 'Ext Shared',
    'com.google.android.media.providers': 'Media Providers',
    'com.android.providers.media.module': 'Media Provider',
    'com.android.providers.calendar': 'Takvim Provider',
    'com.android.providers.contacts': 'Kiysiler Provider',
    'com.android.providers.settings': 'Ayarlar Provider',
    'com.android.providers.telephony': 'Telephony Provider',
    'com.google.android.providers.userdictionary': 'Kullanıcı Sözlük',
    'com.android.chrome': 'Chrome',
    'com.google.android.apps.tachyon': 'Google Cast',
    'com.google.android.apps.photos.tv': 'Photos TV',
    'com.google.android.apps.maps': 'Haritalar',
    'com.google.android.apps.translate': 'Ceviri',
    'com.google.android.apps.wellbeing': 'Screen Time',
    'com.google.android.apps.safetyhub': 'Guvvenlik Merkezi',
    'com.google.android.apps.docs': 'Google Dokumanlar',
    'com.google.android.apps.drive': 'Drive',
    'com.google.android.apps.calendar': 'Takvim',
    'com.google.android.apps.youtube.music': 'YouTube Music',
    'com.google.android.apps.youtube.kids': 'YouTube Kids',
    'com.google.android.apps.youtube.kids.tv': 'YouTube Kids TV',
    'com.google.android.apps.youtube.music.tv': 'YouTube Music TV',
    'com.google.android.apps.assistant': 'Google Asistan',
    'com.google.android.apps.assistant.tv': 'Asistan TV',
    'com.google.android.apps.games': 'Google Oyunlar',
    'com.google.android.apps.games.tv': 'Oyunlar TV',
    'com.google.android.apps.talkback': 'TalkBack',
    'com.google.android.apps.pdfviewer': 'PDF Goruntuleyici',
    'com.google.android.apps.podcasts': 'Podcastler',
    'com.google.android.apps.search': 'Arama',
    'com.google.android.apps.wallpaper': 'Duvarkagidi',
    'com.google.android.apps.gmdm': 'Google Device Manager',
    'com.google.android.gsf': 'Google Hesap Servisleri',
    'com.google.android.gsf.login': 'Google Login',
    'com.inat.box': 'İnat Box TV',
    'com.inat.boxtv': 'İnat Box TV',
    'com.rectv.shot': 'Rec TV Ekran Aracı',
    'me.flauncher.flauncher': 'FLauncher',
    'com.google.android.apps.tv.launcherx': 'Google TV Home',
    'com.google.android.apps.tv.launcherx.playnext': 'Google TV Sırada Ne Var',
    'com.google.android.katniss': 'Google Asistan (TV Sesli Arama)',
    'com.google.android.apps.tv.dreamx': 'Google TV Ekran Koruyucu',
    'com.brouken.player': 'Just Player',
    'com.mitv.videoplayer': 'Mi Video Oynatıcı',
    'com.mitv.gallery': 'Mi Galeri',
    'com.xiaomi.mimusic2': 'Mi Müzik 2',
    'com.mitv.tvhome.atv': 'Mi TV Home (Android TV)',
    'com.mitv.tvhome.michannel': 'Mi Kanal',
    'com.mitv.tvhome.mitvplus': 'Mi TV Plus',
    'com.xiaomi.statistic': 'Xiaomi İstatistik / Telemetri',
    'com.miui.tv.analytics': 'MIUI TV Analitik',
    'com.xiaomo.tv.milegal': 'Xiaomi TV Sözleşme & Yasal',
    'com.xiaomi.tvqs.overseas': 'Xiaomi TV Hızlı Ayarlar',
    'com.xiaomi.mitv.smartshare': 'Mi Smart Share',
    'com.xiaomi.mitv.mediaexplorer': 'Mi Medya Tarayıcı',
    'com.xiaomi.android.tvsetup.partnercustomizer': 'Xiaomi TV Partner Kurulumu',
    'com.android.adservices.api': 'Android Reklam Servisleri',
    'com.dolby.android.audio.service': 'Dolby Audio Servisi',
    'com.droidlogic': 'Droidlogic Amlogic Platform',
    'com.droidlogic.systemui.overlay': 'Droidlogic Sistem Arayüzü',
    'com.google.android.youtube.tvmusic': 'YouTube Music TV',
    'com.netflix.tokenmanager': 'Netflix Belirteç Yöneticisi',
    'com.google.android.tvlauncher': 'Android TV Başlatıcı',
    'com.google.android.apps.mediashell': 'Chromecast Built-in',
    'com.mi.bluetooth': 'Xiaomi Bluetooth Kumanda Servisi',
}

DEFAULT_PROTECTED = []  # Kullanıcı kendi koruma listesini oluşturur.


def prettify_package_name(pkg):
    """Bilinmeyen paket adlarından temiz, okunabilir bir uygulama adı üretir."""
    if not pkg or not isinstance(pkg, str):
        return ''
    parts = pkg.strip().split('.')
    while parts and parts[0].lower() in ('com', 'org', 'net', 'io', 'tv', 'me', 'co', 'ar', 'de', 'fr'):
        parts.pop(0)
    if not parts:
        parts = pkg.split('.')[-1:]
    if len(parts) > 1 and parts[-1].lower() in ('tv', 'app', 'android', 'client', 'player', 'stable', 'beta', 'one', 'shot', 'menu'):
        raw = f'{parts[-2]} {parts[-1]}'
    else:
        raw = parts[-1]
    s1 = re.sub(r'([a-z])([A-Z])', r'\1 \2', raw)
    s2 = re.sub(r'([A-Za-z])([0-9])', r'\1 \2', s1)
    s3 = re.sub(r'([0-9])([A-Za-z])', r'\1 \2', s2)
    s4 = s3.replace('_', ' ').replace('-', ' ')
    words = [w.capitalize() for w in s4.split() if w]
    res = ' '.join(['TV' if w.upper() == 'TV' else w for w in words])
    return res or pkg


class Config:
    def __init__(self, load=True, on_persistence_error=None):
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._on_persistence_error = on_persistence_error
        self.save_error = ''
        # Varsayilan kalip: kullanici kendi IP'sini yazar, ilk baglantida
        # kaydedilir. Eskiden sabit ev IP'si gomuluydu (otomatik baglanma
        # sikayeti) — artik bos kalip, otomatik baglanti YOK.
        self.last_target = ''
        self.protected = list(DEFAULT_PROTECTED)
        # legacy salt-okunur yedek (yeni kayit yazilmaz)
        self.friendly = dict(DEFAULT_FRIENDLY)
        self.include_system = False
        self.dark_mode = True
        self.auto_refresh_min = 0
        self.log_to_file = True
        self.device_history = []
        self.screenshot_hd = False
        self.auto_maint = False
        self.maint_last = ''
        self.user_id = 0
        self.show_unlisted = False
        self.show_removed = False  # kaldirilmislar varsayilan gizli
        self.keyboard_nav = True   # Kumanda sekmesinde klavye yon tuslari ile yonetim
        self.install_grant_perms = False  # -g varsayılan kapalı; kullanıcı ayardan açabilir
        self.auto_connect_last = False   # Acilista son baglanilan cihaza otomatik baglan
        # Bekci baglantiyi geri getirdiginde cihazi uyandir (uyku modundan cikar)
        self.wake_on_reconnect = True
        self.load_warning = ''
        self._recovery_blocked = False
        if load:
            self.load()

    def load(self):
        with self._lock:
            self._load_locked()

    def _load_locked(self):
        self.load_warning = ''
        self._recovery_blocked = False
        warnings = []
        cfg = None
        seen_paths = set()
        for path in (CONFIG_PATH, LEGACY_CONFIG_PATH):
            normalized_path = os.path.normcase(os.path.abspath(path))
            if normalized_path in seen_paths:
                continue
            seen_paths.add(normalized_path)
            if not os.path.exists(path):
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    candidate = json.load(f)
                if not isinstance(candidate, dict):
                    raise ValueError('JSON kökü nesne değil')
                cfg = candidate
                break
            except (OSError, ValueError):
                try:
                    backup = self._preserve_invalid_config(path)
                    warnings.append(
                        'Okunamayan ayar dosyasının yedeği oluşturuldu: {}'
                        .format(backup))
                except OSError as backup_error:
                    self._recovery_blocked = True
                    warnings.append(
                        'Ayar dosyası okunamadı ve güvenli biçimde yedeklenemedi: {} '
                        '({}). Ayarlar bu dosyaya yazılmayacak.'
                        .format(path, backup_error))
        if isinstance(cfg, dict):
            values, value_warnings = self.validated_values(cfg)
            for key, value in values.items():
                setattr(self, key, value)
            warnings.extend(value_warnings)
        self.load_warning = '\n'.join(warnings)
        # NOT: mibox-bilinen-uygulamalar.json ARTIK OKUNMUYOR/YAZILMIYOR.
        # Adlar cihazdan gelir; bu dosya varsa yoksayilir (asagida
        # save_known_apps artik dosyayi SILER).

    @staticmethod
    def validated_values(data, strict=False):
        """Validate known fields without turning malformed values into permissions."""
        if not isinstance(data, dict):
            raise ValueError('Ayar verisi bir JSON nesnesi olmalıdır.')
        boolean_fields = {
            'include_system', 'dark_mode', 'log_to_file', 'screenshot_hd',
            'auto_maint', 'show_unlisted', 'show_removed', 'keyboard_nav',
            'install_grant_perms', 'auto_connect_last', 'wake_on_reconnect',
        }
        text_fields = {'last_target', 'maint_last'}
        integer_limits = {'auto_refresh_min': 35791, 'user_id': 21474}
        values, warnings = {}, []
        for key, value in data.items():
            valid = True
            if key in boolean_fields:
                valid = type(value) is bool
            elif key in text_fields:
                valid = isinstance(value, str)
            elif key in integer_limits:
                valid = type(value) is int and 0 <= value <= integer_limits[key]
            elif key in ('protected', 'device_history'):
                valid = isinstance(value, list) and all(isinstance(x, str) for x in value)
                if valid:
                    value = list(dict.fromkeys(x.strip() for x in value if x.strip()))
                    if key == 'device_history':
                        value = value[:10]
            else:
                continue
            if valid:
                values[key] = value
            else:
                message = 'Geçersiz ayar değeri: {}.'.format(key)
                if strict:
                    raise ValueError(message)
                warnings.append(message + ' Mevcut veya varsayılan değer korunuyor.')
        return values, warnings

    def to_dict(self):
        with self._lock:
            return {
                'last_target': self.last_target,
                'protected': list(self.protected),
                'include_system': self.include_system,
                'dark_mode': self.dark_mode,
                'auto_refresh_min': self.auto_refresh_min,
                'log_to_file': self.log_to_file,
                'device_history': list(self.device_history),
                'screenshot_hd': self.screenshot_hd,
                'auto_maint': self.auto_maint,
                'maint_last': self.maint_last,
                'user_id': self.user_id,
                'show_unlisted': self.show_unlisted,
                'show_removed': self.show_removed,
                'keyboard_nav': self.keyboard_nav,
                'install_grant_perms': self.install_grant_perms,
                'auto_connect_last': self.auto_connect_last,
                'wake_on_reconnect': self.wake_on_reconnect,
            }

    @staticmethod
    def _preserve_invalid_config(path):
        """Copy a broken settings file before a later save can replace it."""
        import datetime
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        base = '{}.corrupt-{}'.format(path, stamp)
        backup = base + '.bak'
        suffix = 1
        while os.path.exists(backup):
            backup = '{}-{}.bak'.format(base, suffix)
            suffix += 1
        shutil.copy2(path, backup)
        return backup

    def _write_atomic(self, data):
        with self._write_lock:
            return self._write_atomic_locked(data)

    def _write_atomic_locked(self, data):
        """JSON'u atomik yaz: tmp -> fsync -> os.replace (tum yazma yollari)."""
        tmp = None
        try:
            os.makedirs(BASE_DIR, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                    mode='w', encoding='utf-8', dir=BASE_DIR,
                    prefix='mibox-ayarlar.json.', suffix='.tmp', delete=False) as f:
                tmp = f.name
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            # Atomik degisim: elektrik kesintisinde yari-yazilmis JSON kalmaz.
            os.replace(tmp, CONFIG_PATH)
            self.save_error = ''
            return True
        except (OSError, TypeError, ValueError) as error:
            try:
                if tmp and os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return self._persistence_failed(
                'Ayar dosyası kaydedilemedi ({}): {}'.format(CONFIG_PATH, error))

    def _persistence_failed(self, message):
        self.save_error = message
        if self._on_persistence_error is not None:
            try:
                self._on_persistence_error(message)
            except Exception:
                pass
        return False

    def save(self):
        with self._write_lock:
            if self._recovery_blocked:
                return self._persistence_failed(
                    'Okunamayan ayar dosyası yedeklenemediği için kayıt engellendi. '
                    'Dosyayı güvenli bir yere kopyalayıp uygulamayı yeniden açın.')
            return self._write_atomic_locked(self.to_dict())

    def save_known_apps(self):
        # LEGACY: artik dosya YAZILMAZ; varsa kalinti temizlenir.
        try:
            if os.path.exists(os.path.join(BASE_DIR, 'mibox-bilinen-uygulamalar.json')):
                os.remove(os.path.join(BASE_DIR, 'mibox-bilinen-uygulamalar.json'))
        except OSError:
            pass
        try:
            if os.path.exists(os.path.join(BASE_DIR, 'MiBox-bilinen-uygulamalar.json')):
                os.remove(os.path.join(BASE_DIR, 'MiBox-bilinen-uygulamalar.json'))
        except OSError:
            pass

    def friendly_name(self, pkg):
        """Uygulama paket adını insan tarafından okunabilir dost ada çevirir."""
        if not pkg or not isinstance(pkg, str):
            return str(pkg or '')
        # 1. Kayıtlı / özelleştirilmiş friendly sözlüğü
        if pkg in self.friendly:
            return self.friendly[pkg]

        # 2. TV Kataloğu (catalog.py)
        try:
            from .catalog import TV_CATALOG
            for item in TV_CATALOG:
                if item.get('package') == pkg or pkg in item.get('alt_packages', []):
                    return item.get('name')
        except Exception:
            pass

        # 3. Debloat Veritabanı (debloat_db.py)
        try:
            from .debloat_db import DEBLOAT_DB
            for cat_list in DEBLOAT_DB.values():
                for entry in cat_list:
                    if entry and entry[0] == pkg:
                        return entry[1]
        except Exception:
            pass

        # 4. Akıllı paket adı biçimlendirme (fallback)
        return prettify_package_name(pkg)

    def is_protected(self, pkg):
        return pkg in self.protected

    def push_history(self, target):
        target = (target or '').strip()
        if not target:
            return False
        with self._lock:
            hist = [t for t in self.device_history if t != target]
            hist.insert(0, target)
            self.device_history = hist[:10]
        return self.save()
