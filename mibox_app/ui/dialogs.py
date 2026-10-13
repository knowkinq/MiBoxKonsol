# -*- coding: utf-8 -*-
"""Ortak onay diyaloglari: hangi uygulamaya ne yapilacagi HER ZAMAN gosterilir.

Kural: hicbir yikici/islem onayinda yalnizca sayi sorulmaz; ilk 8 paketin
'dost ad (paket)' satiri listelenir, fazlasi '+N tane daha' diye ozetlenir.
"""
from PySide6.QtWidgets import QMessageBox

MAX_LIST = 8

ACTION_TR = {
    'stop': 'Zorla durdurma',
    'clear': 'Veri silme',
    'enable': 'Aktif etme',
    'disable': 'Devre dışı bırakma',
    'uninstall': 'Kaldırma (user)',
    'restore': 'Geri yükleme',
    'launch': 'Açma',
    'restrict': 'Kısıtlama',
    'unrestrict': 'Serbest bırakma',
    'smart': 'Akıllı kaldırma',
}


def pkg_lines(pkgs, name_of, limit=MAX_LIST):
    """['Ad (paket)', ...] + ozet satiri. name_of: paket->dost ad."""
    lines = []
    for p in pkgs[:limit]:
        try:
            name = name_of(p)
        except Exception:
            name = p
        if name and name != p:
            lines.append(u'• {} ({})'.format(name, p))
        else:
            lines.append(u'• {}'.format(p))
    rest = len(pkgs) - len(lines)
    if rest > 0:
        lines.append(u'… ve {} tane daha'.format(rest))
    return lines


def confirm_action(parent, action, pkgs, name_of, extra=''):
    """Islem onayi: baslikta islem, govdede uygulama listesi.

    Donus: True (Yes) / False.
    """
    label = ACTION_TR.get(action, action)
    lines = pkg_lines(pkgs, name_of)
    if len(pkgs) == 1:
        body = u'{}\n\n{}'.format(label, '\n'.join(lines))
    else:
        body = u'{} uygulama — {}:\n\n{}'.format(len(pkgs), label, '\n'.join(lines))
    if action == 'clear':
        body += '\n\nUygulama verileri kalıcı olarak silinir. Durum kaydı bu verileri geri getirmez.'
    if extra:
        body += u'\n\n' + extra
    ret = QMessageBox.question(parent, u'Onay — ' + label, body,
                               QMessageBox.Yes | QMessageBox.No,
                               QMessageBox.No)
    return ret == QMessageBox.Yes
