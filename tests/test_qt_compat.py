# -*- coding: utf-8 -*-
"""Qt uyumluluk katmani testleri: motor bilgisi ve mimari tutarliligi."""
import platform
import struct
import sys
import types

from mibox_app import qt_compat


def test_is_32bit_isaretci_tutarli():
    assert qt_compat.IS_32BIT == (struct.calcsize('P') == 4)


def test_get_qt_info_alanlari():
    info = qt_compat.get_qt_info()

    assert set(info) == {'api', 'version', 'arch', 'is_32bit', 'machine'}
    assert info['api'] == (qt_compat.QT_API or '(Qt bulunamadı)')
    assert isinstance(info['is_32bit'], bool)
    assert info['arch'] == ('32-bit (x86)' if info['is_32bit']
                            else '64-bit (x64)')
    assert info['version'] not in (None, '', '-')
    assert info['machine'] == platform.machine()


def test_init_qt_pyside6_kullanilabilir():
    # Test ortami PySide6 ile kosar; ilklendirme yine de idempotent olmali.
    assert qt_compat.init_qt() is True
    assert qt_compat.QT_API == 'PySide6'
    assert qt_compat.QT_VERSION not in (None, '', '-')


# --- PyQt5 simi ---------------------------------------------------------------
# Gercek PyQt5 kurulu olmadan simi dogrulamak icin sahte PyQt5 modulleri
# sys.modules'a enjekte edilir; monkeypatch teardown'da hepsini geri alir.

class _SahteQMessageBox:
    Yes = 1
    No = 2
    Ok = 4
    Cancel = 8
    Close = 16
    Abort = 32
    Retry = 64
    Ignore = 128
    Save = 256


class _SahteQFileDialog:
    DontConfirmOverwrite = 16


def _sahte_pyqt5():
    qtc = types.ModuleType('PyQt5.QtCore')
    qtc.PYQT_VERSION_STR = '5.15.9'
    qtc.pyqtSignal = object()
    qtc.pyqtSlot = object()
    qtc.pyqtProperty = object()
    qtc.qInstallMessageHandler = object()
    qtc.Qt = 'Qt-namespace'
    # QtMsgType bilerek yok: sim object'e dusmeli.

    qtg = types.ModuleType('PyQt5.QtGui')
    qtg.QKeySequence = 'QKeySequence-nesnesi'
    # QAction/QShortcut bilerek yok: sim QtWidgets'ten kopyalamali.

    qtw = types.ModuleType('PyQt5.QtWidgets')
    qtw.QAction = 'QAction-nesnesi'
    qtw.QShortcut = 'QShortcut-nesnesi'
    qtw.QMessageBox = _SahteQMessageBox
    qtw.QFileDialog = _SahteQFileDialog
    return qtc, qtg, qtw


def _pyqt5_enjekte(monkeypatch, qtc, qtg, qtw, pyside6_yok=False):
    monkeypatch.setitem(sys.modules, 'PyQt5', types.ModuleType('PyQt5'))
    monkeypatch.setitem(sys.modules, 'PyQt5.QtCore', qtc)
    monkeypatch.setitem(sys.modules, 'PyQt5.QtGui', qtg)
    monkeypatch.setitem(sys.modules, 'PyQt5.QtWidgets', qtw)
    # Sim bu anahtarlari ezebilir; teardown icin mevcut degerleri kaydet.
    for key in ('PySide6', 'PySide6.QtCore', 'PySide6.QtGui',
                'PySide6.QtWidgets'):
        monkeypatch.setitem(sys.modules, key, sys.modules.get(key))
    if pyside6_yok:
        sys.modules['PySide6'] = None


def test_setup_pyqt5_shim_esleme(monkeypatch):
    qtc, qtg, qtw = _sahte_pyqt5()
    _pyqt5_enjekte(monkeypatch, qtc, qtg, qtw)

    assert qt_compat._setup_pyqt5_shim() is True

    pyside6 = sys.modules['PySide6']
    core = sys.modules['PySide6.QtCore']
    gui = sys.modules['PySide6.QtGui']
    widgets = sys.modules['PySide6.QtWidgets']

    assert pyside6.__version__ == '5.15.9'
    assert core.Signal is qtc.pyqtSignal
    assert core.Slot is qtc.pyqtSlot
    assert core.Property is qtc.pyqtProperty
    assert core.qInstallMessageHandler is qtc.qInstallMessageHandler
    assert core.QtMsgType is object
    assert core.Qt == 'Qt-namespace'
    assert gui.QKeySequence == 'QKeySequence-nesnesi'
    assert gui.QAction == 'QAction-nesnesi'
    assert gui.QShortcut == 'QShortcut-nesnesi'
    assert widgets.QMessageBox is _SahteQMessageBox

    std = qtw.QMessageBox.StandardButton
    assert std.Yes == 1
    assert std.Save == 256
    assert not hasattr(std, 'Discard')
    assert qtw.QFileDialog.Option.DontConfirmOverwrite == 16


def test_setup_pyqt5_shim_pyqt5_yoksa(monkeypatch):
    monkeypatch.setitem(sys.modules, 'PyQt5', None)
    assert qt_compat._setup_pyqt5_shim() is False


def test_init_qt_pyqt5_simine_duser(monkeypatch):
    monkeypatch.setattr(qt_compat, 'QT_API', qt_compat.QT_API)
    monkeypatch.setattr(qt_compat, 'QT_VERSION', qt_compat.QT_VERSION)
    qtc, qtg, qtw = _sahte_pyqt5()
    _pyqt5_enjekte(monkeypatch, qtc, qtg, qtw, pyside6_yok=True)

    assert qt_compat.init_qt() is True
    assert qt_compat.QT_API == 'PyQt5 (32-bit x86 uyumluluk modu)'
    assert qt_compat.QT_VERSION == '5.x'
    assert sys.modules['PySide6.QtCore'].Signal is qtc.pyqtSignal


def test_init_qt_hicbir_motor_yoksa(monkeypatch):
    monkeypatch.setattr(qt_compat, 'QT_API', qt_compat.QT_API)
    monkeypatch.setattr(qt_compat, 'QT_VERSION', qt_compat.QT_VERSION)
    monkeypatch.setitem(sys.modules, 'PySide6', None)
    monkeypatch.setitem(sys.modules, 'PyQt5', None)

    assert qt_compat.init_qt() is False
    assert qt_compat.QT_API == '(bulunamadı)'
    assert qt_compat.QT_VERSION == '-'
    assert qt_compat.get_qt_info()['api'] == '(bulunamadı)'
