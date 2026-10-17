# -*- coding: utf-8 -*-
"""Ortak test altyapisi.

Qt bagimli moduller ekransiz (offscreen) calisir; testler ADB gerektirmez
(AdbEngine her testte sahte bir yol ile orneklenir).
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

PROJE_KOKU = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJE_KOKU not in sys.path:
    sys.path.insert(0, PROJE_KOKU)
