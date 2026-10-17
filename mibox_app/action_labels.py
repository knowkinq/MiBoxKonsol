# -*- coding: utf-8 -*-
"""Aksiyon adlarinin baglama gore Turkce karsiliklari (TEK KAYNAK).

Ayni aksiyonun baglama gore cekimi farklidir; kopya sozlukler yerine
tek yerde tutulur:
- ACTION_TR        : sahne onizlemesi / calistirma listesi (emir kipi)
- ACTION_TR_CONFIRM: onay diyalogu basligi (isim kipi)
- ACTION_TR_LOG    : gecmis ve durum metni (kisa ad)
"""

ACTION_TR = {
    'uninstall': 'Kaldır (user 0)', 'disable': 'Devre dışı bırak',
    'enable': 'Aktif et', 'restore': 'Geri yükle',
    'restrict': 'Kısıtla', 'unrestrict': 'Serbest bırak',
    'clear': 'Veriyi sil', 'stop': 'Force stop',
    'smart': 'Akıllı kaldır (önce devre dışı bırak)',
}

ACTION_TR_CONFIRM = {
    'stop': 'Zorla durdurma',
    'clear': 'Veri silme',
    'enable': 'Aktif etme',
    'disable': 'Devre dışı bırakma',
    'uninstall': 'Kullanıcı için kaldırma',
    'restore': 'Geri yükleme',
    'launch': 'Açma',
    'restrict': 'Kısıtlama',
    'unrestrict': 'Serbest bırakma',
    'smart': 'Akıllı kaldırma',
}

ACTION_TR_LOG = {
    'uninstall_full': 'Tam kaldırma (veriler silindi)',
    'uninstall': 'Kaldırma', 'disable': 'Devre dışı', 'enable': 'Aktif',
    'restore': 'Geri yükleme', 'restrict': 'Kısıtla', 'unrestrict': 'Serbest',
    'smart': 'Akıllı kaldırma', 'snapshot': 'Durum kaydı', 'clear': 'Veri silme',
    'stop': 'Force stop', 'launch': 'Açma',
}
