# -*- coding: utf-8 -*-
"""kit: CSV notralizasyonu, tema cozumleme ve ortak widget yardimcilari."""
import pytest
import shiboken6
from PySide6.QtCore import QRect
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QPushButton,
    QTableWidget,
    QWidget,
)

from mibox_app.ui import kit, theme
from mibox_app.ui.flowlayout import FlowLayout


class _Ayarlar:
    def __init__(self, dark):
        self.dark_mode = dark


class _Cekirdek:
    def __init__(self, dark):
        self.config = _Ayarlar(dark)


class _PencereKok:
    """core.config.dark_mode tasiyan basit nesne (engine/window benzetimi)."""

    def __init__(self, dark):
        self.core = _Cekirdek(dark)


class _Sarmal:
    """Yalnizca .window uzerinden ayara ulasan sarmalayici."""

    def __init__(self, pencere):
        self.window = pencere


class _IkiYuzlu:
    """core erisimi ikinci cagrida patlar: koruma yolunu tetikler."""

    def __init__(self):
        self.cagri = 0

    def __getattr__(self, ad):
        if ad == 'core':
            self.cagri += 1
            if self.cagri >= 2:
                raise RuntimeError('core artik patlar')
        raise AttributeError(ad)


class _PencerePatlak:
    """window erisimi patlar: ikinci koruma yolunu tetikler."""

    def __getattr__(self, ad):
        if ad == 'window':
            raise RuntimeError('pencere yok')
        raise AttributeError(ad)


class _CocukPatlak:
    """children() cagrisi patlar: refresh_theme korumasini tetikler."""

    def children(self):
        raise RuntimeError('cocuklar yok')


class _Yenilenen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sayac = 0

    def apply_theme(self):
        self.sayac += 1


class _PatlakAta(_Yenilenen):
    def apply_theme(self):
        raise RuntimeError('olu')


class _PatlakDiger(QWidget):
    def apply_theme(self):
        raise ValueError('beklenmedik')


@pytest.mark.parametrize('raw,expected', [
    ('=cmd|calc', "'=cmd|calc"),
    ('+SUM(1)', "'+SUM(1)"),
    ('-2+3', "'-2+3"),
    ('@x', "'@x"),
    ('  =1+1', "'  =1+1"),
    ('\t=1+1', "'\t=1+1"),
])
def test_formul_baslangiclari_notralize_edilir(raw, expected):
    assert kit.csv_cell(raw) == expected


@pytest.mark.parametrize('raw,expected', [
    ('com.example.app', 'com.example.app'),
    ('2026-10-17 10:00', '2026-10-17 10:00'),
    ('normal metin', 'normal metin'),
    ('', ''),
    ('   ', '   '),
    (None, ''),
    (0, '0'),
])
def test_normal_degerler_degismez(raw, expected):
    assert kit.csv_cell(raw) == expected


def test_dark_of_bool_donusumu_ve_patlak_bool():
    assert kit._dark_of() is True
    assert kit._dark_of(0) is False
    assert kit._dark_of('x') is True

    class _PatlakBool:
        def __bool__(self):
            raise ValueError('yok')

    assert kit._dark_of(_PatlakBool()) is True


def test_muted_faint_title_temaya_delege_eder():
    assert kit.muted(True) == theme.muted_style(True)
    assert kit.muted(False) == theme.muted_style(False)
    assert kit.faint() == theme.faint_style(True)
    assert kit.title(False) == theme.title_style(False)


def test_dark_from_core_ve_varsayilanlar():
    assert kit.dark_from(_PencereKok(False)) is False
    assert kit.dark_from(_PencereKok(True)) is True
    assert kit.dark_from(None) is True
    assert kit.dark_from(None, default=False) is False


def test_dark_from_ust_widget_zincirini_yurur(qtbot):
    class _Kok(QWidget):
        def __init__(self, dark):
            super().__init__()
            self.core = _Cekirdek(dark)

    kok = _Kok(False)
    qtbot.addWidget(kok)
    cocuk = QLabel(kok)

    assert kit.dark_from(cocuk) is False


def test_dark_from_window_tasiyicisi():
    assert kit.dark_from(_Sarmal(_PencereKok(False))) is False


def test_dark_from_savunma_yollari():
    assert kit.dark_from(_IkiYuzlu()) is True
    assert kit.dark_from(_PencerePatlak()) is True


def test_dark_from_gec_ortaya_cikan_config():
    class _GecikmeliAyarlar:
        """config ikinci erisimde acilir: tekil dogrulama yolunu tetikler."""

        def __init__(self):
            self._ayar = _Ayarlar(False)
            self._cagri = 0

        @property
        def config(self):
            self._cagri += 1
            return None if self._cagri == 1 else self._ayar

    assert kit.dark_from(_GecikmeliAyarlar()) is False


def test_dark_from_silinmis_widget_varsayilana_duser(qtbot):
    kok = QWidget()
    cocuk = QLabel(kok)
    shiboken6.delete(kok)
    assert shiboken6.isValid(cocuk) is False

    assert kit.dark_from(cocuk) is True
    assert kit.dark_from(cocuk, default=False) is False


def test_colors_ve_mono_style():
    assert kit.colors(None) is theme.DARK_COLORS
    assert kit.colors(_PencereKok(False)) is theme.LIGHT_COLORS
    assert kit.colors(None, default=False) is theme.LIGHT_COLORS
    assert 'monospace' in kit.mono_style()


def test_refresh_theme_semantik_etiketleri_boyar(qtbot):
    muted_lbl = QLabel('m')
    faint_lbl = QLabel('f')
    diger = QLabel('d')
    muted_lbl.setProperty('semanticRole', 'muted')
    faint_lbl.setProperty('semanticRole', 'faint')
    for w in (muted_lbl, faint_lbl, diger):
        qtbot.addWidget(w)

    kit.refresh_theme(None)  # None sessizce yok sayilir
    kit.refresh_theme(muted_lbl)
    kit.refresh_theme(faint_lbl)
    kit.refresh_theme(diger)

    assert muted_lbl.styleSheet() == theme.muted_style(kit.dark_from(muted_lbl))
    assert faint_lbl.styleSheet() == theme.faint_style(kit.dark_from(faint_lbl))
    assert diger.styleSheet() == ''


def test_refresh_theme_agacta_apply_theme_cagirir(qtbot):
    kok = _Yenilenen()
    cocuk = _Yenilenen(kok)
    qtbot.addWidget(kok)

    kit.refresh_theme(kok)

    assert kok.sayac == 1
    assert cocuk.sayac == 1


def test_refresh_theme_runtime_hatasinda_dal_kesilir(qtbot):
    kok = _PatlakAta()
    cocuk = _Yenilenen(kok)
    qtbot.addWidget(kok)

    kit.refresh_theme(kok)

    assert kok.sayac == 0
    assert cocuk.sayac == 0


def test_refresh_theme_diger_hata_yutulur_cocuklar_yenilenir(qtbot):
    kok = _PatlakDiger()
    cocuk = _Yenilenen(kok)
    qtbot.addWidget(kok)

    kit.refresh_theme(kok)

    assert cocuk.sayac == 1


def test_refresh_theme_cocuk_hatasinda_doner():
    kit.refresh_theme(_CocukPatlak())  # patlamamali


def test_page_ve_section(qtbot):
    kap = QWidget()
    qtbot.addWidget(kap)
    root = kit.page(kap)

    assert kap.layout() is root
    m = root.contentsMargins()
    assert (m.left(), m.top(), m.right(), m.bottom()) == (kit.MARGIN,) * 4
    assert root.spacing() == kit.SPACING

    kutu = kit.section('Bölüm')
    qtbot.addWidget(kutu)
    assert kutu.title() == 'Bölüm'


def test_hint_ve_status_label(qtbot):
    ipucu = kit.hint_label('ipucu', dark=False)
    durum = kit.status_label(dark=True)
    otomatik = kit.hint_label('x')
    for w in (ipucu, durum, otomatik):
        qtbot.addWidget(w)

    assert ipucu.property('semanticRole') == 'faint'
    assert ipucu.styleSheet() == theme.faint_style(False)
    assert ipucu.wordWrap() is True
    assert ipucu.text() == 'ipucu'

    assert durum.property('semanticRole') == 'muted'
    assert durum.styleSheet() == theme.muted_style(True)
    assert durum.text() == 'Hazır.'

    assert otomatik.styleSheet() == theme.faint_style(kit.dark_from(otomatik))


def test_action_bar_flowlayout_dondurur():
    assert isinstance(kit.action_bar(), FlowLayout)


def test_make_table_ve_single_table(qtbot):
    grid = kit.make_table(3, ['A', 'B', 'C'])
    tek = kit.single_table(1, ['A'])
    qtbot.addWidget(grid)
    qtbot.addWidget(tek)

    assert grid.columnCount() == 3
    assert grid.horizontalHeaderItem(2).text() == 'C'
    assert grid.selectionBehavior() == QAbstractItemView.SelectRows
    assert grid.selectionMode() == QAbstractItemView.ExtendedSelection
    assert grid.alternatingRowColors() is True
    assert grid.showGrid() is False
    assert grid.wordWrap() is False
    assert grid.verticalHeader().defaultSectionSize() == kit.ROW_H
    assert grid.verticalHeader().isHidden() is True

    assert tek.selectionMode() == QAbstractItemView.SingleSelection


def test_set_busy_kilitler_ve_olu_widgeti_yutar(qtbot):
    b1 = QPushButton('a')
    b2 = QPushButton('b')
    qtbot.addWidget(b1)
    qtbot.addWidget(b2)

    kit.set_busy([b1, b2], True)
    assert b1.isEnabled() is False
    assert b2.isEnabled() is False

    kit.set_busy([b1, b2], False)
    assert b1.isEnabled() is True
    assert b2.isEnabled() is True

    class _Olu:
        def setEnabled(self, deger):
            raise RuntimeError('olu')

    kit.set_busy([_Olu(), b1], True)
    assert b1.isEnabled() is False


def test_data_table_kurulum_ve_bos_durum(qtbot):
    grid = kit.DataTable(2)
    qtbot.addWidget(grid)

    assert grid.empty_label.objectName() == 'emptyState'
    assert grid.empty_label.wordWrap() is True
    assert 'Henüz veri yok' in grid.empty_label.text()
    assert 'Cihaza bağlanın' in grid.empty_label.text()


def test_data_table_tema_metni_kacislari_uygular(qtbot):
    grid = kit.DataTable(1)
    qtbot.addWidget(grid)
    grid.empty_title = '<b>t&t</b>\nyeni'
    grid.empty_description = 'x > y'

    grid.apply_theme()

    metin = grid.empty_label.text()
    assert '&lt;b&gt;t&amp;t&lt;/b&gt;<br>yeni' in metin
    assert 'x &gt; y' in metin


def test_data_table_bos_etiket_model_degisimini_izler(qtbot):
    grid = kit.make_table(1, ['A'])
    qtbot.addWidget(grid)
    grid.show()
    grid.resize(320, 240)
    qtbot.wait(10)

    assert grid.empty_label.isVisible() is True

    grid.setRowCount(1)
    assert grid.empty_label.isVisible() is False

    grid.setRowCount(0)
    assert grid.empty_label.isVisible() is True

    grid.model().modelReset.emit()
    assert grid.empty_label.isVisible() is True


def test_empty_state_data_table_ve_diger(qtbot):
    grid = kit.make_table(1, ['A'])
    qtbot.addWidget(grid)

    kit.empty_state(grid, 'Başlık', 'Açıklama')

    assert grid.empty_title == 'Başlık'
    assert grid.empty_description == 'Açıklama'
    assert 'Başlık' in grid.empty_label.text()

    duz = QTableWidget(0, 1)
    qtbot.addWidget(duz)
    kit.empty_state(duz, 'x', 'y')  # sessizce yok saymali


def test_checkbox_paint_isaretli_ve_isaretsiz(qtbot):
    cb = kit.CheckBox('x')
    qtbot.addWidget(cb)
    cb.resize(60, 24)

    cb.setChecked(False)
    assert cb.grab().isNull() is False

    cb.setChecked(True)
    assert cb.grab().isNull() is False


def test_checkbox_paint_gostergesiz_cizmez(qtbot, monkeypatch):
    cb = kit.CheckBox('x')
    qtbot.addWidget(cb)
    cb.setChecked(True)

    class _SahteStil:
        def subElementRect(self, *args):
            return QRect()

    monkeypatch.setattr(cb, 'style', lambda: _SahteStil())
    assert cb.grab().isNull() is False
