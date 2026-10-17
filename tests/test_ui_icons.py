# -*- coding: utf-8 -*-
"""icons: cizgisel simgelerin uretimi ve geri donus cizimi."""
import pytest
from PySide6.QtCore import QSize

from mibox_app.ui.icons import line_icon

ADLAR = [
    'home', 'apps', 'remote', 'cleanup', 'health', 'optimization',
    'history', 'logs', 'files', 'install', 'network', 'settings',
    'terminal', 'mute', 'volume-mute', 'volume', 'speaker', 'tv',
    'display',
]


def _dolu_piksel_var_mi(ikon, boyut=20):
    resim = ikon.pixmap(boyut, boyut).toImage()
    for y in range(resim.height()):
        for x in range(resim.width()):
            if resim.pixelColor(x, y).alpha() > 0:
                return True
    return False


@pytest.mark.parametrize('ad', ADLAR + ['bilinmeyen-ad'])
def test_her_ad_dolu_simge_uretir(qtbot, ad):
    ikon = line_icon(ad)

    assert not ikon.isNull()
    assert _dolu_piksel_var_mi(ikon)


def test_bilinmeyen_ad_display_cizimiyle_ayni(qtbot):
    bilinmeyen = line_icon('yok-boyle-bir-sey')
    display = line_icon('tv')

    assert (bilinmeyen.pixmap(20, 20).toImage()
            == display.pixmap(20, 20).toImage())


def test_boyut_ve_renk_gecirilir(qtbot):
    ikon = line_icon('home', color='#ff0000', size=40)

    # QIcon ham pixmap boyutunu bildirir (size*2); DPR 2 ile mantiksal 40.
    assert ikon.availableSizes() == [QSize(80, 80)]

    resim = ikon.pixmap(40, 40).toImage()
    kirmizi = 0
    for y in range(resim.height()):
        for x in range(resim.width()):
            renk = resim.pixelColor(x, y)
            if renk.alpha() > 0 and renk.red() > 200 and renk.green() < 80:
                kirmizi += 1
    assert kirmizi > 0
