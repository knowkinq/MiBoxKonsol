# -*- coding: utf-8 -*-
"""Qt uyumluluk katmanı (64-bit PySide6 ve 32-bit x86 PyQt5 desteği).

MiBox Konsol varsayılan olarak modern 64-bit Windows sistemlerde PySide6 (Qt 6)
kullanır. Ancak Qt 6 resmi olarak 32-bit Windows (x86) ikili tekerlekleri
yayınlamamaktadır.

Bu modül sayesinde:
- 64-bit sistemlerde PySide6 doğrudan kullanılır.
- 32-bit (x86) Windows sistemlerde veya 32-bit Python ortamlarında PyQt5
  otomatik olarak devreye girer.
- PySide6 modül adları (PySide6.QtCore, PySide6.QtGui, PySide6.QtWidgets)
  sys.modules üzerinde şimlenerek kod tabanının tamamı hiçbir değişiklik
  gerektirmeden 32-bit sistemlerde sorunsuz çalışır.
"""
import platform
import struct
import sys
import types

IS_32BIT = (struct.calcsize('P') == 4)
QT_API = None
QT_VERSION = None


def _setup_pyqt5_shim():
    """PyQt5 modüllerini PySide6 API'siyle tam uyumlu biçimde eşleştirir."""
    try:
        import PyQt5.QtCore as qtc
        import PyQt5.QtGui as qtg
        import PyQt5.QtWidgets as qtw
    except ImportError:
        return False

    pyside6 = types.ModuleType('PySide6')
    pyside6.__version__ = getattr(qtc, 'PYQT_VERSION_STR', '5.15')

    # QtCore
    core = types.ModuleType('PySide6.QtCore')
    for attr in dir(qtc):
        if not attr.startswith('__'):
            setattr(core, attr, getattr(qtc, attr))
    core.Signal = getattr(qtc, 'pyqtSignal', None)
    core.Slot = getattr(qtc, 'pyqtSlot', None)
    core.Property = getattr(qtc, 'pyqtProperty', None)
    core.qInstallMessageHandler = getattr(qtc, 'qInstallMessageHandler', None)
    if not hasattr(core, 'QtMsgType'):
        core.QtMsgType = getattr(qtc, 'QtMsgType', object)

    # QtGui
    gui = types.ModuleType('PySide6.QtGui')
    for attr in dir(qtg):
        if not attr.startswith('__'):
            setattr(gui, attr, getattr(qtg, attr))
    # Qt5'te QAction ve QShortcut QtWidgets içindedir
    if not hasattr(gui, 'QAction') and hasattr(qtw, 'QAction'):
        gui.QAction = qtw.QAction
    if not hasattr(gui, 'QShortcut') and hasattr(qtw, 'QShortcut'):
        gui.QShortcut = qtw.QShortcut
    if not hasattr(gui, 'QKeySequence') and hasattr(qtg, 'QKeySequence'):
        gui.QKeySequence = qtg.QKeySequence

    # QtWidgets
    widgets = types.ModuleType('PySide6.QtWidgets')
    for attr in dir(qtw):
        if not attr.startswith('__'):
            setattr(widgets, attr, getattr(qtw, attr))

    # Enum uyumluluk yardımcıları
    if hasattr(qtw, 'QMessageBox'):
        class _StandardButtonHelper:
            pass
        for btn in ('Yes', 'No', 'Ok', 'Cancel', 'Close', 'Abort', 'Retry', 'Ignore', 'Save', 'Discard'):
            if hasattr(qtw.QMessageBox, btn):
                setattr(_StandardButtonHelper, btn, getattr(qtw.QMessageBox, btn))
        qtw.QMessageBox.StandardButton = _StandardButtonHelper

    if hasattr(qtw, 'QFileDialog'):
        class _OptionHelper:
            DontConfirmOverwrite = getattr(qtw.QFileDialog, 'DontConfirmOverwrite', 0)
        qtw.QFileDialog.Option = _OptionHelper

    sys.modules['PySide6'] = pyside6
    sys.modules['PySide6.QtCore'] = core
    sys.modules['PySide6.QtGui'] = gui
    sys.modules['PySide6.QtWidgets'] = widgets
    return True


def init_qt():
    """Qt motorunu başlatır ve mimariye göre en uygun motoru yükler."""
    global QT_API, QT_VERSION

    # 1. PySide6 dene (varsayılan, 64-bit)
    try:
        from PySide6 import QtCore
        QT_API = 'PySide6'
        QT_VERSION = getattr(QtCore, '__version__', '6.x')
        return True
    except ImportError:
        pass

    # 2. PyQt5 şimi dene (32-bit x86 uyumluluk)
    if _setup_pyqt5_shim():
        from PySide6 import QtCore
        QT_API = 'PyQt5 (32-bit x86 uyumluluk modu)'
        QT_VERSION = getattr(QtCore, '__version__', '5.x')
        return True

    QT_API = '(bulunamadı)'
    QT_VERSION = '-'
    return False


# Modül yüklendiğinde otomatik ilklendir
init_qt()


def get_qt_info():
    """[(etiket, değer)] — tanı ve sürüm raporu için."""
    arch = '32-bit (x86)' if IS_32BIT else '64-bit (x64)'
    return {
        'api': QT_API or '(Qt bulunamadı)',
        'version': QT_VERSION or '-',
        'arch': arch,
        'is_32bit': IS_32BIT,
        'machine': platform.machine(),
    }
