# -*- coding: utf-8 -*-
"""Aksiyon etiket tablolarinin tutarlilik ve kaynak testleri."""
from mibox_app.action_labels import ACTION_TR, ACTION_TR_CONFIRM, ACTION_TR_LOG

CEKIRDEK_AKSIYONLAR = ('uninstall', 'disable', 'enable', 'restore',
                       'restrict', 'unrestrict', 'clear', 'stop', 'smart')


def test_tum_baglamlar_cekirdek_aksiyonlari_icerir():
    for table in (ACTION_TR, ACTION_TR_CONFIRM, ACTION_TR_LOG):
        eksik = [a for a in CEKIRDEK_AKSIYONLAR if a not in table]
        assert not eksik, eksik


def test_etiketler_bos_degil():
    for table in (ACTION_TR, ACTION_TR_CONFIRM, ACTION_TR_LOG):
        for action, label in table.items():
            assert isinstance(label, str) and label.strip(), action


def test_moduller_ayni_kaynagi_paylasir():
    # Kopya sozlukler donmesin: uc modul de action_labels nesnelerini
    # disa aktarmali (dedup regresyonu).
    from mibox_app.stage import ACTION_TR as stage_tr
    from mibox_app.ui.dialogs import ACTION_TR as dialogs_tr
    from mibox_app.ui.history_tab import ACTION_TR as history_tr

    assert stage_tr is ACTION_TR
    assert dialogs_tr is ACTION_TR_CONFIRM
    assert history_tr is ACTION_TR_LOG
