# -*- coding: utf-8 -*-
"""Komut kapisi (gate.py) siniflandirma testleri.

En kritik kural: adb_enabled anahtarini degistiren HICBIR yazim yolu
calismaz (REFUSED). Android bu anahtari '1 degilse ADB kapali' diye
okur; 'false', '.0', '', '0x0' gibi deger varyantlari ADB'yi kapatir ve
yonetim kanali kopar.
"""
import pytest

from mibox_app.gate import classify

# --- REad yollari: teshis komutlari calisir ------------------------------

@pytest.mark.parametrize('cmd', [
    'getprop',
    'getprop ro.product.model',
    'dumpsys battery',
    'dumpsys wifi',
    'dumpsys meminfo -s',
    'pm list packages',
    'pm list packages -3',
    'pm path --user 0 com.example.app',
    'settings get global device_provisioned',
    'wm size',
    'wm density',
    'ip route',
    'logcat -d -t 200',
    'cat /proc/cpuinfo',
    'ps -A',
    'df -h',
    'du -sh /sdcard',
    'ls /sdcard',
    'uptime',
    'cmd package resolve com.example.app',
])
def test_read_komutlari_calisir(cmd):
    assert classify(cmd) == 'READ'


# --- SETTING: goster + calistir ------------------------------------------

@pytest.mark.parametrize('cmd', [
    'settings put global device_provisioned 1',
    'settings put secure user_setup_complete 1',
    'wm size 1920x1080',
    'wm density 320',
    'wm overscan reset',
    'wm overscan 30,30,30,30',
    'cmd package set-home-activity com.example.app/.MainActivity',
])
def test_setting_komutlari(cmd):
    assert classify(cmd) == 'SETTING'


# --- CHANGE: goster + onayla ---------------------------------------------

@pytest.mark.parametrize('cmd', [
    'pm disable-user --user 0 com.example.app',
    'pm enable com.example.app',
    'pm uninstall --user 0 com.example.app',
    'pm clear com.example.app',
    'am force-stop com.example.app',
    'am kill-all',
    'am start --user 0 -n com.example.app/.MainActivity',
    'input keyevent 26',
    'reboot',
    'svc wifi disable',
    'monkey --user 0 -p com.example.app -c android.intent.category.LAUNCHER 1',
    'cmd clipboard set text',
])
def test_change_komutlari(cmd):
    assert classify(cmd) == 'CHANGE'


# --- REFUSED: yikici ve taninmayan komutlar ------------------------------

@pytest.mark.parametrize('cmd', [
    'rm -rf /',
    'rm /sdcard/x',
    'wipe data',
    'factory reset',
    'fastboot flash boot boot.img',
    'su',
    'reboot bootloader',
    'mkfs.ext4 /dev/block/mmcblk0',
    'format /dev/block/sda',
    'dd if=/dev/zero of=/dev/block/sda',
    'getprop; reboot',
    'getprop && reboot',
    'getprop | reboot',
    'getprop `reboot`',
    'getprop $(reboot)',
    'getprop > /sdcard/x',
    'getprop\nreboot',
    'echo merhaba',
    'cat /etc/passwd',
    '',
    '   ',
])
def test_refused_komutlar(cmd):
    assert classify(cmd) == 'REFUSED'


# --- adb_enabled: deger varyantlariyla bypass DENEMELERI -----------------
# Regresyon: 'false' ve '' 0' varyantlari eskiden SETTING sinifina
# dusuyor ve onayla calistirilabiliyordu.

@pytest.mark.parametrize('cmd', [
    'settings put global adb_enabled 0',
    'settings put global adb_enabled 00',
    'settings put global adb_enabled +0',
    'settings put global adb_enabled -0',
    'settings put global adb_enabled false',
    'settings put global adb_enabled .0',
    'settings put global adb_enabled 0x0',
    'settings put global adb_enabled "" 0',
    "settings put global adb_enabled ''", 
    'settings put global adb_enabled "0"',
    'settings put global adb_enabled',
    'settings put global adb_enabled FALSE',
    'settings put global ADB_ENABLED false',
    'settings put global Adb_Enabled 0',
    'settings put secure adb_enabled false',
    'settings put system adb_enabled false',
    'settings put global adb_enabled 0; getprop',
])
def test_adb_enabled_yazma_her_varyantta_reddedilir(cmd):
    assert classify(cmd) == 'REFUSED'


def test_adb_enabled_salt_okunur_sorgu_izinli():
    # Teshis icin okumak serbest; yazmak yasak.
    assert classify('settings get global adb_enabled') == 'READ'


def test_adb_enabled_okuma_fazla_argumanla_reddedilir():
    # 'settings get' kalibina uymayan fazladan argumanli okuma denemesi.
    assert classify('settings get global adb_enabled extra') == 'REFUSED'


def test_dengesiz_tirnak_reddedilir():
    # shlex cozumlemesi basarisizsa komut siniflandirilamaz: REFUSED.
    assert classify('pm list packages "bitmemis') == 'REFUSED'
