# -*- coding: utf-8 -*-
"""Komut kapısı (tvboxtools 'command gate' uyarlaması).

Serbest konsol yerine sınıflı çalıştırma:
  - READ: getprop/dumpsys/pm list/... → doğrudan çalışır
  - SETTING: settings put/wm size/set-home-activity → göster + çalıştır
  - CHANGE: pm disable-user/pm install/dpm/... → göster + ONAYLA + çalıştır
  - REFUSED: wipe/factory reset/bootloader/su/adb_enabled 0/... → ASLA çalışmaz
"""
import re
import shlex

# Asla çalıştırılmayacaklar (alt-string değil, komut bazında)
REFUSED_PATTERNS = [
    r'[;&|`$<>]', r'\$\(', r'\r|\n',
    r'^\s*rm(?:\s|$)',
    r'\bwipe\b', r'factory\s*reset', r'fastboot', r'\bsu\b',
    r'bootloader', r'adb_enabled\s+0', r'recovery\s+--wipe',
    r'format\s', r'dd\s+if=', r':\(\)\{\s*:\|\:&\s*\};:',
    r'\bmkfs\b', r'\bnewfs\b',
    r'rm\s+(-[a-z]*r[a-z]*\s+)+/(system|vendor|data|sdcard)?(\s|$)',
    r'rm\s+(-[a-z]*r[a-z]*\s+)+/(system|vendor|data|sdcard)?/',
]

READ_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r'getprop(?: [A-Za-z0-9._-]+)?',
    r'dumpsys(?: (?:cpuinfo|battery|wifi|display|power))?',
    r'dumpsys meminfo(?: -s)?',
    r'pm list(?: [A-Za-z0-9._=-]+)*',
    r'pm path(?: --user [0-9]+)? [A-Za-z0-9._]+',
    r'pm dump [A-Za-z0-9._]+',
    r'cmd package (?:query|resolve)(?: [A-Za-z0-9._=/:-]+)*',
    r'cmd appops (?:get|query)(?: [A-Za-z0-9._=/:-]+)*',
    r'settings get [A-Za-z0-9._-]+ [A-Za-z0-9._-]+',
    r'df(?: [A-Za-z0-9._=/-]+)*',
    r'du(?: [A-Za-z0-9._=/-]+)*',
    r'ls(?: [A-Za-z0-9._=/-]+)*',
    r'cat (?:/proc|/sys)(?:/[A-Za-z0-9._-]+)+',
    r'uptime',
    r'wm (?:size|density|overscan)',
    r'ip route(?: (?:show|list)(?: table all)?)?',
    r'logcat -d(?: -t [0-9]+)?',
    r'ps(?: [A-Za-z0-9._=-]+)*',
))

SETTING_PREFIX = (
    'settings put', 'cmd package set-home-activity',
    'cmd appops set', 'am set-standby-bucket',
)

SETTING_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r'wm size [0-9]+x[0-9]+',
    r'wm density [0-9]+',
    r'wm overscan reset',
    r'wm overscan -?[0-9]+,-?[0-9]+,-?[0-9]+,-?[0-9]+',
))

CHANGE_PREFIX = (
    'pm disable-user', 'pm enable', 'pm uninstall', 'pm install',
    'pm clear', 'pm trim', 'am force-stop', 'am kill-all', 'am start', 'appops set', 'dpm ',
    'dumpsys battery set',
    'cmd package install', 'cmd clipboard', 'input ', 'keyevent ', 'screencap',
    'monkey ', 'reboot', 'svc ',
)


def classify(cmdline):
    """Komut satırını sınıfla: READ/SETTING/CHANGE/REFUSED.

    ADB shell argümanları liste olarak verilse de bazı Android sürümleri
    shell metakarakterlerini yorumlayabilir; zincirleme/yönlendirme bu yüzden
    kapıdan geçirilmez.
    """
    c = (cmdline or '').strip()
    low = c.lower()
    for pat in REFUSED_PATTERNS:
        if re.search(pat, low):
            return 'REFUSED'

    # Shell removes quotes and unquoted backslash escapes before Android sees
    # the arguments, so inspect parsed tokens as well as the raw command text.
    try:
        tokens = shlex.split(c)
    except ValueError:
        return 'REFUSED'
    for key, value in zip(tokens, tokens[1:]):
        if key.lower() == 'adb_enabled':
            # Avoid int()'s digit limit: a very long zero string still means 0.
            if re.fullmatch(r'[+-]?0+', value):
                return 'REFUSED'

    def matches_prefix(prefix):
        prefix = prefix.rstrip()
        return low == prefix or low.startswith(prefix + ' ')

    if any(pattern.fullmatch(low) for pattern in SETTING_PATTERNS):
        return 'SETTING'
    for pre in SETTING_PREFIX:
        if matches_prefix(pre):
            return 'SETTING'
    for pre in CHANGE_PREFIX:
        if matches_prefix(pre):
            return 'CHANGE'
    if any(pattern.fullmatch(low) for pattern in READ_PATTERNS):
        return 'READ'
    # Bilinmeyen komutun etkisi öngörülemez; onay kutusu bunu güvenli yapmaz.
    return 'REFUSED'


REFUSED_MSG = ('Bu komut kapı tarafından REDDEDİLDİ (yıkıcı/geri dönüşsüz):\n'
               'yıkıcı komutlar ve tanınmayan shell komutları çalıştırılmaz.')
