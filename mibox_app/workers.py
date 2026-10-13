# -*- coding: utf-8 -*-
"""QThread worker'lari - UI thread'ini dondurmeden ADB isleri calistirir.

Mimari (v7): tum worker'lar BaseWorker'dan turer. Ortak sozlesme:
  - finished_ok: tek dict/liste/bytes sonuc; asla cok-argumanli sinyal yok
  - failed: str hata metni (AdbError -> ham mesaj, diger -> Tip: mesaj)
  - log/progress: ara bildirim
  - isInterruptionRequested kontrolu uzun dongulerde (Durdur destegi)

Faz 3 disiplini: uzun isler her fazda ve dongude check_cancel() cagirir.
  Iptal CancelledError yukseltir; run() bunu 'kullanici durdurdu' olarak
  loglar ve failed('kullanici durdurdu') yayinlar. run_stage/snapshot.apply
  gibi yardimcilar is_cancelled callback'i alir (StageWorker/SnapshotWorker
  self.isInterruptionRequested verir).
"""
import inspect

from PySide6.QtCore import QThread, Signal

from .adb_engine import AdbError, is_valid_package, safe_remote_path

# Sistem uygulamasi tespiti: APK yolu bu koklerden birindeyse paket
# ROM'un parcasi demektir (/data/app/... ise kullanici uygulamasidir).
SYSTEM_APK_PREFIXES = ('/system/', '/system_ext/', '/vendor/', '/product/',
                       '/apex/', '/odm/', '/oem/', '/pr/product/')


def _require_user_scope(engine, method_names, user_id):
    """Refuse secondary-user work before mutation if an engine method is owner-only."""
    if int(user_id or 0) == 0:
        return
    for name in method_names:
        method = getattr(engine, name, None)
        try:
            parameters = inspect.signature(method).parameters
        except (TypeError, ValueError, AttributeError):
            parameters = {}
        user_id_parameter = parameters.get('user_id')
        supports_user_id = (
            (user_id_parameter is not None
             and user_id_parameter.kind != inspect.Parameter.POSITIONAL_ONLY)
            or any(parameter.kind == inspect.Parameter.VAR_KEYWORD
                   for parameter in parameters.values()))
        if not supports_user_id:
            raise AdbError(
                'İşlem user {} için güvenli biçimde hedeflenemiyor: {} '
                'user_id desteği sunmuyor. İşlem yapılmadı.'.format(
                    user_id, name))


def _call_user_method(engine, name, *args, user_id=0, **kwargs):
    """Keep legacy Owner adapters working while requiring explicit user scope otherwise."""
    method = getattr(engine, name, None)
    if not callable(method):
        raise AdbError('İşlem API’si bulunamadı: {}'.format(name))
    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError, AttributeError):
        parameters = {}
    accepts_user = ('user_id' in parameters and
                    parameters['user_id'].kind != inspect.Parameter.POSITIONAL_ONLY)
    accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD
                         for parameter in parameters.values())
    if accepts_user or accepts_kwargs:
        return method(*args, user_id=user_id, **kwargs)
    if int(user_id or 0) == 0:
        return method(*args, **kwargs)
    raise AdbError(
        'İşlem user {} için güvenli biçimde hedeflenemiyor: {} user_id desteği sunmuyor.'
        .format(user_id, name))


def is_system_apk(apk):
    """APK yolu sistem bolumundeyse True (Uygulamalar 'Sistem' filtresi)."""
    path = (apk or '').strip().lower()
    return bool(path) and path.startswith(SYSTEM_APK_PREFIXES)


def _fail_text(exc):
    if isinstance(exc, AdbError):
        return str(exc)
    return '{}: {}'.format(type(exc).__name__, exc)


class CancelledError(Exception):
    """Kullanici iptali; BaseWorker.run tarafindan ozel islenir."""
    pass


class BaseWorker(QThread):
    """Ortak sinyal + hata standardi. Alt siniflar _work() uygular.

    Is adi (job_name): Canli Log'da '▶ basladi / ✔ bitti (N sn)' satirlari
    icin. Alt sinif __init__'te self.job_name atar; atamazsa sinif adi.

    TIMEOUT_S: alt sinif isterse toplam sure hedefi (bilgi amacli; asimda
    engine çağrıları kendi timeout'una uyar, worker erken bitirmeye calisir).
    """

    finished_ok = Signal(object)
    failed = Signal(str)
    log = Signal(str)
    progress = Signal(int, int)

    TIMEOUT_S = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cancelled = False

    def isInterruptionRequested(self):
        # Qt discards requests made before a thread starts. Keep cancellation
        # sticky so a queued job cannot act on a disconnected device later.
        return self._cancelled or super().isInterruptionRequested()

    def cancel(self):
        """Disaridan iptal: UI veya MainWindow.cancel_workers kullanir."""
        self._cancelled = True
        try:
            self.requestInterruption()
        except Exception:
            pass

    def check_cancel(self):
        """Uzun islerde faz gecislerinde cagir; iptal varsa firlatir."""
        try:
            if self.isInterruptionRequested():
                raise CancelledError('kullanıcı durdurdu')
        except CancelledError:
            raise
        except Exception:
            pass

    def run(self):
        import time as _time
        name = getattr(self, 'job_name', None) or type(self).__name__
        t0 = _time.time()
        try:
            self.log.emit(u'▶ {} başladı.'.format(name))
        except Exception:
            pass
        try:
            self.check_cancel()
            self._work()
            try:
                self.log.emit(u'✔ {} bitti ({:.1f} sn).'.format(name, _time.time() - t0))
            except Exception:
                pass
        except CancelledError:
            try:
                self.log.emit(u'⏹ {} durduruldu ({:.1f} sn).'.format(name, _time.time() - t0))
            except Exception:
                pass
            try:
                self.failed.emit('kullanıcı durdurdu')
            except Exception:
                pass
        except Exception as e:  # noqa: BLE001 - tek noktada yakala, standarda cevir
            try:
                self.log.emit(u'✘ {} başarısız ({:.1f} sn): {}'.format(
                    name, _time.time() - t0, _fail_text(e)))
            except Exception:
                pass
            self.failed.emit(_fail_text(e))

    def _work(self):
        raise NotImplementedError


class Worker(BaseWorker):
    """Tek bir islevi arka planda calistirir.

    Kullanim:
        w = Worker(lambda: engine.shell(t, 'getprop', 'ro.product.model'))
        w.log.connect(self.append_log)
        w.finished_ok.connect(self.on_done)
        w.failed.connect(self.on_fail)
        w.start()
    """

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.job_name = 'Arka plan isi'
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def _work(self):
        result = self._func(*self._args, **self._kwargs)
        self.finished_ok.emit(result)


class AppScanWorker(BaseWorker):
    """Tum uygulamalari tarama (bulk appops + ps ile hizli)."""

    finished_ok = Signal(list)
    presence = Signal(set)  # cihazdaki tum paketler (sistem dahil) -> Debloat sekmesi

    def __init__(self, engine, target, include_system=False):
        super().__init__()
        self.job_name = 'Uygulama tarama'
        self._engine = engine
        self._target = target
        self._include_system = include_system

    def _work(self):
        self.check_cancel()
        self.log.emit('Bağlantı kontrol ediliyor...')
        self._engine.connect(self._target)
        self.check_cancel()
        self.log.emit('Paketler listeleniyor...')
        detailed = self._engine.list_packages_detailed(
            self._target, self._include_system, use_cache=False)
        self.check_cancel()
        try:
            all_detailed = detailed if self._include_system else \
                self._engine.list_packages_detailed(self._target, True, use_cache=False)
        except AdbError:
            all_detailed = detailed
        self.presence.emit({e['package'] for e in all_detailed
                            if e.get('installed_user0', True)})
        # cihazdan GERCEK adlar (bilinen-uygulama listesi YOK):
        # tek dumpsys cagrisi, etiketsiz paketler paket adiyla gelir.
        try:
            self.log.emit('Uygulama adlari okunuyor...')
            labels = self._engine.app_labels(self._target)
        except Exception:
            labels = {}
        if not isinstance(labels, dict):
            labels = {}
        if labels:
            self.log.emit('{} uygulamanin adi cihazdan okundu.'.format(len(labels)))
        pkgs = [e['package'] for e in detailed]
        enabled_map = {e['package']: e['enabled'] for e in detailed}
        user0_map = {e['package']: e.get('installed_user0', True) for e in detailed}
        system_map = {e['package']: is_system_apk(e.get('apk', '')) for e in detailed}
        total = len(pkgs)
        self.log.emit('Toplam {} paket bulundu. Durumlar okunuyor...'.format(total))

        running_eligible = {pkg for pkg in pkgs
                            if enabled_map.get(pkg, True) and user0_map.get(pkg, True)}
        try:
            running_raw = self._engine.running_processes(self._target)
            if not running_raw or not running_raw.strip():
                raise AdbError('Boş süreç snapshot\'ı alındı.')
            running = self._engine.parse_running_packages(running_raw, running_eligible)
            running_known = True
        except AdbError as exc:
            running = set()
            running_known = False
            self.log.emit('Çalışma durumu okunamadı; bilinmiyor olarak gösterilecek: {}'.format(exc))
        restricted = self._engine.bulk_restricted(self._target)
        if restricted is None:
            self.log.emit('Bulk okuma desteklenmiyor; tekil kontrol yapilacak (daha yavaş).')
        else:
            self.log.emit('Bulk okuma tamam: {} kısıtlı uygulama bulundu.'.format(len(restricted)))

        apps = []
        for i, pkg in enumerate(pkgs, 1):
            self.check_cancel()
            if i % 25 == 0:
                self.progress.emit(i, total)
            if not self._include_system and pkg.startswith('com.android.'):
                continue
            if restricted is None:
                status = self._engine.app_status_fallback(self._target, pkg)
            else:
                status = self._engine.app_status(restricted, pkg)
            if pkg not in running_eligible:
                running_flag = 'Hayir'
            elif not running_known:
                running_flag = 'Bilinmiyor'
            else:
                running_flag = 'Evet' if pkg in running else 'Hayir'
            label = str(labels.get(pkg) or '').strip()
            if (not label or label.casefold() == pkg.casefold()
                    or ('.' in label and is_valid_package(label))):
                label = ''
            apps.append({'package': pkg, 'status': status, 'running': running_flag,
                         'enabled': enabled_map.get(pkg, True),
                         'installed_user0': user0_map.get(pkg, True),
                         'system': system_map.get(pkg, False),
                         'label': label})

        self.progress.emit(total, total)
        self.finished_ok.emit(apps)


class BulkActionWorker(BaseWorker):
    """Secili uygulamalara toplu islem uygular (kisitla/serbest)."""

    def __init__(self, engine, target, packages, restrict, protected,
                 validate_packages=False, user_id=0):
        super().__init__()
        self.job_name = 'Toplu kısıtla/serbest'
        self._engine = engine
        self._target = target
        self._packages = packages
        self._restrict = restrict
        self._protected = protected
        self._validate_packages = validate_packages
        self._user_id = int(user_id or 0)

    def _work(self):
        methods = ['restrict' if self._restrict else 'unrestrict']
        if self._validate_packages:
            methods.append('list_packages_detailed')
        _require_user_scope(self._engine, methods, self._user_id)
        self.check_cancel()
        self._engine.connect(self._target)
        self.check_cancel()
        eligible = None
        package_states = {}
        if self._validate_packages:
            entries = _call_user_method(
                self._engine, 'list_packages_detailed', self._target, True,
                use_cache=False, user_id=self._user_id)
            eligible = {entry['package'] for entry in entries
                        if entry.get('enabled', False) and entry.get('installed_user0', False)}
            package_states = {entry['package']: {'enabled': entry.get('enabled', False),
                              'installed_user0': entry.get('installed_user0', False)} for entry in entries}
            self.check_cancel()
        ok = 0
        skip = 0
        details = []
        cancelled = 0
        total = len(self._packages)
        for i, pkg in enumerate(self._packages, 1):
            if self.isInterruptionRequested():
                # Iptal bayragi kalkmaz: kalan her paket "durduruldu" isaretlenir,
                # toplamlar tutsun diye skip'e de eklenir.
                cancelled += 1
                skip += 1
                details.append((pkg, False, 'kullanıcı durdurdu'))
                self.progress.emit(i, total)
                continue
            self.progress.emit(i, total)
            if pkg in self._protected:
                skip += 1
                details.append((pkg, False, 'koruma listesinde'))
                continue
            if eligible is not None and pkg not in eligible:
                skip += 1
                details.append((pkg, False, 'Paket artık etkin veya kurulu değil.'))
                continue
            try:
                if self._restrict:
                    _call_user_method(
                        self._engine, 'restrict', self._target, pkg,
                        user_id=self._user_id)
                else:
                    _call_user_method(
                        self._engine, 'unrestrict', self._target, pkg,
                        user_id=self._user_id)
                ok += 1
                details.append((pkg, True, 'tamam'))
            except AdbError as e:
                self.log.emit('{}: {}'.format(pkg, e))
                skip += 1
                details.append((pkg, False, str(e)))
        if cancelled:
            self.log.emit(u'⏹ {} paket islenmedi (kullanıcı durdurdu).'.format(cancelled))
        self.finished_ok.emit({'ok': ok, 'skip': skip, 'details': details,
                               'cancelled': cancelled,
                               'package_states': package_states,
                               'action': 'restrict' if self._restrict else 'unrestrict',
                               'user_id': self._user_id})


class PackageActionWorker(BaseWorker):
    """Tek veya coklu paket islemi (stop/clear/enable/disable/uninstall/launch)."""

    def __init__(self, engine, target, packages, action, protected, auto_snapshot=True,
                 user_id=0):
        super().__init__()
        self.job_name = 'Paket islemi'
        self._engine = engine
        self._target = target
        self._packages = packages
        self._action = action
        self._protected = protected
        self._user_id = int(user_id or 0)
        self._auto_snapshot = auto_snapshot and action in (
            'uninstall', 'disable', 'restore', 'enable')
        self._snapshot_required = auto_snapshot and action in ('uninstall', 'disable')

    def _take_safety_snapshot(self):
        self.check_cancel()
        try:
            from . import snapshot as snapmod
            name, count = snapmod.take(
                self._engine, self._target, user_id=self._user_id,
                is_cancelled=self.check_cancel)
            self.check_cancel()
            self.log.emit(
                'User {} için paket durumu snapshot\'ı alındı: {} '
                '({} paket; uygulama verisi yedeklenmez)'.format(
                    self._user_id, name, count))
            return name
        except CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            self.log.emit('Paket durumu snapshot\'ı alınamadı: {}'.format(e))
            return None

    def _do(self, pkg):
        e = self._engine
        t = self._target
        if self._action == 'stop':
            _call_user_method(e, 'force_stop', t, pkg, user_id=self._user_id)
        elif self._action == 'clear':
            _call_user_method(e, 'clear_data', t, pkg, user_id=self._user_id)
        elif self._action == 'enable':
            _call_user_method(e, 'enable', t, pkg, user_id=self._user_id)
        elif self._action == 'disable':
            _call_user_method(e, 'disable_user', t, pkg, user_id=self._user_id)
        elif self._action == 'uninstall':
            _call_user_method(e, 'uninstall_user', t, pkg, user_id=self._user_id)
        elif self._action == 'restore':
            _call_user_method(e, 'install_existing', t, pkg, user_id=self._user_id)
        elif self._action == 'launch':
            _call_user_method(e, 'launch_resolved', t, pkg, user_id=self._user_id)
        elif self._action == 'restrict':
            _call_user_method(e, 'restrict', t, pkg, user_id=self._user_id)
        elif self._action == 'unrestrict':
            _call_user_method(e, 'unrestrict', t, pkg, user_id=self._user_id)
        else:
            raise AdbError('Bilinmeyen paket işlemi: {}'.format(self._action))

    def _verify(self, pkg):
        """Islem sonrasi durumu dogrula; tutarsizsa hata yukseltir."""
        e = self._engine
        t = self._target
        if self._action == 'uninstall':
            if not _call_user_method(
                    e, 'is_uninstalled_for_user', t, pkg, user_id=self._user_id):
                raise AdbError('Doğrulama başarısız: {} hala kurulu gorunuyor.'.format(pkg))
        elif self._action == 'disable':
            if not _call_user_method(e, 'is_disabled', t, pkg, user_id=self._user_id):
                raise AdbError('Doğrulama başarısız: {} hala aktif gorunuyor.'.format(pkg))
        elif self._action == 'restore':
            if _call_user_method(
                    e, 'is_uninstalled_for_user', t, pkg, user_id=self._user_id):
                raise AdbError('Doğrulama başarısız: {} geri gelmedi.'.format(pkg))
        elif self._action == 'enable':
            if _call_user_method(e, 'is_disabled', t, pkg, user_id=self._user_id):
                raise AdbError('Doğrulama başarısız: {} hala devre dışı.'.format(pkg))
        elif self._action in ('restrict', 'unrestrict'):
            restricted = _call_user_method(
                e, 'bulk_restricted', t, user_id=self._user_id)
            if not isinstance(restricted, (set, frozenset)):
                raise AdbError('Doğrulama başarısız: arka plan durumu okunamadı.')
            expected = self._action == 'restrict'
            if (pkg in restricted) != expected:
                raise AdbError('Doğrulama başarısız: {} arka plan durumu değişmedi.'.format(pkg))
        elif self._action not in ('stop', 'clear', 'launch'):
            raise AdbError('Bilinmeyen paket işlemi: {}'.format(self._action))

    def _work(self):
        action_methods = {
            'stop': ('force_stop',),
            'clear': ('clear_data',),
            'enable': ('enable', 'is_disabled'),
            'disable': ('disable_user', 'force_stop', 'is_disabled'),
            'uninstall': ('uninstall_user', 'force_stop', 'is_uninstalled_for_user'),
            'restore': ('install_existing',),
            'launch': ('launch_resolved',),
            'restrict': ('restrict', 'bulk_restricted'),
            'unrestrict': ('unrestrict', 'bulk_restricted'),
        }
        if self._action not in action_methods:
            raise AdbError('Bilinmeyen paket işlemi: {}'.format(self._action))
        _require_user_scope(
            self._engine, action_methods.get(self._action, ()), self._user_id)
        if self._auto_snapshot:
            from . import snapshot as snapmod
            _require_user_scope(snapmod, ('take',), self._user_id)
        self._engine.connect(self._target)
        self.check_cancel()
        snap_name = self._take_safety_snapshot() if self._auto_snapshot else None
        self.check_cancel()
        ok = 0
        fail = 0
        cancelled = 0
        details = []
        total = len(self._packages)
        for i, pkg in enumerate(self._packages, 1):
            if self.isInterruptionRequested():
                details.append((pkg, False, 'kullanıcı durdurdu'))
                fail += 1
                cancelled += 1
                self.progress.emit(i, total)
                continue
            self.progress.emit(i, total)
            if pkg in self._protected and self._action != 'stop':
                self.log.emit('{} korumali; atlandı.'.format(pkg))
                fail += 1
                details.append((pkg, False, 'koruma listesinde'))
                continue
            if self._snapshot_required and snap_name is None:
                fail += 1
                details.append((pkg, False,
                                'paket durumu snapshot\'ı alınamadı; işlem yapılmadı'))
                continue
            try:
                self._do(pkg)
                self._verify(pkg)
                ok += 1
                details.append((pkg, True, 'tamam (dogrulandi)'))
            except AdbError as e:
                self.log.emit('{} {}: {}'.format(pkg, self._action, e))
                fail += 1
                details.append((pkg, False, str(e)))
        if cancelled:
            self.log.emit(u'⏹ {} paket islenmedi (kullanıcı durdurdu).'.format(cancelled))
        try:
            from . import history as histmod
            histmod.append_many(
                self._target, self._action, details, user_id=self._user_id)
        except Exception as e:
            if self._user_id != 0:
                self.log.emit('User {} işlem geçmişi kaydedilemedi: {}'.format(
                    self._user_id, e))
        try:
            self._engine.invalidate_pkg_cache(self._target)
        except Exception:
            pass
        self.finished_ok.emit({'ok': ok, 'fail': fail, 'details': details,
                               'cancelled': cancelled,
                               'action': self._action, 'auto_snap': snap_name,
                               'user_id': self._user_id})


def format_action_result(res, name_of=None, max_items=60):
    """Sonuc ozeti: TAM olarak hangi uygulamanin islem gordugunu yazar.

    name_of(pkg)->dost ad callback'i opsiyonel. Tum paketler sayilir;
    ekrani asiri uzatmamak icin ilk max_items ayrintili yazilir, kalan
    sayisi belirtilir. Dosya gunlugunde worker detaylari zaten tutulur.
    """
    ok = res.get('ok', 0)
    fail = res.get('fail', 0)
    details = res.get('details', [])
    action = res.get('action', '')
    labels = {
        'uninstall': 'kaldırıldı (user)', 'disable': 'devre dışı bırakıldı',
        'enable': 'aktif edildi', 'restore': 'geri yuklendi', 'clear': 'verisi temizlendi',
        'stop': 'durduruldu', 'launch': 'acildi', 'smart': 'işlem yapildi',
        'stage': 'işlem yapildi',
    }
    verb = labels.get(action, action or 'işlem yapildi')

    def display(pkg):
        if name_of:
            try:
                name = name_of(pkg)
                if name and name != pkg:
                    return '{} ({})'.format(name, pkg)
            except Exception:
                pass
        return str(pkg)

    lines = ['{} başarılı, {} başarısız/atlandı.'.format(ok, fail)]
    if res.get('user_id') is not None:
        lines.append('İşlem kullanıcısı: user {}'.format(res['user_id']))
    if res.get('auto_snap'):
        lines.append('Paket durumu snapshot\'ı: {} (uygulama verisi yedeklenmez)'.format(
            res['auto_snap']))
    good_rows = [(p, m) for p, good, m in details if good]
    bad_rows = [(p, m) for p, good, m in details if not good]
    if good_rows:
        lines += ['', 'Yapilan işlem ({}):'.format(verb)]
        for pkg, msg in good_rows[:max_items]:
            extra = ''
            if action == 'smart' and msg:
                extra = ' — ' + str(msg)
            lines.append('+ {}{}'.format(display(pkg), extra))
        if len(good_rows) > max_items:
            lines.append('… ve {} uygulama daha (tam liste Canli Log / dosya gunlugunde).'.format(
                len(good_rows) - max_items))
    if bad_rows:
        lines += ['', 'Başarısız / atlanan:']
        for pkg, msg in bad_rows[:max_items]:
            lines.append('X {}: {}'.format(display(pkg), msg))
        if len(bad_rows) > max_items:
            lines.append('… ve {} uygulama daha.'.format(len(bad_rows) - max_items))
    if action in ('uninstall', 'disable', 'smart', 'stage') and fail:
        lines += ['', 'Ipucu: bazi sistem paketleri Android tarafindan korunur; '
                  '"Akilli Kaldır" önce devre dışı birakir, olmazsa kaldirir (UAD onerisi).']
    return '\n'.join(lines)


class SmartRemoveWorker(BaseWorker):
    """Akilli kaldirma: her pakette disable dene, olmazsa uninstall (UAD sirasi)."""

    def __init__(self, engine, target, packages, protected, auto_snapshot=True,
                 user_id=0):
        super().__init__()
        self.job_name = 'Akilli kaldırma'
        self._engine = engine
        self._target = target
        self._packages = packages
        self._protected = protected
        self._auto_snapshot = auto_snapshot
        self._user_id = int(user_id or 0)

    def _take_safety_snapshot(self):
        """Toplu işlem öncesi paket durumu snapshot'ı. Başarısızsa None."""
        self.check_cancel()
        try:
            from . import snapshot as snapmod
            name, count = snapmod.take(
                self._engine, self._target, user_id=self._user_id,
                is_cancelled=self.check_cancel)
            self.check_cancel()
            self.log.emit(
                'User {} için paket durumu snapshot\'ı alındı: {} '
                '({} paket; uygulama verisi yedeklenmez)'.format(
                    self._user_id, name, count))
            return name
        except CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            self.log.emit('Paket durumu snapshot\'ı alınamadı: {}'.format(e))
            return None

    def _work(self):
        _require_user_scope(
            self._engine,
            ('smart_remove', 'disable_user', 'uninstall_user', 'force_stop',
             'is_disabled', 'is_uninstalled_for_user'),
            self._user_id)
        if self._auto_snapshot:
            from . import snapshot as snapmod
            _require_user_scope(snapmod, ('take',), self._user_id)
        self._engine.connect(self._target)
        self.check_cancel()
        snap_name = self._take_safety_snapshot() if self._auto_snapshot else None
        snapshot_failed = self._auto_snapshot and snap_name is None
        self.check_cancel()
        ok = 0
        fail = 0
        cancelled = 0
        details = []
        total = len(self._packages)
        for i, pkg in enumerate(self._packages, 1):
            if self.isInterruptionRequested():
                details.append((pkg, False, 'kullanıcı durdurdu'))
                fail += 1
                cancelled += 1
                self.progress.emit(i, total)
                continue
            self.progress.emit(i, total)
            if pkg in self._protected:
                self.log.emit('{} korumali; atlandı.'.format(pkg))
                fail += 1
                details.append((pkg, False, 'koruma listesinde'))
                continue
            if snapshot_failed:
                fail += 1
                details.append((pkg, False,
                                'paket durumu snapshot\'ı alınamadı; işlem yapılmadı'))
                continue
            try:
                method, _r = _call_user_method(
                    self._engine, 'smart_remove', self._target, pkg,
                    user_id=self._user_id)
                if method == 'disable':
                    msg = 'disable ile kapatildi (güvenli)'
                else:
                    msg = 'uninstall ile kaldırıldı'
                ok += 1
                details.append((pkg, True, msg))
            except AdbError as e:
                self.log.emit('{} akilli-kaldırma: {}'.format(pkg, e))
                fail += 1
                details.append((pkg, False, str(e)))
        if cancelled:
            self.log.emit(u'⏹ {} paket islenmedi (kullanıcı durdurdu).'.format(cancelled))
        try:
            from . import history as histmod
            histmod.append_many(
                self._target, 'smart', details, user_id=self._user_id)
        except Exception as e:
            if self._user_id != 0:
                self.log.emit('User {} işlem geçmişi kaydedilemedi: {}'.format(
                    self._user_id, e))
        try:
            self._engine.invalidate_pkg_cache(self._target)
        except Exception:
            pass
        self.finished_ok.emit({'ok': ok, 'fail': fail, 'details': details,
                               'cancelled': cancelled,
                               'action': 'smart', 'auto_snap': snap_name,
                               'user_id': self._user_id})


class SnapshotWorker(BaseWorker):
    """Snapshot al veya uygula (arka plan). mode: 'take' | 'apply'."""

    def __init__(self, engine, target, mode, snapshot_name=None, protected=(),
                 user_id=0):
        super().__init__()
        self.job_name = 'Snapshot'
        self._engine = engine
        self._target = target
        self._mode = mode
        self._snapshot_name = snapshot_name
        self._protected = protected
        self._user_id = int(user_id or 0)

    def _work(self):
        from . import snapshot as snapmod
        if self._mode == 'take':
            _require_user_scope(snapmod, ('take',), self._user_id)
            self.check_cancel()
            name, count = snapmod.take(
                self._engine, self._target, user_id=self._user_id,
                is_cancelled=self.check_cancel)
            self.check_cancel()
            self.finished_ok.emit({'name': name, 'count': count,
                                   'user_id': self._user_id})
        else:
            self.check_cancel()
            snap = snapmod.load(self._snapshot_name)
            self.check_cancel()
            snapshot_user_id = int(snap.get('user_id', 0) or 0)
            if snapshot_user_id != self._user_id:
                raise AdbError(
                    'Snapshot user {} için; seçili user {} olduğundan '
                    'uygulanmadı.'.format(snapshot_user_id, self._user_id))
            res = snapmod.apply(self._engine, self._target, snap,
                                protected=self._protected,
                                log=self.log.emit,
                                progress=self.progress.emit,
                                is_cancelled=self.isInterruptionRequested)
            try:
                from . import history as histmod
                histmod.append_many(
                    self._target, 'snapshot', res.get('details', []),
                    user_id=self._user_id)
            except Exception as e:
                if self._user_id != 0:
                    self.log.emit('User {} işlem geçmişi kaydedilemedi: {}'.format(
                        self._user_id, e))
            res['user_id'] = self._user_id
            self.finished_ok.emit(res)


class HealthWorker(BaseWorker):
    """Cihaz saglik ozeti (depolama/RAM/paket)."""

    def __init__(self, engine, target):
        super().__init__()
        self.job_name = 'Sağlık olcumu'
        self._engine = engine
        self._target = target

    def _work(self):
        self._engine.connect(self._target)
        self.finished_ok.emit(self._engine.health(self._target))


class StageWorker(BaseWorker):
    """Sahneyi arka planda calistirir (otomatik snapshot dahil)."""

    def __init__(self, engine, target, items, protected=(), user_id=0):
        super().__init__()
        self.job_name = 'Sahne calistirma'
        self._engine = engine
        self._target = target
        self._items = list(items)
        self._protected = protected
        self._user_id = int(user_id or 0)

    def _run_for_user(self, stagemod):
        """Execute stage actions through the user-scoped engine and snapshot APIs."""
        from . import snapshot as snapmod

        items = self._items
        action_methods = {
            'uninstall': ('uninstall_user', 'force_stop', 'is_uninstalled_for_user'),
            'disable': ('disable_user', 'force_stop', 'is_disabled'),
            'enable': ('enable',),
            'restore': ('install_existing', 'is_uninstalled_for_user'),
            'restrict': ('restrict',),
            'unrestrict': ('unrestrict',),
            'clear': ('clear_data',),
            'stop': ('force_stop',),
            'smart': ('smart_remove', 'disable_user', 'uninstall_user', 'force_stop',
                      'is_disabled', 'is_uninstalled_for_user'),
        }
        methods = tuple(dict.fromkeys(
            method for action, _pkg in items
            for method in action_methods.get(action, ())))
        _require_user_scope(self._engine, methods, self._user_id)
        _require_user_scope(snapmod, ('take',), self._user_id)
        try:
            self._engine.connect(self._target)
        except AdbError as e:
            return {'ok': 0, 'fail': len(items),
                    'details': [(pkg, False, str(e)) for _action, pkg in items],
                    'action': 'stage', 'auto_snap': None,
                    'user_id': self._user_id}

        self.check_cancel()
        snap_name = None
        snapshot_failed = False
        try:
            snap_name, _count = snapmod.take(
                self._engine, self._target, user_id=self._user_id,
                is_cancelled=self.check_cancel)
            self.check_cancel()
            self.log.emit(
                'User {} için paket durumu snapshot\'ı: {} '
                '(uygulama verisi yedeklenmez)'.format(self._user_id, snap_name))
        except CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            snapshot_failed = True
            self.log.emit('Paket durumu snapshot\'ı alınamadı: {}'.format(e))

        ok = 0
        fail = 0
        details = []
        history_details = []
        required_actions = stagemod._SNAPSHOT_REQUIRED_ACTIONS

        def record(action, pkg, succeeded, message, history_action=None):
            details.append((pkg, succeeded, message))
            history_details.append((
                action if history_action is None else history_action,
                pkg, succeeded, message))

        total = len(items)
        for i, (action, pkg) in enumerate(items, 1):
            self.progress.emit(i, total)
            if self.isInterruptionRequested():
                fail += 1
                record(action, pkg, False, 'kullanıcı durdurdu')
                continue
            if pkg in (self._protected or ()):
                fail += 1
                record(action, pkg, False, 'koruma listesinde')
                continue
            if snapshot_failed and action in required_actions:
                fail += 1
                record(action, pkg, False,
                       'paket durumu snapshot\'ı alınamadı; işlem yapılmadı')
                continue
            try:
                history_action = action
                if action == 'uninstall':
                    self._engine.uninstall_user(
                        self._target, pkg, user_id=self._user_id)
                    if not self._engine.is_uninstalled_for_user(
                            self._target, pkg, user_id=self._user_id):
                        raise AdbError('doğrulama başarısız: hala kurulu')
                elif action == 'disable':
                    self._engine.disable_user(
                        self._target, pkg, user_id=self._user_id)
                    if not self._engine.is_disabled(
                            self._target, pkg, user_id=self._user_id):
                        raise AdbError('doğrulama başarısız: hala aktif')
                elif action == 'enable':
                    self._engine.enable(self._target, pkg, user_id=self._user_id)
                elif action == 'restore':
                    self._engine.install_existing(
                        self._target, pkg, user_id=self._user_id)
                elif action == 'restrict':
                    self._engine.restrict(self._target, pkg, user_id=self._user_id)
                elif action == 'unrestrict':
                    self._engine.unrestrict(self._target, pkg, user_id=self._user_id)
                elif action == 'clear':
                    self._engine.clear_data(self._target, pkg, user_id=self._user_id)
                elif action == 'stop':
                    self._engine.force_stop(self._target, pkg, user_id=self._user_id)
                elif action == 'smart':
                    method, _result = self._engine.smart_remove(
                        self._target, pkg, user_id=self._user_id)
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
                    result = stagemod.ACTION_TR.get(action, action) + ' (doğrulandı)'
                record(action, pkg, True, result, history_action)
            except AdbError as e:
                self.log.emit('{} {}: {}'.format(pkg, action, e))
                fail += 1
                record(action, pkg, False, str(e))

        try:
            from . import history as histmod
            histmod.append_many(
                self._target, 'stage', history_details, user_id=self._user_id)
        except Exception as e:
            self.log.emit('User {} işlem geçmişi kaydedilemedi: {}'.format(
                self._user_id, e))
        try:
            self._engine.invalidate_pkg_cache(self._target)
        except Exception:
            pass
        return {'ok': ok, 'fail': fail, 'details': details,
                'action': 'stage', 'auto_snap': snap_name,
                'user_id': self._user_id}

    def _work(self):
        from . import stage as stagemod
        if self._user_id != 0:
            self.finished_ok.emit(self._run_for_user(stagemod))
            return
        s = stagemod.Stage()
        for action, pkg in self._items:
            s.add(action, pkg)
        self.check_cancel()
        res = stagemod.run_stage(self._engine, self._target, s,
                                 protected=self._protected,
                                 log=self.log.emit,
                                 progress=self.progress.emit,
                                 is_cancelled=self.isInterruptionRequested)
        res['user_id'] = self._user_id
        self.finished_ok.emit(res)


class ScreenshotWorker(BaseWorker):
    finished_ok = Signal(bytes)

    def __init__(self, engine, target):
        super().__init__()
        self.job_name = 'Ekran goruntusu'
        self._engine = engine
        self._target = target

    def _work(self):
        self._engine.connect(self._target)
        data = self._engine.screenshot(self._target)
        # PNG gecerliligini worker'da dogrula (bozuk veri UI'a gitmesin)
        from .adb_engine import png_is_valid
        if not png_is_valid(data):
            self.failed.emit('Ekran goruntusu bozuk indi (PNG degil). Tekrar deneyin.')
            return
        self.finished_ok.emit(data)


class DeviceInfoWorker(BaseWorker):
    finished_ok = Signal(dict)

    def __init__(self, engine, target):
        super().__init__()
        self.job_name = 'Cihaz bilgisi'
        self._engine = engine
        self._target = target

    def _work(self):
        self._engine.connect(self._target)
        info = self._engine.device_info_full(self._target)
        self.finished_ok.emit(info)


class ApkBackupWorker(BaseWorker):
    """Split APK dahil yedekleme (pm path -> tum yollari pull)."""

    def __init__(self, engine, target, packages, dest_dir):
        super().__init__()
        self.job_name = 'APK yedekleme'
        self._engine = engine
        self._target = target
        self._packages = packages
        self._dest = dest_dir

    @staticmethod
    def _validated_remote_apk_path(remote):
        """Validate pm output and reject device paths with unsafe leaf names."""
        raw = str(remote or '')
        if not raw.startswith('/') or '\\' in raw:
            raise AdbError('Cihaz geçersiz bir APK yolu döndürdü.')
        path = safe_remote_path(raw)
        leaf = path.rsplit('/', 1)[-1]
        if (not leaf.lower().endswith('.apk') or leaf == '.apk'
                or any(ch in '<>:"|?*' for ch in leaf)):
            raise AdbError('Cihaz geçersiz bir APK dosya adı döndürdü.')
        return path

    def _pull_single_atomically(self, remote, destination, pkg):
        import os
        import shutil
        import tempfile

        staging_dir = tempfile.mkdtemp(prefix='.mibox-apk-', dir=self._dest)
        try:
            staged_path = os.path.join(staging_dir, pkg + '.apk')
            self.check_cancel()
            self._engine.pull(self._target, remote, staged_path)
            self.check_cancel()
            os.replace(staged_path, destination)
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    def _pull_split_set(self, remote_paths, package_dir, pkg):
        import os
        import shutil
        import tempfile

        staging_dir = tempfile.mkdtemp(
            prefix='.mibox-{}-'.format(pkg), dir=self._dest)
        old_dir = None
        try:
            for index, remote in enumerate(remote_paths):
                self.check_cancel()
                # Local names are generated only from the validated list order;
                # never join a path component derived from device output.
                local_name = 'base.apk' if index == 0 else 'split_{:03d}.apk'.format(index)
                self._engine.pull(
                    self._target, remote, os.path.join(staging_dir, local_name))
            self.check_cancel()

            if os.path.lexists(package_dir):
                if os.path.islink(package_dir) or not os.path.isdir(package_dir):
                    raise AdbError('Mevcut APK yedek dizini güvenli biçimde değiştirilemiyor.')
                old_dir = tempfile.mkdtemp(
                    prefix='.mibox-old-{}-'.format(pkg), dir=self._dest)
                os.rmdir(old_dir)
                os.replace(package_dir, old_dir)
            try:
                os.replace(staging_dir, package_dir)
                staging_dir = None
            except OSError as replace_error:
                if old_dir is not None:
                    try:
                        os.replace(old_dir, package_dir)
                        old_dir = None
                    except OSError as restore_error:
                        raise AdbError(
                            'Yeni APK seti yerleştirilemedi; eski yedek {} konumunda '
                            'korundu: {} (geri alma: {})'.format(
                                old_dir, replace_error, restore_error)) from replace_error
                raise
            if old_dir is not None:
                try:
                    shutil.rmtree(old_dir)
                except OSError as e:
                    self.log.emit(
                        '{}: eski yedek dizini temizlenemedi ({}): {}'.format(
                            pkg, old_dir, e))
                old_dir = None
        finally:
            if staging_dir is not None:
                shutil.rmtree(staging_dir, ignore_errors=True)

    def _work(self):
        import os
        self._engine.connect(self._target)
        self.check_cancel()
        os.makedirs(self._dest, exist_ok=True)
        ok = 0
        fail = 0
        cancelled = 0
        total = len(self._packages)
        for i, pkg in enumerate(self._packages, 1):
            if self.isInterruptionRequested():
                fail += 1
                cancelled += 1
                self.progress.emit(i, total)
                continue
            self.progress.emit(i, total)
            try:
                if not is_valid_package(pkg):
                    raise AdbError('Geçersiz paket adı: {!r}'.format(pkg))
                paths = self._engine.pm_paths(self._target, pkg)
                if not paths:
                    self.log.emit('{}: APK yolu bulunamadı.'.format(pkg))
                    fail += 1
                    continue
                remote_paths = [self._validated_remote_apk_path(path) for path in paths]
                if len(set(remote_paths)) != len(remote_paths):
                    raise AdbError('Cihaz tekrarlanan APK yolları döndürdü.')
                if len(paths) == 1:
                    local = os.path.join(self._dest, pkg + '.apk')
                    self._pull_single_atomically(remote_paths[0], local, pkg)
                else:
                    pkgdir = os.path.join(self._dest, pkg)
                    self._pull_split_set(remote_paths, pkgdir, pkg)
                ok += 1
            except CancelledError:
                self.log.emit('{}: yedekleme kullanıcı tarafından durduruldu.'.format(pkg))
                fail += 1
                cancelled += 1
            except (AdbError, OSError) as e:
                self.log.emit('{}: {}'.format(pkg, e))
                fail += 1
        if cancelled:
            self.log.emit(u'⏹ {} paket yedeklenmedi (kullanıcı durdurdu).'.format(cancelled))
        self.finished_ok.emit({'ok': ok, 'fail': fail, 'cancelled': cancelled})
