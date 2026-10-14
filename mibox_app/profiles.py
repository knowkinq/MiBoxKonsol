# -*- coding: utf-8 -*-
"""Hazır debloat profilleri: tek tıkla, açıklamalı, güvenli paket setleri.

Her profil: {key: {'label': ..., 'desc': ..., 'pkgs': [...], 'method': ...}}
method: 'smart' (önerilen) | 'disable' | 'uninstall'
Profiller debloat DB kategorileriyle çapraz doğrulanır; dokunma/riskli
paket içeren profil yüklenirken reddedilir (güvenlik).
"""
from .debloat_db import package_to_category

PROFILES = {
    'minimal': {
        'label': 'Minimal (Güvenli Temizlik)',
        'desc': 'Sponsorlu öneri satırı, demo modu, yazdırma servisleri, '
                'telefon artıkları (SMS/hücre yayını). Günlük TV kullanımı etkilenmez.',
        'method': 'smart',
        'pkgs': [
            'com.google.android.tvrecommendations',
            'fusion.android.tv.demo',
            'com.android.printspooler',
            'com.android.bips',
            'com.google.android.printservice.recommendation',
            'com.android.stk',
            'com.android.cellbroadcastreceiver',
            'com.android.smspush',
            'com.google.android.cellbroadcastreceiver',
            'com.google.android.emergencyassist',
            'com.android.dreams.basic',
            'com.android.dreams.phototable',
            'com.android.wallpaper.livepicker',
            'com.android.wallpaperbackup',
            'com.android.bookmarkprovider',
        ],
    },
    'google': {
        'label': 'Google Servis Diyeti',
        'desc': 'TV de kullanılmayan Google uygulamaları: Haritalar, Gmail, '
                'Dokümanlar, Drive, Çeviri, Fotoğraflar, Takvim senkronu. '
                'Play Store / Play Servisleri / YouTube TV ELLEMEZ.',
        'method': 'smart',
        'pkgs': [
            'com.google.android.apps.maps',
            'com.google.android.apps.gmail',
            'com.google.android.apps.docs',
            'com.google.android.apps.drive',
            'com.google.android.apps.translate',
            'com.google.android.apps.photos',
            'com.google.android.apps.calendar',
            'com.google.android.apps.contacts',
            'com.google.android.feedback',
            'com.google.android.feedbacktv',
            'com.google.android.apps.messaging',
            'com.google.android.apps.dialer',
            'com.google.android.apps.podcasts',
            'com.google.android.apps.search',
            'com.google.android.apps.wallpaper',
            'com.google.android.syncadapters.calendar',
            'com.google.android.syncadapters.contacts',
            'com.google.android.apps.photos.tv',
            'com.google.android.videos',
            'com.google.android.music',
            'com.google.android.books',
            'com.google.android.play.games',
        ],
    },
    'privacy': {
        'label': 'Gizlilik Kalkanı',
        'desc': 'Analitik, geri bildirim, konum geçmişi ve Facebook arka plan '
                'servislerini kapatır. Reklam/öneri trafiğini azaltır.',
        'method': 'disable',
        'pkgs': [
            'com.miui.analytics',
            'com.google.android.feedback',
            'com.google.android.feedbacktv',
            'com.google.android.gms.location.history',
            'com.google.android.gms.supervision',
            'com.facebook.system',
            'com.facebook.appmanager',
            'com.facebook.services',
            'com.google.android.backuptransport',
        ],
    },
    'stream': {
        'label': 'Yayıncı Temizliği',
        'desc': 'Ön yüklü yayın uygulamaları (Netflix/Disney+/Prime/Hulu/Spotify). '
                'İstenirse Play Store dan yeniden kurulabilir. DİKKAT: kullandığın '
                'servisleri listeden çıkar.',
        'method': 'smart',
        'pkgs': [
            'com.netflix.ninja',
            'com.netflix.mediaclient',
            'com.disney.disneyplus',
            'com.amazon.amazonvideo.livingroom',
            'com.amazon.venezia',
            'com.hulu.plus',
            'com.spotify.tv',
            'com.google.android.apps.youtube.music.tv',
            'com.google.android.apps.youtube.kids.tv',
            'com.google.android.apps.youtube.music',
            'com.google.android.apps.youtube.kids',
        ],
    },
    'oem': {
        'label': 'Üretici Artıkları (Xiaomi/TCL/Philips)',
        'desc': 'Üretici demo/ödeme/kılavuz uygulamaları. Kendi markana ait '
                'olmayanları da güvenle kapatır (cihazda yoksa atlanır).',
        'method': 'smart',
        'pkgs': [
            'com.miui.analytics',
            'com.xiaomi.mitv.pay',
            'com.tcl.exhibit',
            'com.tcl.ocean.instructions',
            'com.nvidia.tegrazone',
            'org.droidtv.eum',
            'org.droidtv.android.fitness',
            'com.mediatek.wwtv.mediaplayer',
            'com.google.android.partnersetup',
            'com.google.android.onetimeinitializer',
            'com.google.android.setupwizard',
            'com.android.tungsten.setupwraith',
            'com.google.android.tungsten.setupwraith',
        ],
    },
    'xiaomi_ultra': {
        'label': 'Xiaomi Mi Box & TV Ultra Temizlik',
        'desc': 'Xiaomi telemetrisi, web reklam motoru, Mi TV Plus, Mi Kanal, '
                'OEM sekmeleri, Mi Müzik ve gereksiz Xiaomi servislerini kapatır.',
        'method': 'smart',
        'pkgs': [
            'com.xm.webcontent',
            'com.xiaomi.statistic',
            'com.miui.tv.analytics',
            'com.miui.analytics',
            'com.xiaomo.tv.milegal',
            'com.mitv.tvhome.mitvplus',
            'com.mitv.tvhome.michannel',
            'com.mitv.tvhome.oemtab',
            'com.mitv.gallery',
            'com.xiaomi.mimusic2',
            'com.xiaomi.mitv.pay',
            'com.xiaomi.android.tvsetup.partnercustomizer',
            'com.xiaomi.tvqs.overseas',
        ],
    },
    'low_ram': {
        'label': 'Maksimum RAM & Hızlandırma (1GB / 2GB)',
        'desc': 'Düşük RAM li Mi Box ve TV Stick lerde arka planı temizleyip '
                'bellek kazandırır. Takılmaları ve gecikmeleri azaltır.',
        'method': 'smart',
        'pkgs': [
            'com.xm.webcontent',
            'com.xiaomi.statistic',
            'com.miui.tv.analytics',
            'com.android.adservices.api',
            'com.google.android.tvrecommendations',
            'com.google.android.apps.tv.launcherx.playnext',
            'com.android.printspooler',
            'com.android.bips',
            'com.google.android.printservice.recommendation',
            'com.android.stk',
            'com.android.cellbroadcastreceiver',
            'com.android.smspush',
            'com.google.android.cellbroadcastreceiver',
            'com.google.android.backuptransport',
            'com.google.android.feedback',
            'com.google.android.feedbacktv',
            'com.facebook.system',
            'com.facebook.appmanager',
            'com.facebook.services',
            'com.mitv.tvhome.mitvplus',
            'com.mitv.tvhome.michannel',
            'com.mitv.tvhome.oemtab',
            'com.xiaomi.mimusic2',
        ],
    },
    'google_clean': {
        'label': 'Google TV Reklam & Öneri Temizliği',
        'desc': 'Google TV ana ekranındaki sponsorlu satırlar, partner kurulumları, '
                'reklam servisleri ve izleyicileri temizler.',
        'method': 'smart',
        'pkgs': [
            'com.google.android.tvrecommendations',
            'com.google.android.apps.tv.launcherx.playnext',
            'com.android.adservices.api',
            'com.google.android.partnersetup',
            'com.google.android.onetimeinitializer',
            'com.google.android.feedback',
            'com.google.android.feedbacktv',
            'com.google.android.backuptransport',
        ],
    },
}

# Asla profile giremeyecek kategoriler
FORBIDDEN_CATS = {'dokunma', 'riskli'}


def validate_profile(key):
    """Profili DB'ye karşı doğrula. Dönüş: (temiz_pkgs, reddedilenler)."""
    prof = PROFILES.get(key)
    if not prof:
        return [], [('?', 'profil yok')]
    clean, rejected = [], []
    for pkg in prof['pkgs']:
        cat = package_to_category(pkg)
        if cat in FORBIDDEN_CATS:
            rejected.append((pkg, 'yasak kategori: ' + cat))
        else:
            clean.append(pkg)
    return clean, rejected


def profile_summary(key):
    prof = PROFILES.get(key, {})
    return '{} — {}'.format(prof.get('label', key), prof.get('desc', ''))
