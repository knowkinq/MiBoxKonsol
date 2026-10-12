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
from PySide6.QtCore import QThread, Signal

from .adb_engine import AdbError

# Sistem uygulamasi tespiti: APK yolu bu koklerden birindeyse paket
# ROM'un parcasi demektir (/data/app/... ise kullanici uygulamasidir).
SYSTEM_APK_PREFIXES = ('/system/', '/system_ext/', '/vendor/', '/product/',
                       '/apex/', '/odm/', '/oem/', '/pr/product/')


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

    def cancel(self):
        """Disaridan iptal: UI veya MainWindow.cancel_workers kullanir."""
        try:
            self.requestInterruption()
        except Exception:
            pass

    def check_cancel(self):
        """Uzun islerde faz gecislerinde cagir; iptal varsa firlatir."""
        try:
            if self.isInterruptionRequested():
                raise CancelledError('kullanici durdurdu')
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
                self.failed.emit('kullanici durdurdu')
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
        self.log.emit('Baglanti kontrol ediliyor...')
        self._engine.connect(self._target)
        self.check_cancel()
        self.log.emit('Paketler listeleniyor...')
        detailed = self._engine.list_packages_detailed(self._target, self._include_system)
        self.check_cancel()
        try:
            all_detailed = detailed if self._include_system else \
                self._engine.list_packages_detailed(self._target, True)
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
        if labels:
            self.log.emit('{} uygulamanin adi cihazdan okundu.'.format(len(labels)))
        pkgs = [e['package'] for e in detailed]
        enabled_map = {e['package']: e['enabled'] for e in detailed}
        user0_map = {e['package']: e.get('installed_user0', True) for e in detailed}
        system_map = {e['package']: is_system_apk(e.get('apk', '')) for e in detailed}
        total = len(pkgs)
        self.log.emit('Toplam {} paket bulundu. Durumlar okunuyor...'.format(total))

        running_raw = self._engine.running_processes(self._target)
        # ps -A -o NAME tek sutun: ilk gecis (hizli, yaklasik)
        running = self._engine.parse_running_packages(running_raw, pkgs)
        restricted = self._engine.bulk_restricted(self._target)
        if restricted is None:
            self.log.emit('Bulk okuma desteklenmiyor; tekil kontrol yapilacak (daha yavas).')
        else:
            self.log.emit('Bulk okuma tamam: {} kisitli uygulama bulundu.'.format(len(restricted)))

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
            if pkg in running:
                running_flag = 'Evet'
            else:
                # ps anlik goruntusunde kacmis olabilir; kucuk listelerde
                # pidof ile kesinlestir (buyuk listelerde sadece ps).
                if total <= 30 and self._engine.is_running(self._target, pkg):
                    running.add(pkg)
                    running_flag = 'Evet'
                else:
                    running_flag = 'Hayir'
            apps.append({'package': pkg, 'status': status, 'running': running_flag,
                         'enabled': enabled_map.get(pkg, True),
                         'installed_user0': user0_map.get(pkg, True),
                         'system': system_map.get(pkg, False),
                         'label': labels.get(pkg, '')})

        self.progress.emit(total, total)
        self.finished_ok.emit(apps)


class BulkActionWorker(BaseWorker):
    """Secili uygulamalara toplu islem uygular (kisitla/serbest)."""

    def __init__(self, engine, target, packages, restrict, protected):
        super().__init__()
        self.job_name = 'Toplu kisitla/serbest'
        self._engine = engine
        self._target = target
        self._packages = packages
        self._restrict = restrict
        self._protected = protected

    def _work(self):
        self._engine.connect(self._target)
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
                details.append((pkg, False, 'kullanici durdurdu'))
                self.progress.emit(i, total)
                continue
            self.progress.emit(i, total)
            if pkg in self._protected:
                skip += 1
                details.append((pkg, False, 'koruma listesinde'))
                continue
            try:
                if self._restrict:
                    self._engine.restrict(self._target, pkg)
                else:
                    self._engine.unrestrict(self._target, pkg)
                ok += 1
                details.append((pkg, True, 'tamam'))
            except AdbError as e:
                self.log.emit('{}: {}'.format(pkg, e))
                skip += 1
                details.append((pkg, False, str(e)))
        if cancelled:
            self.log.emit(u'⏹ {} paket islenmedi (kullanici durdurdu).'.format(cancelled))
        self.finished_ok.emit({'ok': ok, 'skip': skip, 'details': details,
                               'cancelled': cancelled,
                               'action': 'restrict' if self._restrict else 'unrestrict'})


class PackageActionWorker(BaseWorker):
    """Tek veya coklu paket islemi (stop/clear/enable/disable/uninstall/launch)."""

    def __init__(self, engine, target, packages, action, protected, auto_snapshot=True):
        super().__init__()
        self.job_name = 'Paket islemi'
        self._engine = engine
        self._target = target
        self._packages = packages
        self._action = action
        self._protected = protected
        self._auto_snapshot = auto_snapshot and action in (
            'uninstall', 'disable', 'restore', 'enable')

    def _take_safety_snapshot(self):
        try:
            from . import snapshot as snapmod
            name, count = snapmod.take(self._engine, self._target)
            self.log.emit('Guvenlik snapshot alindi: {} ({} paket)'.format(name, count))
            return name
        except Exception as e:  # noqa: BLE001
            self.log.emit('Guvenlik snapshot alinamadi: {}'.format(e))
            return None

    def _do(self, pkg):
        e = self._engine
        t = self._target
        if self._action == 'stop':
            e.force_stop(t, pkg)
        elif self._action == 'clear':
            e.clear_data(t, pkg)
        elif self._action == 'enable':
            e.enable(t, pkg)
        elif self._action == 'disable':
            e.disable_user(t, pkg)
        elif self._action == 'uninstall':
            e.uninstall_user(t, pkg)
        elif self._action == 'restore':
            e.install_existing(t, pkg)
        elif self._action == 'launch':
            e.launch_resolved(t, pkg)

    def _verify(self, pkg):
        """Islem sonrasi durumu dogrula; tutarsizsa hata yukseltir."""
        e = self._engine
        t = self._target
        if self._action == 'uninstall':
            if not e.is_uninstalled_for_user(t, pkg):
                raise AdbError('Dogrulama basarisiz: {} hala kurulu gorunuyor.'.format(pkg))
        elif self._action == 'disable':
            if not e.is_disabled(t, pkg):
                raise AdbError('Dogrulama basarisiz: {} hala aktif gorunuyor.'.format(pkg))
        elif self._action == 'restore':
            if e.is_uninstalled_for_user(t, pkg):
                raise AdbError('Dogrulama basarisiz: {} geri gelmedi.'.format(pkg))
        elif self._action == 'enable':
            if e.is_disabled(t, pkg):
                raise AdbError('Dogrulama basarisiz: {} hala devre disi.'.format(pkg))

    def _work(self):
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
                details.append((pkg, False, 'kullanici durdurdu'))
                fail += 1
                cancelled += 1
                self.progress.emit(i, total)
                continue
            self.progress.emit(i, total)
            if pkg in self._protected and self._action != 'stop':
                self.log.emit('{} korumali; atlandi.'.format(pkg))
                fail += 1
                details.append((pkg, False, 'koruma listesinde'))
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
            self.log.emit(u'⏹ {} paket islenmedi (kullanici durdurdu).'.format(cancelled))
        try:
            from . import history as histmod
            histmod.append_many(self._target, self._action, details)
        except Exception:
            pass
        try:
            self._engine.invalidate_pkg_cache(self._target)
        except Exception:
            pass
        self.finished_ok.emit({'ok': ok, 'fail': fail, 'details': details,
                               'cancelled': cancelled,
                               'action': self._action, 'auto_snap': snap_name})


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
        'uninstall': 'kaldirildi (user)', 'disable': 'devre disi birakildi',
        'enable': 'aktif edildi', 'restore': 'geri yuklendi', 'clear': 'verisi temizlendi',
        'stop': 'durduruldu', 'launch': 'acildi', 'smart': 'islem yapildi',
        'stage': 'islem yapildi',
    }
    verb = labels.get(action, action or 'islem yapildi')

    def display(pkg):
        if name_of:
            try:
                name = name_of(pkg)
                if name and name != pkg:
                    return '{} ({})'.format(name, pkg)
            except Exception:
                pass
        return str(pkg)

    lines = ['{} basarili, {} basarisiz/atlandi.'.format(ok, fail)]
    if res.get('auto_snap'):
        lines.append('Guvenlik snapshot: {}'.format(res['auto_snap']))
    good_rows = [(p, m) for p, good, m in details if good]
    bad_rows = [(p, m) for p, good, m in details if not good]
    if good_rows:
        lines += ['', 'Yapilan islem ({}):'.format(verb)]
        for pkg, msg in good_rows[:max_items]:
            extra = ''
            if action == 'smart' and msg:
                extra = ' — ' + str(msg)
            lines.append('+ {}{}'.format(display(pkg), extra))
        if len(good_rows) > max_items:
            lines.append('… ve {} uygulama daha (tam liste Canli Log / dosya gunlugunde).'.format(
                len(good_rows) - max_items))
    if bad_rows:
        lines += ['', 'Basarisiz / atlanan:']
        for pkg, msg in bad_rows[:max_items]:
            lines.append('X {}: {}'.format(display(pkg), msg))
        if len(bad_rows) > max_items:
            lines.append('… ve {} uygulama daha.'.format(len(bad_rows) - max_items))
    if action in ('uninstall', 'disable', 'smart', 'stage') and fail:
        lines += ['', 'Ipucu: bazi sistem paketleri Android tarafindan korunur; '
                  '"Akilli Kaldir" once devre disi birakir, olmazsa kaldirir (UAD onerisi).']
    return '\n'.join(lines)


class SmartRemoveWorker(BaseWorker):
    """Akilli kaldirma: her pakette disable dene, olmazsa uninstall (UAD sirasi)."""

    def __init__(self, engine, target, packages, protected, auto_snapshot=True):
        super().__init__()
        self.job_name = 'Akilli kaldirma'
        self._engine = engine
        self._target = target
        self._packages = packages
        self._protected = protected
        self._auto_snapshot = auto_snapshot

    def _take_safety_snapshot(self):
        """Toplu islem oncesi otomatik guvenlik snapshot'i. Basarisizsa None."""
        try:
            from . import snapshot as snapmod
            name, count = snapmod.take(self._engine, self._target)
            self.log.emit('Guvenlik snapshot alindi: {} ({} paket)'.format(name, count))
            return name
        except Exception as e:  # noqa: BLE001
            self.log.emit('Guvenlik snapshot alinamadi: {}'.format(e))
            return None

    def _work(self):
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
                details.append((pkg, False, 'kullanici durdurdu'))
                fail += 1
                cancelled += 1
                self.progress.emit(i, total)
                continue
            self.progress.emit(i, total)
            if pkg in self._protected:
                self.log.emit('{} korumali; atlandi.'.format(pkg))
                fail += 1
                details.append((pkg, False, 'koruma listesinde'))
                continue
            try:
                method, _r = self._engine.smart_remove(self._target, pkg)
                if method == 'disable':
                    msg = 'disable ile kapatildi (guvenli)'
                else:
                    msg = 'uninstall ile kaldirildi'
                ok += 1
                details.append((pkg, True, msg))
            except AdbError as e:
                self.log.emit('{} akilli-kaldirma: {}'.format(pkg, e))
                fail += 1
                details.append((pkg, False, str(e)))
        if cancelled:
            self.log.emit(u'⏹ {} paket islenmedi (kullanici durdurdu).'.format(cancelled))
        try:
            from . import history as histmod
            histmod.append_many(self._target, 'smart', details)
        except Exception:
            pass
        try:
            self._engine.invalidate_pkg_cache(self._target)
        except Exception:
            pass
        self.finished_ok.emit({'ok': ok, 'fail': fail, 'details': details,
                               'cancelled': cancelled,
                               'action': 'smart', 'auto_snap': snap_name})


class SnapshotWorker(BaseWorker):
    """Snapshot al veya uygula (arka plan). mode: 'take' | 'apply'."""

    def __init__(self, engine, target, mode, snapshot_name=None, protected=()):
        super().__init__()
        self.job_name = 'Snapshot'
        self._engine = engine
        self._target = target
        self._mode = mode
        self._snapshot_name = snapshot_name
        self._protected = protected

    def _work(self):
        from . import snapshot as snapmod
        if self._mode == 'take':
            self.check_cancel()
            name, count = snapmod.take(self._engine, self._target)
            self.finished_ok.emit({'name': name, 'count': count})
        else:
            self.check_cancel()
            snap = snapmod.load(self._snapshot_name)
            self.check_cancel()
            res = snapmod.apply(self._engine, self._target, snap,
                                protected=self._protected,
                                log=self.log.emit,
                                progress=self.progress.emit,
                                is_cancelled=self.isInterruptionRequested)
            try:
                from . import history as histmod
                histmod.append_many(self._target, 'snapshot', res.get('details', []))
            except Exception:
                pass
            self.finished_ok.emit(res)


class HealthWorker(BaseWorker):
    """Cihaz saglik ozeti (depolama/RAM/paket)."""

    def __init__(self, engine, target):
        super().__init__()
        self.job_name = 'Saglik olcumu'
        self._engine = engine
        self._target = target

    def _work(self):
        self._engine.connect(self._target)
        self.finished_ok.emit(self._engine.health(self._target))


class StageWorker(BaseWorker):
    """Sahneyi arka planda calistirir (otomatik snapshot dahil)."""

    def __init__(self, engine, target, items, protected=()):
        super().__init__()
        self.job_name = 'Sahne calistirma'
        self._engine = engine
        self._target = target
        self._items = list(items)
        self._protected = protected

    def _work(self):
        from . import stage as stagemod
        s = stagemod.Stage()
        for action, pkg in self._items:
            s.add(action, pkg)
        self.check_cancel()
        res = stagemod.run_stage(self._engine, self._target, s,
                                 protected=self._protected,
                                 log=self.log.emit,
                                 progress=self.progress.emit,
                                 is_cancelled=self.isInterruptionRequested)
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
                paths = self._engine.pm_paths(self._target, pkg)
                if not paths:
                    self.log.emit('{}: APK yolu bulunamadi.'.format(pkg))
                    fail += 1
                    continue
                if len(paths) == 1:
                    local = os.path.join(self._dest, pkg + '.apk')
                    self._engine.pull(self._target, paths[0], local)
                else:
                    pkgdir = os.path.join(self._dest, pkg)
                    os.makedirs(pkgdir, exist_ok=True)
                    for rp in paths:
                        base = rp.rsplit('/', 1)[-1] or 'base.apk'
                        self._engine.pull(self._target, rp, os.path.join(pkgdir, base))
                ok += 1
            except AdbError as e:
                self.log.emit('{}: {}'.format(pkg, e))
                fail += 1
        if cancelled:
            self.log.emit(u'⏹ {} paket yedeklenmedi (kullanici durdurdu).'.format(cancelled))
        self.finished_ok.emit({'ok': ok, 'fail': fail, 'cancelled': cancelled})
