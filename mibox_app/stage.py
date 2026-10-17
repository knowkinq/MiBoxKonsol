# -*- coding: utf-8 -*-
"""Sahne (staging): işlemleri uygulamadan önce topla, önizle, sonra çalıştır.

Kullanım: Debloat/Profil/Sağlık sekmeleri işlem listesini buraya ekler,
kullanıcı Önizle ile görür, Uygula ile tek worker zincirinde çalıştırır.
Her sahne çalışması öncesi paket durum snapshot'ı alınır; uygulama verisi
snapshot'a dahil değildir.
"""
from .action_labels import ACTION_TR  # geriye uyumlu disa aktarim
from .adb_engine import AdbError

ACTION_ICON = {
    'uninstall': '🗑', 'disable': '⏸', 'enable': '▶', 'restore': '♻',
    'restrict': '🔒', 'unrestrict': '🔓', 'clear': '🧹', 'stop': '⏹',
    'smart': '⚡',
}

# Geri dönüşü olmayan/zor olanlar uyarılır. Akıllı kaldırma, yedek yöntem
# olarak paketi kaldırabildiğinden önizlemede riskli kabul edilir.
RISKY_ACTIONS = {'uninstall', 'clear', 'smart'}
_SNAPSHOT_REQUIRED_ACTIONS = {
    'uninstall', 'disable', 'restrict', 'unrestrict', 'smart',
}


class Stage:
    def __init__(self):
        self._items = []  # [(action, pkg)]
        self._item_tokens = {}
        self._next_token = 0

    def add(self, action, pkg):
        key = (action, pkg)
        if key not in self._items:
            self._items.append(key)
            self._next_token += 1
            self._item_tokens[key] = self._next_token
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
            self._item_tokens.pop(key, None)
            return True
        return False

    def items_with_tokens(self):
        """Return staged entries with identities for safe async completion updates."""
        return [(action, pkg, self._item_tokens[(action, pkg)])
                for action, pkg in self._items]

    def remove_if_unchanged(self, action, pkg, token):
        """Remove an entry only if it is still the same queued instance."""
        if self._item_tokens.get((action, pkg)) != token:
            return False
        return self.remove(action, pkg)

    def clear(self):
        self._items = []
        self._item_tokens.clear()

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
        engine.connect(target, cancel_check=is_cancelled)
    except AdbError as e:
        if is_cancelled is not None and is_cancelled():
            from .workers import CancelledError
            raise CancelledError('kullanıcı durdurdu')
        return {'ok': 0, 'fail': len(items),
                'details': [(p, False, str(e)) for _a, p in items],
                'failed_items': list(items),
                'action': 'stage', 'auto_snap': None}
    snap_name = None
    snapshot_failed = False
    try:
        snap_name, _c = snapmod.take(
            engine, target, is_cancelled=is_cancelled)
        if log:
            log('Paket durumu snapshot\'ı: {} (uygulama verisi yedeklenmez)'.format(snap_name))
    except Exception as e:  # noqa: BLE001
        from .workers import CancelledError
        if isinstance(e, CancelledError):
            raise
        if is_cancelled is not None and is_cancelled():
            raise CancelledError('kullanıcı durdurdu')
        snapshot_failed = True
        if log:
            log('Paket durumu snapshot\'ı alınamadı: {}'.format(e))
    ok, fail, details, history_details, failed_items = 0, 0, [], [], []

    def record(action, pkg, succeeded, message, history_action=None):
        details.append((pkg, succeeded, message))
        if not succeeded:
            failed_items.append((action, pkg))
        history_details.append((
            action if history_action is None else history_action,
            pkg, succeeded, message))

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
                record(action, pkg, False, 'kullanıcı durdurdu')
                continue
        except Exception:
            pass
        if pkg in (protected or ()):
            fail += 1
            record(action, pkg, False, 'koruma listesinde')
            continue
        if snapshot_failed and action in _SNAPSHOT_REQUIRED_ACTIONS:
            fail += 1
            record(action, pkg, False,
                   'paket durumu snapshot\'ı alınamadı; işlem yapılmadı')
            continue
        try:
            history_action = action
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
            elif action == 'smart':
                method, _result = engine.smart_remove(target, pkg)
                if method == 'disable':
                    result = 'Akıllı kaldırma: devre dışı bırakıldı ve doğrulandı'
                elif method == 'uninstall':
                    result = 'Akıllı kaldırma: kullanıcı için kaldırıldı ve doğrulandı'
                else:
                    raise AdbError('akıllı kaldırma beklenmeyen yöntem döndürdü')
                history_action = method
            else:
                raise AdbError('bilinmeyen aksiyon: ' + action)
            ok += 1
            if action != 'smart':
                result = ACTION_TR.get(action, action) + ' (doğrulandı)'
            record(action, pkg, True, result, history_action)
        except AdbError as e:
            if log:
                try:
                    log('{} {}: {}'.format(pkg, action, e))
                except Exception:
                    pass
            fail += 1
            record(action, pkg, False, str(e))
    try:
        from . import history as histmod
        histmod.append_many(target, 'stage', history_details)
    except Exception:
        pass
    try:
        engine.invalidate_pkg_cache(target)
    except Exception:
        pass
    return {'ok': ok, 'fail': fail, 'details': details,
            'failed_items': failed_items,
            'action': 'stage', 'auto_snap': snap_name}
