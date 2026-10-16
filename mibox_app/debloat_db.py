# -*- coding: utf-8 -*-
"""Kategorili Android TV / Mi Box bloatware veritabani.

Kategoriler:
  - 'guvenli'   : Kaldirilmasi guvenli, TV deneyimini bozmaz
  - 'opsiyonel' : Kaldirilabilir ama bazen kullanilir
  - 'riskli'    : Kaldirmak sistemi bozabilir, dikkatli
  - 'dokunma'   : ASLA kaldirmayin (sistem kritik)
  - 'favoriler' : Kullanicinin ekledigi ozel girisler (kalici JSON)

Her giris: (paket, ad, aciklama)
"""
import json
import os
import tempfile

from .adb_engine import is_valid_package

DEBLOAT_DB = {
    'guvenli': [
        ('com.google.android.feedback', 'Geri Bildirim', 'Hata bildirme araci. TV de gereksiz.'),
        ('com.google.android.feedbacktv', 'TV Geri Bildirim', 'TV hata bildirme.'),
        ('com.google.android.setupwizard', 'Kurulum Sihirbazi', 'İlk kurulumdan sonra gereksiz.'),
        ('com.google.android.gsf', 'Google Hesap Servisleri', 'Hesap senkronizasyonu. TV de nadir kullanılır.'),
        ('com.google.android.gsf.login', 'Google Login', 'Google giris ekranlari.'),
        ('com.google.android.apps.tachyon', 'Google Cast', 'Cast araci. TV de zaten var.'),
        ('com.google.android.apps.gmdm', 'Google Device Manager', 'Cihaz yonetimi.'),
        ('com.google.android.apps.photos.tv', 'Photos TV', 'Fotograf galerisi TV.'),
        ('com.google.android.apps.maps', 'Haritalar', 'TV de kullanilmaz.'),
        ('com.google.android.apps.translate', 'Ceviri', 'TV de kullanilmaz.'),
        ('com.google.android.apps.wellbeing', 'Screen Time', 'Ekranda süre. TV de anlamsiz.'),
        ('com.google.android.apps.safetyhub', 'Güvenlik Merkezi', 'Telefon uyarıları.'),
        ('com.google.android.apps.docs', 'Google Dokumanlar', 'Ofis uygulamaları.'),
        ('com.google.android.apps.drive', 'Drive', 'Bulut depolama.'),
        ('com.google.android.apps.calendar', 'Takvim', 'TV de kullanilmaz.'),
        ('com.google.android.apps.youtube.music.tv', 'YouTube Music TV', 'Muzik TV. İsteğe bağlı.'),
        ('com.google.android.apps.youtube.kids.tv', 'YouTube Kids TV', 'Cocuk modu TV.'),
        ('com.google.android.apps.assistant.tv', 'Asistan TV', 'TV sesli asistan. İsteğe bağlı.'),
        ('com.google.android.apps.games.tv', 'Oyunlar TV', 'Oyun merkezi TV. TV de gereksiz.'),
        ('com.google.android.apps.pdfviewer', 'PDF Goruntuleyici', 'TV de kullanilmaz.'),
        ('com.google.android.apps.podcasts', 'Podcastler', 'TV de kullanilmaz.'),
        ('com.google.android.apps.search', 'Arama', 'TV de kullanilmaz.'),
        ('com.google.android.apps.wallpaper', 'Duvarkagidi', 'TV de kullanilmaz.'),
        ('com.google.android.apps.talkback', 'TalkBack', 'Ekran okuyucu. İsteğe bağlı.'),
        ('com.google.android.apps.youtube.music', 'YouTube Music', 'Telefon muzik uygulamasi TV de gereksiz.'),
        ('com.google.android.apps.youtube.kids', 'YouTube Kids', 'Telefon cocuk uygulamasi.'),
        ('com.google.android.apps.assistant', 'Google Asistan', 'Telefon asistani.'),
        ('com.google.android.apps.games', 'Google Oyunlar', 'Telefon oyun merkezi.'),
        ('com.google.android.apps.photos', 'Google Fotograflar', 'Telefon galerisi.'),
        ('com.google.android.apps.messaging', 'Mesajlar', 'SMS uygulamasi TV de gereksiz.'),
        ('com.google.android.apps.dialer', 'Telefon', 'Arama uygulamasi TV de gereksiz.'),
        ('com.google.android.apps.contacts', 'Kisiler', 'TV de kullanilmaz.'),
        ('com.google.android.apps.gmail', 'Gmail', 'TV de kullanilmaz.'),
        # --- UAD + TV/Xiaomi genisletme (v3.2) ---
        ('com.google.android.tvrecommendations', 'TV Oneriler', 'Ana ekrandaki sponsorlu içerik satiri. Kaldırınca arayuz hizlanir.'),
        ('fusion.android.tv.demo', 'Demo Modu', 'Magaza demo uygulamasi.'),
        ('org.droidtv.android.fitness', 'Fitness TV', 'Philips egzersiz uygulamasi.'),
        ('com.android.printspooler', 'Yazdirma Biriktirici', 'TV de yazici yok.'),
        ('com.android.bips', 'BIPS Yazdirma', 'Dahili yazdirma servisi. TV de gereksiz.'),
        ('com.google.android.printservice.recommendation', 'Yazdirma Onerisi', 'Yazici oneri servisi.'),
        ('com.google.android.syncadapters.calendar', 'Takvim Senkron', 'Takvim senkron adaptoru.'),
        ('com.google.android.syncadapters.contacts', 'Kisi Senkron', 'Kisi senkron adaptoru.'),
        ('com.google.android.backuptransport', 'Yedekleme Tasiyici', 'Bulut yedegi. TV de gereksiz.'),
        ('com.google.android.onetimeinitializer', 'İlk Kurulum Artigi', 'Kurulum sonrasi gereksiz.'),
        ('com.google.android.partnersetup', 'Partner Kurulum', 'Operatör ozellestirme kurulumu.'),
        ('com.google.android.videos', 'Play Filmler', 'Film magazasi TV uygulamasi.'),
        ('com.google.android.music', 'Play Muzik', 'Kullanim dışı muzik uygulamasi.'),
        ('com.google.android.books', 'Play Kitaplar', 'TV de kullanilmaz.'),
        ('com.google.android.play.games', 'Play Oyunlar', 'Oyun merkezi. TV de gereksiz.'),
        ('com.google.android.marvin.talkback', 'TalkBack (sistem)', 'Ekran okuyucu sistem servisi. İsteğe bağlı.'),
        ('com.android.dreams.basic', 'Temel Ruya', 'Ekran koruyucu animasyonlari.'),
        ('com.android.dreams.phototable', 'Fotograf Masasi', 'Ekran koruyucu slayt.'),
        ('com.android.wallpaper.livepicker', 'Canli Duvarkagidi Secici', 'Canli duvar kagidi secimi.'),
        ('com.android.wallpaperbackup', 'Duvarkagidi Yedegi', 'Duvar kagidi yedek servisi.'),
        ('com.android.stk', 'SIM Araclari', 'TV de SIM kart yok.'),
        ('com.android.cellbroadcastreceiver', 'Hucre Yayini', 'Acil durum yayinlari. TV de gereksiz.'),
        ('com.android.smspush', 'WAP Push', 'SMS push servisi. TV de gereksiz.'),
        ('com.android.bookmarkprovider', 'Yer Isareti Saglayici', 'Tarayici yer isaretleri.'),
        ('com.google.android.projection.gearhead', 'Android Auto', 'Araba bağlantısı. TV de gereksiz.'),
        ('com.google.ar.lens', 'Google Lens', 'Gorsel arama. TV de gereksiz.'),
        ('com.google.android.contacts', 'Kisiler (Google)', 'Google kisi uygulamasi. TV de gereksiz.'),
        ('com.google.android.apps.kids.familylink', 'Family Link', 'Ebeveyn denetimi. TV de nadir.'),
        ('com.google.android.apps.restore', 'Veri Geri Yükleme', 'Telefon gecis araci. TV de gereksiz.'),
        ('com.google.android.gms.supervision', 'Supervision', 'Denetim servisi parcasi.'),
        ('com.android.companiondevicemanager', 'Refakatci Cihaz', 'Telefon eşleştirme. TV de gereksiz.'),
        ('com.google.android.nearby.halfsheet', 'Yakin Paylasim UI', 'Nearby Share arayuzu. TV de gereksiz.'),
        ('com.android.hotwordenrollment.okgoogle', 'OK Google Kayıt', 'Ses eşleştirme kaydi.'),
        ('com.android.hotwordenrollment.xgoogle', 'X Google Kayıt', 'Ses eşleştirme kaydi.'),
        ('com.android.tungsten.setupwraith', 'Kurulum Hayaleti', 'Kurulum artik servisi.'),
        ('com.google.android.tungsten.setupwraith', 'Kurulum Hayaleti (Google TV)',
         'Google TV kurulum sihirbazi; HOME/launcher ayarini kilitler.'),
        ('com.facebook.system', 'Facebook Sistem', 'Facebook arka plan servisi.'),
        ('com.facebook.appmanager', 'Facebook Yoneticisi', 'Facebook uygulama yonetimi.'),
        ('com.facebook.services', 'Facebook Servisleri', 'Facebook servisleri.'),
        ('com.netflix.ninja', 'Netflix TV', 'On yuklu Netflix. Istenirse Store dan kurulabilir.'),
        ('com.netflix.mediaclient', 'Netflix Mobil', 'Telefon Netflix istemcisi.'),
        ('com.disney.disneyplus', 'Disney+', 'On yuklu Disney+. İsteğe bağlı.'),
        ('com.amazon.amazonvideo.livingroom', 'Prime Video TV', 'On yuklu Prime Video. İsteğe bağlı.'),
        ('com.amazon.venezia', 'Amazon Appstore', 'Amazon magazasi. Kullanilmiyorsa kaldırılabilir.'),
        ('com.hulu.plus', 'Hulu', 'On yuklu Hulu. İsteğe bağlı.'),
        ('com.spotify.tv', 'Spotify TV', 'On yuklu Spotify. İsteğe bağlı.'),
        ('com.mediatek.wwtv.mediaplayer', 'MediaTek Oynatici', 'Uretici video oynatici yedegi.'),
        ('org.droidtv.eum', 'EUM Sozlesme', 'Philips kullanim sozlesmesi ekrani.'),
        ('com.tcl.exhibit', 'TCL Sergi', 'TCL magaza demo icerigi.'),
        ('com.tcl.ocean.instructions', 'TCL Kilavuz', 'TCL kullanim kilavuzu.'),
        ('com.nvidia.tegrazone', 'TegraZone', 'Nvidia oyun merkezi. Shield da isteğe bağlı.'),
        ('com.miui.analytics', 'Mi Analitik', 'Xiaomi kullanim analitigi. Gizlilik için kaldırılabilir.'),
        ('com.xiaomi.mitv.pay', 'Mi Odeme TV', 'Xiaomi TV odeme servisi. Kullanilmiyorsa gereksiz.'),
        ('com.xm.webcontent', 'Xiaomi Web Reklam', 'Xiaomi arayüzündeki reklam ve sponsorlu web önerilerini çeker. Güvenle kaldırılabilir.'),
        ('com.xiaomi.statistic', 'Xiaomi Telemetri', 'Arka planda kullanım verilerini Xiaomi sunucularına gönderir. Kapatılması RAM ve CPU tasarrufu sağlar.'),
        ('com.miui.tv.analytics', 'MIUI TV Analitik', 'Xiaomi TV kullanıcı davranış analitiği.'),
        ('com.xiaomo.tv.milegal', 'Xiaomi Yasal Şartlar', 'İlk kurulum sonrası gereksiz Xiaomi sözleşme servisi.'),
        ('com.mitv.tvhome.mitvplus', 'Mi TV Plus', 'Ücretsiz TV kanalları ve reklam satırları sunar. Kullanılmıyorsa kaldırılabilir.'),
        ('com.mitv.tvhome.michannel', 'Mi Kanal', 'Mi TV kanal entegrasyonu.'),
        ('com.mitv.tvhome.oemtab', 'Mi TV OEM Sekmesi', 'Ana ekranda OEM sekmesini barındırır. Standart deneyim için gereksizdir.'),
        ('com.mitv.gallery', 'Mi Galeri', 'Xiaomi resim galerisi.'),
        ('com.xiaomi.mimusic2', 'Mi Müzik 2', 'Ön yüklü Xiaomi müzik uygulaması.'),
        ('com.android.adservices.api', 'Android Reklam Servisleri', 'Gizlilik Sandbox ve reklam izleme servisi.'),
        ('com.xiaomi.android.tvsetup.partnercustomizer', 'Xiaomi Partner Özelleştirici', 'İlk kurulum operatör ve bölge özelleştirme artığı.'),
        ('com.xiaomi.tvqs.overseas', 'Xiaomi TV Hızlı Ayarlar', 'Yurtdışı model telemetrisi ve hızlı ayar artıkları.'),
        ('com.google.android.apps.tv.launcherx.playnext', 'Google TV Sırada Ne Var', 'Google TV ana ekranındaki sponsorlu satırlar.'),
        ('com.xiaomi.mitv.updateservice', 'Xiaomi TV Güncelleme', 'Xiaomi TV OTA güncelleme servisi. İsteğe bağlı.'),
    ],
    'opsiyonel': [
        ('com.android.chrome', 'Chrome', 'Tarayici. TV de gereksiz ama bazen kullanılır.'),
        ('com.google.android.webview', 'WebView', 'Uygulamalar için web goruntuleyici. Kaldirmayin eger uygulamalar bozuluyorsa.'),
        ('com.google.android.inputmethod.latin', 'Gboard', 'Klavye. TV de nadir kullanılır.'),
        ('com.google.android.tv.inputmethod', 'TV Klavye', 'TV klavye.'),
        ('com.google.android.documentsui', 'Dosya Secici', 'Dosya seçme arayuzu.'),
        ('com.google.android.tts', 'Text-to-Speech', 'Metin seslendirme.'),
        ('com.google.android.providers.userdictionary', 'Kullanıcı Sözlük', 'Klavye sözlük.'),
        ('com.google.android.wifi.dialog', 'Wi-Fi Diyalog', 'Wi-Fi baglanti diyaloğu.'),
        ('com.google.android.captiveportallogin', 'Captive Portal', 'Ag giris sayfasi.'),
        ('com.android.providers.calendar', 'Takvim Provider', 'Takvim verisi.'),
        ('com.android.providers.contacts', 'Kiysiler Provider', 'Kiysiler verisi.'),
        ('com.android.providers.telephony', 'Telephony Provider', 'Telefon verisi. TV de gereksiz.'),
        # --- v3.2 ekleri ---
        ('com.google.android.apps.mediashell', 'Media Shell', 'Chromecast alici kabugu. Cast kullanilmiyorsa opsiyonel.'),
        ('com.google.android.tvlauncher', 'Eski TV Launcher', 'Eski launcher; Projectivy gibi alternatif kullaniliyorsa kapatilabilir (önce yedek launcher kurulu olsun!).'),
        ('com.google.android.apps.tv.launcherx', 'Yeni TV Launcher', 'Yeni launcher; alternatif launcher kuruluysa kapatilabilir.'),
        ('com.google.android.leanbacklauncher', 'Leanback Launcher', 'Leanback ana ekran; alternatif varsa kapatilabilir.'),
        ('com.android.tv.settings', 'TV Ayarlar (AOSP)', 'AOSP TV ayarlar uygulamasi.'),
        ('com.example.android.livecubes', 'Live Cubes', 'Ornek canli duvar kagidi.'),
        ('com.google.android.gms.location.history', 'Konum Geçmişi', 'Konum gecmisi servisi. TV de gereksiz.'),
        ('com.google.android.carrierwizard', 'Operatör Sihirbaz', 'Operatör kurulum sihirbazi.'),
        ('com.google.android.carriersetup', 'Operatör Kurulum', 'Operatör ozellestirme.'),
        ('com.android.carrierconfig', 'Operatör Yapılandırma', 'Operatör ayarları deposu. Kaldırma yerine birakmak daha güvenli.'),
        ('com.google.android.configupdater', 'Yapılandırma Guncelleyici', 'Sertifika/yapilandirma guncelleyici. Genelde zararsiz ama gereksiz.'),
        ('com.google.android.modulemetadata', 'Modul Metadata', 'Mainline modul bilgisi.'),
        ('com.google.android.permissioncontroller', 'İzin Denetleyici Notu', 'ANA izin servisi degil, ek bilesen; genelde birakilir.'),
        ('com.google.android.cellbroadcastreceiver', 'Hucre Yayini (Google)', 'Google hucre yayini alicisi. TV de gereksiz.'),
        ('com.google.android.emergencyassist', 'Acil Yardim', 'Acil durum bilgisi. TV de gereksiz.'),
        ('com.mitv.videoplayer', 'Mi Video Oynatıcı', 'Xiaomi varsayılan video oynatıcısı. VLC veya Just Player varsa kaldırılabilir.'),
        ('com.xiaomi.mitv.mediaexplorer', 'Mi Medya Tarayıcı', 'USB medya tarayıcısı; alternatif dosya yöneticisi varsa kaldırılabilir.'),
        ('com.xiaomi.mitv.smartshare', 'Mi Smart Share', 'Xiaomi kablosuz ekran yansıtma.'),
        ('com.google.android.katniss', 'Google Asistan (TV)', 'Kumandadan sesli arama yapmıyorsanız kapatılabilir.'),
        ('com.google.android.apps.tv.dreamx', 'Google TV Ekran Koruyucu', 'Özel ekran koruyucu kullanıyorsanız kaldırılabilir.'),
        ('com.google.android.youtube.tvmusic', 'YouTube Music TV', 'TV YouTube Müzik uygulaması.'),
    ],
    'riskli': [
        ('com.google.android.gms', 'Google Play Servisleri', 'CRITICAL: Çok uygulama buna bağlı. KALDIRMAYIN.'),
        ('com.google.android.gms.tv', 'Google Play Servisleri (TV)', 'TV için GMS. Çok uygulama buna bağlı.'),
        ('com.android.vending', 'Google Play Store', 'Uygulama marketi. Kaldirirseniz yeni uygulama kuramazsiniz.'),
        ('com.google.android.tv', 'Android TV (Launcher)', 'ANA LAUNCHER. KALDIRMAYIN.'),
        ('com.google.android.tv.home', 'TV Home', 'TV ana ekran.'),
        ('com.google.android.tv.startguide', 'TV Start Guide', 'TV baslangic rehberi.'),
        ('com.google.android.tv.settings', 'TV Ayarlar', 'TV ayarlar.'),
        ('com.google.android.tv.unifiedsettings', 'TV Unify Ayarlar', 'TV birlesik ayarlar.'),
        ('com.android.settings', 'Sistem Ayarlar', 'Sistem ayarlar. KALDIRMAYIN.'),
        ('com.android.systemui', 'System UI', 'Sistem arayuzu. KALDIRMAYIN.'),
        ('com.android.launcher', 'Launcher', 'Ana launcher. KALDIRMAYIN.'),
        ('com.xiaomi.mibrand', 'Mi Brand', 'Xiaomi marka. TV de kritik olabilir.'),
        ('com.miui.tv', 'Mi UI TV', 'Xiaomi TV arayuzu. KALDIRMAYIN.'),
        ('com.xiaomi.mitv', 'Mi TV', 'Xiaomi TV. KALDIRMAYIN.'),
        ('com.google.android.tv.remote.service', 'TV Remote Servisi', 'TV kumanda servisi. Dikkatli.'),
        ('com.google.android.tv.remotelauncher', 'TV Remote Launcher', 'TV kumanda launcher.'),
        ('com.google.android.tv.remote', 'TV Remote', 'TV kumanda.'),
        ('com.google.android.media.providers', 'Media Providers', 'Medya provider. Dikkatli.'),
        ('com.android.providers.media.module', 'Media Provider', 'Medya provider. Dikkatli.'),
        ('com.google.android.networkstack', 'Network Stack', 'Ag stack. Dikkatli.'),
        ('com.google.android.ext.services', 'Ext Servisler', 'Genisletme servisleri.'),
        ('com.google.android.ext.shared', 'Ext Shared', 'Genisletme paylasim.'),
    ],
    'dokunma': [
        ('com.android.shell', 'Shell', 'ADB shell. KALDIRMAYIN.'),
        ('com.android.providers.settings', 'Ayarlar Provider', 'Sistem ayarlar verisi.'),
        ('com.android.providers.blockednumber', 'Engellenen Numaralar', 'Engellenen numaralar.'),
        ('com.android.providers.applications', 'Uygulama Provider', 'Uygulama verisi.'),
        ('com.android.providers.partnerbookmarks', 'Partner Bookmarks', 'Partner yer imleri.'),
        ('com.android.providers.partnersync', 'Partner Sync', 'Partner senkron.'),
        ('com.android.providers.userdictionary', 'User Dictionary', 'Kullanıcı sözlük.'),
        ('com.dolby.android.audio.service', 'Dolby Audio Servisi', 'Ses çıkışını ve Dolby ses işlemcisini yönetir. ASLA KALDIRMAYIN!'),
        ('com.droidlogic', 'Droidlogic Platform', 'SoC donanım ve işlemci sürücüleri. ASLA KALDIRMAYIN!'),
        ('com.android.bluetooth', 'Bluetooth Servisi', 'TV kumandasının Bluetooth bağlantısını sağlar. ASLA KALDIRMAYIN!'),
    ],
}


def get_category(name):
    """Kategori dondurur. Her giris (paket, ad, aciklama) tuple."""
    return DEBLOAT_DB.get(name, [])


CAT_LABELS = {
    'guvenli': 'Güvenli',
    'opsiyonel': 'Opsiyonel',
    'riskli': 'Riskli',
    'dokunma': 'Dokunma',
    'favoriler': 'Favoriler',
}

CAT_COLORS = {
    'guvenli': '#a6e3a1',
    'opsiyonel': '#89b4fa',
    'riskli': '#f9e2af',
    'dokunma': '#f38ba8',
    'favoriler': '#94e2d5',
}

# Hızlı paket -> kategori haritasi (modul yuklenirken bir kez olusturulur)
_PKG_CAT = {}
for _cat, _entries in DEBLOAT_DB.items():
    for _p, _n, _d in _entries:
        _PKG_CAT[_p] = _cat


# ---------------------------------------------------------------------------
# UAD (Universal Android Debloater) uyumluluk katmanı — v6.0.0
# Kaynaklar: 0x192/UAD + Universal-Debloater-Alliance/UAD-NG wiki.
# removal: Recommended/Advanced/Expert/Unsafe (UAD-NG 'removal' alanı)
# list: Google/Misc/Oem/Aosp/Pending/Carrier (UAD-NG 'list' alanı)
# dependencies/neededBy: kesin gerekli bağlar (UAD-NG, auto-remove YOK,
# sadece uyarı — UAD davranışı birebir).
# ---------------------------------------------------------------------------

# kategori -> UAD removal seviyesi
CAT_REMOVAL = {
    'guvenli': 'Recommended',
    'opsiyonel': 'Advanced',
    'riskli': 'Expert',
    'dokunma': 'Unsafe',
    'favoriler': 'Advanced',
}

REMOVAL_TR = {
    'Recommended': 'Önerilen',
    'Advanced': 'İleri',
    'Expert': 'Uzman',
    'Unsafe': 'Güvensiz',
}

REMOVAL_COLOR = {
    'Recommended': '#a6e3a1',
    'Advanced': '#89b4fa',
    'Expert': '#f9e2af',
    'Unsafe': '#f38ba8',
}

# Paket üreten taraf -> UAD 'list' alanı (öncelik sırasına göre eşleşir)
_LIST_PATTERNS = [
    (('com.google.', 'com.android.chrome', 'com.android.vending'), 'Google'),
    (('com.xiaomi.', 'com.miui.', 'com.tcl.', 'com.mediatek.',
       'org.droidtv.', 'com.nvidia.', 'fusion.'), 'Oem'),
    (('com.facebook.', 'com.netflix.', 'com.amazon.', 'com.disney.',
       'com.spotify.', 'com.hulu.'), 'Misc'),
    (('com.android.',), 'Aosp'),
]


def uad_list_of(pkg):
    """Paketin UAD 'list' alanı: Google/Misc/Oem/Aosp/Carrier."""
    for prefixes, lst in _LIST_PATTERNS:
        for pre in prefixes:
            if pkg.startswith(pre):
                return lst
    return 'Misc'


def uad_removal_of(pkg):
    """Paketin UAD 'removal' seviyesi (kategori üzerinden)."""
    return CAT_REMOVAL.get(package_to_category(pkg) or '', 'Pending')


# Bağımlılıklar: kaldırılınca BOZULAN taraf -> gerekli paketler.
# UAD-NG gibi auto-remove yok; kullanıcı uyarılır, seçimden çıkarabilir.
DEPENDENCIES = {
    # launcher'sız kalma koruması
    'com.google.android.tvlauncher': ['com.google.android.tv'],
    'com.google.android.apps.tv.launcherx': ['com.google.android.tv'],
    'com.google.android.leanbacklauncher': ['com.google.android.tv'],
    # webview bağımlıları
    'com.google.android.webview': ['com.android.chrome'],
    # hesap servisleri
    'com.google.android.gsf.login': ['com.google.android.gsf'],
    'com.google.android.gsf': ['com.google.android.gms'],
}

# Ters bağlar (otomatik türetilir): neededBy[p] = p'ye ihtiyaç duyanlar
NEEDED_BY = {}
for _dependent, _deps in DEPENDENCIES.items():
    for _d in _deps:
        NEEDED_BY.setdefault(_d, []).append(_dependent)


def dependencies_of(pkg):
    """Paketin ihtiyaç duydukları (kaldırınca bunlara dikkat)."""
    return list(DEPENDENCIES.get(pkg, []))


def needed_by(pkg):
    """Bu pakete ihtiyaç duyanlar (bunu kaldırınca bunlar bozulabilir)."""
    return list(NEEDED_BY.get(pkg, []))


def all_categories():
    """Tum kategorileri dondurur: [(isim, etiket, girisler), ...]"""
    return [
        ('guvenli', 'Güvenli (Kaldırılabilir)', DEBLOAT_DB['guvenli']),
        ('opsiyonel', 'Opsiyonel (İsteğe Bağlı)', DEBLOAT_DB['opsiyonel']),
        ('riskli', 'Riskli (Dikkatli)', DEBLOAT_DB['riskli']),
        ('dokunma', 'Dokunma (Kritik)', DEBLOAT_DB['dokunma']),
        ('favoriler', 'Favoriler (Kendin Ekladigin)', user_entries()),
    ]


def all_packages():
    """Tum kategorilerdeki tum paketleri tek liste olarak dondurur (tekil)."""
    out = []
    seen = set()
    for cat in ('guvenli', 'opsiyonel', 'riskli', 'dokunma'):
        for pkg, _n, _d in DEBLOAT_DB.get(cat, []):
            if pkg not in seen:
                seen.add(pkg)
                out.append(pkg)
    return out


# ---------------------------------------------------------------------------
# Kullanicinin ekledigi ozel (favori) debloat girisleri
# ---------------------------------------------------------------------------
_FAVORITES = []
_user_entries_loaded = False
_user_entries_load_error = ''


def _user_entries_path():
    from .config import BASE_DIR
    # DIKKAT: dosya adi VERIDIR (etiket degil). Cevrilirse kullanicinin
    # kaydettigi favoriler bulunamaz.
    return os.path.join(BASE_DIR, 'debloat-kullanici.json')


def _save_user_entries():
    """Persist favorites atomically so an interrupted write keeps the old file."""
    path = _user_entries_path()
    directory = os.path.dirname(path)
    fd = None
    temporary_path = None
    try:
        os.makedirs(directory, exist_ok=True)
        fd, temporary_path = tempfile.mkstemp(
            prefix='.mibox-debloat-favorites-', suffix='.tmp', dir=directory)
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            fd = None
            json.dump(_FAVORITES, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                os.remove(temporary_path)
            except OSError:
                pass


def _load_user_entries():
    global _user_entries_loaded, _user_entries_load_error
    if _user_entries_loaded:
        return
    _user_entries_loaded = True
    try:
        path = _user_entries_path()
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        if not isinstance(data, list):
            raise ValueError('Dosya kökünde liste bekleniyordu.')
        loaded = []
        for index, item in enumerate(data, 1):
            if (not isinstance(item, list) or len(item) < 3
                    or not all(isinstance(value, str) for value in item[:3])):
                raise ValueError('{} numaralı kayıt bozuk.'.format(index))
            pkg = item[0].strip()
            if not is_valid_package(pkg) or ':' in pkg:
                raise ValueError('{} numaralı kaydın paket adı geçersiz.'.format(index))
            loaded.append((pkg, item[1], item[2]))
        _FAVORITES.extend(loaded)
    except (OSError, ValueError):
        try:
            _user_entries_load_error = (
                'Kullanıcı favori dosyası okunamadı: {}. Dosyanın yedeğini alıp '
                'düzeltene kadar üzerine yazılmayacak.'.format(_user_entries_path()))
        except OSError:
            _user_entries_load_error = 'Kullanıcı favori dosyası okunamadı; üzerine yazılmayacak.'


def _ensure_user_entries_writable():
    _load_user_entries()
    if _user_entries_load_error:
        raise OSError(_user_entries_load_error)


def user_entries():
    """Kullanicinin 'Favorilere Ekle' ile ekledigi girisleri [(pkg, ad, aciklama),...]."""
    _load_user_entries()
    return list(_FAVORITES)


def add_user_entry(pkg, name, desc, category='guvenli'):
    """Yeni favori girisi ekler ve kalici olarak yazar. Geri: True (eklendi)/False."""
    if not isinstance(pkg, str):
        raise ValueError('Geçerli bir Android paket adı girin.')
    pkg = pkg.strip()
    if not is_valid_package(pkg) or ':' in pkg:
        raise ValueError('Geçerli bir Android paket adı girin.')
    _ensure_user_entries_writable()
    # Zaten DB'de veya kullanici listesinde mi?
    existing = set()
    for entries in DEBLOAT_DB.values():
        for p, _n, _d in entries:
            existing.add(p)
    for p, _n, _d in _FAVORITES:
        existing.add(p)
    if pkg in existing:
        return False
    entry = (pkg, str(name or pkg).strip()[:128] or pkg,
             str(desc or '').strip()[:512])
    _FAVORITES.append(entry)
    try:
        _save_user_entries()
    except Exception:
        _FAVORITES.pop()
        raise
    return True


def remove_user_entries(pkgs):
    """Remove favorites as one transaction; retain the old list on write failure."""
    _ensure_user_entries_writable()
    selected = {pkg for pkg in pkgs if isinstance(pkg, str)}
    before = list(_FAVORITES)
    remaining = [entry for entry in before if entry[0] not in selected]
    if len(remaining) == len(before):
        return False
    _FAVORITES[:] = remaining
    try:
        _save_user_entries()
    except Exception:
        _FAVORITES[:] = before
        raise
    return True


def remove_user_entry(pkg):
    return remove_user_entries((pkg,))


def get_category_with_user(name):
    """get_category + kullanici girileri. 'guvenli' icinde kullanicinin
    ekledigi favoriler de gorunur (sona eklenir)."""
    base = list(DEBLOAT_DB.get(name, []))
    if name == 'guvenli':
        for pkg, n, d in user_entries():
            if pkg not in [p for p, _n, _dd in base]:
                base.append((pkg, n, d))
    return base


def package_to_category_with_user(pkg):
    """package_to_category + kullanici favorileri (favoriler->None yerine 'favoriler')."""
    cat = _PKG_CAT.get(pkg)
    if cat:
        return cat
    for p, _n, _d in user_entries():
        if p == pkg:
            return 'favoriler'
    return None


def package_to_category(pkg):
    """Paketin hangi kategoride oldugunu bulur. Yoksa None. (O(1))"""
    cat = _PKG_CAT.get(pkg)
    if cat:
        return cat
    # favorileri de tara (yavas yol, sadece bulunamazsa)
    for p, _n, _d in user_entries():
        if p == pkg:
            return 'favoriler'
    return None
