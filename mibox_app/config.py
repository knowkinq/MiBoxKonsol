# -*- coding: utf-8 -*-
"""Yapilandirma ve bilinen uygulama adlari (JSON kalicilik).

Thread notu: Config hem UI thread'inden (hedef degisimi, gecmis, ayar
sekmesi) hem kapanis yolundan yazilir. Okuma/yazma RLock ile korunur;
save() tmp + os.replace ile atomiktir.
"""
import json
import os
import sys
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
APK_DIR = os.path.join(BASE_DIR, 'apk-yedekleri')
# Eski buyuk harfli dosya adiyla geriye uyumluluk (kullanicida varsa oku).
LEGACY_CONFIG_PATH = os.path.join(BASE_DIR, 'MiBox-ayarlar.json')

# NOT: Bilinen-uygulama listesi KALDIRILDI (v8.3). Adlar cihazin
# kendisinden okunur (dumpsys package -> application-label). Asagidaki
# tablo yalnizca cihaz etiketsiz eski kayitlarla geriye uyumluluk icin
# durur; yeni kayit YAZILMAZ, sisteme gore hareket edilir.
# TV icin yaygin paketler -> dost ad (LEGACY, salt-okunur yedek)
DEFAULT_FRIENDLY = {
    'ar.tvplayer.tv': 'TiviMate',
    'com.spocky.projengmenu': 'Projectivy Launcher',
    'org.smarttube.stable': 'SmartTube',
    'org.smarttube': 'SmartTube (beta)',
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
    'com.google.android.tv.remote.service': 'TV Remote Servisi',
    'com.google.android.tv.startguide': 'TV Start Guide',
    'com.google.android.tv.settings': 'TV Ayarlar',
    'com.android.settings': 'Sistem Ayarlar',
    'com.android.systemui': 'System UI',
    'com.android.launcher': 'Launcher',
    'com.google.android.tv.home': 'TV Home',
    'com.xiaomi.mibrand': 'Mi Brand',
    'com.miui.tv': 'Mi UI TV',
    'com.xiaomi.mitv': 'Mi TV',
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
}

DEFAULT_PROTECTED = ['ar.tvplayer.tv', 'com.spocky.projengmenu']


class Config:
    def __init__(self):
        self._lock = threading.RLock()
        # Varsayilan kalip: kullanici kendi IP'sini yazar, ilk baglantida
        # kaydedilir. Eskiden sabit ev IP'si gomuluydu (otomatik baglanma
        # sikayeti) — artik bos kalip, otomatik baglanti YOK.
        self.last_target = '192.168.1.x:5555'
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
        self.load()

    def load(self):
        with self._lock:
            self._load_locked()

    def _load_locked(self):
        try:
            cfg = None
            for p in (CONFIG_PATH, LEGACY_CONFIG_PATH):
                if os.path.exists(p):
                    with open(p, 'r', encoding='utf-8') as f:
                        cfg = json.load(f)
                    break
            if isinstance(cfg, dict):
                data = cfg
                if isinstance(data.get('protected'), list):
                    self.protected = [str(p) for p in data['protected']]
                if data.get('last_target'):
                    self.last_target = str(data['last_target'])
                if data.get('include_system') is not None:
                    self.include_system = bool(data['include_system'])
                if data.get('dark_mode') is not None:
                    self.dark_mode = bool(data['dark_mode'])
                if data.get('auto_refresh_min') is not None:
                    try:
                        self.auto_refresh_min = int(data['auto_refresh_min'])
                    except (TypeError, ValueError):
                        self.auto_refresh_min = 0
                if data.get('log_to_file') is not None:
                    self.log_to_file = bool(data['log_to_file'])
                if data.get('device_history'):
                    self.device_history = [str(x) for x in data['device_history']][:10]
                if data.get('screenshot_hd') is not None:
                    self.screenshot_hd = bool(data['screenshot_hd'])
                if data.get('auto_maint') is not None:
                    self.auto_maint = bool(data['auto_maint'])
                if data.get('maint_last'):
                    self.maint_last = str(data['maint_last'])
                if data.get('user_id') is not None:
                    try:
                        self.user_id = int(data['user_id'])
                    except (TypeError, ValueError):
                        self.user_id = 0
                if data.get('show_unlisted') is not None:
                    self.show_unlisted = bool(data['show_unlisted'])
                if data.get('show_removed') is not None:
                    self.show_removed = bool(data['show_removed'])
        except (OSError, ValueError):
            pass
        # NOT: mibox-bilinen-uygulamalar.json ARTIK OKUNMUYOR/YAZILMIYOR.
        # Adlar cihazdan gelir; bu dosya varsa yoksayilir (asagida
        # save_known_apps artik dosyayi SILER).

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
            }

    @staticmethod
    def _write_atomic(data):
        """JSON'u atomik yaz: tmp -> fsync -> os.replace (tum yazma yollari)."""
        tmp = CONFIG_PATH + '.tmp'
        try:
            os.makedirs(BASE_DIR, exist_ok=True)
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            # Atomik degisim: elektrik kesintisinde yari-yazilmis JSON kalmaz.
            os.replace(tmp, CONFIG_PATH)
        except OSError:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass

    def save(self):
        self._write_atomic(self.to_dict())

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
        # Uyumluluk yedeği: onay pencerelerinde ad çözümü için kullanılır.
        # Birincil kaynak cihaz etiketidir (AppScanWorker 'label').
        return self.friendly.get(pkg, pkg)

    def is_protected(self, pkg):
        return pkg in self.protected

    def push_history(self, target):
        target = (target or '').strip()
        if not target:
            return
        with self._lock:
            hist = [t for t in self.device_history if t != target]
            hist.insert(0, target)
            self.device_history = hist[:10]
            data = self.to_dict()
        self._write_atomic(data)
