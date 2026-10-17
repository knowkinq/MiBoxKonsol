# -*- coding: utf-8 -*-
"""adb_engine saf yardimci fonksiyon testleri (ADB gerektirmez).

Kapsam: girdi metni transliterasyonu, log maskeleme, paket/bilesen/yol
dogrulama, kullanici id kontrolu, bekci araligi, satir siniri ve PNG
dogrulama/onarim.
"""
import struct
import sys
import zlib

import pytest

from mibox_app.adb_engine import (
    AdbError,
    _base_dir,
    _repair_png,
    check_user_id,
    clamp_lines,
    is_setup_wizard_pkg,
    is_valid_home_component,
    is_valid_package,
    png_is_valid,
    safe_remote_path,
    sanitize_input_text,
    sanitize_log_text,
    target_private_values,
    watchdog_interval,
)

# --- sanitize_input_text --------------------------------------------------

class TestSanitizeInputText:
    def test_turkce_karakterler_ascii_ye_iner(self):
        assert sanitize_input_text('Çğİıöşü') == 'CgIiosu'

    def test_bosluk_yuzde_s_olur(self):
        assert sanitize_input_text('iki kelime') == 'iki%skelime'

    def test_shell_metakarakterleri_atilir(self):
        assert sanitize_input_text('a;b&c|d`e$(f)') == 'abcdef'

    def test_yuzde_islemi_atilir(self):
        # '%' guvenli semboller arasinda degil; bosluk yerine uretilen
        # '%s' ile karismamasi icin ham '%' her zaman atilir.
        assert sanitize_input_text('100%') == '100'

    def test_emoji_ve_unicode_atilir(self):
        # Emoji/CJK atilir; aradaki her bosluk korunur ('%s').
        assert sanitize_input_text('selam 🚀 世界') == 'selam%s%s'

    def test_guvenli_semboller_korunur(self):
        assert sanitize_input_text('a-b_c.d,e:f/g@h+i=j') == 'a-b_c.d,e:f/g@h+i=j'

    def test_tirnak_atilir(self):
        assert sanitize_input_text("it's") == 'its'

    def test_bos_metin(self):
        assert sanitize_input_text('') == ''


# --- sanitize_log_text ----------------------------------------------------

class TestSanitizeLogText:
    def test_url_maskelenir(self):
        assert sanitize_log_text('indiriliyor https://example.com/x.apk tamam') == \
            'indiriliyor ****** tamam'

    def test_ipv4_port_maskelenir(self):
        assert sanitize_log_text('baglandi 192.168.1.20:5555') == 'baglandi ******'

    def test_bilinen_deger_maskelenir(self):
        assert sanitize_log_text('serial R58M123AB okundu', ['R58M123AB']) == \
            'serial ****** okundu'

    def test_bilinen_deger_buyuk_kucuk_harf_duyarsiz(self):
        assert sanitize_log_text('deger ABC123 burada', ['abc123']) == \
            'deger ****** burada'

    def test_tirnakli_yerel_yol_maskelenir(self):
        assert sanitize_log_text('dosya "C:\\Users\\Jim\\a.apk" bulunamadi') == \
            'dosya "******" bulunamadi'

    def test_tirnaksiz_windows_yolu_maskelenir(self):
        assert sanitize_log_text('kaydedildi C:\\temp\\a.zip') == 'kaydedildi ******'

    def test_unix_yolu_maskelenir(self):
        assert sanitize_log_text('hedef /sdcard/Download/x') == 'hedef ******'

    def test_bos_ve_none(self):
        assert sanitize_log_text('') == ''
        assert sanitize_log_text(None) == ''


# --- target_private_values ------------------------------------------------

class TestTargetPrivateValues:
    def test_host_ve_port_ayrilir(self):
        assert target_private_values('192.168.1.20:5555') == \
            ['192.168.1.20:5555', '192.168.1.20']

    def test_koseli_parantezli_ipv6(self):
        assert target_private_values('[fe80::1]:5555') == \
            ['[fe80::1]:5555', 'fe80::1']

    def test_usb_seri_numarasi_tek_deger(self):
        assert target_private_values('emulator-5554') == ['emulator-5554']

    def test_port_sayisal_degilse_bolunmez(self):
        assert target_private_values('usb:notaport') == ['usb:notaport']

    def test_bos_ve_none(self):
        assert target_private_values('   ') == []
        assert target_private_values(None) == []


# --- is_valid_package -----------------------------------------------------

class TestIsValidPackage:
    @pytest.mark.parametrize('pkg', [
        'com.example',
        'com.example.app',
        'a.b.c',
        'com.example_app',
        'com.x:remote',
        'Org.Example9',
    ])
    def test_gecerli(self, pkg):
        assert is_valid_package(pkg)

    @pytest.mark.parametrize('pkg', [
        '',
        ' ',
        'com.',
        '.com',
        'com..x',
        '9com.x',
        'com.x y',
        'com.x;reboot',
        'com.x/y',
        'com.x$y',
        '-com.x',
        'com.x\ny',
        None,
    ])
    def test_gecersiz(self, pkg):
        assert not is_valid_package(pkg)


# --- safe_remote_path -----------------------------------------------------

class TestSafeRemotePath:
    def test_basa_slash_eklenir(self):
        assert safe_remote_path('sdcard/DCIM') == '/sdcard/DCIM'

    def test_cift_slash_ve_nokta_sadelestirilir(self):
        assert safe_remote_path('/sdcard//DCIM/./Camera') == '/sdcard/DCIM/Camera'

    def test_kok_dizin(self):
        assert safe_remote_path('/') == '/'
        assert safe_remote_path('') == '/'

    @pytest.mark.parametrize('path', [
        '/sdcard/a/../b',
        '/sdcard/..',
        '/..',
        '../x',
    ])
    def test_ust_dizine_cikis_reddedilir(self, path):
        with pytest.raises(AdbError):
            safe_remote_path(path)

    @pytest.mark.parametrize('path', [
        '/sdcard/a\nb',
        '/sdcard/a\x00b',
        '/sdcard/a\tb',
    ])
    def test_kontrol_karakteri_reddedilir(self, path):
        with pytest.raises(AdbError):
            safe_remote_path(path)


# --- is_valid_home_component ----------------------------------------------

class TestIsValidHomeComponent:
    @pytest.mark.parametrize('comp', [
        'com.foo/.MainActivity',
        'com.foo/com.foo.MainActivity',
        'com.foo/.A$B',
        'com.foo/.MainActivity$Inner',
    ])
    def test_gecerli(self, comp):
        assert is_valid_home_component(comp)

    @pytest.mark.parametrize('comp', [
        '',
        'com.foo',
        'com.foo/',
        '/.MainActivity',
        'com.foo/.A B',
        'com.foo/.A;rm',
        'com.foo\\/.MainActivity',
        None,
    ])
    def test_gecersiz(self, comp):
        assert not is_valid_home_component(comp)


# --- check_user_id ----------------------------------------------------------

class TestCheckUserId:
    @pytest.mark.parametrize('value,expected', [
        (0, 0),
        (13, 13),
        ('5', 5),
        (' 5 ', 5),
        ('021', 21),
        (21474, 21474),
    ])
    def test_gecerli(self, value, expected):
        assert check_user_id(value) == expected

    @pytest.mark.parametrize('value', [
        -1,
        21475,
        True,
        False,
        None,
        '',
        'abc',
        '0x2',
        1.5,
    ])
    def test_gecersiz(self, value):
        with pytest.raises(AdbError):
            check_user_id(value)


# --- watchdog_interval ------------------------------------------------------

class TestWatchdogInterval:
    @pytest.mark.parametrize('fail_count,expected', [
        (0, 15),
        (1, 15),
        (2, 30),
        (3, 60),
        (50, 60),
    ])
    def test_varsayilan_taban(self, fail_count, expected):
        assert watchdog_interval(fail_count) == expected

    def test_sayisiz_deger_tabani_dondurur(self):
        assert watchdog_interval('abc') == 15
        assert watchdog_interval(None) == 15

    def test_ozel_taban_ve_ust_sinir(self):
        assert watchdog_interval(2, base=10, max_interval=25) == 20
        assert watchdog_interval(2, base=20, max_interval=25) == 25
        assert watchdog_interval(5, base=10, max_interval=25) == 25


# --- clamp_lines -------------------------------------------------------------

class TestClampLines:
    @pytest.mark.parametrize('value,expected', [
        (None, 200),
        ('abc', 200),
        ('50', 50),
        (0, 1),
        (-3, 1),
        (99999, 2000),
        (200, 200),
    ])
    def test_varsayilan_sinirlar(self, value, expected):
        assert clamp_lines(value) == expected

    def test_ozel_sinirlar(self):
        assert clamp_lines(5, 3, 0, 10) == 5
        assert clamp_lines(100, 3, 0, 10) == 10
        assert clamp_lines('abc', 3, 0, 10) == 3


# --- PNG dogrulama / onarim ---------------------------------------------------

def _chunk(kind, payload):
    return (struct.pack('>I', len(payload)) + kind + payload
            + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff))


def _minimal_png(bit_depth=8, color_type=6):
    """1x1 piksel, gecerli chunk yapisi ve CRC'lerle PNG uretir."""
    ihdr = struct.pack('>IIBBBBB', 1, 1, bit_depth, color_type, 0, 0, 0)
    raw = b'\x00' + b'\xff\x00\x00\xff'  # filtre bayti + tek RGBA piksel
    return (b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', ihdr)
            + _chunk(b'IDAT', zlib.compress(raw)) + _chunk(b'IEND', b''))


class TestPngIsValid:
    def test_gecerli_png_kabul_edilir(self):
        assert png_is_valid(_minimal_png())

    def test_bos_ve_kisa_veri_reddedilir(self):
        assert not png_is_valid(b'')
        assert not png_is_valid(None)
        assert not png_is_valid(_minimal_png()[:20])

    def test_yanlis_imza_reddedilir(self):
        broken = b'XXXX' + _minimal_png()[4:]
        assert not png_is_valid(broken)

    def test_bozuk_crc_reddedilir(self):
        data = bytearray(_minimal_png())
        data[20] ^= 0xff  # IHDR govdesinde bir biti cevir
        assert not png_is_valid(bytes(data))

    def test_iend_eksikse_reddedilir(self):
        assert not png_is_valid(_minimal_png()[:-12])

    def test_gecersiz_bit_derinligi_reddedilir(self):
        assert not png_is_valid(_minimal_png(bit_depth=4, color_type=6))

    def test_gecersiz_renk_tipi_reddedilir(self):
        assert not png_is_valid(_minimal_png(color_type=7))

    def test_ikinci_ihdr_reddedilir(self):
        base = _minimal_png()
        ihdr_chunk = base[8:33]
        broken = base[:33] + ihdr_chunk + base[33:]
        assert not png_is_valid(broken)

    def test_chunk_uzunlugu_veriyi_asarsa_reddedilir(self):
        data = bytearray(_minimal_png())
        struct.pack_into('>I', data, 8, 1000)
        assert not png_is_valid(bytes(data))

    def test_ilk_chunk_ihdr_degilse_reddedilir(self):
        data = (b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', b'\x00' * 12)
                + _chunk(b'IDAT', b'\x00'))
        assert not png_is_valid(data)

    def test_ilk_chunk_turu_ihdr_degilse_reddedilir(self):
        data = (b'\x89PNG\r\n\x1a\n' + _chunk(b'IDAT', b'\x00' * 20)
                + _chunk(b'IEND', b''))
        assert not png_is_valid(data)

    def test_idat_aradan_sonra_tekrar_ederse_reddedilir(self):
        data = (_minimal_png()[:33]
                + _chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00\xff'))
                + _chunk(b'tEXt', b'k\x00v')
                + _chunk(b'IDAT', zlib.compress(b'\x00')))
        assert not png_is_valid(data)

    def test_bos_olmayan_iend_reddedilir(self):
        data = (_minimal_png()[:33]
                + _chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00\xff'))
                + _chunk(b'IEND', b'abcd'))
        assert not png_is_valid(data)

    def test_idat_olmadan_iend_reddedilir(self):
        data = _minimal_png()[:33] + _chunk(b'IEND', b'')
        assert not png_is_valid(data)

    def test_iend_sonrasi_cop_reddedilir(self):
        assert not png_is_valid(_minimal_png() + b'cop')


class TestRepairPng:
    def test_gecerli_veri_aynen_doner(self):
        data = _minimal_png()
        assert _repair_png(data) == data

    def test_bos_ve_cop_veri_none_doner(self):
        assert _repair_png(b'') is None
        assert _repair_png(b'bu bir png degil') is None

    def test_cift_cr_bozulmasi_onarilir(self):
        data = _minimal_png()
        broken = data.replace(b'\r\n', b'\r\r\n')
        assert broken != data
        assert _repair_png(broken) == data


# --- _base_dir ----------------------------------------------------------------

class TestBaseDir:
    def test_dondurulmus_exe_klasoru_kullanilir(self, monkeypatch, tmp_path):
        exe = tmp_path / 'MiBoxKonsol.exe'
        exe.write_bytes(b'x')
        monkeypatch.setattr(sys, 'frozen', True, raising=False)
        monkeypatch.setattr(sys, 'executable', str(exe))
        assert _base_dir() == str(tmp_path)

    def test_kaynak_agaci_ust_klasoru_kullanilir(self):
        import os

        import mibox_app
        beklenen = os.path.dirname(os.path.dirname(
            os.path.abspath(mibox_app.__file__)))
        assert _base_dir() == beklenen


# --- is_setup_wizard_pkg ------------------------------------------------------

class TestIsSetupWizardPkg:
    def test_bos_ve_none_reddedilir(self):
        assert is_setup_wizard_pkg('') is False
        assert is_setup_wizard_pkg(None) is False

    def test_tam_liste_ve_kuyruk_eslesir(self):
        assert is_setup_wizard_pkg('com.android.provision') is True
        assert is_setup_wizard_pkg('com.foo.SetupWizard') is True
        assert is_setup_wizard_pkg('com.ornek.uygulama') is False
