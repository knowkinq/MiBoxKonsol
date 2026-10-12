# -*- coding: utf-8 -*-
"""Kok dizin giris noktasi (BAT ve PyInstaller .exe icin)."""
import sys

from mibox_app.main import run

if __name__ == '__main__':
    sys.exit(run(selftest='--selftest' in sys.argv))