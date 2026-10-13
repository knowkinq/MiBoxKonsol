# -*- coding: utf-8 -*-
"""Kalıcı işlem geçmişi (JSONL).

Her başarılı paket işlemi buraya eklenir:
  {"ts": ..., "target": ..., "action": ..., "package": ..., "method": ..., "ok": ...}
Ayarlar/Gecmis sekmesinden listelenir, tek tek geri alınabilir.

Geri alma eşlemesi (INVERSE):
  uninstall -> restore, disable -> enable, restrict -> unrestrict,
  enable -> disable, restore -> smart-remove, unrestrict -> restrict.
  clear/stop geri alınamaz (veri/süreç zaten gitti).
"""
import datetime
import json
import os
import threading

_HIST_LOCK = threading.Lock()

INVERSE = {
    'uninstall': 'restore',
    'disable': 'enable',
    'restrict': 'unrestrict',
    'enable': 'disable',
    'restore': 'smart',
    'unrestrict': 'restrict',
}

NON_REVERSIBLE = {'clear', 'stop', 'launch'}


def _path():
    from .config import BASE_DIR
    # DIKKAT: dosya adi VERIDIR (etiket degil). Cevrilirse eski gecmis
    # dosyasi bulunamaz ve kullanici gecmisi kaybolmus gibi gorunur.
    return os.path.join(BASE_DIR, 'mibox-islem-gecmisi.jsonl')


def append(target, action, package, method='', ok=True, user_id=0):
    """Tek kayıt ekler. Hata verirse sessizce geçer (kritik yol değil)."""
    if type(user_id) is not int or not 0 <= user_id <= 21474:
        raise ValueError('Geçersiz kullanıcı kimliği.')
    rec = {
        'ts': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'target': target or '',
        'action': action,
        'package': package,
        'method': method or '',
        'ok': bool(ok),
        'user_id': user_id,
    }
    line = json.dumps(rec, ensure_ascii=False) + '\n'
    try:
        with _HIST_LOCK:
            with open(_path(), 'a', encoding='utf-8') as f:
                f.write(line)
                try:
                    f.flush()
                except OSError:
                    pass
    except OSError:
        pass


def append_many(target, action, details, user_id=0):
    """Worker ayrıntılarını toplu yazar.

    Eski biçim `(pkg, ok, msg)` her kayıt için ortak `action` kullanır.
    `(action, pkg, ok, msg)` biçimi işlem sahnelerinde paket başına doğru
    geri alma türünü korur.
    """
    for detail in details:
        if len(detail) == 4:
            record_action, pkg, ok, msg = detail
        else:
            pkg, ok, msg = detail
            record_action = action
        method = ''
        if isinstance(msg, str):
            if msg.startswith('disable ile'):
                method = 'disable'
            elif msg.startswith('uninstall ile'):
                method = 'uninstall'
        if not method and record_action in ('disable', 'uninstall'):
            method = record_action
        append(target, record_action, pkg, method, ok, user_id=user_id)


def read_all(limit=500):
    """En yeniden eskiye kayıt listesi (dict). Dosya yoksa []."""
    try:
        path = _path()
        if not os.path.exists(path):
            return []
        with _HIST_LOCK:
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines[-limit:]):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if isinstance(rec, dict) and rec.get('package'):
                out.append(rec)
        except ValueError:
            continue
    return out


def clear():
    try:
        with _HIST_LOCK:
            os.remove(_path())
    except OSError:
        pass


def inverse_of(action):
    return INVERSE.get(action)
