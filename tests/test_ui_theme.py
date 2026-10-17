# -*- coding: utf-8 -*-
"""theme: palet, stil ve stil sayfasi yardimcilari."""
from mibox_app.ui import theme


def test_colors_for_iki_tema():
    assert theme.colors_for(True) is theme.DARK_COLORS
    assert theme.colors_for(False) is theme.LIGHT_COLORS


def test_metin_stilleri_iki_tema():
    assert theme.muted_style(True) == 'color: {};'.format(
        theme.DARK_COLORS['muted'])
    assert theme.muted_style(False) == 'color: {};'.format(
        theme.LIGHT_COLORS['muted'])
    assert theme.faint_style(True) == 'color: {};'.format(
        theme.DARK_COLORS['faint'])
    assert theme.faint_style(False) == 'color: {};'.format(
        theme.LIGHT_COLORS['faint'])
    assert theme.title_style(True) == 'color: {}; font-weight: bold;'.format(
        theme.DARK_COLORS['accent'])
    assert theme.title_style(False) == 'color: {}; font-weight: bold;'.format(
        theme.LIGHT_COLORS['accent'])


def test_conn_style_iki_durum():
    assert theme.conn_style(True, True) == 'color: {}; font-weight: bold;'.format(
        theme.DARK_COLORS['success'])
    assert theme.conn_style(False, False) == 'color: {}; font-weight: bold;'.format(
        theme.LIGHT_COLORS['muted'])


def test_logcat_colors_for_iki_tema():
    koyu = theme.logcat_colors_for(True)
    acik = theme.logcat_colors_for(False)
    assert set(koyu) == set(acik) == {'V', 'D', 'I', 'W', 'E', 'F'}
    assert koyu['E'] == theme.DARK_COLORS['danger']
    assert acik['F'] == theme.LIGHT_COLORS['danger']


def test_cat_colors_for_iki_tema():
    koyu = theme.cat_colors_for(True)
    acik = theme.cat_colors_for(False)
    assert set(koyu) == set(acik) == {
        'guvenli', 'opsiyonel', 'riskli', 'dokunma', 'favoriler'}
    assert koyu['guvenli'] == theme.DARK_COLORS['success']
    assert acik['dokunma'] == theme.LIGHT_COLORS['danger']


def test_removal_colors_for_iki_tema():
    koyu = theme.removal_colors_for(True)
    acik = theme.removal_colors_for(False)
    assert set(koyu) == set(acik) == {
        'Recommended', 'Advanced', 'Expert', 'Unsafe'}
    assert koyu['Recommended'] == theme.DARK_COLORS['success']
    assert acik['Unsafe'] == theme.LIGHT_COLORS['danger']


def test_qss_for_iki_tema():
    assert theme.qss_for(True) == theme.DARK_QSS + theme.DARK_EXTRA_QSS
    assert theme.qss_for(False) == theme.LIGHT_QSS + theme.LIGHT_EXTRA_QSS


def test_level_colors_for_iki_tema():
    assert theme.level_colors_for(True) is theme.LEVEL_COLORS
    assert theme.level_colors_for(False) is theme.LIGHT_LEVEL_COLORS
