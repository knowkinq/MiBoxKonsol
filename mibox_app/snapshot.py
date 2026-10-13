# -*- coding: utf-8 -*-
"""Paket durumu snapshot sistemi; uygulama verisi yedeklemez.

Snapshot = {paket: {'enabled': bool, 'installed_user0': bool, 'restricted': bool}}
`user_id` bu durumların hangi Android kullanıcısına ait olduğunu belirtir;
eski dosyalarda alan yoksa user 0 kabul edilir.
JSON dosyası: mibox-snapshot-<etiket>.json

Uygulama (apply): snapshot'taki her paket için mevcut durumla karşılaştır,
farklıysa düzelt (disable/uninstall/restore/enable/restrict/unrestrict).
UAD-NG "apply snapshots to multiple Androids" yaklaşımı baz alındı.
"""
import datetime
import inspect
import json
import os
import tempfile
import threading

from .adb_engine import AdbError, is_valid_package

# Read/delete operations share a lock. New files are published through an
# atomic hard link so separate processes cannot overwrite a same-name capture.
_SNAP_LOCK = threading.Lock()
_SNAPSHOT_PREFIX = 'mibox-snapshot-'
_SNAPSHOT_SUFFIX = '.json'
_SNAPSHOT_KEYS = frozenset(('created', 'target', 'packages'))
_SNAPSHOT_USER_KEYS = _SNAPSHOT_KEYS | frozenset(('user_id',))
_PACKAGE_STATE_KEYS = frozenset(('enabled', 'installed_user0', 'restricted'))


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
        if name.startswith(_SNAPSHOT_PREFIX) and name.endswith(_SNAPSHOT_SUFFIX):
            out.append(name)
    return out


def snapshot_path(name):
    if (type(name) is not str or '/' in name or '\\' in name
            or not name.startswith(_SNAPSHOT_PREFIX)
            or not name.endswith(_SNAPSHOT_SUFFIX)):
        raise ValueError('Geçersiz snapshot adı.')
    return os.path.join(_dir(), name)


def _validate_user_id(user_id):
    if type(user_id) is not int or not 0 <= user_id <= 21474:
        raise ValueError('Geçersiz snapshot kullanıcı kimliği.')
    return user_id


def validate(data):
    """Validate a snapshot's complete serialized schema before it is used."""
    if type(data) is not dict or set(data) not in (_SNAPSHOT_KEYS, _SNAPSHOT_USER_KEYS):
        raise ValueError('Geçersiz snapshot dosyası (şema hatalı).')
    if type(data.get('created')) is not str or type(data.get('target')) is not str:
        raise ValueError('Geçersiz snapshot dosyası (metadata türü hatalı).')
    _validate_user_id(data.get('user_id', 0))
    pkgs = data.get('packages')
    if type(pkgs) is not dict or not pkgs:
        raise ValueError('Geçersiz snapshot dosyası (packages boş/bozuk).')
    for pkg, state in pkgs.items():
        if (type(pkg) is not str or pkg != pkg.strip() or ':' in pkg
                or not is_valid_package(pkg)):
            raise ValueError('Geçersiz snapshot dosyası (paket adı: {}).'.format(pkg))
        if type(state) is not dict or set(state) != _PACKAGE_STATE_KEYS:
            raise ValueError('Geçersiz snapshot dosyası (bozuk kayıt: {}).'.format(pkg))
        if any(type(state[key]) is not bool for key in _PACKAGE_STATE_KEYS):
            raise ValueError('Geçersiz snapshot dosyası (boole durumu hatalı: {}).'.format(pkg))
    return data


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Geçersiz snapshot dosyası (yinelenen alan: {}).'.format(key))
        result[key] = value
    return result


def _accepts_user_id(method):
    try:
        parameters = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(parameter.name == 'user_id'
               or parameter.kind == inspect.Parameter.VAR_KEYWORD
               for parameter in parameters)


def _call_user_api(engine, names, kwargs, user_id, description):
    """Call a user-aware engine API, falling back to legacy APIs for user 0."""
    user_id = _validate_user_id(user_id)
    for index, name in enumerate(names):
        method = getattr(engine, name, None)
        if not callable(method):
            continue
        accepts_user = _accepts_user_id(method)
        is_legacy_default = index == len(names) - 1 and user_id == 0
        if not accepts_user and not is_legacy_default:
            continue
        call_kwargs = dict(kwargs)
        if accepts_user:
            call_kwargs['user_id'] = user_id
        else:
            call_kwargs.pop('user_id', None)
        try:
            parameters = inspect.signature(method).parameters
        except (TypeError, ValueError):
            parameters = {}
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
            return method(**call_kwargs)
        return method(**{key: value for key, value in call_kwargs.items()
                         if key in parameters})
    raise AdbError('{} user {} için desteklenmiyor.'.format(description, user_id))


def _save_unique(name, data):
    """Atomically add a complete snapshot under an unused name across processes."""
    directory = _dir()
    stem = name[:-len(_SNAPSHOT_SUFFIX)]
    fd, tmp = tempfile.mkstemp(prefix='.mibox-snapshot-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        suffix = 1
        while True:
            candidate = name if suffix == 1 else '{}-{}.json'.format(stem, suffix)
            path = snapshot_path(candidate)
            try:
                # A hard link publishes the fully written file and fails if
                # another process already claimed this name.
                os.link(tmp, path)
                return candidate
            except FileExistsError:
                suffix += 1
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _validated_entries(detailed):
    """Reject incomplete package scans before they can drive snapshot actions."""
    if not isinstance(detailed, (list, tuple)) or not detailed:
        raise AdbError('Paket listesi boş veya bozuk; snapshot kaydedilmedi.')
    entries = {}
    for entry in detailed:
        if not isinstance(entry, dict):
            raise AdbError('Paket listesi bozuk kayıt içeriyor; snapshot kaydedilmedi.')
        pkg = entry.get('package')
        if (type(pkg) is not str or pkg != pkg.strip()
                or not is_valid_package(pkg) or ':' in pkg or pkg in entries
                or type(entry.get('enabled')) is not bool
                or type(entry.get('installed_user0')) is not bool):
            raise AdbError('Paket listesi bozuk kayıt içeriyor; snapshot kaydedilmedi.')
        entries[pkg] = entry
    return entries


def load(name):
    with _SNAP_LOCK:
        with open(snapshot_path(name), 'r', encoding='utf-8') as f:
            raw = f.read()
    return validate(json.loads(raw, object_pairs_hook=_unique_json_object))


def import_snapshot(path):
    """Validate and import an external snapshot without replacing existing files."""
    with open(path, 'r', encoding='utf-8') as f:
        data = validate(json.load(f, object_pairs_hook=_unique_json_object))
    preferred_name = 'mibox-snapshot-klon-{}.json'.format(
        datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    return _save_unique(preferred_name, data), len(data['packages'])


def delete(name):
    try:
        with _SNAP_LOCK:
            os.remove(snapshot_path(name))
        return True
    except (OSError, ValueError):
        return False


def take(engine, target, include_system=True, user_id=0, is_cancelled=None):
    """Mevcut durumu yakala. Dönüş: (dosya_adı, paket_sayısı)."""
    user_id = _validate_user_id(user_id)
    if is_cancelled is not None:
        is_cancelled()
    engine.connect(target)
    if is_cancelled is not None:
        is_cancelled()
    # snapshot her zaman GERCEGI gormeli: onbellek atlanir.
    detailed = _call_user_api(
        engine,
        ('list_packages_detailed_for_user_id', 'list_packages_detailed_for_user',
         'list_packages_detailed'),
        {'target': target, 'include_system': include_system, 'use_cache': False},
        user_id, 'Paket durumunu kullanıcıya göre okuma')
    if is_cancelled is not None:
        is_cancelled()
    entries = _validated_entries(detailed)
    restricted = _call_user_api(
        engine,
        ('bulk_restricted_for_user_id', 'bulk_restricted_for_user', 'bulk_restricted'),
        {'target': target}, user_id, 'Arka plan kısıtlamalarını kullanıcıya göre okuma')
    if is_cancelled is not None:
        is_cancelled()
    if restricted is None:
        raise AdbError('Arka plan kisitlama durumu okunamadi; snapshot kaydedilmedi.')
    if (not isinstance(restricted, (set, frozenset))
            or any(type(pkg) is not str or pkg != pkg.strip()
                   or not is_valid_package(pkg) or ':' in pkg for pkg in restricted)):
        raise AdbError('Arka plan kisitlama listesi bozuk; snapshot kaydedilmedi.')
    pkgs = {}
    for p, e in entries.items():
        pkgs[p] = {
            'enabled': e['enabled'],
            'installed_user0': e['installed_user0'],
            'restricted': p in restricted,
        }
    label = _safe_label('{}-{}'.format(
        target.replace(':', '-'), datetime.datetime.now().strftime('%Y%m%d-%H%M%S')))
    name = '{}{}.json'.format(_SNAPSHOT_PREFIX, label)
    data = {
        'created': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'target': target,
        'user_id': user_id,
        'packages': pkgs,
    }
    if is_cancelled is not None:
        is_cancelled()
    name = _save_unique(name, data)
    return name, len(pkgs)


def diff_current(engine, target, snap):
    """Snapshot ile mevcut durum farkı: [(pkg, beklenen, mevcut, aksiyon)]."""
    snap = validate(snap)
    user_id = snap.get('user_id', 0)
    engine.connect(target)
    detailed = _call_user_api(
        engine,
        ('list_packages_detailed_for_user_id', 'list_packages_detailed_for_user',
         'list_packages_detailed'),
        {'target': target, 'include_system': True, 'use_cache': False},
        user_id, 'Paket durumunu kullanıcıya göre okuma')
    entries = _validated_entries(detailed)
    restricted = _call_user_api(
        engine,
        ('bulk_restricted_for_user_id', 'bulk_restricted_for_user', 'bulk_restricted'),
        {'target': target}, user_id, 'Arka plan kısıtlamalarını kullanıcıya göre okuma')
    if restricted is None:
        raise AdbError('Arka plan kisitlama durumu okunamadi; snapshot uygulanamadi.')
    if (not isinstance(restricted, (set, frozenset))
            or any(type(pkg) is not str or pkg != pkg.strip()
                   or not is_valid_package(pkg) or ':' in pkg for pkg in restricted)):
        raise AdbError('Arka plan kisitlama listesi bozuk; snapshot uygulanamadi.')
    cur = {}
    for p, e in entries.items():
        cur[p] = {
            'enabled': e['enabled'],
            'installed_user0': e['installed_user0'],
            'restricted': p in restricted,
        }
    diffs = []
    for pkg, want in snap.get('packages', {}).items():
        have = cur.get(pkg)
        if have is None:
            diffs.append((pkg, want, None, 'bilinmiyor (cihazda yok)'))
            continue
        actions = []
        if want['installed_user0']:
            restored = not have['installed_user0']
            if restored:
                actions.append('restore')
            if restored or want['enabled'] != have['enabled']:
                actions.append('enable' if want['enabled'] else 'disable')
            if restored or want['restricted'] != have['restricted']:
                actions.append('restrict' if want['restricted'] else 'unrestrict')
        elif have['installed_user0']:
            # Once removed for this user, enabled and background state cannot
            # be changed until the package is installed again.
            actions.append('uninstall')
        if actions:
            diffs.append((pkg, want, have, tuple(actions)))
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
    successful = set()
    for i, (pkg, _want, _have, action) in enumerate(diffs, 1):
        if progress:
            try:
                progress(i, total)
            except Exception:
                pass
        try:
            if is_cancelled is not None and is_cancelled():
                details.append((pkg, False, 'kullanıcı durdurdu'))
                fail += 1
                continue
        except Exception:
            pass
        if isinstance(action, str) and action.startswith('bilinmiyor'):
            details.append((pkg, False, action))
            fail += 1
            continue
        if pkg in (protected or ()):
            details.append((pkg, False, 'koruma listesinde'))
            fail += 1
            continue
        try:
            user_id = snap.get('user_id', 0)
            methods = {
                'restore': ('install_existing_user_id', 'install_existing_for_user_id',
                            'install_existing_for_user', 'install_existing'),
                'uninstall': ('uninstall_user_id', 'uninstall_for_user_id',
                              'uninstall_for_user', 'uninstall_user'),
                'enable': ('enable_user_id', 'enable_for_user_id', 'enable_for_user', 'enable'),
                'disable': ('disable_user_id', 'disable_for_user_id',
                            'disable_for_user', 'disable_user'),
                'restrict': ('restrict_user_id', 'restrict_for_user_id',
                             'restrict_for_user', 'restrict'),
                'unrestrict': ('unrestrict_user_id', 'unrestrict_for_user_id',
                               'unrestrict_for_user', 'unrestrict'),
            }
            actions = (action,) if isinstance(action, str) else tuple(action)
            if not actions or any(step not in methods for step in actions):
                raise AdbError('Bilinmeyen snapshot işlemi: {}'.format(action))
            for step in actions:
                if is_cancelled is not None and is_cancelled():
                    raise AdbError('kullanıcı durdurdu')
                _call_user_api(engine, methods[step],
                               {'target': target, 'pkg': pkg}, user_id,
                               'Snapshot işlemi {}'.format(step))
            ok += 1
            successful.add(pkg)
            details.append((pkg, True, '{} uygulandı'.format(' → '.join(actions))))
        except AdbError as e:
            if log:
                try:
                    log('{} snapshot: {}'.format(pkg, e))
                except Exception:
                    pass
            fail += 1
            details.append((pkg, False, str(e)))

    # Operations can each succeed while a later operation changes an earlier
    # state (for example install_existing may re-enable a package). Re-read the
    # complete snapshot once and only report success for final matching states.
    if successful:
        try:
            remaining = diff_current(engine, target, snap)
            remaining_by_pkg = {pkg: action for pkg, _want, _have, action in remaining}
        except Exception as exc:  # noqa: BLE001
            remaining_by_pkg = {pkg: 'son durum doğrulanamadı: {}'.format(exc)
                                for pkg in successful}
        for pkg in successful:
            if pkg not in remaining_by_pkg:
                continue
            ok -= 1
            fail += 1
            message = 'Snapshot son durumu eşleşmedi: {}'.format(
                remaining_by_pkg[pkg])
            details = [(p, passed, message if p == pkg and passed else msg)
                       for p, passed, msg in details]
    return {'ok': ok, 'fail': fail, 'details': details, 'action': 'snapshot'}
