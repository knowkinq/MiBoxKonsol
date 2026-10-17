# -*- coding: utf-8 -*-
"""config.py: kalıcılık, doğrulama ve kurtarma testleri.

Gerçek ayar dosyasına dokunulmaz: BASE_DIR/CONFIG_PATH/LEGACY_CONFIG_PATH
geçici klasöre yönlendirilir.
"""
import datetime
import json
import sys

import pytest

from mibox_app import config


@pytest.fixture
def cfg_ortam(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(config, 'CONFIG_PATH', str(tmp_path / 'mibox-ayarlar.json'))
    monkeypatch.setattr(config, 'LEGACY_CONFIG_PATH',
                        str(tmp_path / 'MiBox-ayarlar.json'))
    return tmp_path


# --- prettify_package_name ---------------------------------------------------

@pytest.mark.parametrize('pkg,beklenen', [
    ('com.example.myapp', 'Myapp'),
    ('tv.example.player', 'Example Player'),
    ('com.foo.tv', 'Foo TV'),
    ('com.example.videoPlayer', 'Video Player'),
    ('com.example.my_video_app', 'My Video App'),
    ('me.efdev.flauncher', 'Flauncher'),
    ('___', '___'),
    ('', ''),
    (None, ''),
])
def test_prettify_package_name(pkg, beklenen):
    assert config.prettify_package_name(pkg) == beklenen


def test_prettify_sadece_onek_sozcukleri():
    # Tum parcalar onek listesindeyse son parca kullanilir.
    assert config.prettify_package_name('com.org.net') == 'Net'


# --- _base_dir ---------------------------------------------------------------

def test_base_dir_frozen_exe_klasoru(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'MiBoxKonsol.exe'))
    assert config._base_dir() == str(tmp_path)


# --- varsayılanlar -----------------------------------------------------------

def test_config_varsayilanlar(cfg_ortam):
    cfg = config.Config(load=False)
    assert cfg.last_target == ''
    assert cfg.protected == []
    assert cfg.dark_mode is True
    assert cfg.keyboard_nav is True
    assert cfg.install_grant_perms is False
    assert cfg.auto_connect_last is False
    assert cfg.wake_on_reconnect is True
    assert cfg.user_id == 0
    assert cfg.save_error == ''
    assert cfg.load_warning == ''


def test_to_dict_alanlari(cfg_ortam):
    cfg = config.Config(load=False)
    assert set(cfg.to_dict()) == {
        'last_target', 'protected', 'include_system', 'dark_mode',
        'auto_refresh_min', 'log_to_file', 'device_history', 'screenshot_hd',
        'auto_maint', 'maint_last', 'user_id', 'show_unlisted', 'show_removed',
        'keyboard_nav', 'install_grant_perms', 'auto_connect_last',
        'wake_on_reconnect',
    }


# --- save / load -------------------------------------------------------------

def test_save_load_gidis_donus(cfg_ortam):
    cfg = config.Config(load=False)
    cfg.last_target = 'tv-1'
    cfg.protected = ['com.a', 'com.b']
    cfg.device_history = ['tv-1', 'tv-2']
    cfg.auto_refresh_min = 30
    cfg.user_id = 2
    cfg.dark_mode = False
    cfg.include_system = True
    assert cfg.save() is True
    assert (cfg_ortam / 'mibox-ayarlar.json').exists()
    geri = config.Config()
    assert geri.last_target == 'tv-1'
    assert geri.protected == ['com.a', 'com.b']
    assert geri.device_history == ['tv-1', 'tv-2']
    assert geri.auto_refresh_min == 30
    assert geri.user_id == 2
    assert geri.dark_mode is False
    assert geri.include_system is True
    assert geri.load_warning == ''


def test_save_klasoru_olusturur(tmp_path, monkeypatch):
    alt = tmp_path / 'alt'
    monkeypatch.setattr(config, 'BASE_DIR', str(alt))
    monkeypatch.setattr(config, 'CONFIG_PATH', str(alt / 'mibox-ayarlar.json'))
    monkeypatch.setattr(config, 'LEGACY_CONFIG_PATH', str(alt / 'MiBox-ayarlar.json'))
    cfg = config.Config(load=False)
    assert cfg.save() is True
    assert (alt / 'mibox-ayarlar.json').exists()


def test_load_dosya_yoksa_varsayilan(cfg_ortam):
    cfg = config.Config()
    assert cfg.dark_mode is True
    assert cfg.load_warning == ''


def test_load_bozuk_json_yedekler(cfg_ortam):
    (cfg_ortam / 'mibox-ayarlar.json').write_text('{bozuk', encoding='utf-8')
    cfg = config.Config()
    assert 'yedeği oluşturuldu' in cfg.load_warning
    yedekler = list(cfg_ortam.glob('mibox-ayarlar.json.corrupt-*.bak'))
    assert len(yedekler) == 1
    assert yedekler[0].read_text(encoding='utf-8') == '{bozuk'
    assert cfg.dark_mode is True


def test_load_kok_nesne_degilse_yedekler(cfg_ortam):
    (cfg_ortam / 'mibox-ayarlar.json').write_text('[1, 2]', encoding='utf-8')
    cfg = config.Config()
    assert 'yedeği oluşturuldu' in cfg.load_warning
    assert list(cfg_ortam.glob('mibox-ayarlar.json.corrupt-*.bak'))


def test_load_eski_dosyaya_duser(cfg_ortam):
    # Windows'ta 'MiBox-ayarlar.json' ile 'mibox-ayarlar.json' ayni dosyadir
    # (buyuk/kucuk harf duyarsiz); diger platformlarda yedek yol okunur.
    (cfg_ortam / 'MiBox-ayarlar.json').write_text('{"dark_mode": false}',
                                                  encoding='utf-8')
    cfg = config.Config()
    assert cfg.dark_mode is False
    assert cfg.load_warning == ''


def test_load_yeni_dosya_varsa_eskiyi_yok_sayar(tmp_path, monkeypatch):
    # Windows'ta gercek adlar ayni dosyaya cikar; sira testi icin ayrik
    # bir yedek ad kullanilir.
    monkeypatch.setattr(config, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(config, 'CONFIG_PATH', str(tmp_path / 'mibox-ayarlar.json'))
    monkeypatch.setattr(config, 'LEGACY_CONFIG_PATH',
                        str(tmp_path / 'eski-ayarlar.json'))
    (tmp_path / 'mibox-ayarlar.json').write_text('{"dark_mode": true}',
                                                 encoding='utf-8')
    (tmp_path / 'eski-ayarlar.json').write_text('{"dark_mode": false}',
                                                encoding='utf-8')
    cfg = config.Config()
    assert cfg.dark_mode is True


def test_load_gecersiz_deger_uyari_ve_varsayilan(cfg_ortam):
    (cfg_ortam / 'mibox-ayarlar.json').write_text(
        '{"dark_mode": 1, "auto_refresh_min": -5, "user_id": 99999}',
        encoding='utf-8')
    cfg = config.Config()
    assert 'dark_mode' in cfg.load_warning
    assert 'auto_refresh_min' in cfg.load_warning
    assert 'user_id' in cfg.load_warning
    assert cfg.dark_mode is True
    assert cfg.auto_refresh_min == 0
    assert cfg.user_id == 0


def test_load_yedeklenemeyen_dosya_kaydi_engeller(cfg_ortam):
    (cfg_ortam / 'mibox-ayarlar.json').mkdir()
    cfg = config.Config()
    assert 'yedeklenemedi' in cfg.load_warning
    assert cfg.save() is False
    assert 'engellendi' in cfg.save_error
    assert (cfg_ortam / 'mibox-ayarlar.json').is_dir()


def test_save_hatasi_callback(tmp_path, monkeypatch):
    engel = tmp_path / 'engel.txt'
    engel.write_text('x', encoding='utf-8')
    monkeypatch.setattr(config, 'BASE_DIR', str(engel))
    monkeypatch.setattr(config, 'CONFIG_PATH', str(tmp_path / 'mibox-ayarlar.json'))
    monkeypatch.setattr(config, 'LEGACY_CONFIG_PATH',
                        str(tmp_path / 'MiBox-ayarlar.json'))
    mesajlar = []
    cfg = config.Config(load=False, on_persistence_error=mesajlar.append)
    assert cfg.save() is False
    assert cfg.save_error
    assert mesajlar and mesajlar[0] == cfg.save_error


def test_write_atomic_wrapper_kaydeder(cfg_ortam):
    cfg = config.Config(load=False)
    assert cfg._write_atomic({'last_target': 'tv-9'}) is True
    kayit = json.loads((cfg_ortam / 'mibox-ayarlar.json').read_text(
        encoding='utf-8'))
    assert kayit == {'last_target': 'tv-9'}


def test_write_atomic_serilestirme_hatasi_temizler(cfg_ortam, monkeypatch):
    cfg = config.Config(load=False)

    def patlak_remove(path):
        raise OSError('silinemez')

    monkeypatch.setattr(config.os, 'remove', patlak_remove)

    assert cfg._write_atomic({'bozuk': object()}) is False
    assert 'kaydedilemedi' in cfg.save_error


def test_persistence_failed_callback_hatasi_yutulur():
    def patlak_callback(mesaj):
        raise RuntimeError('callback patladi')

    cfg = config.Config(load=False, on_persistence_error=patlak_callback)
    assert cfg._persistence_failed('deneme') is False
    assert cfg.save_error == 'deneme'


def test_preserve_invalid_config_yedek_adi_cakismasi(tmp_path, monkeypatch):
    gercek_dt = datetime.datetime

    class SabitDatetime:
        @staticmethod
        def now():
            return gercek_dt(2024, 1, 2, 3, 4, 5)

    monkeypatch.setattr(datetime, 'datetime', SabitDatetime)
    bozuk = tmp_path / 'bozuk.json'
    bozuk.write_text('{', encoding='utf-8')
    taban = str(bozuk) + '.corrupt-20240102-030405'
    (tmp_path / 'bozuk.json.corrupt-20240102-030405.bak').write_text(
        'eski', encoding='utf-8')

    sonuc = config.Config._preserve_invalid_config(str(bozuk))

    assert sonuc == taban + '-1.bak'
    assert (tmp_path / 'bozuk.json.corrupt-20240102-030405-1.bak').read_text(
        encoding='utf-8') == '{'


# --- validated_values --------------------------------------------------------

def test_validated_values_sozluk_degilse_hata():
    with pytest.raises(ValueError):
        config.Config.validated_values([1, 2])


def test_validated_values_gecerli_alanlar():
    values, warnings = config.Config.validated_values({
        'dark_mode': False,
        'last_target': 'tv-1',
        'auto_refresh_min': 35791,
        'user_id': 21474,
        'protected': [' com.a ', 'com.a', '', 'com.b'],
        'device_history': ['t{}'.format(i) for i in range(15)],
        'bilinmeyen': 'yok sayilir',
    })
    assert warnings == []
    assert values['dark_mode'] is False
    assert values['last_target'] == 'tv-1'
    assert values['auto_refresh_min'] == 35791
    assert values['user_id'] == 21474
    assert values['protected'] == ['com.a', 'com.b']
    assert values['device_history'] == ['t{}'.format(i) for i in range(10)]
    assert 'bilinmeyen' not in values


@pytest.mark.parametrize('veri', [
    {'dark_mode': 1},
    {'auto_refresh_min': 35792},
    {'user_id': -1},
    {'last_target': 5},
    {'protected': ['com.a', 3]},
    {'device_history': 'tv-1'},
])
def test_validated_values_gecersiz_uyari(veri):
    values, warnings = config.Config.validated_values(veri)
    assert values == {}
    assert warnings and 'Geçersiz ayar değeri' in warnings[0]


def test_validated_values_strict_hata():
    with pytest.raises(ValueError):
        config.Config.validated_values({'dark_mode': 1}, strict=True)


# --- geçmiş / koruma / ad çözümleme ------------------------------------------

def test_push_history_siralar_ve_kaydeder(cfg_ortam):
    cfg = config.Config(load=False)
    assert cfg.push_history('tv-1') is True
    assert cfg.device_history == ['tv-1']
    assert cfg.push_history('tv-2') is True
    assert cfg.device_history == ['tv-2', 'tv-1']
    assert cfg.push_history('tv-1') is True
    assert cfg.device_history == ['tv-1', 'tv-2']
    assert (cfg_ortam / 'mibox-ayarlar.json').exists()


def test_push_history_bos_hedef_false(cfg_ortam):
    cfg = config.Config(load=False)
    assert cfg.push_history('') is False
    assert cfg.push_history(None) is False
    assert cfg.device_history == []


def test_push_history_on_ile_sinirli(cfg_ortam):
    cfg = config.Config(load=False)
    for i in range(12):
        cfg.push_history('tv-{}'.format(i))
    assert cfg.device_history == ['tv-{}'.format(i) for i in range(11, 1, -1)]


def test_is_protected(cfg_ortam):
    cfg = config.Config(load=False)
    cfg.protected = ['com.a']
    assert cfg.is_protected('com.a') is True
    assert cfg.is_protected('com.b') is False


def test_friendly_name_ozel_sozluk(cfg_ortam):
    cfg = config.Config(load=False)
    cfg.friendly = {'com.ozel': 'Özel Ad'}
    assert cfg.friendly_name('com.ozel') == 'Özel Ad'


def test_friendly_name_katalogdan(cfg_ortam, monkeypatch):
    from mibox_app import catalog
    monkeypatch.setattr(catalog, 'TV_CATALOG', [
        {'package': 'com.test.katalog', 'name': 'Katalog Adı'},
        {'package': 'com.test.diger', 'alt_packages': ['com.test.alternatif'],
         'name': 'Alternatif Ad'},
    ])
    cfg = config.Config(load=False)
    cfg.friendly = {}
    assert cfg.friendly_name('com.test.katalog') == 'Katalog Adı'
    assert cfg.friendly_name('com.test.alternatif') == 'Alternatif Ad'


def test_friendly_name_debloatdan(cfg_ortam, monkeypatch):
    from mibox_app import debloat_db
    monkeypatch.setattr(debloat_db, 'DEBLOAT_DB', {
        'Test': [None, (), ('com.test.debloat', 'Debloat Adı', 'aciklama')],
    })
    cfg = config.Config(load=False)
    cfg.friendly = {}
    assert cfg.friendly_name('com.test.debloat') == 'Debloat Adı'


def test_friendly_name_fallback_bicimlendirir(cfg_ortam):
    cfg = config.Config(load=False)
    cfg.friendly = {}
    assert cfg.friendly_name('com.test.unknownthing') == 'Unknownthing'


def test_friendly_name_bos_ve_str_olmayan(cfg_ortam):
    cfg = config.Config(load=False)
    assert cfg.friendly_name('') == ''
    assert cfg.friendly_name(None) == ''
    assert cfg.friendly_name(123) == '123'


def test_friendly_name_katalog_import_hatasi_yok_sayilir(cfg_ortam,
                                                         monkeypatch):
    monkeypatch.setitem(sys.modules, 'mibox_app.catalog', None)
    cfg = config.Config(load=False)
    cfg.friendly = {}
    assert cfg.friendly_name('com.ornek.bilinmeyen') == 'Bilinmeyen'


def test_friendly_name_debloat_import_hatasi_yok_sayilir(cfg_ortam,
                                                         monkeypatch):
    monkeypatch.setitem(sys.modules, 'mibox_app.debloat_db', None)
    cfg = config.Config(load=False)
    cfg.friendly = {}
    assert cfg.friendly_name('com.ornek.bilinmeyen') == 'Bilinmeyen'


# --- save_known_apps ---------------------------------------------------------

def test_save_known_apps_legacy_dosyalari_siler(cfg_ortam):
    (cfg_ortam / 'mibox-bilinen-uygulamalar.json').write_text('{}', encoding='utf-8')
    (cfg_ortam / 'MiBox-bilinen-uygulamalar.json').write_text('{}', encoding='utf-8')
    cfg = config.Config(load=False)
    cfg.save_known_apps()
    assert not (cfg_ortam / 'mibox-bilinen-uygulamalar.json').exists()
    assert not (cfg_ortam / 'MiBox-bilinen-uygulamalar.json').exists()
    cfg.save_known_apps()  # dosyalar yokken hata vermez


def test_save_known_apps_silme_hatasi_yutulur(cfg_ortam, monkeypatch):
    hedef = cfg_ortam / 'mibox-bilinen-uygulamalar.json'
    hedef.write_text('{}', encoding='utf-8')

    def patlak_remove(path):
        raise OSError('silinemez')

    monkeypatch.setattr(config.os, 'remove', patlak_remove)
    config.Config(load=False).save_known_apps()

    assert hedef.exists()
