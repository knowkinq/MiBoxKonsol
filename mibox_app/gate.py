# -*- coding: utf-8 -*-
"""Komut kapısı (tvboxtools 'command gate' uyarlaması).

Serbest konsol yerine sınıflı çalıştırma:
  - READ: getprop/dumpsys/pm list/... → doğrudan çalışır
  - SETTING: settings put/wm size/set-home-activity → göster + çalıştır
  - CHANGE: pm disable-user/pm install/dpm/... → göster + ONAYLA + çalıştır
  - REFUSED: wipe/factory reset/bootloader/su/adb_enabled 0/... → ASLA çalışmaz
"""
import re

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

READ_PREFIX = (
    'getprop', 'dumpsys', 'pm list', 'pm path', 'pm dump', 'cmd package query',
    'cmd package resolve', 'cmd appops get', 'cmd appops query', 'settings get',
    'df', 'du ', 'du\t', 'ls', 'cat /proc', 'cat /sys', 'uptime', 'wm size', 'wm density',
    'wm overscan', 'ip route', 'logcat -d', 'ps',
)

SETTING_PREFIX = (
    'settings put', 'wm size ', 'wm density ', 'wm overscan ', 'cmd package set-home-activity',
    'cmd appops set', 'am set-standby-bucket',
)

CHANGE_PREFIX = (
    'pm disable-user', 'pm enable', 'pm uninstall', 'pm install',
    'pm clear', 'pm trim', 'am force-stop', 'am kill-all', 'am start', 'appops set', 'dpm ',
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
    for pre in READ_PREFIX:
        if low.startswith(pre):
            return 'READ'
    for pre in SETTING_PREFIX:
        if low.startswith(pre):
            return 'SETTING'
    for pre in CHANGE_PREFIX:
        if low.startswith(pre):
            return 'CHANGE'
    # Bilinmeyen komutun etkisi öngörülemez; onay kutusu bunu güvenli yapmaz.
    return 'REFUSED'


REFUSED_MSG = ('Bu komut kapı tarafından REDDEDİLDİ (yıkıcı/geri dönüşsüz):\n'
               'yıkıcı komutlar ve tanınmayan shell komutları çalıştırılmaz.')
