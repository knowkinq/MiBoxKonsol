# -*- mode: python ; coding: utf-8 -*-
# MiBox Konsol - optimize PyInstaller spec (64-bit PySide6 & 32-bit x86 PyQt5).
# Kullanim:  pyinstaller --noconfirm MiBoxKonsol.spec
# Not: UPX kuruluysa (upx.exe PATH'te) ek sikistirma yapar; sart degil.
import struct
import sys

IS_32BIT = (struct.calcsize('P') == 4)

try:
    import PySide6
    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False

try:
    import PyQt5
    HAS_PYQT5 = True
except ImportError:
    HAS_PYQT5 = False

EXCLUDE_QT_MODULES = [
    'PySide6.Qt3DAnimation', 'PySide6.Qt3DCore', 'PySide6.Qt3DExtras', 'PySide6.Qt3DInput',
    'PySide6.Qt3DLogic', 'PySide6.Qt3DQuick', 'PySide6.Qt3DQuickAnimation', 'PySide6.Qt3DQuickExtras',
    'PySide6.Qt3DQuickInput', 'PySide6.Qt3DQuickLogic', 'PySide6.Qt3DQuickRender', 'PySide6.Qt3DQuickScene2D',
    'PySide6.Qt3DQuickScene3D', 'PySide6.Qt3DRender', 'PySide6.QtBluetooth', 'PySide6.QtCharts',
    'PySide6.QtChartsQml', 'PySide6.QtConcurrent', 'PySide6.QtDataVisualization', 'PySide6.QtDataVisualizationQml',
    'PySide6.QtDBus', 'PySide6.QtDesigner', 'PySide6.QtGraphs', 'PySide6.QtGraphsWidgets',
    'PySide6.QtHelp', 'PySide6.QtHttpServer', 'PySide6.QtLocation', 'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets', 'PySide6.QtNetwork', 'PySide6.QtNetworkAuth', 'PySide6.QtNfc',
    'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
    'PySide6.QtPositioning', 'PySide6.QtPrintSupport', 'PySide6.QtQml', 'PySide6.QtQuick',
    'PySide6.QtQuick3D', 'PySide6.QtQuickControls2', 'PySide6.QtQuickWidgets', 'PySide6.QtRemoteObjects',
    'PySide6.QtScxml', 'PySide6.QtSensors', 'PySide6.QtSerialBus', 'PySide6.QtSerialPort',
    'PySide6.QtSpatialAudio', 'PySide6.QtSql', 'PySide6.QtStateMachine', 'PySide6.QtSvg',
    'PySide6.QtSvgWidgets', 'PySide6.QtTest', 'PySide6.QtTextToSpeech', 'PySide6.QtUiTools',
    'PySide6.QtVirtualKeyboard', 'PySide6.QtWebChannel', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineQuick',
    'PySide6.QtWebEngineWidgets', 'PySide6.QtWebSockets', 'PySide6.QtWebView', 'PySide6.QtXml',
    # PyQt5 excludes (32-bit x86)
    'PyQt5.QtNetwork', 'PyQt5.QtQml', 'PyQt5.QtQuick', 'PyQt5.QtQuickWidgets',
    'PyQt5.QtMultimedia', 'PyQt5.QtMultimediaWidgets', 'PyQt5.QtSql', 'PyQt5.QtSvg',
    'PyQt5.QtXml', 'PyQt5.QtXmlPatterns', 'PyQt5.QtBluetooth', 'PyQt5.QtNfc',
    'PyQt5.QtPositioning', 'PyQt5.QtLocation', 'PyQt5.QtSensors', 'PyQt5.QtSerialPort',
    'PyQt5.QtWebChannel', 'PyQt5.QtWebSockets', 'PyQt5.QtDesigner', 'PyQt5.QtHelp',
    'PyQt5.QtTest', 'PyQt5.QtOpenGL',
]

EXCLUDE_STDLIB = [
    'unittest', 'test', 'pydoc', 'doctest', 'pdb', 'difflib',
    'multiprocessing', 'concurrent.futures.process',
    'xml', 'xmlrpc', 'http.server', 'email', 'html',
    'tkinter', 'ctypes.test',
]

hooksconfig = {}
if HAS_PYSIDE6:
    hooksconfig['PySide6'] = {'collect_all': False}

a = Analysis(
    ['mibox.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['mibox_app.qt_compat'],
    hookspath=[],
    hooksconfig=hooksconfig,
    runtime_hooks=[],
    excludes=EXCLUDE_QT_MODULES + EXCLUDE_STDLIB,
    noarchive=False,
    optimize=2,
)

_KEEP_SUBSTR = (
    'Qt6Core', 'Qt6Gui', 'Qt6Widgets',
    'Qt5Core', 'Qt5Gui', 'Qt5Widgets',
    'qwindows', 'qoffscreen', 'qminimal', 'qmodernwindowsstyle',
    'qico', 'qjpeg', 'qsvgicon', 'qgif',
    'MSVCP', 'VCRUNTIME', 'python3', 'python3',
    'shiboken', 'pyside6.abi3', 'PyQt5',
    'libffi', 'base_library',
)

_DROP_SUBSTR = (
    'Qt6Qml', 'Qt6Quick', 'Qt63D', 'Qt6Network', 'Qt6OpenGL', 'Qt6Pdf',
    'Qt6Svg', 'Qt6Multimedia', 'Qt6VirtualKeyboard', 'Qt6WebEngine',
    'Qt6Designer', 'Qt6Charts', 'Qt6Bluetooth', 'Qt6Nfc', 'Qt6Sql',
    'Qt6Sensors', 'Qt6Serial', 'Qt6Positioning', 'Qt6Location',
    'Qt6TextToSpeech', 'Qt6RemoteObjects', 'Qt6Scxml', 'Qt6StateMachine',
    'Qt6SpatialAudio', 'Qt6Graphs', 'Qt6DataVisualization', 'Qt6HttpServer',
    'Qt6Help', 'Qt6DBus', 'Qt6UiTools', 'Qt6Test', 'Qt6Xml',
    'Qt5Qml', 'Qt5Quick', 'Qt5Network', 'Qt5OpenGL', 'Qt5Svg', 'Qt5Multimedia',
    'Qt5Designer', 'Qt5Bluetooth', 'Qt5Nfc', 'Qt5Sql', 'Qt5Sensors', 'Qt5SerialPort',
    'Qt5Positioning', 'Qt5Location', 'Qt5WebChannel', 'Qt5WebSockets', 'Qt5Help', 'Qt5Test', 'Qt5Xml',
    'opengl32sw', 'translations', '.qm',
    'qpdf', 'qtiff', 'qwebp', 'qwbmp', 'qicns', 'qtga',
    'qdirect2d', 'qtuiotouchplugin', 'tls', 'networkinformation',
    'platforminputcontexts', 'qwindowsvistastyle',
    'QtOpenGL', 'QtNetwork', 'QtQml', 'QtQuick', 'QtPdf', 'QtSvg',
)


def _keep_binary(dest_name):
    low = dest_name.replace('\\', '/').lower()
    basename = low.rsplit('/', 1)[-1]
    if basename == 'icuuc.dll' or basename.startswith('icudt'):
        return False
    for drop in _DROP_SUBSTR:
        if drop.lower() in low:
            keep = False
            for k in _KEEP_SUBSTR:
                if k.lower() in low and (
                        'platforms' in low or 'styles' in low or 'dll' in low):
                    keep = True
                    break
            if not keep:
                return False
    return True


a.binaries = [b for b in a.binaries if _keep_binary(b[0])]
a.datas = [d for d in a.datas
           if not d[0].lower().endswith('.qm')
           and 'translations' not in d[0].replace('\\', '/').lower()]

pyz = PYZ(a.pure, optimize=2)

exe_name = 'MiBoxKonsol_x86' if IS_32BIT else 'MiBoxKonsol'

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=exe_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
