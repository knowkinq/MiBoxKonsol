# -*- coding: utf-8 -*-
"""Kok dizin giris noktasi (BAT ve PyInstaller .exe icin)."""
import sys

from mibox_app import qt_compat  # noqa: F401
from mibox_app.main import main

if __name__ == '__main__':
    sys.exit(main())