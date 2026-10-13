# -*- coding: utf-8 -*-
"""ADB motoru - subprocess tabanli.

Not: Bu sinif kendisi thread-safe DEGILDIR; her cagri bir worker thread
icinde yapilmalidir (UI thread'inde calistirmayin). Birden fazla worker
ayni anda calisabilecegi icin paket onbelligi (_pkg_cache) kilitli tutulur
ve uretim sayaci (generation) ile yarisma onlenir: tarama sirasinda bir
yazma islemi onbelligi iptal ederse, o sirada biten taramanin bayati verisi
tekrar onbellige yazilmaz.
"""
import os
import re
import shutil
import subprocess
import sys
import threading
import time

CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

# input text icin transliterasyon: ADB 'input text' ASCII disi karakterleri
# ve shell metakarakterlerini kabul etmez; Turkce harfleri ASCII'ye indirger,
# geri kalani atar.
_TR_CHARS = {
    'ç': 'c', 'Ç': 'C', 'ğ': 'g', 'Ğ': 'G', 'ı': 'i', 'İ': 'I',
    'ö': 'o', 'Ö': 'O', 'ş': 's', 'Ş': 'S', 'ü': 'u', 'Ü': 'U',
}
# input text icin izinli semboller (shell metakarakterleri HARIC).
_INPUT_SAFE_SYMBOLS = set('-_.,:/@+=')


def _repair_png(data):
    """Windows ADB exec-out CRLF bozulmasini onarmaya calisir.

    Bazi Windows surumlerinde stdout '\n' -> '\r\n' cevirir; PNG imzasi cift-CR olur.
    Onarim: 0D 0D 0A -> 0D 0A geri cevirir; gecerli PNG degilse None.
    """
    if not data:
        return None
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return data  # zaten saglikli
    # Windows text-mode stdout her LF'den once CR ekleyebilir: orijinal
    # CRLF -> CR CR LF olur. Cift-CR'yi tekle; imza VE IEND kuyrugu
    # saglamsa kabul et (govdedeki yalniz-LF bozulmasi kurtarilamaz,
    # bu durumda None doner ve dosya-yolu yonteme dusulur).
    fixed = data.replace(b'\r\r\n', b'\r\n')
    if png_is_valid(fixed):
        return fixed
    return None


def png_is_valid(data):
    """Gercek PNG mi? (imza + IEND kuyrugu kontrolu)."""
    if not data or len(data) < 24:
        return False
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        return False
    tail = data.rstrip(b'\r\n').rstrip(b'\n')
    return tail.endswith(b'\x00\x00\x00\x00IEND\xaeB`\x82')


def _base_dir():
    """Uygulama kok klasoru (.exe dondurulmisse exe klasoru)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sanitize_input_text(text):
    """'adb shell input text' icin guvenli metin uretir.

    - Turkce karakterleri ASCII karsiligina indirger.
    - Bosluk -> %s; harf/rakam ve -_.,:/@+= disindaki her sey atilir
      (shell metakarakterleri komut kirilmasina yol acardi).
    - ASCII disi kalan karakterleri atar (cihazda '?' olusmamasi icin).
    """
    out = []
    for ch in text:
        if ch in _TR_CHARS:
            out.append(_TR_CHARS[ch])
        elif ch == ' ':
            out.append('%s')
        elif ch.isascii() and (ch.isalnum() or ch in _INPUT_SAFE_SYMBOLS):
            out.append(ch)
        # diger her sey (%, shell metakarakterleri, emoji, unicode) atilir
    return ''.join(out)


PKG_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)*(:[A-Za-z0-9_]+)?$')


def is_valid_package(pkg):
    """Android paket adi bicimi gecerli mi? (enjeksiyon onleme)"""
    return bool(pkg) and bool(PKG_RE.match(str(pkg).strip()))


LOGCAT_LEVELS = frozenset(('V', 'D', 'I', 'W', 'E', 'F'))
TAG_RE = re.compile(r'^[A-Za-z0-9_.\-]{1,64}$')
HOME_COMP_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+/[A-Za-z0-9_.$]+$')
ANIM_SCALES = frozenset(('0', '0.5', '1', '1.0'))


def is_valid_tag(tag):
    return bool(tag) and bool(TAG_RE.match(str(tag).strip()))


def is_valid_home_component(comp):
    return bool(comp) and bool(HOME_COMP_RE.match(str(comp).strip()))


# --- Google TV / Android TV kurulum sihirbazi (HOME kilidi) --------------
# Cihaz "kurulmadi" sayildigi surece sihirbaz HOME'u kendi RecoveryActivity'sine
# kilitler: 'cmd package set-home-activity' hatasiz doner ama resolve-activity
# hala sihirbazi gosterir. Cozum: cihazi kurulmus isaretlemek + sihirbazi
# user 0 icin devre disi birakmak.
SETUP_WIZARD_PKGS = frozenset((
    'com.google.android.tungsten.setupwraith',
    'com.android.tungsten.setupwraith',
    'com.google.android.setupwizard',
    'com.android.setupwizard',
    'com.google.android.tvsetup',
    'com.android.tvsetup',
    'com.google.android.apps.tvsetup',
    'com.android.provision',
))
SETUP_WIZARD_TAILS = frozenset(('setupwraith', 'setupwizard', 'tvsetup', 'provision'))


def is_setup_wizard_pkg(pkg):
    """Paket adi bir kurulum sihirbazi mi? (HOME kilidi suphesi)"""
    p = str(pkg or '').strip().lower()
    if not p:
        return False
    if p in SETUP_WIZARD_PKGS:
        return True
    return p.rsplit('.', 1)[-1] in SETUP_WIZARD_TAILS


def home_pkg_of(activity):
    """'paket/.Aktivite' ya da 'paket/Aktivite' -> 'paket' (gecersizse '')."""
    a = str(activity or '').strip()
    if '/' in a:
        a = a.split('/', 1)[0]
    a = a.strip()
    return a if is_valid_package(a) else ''


# --- Baglanti dayanikliligi ------------------------------------------------
# Cihaz uyku modunda / ag dalgaliyken adb connect zaman asimi verebilir
# (logda: 'adb connect ... 8024ms HATA: zaman asimi'). Bu durumda tekrar
# denemek anlamlidir; kalici hatalarda (yetki yok, adb yok) degildir.
_TRANSIENT_CONNECT_RE = re.compile(
    # 'zaman asimi' (eski) ve 'zaman aşımı' (Türkçe) yazımlarının ikisi de:
    r'zaman\s*a[sş][iı]m[iı]|timeout|timed out|could not|can\'t connect|'
    r'cannot connect|unable to connect|failed to connect|no route|'
    r'connection refused|reset by peer|protocol fault|device offline',
    re.I)

WATCHDOG_BASE_S = 15
WATCHDOG_MAX_S = 60


def is_transient_connect_error(text):
    """Baglanti hatasi gecici mi? (tekrar denemeye deger)"""
    return bool(_TRANSIENT_CONNECT_RE.search(str(text or '')))


def watchdog_interval(fail_count, base=WATCHDOG_BASE_S, max_interval=WATCHDOG_MAX_S):
    """Ardisik basarisiz bekci denemesine gore yoklama araligi (saniye).

    0-1 hata -> base, 2 hata -> 2*base, 3+ hata -> max_interval.
    Cihaz uykudayken her 15 sn'de bir bosa ADB cagrilmasi boylece biter.
    """
    try:
        n = int(fail_count)
    except (TypeError, ValueError):
        return base
    if n <= 1:
        return base
    if n == 2:
        return min(base * 2, max_interval)
    return max_interval


def clamp_lines(lines, default=200, lo=1, hi=2000):
    try:
        n = int(lines)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def check_user_id(user_id):
    try:
        n = int(user_id)
    except (TypeError, ValueError):
        raise AdbError('Geçersiz kullanıcı id: {!r}'.format(user_id))
    if not 0 <= n <= 100:
        raise AdbError('Geçersiz kullanıcı id: {!r}'.format(user_id))
    return n


def safe_remote_path(path):
    """Cihazdaki dosya yolu icin guvenli bicim uretir.

    - Bosluk ve shell metakarakterlerini atar (arguman listesi olarak
      gecirilse de bazi Android surumleri shell'de yorumlayabilir).
    - Yalnizca mutlak yol kabul edilir (relative kacinma onlenir).
    """
    p = (path or '').strip().replace('\\', '/')
    if not p.startswith('/'):
        p = '/' + p
    out = []
    for ch in p:
        if ch.isalnum() or ch in '/._-:@+':
            out.append(ch)
        else:
            out.append('_')
    p = ''.join(out) or '/'
    # '..' ile disari kacinma onlenir
    parts = [seg for seg in p.split('/') if seg not in ('', '.')]
    if '..' in parts:
        parts = [seg for seg in parts if seg != '..']
    return '/' + '/'.join(parts) if parts else '/'


class AdbError(Exception):
    """ADB isleminde basarisizlik."""


class AdbResult:
    def __init__(self, exit_code, output, error):
        self.exit_code = exit_code
        self.output = output
        self.error = error

    @property
    def ok(self):
        return self.exit_code == 0

    def __str__(self):
        return (self.output or self.error) or ''


class AdbEngine:
    """ADB komutlarini calistiran, ADB'yi otomatik bulan motor.

    Komut izi (v8.1): her calistirilan ADB cagrisi trace_cb'ye bildirilir:
      trace_cb(cmd_list, ok: bool, ms: int, err: str)
    UI bunu Canli Log'a 'ADB' seviyesiyle yazar. trace_cb yoksa sessizdir.
    Uzun cikti kirpilir; hassas veri (pair kodu) maskelenir.
    """

    # logda gosterilmeyecek/gizlenecek komutlar
    _MASK_ARGS = {'pair'}

    def __init__(self, adb_path=None, trace_cb=None):
        self.adb_path = adb_path or self.find_adb()
        if not self.adb_path:
            raise AdbError(
                'ADB bulunamadı. platform-tools klasorunu program yanina koyun '
                'veya adb.exe\'i PATH\'e ekleyin.'
            )
        self.trace_cb = trace_cb
        # set_home_activity ek adimlarinin insan-okur ozeti (UI gosterir).
        self.last_home_notes = []
        # Onbellek ARTIK ornek basina; kilit class seviyesinde (eski orneklerle
        # ortak kullanima da guvenli) — asagida _pkg_cache_lock tanimli.

    def _trace(self, args, ok, ms, err='', probe=False):
        cb = getattr(self, 'trace_cb', None)
        if not cb:
            return
        try:
            shown = list(args)
            for i, a in enumerate(shown):
                # 'adb pair HOST:PORT KOD' -> host ve kodun TAMAMI maskelenir
                if str(a).lower() in self._MASK_ARGS:
                    for j in range(i + 1, len(shown)):
                        shown[j] = '******'
            try:
                cb(shown, ok, ms, (err or '')[:200], bool(probe))
            except TypeError:
                # eski imzali callback (4 arg) uyumlulugu
                cb(shown, ok, ms, (err or '')[:200])
        except Exception:
            pass

    @staticmethod
    def find_adb():
        base = _base_dir()
        candidates = [
            os.path.join(base, 'adb.exe'),
            os.path.join(base, 'platform-tools', 'adb.exe'),
            os.path.join(base, 'platform-tools', 'adb'),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return shutil.which('adb') or shutil.which('adb.exe')

    # ------------------------------------------------------------------
    def run(self, args, timeout=30, binary=False, quiet_first=False):
        """quiet_first: exit!=0 'yoklama negatif sonucu' sayilir.

        trace_cb imzasi genisledi: (cmd, ok, ms, err, probe).
        probe=True ise UI bunu ADB degil VERBOSE sayar (gri, varsayilan kapali).
        """
        import time as _time
        cmd = [self.adb_path] + [str(a) for a in args]
        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = CREATE_NO_WINDOW
        t0 = _time.time()
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=timeout, **kwargs)
        except subprocess.TimeoutExpired:
            self._trace(args, False, int((_time.time() - t0) * 1000), 'zaman aşımı')
            raise AdbError('ADB zaman aşımı ({} sn): adb {}'.format(timeout, ' '.join(str(a) for a in args)))
        except OSError as e:
            self._trace(args, False, int((_time.time() - t0) * 1000), str(e)[:120])
            raise AdbError('ADB calistirilamadi: {}'.format(e))
        out, err = r.stdout, r.stderr
        if not binary:
            out = out.decode('utf-8', 'replace').strip()
            err = err.decode('utf-8', 'replace').strip()
        else:
            out, err = out or b'', (err or b'').decode('utf-8', 'replace').strip()
        ms = int((_time.time() - t0) * 1000)
        ok = (r.returncode == 0)
        if quiet_first:
            # negatif sonuc: hata degil, sessiz probe
            self._trace(args, True, ms, '', probe=True)
        else:
            self._trace(args, ok, ms, '' if ok else (err or out if isinstance(err, str) else '')[:200])
        return AdbResult(r.returncode, out, err)

    # ------------------------------------------------------------------
    # Baglanti
    # ------------------------------------------------------------------
    def connect(self, target, timeout=10, deneme=1, bekleme=0.6):
        """Baglanti kurar; basarisizsa AdbError.

        deneme=1 (varsayilan): tek deneme — etkilesimli 'Baglan' hizli basarisiz
        olsun. Arka plan bekcisi deneme=2 verir: zaman asimi/ag hatasi gecici
        sayilir ve kisa bir beklemeden sonra bir kez daha denenir.
        """
        import time as _time
        deneme = max(1, int(deneme or 1))
        son_hata = None
        for i in range(deneme):
            try:
                r = self.run(['connect', target], timeout=timeout)
            except AdbError as e:
                if i + 1 < deneme and is_transient_connect_error(str(e)):
                    son_hata = e
                    _time.sleep(bekleme)
                    continue
                raise
            text = '{} {}'.format(r.output, r.error)
            if r.exit_code != 0 or re.search(r'failed|refused|cannot|unreachable|unable|no route',
                                             text, re.I):
                hata = AdbError('Bağlantı başarısız: {} (Cihaz uyku modunda olabilir; '
                                'fiziksel kumandayla uyandin.)'.format(text.strip()))
                if i + 1 < deneme and is_transient_connect_error(text):
                    son_hata = hata
                    _time.sleep(bekleme)
                    continue
                raise hata
            st = self.run(['-s', target, 'get-state'], timeout=timeout)
            if st.output != 'device':
                hata = AdbError('Cihaz hazır degil: {} {}'.format(st.output, st.error))
                if i + 1 < deneme and is_transient_connect_error('{} {}'.format(st.output, st.error)):
                    son_hata = hata
                    _time.sleep(bekleme)
                    continue
                raise hata
            return target
        raise son_hata or AdbError('Bağlantı kurulamadi: {}'.format(target))

    def disconnect(self, target):
        try:
            self.run(['disconnect', target], timeout=10)
        except AdbError:
            pass

    def pair(self, host_port, code, timeout=15):
        """Android 11+ kablosuz eslestirme (adb pair host:port kod)."""
        r = self.run(['pair', host_port, str(code)], timeout=timeout)
        text = '{} {}'.format(r.output, r.error)
        if r.exit_code != 0 or re.search(r'failed|error|wrong|incorrect', text, re.I):
            raise AdbError('Eşleştirme başarısız: {}'.format(text.strip()))
        return text.strip()

    def devices(self):
        r = self.run(['devices', '-l'], timeout=15)
        devs = []
        for line in r.output.splitlines():
            line = line.strip()
            if not line or line.startswith('List of devices'):
                continue
            parts = line.split()
            if len(parts) >= 2 and re.search(r'[\.:]', parts[0]):
                devs.append({'id': parts[0], 'state': parts[1], 'detail': line})
        return devs

    def get_state(self, target):
        return self.run(['-s', target, 'get-state'], timeout=10).output

    # ------------------------------------------------------------------
    # Shell
    # ------------------------------------------------------------------
    # Negatif-sonuc NORMAL olan yoklamalar: izde ERROR degil 'yoklama' sayilir.
    # pidof (calismiyor), pm path (yok), dumpsys kismi, get (bos deger).
    QUIET_FIRST = {'pidof', 'pm', 'dumpsys', 'getprop', 'settings'}

    def shell(self, target, *cmd, timeout=30, quiet=False):
        return self.run(['-s', target, 'shell'] + list(cmd), timeout=timeout,
                        quiet_first=quiet and bool(cmd) and str(cmd[0]) in self.QUIET_FIRST)

    def getprop(self, target, prop):
        return self.shell(target, 'getprop', prop).output.strip()

    # ------------------------------------------------------------------
    # Uygulamalar
    # ------------------------------------------------------------------
    def list_packages(self, target, include_system=False):
        flag = '-a' if include_system else '-3'
        r = self.shell(target, 'pm', 'list', 'packages', flag)
        pkgs = []
        for line in r.output.splitlines():
            line = line.strip()
            if line.startswith('package:'):
                pkgs.append(line[len('package:'):].strip())
        return pkgs

    def list_packages_user0(self, target, timeout=30):
        """user 0 icin GERCEKTEN kurulu paketler (kaldirilanlar haric).

        'pm list packages --user 0' sadece bu kullanicida gorunur
        paketleri dondurur; '--user 0' ile kaldirilmis sistem
        uygulamalari listede CIKMAZ.
        """
        try:
            r = self.shell(target, 'pm', 'list', 'packages', '--user', '0', timeout=timeout)
        except AdbError:
            return None
        pkgs = set()
        for line in (r.output or '').splitlines():
            line = line.strip()
            if line.startswith('package:'):
                pkgs.add(line[len('package:'):].strip())
        return pkgs

    # Paket listesi önbelleği: {(target, include_system): (zaman, veri)}
    # Coklu worker thread erisimine karsi kilit + uretim sayaci (generation):
    # invalidate -> generation artar; bayat okumayla baslayan tarama eski
    # generation ile yazar, put() sayac uyusmadigi icin reddedilir.
    _pkg_cache = {}
    _pkg_cache_ttl = 60
    _pkg_cache_gen = 0
    _pkg_cache_lock = threading.Lock()

    def _pkg_cache_get(self, target, include_system):
        """(veri, generation) dondurur; miss ise (None, generation)."""
        key = (target, bool(include_system))
        with self._pkg_cache_lock:
            gen = self._pkg_cache_gen
            hit = self._pkg_cache.get(key)
            if hit and (time.time() - hit[0]) < self._pkg_cache_ttl:
                return hit[1], gen
            return None, gen

    def _pkg_cache_put(self, target, include_system, data, gen=None):
        """Onbellige yazar. gen verilmis ve bayattiysa yazmaz (yarisma onlenir).

        Donus: True = yazildi, False = bayat/iptal edilmis yazma reddedildi.
        """
        key = (target, bool(include_system))
        with self._pkg_cache_lock:
            if gen is not None and gen != self._pkg_cache_gen:
                return False
            self._pkg_cache[key] = (time.time(), data)
            return True

    def invalidate_pkg_cache(self, target=None):
        """Yazma işlemlerinden sonra çağır (uninstall/disable/restore...).

        Sadece ilgili anahtarlari silmekle kalmaz, uretim sayacini da
        artirir; o anda surulen taramalarin bayat sonuclari yazilmaz.
        """
        with self._pkg_cache_lock:
            if target is None:
                self._pkg_cache.clear()
            else:
                for key in [k for k in self._pkg_cache if k[0] == target]:
                    del self._pkg_cache[key]
            self._pkg_cache_gen += 1

    @classmethod
    def clear_pkg_cache_for_tests(cls):
        """Test yardimcisi: onbellek ve sayaci sifirla."""
        with cls._pkg_cache_lock:
            cls._pkg_cache.clear()
            cls._pkg_cache_gen += 1

    def list_packages_detailed(self, target, include_system=False, use_cache=True):
        """Paket + APK yolu + kurulum/devre disi/user0 durumu (hizli).

        Donus: [{'package':, 'apk':, 'enabled': bool, 'installed_user0': bool}]

        Not: Android 8+ APK yolu '.../base.apk=com.pkg' biciminde ve yolun
        kendisi '==' icerebilir (ornegin
        /data/app/~~XXXX==/com.pkg-YYYY==/base.apk=com.pkg). Bu yuzden
        sondaki SON '=' isaretinden bolunur (rpartition).

        Not: '--user 0' ile kaldirilmis sistem uygulamalari '-a' listesinde
        HALA gorunur. 'installed_user0=False' olanlar listede rozetli
        gosterilir, sag tiktan geri yuklenebilir.

        use_cache=True ise 60 sn onbellek kullanilir (tarama hizi).
        Yazma islemleri sonrasi invalidate_pkg_cache() cagrilmalidir.
        """
        gen = None
        if use_cache:
            hit, gen = self._pkg_cache_get(target, include_system)
            if hit is not None:
                return [dict(e) for e in hit]
        flag = '-a' if include_system else '-3'
        r = self.shell(target, 'pm', 'list', 'packages', '-f', flag, timeout=60)
        out = []
        for line in r.output.splitlines():
            line = line.strip()
            if not line.startswith('package:'):
                continue
            body = line[len('package:'):].strip()
            # SON '=' ayirici: sol APK yolu, sag paket adi.
            apk, sep, pkg = body.rpartition('=')
            pkg = pkg.strip()
            apk = apk.strip()
            if not sep or not pkg or ' ' in pkg:
                continue
            out.append({'package': pkg, 'apk': apk, 'enabled': True,
                        'installed_user0': True})
        # user 0'da gercekten kurulu olanlar (kaldirilanlari isaretle)
        user0 = self.list_packages_user0(target)
        if user0 is not None:
            for e in out:
                e['installed_user0'] = e['package'] in user0
        # devre disi olanlari isaretle (pm list packages -d)
        try:
            rd = self.shell(target, 'pm', 'list', 'packages', '-d', timeout=30)
            disabled = set()
            for line in rd.output.splitlines():
                line = line.strip()
                if line.startswith('package:'):
                    disabled.add(line[len('package:'):].strip())
            for e in out:
                if e['package'] in disabled:
                    e['enabled'] = False
        except AdbError:
            pass
        if use_cache:
            # gen: bayat olani yazma (islem sirasinda invalidate olmus olabilir)
            self._pkg_cache_put(target, include_system,
                                [dict(e) for e in out], gen)
        return out

    def running_processes(self, target):
        """Calisan process adlarini dondurur (ps -A -o NAME)."""
        r = self.shell(target, 'ps', '-A', '-o', 'NAME')
        if r.output.strip():
            return r.output
        # eski cihazlarda -o destegi yoksa tam ps ciktisi
        return self.shell(target, 'ps', '-A').output

    @staticmethod
    def parse_running_packages(ps_output, known_packages=None):
        """'ps' ciktisindan calisan paket seti cikarir.

        - NAME-only ciktida (ps -A -o NAME) her satir tek process adidir.
        - Tam 'ps -A' ciktisinda son sutundaki process adi alinir.
        - known_packages verilirse SADECE listedeki paketler eslesir
          (alt-string hatasi olmaz: 'com.a' ile 'com.ab' karismaz).
        - known_packages yoksa nokta iceren gecerli process adlari alinir.
        """
        running = set()
        known = set(known_packages or [])
        for line in (ps_output or '').splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith('USER') or line.startswith('LABEL') or line.startswith('NAME'):
                continue
            if ' ' in line or '\t' in line:
                # tam ps tablosu: son sutun process adi
                parts = line.split()
                if not parts:
                    continue
                name = parts[-1].strip()
            else:
                name = line
            # 'com.example.app' veya 'com.example.app:service' bicimi
            name = name.split(':')[0]
            if known:
                if name in known:
                    running.add(name)
            elif '.' in name and re.match(r'^[a-zA-Z][\w\.]+$', name):
                running.add(name)
        return running

    def is_running(self, target, pkg, timeout=10):
        """Tek paket icin kesin calisma kontrolu.

        pidof, calismayan paketlerde exit=1 verir; bu NORMAL bir negatif
        sonuctur, hata degildir. trace'e noisy ERROR dusurmemek icin
        quiet=True shell yolu kullanilir.
        """
        try:
            r = self.shell(target, 'pidof', pkg, timeout=timeout, quiet=True)
            return bool(r.output.strip() and r.output.strip()[0].isdigit())
        except AdbError:
            return False

    def app_labels(self, target, timeout=120):
        """Cihazdaki GERCEK uygulama adlari (dumpsys package'tan).

        Donus: {paket: etiket}. Etiket yoksa paket listede olmaz;
        cagiran paket adini kullanir. Tek ADB cagrisi (hizli).
        Cihaz desteklemiyorsa bos dict doner.
        """
        try:
            r = self.shell(target, 'dumpsys', 'package', timeout=timeout)
        except AdbError:
            return {}
        labels = {}
        cur = None
        for line in (r.output or '').splitlines():
            s = line.strip()
            if s.startswith('Package ['):
                end = s.find(']')
                cur = s[len('Package ['):end].strip() if end > 0 else None
                continue
            if cur is None:
                continue
            if s.startswith('application-label:') or s.startswith('application-label '):
                body = s.split(':', 1)[1] if ':' in s else s.split(None, 1)[1]
                label = body.strip().strip('\'"')
                if label and label != cur:
                    labels[cur] = label
                cur = None
        return labels

    def bulk_restricted(self, target):
        """RUN_IN_BACKGROUND/RUN_ANY_IN_BACKGROUND=ignore olanlari TEK'ER cagri ile alir.

        `cmd appops query-op ... ignore` kullanir; iki op'un birlesimini doner
        (restrict() ikisini de 'ignore' yaptigi icin tek op yetmezdi).
        Donus: paket seti. Cihaz komutu desteklemiyorsa None doner.
        (Desteklenen ama bos durumda bos set doner.)
        """
        out = set()
        supported = False
        for op in ('RUN_IN_BACKGROUND', 'RUN_ANY_IN_BACKGROUND'):
            r = self.shell(target, 'cmd', 'appops', 'query-op', op, 'ignore', timeout=60)
            if r.exit_code != 0 or re.search(r'(?im)^\s*(error|unknown)', r.output):
                continue
            supported = True
            for line in r.output.splitlines():
                line = line.strip()
                # 'No operations.' gibi bilgi satirlarini ele (paket degil):
                # gecerli paket adinda bosluk olmaz, 'No ' ile baslamaz.
                if line and ' ' not in line and not line.lower().startswith('no '):
                    out.add(line)
        return out if supported else None

    def app_status_fallback(self, target, pkg):
        """Bulk cagrisi bos donerse tek paket icin kullanim.

        Donus: 'Kisitli' | 'Serbest'
        """
        try:
            r = self.shell(target, 'cmd', 'appops', 'get', pkg, 'RUN_IN_BACKGROUND', timeout=10)
            if 'ignore' in r.output:
                return 'Kisitli'
        except AdbError:
            pass
        return 'Serbest'

    @staticmethod
    def app_status(restricted, pkg):
        if restricted is not None and pkg in restricted:
            return 'Kisitli'
        return 'Serbest'

    def restrict(self, target, pkg):
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        self.shell(target, 'cmd', 'appops', 'set', pkg, 'RUN_IN_BACKGROUND', 'ignore')
        self.shell(target, 'cmd', 'appops', 'set', pkg, 'RUN_ANY_IN_BACKGROUND', 'ignore')
        self.shell(target, 'am', 'set-standby-bucket', pkg, 'restricted')

    def unrestrict(self, target, pkg):
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        self.shell(target, 'cmd', 'appops', 'set', pkg, 'RUN_IN_BACKGROUND', 'allow')
        self.shell(target, 'cmd', 'appops', 'set', pkg, 'RUN_ANY_IN_BACKGROUND', 'allow')
        self.shell(target, 'am', 'set-standby-bucket', pkg, 'active')

    def force_stop(self, target, pkg):
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        return self.shell(target, 'am', 'force-stop', pkg)

    def clear_data(self, target, pkg):
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        r = self.shell(target, 'pm', 'clear', pkg)
        text = '{} {}'.format(r.output, r.error)
        if r.exit_code != 0 or re.search(r'failed|not allowed|no such|unknown', text, re.I):
            raise AdbError('Veri silinemedi ({}): {}'.format(pkg, text.strip() or 'bilinmeyen hata'))
        return r

    def enable(self, target, pkg):
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        r = self.shell(target, 'pm', 'enable', pkg)
        text = '{} {}'.format(r.output, r.error)
        if r.exit_code != 0 or re.search(r'failed|not allowed|no such|unknown', text, re.I):
            raise AdbError('Aktif edilemedi ({}): {}'.format(pkg, text.strip() or 'bilinmeyen hata'))
        return r

    def disable_user(self, target, pkg):
        """UAD yontemi: force-stop + clear + disable-user (sirali).

        Donus: (durum, mesaj). durum True ise paket gercekten devre disi.
        """
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        try:
            self.force_stop(target, pkg)
        except AdbError:
            pass
        try:
            self.clear_data(target, pkg)
        except AdbError:
            pass
        r = self.shell(target, 'pm', 'disable-user', '--user', '0', pkg)
        text = '{} {}'.format(r.output, r.error)
        if r.exit_code != 0 or re.search(r'failed|not allowed|cannot|no such|unknown', text, re.I):
            raise AdbError('Devre dışı birakilamadi ({}): {}'.format(pkg, text.strip() or 'bilinmeyen hata'))
        if not self.is_disabled(target, pkg):
            raise AdbError('Komut calisti ama {} hala aktif gorunuyor.'.format(pkg))
        return r

    def uninstall_user(self, target, pkg):
        """Kullanici icin kaldirma. pm ciktisini DOGRULAR.

        Sistem uygulamalarinda 'Failure [not installed for 0]' gibi
        cikti sessizce basari sayilmaz; AdbError atilir. Zaten kaldirilmis
        paket icin tekrar denemek basari sayilir (idempotent).
        UAD-ng yontemi: force-stop + clear oncesi uygulanir.
        """
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        if self.is_uninstalled_for_user(target, pkg):
            return None  # zaten kaldirilmis -> basari
        try:
            self.force_stop(target, pkg)
        except AdbError:
            pass
        try:
            self.clear_data(target, pkg)
        except AdbError:
            pass
        r = self.shell(target, 'pm', 'uninstall', '--user', '0', pkg)
        text = '{} {}'.format(r.output, r.error)
        if re.search(r'\bSuccess\b', text):
            return r
        if re.search(r'not installed for|already|no such package|unknown package', text, re.I):
            # Yaris durumu: komut sirasinda zaten gitmis -> basari say.
            if self.is_uninstalled_for_user(target, pkg):
                return r
        raise AdbError('Kaldırılamadı ({}): {}'.format(pkg, text.strip() or 'bilinmeyen hata'))

    def install_existing(self, target, pkg):
        """Geri yukleme (UAD: cmd package install-existing --user 0).

        Eski 'pm install-existing' bazi Android 14 surumlerinde sessiz
        kalir; once 'cmd package' denenir, olmazsa 'pm' yedegi kullanilir.
        Cikti ve durum DOGRULANIR.
        """
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        last_err = ''
        for args in (['cmd', 'package', 'install-existing', '--user', '0', pkg],
                     ['pm', 'install-existing', '--user', '0', pkg],
                     ['pm', 'install-existing', pkg]):
            r = self.shell(target, *args)
            text = '{} {}'.format(r.output, r.error)
            if re.search(r'\bSuccess\b', text) or 'installed for user' in text.lower():
                if not self.is_uninstalled_for_user(target, pkg):
                    # install-existing bazi surumlerde devre disi birakir;
                    # UAD sirasi: geri yukle + aktif et.
                    try:
                        self.enable(target, pkg)
                    except AdbError:
                        pass
                    return r
                last_err = text.strip()
                continue
            last_err = text.strip()
        raise AdbError('Geri yuklenemedi ({}): {}'.format(pkg, last_err or 'bilinmeyen hata'))

    def smart_remove(self, target, pkg):
        """Akilli kaldirma (UAD onerisi: disable dene, olmazsa uninstall).

        Sirayla dener, ilk basarili yontemi dondurur:
        1. disable-user (en guvenli, geri donusu kolay)
        2. uninstall --user 0 (daha derin, geri donusu zor)
        Ikisi de basarisizsa son hatayi yukseltir.
        Donus: (yontem, sonuc) ; yontem 'disable' | 'uninstall'.
        """
        errors = []
        try:
            r = self.disable_user(target, pkg)
            return ('disable', r)
        except AdbError as e:
            errors.append('disable: ' + str(e))
        try:
            r = self.uninstall_user(target, pkg)
            return ('uninstall', r)
        except AdbError as e:
            errors.append('uninstall: ' + str(e))
        raise AdbError('{} kaldirilamadi.\n{}'.format(pkg, '\n'.join(errors)))

    def is_uninstalled_for_user(self, target, pkg, timeout=10):
        """Paket user 0 icin kaldirilmis mi? ('Failure [not installed for 0]')."""
        if not is_valid_package(str(pkg).strip()):
            return False
        try:
            r = self.shell(target, 'pm', 'list', 'packages', '--user', '0', pkg, timeout=timeout)
            # ciktida 'package:<pkg>' yoksa user 0'da kurulu degil.
            for line in (r.output or '').splitlines():
                if line.strip() == 'package:' + pkg:
                    return False
            return True
        except AdbError:
            return False

    def is_disabled(self, target, pkg, timeout=10):
        """Paket devre disi mi? (pm list packages -d kontrolu)."""
        if not is_valid_package(str(pkg).strip()):
            return False
        try:
            r = self.shell(target, 'pm', 'list', 'packages', '-d', timeout=timeout)
            for line in (r.output or '').splitlines():
                if line.strip() == 'package:' + pkg:
                    return True
            return False
        except AdbError:
            return False

    def pm_path(self, target, pkg):
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        r = self.shell(target, 'pm', 'path', pkg)
        m = re.search(r'package:(.+)', r.output)
        return m.group(1).strip() if m else None

    def pm_paths(self, target, pkg):
        """Split APK dahil TUM dex/yollar (base.apk + split_*.apk)."""
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        r = self.shell(target, 'pm', 'path', pkg)
        paths = []
        for line in r.output.splitlines():
            line = line.strip()
            if line.startswith('package:'):
                p = line[len('package:'):].strip()
                if p and p not in paths:
                    paths.append(p)
        return paths

    def app_detail(self, target, pkg, timeout=20):
        """dumpsys package'tan surum/kurulum/izin ozeti cikarir."""
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        r = self.shell(target, 'dumpsys', 'package', pkg, timeout=timeout)
        out = r.output or ''
        if 'Unable to find package' in out or 'No such package' in out or not out.strip():
            raise AdbError('{} için paket bilgisi bulunamadı.'.format(pkg))

        def grab(pat, default='?'):
            m = re.search(pat, out, re.M)
            return m.group(1).strip() if m else default

        detail = {
            'package': pkg,
            'versionName': grab(r'versionName=([^\s]+)'),
            'versionCode': grab(r'versionCode=(\d+)'),
            'installer': grab(r'installerPackageName=([^\s]+)', 'bilinmiyor'),
            'firstInstall': grab(r'firstInstallTime=([^\n\r]+)'),
            'lastUpdate': grab(r'lastUpdateTime=([^\n\r]+)'),
            'codePath': grab(r'codePath=([^\n\r]+)'),
            'dataDir': grab(r'dataDir=([^\n\r]+)'),
            'enabled': not bool(re.search(r'enabled\s*=\s*false|enabledState\s*=\s*DISABLED', out, re.I)),
        }
        # runtime izin sayisi (kaba sayim)
        perms = re.findall(r'runtime permissions:', out, re.I)
        detail['perm_blocks'] = len(perms)
        m2 = re.search(r'USER 0:.*?granted=(\w+)', out, re.S)
        detail['granted_hint'] = m2.group(1) if m2 else '?'
        # raw kisaltma (dialogda gostermek icin)
        detail['raw_head'] = '\n'.join(out.splitlines()[:60])
        return detail

    def app_size(self, target, pkg, timeout=20):
        """Paket veri boyutunu du ile olcer (KB). Basarisizsa None."""
        try:
            d = self.app_detail(target, pkg, timeout=timeout)
            data_dir = d.get('dataDir') or ('/data/data/' + pkg)
        except AdbError:
            data_dir = '/data/data/' + pkg
        try:
            r = self.shell(target, 'du', '-sk', data_dir, timeout=timeout)
            m = re.search(r'(\d+)', r.output)
            if m:
                return int(m.group(1))
        except AdbError:
            pass
        return None

    def pull(self, target, remote, local, timeout=300):
        remote = safe_remote_path(remote)
        r = self.run(['-s', target, 'pull', remote, local], timeout=timeout)
        if r.exit_code != 0:
            raise AdbError('Indirilemedi ({}): {}'.format(
                remote, (r.output + ' ' + r.error).strip() or 'bilinmeyen hata'))
        return r

    def push(self, target, local, remote, timeout=300):
        """Yerel dosyayi cihaza yukler. Basarisizsa AdbError atar."""
        remote = safe_remote_path(remote)
        r = self.run(['-s', target, 'push', local, remote], timeout=timeout)
        text = '{} {}'.format(r.output, r.error)
        if r.exit_code != 0 or re.search(r'failed|error|no such|denied', text, re.I):
            raise AdbError('Yüklenemedi ({} -> {}): {}'.format(
                local.rsplit('\\', 1)[-1].rsplit('/', 1)[-1],
                remote, text.strip() or 'bilinmeyen hata'))
        return r

    # ------------------------------------------------------------------
    # Kumanda
    # ------------------------------------------------------------------
    def keyevent(self, target, code):
        try:
            code = int(code)
        except (TypeError, ValueError):
            raise AdbError('Geçersiz keyevent kodu: {!r}'.format(code))
        if not 0 <= code <= 300:
            raise AdbError('Geçersiz keyevent kodu: {}'.format(code))
        return self.shell(target, 'input', 'keyevent', str(code), timeout=10)

    def input_text(self, target, text):
        safe = sanitize_input_text(text)
        if not safe:
            raise AdbError('Gonderilecek geçerli karakter yok (özel semboller atildi).')
        return self.shell(target, 'input', 'text', safe, timeout=10)

    def launch(self, target, pkg):
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        r = self.shell(target, 'monkey', '-p', pkg, '-c', 'android.intent.category.LAUNCHER', '1', timeout=15)
        if 'No activities found' in r.output:
            raise AdbError('{} için launcher aktivitesi bulunamadı.'.format(pkg))
        return r

    def launch_resolved(self, target, pkg, timeout=15):
        """Once resolve-activity dener, olmazsa monkey fallback."""
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        try:
            r = self.shell(target, 'cmd', 'package', 'resolve-activity',
                           '--brief', '-c', 'android.intent.category.LAUNCHER', pkg,
                           timeout=timeout)
            # basarili cozumde paket adi ciktida gecer
            if pkg in (r.output or ''):
                r2 = self.shell(target, 'am', 'start', '-n', r.output.splitlines()[-1].strip(),
                                timeout=timeout)
                if 'Error' not in (r2.output or '') and 'Exception' not in (r2.output or ''):
                    return r2
        except AdbError:
            pass
        return self.launch(target, pkg)

    # ------------------------------------------------------------------
    # Donanim / sistem
    # ------------------------------------------------------------------
    def screenshot(self, target, timeout=30):
        """Ekran goruntusu (PNG bytes).

        Yontem: once dosya-yoluyla (screencap + pull) denenir; bu yol
        her zaman temiz PNG indirir (Windows text-mode stdout
        bozulmasindan etkilenmez). Basarisiz olursa exec-out denenir
        (onarim + dogrulama ile).
        """
        try:
            data = self.screenshot_via_file(target, timeout=timeout)
            if png_is_valid(data):
                return data
        except AdbError:
            pass
        try:
            r = self.run(['-s', target, 'exec-out', 'screencap', '-p'],
                         timeout=timeout, binary=True)
            fixed = _repair_png(r.output)
            if fixed and png_is_valid(fixed):
                return fixed
        except AdbError:
            pass
        raise AdbError('Ekran goruntusu alinamadi (PNG dogrulanamadi).')

    def screenshot_via_file(self, target, timeout=60):
        """screencap'i cihazdaki dosyaya yazip pull ile indirir (guvenilir)."""
        import tempfile
        remote = '/sdcard/mibox_scr_{}.png'.format(os.getpid())
        try:
            r = self.shell(target, 'screencap', '-p', remote, timeout=timeout)
            if r.exit_code != 0:
                raise AdbError('screencap başarısız: {} {}'.format(r.output, r.error))
            tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            tmp.close()
            try:
                pr = self.pull(target, remote, tmp.name, timeout=timeout)
                if pr.exit_code != 0:
                    raise AdbError('Ekran dosyası indirilemedi: {} {}'.format(pr.output, pr.error))
                with open(tmp.name, 'rb') as f:
                    data = f.read()
                if not data or data[1:4] != b'PNG':
                    raise AdbError('Ekran dosyası bozuk indi.')
                return data
            finally:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass
        finally:
            try:
                self.shell(target, 'rm', remote, timeout=10)
            except AdbError:
                pass

    def screenshot_hd(self, target, timeout=45):
        """Hidpi/dahili ekran goruntusu (kilitli-kenar modunda genis ekran)."""
        try:
            r = self.run(['-s', target, 'exec-out', 'screencap', '-d', 'internal_display', '-p'],
                         timeout=timeout, binary=True)
            fixed = _repair_png(r.output)
            if fixed:
                return fixed
        except AdbError:
            pass
        return self.screenshot(target, timeout=timeout)

    def reboot(self, target):
        return self.run(['-s', target, 'reboot'], timeout=15)

    def reboot_recovery(self, target):
        return self.run(['-s', target, 'reboot', 'recovery'], timeout=15)

    def reboot_bootloader(self, target):
        return self.run(['-s', target, 'reboot', 'bootloader'], timeout=15)

    def sleep(self, target):
        return self.keyevent(target, 223)

    def wakeup(self, target):
        return self.keyevent(target, 224)

    def trim_caches(self, target):
        return self.shell(target, 'pm', 'trim-caches', '999G', timeout=30)

    def logcat_clear(self, target, timeout=15):
        self.shell(target, 'logcat', '-c', timeout=timeout)

    def logcat_dump(self, target, lines=200, level=None, tag=None, timeout=30):
        """Son N satır logcat. level: V/D/I/W/E/F, tag: etiket filtresi."""
        n = clamp_lines(lines, default=200)
        args = ['logcat', '-d', '-v', 'brief']
        if level:
            lv = str(level).strip().upper()
            if lv not in LOGCAT_LEVELS:
                raise AdbError('Geçersiz log seviyesi: {!r}'.format(level))
            args += ['*:{}'.format(lv)]
        if tag:
            tg = str(tag).strip()
            if not is_valid_tag(tg):
                raise AdbError('Geçersiz log etiketi: {!r}'.format(tag))
            args += [tg]
        args += ['-t', str(n)]
        r = self.shell(target, *args, timeout=timeout)
        return r.output or ''

    def logcat_crash(self, target, lines=120, timeout=30):
        """Son çökme izleri (AndroidRuntime + FATAL)."""
        args = ['logcat', '-d', '-v', 'brief', '-t', str(clamp_lines(lines, default=120)),
                'AndroidRuntime:E', '*:F', '*:S']
        try:
            r = self.shell(target, *args, timeout=timeout)
            return r.output or ''
        except AdbError:
            return ''

    def file_list(self, target, path, timeout=20):
        """ls -la ayristir: [{'name','size','dir','perm','mtime'}].

        Toybox (Mi Box) '--time-style' desteklemez; once sade 'ls -la'
        denenir, tarih bicimi her iki varyanta da uyar (ISO veya
        'Mon DD HH:MM').

        Not: '/sdcard' tek basina sembolik bagi dondurur; icerik icin
        yolun sonuna '/' eklenir.
        """
        p = safe_remote_path(path)
        if not p.endswith('/'):
            p += '/'
        r = self.shell(target, 'ls', '-la', p, timeout=timeout)
        out = []
        for line in (r.output or '').splitlines():
            line = line.strip()
            if not line or line.startswith('total'):
                continue
            parts = line.split()
            # toybox: perm links owner group size date time name (8+)
            # ISO:    perm links owner group size YYYY-MM-DD HH:MM name (8+)
            if len(parts) < 7:
                continue
            perm = parts[0]
            if len(perm) < 10 or perm[0] not in 'd-lcbps':
                continue
            try:
                size = int(parts[4])
            except ValueError:
                continue
            # boyut-detay farki: [perm, link, owner, group, size, ...tarih, ad]
            # ad, sondan bulunur: tarih parcaciklarini atla
            rest = parts[5:]
            name_parts = list(rest)
            # ISO 'YYYY-MM-DD HH:MM' veya 'Mon DD HH:MM/YYYY' kalibini sok
            if len(name_parts) >= 2 and (
                    '-' in name_parts[0] or name_parts[0] in (
                        'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul',
                        'Aug', 'Sep', 'Oct', 'Nov', 'Dec')):
                name_parts = name_parts[2:] if len(name_parts) > 2 else []
            name = ' '.join(name_parts).strip()
            if not name or name in ('.', '..'):
                continue
            mtime = ' '.join(parts[5:7])
            out.append({'name': name, 'size': size, 'dir': perm.startswith('d'),
                        'perm': perm, 'mtime': mtime})
        out.sort(key=lambda e: (not e['dir'], e['name'].lower()))
        return out

    def file_remove(self, target, path, timeout=20):
        path = safe_remote_path(path)
        if path in ('/', '/sdcard', '/data', '/system', '/vendor', '/storage'):
            raise AdbError('Kok dizinler silinemez: {}'.format(path))
        r = self.shell(target, 'rm', '-rf', path, timeout=timeout)
        if r.exit_code != 0:
            raise AdbError('Silinemedi ({}): {}'.format(path, (r.output + r.error).strip()))

    def file_mkdir(self, target, path, timeout=15):
        self.shell(target, 'mkdir', '-p', safe_remote_path(path), timeout=timeout)

    # ------------------------------------------------------------------
    # APK kurulum + HOME launcher + hizlandirma (v8: AppControl/tvboxtools)
    # ------------------------------------------------------------------
    def install_apk(self, target, local_path, reinstall=True, timeout=120):
        """Tek APK kur. Donus: AdbResult (Success kontrolu yapilir)."""
        import os as _os
        lp = str(local_path or '').strip()
        if not lp.lower().endswith('.apk'):
            raise AdbError('Geçersiz APK yolu (uzanti .apk olmali): {!r}'.format(local_path))
        if '\n' in lp or '\r' in lp or '\x00' in lp:
            raise AdbError('Geçersiz APK yolu: {!r}'.format(local_path))
        if not _os.path.isfile(lp):
            raise AdbError('APK bulunamadı: {}'.format(lp))
        args = ['install']
        if reinstall:
            args.append('-r')
        args.append(lp)
        r = self.run(['-s', target] + args, timeout=timeout)
        text = '{} {}'.format(r.output, r.error)
        if r.exit_code != 0 or not re.search(r'\bSuccess\b', text):
            raise AdbError('Kurulum başarısız ({}): {}'.format(
                local_path.rsplit('\\', 1)[-1].rsplit('/', 1)[-1],
                text.strip() or 'bilinmeyen hata'))
        return r

    def install_multiple(self, target, apk_path, timeout=180):
        """Split-APK toplu kurulum (adb install-multiple).

        apk_path tek tek dosya listesi, dizin (icindeki *.apk'lar) veya
        tek dosya olabilir. Base + split'ler tek oturumda kurulur
        (AppControl 'install APKS' davranisi).
        """
        import glob as _glob
        import os as _os
        if isinstance(apk_path, (list, tuple)):
            files = [str(f or '').strip() for f in list(apk_path)]
        elif isinstance(apk_path, str) and _os.path.isdir(apk_path):
            files = sorted(_glob.glob(_os.path.join(apk_path, '*.apk')))
        else:
            files = [str(apk_path or '').strip()]
        clean = []
        for f in files:
            if not f or '\n' in f or '\r' in f or '\x00' in f:
                continue
            if not f.lower().endswith('.apk'):
                continue
            if not _os.path.isfile(f):
                continue
            if f not in clean:
                clean.append(f)
        files = clean
        if not files:
            raise AdbError('Kurulacak APK bulunamadı: ' + str(apk_path))
        args = ['install-multiple', '-r'] + files
        r = self.run(['-s', target] + args, timeout=timeout)
        text = '{} {}'.format(r.output, r.error)
        if r.exit_code != 0 or not re.search(r'\bSuccess\b', text):
            raise AdbError('Toplu kurulum başarısız: {}'.format(text.strip()[:300]))
        return r

    # Geriye uyumluluk: eski cagrilar calismaya devam eder.
    def install_apks(self, target, apk_files, timeout=600):
        """DEPRECATED: install_multiple(liste) kullanin."""
        return self.install_multiple(target, apk_files, timeout=timeout)

    def home_activity(self, target, timeout=15):
        """Mevcut HOME aktivitesi (cmd package get-home-activity esdegeri)."""
        try:
            r = self.shell(target, 'cmd', 'package', 'resolve-activity',
                           '--brief', '-a', 'android.intent.action.MAIN',
                           '-c', 'android.intent.category.HOME', timeout=timeout)
            for line in (r.output or '').splitlines():
                line = line.strip()
                if '/' in line and '.' in line.split('/')[0]:
                    return line
        except AdbError:
            pass
        return '?'

    def set_home_activity(self, target, component, timeout=20, fix_setup=True):
        """HOME uygulamasini kalici ayarla (tvboxtools yontemi, reboot dayanir).

        component: 'paket/.Aktivite' biciminde. Dogrulama: geri okuma.

        Google TV / Android TV'de kurulum sihirbazi (setupwraith vb.) cihaz
        'kurulmadi' sayildigi surece HOME'u kilitler: komut basarili gorunur,
        resolve-activity hala sihirbazi dondurur. fix_setup=True iken bu engel
        otomatik cozulur:
          1) device_provisioned + user_setup_complete = 1
          2) HOME'u tutan sihirbaz paketi user 0 icin devre disi birakilir
          3) set-home-activity tekrarlanir ve yeniden dogrulanir
        Yapilan ek adimlar self.last_home_notes listesine yazilir (UI gosterir).
        """
        self.last_home_notes = []
        comp = str(component or '').strip()
        if not is_valid_home_component(comp):
            raise AdbError('Geçersiz HOME bileseni: {!r}'.format(component))
        want = comp.split('/')[0]
        r = self.shell(target, 'cmd', 'package', 'set-home-activity', comp,
                       timeout=timeout)
        text = '{} {}'.format(r.output, r.error)
        if r.exit_code != 0:
            raise AdbError('HOME ayarlanamadi: {}'.format(text.strip() or 'bilinmeyen hata'))
        cur = self.home_activity(target)
        if want in cur:
            return r
        blocker = home_pkg_of(cur)
        if not fix_setup or not is_setup_wizard_pkg(blocker):
            raise AdbError('Doğrulama başarısız: HOME hala {}'.format(cur))
        # --- Kurulum sihirbazi engeli: coz ve tekrar dene ---
        written = self.mark_device_provisioned(target)
        if written:
            self.last_home_notes.append(
                'Cihaz kurulmus isaretlendi: ' + ', '.join(written))
        try:
            self.disable_setup_blocker(target, blocker, timeout=timeout)
            self.last_home_notes.append(
                'Kurulum sihirbazi devre dışı bırakıldı: ' + blocker)
        except AdbError as e:
            self.last_home_notes.append(str(e))
        r2 = self.shell(target, 'cmd', 'package', 'set-home-activity', comp,
                        timeout=timeout)
        cur2 = self.home_activity(target)
        if want in cur2:
            self.last_home_notes.append('HOME dogrulandi: ' + cur2)
            return r2
        raise AdbError(
            'HOME hala {} — kurulum sihirbazi ({}). Sihirbaz devre dışı bırakıldı; '
            'cihazi yeniden baslatip tekrar deneyin.'.format(cur2, blocker or '?'))

    def mark_device_provisioned(self, target, timeout=15):
        """Cihazi 'kurulmus' isaretle (kurulum sihirbazi HOME'u kilitlemesin).

        Android TV'de device_provisioned=0 / user_setup_complete=0 iken
        setupwraith HOME olarak zorlanir; set-home-activity kalici olmaz.
        Donus: yazilabilen anahtarlarin listesi (bilgi amacli).
        """
        done = []
        for ns, key in (('global', 'device_provisioned'),
                        ('secure', 'user_setup_complete')):
            try:
                r = self.shell(target, 'settings', 'put', ns, key, '1',
                               timeout=timeout)
                if r.exit_code == 0:
                    done.append('{}.{}'.format(ns, key))
            except AdbError:
                continue
        return done

    def disable_setup_blocker(self, target, pkg, timeout=20):
        """HOME'u tutan kurulum sihirbazini user 0 icin devre disi birak.

        clear_data YAPILMAZ (sihirbaz verisi silinmez): yalnizca force-stop +
        'pm disable-user --user 0'. Paket adi kurulum sihirbazi kaliplarina
        uymuyorsa AdbError atilir (yanlislikla baska paket kapatilmasin).
        """
        pkg = str(pkg or '').strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        if not is_setup_wizard_pkg(pkg):
            raise AdbError('Kurulum sihirbazi degil, devre dışı birakilmadi: {}'.format(pkg))
        try:
            self.force_stop(target, pkg)
        except AdbError:
            pass
        r = self.shell(target, 'pm', 'disable-user', '--user', '0', pkg,
                       timeout=timeout)
        text = '{} {}'.format(r.output, r.error)
        if r.exit_code != 0 or re.search(r'failed|not allowed|cannot|no such|unknown',
                                         text, re.I):
            raise AdbError('Kurulum sihirbazi devre dışı birakilamadi ({}): {}'.format(
                pkg, text.strip() or 'bilinmeyen hata'))
        return r

    def launcher_apps(self, target, timeout=30):
        """HOME kategorisinde launcher olabilecek uygulamalar."""
        try:
            r = self.shell(target, 'cmd', 'package', 'query-activities',
                           '--brief', '-a', 'android.intent.action.MAIN',
                           '-c', 'android.intent.category.HOME', timeout=timeout)
            out = []
            for line in (r.output or '').splitlines():
                line = line.strip()
                if '/' in line and '.' in line.split('/')[0]:
                    out.append(line)
            return out
        except AdbError:
            return []

    def animator_scales(self, target, timeout=15):
        """Mevcut animasyon olcekleri (hizlandirma paneli icin)."""
        out = {}
        for key in ('window_animation_scale', 'transition_animation_scale',
                    'animator_duration_scale'):
            try:
                r = self.shell(target, 'settings', 'get', 'global', key, timeout=timeout)
                out[key] = (r.output or '').strip() or '1'
            except AdbError:
                out[key] = '?'
        return out

    def set_animator_scales(self, target, value, timeout=15):
        """0=hizli (kapali), 0.5=yari, 1=normal. tvboxtools 'speed up' esdegeri."""
        val = str(value or '').strip()
        if val not in ANIM_SCALES:
            raise AdbError('Geçersiz animasyon olcegi: {!r}'.format(value))
        if val == '1.0':
            val = '1'
        for key in ('window_animation_scale', 'transition_animation_scale',
                    'animator_duration_scale'):
            self.shell(target, 'settings', 'put', 'global', key, val,
                       timeout=timeout)
        # dogrula
        cur = self.animator_scales(target)
        bad = [k for k, v in cur.items() if v != val]
        if bad:
            raise AdbError('Doğrulama başarısız: {}'.format(', '.join(bad)))

    def storage_top(self, target, limit=15, timeout=60):
        """En çok yer kaplayan dizinler (GB eşiği üstü du taraması)."""
        out = []
        for base in ('/sdcard', '/data/media/0'):
            try:
                r = self.shell(target, 'du', '-sk', base + '/*', timeout=timeout)
            except AdbError:
                continue
            for line in (r.output or '').splitlines():
                m = re.match(r'\s*(\d+)\s+(.+)', line)
                if m:
                    out.append({'path': m.group(2).strip(), 'kb': int(m.group(1))})
        out.sort(key=lambda e: e['kb'], reverse=True)
        return out[:limit]

    def list_users(self, target, timeout=15):
        """Cihazdaki kullanıcılar: [{'id': int, 'name': str, 'running': bool}]."""
        try:
            r = self.shell(target, 'pm', 'list', 'users', timeout=timeout)
        except AdbError:
            return [{'id': 0, 'name': 'Owner', 'running': True}]
        out = []
        for line in (r.output or '').splitlines():
            m = re.match(r'\s*UserInfo\{(\d+):([^:}]+)', line)
            if m:
                uid = int(m.group(1))
                name = m.group(2).strip()
                running = 'running' in line
                out.append({'id': uid, 'name': name, 'running': running})
        return out or [{'id': 0, 'name': 'Owner', 'running': True}]

    def uninstall_user_id(self, target, pkg, user_id):
        """Belirli kullanıcı için kaldırma (multi-user, UAD davranışı)."""
        pkg = str(pkg or '').strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        uid = check_user_id(user_id)
        if self.is_uninstalled_for_user_id(target, pkg, uid):
            return None
        try:
            self.force_stop(target, pkg)
        except AdbError:
            pass
        r = self.shell(target, 'pm', 'uninstall', '--user', str(uid), pkg)
        text = '{} {}'.format(r.output, r.error)
        if re.search(r'\bSuccess\b', text):
            return r
        if self.is_uninstalled_for_user_id(target, pkg, user_id):
            return r
        raise AdbError('Kaldırılamadı ({} user {}): {}'.format(
            pkg, user_id, text.strip() or 'bilinmeyen hata'))

    def is_uninstalled_for_user_id(self, target, pkg, user_id, timeout=10):
        pkg = str(pkg or '').strip()
        if not is_valid_package(pkg):
            return False
        try:
            uid = check_user_id(user_id)
        except AdbError:
            return False
        try:
            r = self.shell(target, 'pm', 'list', 'packages', '--user', str(uid),
                           pkg, timeout=timeout)
            for line in (r.output or '').splitlines():
                if line.strip() == 'package:' + pkg:
                    return False
            return True
        except AdbError:
            return False

    def autorun_receivers(self, target, timeout=40):
        """BOOT_COMPLETED dinleyen paketler: {pkg: [component, ...]}.

        Yöntem: 'cmd package query-receivers' önce denenir (hızlı),
        desteklenmiyorsa dumpsys package çıktısı taranır (yavaş ama evrensel).
        """
        found = {}
        try:
            r = self.shell(target, 'cmd', 'package', 'query-receivers',
                           '--brief', 'android.intent.action.BOOT_COMPLETED',
                           timeout=timeout)
            for line in (r.output or '').splitlines():
                line = line.strip()
                if '/' in line and not line.startswith(('package:', 'all ')):
                    pkg = line.split('/')[0]
                    if '.' in pkg:
                        found.setdefault(pkg, []).append(line)
            if found:
                return found
        except AdbError:
            pass
        try:
            r = self.shell(target, 'dumpsys', 'package', 'receivers', timeout=timeout)
            cur_pkg = None
            has_boot = False
            for line in (r.output or '').splitlines():
                s = line.strip()
                m = re.match(r'^([a-zA-Z][\w\.]+)/([\.\w]+)', s)
                if m and '/' in s and ' ' not in s.split('/')[0]:
                    if cur_pkg and has_boot:
                        found.setdefault(cur_pkg, [])
                    cur_pkg = m.group(1)
                    has_boot = False
                    continue
                if 'BOOT_COMPLETED' in s and cur_pkg:
                    has_boot = True
            if cur_pkg and has_boot:
                found.setdefault(cur_pkg, [])
        except AdbError:
            pass
        return found

    def app_permissions(self, target, pkg, timeout=20):
        """dumpsys package'tan istenen izinler + çalışma durumu."""
        r = self.shell(target, 'dumpsys', 'package', pkg, timeout=timeout)
        out = (r.output or '')
        granted, perms = [], []
        in_perms = False
        for line in out.splitlines():
            s = line.strip()
            if 'install permissions:' in s or 'runtime permissions:' in s:
                in_perms = True
                continue
            if in_perms:
                if not s or ':' in s and not s.startswith('android.permission'):
                    if s and not s.startswith('android.permission'):
                        in_perms = False
                        continue
                m = re.match(r'(android\.permission\.[A-Z_]+):\s*granted=(true|false)', s)
                if m:
                    is_granted = (m.group(2) == 'true')
                    perms.append({'perm': m.group(1), 'granted': is_granted})
                    if is_granted:
                        granted.append(m.group(1))
        return {'all': perms, 'granted': granted}

    def health(self, target, timeout=30):
        """Cihaz sağlık özeti: depolama + RAM + paket sayıları.

        Dönüş: {'disk_total_kb','disk_avail_kb','disk_pct',
                'mem_total_kb','mem_avail_kb','mem_pct',
                'pkg_total','pkg_disabled','pkg_removed_u0'}
        """
        out = {}
        try:
            df = self.shell(target, 'df', '/data', timeout=timeout).output
            # ör: /dev/block/...  12345678  2345678  9999999  19% /data
            line = [l for l in df.splitlines() if '/data' in l]
            line = line[-1] if line else ''
            parts = line.split()
            if len(parts) >= 5:
                out['disk_total_kb'] = int(parts[1])
                out['disk_avail_kb'] = int(parts[3])
                pct = parts[4].rstrip('%')
                out['disk_pct'] = int(pct) if pct.isdigit() else 0
        except (AdbError, ValueError, IndexError):
            pass
        try:
            mem = self.shell(target, 'cat', '/proc/meminfo', timeout=timeout).output
            mt = re.search(r'MemTotal:\s+(\d+)', mem)
            ma = re.search(r'MemAvailable:\s+(\d+)', mem)
            if mt:
                out['mem_total_kb'] = int(mt.group(1))
            if mt and ma:
                total = int(mt.group(1))
                avail = int(ma.group(1))
                out['mem_avail_kb'] = avail
                out['mem_pct'] = int((total - avail) * 100 / total) if total else 0
        except (AdbError, ValueError):
            pass
        try:
            det = self.list_packages_detailed(target, True)
            out['pkg_total'] = len(det)
            out['pkg_disabled'] = sum(1 for e in det if not e.get('enabled', True))
            out['pkg_removed_u0'] = sum(1 for e in det if not e.get('installed_user0', True))
        except AdbError:
            pass
        return out

    def device_info(self, target):
        info = {}
        props = (
            'ro.product.model', 'ro.product.brand', 'ro.product.name',
            'ro.build.version.release', 'ro.build.version.sdk',
            'ro.build.display.id', 'ro.build.fingerprint', 'ro.product.device',
        )
        for prop in props:
            try:
                info[prop] = self.getprop(target, prop)
            except AdbError:
                info[prop] = ''
        try:
            mem = self.shell(target, 'cat', '/proc/meminfo').output
            m = re.search(r'MemTotal:\s+(\d+)', mem)
            info['mem_total_kb'] = m.group(1) if m else '?'
        except AdbError:
            info['mem_total_kb'] = '?'
        return info

    def device_info_full(self, target, timeout=30):
        """Genis cihaz bilgisi: depolama, pil, wifi, uptime, ekran."""
        info = self.device_info(target)
        try:
            df = self.shell(target, 'df', '/data', timeout=timeout).output
            # son satirdaki kullanim % ve bos alan
            lines = [l for l in df.splitlines() if '/data' in l]
            info['disk_data'] = lines[-1].strip() if lines else df.strip().splitlines()[-1]
        except AdbError:
            info['disk_data'] = '?'
        try:
            batt = self.shell(target, 'dumpsys', 'battery', timeout=timeout).output
            m = re.search(r'level:\s*(\d+)', batt)
            info['battery'] = m.group(1) + '%' if m else '?'
            m2 = re.search(r'status:\s*(\d+)', batt)
            info['battery_status'] = m2.group(1) if m2 else '?'
        except AdbError:
            info['battery'] = '?'
        try:
            up = self.shell(target, 'uptime', timeout=timeout).output
            info['uptime'] = up.strip().splitlines()[0] if up.strip() else '?'
        except AdbError:
            info['uptime'] = '?'
        try:
            wm = self.shell(target, 'dumpsys', 'wifi', timeout=timeout).output
            m = re.search(r'mWifiInfo\s+SSID:\s*"([^"]+)"', wm)
            if not m:
                m = re.search(r'SSID:\s*"([^"]+)"', wm)
            info['wifi_ssid'] = m.group(1) if m else '?'
            m2 = re.search(r'ip\s*[:=]\s*([\d\.]+)', wm, re.I)
            if not m2:
                try:
                    ip = self.shell(target, 'ip', 'route', timeout=timeout).output
                    m3 = re.search(r'src\s+([\d\.]+)', ip)
                    info['wifi_ip'] = m3.group(1) if m3 else '?'
                except AdbError:
                    info['wifi_ip'] = '?'
            else:
                info['wifi_ip'] = m2.group(1)
        except AdbError:
            info['wifi_ssid'] = '?'
            info['wifi_ip'] = '?'
        try:
            wm2 = self.shell(target, 'wm', 'size', timeout=timeout).output
            info['screen'] = wm2.strip().splitlines()[0] if wm2.strip() else '?'
        except AdbError:
            info['screen'] = '?'
        return info
