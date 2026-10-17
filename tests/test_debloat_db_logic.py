# -*- coding: utf-8 -*-
"""Debloat DB mantik testleri: kategori arama, UAD esleme, bagimlilik, veri sagligi.

Buyuk veri tablolarinin tamami degil, sozlesmeler ve capraz tutarlilik
dogrulanir; favori kaliciligi test_debloat_db_favorites.py icinde.
"""
from mibox_app import debloat_db
from mibox_app.adb_engine import is_valid_package


def test_get_category_bilinen_ve_bilinmeyen():
    assert debloat_db.get_category('guvenli') == \
        debloat_db.DEBLOAT_DB['guvenli']
    assert debloat_db.get_category('hayali') == []


def test_uad_list_of_deseni():
    assert debloat_db.uad_list_of('com.google.android.tvlauncher') == 'Google'
    assert debloat_db.uad_list_of('com.android.chrome') == 'Google'
    assert debloat_db.uad_list_of('com.miui.foo') == 'Oem'
    assert debloat_db.uad_list_of('fusion.android.tv.demo') == 'Oem'
    assert debloat_db.uad_list_of('com.netflix.ninja') == 'Misc'
    assert debloat_db.uad_list_of('com.android.printspooler') == 'Aosp'
    # Hicbir desene uymayan paket varsayilan olarak Misc sayilir.
    assert debloat_db.uad_list_of('org.ornek.app') == 'Misc'


def test_uad_removal_of_kategori_uzerinden():
    assert debloat_db.uad_removal_of(
        'com.google.android.tvrecommendations') == 'Recommended'
    assert debloat_db.uad_removal_of('bilinmeyen.paket') == 'Pending'


def test_uad_removal_of_favori(monkeypatch):
    monkeypatch.setattr(debloat_db, 'user_entries',
                        lambda: [('com.ozel.app', 'Özel', '')])
    assert debloat_db.uad_removal_of('com.ozel.app') == 'Advanced'


def test_needed_by_ters_bag_turetimi():
    assert debloat_db.needed_by('com.google.android.tv') == [
        'com.google.android.tvlauncher',
        'com.google.android.apps.tv.launcherx',
        'com.google.android.leanbacklauncher']
    assert debloat_db.needed_by('com.google.android.gms') == [
        'com.google.android.gsf']
    assert debloat_db.needed_by('com.olmayan.paket') == []

    # Donen liste kopya olmali: cagiran taraf ic haritayi bozamaz.
    kopya = debloat_db.needed_by('com.google.android.gms')
    kopya.append('com.sahte')
    assert debloat_db.needed_by('com.google.android.gms') == [
        'com.google.android.gsf']


def test_all_categories_yapisi(monkeypatch):
    monkeypatch.setattr(debloat_db, 'user_entries',
                        lambda: [('com.a.a', 'A', '')])
    cats = debloat_db.all_categories()

    assert [c[0] for c in cats] == ['guvenli', 'opsiyonel', 'riskli',
                                    'dokunma', 'favoriler']
    assert cats[0][2] == debloat_db.DEBLOAT_DB['guvenli']
    assert cats[-1][2] == [('com.a.a', 'A', '')]
    for key, label, entries in cats:
        assert label, key
        assert isinstance(entries, list), key


def test_package_to_category_db_favori_ve_yok(monkeypatch):
    assert debloat_db.package_to_category(
        'com.google.android.tvrecommendations') == 'guvenli'

    monkeypatch.setattr(debloat_db, 'user_entries',
                        lambda: [('com.ozel.app', 'X', '')])
    assert debloat_db.package_to_category('com.ozel.app') == 'favoriler'
    assert debloat_db.package_to_category('com.olmayan.paket') is None


def test_debloat_db_girdileri_tutarli():
    tum_paketler = []
    for cat, entries in debloat_db.DEBLOAT_DB.items():
        assert entries, cat
        for entry in entries:
            assert isinstance(entry, tuple) and len(entry) == 3, entry
            pkg, name, desc = entry
            assert is_valid_package(pkg), pkg
            assert name and desc, pkg
            tum_paketler.append(pkg)

    # Ayni paket iki kategoride birden olamaz.
    assert len(tum_paketler) == len(set(tum_paketler))


def test_kategori_sabitleri_tam():
    db_cats = set(debloat_db.DEBLOAT_DB)
    assert db_cats == {'guvenli', 'opsiyonel', 'riskli', 'dokunma'}

    etiketli = db_cats | {'favoriler'}
    assert set(debloat_db.CAT_LABELS) == etiketli
    assert set(debloat_db.CAT_COLORS) == etiketli
    assert set(debloat_db.CAT_REMOVAL) == etiketli

    assert set(debloat_db.REMOVAL_TR) == set(debloat_db.REMOVAL_COLOR)
    assert set(debloat_db.CAT_REMOVAL.values()) <= set(debloat_db.REMOVAL_TR)


def test_pkg_cat_haritasi_db_ile_uyumlu():
    for cat, entries in debloat_db.DEBLOAT_DB.items():
        for pkg, _n, _d in entries:
            assert debloat_db._PKG_CAT[pkg] == cat, pkg


def test_bagimliliklar_gecerli_ve_ters_bagli():
    for dependent, deps in debloat_db.DEPENDENCIES.items():
        assert is_valid_package(dependent), dependent
        assert deps, dependent
        for dep in deps:
            assert is_valid_package(dep), dep
            assert dependent in debloat_db.NEEDED_BY[dep], (dependent, dep)
