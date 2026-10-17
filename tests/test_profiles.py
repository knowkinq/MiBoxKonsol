# -*- coding: utf-8 -*-
"""Profil testleri: sema tutarliligi, paket gecerliligi, yasak kategori reddi."""
from mibox_app.adb_engine import is_valid_package
from mibox_app.profiles import (
    FORBIDDEN_CATS,
    PROFILES,
    profile_summary,
    validate_profile,
)


def test_profil_semasi_tutarli():
    assert PROFILES
    for key, prof in PROFILES.items():
        assert prof['label'], key
        assert prof['desc'], key
        assert prof['method'] in ('smart', 'disable', 'uninstall'), key
        assert prof['pkgs'], key
        assert len(prof['pkgs']) == len(set(prof['pkgs'])), key


def test_profil_paketleri_gecerli_bicimde():
    for key, prof in PROFILES.items():
        for pkg in prof['pkgs']:
            assert is_valid_package(pkg), '{}: {}'.format(key, pkg)


def test_profiller_yasak_kategori_icermez():
    assert FORBIDDEN_CATS == {'dokunma', 'riskli'}
    for key, prof in PROFILES.items():
        clean, rejected = validate_profile(key)
        assert rejected == [], '{}: {}'.format(key, rejected)
        assert clean == list(prof['pkgs'])


def test_validate_profile_bilinmeyen_profil():
    assert validate_profile('hayali') == ([], [('?', 'profil yok')])


def test_validate_profile_yasak_kategori_reddeder(monkeypatch):
    monkeypatch.setitem(PROFILES, 'test-profil', {
        'label': 'Test', 'desc': 'x', 'method': 'smart',
        'pkgs': ['com.yasakli', 'com.temiz']})
    monkeypatch.setattr('mibox_app.profiles.package_to_category',
                        lambda pkg: 'dokunma' if pkg == 'com.yasakli'
                        else 'guvenli')

    clean, rejected = validate_profile('test-profil')

    assert clean == ['com.temiz']
    assert rejected == [('com.yasakli', 'yasak kategori: dokunma')]


def test_profile_summary():
    prof = PROFILES['minimal']
    assert profile_summary('minimal') == \
        '{} — {}'.format(prof['label'], prof['desc'])
    assert profile_summary('hayali') == 'hayali — '
