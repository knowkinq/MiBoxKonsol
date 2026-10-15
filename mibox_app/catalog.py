# -*- coding: utf-8 -*-
"""Popüler ve açık kaynak Android TV uygulamaları kataloğu.

Kullanıcıların harici sitelerden zararlı veya uyumsuz mobil APK aramak
zorunda kalmadan; SmartTube, Stremio, Projectivy, Kodi, VLC gibi TV için optimize
edilmiş en iyi uygulamaları tek tıkla indirip TV'ye kurmasını sağlar.
"""
import os
import tempfile
import urllib.request
from urllib.parse import urlsplit

from .config import DOWNLOADS_DIR

TV_CATEGORIES = [
    'Tümü',
    'Medya & Video',
    'TV Başlatıcı',
    'Dosya & Araçlar',
    'Oyun & Akış',
    'TV Mağazası',
]

TV_CATALOG = [
    {
        'id': 'smarttube_stable',
        'name': 'SmartTube (Kararlı)',
        'category': 'Medya & Video',
        'badge': '★ Çok Popüler',
        'icon': '▶',
        'package': 'org.smarttube.stable',
        'alt_packages': ['com.teamsmart.videomanager.tv', 'com.liskovsoft.videomanager', 'com.liskovsoft.smarttubetv.beta'],
        'author': 'Yuliskov (Açık Kaynak)',
        'description': 'Android TV için en iyi YouTube istemcisi. Reklamsız, SponsorBlock (içerik atlama), 4K/60fps HDR ve arka planda çalma destekli.',
        'url': 'https://github.com/yuliskov/SmartTube/releases/download/latest/smarttube_stable.apk',
        'website': 'https://github.com/yuliskov/SmartTube',
    },
    {
        'id': 'smarttube_beta',
        'name': 'SmartTube (Beta)',
        'category': 'Medya & Video',
        'badge': 'Test',
        'icon': '⚡',
        'package': 'org.smarttube.beta',
        'alt_packages': ['com.liskovsoft.smarttubetv.beta', 'com.liskovsoft.videomanager'],
        'author': 'Yuliskov (Açık Kaynak)',
        'description': 'En yeni SmartTube özellikleri ve erken hata düzeltmelerini içeren test sürümü.',
        'url': 'https://github.com/yuliskov/SmartTube/releases/download/latest/smarttube_beta.apk',
        'website': 'https://github.com/yuliskov/SmartTube',
    },
    {
        'id': 'stremio_tv',
        'name': 'Stremio Android TV',
        'category': 'Medya & Video',
        'badge': '★ Çok Popüler',
        'icon': '📺',
        'package': 'com.stremio.one',
        'author': 'Stremio (Açık Kaynak)',
        'description': 'Film, dizi ve canlı yayınları tek merkezde toplayan popüler akış platformu. Torrent ve debrid eklentileriyle tam uyumlu TV arayüzü.',
        'url': 'https://dl.strem.io/android/v1.10.4-androidTV/com.stremio.one-1.10.4-31048580-armeabi-v7a.apk',
        'website': 'https://stremio.com',
    },
    {
        'id': 'jellyfin_tv',
        'name': 'Jellyfin Android TV',
        'category': 'Medya & Video',
        'badge': 'Açık Kaynak',
        'icon': '🍇',
        'package': 'org.jellyfin.androidtv',
        'author': 'Jellyfin Team (Açık Kaynak)',
        'description': 'Tamamen ücretsiz ve gizlilik odaklı kişisel medya sunucusu istemcisi. Kendi film ve dizi arşivinizi TV’den reklamsız izleyin.',
        'url': 'https://github.com/jellyfin/jellyfin-androidtv/releases/download/v0.19.10/jellyfin-androidtv-v0.19.10-release.apk',
        'website': 'https://jellyfin.org',
    },
    {
        'id': 'projectivy_launcher',
        'name': 'Projectivy Launcher',
        'category': 'TV Başlatıcı',
        'badge': 'Önerilen',
        'icon': '⊞',
        'package': 'com.spocky.projengmenu',
        'author': 'Spocky (Açık Kaynak)',
        'description': 'Android TV için modern, hızlı ve reklam içermeyen alternatif arayüz. Stok Google TV reklamlarını kaldırır ve kanalları özelleştirir.',
        'url': 'https://github.com/spocky/mimir/releases/latest/download/ProjectivyLauncher.apk',
        'website': 'https://github.com/spocky/mimir',
    },
    {
        'id': 'flauncher',
        'name': 'FLauncher',
        'category': 'TV Başlatıcı',
        'badge': 'Hafif',
        'icon': '🚀',
        'package': 'me.efdev.flauncher',
        'author': 'EtienneP (Açık Kaynak)',
        'description': 'Flutter ile geliştirilmiş minimalist, ultra hafif TV başlatıcı. Sıfır reklam, sıfır telemetri ve çok düşük RAM tüketimi.',
        'url': 'https://gitlab.com/etiennep/flauncher/-/jobs/artifacts/master/raw/app-release.apk?job=assembleRelease',
        'website': 'https://gitlab.com/etiennep/flauncher',
    },
    {
        'id': 'kodi_tv',
        'name': 'Kodi Media Center',
        'category': 'Medya & Video',
        'badge': 'Sinema',
        'icon': '🍿',
        'package': 'org.xbmc.kodi',
        'author': 'Kodi Foundation',
        'description': 'Kapsamlı ev sinema merkezi. Yerel arşiv, harici disk/ağ paylaşımı, IPTV ve zengin eklenti ekosistemi.',
        'url': 'https://mirrors.kodi.tv/releases/android/arm/kodi-21.0-Omega-armeabi-v7a.apk',
        'website': 'https://kodi.tv',
    },
    {
        'id': 'vlc_tv',
        'name': 'VLC for Android',
        'category': 'Medya & Video',
        'badge': 'Evrensel',
        'icon': '🎬',
        'package': 'org.videolan.vlc',
        'author': 'VideoLAN (Açık Kaynak)',
        'description': 'Her türlü video ve ses formatını (MKV, MP4, AVI, AC3 vb.) sorunsuz çözen, ağdan (SMB, UPnP) akış destekli efsane oynatıcı.',
        'url': 'https://get.videolan.org/vlc-android/3.5.4/VLC-Android-3.5.4-arm64-v8a.apk',
        'website': 'https://videolan.org',
    },
    {
        'id': 'nova_player',
        'name': 'Nova Video Player',
        'category': 'Medya & Video',
        'badge': 'Açık Kaynak',
        'icon': '🌟',
        'package': 'org.courville.nova',
        'author': 'Nova Team',
        'description': 'Android TV için tasarlanmış açık kaynak video oynatıcı. Filmler ve diziler için otomatik afiş, özet ve altyazı indirir.',
        'url': 'https://github.com/nova-video-player/aos-AVP/releases/download/v6.2.62/Nova-v6.2.62-universal-release.apk',
        'website': 'https://github.com/nova-video-player/aos-AVP',
    },
    {
        'id': 'sftv',
        'name': 'Send Files to TV',
        'category': 'Dosya & Araçlar',
        'badge': 'Pratik',
        'icon': '⇄',
        'package': 'com.yablio.sendfilestotv',
        'author': 'Yablio',
        'description': 'Bilgisayar veya akıllı telefonunuzdan Mi Box’a yerel WiFi üzerinden saniyeler içinde film, APK ve dosya gönderin.',
        'url': 'https://sendfilestotv.app/apk/sftv.apk',
        'website': 'https://sendfilestotv.app',
    },
    {
        'id': 'button_mapper',
        'name': 'Button Mapper',
        'category': 'Dosya & Araçlar',
        'badge': 'Kumanda',
        'icon': '🎮',
        'package': 'flar2.homebutton',
        'author': 'flar2',
        'description': 'Mi Box kumandasındaki tuşları (Netflix, Prime vb.) istediğiniz uygulamaya (örn: SmartTube veya Kodi) yeniden atayın.',
        'url': 'https://buttonmapper.app/download/ButtonMapper.apk',
        'website': 'https://buttonmapper.app',
    },
    {
        'id': 'anexplorer_tv',
        'name': 'AnExplorer TV File Manager',
        'category': 'Dosya & Araçlar',
        'badge': 'Çok Amaçlı',
        'icon': '📁',
        'package': 'dev.dworks.apps.anexplorer',
        'author': 'DWorks (Açık Kaynak)',
        'description': 'Android TV için özel tasarlanmış hafif, çift panelli dosya yöneticisi. USB bellek, ağ paylaşımı (SMB/FTP) ve depolama yönetimi desteği.',
        'url': 'https://raw.githubusercontent.com/1hakr/data/master/apps/files/otherTelevisionFree-release.apk',
        'website': 'https://anexplorer.io/download/tv',
    },
    {
        'id': 'moonlight_tv',
        'name': 'Moonlight Game Streaming',
        'category': 'Oyun & Akış',
        'badge': 'Oyun',
        'icon': '🕹',
        'package': 'com.limelight',
        'author': 'Moonlight Stream (Açık Kaynak)',
        'description': 'Bilgisayarınızdaki PC oyunlarını (Sunshine / NVIDIA Gamestream) TV’nize 4K HDR 60/120 FPS ultra düşük gecikmeyle aktarın.',
        'url': 'https://github.com/moonlight-stream/moonlight-android/releases/download/v12.2/Moonlight-12.2.apk',
        'website': 'https://moonlight-stream.org',
    },
    {
        'id': 'aptoide_tv',
        'name': 'Aptoide TV',
        'category': 'TV Mağazası',
        'badge': 'Mağaza',
        'icon': '🛍',
        'package': 'cm.aptoidetv.pt',
        'author': 'Aptoide',
        'description': 'Android TV için bağımsız alternatif uygulama mağazası. TV uyumlu binlerce uygulamayı doğrudan keşfedin.',
        'url': 'https://aptoide.com/installer-aptoide-tv',
        'website': 'https://tv.aptoide.com',
    },
    {
        'id': 'aurora_store',
        'name': 'Aurora Store',
        'category': 'TV Mağazası',
        'badge': 'Açık Kaynak',
        'icon': '🏪',
        'package': 'com.aurora.store',
        'author': 'Aurora OSS',
        'description': 'Google Play Store açık kaynak istemcisi. TV kütüphanesinde kısıtlı olan Android uygulamalarını güvenle indirin.',
        'url': 'https://gitlab.com/AuroraOSS/AuroraStore/-/releases/permalink/latest/downloads/AuroraStore.apk',
        'website': 'https://aurorastore.com',
    },
]


def get_catalog(category=None, search=None):
    """Kataloğu kategoriye veya arama metnine göre filtreler."""
    items = TV_CATALOG
    if category and category != 'Tümü':
        items = [x for x in items if x.get('category') == category]
    if search:
        s = search.strip().lower()
        items = [x for x in items if s in x['name'].lower() or s in x['description'].lower() or s in x['package'].lower()]
    return list(items)


def download_apk(app_item, dest_dir=None, progress_cb=None, check_cancel=None):
    """Uygulama APK'sini resmi kaynaktan indirir ve yerel dosya yolunu döner."""
    dest_dir = dest_dir or DOWNLOADS_DIR
    os.makedirs(dest_dir, exist_ok=True)

    url = app_item['url']
    parsed_url = urlsplit(url)
    if parsed_url.scheme != 'https' or not parsed_url.hostname:
        raise ValueError('APK indirme adresi güvenli bir HTTPS bağlantısı olmalıdır.')
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })

    with urllib.request.urlopen(req, timeout=35) as resp:
        total_len = int(resp.headers.get('content-length', 0))
        final_url = urlsplit(resp.geturl())
        if final_url.scheme != 'https' or not final_url.hostname:
            raise ValueError('APK indirmesi güvenli bağlantıda kalmadı.')
        max_size = 512 * 1024 * 1024
        if total_len < 0 or total_len > max_size:
            raise ValueError('APK dosyası izin verilen boyut sınırını aşıyor.')
        downloaded = 0
        chunk_size = 64 * 1024

        fd, temp_path = tempfile.mkstemp(
            prefix='{}-'.format(app_item['id']), suffix='.apk.part', dir=dest_dir)
        target_path = temp_path[:-len('.part')]
        try:
            os.close(fd)
            with open(temp_path, 'wb') as f:
                while True:
                    if check_cancel:
                        check_cancel()
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    if downloaded + len(chunk) > max_size:
                        raise ValueError('APK dosyası izin verilen boyut sınırını aşıyor.')
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb and total_len > 0:
                        progress_cb(downloaded, total_len)

            if total_len and downloaded != total_len:
                raise ValueError('APK indirmesi eksik kaldı; dosya kuruluma açılmadı.')

            if check_cancel:
                check_cancel()

            # Tamamlanıp doğrulanmadan .apk yoluna yayımlama.
            with open(temp_path, 'rb') as f:
                head = f.read(4)
            if head != b'PK\x03\x04':
                raise ValueError('İndirilen dosya geçerli bir APK paketi değil.')

            # Her çağrı kendine ait APK yolu döndürür; başka bir indirme,
            # kurulum sürerken ADB'nin okuduğu dosyayı değiştiremez.
            os.replace(temp_path, target_path)
            return target_path
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
