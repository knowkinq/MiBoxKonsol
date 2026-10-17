# -*- coding: utf-8 -*-
"""Ortak onay diyaloglari: hangi uygulamaya ne yapilacagi HER ZAMAN gosterilir.

Kural: hicbir yikici/islem onayinda yalnizca sayi sorulmaz; ilk 8 paketin
'dost ad (paket)' satiri listelenir, fazlasi '+N tane daha' diye ozetlenir.
"""
from PySide6.QtWidgets import QCheckBox, QMessageBox

from ..action_labels import ACTION_TR_CONFIRM as ACTION_TR  # onay basligi kipi

MAX_LIST = 8


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


def confirm_action(parent, action, pkgs, name_of, extra='', uninstall_options=None):
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
    elif action == 'uninstall' and uninstall_options is not None:
        body += ('\n\nNasıl kaldırılsın? Aşağıdaki seçenek işaretlenmezse '
                 'yalnızca seçili Android kullanıcısından kaldırılır ve '
                 'uygulama verileri korunmaya çalışılır. Seçeneği işaretlerseniz '
                 'veriler de silinerek tamamen kaldırılır.')
    elif action == 'uninstall':
        body += ('\n\nUygulama, işlem için seçili Android kullanıcısından kaldırılır. '
                 'Android uygulama verilerini korumaya çalışır; tekrar kurulumda '
                 'kullanılabilir. Bu işlem bir veri yedeği değildir ve Android sürümü '
                 'ile uygulama durumu geri yüklemeyi etkileyebilir.')
    if extra:
        body += u'\n\n' + extra
    if action == 'uninstall' and uninstall_options is not None:
        uninstall_options['full_uninstall'] = False
        box = QMessageBox(parent)
        box.setWindowTitle(u'Onay — ' + label)
        box.setIcon(QMessageBox.Warning)
        box.setText(body)
        clean = QCheckBox('Verileri de silerek tamamen kaldır')
        clean.setChecked(False)
        clean.setToolTip(
            'Tüm Android kullanıcılarından kaldırır; ayarlar ve hesaplar silinir. '
            'Yeni APK kurulumu için eski veri ve imza kaydı temizlenir.')
        box.setCheckBox(clean)
        box.setInformativeText(
            'Tam kaldırma seçilirse uygulama ve verileri tüm Android '
            'kullanıcılarından kalıcı olarak silinir. Sistem uygulamaları '
            'tamamen kaldırılamayabilir. Geri yüklemek için APK yeniden '
            'kurulmalıdır; durum kaydı silinen verileri geri getirmez.')
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        box.setEscapeButton(QMessageBox.No)
        accepted = box.exec() == QMessageBox.Yes
        uninstall_options['full_uninstall'] = accepted and clean.isChecked()
        return accepted
    ret = QMessageBox.question(parent, u'Onay — ' + label, body,
                               QMessageBox.Yes | QMessageBox.No,
                               QMessageBox.No)
    return ret == QMessageBox.Yes
