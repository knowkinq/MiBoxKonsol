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


def append(target, action, package, method='', ok=True):
    """Tek kayıt ekler. Hata verirse sessizce geçer (kritik yol değil)."""
    rec = {
        'ts': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'target': target or '',
        'action': action,
        'package': package,
        'method': method or '',
        'ok': bool(ok),
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


def append_many(target, action, details):
    """Worker details listesini toplu yazar: [(pkg, ok, msg), ...]."""
    for pkg, ok, msg in details:
        method = ''
        if isinstance(msg, str):
            if msg.startswith('disable ile'):
                method = 'disable'
            elif msg.startswith('uninstall ile'):
                method = 'uninstall'
        append(target, action, pkg, method, ok)


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
