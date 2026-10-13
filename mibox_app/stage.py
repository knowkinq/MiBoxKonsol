# -*- coding: utf-8 -*-
"""Sahne (staging): işlemleri uygulamadan önce topla, önizle, sonra çalıştır.

Kullanım: Debloat/Profil/Sağlık sekmeleri işlem listesini buraya ekler,
kullanıcı Önizle ile görür, Uygula ile tek worker zincirinde çalıştırır.
Her sahne çalışması öncesi otomatik güvenlik snapshot'ı alınır.
"""
from .adb_engine import AdbError

# (aksiyon, paket) -> insan dilinde açıklama
ACTION_TR = {
    'uninstall': 'Kaldır (user 0)', 'disable': 'Devre dışı bırak',
    'enable': 'Aktif et', 'restore': 'Geri yükle',
    'restrict': 'Kısıtla', 'unrestrict': 'Serbest bırak',
    'clear': 'Veriyi sil', 'stop': 'Force stop',
}

ACTION_ICON = {
    'uninstall': '🗑', 'disable': '⏸', 'enable': '▶', 'restore': '♻',
    'restrict': '🔒', 'unrestrict': '🔓', 'clear': '🧹', 'stop': '⏹',
}

# Geri dönüşü olmayan/zor olanlar uyarılır
RISKY_ACTIONS = {'uninstall', 'clear'}


class Stage:
    def __init__(self):
        self._items = []  # [(action, pkg)]

    def add(self, action, pkg):
        key = (action, pkg)
        if key not in self._items:
            self._items.append(key)
            return True
        return False

    def add_many(self, action, pkgs):
        n = 0
        for p in pkgs:
            if self.add(action, p):
                n += 1
        return n

    def remove(self, action, pkg):
        key = (action, pkg)
        if key in self._items:
            self._items.remove(key)
            return True
        return False

    def clear(self):
        self._items = []

    def items(self):
        return list(self._items)

    def count(self):
        return len(self._items)

    def summary(self):
        """Aksiyona göre gruplanmış özet: {action: [pkgs]}."""
        groups = {}
        for action, pkg in self._items:
            groups.setdefault(action, []).append(pkg)
        return groups

    def describe(self, friendly=None):
        """Önizleme metni satırları."""
        lines = []
        for action, pkgs in self.summary().items():
            icon = ACTION_ICON.get(action, '•')
            label = ACTION_TR.get(action, action)
            lines.append('{} {} ({} paket):'.format(icon, label, len(pkgs)))
            for p in pkgs[:20]:
                name = friendly(p) if friendly else p
                extra = ' ⚠ geri dönüşü zor' if action in RISKY_ACTIONS else ''
                lines.append('    {}  {}{}'.format(p, '' if name == p else '(' + name + ')', extra))
            if len(pkgs) > 20:
                lines.append('    ... ve {} tane daha'.format(len(pkgs) - 20))
        return lines


def run_stage(engine, target, stage, protected=(), log=None, progress=None,
              verify=True, is_cancelled=None):
    """Sahneyi çalıştır. Dönüş: {'ok','fail','details','action':'stage','auto_snap'}.

    is_cancelled: opsiyonel callable -> True ise kalan isler 'kullanici
    durdurdu' sayilir (Faz 3 iptal disiplini). StageWorker self.isInterruptionRequested verir.
    """
    from . import snapshot as snapmod
    items = stage.items() if isinstance(stage, Stage) else list(stage)
    try:
        engine.connect(target)
    except AdbError as e:
        return {'ok': 0, 'fail': len(items),
                'details': [(p, False, str(e)) for _a, p in items],
                'action': 'stage', 'auto_snap': None}
    snap_name = None
    try:
        snap_name, _c = snapmod.take(engine, target)
        if log:
            log('Güvenlik snapshot: {}'.format(snap_name))
    except Exception as e:  # noqa: BLE001
        if log:
            log('Snapshot alınamadı: {}'.format(e))
    ok, fail, details = 0, 0, []
    total = len(items)
    for i, (action, pkg) in enumerate(items, 1):
        if progress:
            try:
                progress(i, total)
            except Exception:
                pass
        try:
            if is_cancelled is not None and is_cancelled():
                fail += 1
                details.append((pkg, False, 'kullanıcı durdurdu'))
                continue
        except Exception:
            pass
        if pkg in (protected or ()):
            fail += 1
            details.append((pkg, False, 'koruma listesinde'))
            continue
        try:
            if action == 'uninstall':
                engine.uninstall_user(target, pkg)
                if verify and not engine.is_uninstalled_for_user(target, pkg):
                    raise AdbError('doğrulama başarısız: hala kurulu')
            elif action == 'disable':
                engine.disable_user(target, pkg)
                if verify and not engine.is_disabled(target, pkg):
                    raise AdbError('doğrulama başarısız: hala aktif')
            elif action == 'enable':
                engine.enable(target, pkg)
            elif action == 'restore':
                engine.install_existing(target, pkg)
            elif action == 'restrict':
                engine.restrict(target, pkg)
            elif action == 'unrestrict':
                engine.unrestrict(target, pkg)
            elif action == 'clear':
                engine.clear_data(target, pkg)
            elif action == 'stop':
                engine.force_stop(target, pkg)
            else:
                raise AdbError('bilinmeyen aksiyon: ' + action)
            ok += 1
            details.append((pkg, True, ACTION_TR.get(action, action) + ' (doğrulandı)'))
        except AdbError as e:
            if log:
                try:
                    log('{} {}: {}'.format(pkg, action, e))
                except Exception:
                    pass
            fail += 1
            details.append((pkg, False, str(e)))
    try:
        from . import history as histmod
        histmod.append_many(target, 'stage', details)
    except Exception:
        pass
    try:
        engine.invalidate_pkg_cache(target)
    except Exception:
        pass
    return {'ok': ok, 'fail': fail, 'details': details,
            'action': 'stage', 'auto_snap': snap_name}
