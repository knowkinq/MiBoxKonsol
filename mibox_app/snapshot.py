# -*- coding: utf-8 -*-
"""Snapshot sistemi: cihaz durumunu kaydet, OTA sonrası tek tıkla geri uygula.

Snapshot = {paket: {'enabled': bool, 'installed_user0': bool, 'restricted': bool}}
JSON dosyası: mibox-snapshot-<etiket>.json

Uygulama (apply): snapshot'taki her paket için mevcut durumla karşılaştır,
farklıysa düzelt (disable/uninstall/restore/enable/restrict/unrestrict).
UAD-NG "apply snapshots to multiple Androids" yaklaşımı baz alındı.
"""
import datetime
import json
import os
import threading

from .adb_engine import AdbError

# Snapshot dosyasi degisiklikleri (take/delete) icin kilit: ayni anda iki
# islem yari-yazilmis JSON birakmasin.
_SNAP_LOCK = threading.Lock()


def _dir():
    from .config import BASE_DIR
    d = os.path.join(BASE_DIR, 'snapshots')
    os.makedirs(d, exist_ok=True)
    return d


def _safe_label(label):
    keep = [c for c in (label or '').strip() if c.isalnum() or c in ('-', '_')]
    return ''.join(keep)[:40] or 'adsiz'


def list_snapshots():
    try:
        d = _dir()
    except OSError:
        return []
    out = []
    for name in sorted(os.listdir(d)):
        if name.startswith('mibox-snapshot-') and name.endswith('.json'):
            out.append(name)
    return out


def snapshot_path(name):
    return os.path.join(_dir(), name)


def load(name):
    with _SNAP_LOCK:
        with open(snapshot_path(name), 'r', encoding='utf-8') as f:
            raw = f.read()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('Geçersiz snapshot dosyası (kök dict değil).')
    pkgs = data.get('packages')
    if not isinstance(pkgs, dict) or not pkgs:
        raise ValueError('Geçersiz snapshot dosyası (packages boş/bozuk).')
    for pkg, st in pkgs.items():
        if not isinstance(st, dict):
            raise ValueError('Geçersiz snapshot dosyası (bozuk kayıt: {}).'.format(pkg))
        for key in ('enabled', 'installed_user0', 'restricted'):
            if key not in st:
                raise ValueError('Geçersiz snapshot dosyası (eksik alan: {}).'.format(key))
    return data


def delete(name):
    try:
        with _SNAP_LOCK:
            os.remove(snapshot_path(name))
        return True
    except OSError:
        return False


def take(engine, target, include_system=True):
    """Mevcut durumu yakala. Dönüş: (dosya_adı, paket_sayısı)."""
    engine.connect(target)
    # snapshot her zaman GERCEGI gormeli: onbellek atlanir.
    detailed = engine.list_packages_detailed(target, include_system, use_cache=False)
    restricted = engine.bulk_restricted(target) or set()
    pkgs = {}
    for e in detailed:
        p = e['package']
        pkgs[p] = {
            'enabled': bool(e.get('enabled', True)),
            'installed_user0': bool(e.get('installed_user0', True)),
            'restricted': p in restricted,
        }
    label = _safe_label('{}-{}'.format(
        target.replace(':', '-'), datetime.datetime.now().strftime('%Y%m%d-%H%M%S')))
    name = 'mibox-snapshot-{}.json'.format(label)
    data = {
        'created': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'target': target,
        'packages': pkgs,
    }
    # Atomik yazim: elektrik kesintisi ya da ayni anda calisan ikinci bir
    # take/apply islemi bozuk (yarim) snapshot dosyasi birakmasin.
    path = snapshot_path(name)
    tmp = path + '.tmp'
    try:
        with _SNAP_LOCK:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp, path)
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise
    return name, len(pkgs)


def diff_current(engine, target, snap):
    """Snapshot ile mevcut durum farkı: [(pkg, beklenen, mevcut, aksiyon)]."""
    engine.connect(target)
    detailed = engine.list_packages_detailed(target, True, use_cache=False)
    restricted = engine.bulk_restricted(target) or set()
    cur = {}
    for e in detailed:
        p = e['package']
        cur[p] = {
            'enabled': bool(e.get('enabled', True)),
            'installed_user0': bool(e.get('installed_user0', True)),
            'restricted': p in restricted,
        }
    diffs = []
    for pkg, want in snap.get('packages', {}).items():
        have = cur.get(pkg)
        if have is None:
            diffs.append((pkg, want, None, 'bilinmiyor (cihazda yok)'))
            continue
        if want['installed_user0'] and not have['installed_user0']:
            diffs.append((pkg, want, have, 'restore'))
        elif not want['installed_user0'] and have['installed_user0']:
            diffs.append((pkg, want, have, 'uninstall'))
        elif want['enabled'] and not have['enabled']:
            diffs.append((pkg, want, have, 'enable'))
        elif not want['enabled'] and have['enabled']:
            diffs.append((pkg, want, have, 'disable'))
        elif want['restricted'] and not have['restricted']:
            diffs.append((pkg, want, have, 'restrict'))
        elif not want['restricted'] and have['restricted']:
            diffs.append((pkg, want, have, 'unrestrict'))
    return diffs


def apply(engine, target, snap, protected=(), log=None, progress=None,
          is_cancelled=None):
    """Farkları cihaza uygula. Dönüş: {'ok', 'fail', 'details'}.

    is_cancelled: opsiyonel callable -> True ise kalan farklar 'kullanici
    durdurdu' sayilir (Faz 3 iptal disiplini).
    """
    diffs = diff_current(engine, target, snap)
    ok = 0
    fail = 0
    details = []
    total = len(diffs)
    for i, (pkg, _want, _have, action) in enumerate(diffs, 1):
        if progress:
            try:
                progress(i, total)
            except Exception:
                pass
        try:
            if is_cancelled is not None and is_cancelled():
                details.append((pkg, False, 'kullanici durdurdu'))
                fail += 1
                continue
        except Exception:
            pass
        if action.startswith('bilinmiyor'):
            details.append((pkg, False, action))
            fail += 1
            continue
        if pkg in (protected or ()):
            details.append((pkg, False, 'koruma listesinde'))
            fail += 1
            continue
        try:
            if action == 'restore':
                engine.install_existing(target, pkg)
            elif action == 'uninstall':
                engine.uninstall_user(target, pkg)
            elif action == 'enable':
                engine.enable(target, pkg)
            elif action == 'disable':
                engine.disable_user(target, pkg)
            elif action == 'restrict':
                engine.restrict(target, pkg)
            elif action == 'unrestrict':
                engine.unrestrict(target, pkg)
            ok += 1
            details.append((pkg, True, action + ' uygulandı'))
        except AdbError as e:
            if log:
                try:
                    log('{} snapshot: {}'.format(pkg, e))
                except Exception:
                    pass
            fail += 1
            details.append((pkg, False, str(e)))
    return {'ok': ok, 'fail': fail, 'details': details, 'action': 'snapshot'}
