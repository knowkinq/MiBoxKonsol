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
import posixpath
import re
import shlex
import signal
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from urllib.parse import urlsplit
from types import SimpleNamespace

CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

_LOG_URL = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s'\"<>]+|magnet:[^\s'\"<>]+")
_LOG_ABS_PATH = re.compile(
    r'(?i)(?:[a-z]:[\\/][^\r\n"<>|]+|\\\\[^\r\n"<>|]+'
    r'|/[^\r\n]+)')
_LOG_QUOTED_PATH = re.compile(
    r'''(?i)(["'])(?=[^"'\r\n]*[\\/])[^"'\r\n]*\1''')
_LOG_IPV4 = re.compile(
    r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?![\w.])')


def sanitize_log_text(value, private_values=()):
    """Redact known secrets, URLs, local paths, and IPv4 endpoints from logs."""
    text = str(value or '')
    for private in sorted(set(str(item) for item in private_values if item),
                          key=len, reverse=True):
        pattern = r'(?<![\w]){}(?![\w])'.format(re.escape(private))
        text = re.sub(pattern, '******', text, flags=re.IGNORECASE)
    text = _LOG_QUOTED_PATH.sub('"******"', text)
    text = _LOG_URL.sub('******', text)
    text = _LOG_ABS_PATH.sub('******', text)
    return _LOG_IPV4.sub('******', text)


def target_private_values(target):
    """Return a network target and its host portion for log redaction."""
    value = str(target or '').strip()
    if not value:
        return []
    values = [value]
    if value.startswith('[') and ']' in value:
        host = value[1:value.find(']')]
    elif ':' in value:
        host, _, port = value.rpartition(':')
        if not port.isdigit():
            host = ''
    else:
        host = ''
    if host and host not in values:
        values.append(host)
    return values

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
    if png_is_valid(data):
        return data
    # Windows text-mode stdout her LF'den once CR ekleyebilir: orijinal
    # CRLF -> CR CR LF olur. Cift-CR'yi tekle; imza VE IEND kuyrugu
    # saglamsa kabul et (govdedeki yalniz-LF bozulmasi kurtarilamaz,
    # bu durumda None doner ve dosya-yolu yonteme dusulur).
    fixed = data.replace(b'\r\r\n', b'\r\n')
    if png_is_valid(fixed):
        return fixed
    return None


def png_is_valid(data):
    """PNG chunk yapisini ve CRC'lerini dogrula; bozuk/yarim veriyi reddet."""
    if not data or len(data) < 45 or data[:8] != b'\x89PNG\r\n\x1a\n':
        return False
    import zlib

    offset = 8
    chunk_index = 0
    saw_idat = False
    ended_idat = False
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset:offset + 4], 'big')
        kind = data[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(data):
            return False
        payload = data[offset + 8:offset + 8 + length]
        crc = int.from_bytes(data[offset + 8 + length:end], 'big')
        if (zlib.crc32(kind + payload) & 0xffffffff) != crc:
            return False
        if chunk_index == 0:
            if kind != b'IHDR' or length != 13:
                return False
            width = int.from_bytes(payload[:4], 'big')
            height = int.from_bytes(payload[4:8], 'big')
            bit_depth, color_type = payload[8], payload[9]
            valid_depths = {
                0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8),
                4: (8, 16), 6: (8, 16),
            }
            if (not width or not height or bit_depth not in valid_depths.get(color_type, ())
                    or payload[10:12] != b'\x00\x00' or payload[12] not in (0, 1)):
                return False
        elif kind == b'IHDR':
            return False
        if kind == b'IDAT':
            if ended_idat:
                return False
            saw_idat = True
        elif saw_idat and kind != b'IEND':
            ended_idat = True
        if kind == b'IEND':
            if length != 0 or not saw_idat:
                return False
            tail = data[end:]
            if tail.strip(b'\r\n'):
                return False
            # Correct chunk CRCs alone do not guarantee a decodable pixel
            # stream. QImage is safe in workers and needs no QApplication.
            from PySide6.QtGui import QImage
            return not QImage.fromData(data, 'PNG').isNull()
        offset = end
        chunk_index += 1
    return False


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

# Kumanda tus kodlari (TEK KAYNAK: baglanti bekcisi + Kumanda sekmesi).
# Uyku modundaki Android TV'ye KEYCODE_WAKEUP gonderilerek ekran uyandirilir.
KEYCODE_POWER = 26
KEYCODE_SLEEP = 223
KEYCODE_WAKEUP = 224


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
    if isinstance(user_id, bool):
        raise AdbError('Geçersiz kullanıcı id: {!r}'.format(user_id))
    if isinstance(user_id, int):
        n = user_id
    elif isinstance(user_id, str):
        try:
            n = int(user_id.strip())
        except ValueError:
            raise AdbError('Geçersiz kullanıcı id: {!r}'.format(user_id))
    else:
        raise AdbError('Geçersiz kullanıcı id: {!r}'.format(user_id))
    if not 0 <= n <= 21474:
        raise AdbError('Geçersiz kullanıcı id: {!r}'.format(user_id))
    return n


def safe_remote_path(path):
    """Validate a device path without rewriting its filename characters.

    Shell callers must pass the result through _quoted_remote_path (or
    shlex.quote); pull/push pass it as an argv element directly.
    """
    p = str(path or '')
    if any(unicodedata.category(ch) == 'Cc' for ch in p):
        raise AdbError('Uzak yol kontrol karakteri içeremez.')
    if not p.startswith('/'):
        p = '/' + p
    parts = p.split('/')
    if '..' in parts:
        raise AdbError('Uzak yol üst dizine çıkamaz.')
    parts = [seg for seg in parts if seg not in ('', '.')]
    return '/' + '/'.join(parts) if parts else '/'


def _quoted_remote_path(path):
    """Return a validated path as one safely quoted Android shell word."""
    return shlex.quote(safe_remote_path(path))


class AdbError(Exception):
    """ADB isleminde basarisizlik."""


class PackageStateUnknownError(AdbError):
    """A package state could not be read reliably; callers must not escalate."""


class AdbResult:
    def __init__(self, exit_code, output, error):
        self.exit_code = exit_code
        self.output = output
        self.error = error

    @property
    def returncode(self):
        return self.exit_code

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
    Hassas hedefler, pair verileri, girilen metinler ve yerel yollar maskelenir.
    """

    # logda gosterilmeyecek/gizlenecek komutlar
    _MASK_ARGS = {'pair'}
    _URL_ARG = _LOG_URL
    _LOCAL_PATH_ARG = re.compile(
        r'(?i)^(?:[a-z]:[\\/]|\\\\|/(?:users|home|private|tmp)/|~[\\/])')
    def _safe_trace_args(self, args, hide_shell=False):
        """Return trace args with device targets, user text and local paths hidden."""
        shown = [str(a) for a in args]
        private_values = []

        def hide(index):
            if 0 <= index < len(shown) and shown[index] != '******':
                if shown[index]:
                    private_values.append(shown[index])
                shown[index] = '******'

        # ADB global options can precede the command. Do not record serials or
        # server hosts, which commonly contain a LAN address or device name.
        for i, value in enumerate(shown[:-1]):
            if value in ('-s', '-t', '-H'):
                endpoint = shown[i + 1]
                hide(i + 1)
                if value in ('-s', '-H'):
                    private_values.extend(target_private_values(endpoint))

        lowered = [value.lower() for value in shown]
        for i, value in enumerate(lowered):
            if value in self._MASK_ARGS:
                if i + 1 < len(shown):
                    private_values.extend(target_private_values(shown[i + 1]))
                for j in range(i + 1, len(shown)):
                    hide(j)
            elif value in ('connect', 'disconnect') and i + 1 < len(shown):
                private_values.extend(target_private_values(shown[i + 1]))
                hide(i + 1)
            elif value == 'shell' and (hide_shell or len(shown) == i + 2):
                # Interactive console commands may contain arbitrary values.
                for j in range(i + 1, len(shown)):
                    hide(j)
            elif value == 'text' and i > 0 and lowered[i - 1] == 'input':
                for j in range(i + 1, len(shown)):
                    hide(j)
            elif value in ('push', 'pull'):
                # Both ends can reveal a local account or private storage path.
                for j in range(i + 1, len(shown)):
                    if not shown[j].startswith('-'):
                        hide(j)
            elif value in ('install', 'install-multiple'):
                for j in range(i + 1, len(shown)):
                    if (shown[j].lower().endswith(('.apk', '.apks', '.aab'))
                            or self._LOCAL_PATH_ARG.match(shown[j])):
                        hide(j)

        for i, value in enumerate(shown):
            if value == '******':
                continue
            path_value = value.strip("'\"")
            if (self._URL_ARG.search(value)
                    or self._LOCAL_PATH_ARG.match(value)
                    or '/' in path_value or '\\' in path_value):
                hide(i)
        return shown, sorted(set(private_values), key=len, reverse=True)

    @staticmethod
    def _has_opaque_shell_command(args, hide_shell=False):
        if hide_shell:
            return True
        parts = [str(value).lower() for value in args]
        return any(value == 'shell' and len(parts) == index + 2
                   for index, value in enumerate(parts))

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

    def _trace(self, args, ok, ms, err='', probe=False, hide_shell=False):
        cb = getattr(self, 'trace_cb', None)
        if not cb:
            return
        try:
            shown, private_values = self._safe_trace_args(args, hide_shell)
            if self._has_opaque_shell_command(args, hide_shell) and (err or not ok):
                safe_err = 'ADB shell komutu başarısız; içerik gizlendi.'
            else:
                safe_err = sanitize_log_text(err, private_values)
            try:
                cb(shown, ok, ms, safe_err[:200], bool(probe))
            except TypeError:
                # eski imzali callback (4 arg) uyumlulugu
                cb(shown, ok, ms, safe_err[:200])
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
    def run(self, args, timeout=30, binary=False, quiet_first=False,
            preserve_output_whitespace=False, cancel_check=None,
            hide_shell_from_trace=False):
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
            if cancel_check is None:
                r = subprocess.run(cmd, capture_output=True, timeout=timeout, **kwargs)
            else:
                if cancel_check():
                    self._trace(args, False, 0, 'kullanıcı durdurdu',
                                hide_shell=hide_shell_from_trace)
                    raise AdbError('ADB işlemi kullanıcı tarafından durduruldu')
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
                deadline = _time.monotonic() + max(0.0, float(timeout))
                while True:
                    if cancel_check():
                        if proc.poll() is None:
                            try:
                                proc.terminate()
                            except OSError:
                                try:
                                    proc.kill()
                                except OSError:
                                    pass
                        try:
                            proc.communicate(timeout=2)
                        except subprocess.TimeoutExpired:
                            try:
                                proc.kill()
                            except OSError:
                                pass
                            proc.communicate()
                        self._trace(args, False,
                                    int((_time.time() - t0) * 1000),
                                    'kullanıcı durdurdu',
                                    hide_shell=hide_shell_from_trace)
                        raise AdbError('ADB işlemi kullanıcı tarafından durduruldu')
                    remaining = deadline - _time.monotonic()
                    if remaining <= 0:
                        if proc.poll() is None:
                            try:
                                proc.kill()
                            except OSError:
                                pass
                        proc.communicate()
                        raise subprocess.TimeoutExpired(cmd, timeout)
                    try:
                        stdout, stderr = proc.communicate(
                            timeout=min(0.2, remaining))
                        r = SimpleNamespace(returncode=proc.returncode,
                                            stdout=stdout, stderr=stderr)
                        break
                    except subprocess.TimeoutExpired:
                        continue
        except subprocess.TimeoutExpired:
            self._trace(args, False, int((_time.time() - t0) * 1000), 'zaman aşımı',
                        hide_shell=hide_shell_from_trace)
            shown, _ = self._safe_trace_args(args, hide_shell_from_trace)
            safe_args = ' '.join(str(a) for a in shown)
            raise AdbError('ADB zaman aşımı ({} sn): adb {}'.format(
                timeout, safe_args))
        except OSError as e:
            if self._has_opaque_shell_command(args, hide_shell_from_trace):
                safe_error = 'ADB shell komutu başlatılamadı; içerik gizlendi.'
            else:
                safe_error = sanitize_log_text(
                    str(e), self._safe_trace_args(args, hide_shell_from_trace)[1])
            self._trace(args, False, int((_time.time() - t0) * 1000), safe_error,
                        hide_shell=hide_shell_from_trace)
            raise AdbError('ADB calistirilamadi: {}'.format(safe_error))
        out, err = r.stdout, r.stderr
        if not binary:
            out = out.decode('utf-8', 'replace')
            out = out.rstrip('\r\n') if preserve_output_whitespace else out.strip()
            err = err.decode('utf-8', 'replace').strip()
        else:
            out, err = out or b'', (err or b'').decode('utf-8', 'replace').strip()
        ms = int((_time.time() - t0) * 1000)
        ok = (r.returncode == 0)
        private_values = self._safe_trace_args(args, hide_shell_from_trace)[1]
        opaque_shell = self._has_opaque_shell_command(args, hide_shell_from_trace)
        if not opaque_shell:
            err = sanitize_log_text(err, private_values)
        if not ok and not opaque_shell:
            if isinstance(out, str):
                out = sanitize_log_text(out, private_values)
        if quiet_first:
            # negatif sonuc: hata degil, sessiz probe
            self._trace(args, True, ms, '', probe=True,
                        hide_shell=hide_shell_from_trace)
        else:
            self._trace(args, ok, ms,
                        '' if ok else (err or out if isinstance(err, str) else ''),
                        hide_shell=hide_shell_from_trace)
        return AdbResult(r.returncode, out, err)

    # ------------------------------------------------------------------
    # Baglanti
    # ------------------------------------------------------------------
    def connect(self, target, timeout=10, deneme=1, bekleme=0.6, cancel_check=None):
        """Baglanti kurar; basarisizsa AdbError.

        deneme=1 (varsayilan): tek deneme — etkilesimli 'Baglan' hizli basarisiz
        olsun. Arka plan bekcisi deneme=2 verir: zaman asimi/ag hatasi gecici
        sayilir ve kisa bir beklemeden sonra bir kez daha denenir.
        """
        import time as _time
        target = str(target or '').strip()
        if not self._is_network_target(target):
            device = next((item for item in self.devices()
                           if item['id'] == target), None)
            if device is None:
                raise AdbError('Cihaz ADB listesinde bulunamadı: {}'.format(
                    sanitize_log_text(target, [target])))
            if device['state'] != 'device':
                raise AdbError('Cihaz hazır değil ({}): {}'.format(
                    device['state'], sanitize_log_text(target, [target])))
            state = self.run(['-s', target, 'get-state'], timeout=timeout, cancel_check=cancel_check)
            if state.exit_code != 0 or state.output != 'device':
                raise AdbError('Cihaz hazır değil: {} {}'.format(
                    state.output, state.error).strip())
            return target
        deneme = max(1, int(deneme or 1))
        son_hata = None
        for i in range(deneme):
            if cancel_check and cancel_check():
                raise AdbError('ADB işlemi kullanıcı tarafından durduruldu')
            try:
                r = self.run(['connect', target], timeout=timeout, cancel_check=cancel_check)
            except AdbError as e:
                if i + 1 < deneme and is_transient_connect_error(str(e)):
                    son_hata = e
                    _time.sleep(bekleme)
                    continue
                raise
            text = sanitize_log_text(
                '{} {}'.format(r.output, r.error), target_private_values(target))
            if r.exit_code != 0 or re.search(r'failed|refused|cannot|unreachable|unable|no route',
                                             text, re.I):
                hata = AdbError('Bağlantı başarısız: {} (Cihaz uyku modunda olabilir; '
                                'fiziksel kumandayla uyandin.)'.format(text.strip()))
                if i + 1 < deneme and is_transient_connect_error(text):
                    son_hata = hata
                    _time.sleep(bekleme)
                    continue
                raise hata
            st = self.run(['-s', target, 'get-state'], timeout=timeout, cancel_check=cancel_check)
            if st.output != 'device':
                state_error = sanitize_log_text(
                    '{} {}'.format(st.output, st.error), target_private_values(target))
                hata = AdbError('Cihaz hazır değil: {}'.format(state_error))
                if i + 1 < deneme and is_transient_connect_error(state_error):
                    son_hata = hata
                    _time.sleep(bekleme)
                    continue
                raise hata
            return target
        raise son_hata or AdbError('Bağlantı kurulamadı: {}'.format(
            sanitize_log_text(target, target_private_values(target))))

    @staticmethod
    def _is_network_target(target):
        """Recognize host:port endpoints while leaving USB/emulator serials alone."""
        target = str(target or '').strip()
        host, separator, port = target.rpartition(':')
        return bool(separator and host and port.isdigit()
                    and not any(ch.isspace() for ch in target))

    def disconnect(self, target):
        if not self._is_network_target(target):
            return

        try:
            result = self.run(['disconnect', target], timeout=10)
        except AdbError as exc:
            raise AdbError('ADB bağlantısı kesilemedi: {}'.format(
                sanitize_log_text(exc, target_private_values(target))))
        if result.exit_code != 0:
            detail = (result.error or result.output or '').strip()
            if not detail:
                detail = 'ADB komutu {} çıkış koduyla tamamlandı.'.format(
                    result.exit_code)
            raise AdbError('ADB bağlantısı kesilemedi: {}'.format(
                sanitize_log_text(detail, target_private_values(target))))

    def pair(self, host_port, code, timeout=15):
        """Android 11+ kablosuz eslestirme (adb pair host:port kod)."""
        import ipaddress

        if (not isinstance(host_port, str) or not host_port
                or host_port.startswith('-')
                or any(ch.isspace() or unicodedata.category(ch) == 'Cc'
                       for ch in host_port)):
            raise AdbError('Geçersiz eşleştirme adresi; host:port biçimini kullanın.')

        if host_port.startswith('['):
            closing = host_port.find(']')
            if closing < 0 or host_port[closing + 1:closing + 2] != ':':
                raise AdbError('Geçersiz eşleştirme adresi; host:port biçimini kullanın.')
            host = host_port[1:closing]
            port = host_port[closing + 2:]
            try:
                if '%' in host:
                    raise ValueError
                ipaddress.IPv6Address(host)
            except ValueError:
                raise AdbError('Geçersiz eşleştirme adresi; host:port biçimini kullanın.')
        else:
            host, separator, port = host_port.rpartition(':')
            if not separator or not host or ':' in host:
                raise AdbError('Geçersiz eşleştirme adresi; host:port biçimini kullanın.')
            try:
                ipaddress.IPv4Address(host)
            except ValueError:
                label = r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
                hostname = host[:-1] if host.endswith('.') else host
                if (not hostname or len(hostname) > 253
                        or re.fullmatch(r'[0-9]+(?:\.[0-9]+){3}', hostname)
                        or not re.fullmatch(r'{}(?:\.{})*'.format(label, label), hostname)):
                    raise AdbError('Geçersiz eşleştirme adresi; host:port biçimini kullanın.')

        if (not re.fullmatch(r'[0-9]{1,5}', port)
                or not 1 <= int(port) <= 65535):
            raise AdbError('Geçersiz eşleştirme portu; 1–65535 arasında olmalıdır.')
        if not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}', code):
            raise AdbError('Eşleştirme kodu 6 ASCII rakamından oluşmalıdır.')

        r = self.run(['pair', host_port, str(code)], timeout=timeout)
        text = '{} {}'.format(r.output, r.error)
        safe_text = text
        for endpoint_part in (host_port, host.strip('[]')):
            if endpoint_part:
                safe_text = re.sub(re.escape(endpoint_part), '******', safe_text,
                                   flags=re.IGNORECASE)
        safe_text = safe_text.replace(code, '******')
        succeeded = re.search(
            r'(?im)^[ \t]*Successfully paired to[ \t]+\S+', text)
        if (r.exit_code != 0 or not succeeded
                or re.search(r'failed|error|wrong|incorrect', safe_text, re.I)):
            raise AdbError('Eşleştirme başarısız: {}'.format(
                safe_text.strip() or 'ADB eşleştirmeyi doğrulamadı.'))
        return safe_text.strip()

    def devices(self):
        r = self.run(['devices', '-l'], timeout=15)
        if r.exit_code != 0:
            output = '{} {}'.format(r.output, r.error).strip()
            raise AdbError('ADB cihaz listesi alınamadı: {}'.format(
                output or 'bilinmeyen hata'))
        devs = []
        states = {'device', 'offline', 'unauthorized', 'bootloader',
                  'recovery', 'sideload', 'rescue'}
        for line in r.output.splitlines():
            line = line.strip()
            if not line or line.startswith('List of devices'):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            is_serial = bool(re.fullmatch(r'[A-Za-z0-9._:-]+', parts[0]))
            is_ipv6_endpoint = bool(re.fullmatch(
                r'\[[A-Za-z0-9:.%_-]+\]:\d{1,5}', parts[0]))
            if not (is_serial or is_ipv6_endpoint):
                continue
            state = parts[1]
            if state == 'no' and len(parts) > 2 and parts[2] == 'permissions':
                state = 'no permissions'
            if state in states or state == 'no permissions':
                devs.append({'id': parts[0], 'state': state, 'detail': line})
        return devs

    def get_state(self, target):
        return self.run(['-s', target, 'get-state'], timeout=10).output

    # ------------------------------------------------------------------
    # Shell
    # ------------------------------------------------------------------
    # Negatif-sonuc NORMAL olan yoklamalar: izde ERROR degil 'yoklama' sayilir.
    # pidof (calismiyor), pm path (yok), dumpsys kismi, get (bos deger).
    QUIET_FIRST = {'pidof', 'pm', 'dumpsys', 'getprop', 'settings'}

    def shell(self, target, *cmd, timeout=30, quiet=False,
              preserve_output_whitespace=False, hide_from_trace=False,
              cancel_check=None):
        options = {
            'timeout': timeout,
            'quiet_first': quiet and bool(cmd) and str(cmd[0]) in self.QUIET_FIRST,
        }
        if preserve_output_whitespace:
            options['preserve_output_whitespace'] = True
        if hide_from_trace:
            options['hide_shell_from_trace'] = True
        if cancel_check is not None:
            options['cancel_check'] = cancel_check
        return self.run(['-s', target, 'shell'] + list(cmd), **options)

    def getprop(self, target, prop):
        return self.shell(target, 'getprop', prop).output.strip()

    # ------------------------------------------------------------------
    # Uygulamalar
    # ------------------------------------------------------------------
    def list_packages(self, target, include_system=False):
        flag = '-a' if include_system else '-3'
        r = self.shell(target, 'pm', 'list', 'packages', flag)
        if r.exit_code != 0:
            raise AdbError('Paket listesi okunamadı: {}'.format(
                (r.error or r.output or 'pm list packages başarısız').strip()))
        packages = self._parse_package_list(r.output)
        if include_system and not packages:
            raise AdbError('Sistem paket listesi boş; sonuç doğrulanamadı.')
        return packages

    def is_installed(self, target, package, user_id=None):
        """Paketin hedef cihazda kurulu olup olmadığını hızlıca sorgular (pm path)."""
        if not is_valid_package(package):
            return False
        cmd = ['pm', 'path', package]
        if user_id is not None:
            cmd = ['pm', 'path', '--user', str(check_user_id(user_id)), package]
        try:
            r = self.shell(target, *cmd, timeout=10)
            return r.exit_code == 0 and 'package:' in (r.output or '')
        except Exception:
            return False

    @staticmethod
    def _parse_package_list(output):
        pkgs = []
        for line in (output or '').splitlines():
            line = line.strip()
            if not line:
                continue
            if not line.startswith('package:'):
                if re.fullmatch(r'no packages(?: found)?\.?', line, re.I):
                    continue
                raise AdbError('Paket listesi çözümlenemedi: ' + line[:200])
            pkg = line[len('package:'):].strip()
            if not is_valid_package(pkg) or ':' in pkg:
                raise AdbError('Paket listesi bozuk kayıt içeriyor: ' + line[:200])
            if pkg not in pkgs:
                pkgs.append(pkg)
        return pkgs

    def list_packages_user0(self, target, timeout=30, user_id=0):
        """Seçilen kullanıcı için GERÇEKTEN kurulu paketler.

        Tarihsel metot adı korunur. '--user ID' sadece o kullanicida gorunur
        paketleri dondurur; o kullanıcıdan kaldirilmis sistem
        uygulamalari listede CIKMAZ.
        """
        uid = check_user_id(user_id)
        try:
            r = self.shell(target, 'pm', 'list', 'packages', '--user', str(uid),
                           timeout=timeout)
        except AdbError:
            return None
        if r.exit_code != 0:
            return None
        try:
            pkgs = set(self._parse_package_list(r.output))
        except AdbError:
            return None
        if re.search(r'\b(error|exception|denied|not allowed|invalid|usage|unknown|failed|failure)\b',
                     r.error or '', re.I):
            return None
        # An empty set is a valid result for a newly created user. Keep None
        # reserved for a failed or unparsable query so callers can fail closed.
        return pkgs

    # Paket listesi önbelleği: {(target, include_system, user_id): (zaman, veri)}
    # Coklu worker thread erisimine karsi kilit + uretim sayaci (generation):
    # invalidate -> generation artar; bayat okumayla baslayan tarama eski
    # generation ile yazar, put() sayac uyusmadigi icin reddedilir.
    _pkg_cache = {}
    _pkg_cache_ttl = 60
    _pkg_cache_gen = 0
    _pkg_cache_lock = threading.Lock()

    def _pkg_cache_get(self, target, include_system, user_id=0):
        """(veri, generation) dondurur; miss ise (None, generation)."""
        key = (target, bool(include_system), check_user_id(user_id))
        with self._pkg_cache_lock:
            gen = self._pkg_cache_gen
            hit = self._pkg_cache.get(key)
            if hit and (time.time() - hit[0]) < self._pkg_cache_ttl:
                return hit[1], gen
            return None, gen

    def _pkg_cache_put(self, target, include_system, data, gen=None, user_id=0):
        """Onbellige yazar. gen verilmis ve bayattiysa yazmaz (yarisma onlenir).

        Donus: True = yazildi, False = bayat/iptal edilmis yazma reddedildi.
        """
        key = (target, bool(include_system), check_user_id(user_id))
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

    def list_packages_detailed(self, target, include_system=False, use_cache=True,
                               user_id=0):
        """Paket + APK yolu + kurulum/devre disi/user0 durumu (hizli).

        Donus: [{'package':, 'apk':, 'enabled': bool, 'installed_user0': bool}].
        Eski installed_user0 alanı geriye uyumluluk için korunur; user_id
        verildiğinde seçilen kullanıcının kurulum durumunu taşır.

        Not: Android 8+ APK yolu '.../base.apk=com.pkg' biciminde ve yolun
        kendisi '==' icerebilir (ornegin
        /data/app/~~XXXX==/com.pkg-YYYY==/base.apk=com.pkg). Bu yuzden
        sondaki SON '=' isaretinden bolunur (rpartition).

        Not: '--user ID' ile kaldirilmis sistem uygulamalari '-a' listesinde
        HALA gorunur. 'installed_user0=False' olanlar rozetli gosterilir ve
        geri yuklenebilir; mevcut kullanıcı id'si installed_user0 alaninda
        taşınır.

        use_cache=True ise 60 sn onbellek kullanilir (tarama hizi).
        Yazma islemleri sonrasi invalidate_pkg_cache() cagrilmalidir.
        """
        uid = check_user_id(user_id)
        gen = None
        if use_cache:
            hit, gen = self._pkg_cache_get(target, include_system, uid)
            if hit is not None:
                return [dict(e) for e in hit]
        flag = '-a' if include_system else '-3'
        r = self.shell(target, 'pm', 'list', 'packages', '-f', flag, '-u',
                       '--user', str(uid), timeout=60)
        if r.exit_code != 0:
            raise AdbError('Paket listesi okunamadı: {}'.format(
                (r.error or r.output or 'pm list packages başarısız').strip()))
        out = []
        for line in (r.output or '').splitlines():
            line = line.strip()
            if not line.startswith('package:'):
                if line and not re.fullmatch(r'no packages(?: found)?\.?', line, re.I):
                    raise AdbError('Paket listesi çözümlenemedi: ' + line[:200])
                continue
            body = line[len('package:'):].strip()
            # SON '=' ayirici: sol APK yolu, sag paket adi.
            apk, sep, pkg = body.rpartition('=')
            pkg = pkg.strip()
            apk = apk.strip()
            if not sep or not apk or not is_valid_package(pkg) or ':' in pkg:
                raise AdbError('Paket listesi bozuk kayıt içeriyor: ' + line[:200])
            out.append({'package': pkg, 'apk': apk, 'enabled': True,
                        'installed_user0': True})
        if include_system and not out:
            raise AdbError('Sistem paket listesi boş; sonuç doğrulanamadı.')
        # user 0'da gercekten kurulu olanlar (kaldirilanlari isaretle)
        user0 = self.list_packages_user0(target, user_id=uid)
        if user0 is None:
            raise PackageStateUnknownError(
                'user {} paket listesi okunamadı; paket durumları doğrulanamadı.'.format(uid))
        for e in out:
            e['installed_user0'] = e['package'] in user0
        # devre disi olanlari isaretle (pm list packages -d)
        try:
            rd = self.shell(target, 'pm', 'list', 'packages', '--user', str(uid),
                            '-d', timeout=30)
        except AdbError as exc:
            raise PackageStateUnknownError(
                'Devre dışı paket listesi okunamadı: {}'.format(exc)) from exc
        if rd.exit_code != 0:
            raise PackageStateUnknownError('Devre dışı paket listesi okunamadı: {}'.format(
                (rd.error or rd.output or 'pm list packages -d başarısız').strip()))
        if re.search(r'\b(error|exception|denied|not allowed|invalid|usage|unknown|failed|failure)\b',
                     rd.error or '', re.I):
            raise PackageStateUnknownError(
                'Devre dışı paket listesi okunamadı: ' + (rd.error or '').strip())
        try:
            disabled = set(self._parse_package_list(rd.output))
        except AdbError as exc:
            raise PackageStateUnknownError(
                'Devre dışı paket listesi çözümlenemedi: {}'.format(exc)) from exc
        for e in out:
            if e['package'] in disabled:
                e['enabled'] = False
        if use_cache:
            # gen: bayat olani yazma (islem sirasinda invalidate olmus olabilir)
            self._pkg_cache_put(target, include_system,
                                [dict(e) for e in out], gen, user_id=uid)
        return out

    def running_processes(self, target):
        """Cihazdan taze bir ps snapshot'i oku; okunamiyorsa hata ver."""
        first = self.shell(target, 'ps', '-A', '-o', 'NAME')
        if first.exit_code == 0 and self._has_process_rows(first.output):
            return first.output
        # Eski Android surumlerinde -o NAME desteklenmez.
        fallback = self.shell(target, 'ps', '-A')
        if fallback.exit_code == 0 and self._has_process_rows(fallback.output):
            return fallback.output
        reason = (fallback.error or fallback.output or first.error or first.output or '').strip()
        raise AdbError('Çalışan süreçler okunamadı{}.'.format(
            ': ' + reason[:200] if reason else ''))

    @staticmethod
    def _has_process_rows(output):
        """Bos veya ps hata metnini basarili bir process snapshot'i sanma."""
        lines = [line.strip() for line in (output or '').splitlines() if line.strip()]
        if not lines:
            return False
        if any(re.search(r'\b(?:not found|unknown option|bad option|usage:)\b', line, re.I)
               or re.match(r'^(?:error|ps:|toybox:|busybox:)', line, re.I)
               for line in lines):
            return False
        rows = [line for line in lines if not re.match(
            r'^(?:USER\b|LABEL\b|NAME\b|PID\b)', line, re.I)]
        if not rows:
            return False
        # NAME-only output has one process name per row. Full ps output has
        # numeric process columns; arbitrary diagnostics must not become a
        # clean negative running result.
        return any(len(line.split()) == 1 or any(
            part.isdigit() for part in line.split()[:3]) for line in rows)

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
        known_supplied = known_packages is not None
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
            if known_supplied:
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
        # `application-label:` is also used by aapt, while package-manager
        # dumps vary by Android/OEM version. Prefer the unlocalized label,
        # then accept localized labels and the fields printed by some TV ROMs.
        labels = {}
        priorities = {}
        cur = None
        package_header = re.compile(
            r'^(?:Package\s*\[\s*([^\]]+?)\s*\]'
            r'|Package\s*:\s*([A-Za-z][A-Za-z0-9_.]+)'
            r'|Package\s+([A-Za-z][A-Za-z0-9_.]+)\s*[:{]'
            r'|Package\s*\{\s*[0-9a-fA-F]+\s+([A-Za-z][A-Za-z0-9_.]+)\s*\})', re.I)
        label_line = re.compile(
            r'^(?:application-label(?:-([A-Za-z0-9_-]+))?'
            r'|application[\s_-]+label|app(?:lication)?Label)\s*(?::|=|\s)\s*(.*?)\s*$',
            re.I)
        nonlocalized_label = re.compile(
            r'\bnonLocalizedLabel\s*=\s*(null|"(?:\\.|[^"\\])*"|'
            r"'(?:\\.|[^'\\])*'|.*?)(?=\s+(?:icon|banner|labelRes|name|packageName)=|$)", re.I)

        def record_label(package, value, priority):
            if not package or not is_valid_package(package) or ':' in package:
                return
            label = (value or '').strip()
            if len(label) >= 2 and label[0] == label[-1] and label[0] in '\'"':
                label = label[1:-1].strip()
            label = re.sub(r'\s+', ' ', label)
            if (not label or label.casefold() in ('null', 'none', '(null)', 'unknown')
                    or label.casefold() == package.casefold()
                    or ('.' in label and is_valid_package(label))
                    or re.fullmatch(r'@?0x[0-9a-f]{6,}', label, re.I)):
                return
            if package not in priorities or priority < priorities[package]:
                labels[package] = label
                priorities[package] = priority

        for raw_line in (r.output or '').splitlines():
            s = raw_line.strip()
            if not s:
                continue
            header = package_header.match(s)
            if header:
                cur = next((part.strip() for part in header.groups() if part), None)
                continue
            if s.lower().startswith('package '):
                # Do not let a vendor-specific, unrecognized section header
                # attach its metadata to the preceding package.
                cur = None
                continue
            if cur is None:
                continue

            match = label_line.match(s)
            if match:
                locale = match.group(1)
                record_label(cur, match.group(2), 1 if locale else 0)
                continue

            # A few dumps include PackageItemInfo/ApplicationInfo fields
            # instead of application-label lines. A resource ID alone is not
            # a display name, so only nonLocalizedLabel can supply a value.
            match = nonlocalized_label.search(s)
            if match:
                record_label(cur, match.group(1), 2)
                continue

            # Accept the compact badging-style form when a ROM embeds it in
            # its package dump (the stock dumpsys format does not).
            match = re.search(r"\bapplication:\s*label\s*=\s*(['\"])(.*?)\1", s, re.I)
            if match:
                record_label(cur, match.group(2), 0)
        return labels

    def bulk_restricted(self, target, user_id=0):
        """Kısıtlı arka plan modundaki paketleri iki AppOp için topluca bul.

        ignore, deny ve foreground modları kısıtlı sayılır. Sorgulardan biri
        başarısızsa kısmi sonuçla paketleri yanlışlıkla Serbest göstermemek
        için None döner.
        """
        uid = check_user_id(user_id)
        out = set()
        modes = ('ignore', 'deny', 'foreground')
        for op in ('RUN_IN_BACKGROUND', 'RUN_ANY_IN_BACKGROUND'):
            for mode in modes:
                r = self.shell(target, 'cmd', 'appops', 'query-op', '--user',
                               str(uid), op, mode, timeout=60)
                text = '{} {}'.format(r.output or '', r.error or '')
                if (r.exit_code != 0 or re.search(
                        r'\b(error|unknown|exception|denied|not allowed|not supported|'
                        r'not found|invalid|usage)\b',
                        text, re.I)):
                    return None
                for line in (r.output or '').splitlines():
                    line = line.strip()
                    if not line or re.fullmatch(r'no operations(?: found)?\.?', line, re.I):
                        continue
                    if not is_valid_package(line) or ':' in line:
                        return None
                    out.add(line)
        return out

    def app_status_fallback(self, target, pkg, user_id=0):
        """Bulk cagrisi bos donerse tek paket icin kullanim.

        Dönüş: 'Kisitli' | 'Serbest' | 'Bilinmiyor'
        """
        modes = []
        for op in ('RUN_IN_BACKGROUND', 'RUN_ANY_IN_BACKGROUND'):
            try:
                modes.append(self._background_mode(target, pkg, op, user_id=user_id))
            except AdbError:
                modes.append(None)
        return self._classify_background_modes(modes)

    @staticmethod
    def _classify_background_modes(modes):
        if any(mode in ('ignore', 'deny', 'errored', 'foreground') for mode in modes):
            return 'Kisitli'
        if len(modes) == 2 and all(mode is not None for mode in modes):
            return 'Serbest'
        return 'Bilinmiyor'

    def _background_mode(self, target, pkg, op, user_id=0):
        uid = check_user_id(user_id)
        result = self.shell(target, 'cmd', 'appops', 'get', '--user', str(uid),
                            pkg, op, timeout=10)
        text = '{} {}'.format(result.output, result.error).strip()
        if result.exit_code != 0 or re.search(r'error|exception|unknown|denied', text, re.I):
            raise AdbError('Arka plan izni okunamadı ({}): {}'.format(pkg, text))
        match = re.search(
            re.escape(op) + r'\s*:\s*(allow|ignore|default|deny|errored|foreground)\b',
            result.output, re.I)
        if match:
            mode = match.group(1).lower()
            return 'deny' if mode == 'errored' else mode
        if re.search(r'No operations', result.output, re.I):
            return 'default'
        raise AdbError('Arka plan izni doğrulanamadı: ' + pkg)

    @staticmethod
    def app_status(restricted, pkg):
        if restricted is None:
            return 'Bilinmiyor'
        return 'Kisitli' if pkg in restricted else 'Serbest'

    def restrict(self, target, pkg, user_id=0):
        return self._set_background_state(target, pkg, True, user_id=user_id)

    def unrestrict(self, target, pkg, user_id=0):
        return self._set_background_state(target, pkg, False, user_id=user_id)

    def _set_background_state(self, target, pkg, restrict, user_id=0):
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        uid = check_user_id(user_id)
        api_level = self._android_api_level(target)
        required_api = 30 if restrict else 28
        bucket = 'restricted' if restrict else 'active'
        use_bucket = api_level >= required_api

        ops = ('RUN_IN_BACKGROUND', 'RUN_ANY_IN_BACKGROUND')
        previous = {op: self._background_mode(target, pkg, op, user_id=uid) for op in ops}
        previous_bucket = self._standby_bucket(target, pkg, user_id=uid) if use_bucket else None
        mode = 'ignore' if restrict else 'allow'
        attempted = []
        bucket_attempted = False
        try:
            for op in ops:
                # A command can change state even when it returns an error.
                attempted.append(op)
                result = self.shell(target, 'cmd', 'appops', 'set', '--user',
                                    str(uid), pkg, op, mode)
                text = '{} {}'.format(result.output or '', result.error or '').strip()
                if result.exit_code != 0 or re.search(
                        r'error|exception|unknown|denied|not allowed', text, re.I):
                    raise AdbError(text or 'Komut reddedildi.')

            if use_bucket:
                # A failed shell status may still follow a state change.
                bucket_attempted = True
                result = self.shell(target, 'am', 'set-standby-bucket', '--user',
                                    str(uid), pkg, bucket)
                text = '{} {}'.format(result.output or '', result.error or '').strip()
                if result.exit_code != 0 or re.search(
                        r'error|exception|unknown|denied|not allowed', text, re.I):
                    raise AdbError(text or 'Standby bucket komutu reddedildi.')
                expected_bucket = '45' if restrict else '10'
                if self._standby_bucket(target, pkg, user_id=uid) != expected_bucket:
                    raise AdbError('Standby bucket istenen duruma geçmedi.')

            if any(self._background_mode(target, pkg, op, user_id=uid) != mode
                   for op in ops):
                raise AdbError('Komut çalıştı ancak arka plan izinleri doğrulanamadı.')
            return True
        except Exception as exc:
            rollback_errors = []
            if bucket_attempted:
                try:
                    result = self.shell(target, 'am', 'set-standby-bucket', '--user',
                                        str(uid), pkg, previous_bucket)
                    text = '{} {}'.format(result.output or '', result.error or '').strip()
                    if result.exit_code != 0 or re.search(
                            r'error|exception|unknown|denied|not allowed', text, re.I):
                        raise AdbError(text or 'Standby bucket geri alma komutu reddedildi.')
                    if self._standby_bucket(target, pkg, user_id=uid) != previous_bucket:
                        raise AdbError('Standby bucket geri yüklemesi doğrulanamadı.')
                except Exception as rollback_error:
                    rollback_errors.append('standby bucket: {}'.format(rollback_error))
            for op in reversed(attempted):
                old_mode = previous[op]
                try:
                    result = self.shell(target, 'cmd', 'appops', 'set', '--user',
                                        str(uid), pkg, op, old_mode)
                    text = '{} {}'.format(result.output or '', result.error or '').strip()
                    if result.exit_code != 0 or re.search(
                            r'error|exception|unknown|denied|not allowed', text, re.I):
                        raise AdbError(text or 'Geri alma komutu reddedildi.')
                    if self._background_mode(target, pkg, op, user_id=uid) != old_mode:
                        raise AdbError('Geri yükleme doğrulanamadı.')
                except Exception as rollback_error:
                    rollback_errors.append('{}: {}'.format(op, rollback_error))
            if rollback_errors:
                raise AdbError(
                    'Arka plan kısıtlaması uygulanamadı ({}): {}. AppOps geri alma '
                    'başarısız: {}'.format(pkg, exc, '; '.join(rollback_errors))) from exc
            restored = 'AppOps ve standby bucket' if bucket_attempted else 'AppOps'
            raise AdbError(
                'Arka plan kısıtlaması uygulanamadı ({}): {}. Önceki {} durumları '
                'geri yüklendi.'.format(pkg, exc, restored)) from exc

    def _standby_bucket(self, target, pkg, user_id=0):
        """Read the numeric bucket so a failed operation can restore it exactly."""
        uid = check_user_id(user_id)
        result = self.shell(target, 'am', 'get-standby-bucket', '--user', str(uid),
                            pkg, timeout=10)
        value = (result.output or '').strip()
        if (result.exit_code != 0 or not re.fullmatch(r'\d{1,3}', value)
                or int(value) > 100):
            detail = (result.error or result.output or 'bucket okunamadı').strip()
            raise AdbError('Standby bucket okunamadı ({}): {}'.format(pkg, detail))
        return value

    def _android_api_level(self, target):
        result = self.shell(target, 'getprop', 'ro.build.version.sdk', timeout=10)
        value = (result.output or '').strip()
        if result.exit_code != 0 or not re.fullmatch(r'\d+', value):
            detail = (result.error or result.output or 'API düzeyi okunamadı').strip()
            raise AdbError('Cihaz API düzeyi belirlenemedi; değişiklik yapılmadı: ' + detail)
        return int(value)

    def force_stop(self, target, pkg, user_id=0):
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        uid = check_user_id(user_id)
        result = self.shell(target, 'am', 'force-stop', '--user', str(uid), pkg)
        text = '{} {}'.format(result.output or '', result.error or '').strip()
        if result.exit_code != 0 or re.search(
                r'^\s*(?:error|exception|failed|failure)\b', text, re.I | re.M):
            raise AdbError('Uygulama durdurulamadı ({}): {}'.format(
                pkg, text or 'force-stop başarısız'))
        return result

    def clear_data(self, target, pkg, user_id=0):
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        uid = check_user_id(user_id)
        r = self.shell(target, 'pm', 'clear', '--user', str(uid), pkg)
        text = '{} {}'.format(r.output, r.error)
        if (r.exit_code != 0 or not re.search(r'\bSuccess\b', text)
                or re.search(r'\b(error|failed|denied|not allowed|no such package|unknown package)\b',
                             text, re.I)):
            raise AdbError('Veri silinemedi ({}): {}'.format(pkg, text.strip() or 'bilinmeyen hata'))
        return r

    def enable(self, target, pkg, user_id=0):
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        uid = check_user_id(user_id)
        r = self.shell(target, 'pm', 'enable', '--user', str(uid), pkg)
        text = '{} {}'.format(r.output, r.error)
        if r.exit_code != 0 or re.search(
                r'(^|\n)\s*(?:error|exception|failed|failure|denied|not allowed|'
                r'cannot|no such package|unknown package)\b', text, re.I):
            raise AdbError('Aktif edilemedi ({}): {}'.format(pkg, text.strip() or 'bilinmeyen hata'))
        if self.is_uninstalled_for_user(target, pkg, user_id=uid):
            raise AdbError('{} user {} için kurulu değil; etkinleştirilemez.'.format(pkg, uid))
        if self.is_disabled(target, pkg, user_id=uid):
            raise AdbError('Komut çalıştı ancak {} user {} için hâlâ devre dışı.'.format(
                pkg, uid))
        return r

    def disable_user(self, target, pkg, user_id=0):
        """Force-stop, then disable for the selected user without clearing data.

        Donus: (durum, mesaj). durum True ise paket gercekten devre disi.
        """
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        uid = check_user_id(user_id)
        try:
            self.force_stop(target, pkg, user_id=uid)
        except AdbError:
            pass
        r = self.shell(target, 'pm', 'disable-user', '--user', str(uid), pkg)
        text = '{} {}'.format(r.output, r.error)
        if r.exit_code != 0 or re.search(
                r'(^|\n)\s*(?:error|exception|failed|failure|denied|not allowed|'
                r'cannot|no such package|unknown package)\b', text, re.I):
            raise AdbError('Devre dışı birakilamadi ({}): {}'.format(pkg, text.strip() or 'bilinmeyen hata'))
        if not self.is_disabled(target, pkg, user_id=uid):
            raise AdbError('Komut calisti ama {} user {} icin hala aktif gorunuyor.'.format(
                pkg, uid))
        return r

    def uninstall_user(self, target, pkg, user_id=0):
        """Kullanici icin kaldirma. pm ciktisini DOGRULAR.

        Sistem uygulamalarinda 'Failure [not installed for USER_ID]' gibi
        cikti sessizce basari sayilmaz; AdbError atilir. Zaten kaldirilmis
        paket icin tekrar denemek basari sayilir (idempotent). Uygulama
        '-k' uygulama verisi/cache'i saklamayi ister; kaldirma oncesi pm clear
        calistirilmaz.
        """
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        uid = check_user_id(user_id)
        if self.is_uninstalled_for_user(target, pkg, user_id=uid):
            return None  # zaten kaldirilmis -> basari
        try:
            self.force_stop(target, pkg, user_id=uid)
        except AdbError:
            pass
        r = self.shell(target, 'pm', 'uninstall', '-k', '--user', str(uid), pkg)
        text = '{} {}'.format(r.output, r.error)
        if r.exit_code == 0 and re.search(r'\bSuccess\b', text):
            if self.is_uninstalled_for_user(target, pkg, user_id=uid):
                return r
            raise AdbError('Kaldırma komutu başarılı göründü ancak {} user {} için hâlâ kurulu.'.format(
                pkg, uid))
        if re.search(r'not installed for|already|no such package|unknown package', text, re.I):
            # Yaris durumu: komut sirasinda zaten gitmis -> basari say.
            if self.is_uninstalled_for_user(target, pkg, user_id=uid):
                return r
        raise AdbError('Kaldırılamadı ({}): {}'.format(pkg, text.strip() or 'bilinmeyen hata'))

    def install_existing(self, target, pkg, user_id=0):
        """Geri yukleme (UAD: cmd package install-existing --user USER_ID).

        Eski 'pm install-existing' bazi Android 14 surumlerinde sessiz
        kalir; once 'cmd package' denenir, olmazsa 'pm' yedegi kullanilir.
        Cikti ve durum DOGRULANIR.
        """
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        uid = check_user_id(user_id)
        last_err = ''
        attempts = [['cmd', 'package', 'install-existing', '--user', str(uid), pkg],
                    ['pm', 'install-existing', '--user', str(uid), pkg]]
        if uid == 0:
            attempts.append(['pm', 'install-existing', pkg])
        for args in attempts:
            r = self.shell(target, *args)
            text = '{} {}'.format(r.output, r.error)
            if (r.exit_code == 0 and
                    (re.search(r'\bSuccess\b', text) or 'installed for user' in text.lower())):
                if not self.is_uninstalled_for_user(target, pkg, user_id=uid):
                    # install-existing bazi surumlerde devre disi birakir;
                    # UAD sirasi: geri yukle + aktif et.
                    self.enable(target, pkg, user_id=uid)
                    return r
                last_err = text.strip()
                continue
            last_err = text.strip()
        raise AdbError('Geri yuklenemedi ({}): {}'.format(pkg, last_err or 'bilinmeyen hata'))

    def smart_remove(self, target, pkg, user_id=0):
        """Akilli kaldirma (UAD onerisi: disable dene, olmazsa uninstall).

        Sirayla dener, ilk basarili yontemi dondurur:
        1. disable-user (en guvenli, geri donusu kolay)
        2. uninstall --user ID (daha derin, geri donusu zor)
        Ikisi de basarisizsa son hatayi yukseltir.
        Donus: (yontem, sonuc) ; yontem 'disable' | 'uninstall'.
        """
        errors = []
        try:
            r = self.disable_user(target, pkg, user_id=user_id)
            return ('disable', r)
        except PackageStateUnknownError:
            # Unverified state is not evidence that disabling failed; never
            # escalate to an uninstall when this probe could not be trusted.
            raise
        except AdbError as e:
            errors.append('disable: ' + str(e))
        try:
            r = self.uninstall_user(target, pkg, user_id=user_id)
            return ('uninstall', r)
        except AdbError as e:
            errors.append('uninstall: ' + str(e))
        raise AdbError('{} kaldirilamadi.\n{}'.format(pkg, '\n'.join(errors)))

    def is_uninstalled_for_user(self, target, pkg, timeout=10, user_id=0):
        """Return whether a package is absent for one user; raise if unknown."""
        pkg = str(pkg or '').strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        uid = check_user_id(user_id)
        packages = self.list_packages_user0(target, timeout=timeout, user_id=uid)
        if packages is None:
            raise PackageStateUnknownError(
                'Paket durumu okunamadı ({} user {}); sonuç doğrulanamadı.'.format(pkg, uid))
        return pkg not in packages

    def is_disabled(self, target, pkg, timeout=10, user_id=0):
        """Return whether a package is disabled for one user; raise if unknown."""
        pkg = str(pkg or '').strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        uid = check_user_id(user_id)
        try:
            r = self.shell(target, 'pm', 'list', 'packages', '--user', str(uid),
                           '-d', timeout=timeout)
        except AdbError as exc:
            raise PackageStateUnknownError(
                'Devre dışı durumu okunamadı ({} user {}): {}'.format(pkg, uid, exc)) from exc
        if r.exit_code != 0:
            detail = (r.error or r.output or 'pm list packages -d başarısız').strip()
            raise PackageStateUnknownError(
                'Devre dışı durumu okunamadı ({} user {}): {}'.format(pkg, uid, detail))
        try:
            disabled = self._parse_package_list(r.output)
        except AdbError as exc:
            raise PackageStateUnknownError(
                'Devre dışı durumu çözümlenemedi ({} user {}): {}'.format(
                    pkg, uid, exc)) from exc
        if re.search(r'\b(error|exception|denied|not allowed|invalid|usage|unknown|failed|failure)\b',
                     r.error or '', re.I):
            raise PackageStateUnknownError(
                'Devre dışı durumu okunamadı ({} user {}): {}'.format(
                    pkg, uid, (r.error or '').strip()))
        return pkg in disabled

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
            r = self.shell(target, 'du', '-sk', _quoted_remote_path(data_dir), timeout=timeout)
            m = re.search(r'(\d+)', r.output)
            if m:
                return int(m.group(1))
        except AdbError:
            pass
        return None

    def pull(self, target, remote, local, timeout=300, cancel_check=None):
        remote = safe_remote_path(remote)
        options = {'timeout': timeout}
        if cancel_check is not None:
            options['cancel_check'] = cancel_check
        r = self.run(['-s', target, 'pull', remote, local], **options)
        if r.exit_code != 0:
            raise AdbError('Indirilemedi ({}): {}'.format(
                remote, (r.output + ' ' + r.error).strip() or 'bilinmeyen hata'))
        return r

    def push(self, target, local, remote, timeout=300, cancel_check=None):
        """Yerel dosyayi cihaza yukler. Basarisizsa AdbError atar."""
        remote = safe_remote_path(remote)
        options = {'timeout': timeout}
        if cancel_check is not None:
            options['cancel_check'] = cancel_check
        r = self.run(['-s', target, 'push', local, remote], **options)
        text = '{} {}'.format(r.output, r.error)
        if r.exit_code != 0 or re.search(r'failed|error|no such|denied', text, re.I):
            raise AdbError('Yüklenemedi ({} -> {}): {}'.format(
                local.rsplit('\\', 1)[-1].rsplit('/', 1)[-1],
                remote, text.strip() or 'bilinmeyen hata'))
        return r

    # ------------------------------------------------------------------
    # Kumanda
    # ------------------------------------------------------------------
    def keyevent(self, target, code, longpress=False):
        try:
            code = int(code)
        except (TypeError, ValueError):
            raise AdbError('Geçersiz keyevent kodu: {!r}'.format(code))
        if not 0 <= code <= 300:
            raise AdbError('Geçersiz keyevent kodu: {}'.format(code))
        args = ('--longpress', str(code)) if longpress else (str(code),)
        return self.shell(target, 'input', 'keyevent', *args, timeout=10)

    def input_text(self, target, text):
        safe = sanitize_input_text(text)
        if not safe:
            raise AdbError('Gonderilecek geçerli karakter yok (özel semboller atildi).')
        return self.shell(target, 'input', 'text', safe, timeout=10)

    def tap(self, target, x, y, timeout=10):
        """Ekranda belirli bir koordinata dokunur (input tap X Y)."""
        try:
            x_val, y_val = int(x), int(y)
        except (TypeError, ValueError):
            raise AdbError('Geçersiz koordinat: ({}, {})'.format(x, y))
        if x_val < 0 or y_val < 0:
            raise AdbError('Koordinatlar negatif olamaz: ({}, {})'.format(x_val, y_val))
        return self.shell(target, 'input', 'tap', str(x_val), str(y_val), timeout=timeout)

    def swipe(self, target, x1, y1, x2, y2, duration_ms=300, timeout=10):
        """Ekranda kaydırma hareketi yapar (input swipe X1 Y1 X2 Y2 [duration])."""
        try:
            coords = [int(x1), int(y1), int(x2), int(y2), int(duration_ms)]
        except (TypeError, ValueError):
            raise AdbError('Geçersiz kaydırma parametresi.')
        if any(c < 0 for c in coords):
            raise AdbError('Parametreler negatif olamaz.')
        args = [str(c) for c in coords]
        return self.shell(target, 'input', 'swipe', *args, timeout=timeout)

    def launch(self, target, pkg, user_id=0):
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        uid = check_user_id(user_id)
        # 1. Leanback launcher (TV) ve Standart Launcher (Mobil) kategorileri
        for cat in ('android.intent.category.LEANBACK_LAUNCHER', 'android.intent.category.LAUNCHER'):
            r = self.shell(target, 'monkey', '--user', str(uid), '-p', pkg, '-c',
                           cat, '1', timeout=15)
            text = '{} {}'.format(r.output or '', r.error or '')
            if r.exit_code == 0 and not re.search(r'No activities found|error|exception|failed', text, re.I):
                return r

        # 2. Genel monkey fallback
        r = self.shell(target, 'monkey', '--user', str(uid), '-p', pkg, '1', timeout=15)
        text = '{} {}'.format(r.output or '', r.error or '')
        if r.exit_code != 0 or re.search(
                r'No activities found|error|exception|failed', text, re.I):
            raise AdbError('{} için user {} uygulaması başlatılamadı: {}'.format(
                pkg, uid, text.strip() or 'başlatma başarısız'))
        return r

    def launch_resolved(self, target, pkg, timeout=15, user_id=0):
        """Once resolve-activity dener (LEANBACK_LAUNCHER ve LAUNCHER), olmazsa monkey fallback."""
        pkg = str(pkg).strip()
        if not is_valid_package(pkg):
            raise AdbError('Geçersiz paket adi: {!r}'.format(pkg))
        uid = check_user_id(user_id)
        try:
            for cat in ('android.intent.category.LEANBACK_LAUNCHER', 'android.intent.category.LAUNCHER'):
                r = self.shell(target, 'cmd', 'package', 'resolve-activity',
                               '--brief', '--user', str(uid), '-c',
                               cat, pkg,
                               timeout=timeout)
                resolved = next((line.strip() for line in (r.output or '').splitlines()
                                 if home_pkg_of(line.strip()) == pkg), None)
                if r.exit_code == 0 and resolved:
                    r2 = self.shell(target, 'am', 'start', '--user', str(uid), '-n', resolved,
                                    timeout=timeout)
                    if (r2.exit_code == 0 and not re.search(
                            r'error|exception|failed',
                            '{} {}'.format(r2.output or '', r2.error or ''), re.I)):
                        return r2
        except AdbError:
            pass
        return self.launch(target, pkg, user_id=uid)

    def launch_app(self, target, pkg, timeout=15, user_id=0):
        """Uygulamayı TV ekranında başlatır (launch_resolved takma adı)."""
        return self.launch_resolved(target, pkg, timeout=timeout, user_id=user_id)

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
            fixed = _repair_png(r.output) if r.exit_code == 0 else None
            if fixed and png_is_valid(fixed):
                return fixed
        except AdbError:
            pass
        raise AdbError('Ekran goruntusu alinamadi (PNG dogrulanamadi).')

    def foreground_package(self, target, timeout=12):
        """Return the resumed app package when Android exposes it to dumpsys."""
        queries = (
            (['dumpsys', 'activity', 'activities'],
             ('topResumedActivity', 'mResumedActivity', 'ResumedActivity:')),
            (['dumpsys', 'window', 'windows'], ('mCurrentFocus=', 'mFocusedApp=')),
        )
        for command, markers in queries:
            try:
                result = self.shell(target, *command, timeout=timeout)
            except AdbError:
                continue
            for line in (result.output or '').splitlines():
                if not any(marker in line for marker in markers):
                    continue
                match = re.search(r'\bu\d+\s+([A-Za-z][A-Za-z0-9_.]+)/', line)
                if match:
                    return match.group(1)
        return ''

    def screenshot_via_file(self, target, timeout=60):
        """screencap'i cihazdaki dosyaya yazip pull ile indirir (guvenilir)."""
        import tempfile
        remote = '/sdcard/mibox_scr_{}.png'.format(os.getpid())
        try:
            r = self.shell(target, 'screencap', '-p', _quoted_remote_path(remote), timeout=timeout)
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
                if not png_is_valid(data):
                    raise AdbError('Ekran dosyası bozuk indi.')
                return data
            finally:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass
        finally:
            try:
                self.shell(target, 'rm', _quoted_remote_path(remote), timeout=10)
            except AdbError:
                pass

    def screenshot_hd(self, target, timeout=45):
        """Capture a physical display when possible; preserve the legacy byte API."""
        data, _used_hd = self.screenshot_hd_with_info(target, timeout=timeout)
        return data

    def screenshot_hd_with_info(self, target, timeout=45, check_cancel=None):
        """Return (PNG bytes, physical-display-capture-used)."""
        if callable(check_cancel):
            check_cancel()
        try:
            displays = self.shell(target, 'dumpsys', 'SurfaceFlinger', '--display-id', timeout=15)
            match = re.search(r'(?m)^\s*Display\s+(\d+)\s+\(HWC display 0\)', displays.output)
            if displays.exit_code != 0 or not match:
                if callable(check_cancel):
                    check_cancel()
                return self.screenshot(target, timeout=timeout), False
            r = self.run(['-s', target, 'exec-out', 'screencap', '-d', match.group(1), '-p'],
                         timeout=timeout, binary=True)
            fixed = _repair_png(r.output) if r.exit_code == 0 else None
            if fixed and png_is_valid(fixed):
                return fixed, True
        except AdbError:
            pass
        if callable(check_cancel):
            check_cancel()
        return self.screenshot(target, timeout=timeout), False

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

    def trim_caches(self, target, timeout=30):
        result = self.shell(target, 'pm', 'trim-caches', '999G', timeout=timeout)
        if not result.ok:
            error = '{} {}'.format(result.error or '', result.output or '').strip()
            raise AdbError(error or 'Uygulama önbellekleri temizlenemedi.')
        return result

    def logcat_clear(self, target, timeout=15):
        result = self.shell(target, 'logcat', '-c', timeout=timeout)
        if not result.ok:
            raise AdbError(result.error or result.output or 'Cihaz günlüğü temizlenemedi.')

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
        if not r.ok:
            raise AdbError(r.error or r.output or 'Cihaz günlüğü okunamadı.')
        return r.output or ''

    def logcat_crash(self, target, lines=120, timeout=30):
        """Son çökme izleri (AndroidRuntime + FATAL)."""
        args = ['logcat', '-d', '-v', 'brief', '-t', str(clamp_lines(lines, default=120)),
                'AndroidRuntime:E', '*:F', '*:S']
        r = self.shell(target, *args, timeout=timeout)
        if not r.ok:
            raise AdbError(r.error or r.output or 'Çökme kayıtları okunamadı.')
        return r.output or ''

    def _ls_symlink_name(self, target, directory, entry, timeout):
        """Resolve the filename/target boundary in an ambiguous ls symlink row.

        Toybox prints links as ``name -> target`` without escaping either
        field. When both contain that marker, verify each possible boundary
        with readlink and accept only a unique exact match.
        """
        matches = []
        offset = 0
        marker = ' -> '
        while True:
            boundary = entry.find(marker, offset)
            if boundary < 0:
                break
            name = entry[:boundary]
            link_target = entry[boundary + len(marker):]
            offset = boundary + len(marker)
            if not name or not link_target:
                continue
            try:
                result = self.shell(
                    target, 'readlink', _quoted_remote_path(directory + name),
                    timeout=timeout, preserve_output_whitespace=True)
            except AdbError:
                continue
            actual_target = (result.output or '').rstrip('\r\n')
            if result.exit_code == 0 and actual_target == link_target:
                matches.append(name)
        return matches[0] if len(matches) == 1 else None

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
        r = self.shell(target, 'ls', '-la', shlex.quote(p), timeout=timeout,
                       preserve_output_whitespace=True)
        if r.exit_code != 0:
            raise AdbError('Klasör listelenemedi ({}): {}'.format(
                p, (r.error or r.output or 'ls başarısız').strip()))
        out = []
        for line in (r.output or '').splitlines():
            if not line or line.startswith('total'):
                continue
            # Parse only the fixed metadata prefix. Keep the remaining filename
            # substring byte-for-byte (after UTF-8 decoding): split/join or
            # strip would merge distinct names such as "a  b" and "a b".
            header = re.match(r'^(\S+)\s+\S+\s+\S+\s+\S+\s+(\d+)\s+(.*)$', line)
            if not header:
                continue
            perm = header.group(1)
            if len(perm) < 10 or perm[0] not in 'd-lcbps':
                continue
            try:
                size = int(header.group(2))
            except ValueError:
                continue
            rest = header.group(3)
            date_tokens = list(re.finditer(r'\S+', rest))
            if (date_tokens and re.fullmatch(r'\d{4}-\d{2}-\d{2}',
                                             date_tokens[0].group())):
                date_count = 2
                if (len(date_tokens) < date_count
                        or not re.fullmatch(r'\d{2}:\d{2}', date_tokens[1].group())):
                    continue
            elif date_tokens and date_tokens[0].group() in (
                    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul',
                    'Aug', 'Sep', 'Oct', 'Nov', 'Dec'):
                date_count = 3
                if (len(date_tokens) < date_count
                        or not date_tokens[1].group().isdigit()
                        or not re.fullmatch(r'(?:\d{2}:\d{2}|\d{4})',
                                            date_tokens[2].group())):
                    continue
            else:
                continue
            name_start = date_tokens[date_count - 1].end()
            if name_start >= len(rest) or rest[name_start] not in ' \t':
                continue
            # Skip exactly the separator, retaining any leading whitespace in
            # the actual filename and all internal/trailing spaces.
            name = rest[name_start + 1:]
            if perm.startswith('l') and ' -> ' in name:
                if name.count(' -> ') == 1:
                    name = name.split(' -> ', 1)[0]
                else:
                    resolved_name = self._ls_symlink_name(
                        target, p, name, timeout)
                    if resolved_name is None:
                        # Ambiguous records are omitted rather than exposing
                        # a guessed path that could delete a different file.
                        continue
                    name = resolved_name
            if not name or name in ('.', '..'):
                continue
            mtime = ' '.join(token.group() for token in date_tokens[:date_count])
            out.append({'name': name, 'size': size, 'dir': perm.startswith('d'),
                        'perm': perm, 'mtime': mtime})
        out.sort(key=lambda e: (not e['dir'], e['name'].lower()))
        return out

    @staticmethod
    def _is_protected_file_path(path):
        protected_roots = {
            '/', '/sdcard', '/data', '/system', '/vendor', '/storage',
            '/data/media', '/data/media/0',
            '/storage/emulated', '/storage/emulated/0', '/storage/emulated/legacy',
            '/storage/self', '/storage/self/primary',
            '/mnt', '/mnt/runtime', '/mnt/user', '/mnt/user/0', '/mnt/user/0/primary',
            '/mnt/shell', '/mnt/shell/emulated', '/mnt/shell/emulated/0',
            '/mnt/media_rw', '/mnt/expand',
        }
        for runtime_view in ('default', 'read', 'write'):
            runtime_root = '/mnt/runtime/' + runtime_view
            protected_roots.update((runtime_root, runtime_root + '/emulated',
                                    runtime_root + '/emulated/0'))
        parts = [part for part in path.split('/') if part]
        # Block mount points for every Android user and removable volume, not
        # only user 0. Their child folders remain available to the file manager.
        is_storage_volume_root = len(parts) == 2 and parts[0] == 'storage'
        is_emulated_user_root = (
            len(parts) == 3 and parts[:2] == ['storage', 'emulated']
            and parts[2].isdigit())
        is_data_media_user_root = (
            len(parts) == 3 and parts[:2] == ['data', 'media']
            and parts[2].isdigit())
        is_mnt_user_root = (
            len(parts) == 3 and parts[:2] == ['mnt', 'user']
            and parts[2].isdigit())
        is_mnt_user_primary_root = (
            len(parts) == 4 and parts[:2] == ['mnt', 'user']
            and parts[2].isdigit() and parts[3] == 'primary')
        is_runtime_user_root = (
            len(parts) == 5 and parts[:2] == ['mnt', 'runtime']
            and parts[2] in ('default', 'read', 'write')
            and parts[3] == 'emulated' and parts[4].isdigit())
        is_shell_user_root = (
            len(parts) == 4 and parts[:3] == ['mnt', 'shell', 'emulated']
            and parts[3].isdigit())
        is_media_rw_volume_root = len(parts) == 3 and parts[:2] == ['mnt', 'media_rw']
        is_adopted_storage_root = len(parts) == 3 and parts[:2] == ['mnt', 'expand']
        return (path in protected_roots or is_storage_volume_root or is_emulated_user_root
                or is_data_media_user_root or is_mnt_user_root
                or is_mnt_user_primary_root or is_runtime_user_root or is_shell_user_root
                or is_media_rw_volume_root or is_adopted_storage_root)

    def file_remove(self, target, path, timeout=20):
        path = safe_remote_path(path)
        if self._is_protected_file_path(path):
            raise AdbError('Kok dizinler silinemez: {}'.format(path))

        # Canonicalize the parent rather than the leaf: selecting a symlink
        # should delete the link itself, while symlinked ancestors must not
        # redirect deletion into protected storage. readlink -f is in Android
        # Toybox; failure is fail-closed.
        parent = posixpath.dirname(path.rstrip('/')) or '/'
        name = posixpath.basename(path.rstrip('/'))
        resolved = self.shell(
            target, 'readlink', '-f', _quoted_remote_path(parent), timeout=timeout,
            preserve_output_whitespace=True)
        resolved_parent = (resolved.output or '').rstrip('\r\n')
        if resolved.exit_code != 0 or not resolved_parent:
            raise AdbError('Silinecek yolun üst dizini doğrulanamadı ({}): {}'.format(
                parent, (resolved.error or resolved.output or 'readlink başarısız').strip()))
        resolved_parent = safe_remote_path(resolved_parent)
        canonical = safe_remote_path(
            (resolved_parent.rstrip('/') + '/' + name) if name else resolved_parent)
        if self._is_protected_file_path(canonical):
            raise AdbError('Korunan kok dizin silinemez: {}'.format(canonical))
        r = self.shell(target, 'rm', '-rf', _quoted_remote_path(canonical), timeout=timeout)
        if r.exit_code != 0:
            raise AdbError('Silinemedi ({}): {}'.format(
                canonical, (r.output + r.error).strip() or 'rm başarısız'))

    def file_mkdir(self, target, path, timeout=15):
        r = self.shell(target, 'mkdir', '-p', _quoted_remote_path(path), timeout=timeout)
        if r.exit_code != 0 or re.search(
                r'\b(error|failed|denied|not allowed)\b',
                '{} {}'.format(r.output or '', r.error or ''), re.I):
            raise AdbError('Dizin oluşturulamadı ({}): {}'.format(
                safe_remote_path(path),
                '{} {}'.format(r.output or '', r.error or '').strip() or 'mkdir başarısız'))
        return r

    # ------------------------------------------------------------------
    # APK kurulum + HOME launcher + hizlandirma (v8: AppControl/tvboxtools)
    # ------------------------------------------------------------------
    def install_apk(self, target, local_path, reinstall=True, grant_perms=False,
                    allow_downgrade=False, timeout=120, cancel_check=None):
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
        if grant_perms:
            args.append('-g')
        if allow_downgrade:
            args.append('-d')
        args.append(lp)
        if cancel_check:
            cancel_check()
        r = self.run(['-s', target] + args, timeout=timeout)
        text = '{} {}'.format(r.output, r.error)
        if r.exit_code != 0 or not re.search(r'\bSuccess\b', text):
            raise AdbError('Kurulum başarısız ({}): {}'.format(
                local_path.rsplit('\\', 1)[-1].rsplit('/', 1)[-1],
                text.strip() or 'bilinmeyen hata'))
        return r

    def install_remote_apk(self, target, remote_path, reinstall=True,
                           grant_perms=False, allow_downgrade=False, timeout=180):
        """Cihaz üzerindeki bir APK dosyasını doğrudan kurar (pm install)."""
        rp = safe_remote_path(remote_path)
        if not rp.lower().endswith('.apk'):
            raise AdbError('Geçersiz uzak APK yolu: {!r}'.format(remote_path))
        args = ['pm', 'install']
        if reinstall:
            args.append('-r')
        if grant_perms:
            args.append('-g')
        if allow_downgrade:
            args.append('-d')
        args.append(_quoted_remote_path(rp))
        r = self.shell(target, *args, timeout=timeout)
        text = '{} {}'.format(r.output or '', r.error or '')
        if r.exit_code != 0 or not re.search(r'\bSuccess\b', text):
            raise AdbError('Cihazda kurulum başarısız ({}): {}'.format(
                remote_path.rsplit('/', 1)[-1], text.strip() or 'bilinmeyen hata'))
        return r

    def _bundletool_command(self):
        """Find a directly executable bundletool or a local bundletool JAR."""
        for name in ('bundletool', 'bundletool.exe'):
            path = shutil.which(name)
            if path and os.path.splitext(path)[1].lower() not in ('.bat', '.cmd'):
                return [path]

        java = shutil.which('java') or shutil.which('java.exe')
        if not java:
            return None
        import glob as _glob
        adb_path = getattr(self, 'adb_path', None)
        directories = {_base_dir()}
        if adb_path:
            directories.add(os.path.dirname(os.path.abspath(adb_path)))
        jars = []
        for directory in directories:
            jars.extend(_glob.glob(os.path.join(directory, 'bundletool-all*.jar')))
            jars.extend(_glob.glob(os.path.join(directory, 'bundletool*.jar')))
        jars = sorted(set(jars), key=lambda path: os.path.getmtime(path), reverse=True)
        return [java, '-jar', jars[0]] if jars else None

    @staticmethod
    def _create_bundletool_job(process):
        if os.name != 'nt':
            return None
        import ctypes
        from ctypes import wintypes

        class _JobLimits(ctypes.Structure):
            _fields_ = [
                ('per_process_user_time', ctypes.c_longlong),
                ('per_job_user_time', ctypes.c_longlong),
                ('limit_flags', wintypes.DWORD),
                ('minimum_working_set', ctypes.c_size_t),
                ('maximum_working_set', ctypes.c_size_t),
                ('active_process_limit', wintypes.DWORD),
                ('affinity', ctypes.c_size_t),
                ('priority_class', wintypes.DWORD),
                ('scheduling_class', wintypes.DWORD),
            ]

        class _JobAccounting(ctypes.Structure):
            _fields_ = [
                ('total_user_time', ctypes.c_longlong),
                ('total_kernel_time', ctypes.c_longlong),
                ('period_user_time', ctypes.c_longlong),
                ('period_kernel_time', ctypes.c_longlong),
                ('page_faults', wintypes.DWORD),
                ('total_processes', wintypes.DWORD),
                ('active_processes', wintypes.DWORD),
                ('terminated_processes', wintypes.DWORD),
            ]

        class _IoCounters(ctypes.Structure):
            _fields_ = [
                ('read_operations', ctypes.c_ulonglong),
                ('write_operations', ctypes.c_ulonglong),
                ('other_operations', ctypes.c_ulonglong),
                ('read_transfer', ctypes.c_ulonglong),
                ('write_transfer', ctypes.c_ulonglong),
                ('other_transfer', ctypes.c_ulonglong),
            ]

        class _ExtendedJobLimits(ctypes.Structure):
            _fields_ = [
                ('basic', _JobLimits),
                ('io', _IoCounters),
                ('process_memory_limit', ctypes.c_size_t),
                ('job_memory_limit', ctypes.c_size_t),
                ('peak_process_memory_used', ctypes.c_size_t),
                ('peak_job_memory_used', ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD)]
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise OSError(ctypes.get_last_error(), 'Bundletool iş nesnesi oluşturulamadı.')
        limits = _ExtendedJobLimits()
        limits.basic.limit_flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
                handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(handle)
            raise OSError(error, 'Bundletool iş nesnesi yapılandırılamadı.')
        if not kernel32.AssignProcessToJobObject(
                handle, wintypes.HANDLE(int(process._handle))):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(handle)
            raise OSError(error, 'Bundletool süreci iş nesnesine atanamadı.')
        return kernel32, handle, _JobAccounting

    @staticmethod
    def _resume_bundletool_process(process):
        if os.name != 'nt':
            return
        import ctypes
        from ctypes import wintypes

        class _ThreadEntry(ctypes.Structure):
            _fields_ = [
                ('size', wintypes.DWORD),
                ('usage', wintypes.DWORD),
                ('thread_id', wintypes.DWORD),
                ('owner_process_id', wintypes.DWORD),
                ('base_priority', ctypes.c_long),
                ('delta_priority', ctypes.c_long),
                ('flags', wintypes.DWORD),
            ]

        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)]
        kernel32.Thread32First.restype = wintypes.BOOL
        kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)]
        kernel32.Thread32Next.restype = wintypes.BOOL
        kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenThread.restype = wintypes.HANDLE
        kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel32.ResumeThread.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000004, 0)  # SNAPTHREAD
        invalid_handle = ctypes.c_void_p(-1).value
        if not snapshot or snapshot == invalid_handle:
            raise OSError(ctypes.get_last_error(), 'Bundletool iş parçacığı bulunamadı.')
        try:
            entry = _ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            found = kernel32.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.owner_process_id == process.pid:
                    thread = kernel32.OpenThread(0x0002, False, entry.thread_id)
                    if thread:
                        try:
                            if kernel32.ResumeThread(thread) != 0xFFFFFFFF:
                                return
                        finally:
                            kernel32.CloseHandle(thread)
                found = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        raise OSError('Bundletool başlatma iş parçacığı sürdürülemedi.')

    @staticmethod
    def _bundletool_job_process_count(job):
        if not job:
            return None
        import ctypes
        kernel32, handle, accounting_type = job
        info = accounting_type()
        if not kernel32.QueryInformationJobObject(
                handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
            raise OSError(ctypes.get_last_error(), 'Bundletool iş nesnesi okunamadı.')
        return int(info.active_processes)

    @staticmethod
    def _close_bundletool_job(job):
        if job:
            job[0].CloseHandle(job[1])

    @staticmethod
    def _stop_bundletool_process_tree(process, job=None, force=False):
        if os.name == 'nt':
            if job:
                try:
                    if job[0].TerminateJobObject(job[1], 1):
                        return
                except OSError:
                    pass
            taskkill = (shutil.which('taskkill.exe') or shutil.which('taskkill') or
                        os.path.join(os.environ.get('SystemRoot', r'C:\Windows'),
                                     'System32', 'taskkill.exe'))
            if os.path.isfile(taskkill):
                try:
                    subprocess.run(
                        [taskkill, '/PID', str(process.pid), '/T', '/F'],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=3, check=False, creationflags=CREATE_NO_WINDOW)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
            except OSError:
                pass
        if process.poll() is None:
            try:
                process.kill() if force else process.terminate()
            except OSError:
                pass

    @staticmethod
    def _run_bundletool(command, timeout, operation, cancel_check=None):
        import tempfile as _tempfile
        process = None
        job = None
        try:
            if cancel_check:
                cancel_check()
            deadline = (None if timeout is None else
                        time.monotonic() + max(0.0, float(timeout)))
            with _tempfile.TemporaryFile() as stdout_file, \
                    _tempfile.TemporaryFile() as stderr_file:
                creation = {}
                if os.name == 'nt':
                    creation['creationflags'] = (
                        CREATE_NO_WINDOW | getattr(subprocess, 'CREATE_SUSPENDED', 0x00000004))
                else:
                    creation['start_new_session'] = True
                process = subprocess.Popen(
                    command, stdout=stdout_file, stderr=stderr_file,
                    shell=False, **creation)
                try:
                    if os.name == 'nt':
                        job = AdbEngine._create_bundletool_job(process)
                        AdbEngine._resume_bundletool_process(process)
                    while True:
                        if cancel_check:
                            cancel_check()
                        remaining = (None if deadline is None else
                                     deadline - time.monotonic())
                        if remaining is not None and remaining <= 0:
                            raise subprocess.TimeoutExpired(command, timeout)
                        returncode = process.poll()
                        active = AdbEngine._bundletool_job_process_count(job)
                        if returncode is not None and (active is None or active == 0):
                            break
                        time.sleep(0.2 if remaining is None else min(0.2, remaining))
                    process.wait()

                    def read_output(stream, limit=131072):
                        stream.seek(0, os.SEEK_END)
                        size = stream.tell()
                        stream.seek(max(0, size - limit))
                        return stream.read(limit).decode('utf-8', 'replace')

                    return subprocess.CompletedProcess(
                        command, process.returncode,
                        read_output(stdout_file), read_output(stderr_file))
                except Exception:
                    AdbEngine._stop_bundletool_process_tree(process, job)
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
                    AdbEngine._stop_bundletool_process_tree(process, job, force=True)
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
                    raise
        except subprocess.TimeoutExpired as exc:
            raise AdbError('Bundletool {} zaman aşımına uğradı.'.format(operation)) from exc
        except OSError as exc:
            raise AdbError('Bundletool {} çalıştırılamadı: {}'.format(operation, exc)) from exc
        finally:
            AdbEngine._close_bundletool_job(job)

    @staticmethod
    def _copy_archive_entry(source, destination, cancel_check=None):
        while True:
            if cancel_check:
                cancel_check()
            chunk = source.read(1024 * 1024)
            if not chunk:
                return
            destination.write(chunk)

    def _install_apks_archive(self, target, archive_path, timeout, reinstall=True,
                              grant_perms=False, allow_downgrade=False,
                              cancel_check=None):
        """Install only the APKs bundletool selects for this exact device."""
        import tempfile as _tempfile
        prefix = self._bundletool_command()
        adb_path = getattr(self, 'adb_path', None)
        if not prefix or not adb_path:
            return None

        serial = str(target or '').strip()
        if not serial or any(ord(char) < 32 for char in serial):
            raise AdbError('Cihaz hedefi bundletool için geçersiz.')
        with _tempfile.TemporaryDirectory(prefix='mibox-apks-') as folder:
            spec_path = os.path.join(folder, 'device-spec.json')
            selected_dir = os.path.join(folder, 'selected')
            os.makedirs(selected_dir)
            result = self._run_bundletool(
                prefix + ['get-device-spec', '--adb=' + adb_path,
                          '--device-id=' + serial, '--output=' + spec_path],
                timeout, 'cihaz yapılandırmasını okuma', cancel_check)
            if result.returncode != 0 or not os.path.isfile(spec_path):
                detail = (result.stderr or result.stdout or 'cihaz yapılandırması alınamadı').strip()
                raise AdbError('Bundletool hedef cihaz {} yapılandırmasını okuyamadı: {}'.format(
                    serial, detail[:300]))

            result = self._run_bundletool(
                prefix + ['extract-apks', '--apks=' + archive_path,
                          '--device-spec=' + spec_path, '--output-dir=' + selected_dir],
                timeout, 'cihaz APK varyantlarını seçme', cancel_check)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or 'uyumlu APK seçilemedi').strip()
                raise AdbError('Bundletool {} için uyumlu APK seçemedi: {}'.format(
                    serial, detail[:300]))

            selected = []
            for root, _dirs, names in os.walk(selected_dir):
                selected.extend(os.path.join(root, name) for name in names
                                if name.lower().endswith('.apk'))
            selected.sort()
            if not selected:
                raise AdbError('Bundletool {} için uyumlu APK bulamadı.'.format(serial))
            if cancel_check:
                cancel_check()
            if len(selected) == 1:
                return self.install_apk(
                    target, selected[0], reinstall=reinstall,
                    grant_perms=grant_perms, allow_downgrade=allow_downgrade,
                    timeout=timeout, cancel_check=cancel_check)
            return self.install_multiple(
                target, selected, reinstall=reinstall, grant_perms=grant_perms,
                allow_downgrade=allow_downgrade, timeout=timeout,
                cancel_check=cancel_check)

    def _install_universal_apks(self, target, archive_path, timeout, reinstall=True,
                                grant_perms=False, allow_downgrade=False,
                                cancel_check=None):
        """Use a single explicitly universal APK when bundletool is absent."""
        import zipfile
        import tempfile as _tempfile
        try:
            with zipfile.ZipFile(archive_path) as archive:
                members = [entry for entry in archive.infolist()
                           if not entry.is_dir()
                           and entry.filename.replace('\\', '/').rsplit('/', 1)[-1].lower()
                           == 'universal.apk']
                if len(members) != 1:
                    raise AdbError(
                        '.apks için Bundletool gerekli: {} cihazına uygun tek bir universal.apk '
                        'yok. Bundletool kurun veya hedef cihaz için hazırlanmış APK setini '
                        'seçin.'.format(target))
                entry = members[0]
                if entry.file_size <= 0 or entry.file_size > 2 * 1024 ** 3:
                    raise AdbError('Universal APK boyutu güvenli sınırların dışında.')
                if cancel_check:
                    cancel_check()
                with _tempfile.TemporaryDirectory(prefix='mibox-apks-') as folder:
                    path = os.path.join(folder, 'universal.apk')
                    with archive.open(entry) as source, open(path, 'wb') as dest:
                        self._copy_archive_entry(source, dest, cancel_check)
                    if cancel_check:
                        cancel_check()
                    return self.install_apk(
                        target, path, reinstall=reinstall, grant_perms=grant_perms,
                        allow_downgrade=allow_downgrade, timeout=timeout,
                        cancel_check=cancel_check)
        except AdbError:
            raise
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            raise AdbError('.apks arşivi açılamadı: {}'.format(exc)) from exc

    def install_multiple(self, target, apk_path, reinstall=True,
                         grant_perms=False, allow_downgrade=False, timeout=180,
                         cancel_check=None):
        """Install a flat APK set (adb install-multiple) or .apkm/.xapk archive.

        apk_path tek tek dosya listesi, dizin (icindeki *.apk'lar) veya
        tek dosya olabilir. .apks içinden hedefe uygun varyant bundletool ile
        seçilir; bundletool yoksa yalnızca universal.apk güvenle kullanılabilir.
        """
        import glob as _glob
        import os as _os
        if cancel_check:
            cancel_check()
        if isinstance(apk_path, str) and apk_path.lower().endswith('.apks'):
            if not _os.path.isfile(apk_path):
                raise AdbError('.apks arşivi bulunamadı: ' + apk_path)
            result = self._install_apks_archive(
                target, apk_path, timeout, reinstall=reinstall,
                grant_perms=grant_perms, allow_downgrade=allow_downgrade,
                cancel_check=cancel_check)
            if result is not None:
                return result
            return self._install_universal_apks(
                target, apk_path, timeout, reinstall=reinstall,
                grant_perms=grant_perms, allow_downgrade=allow_downgrade,
                cancel_check=cancel_check)
        if isinstance(apk_path, str) and apk_path.lower().endswith(('.apkm', '.xapk')):
            import zipfile
            import tempfile
            import shutil
            try:
                with zipfile.ZipFile(apk_path) as archive:
                    members = [entry for entry in archive.infolist()
                               if not entry.is_dir() and entry.filename.lower().endswith('.apk')]
                    if not members:
                        raise AdbError('Arşivde kurulacak APK bulunamadı: ' + apk_path)
                    if len(members) > 512 or any(m.file_size > 2 * 1024 ** 3 for m in members) or sum(m.file_size for m in members) > 4 * 1024 ** 3:
                        raise AdbError('APK arşivi boyut veya dosya sayısı sınırını aşıyor.')
                    with tempfile.TemporaryDirectory(prefix='mibox-apks-') as folder:
                        extracted = []
                        for index, entry in enumerate(members):
                            if cancel_check:
                                cancel_check()
                            # Use generated names; archive paths never control extraction paths.
                            path = _os.path.join(folder, 'split-{:04d}.apk'.format(index))
                            with archive.open(entry) as source, open(path, 'wb') as dest:
                                self._copy_archive_entry(source, dest, cancel_check)
                            extracted.append(path)
                        if cancel_check:
                            cancel_check()
                        return self.install_multiple(target, extracted, reinstall=reinstall,
                                                    grant_perms=grant_perms, allow_downgrade=allow_downgrade,
                                                    timeout=timeout, cancel_check=cancel_check)
            except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
                raise AdbError('APK arşivi açılamadı: {}'.format(exc)) from exc
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
        if cancel_check:
            cancel_check()
        args = ['install-multiple']
        if reinstall:
            args.append('-r')
        if grant_perms:
            args.append('-g')
        if allow_downgrade:
            args.append('-d')
        args.extend(files)
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
        if home_pkg_of(cur) == want:
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
        if home_pkg_of(cur2) == want:
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
                value = (r.output or '').strip()
                if (r.exit_code != 0 or not re.fullmatch(r'(?:\d+(?:\.\d*)?|\.\d+)', value)
                        or re.search(r'\b(error|failed|exception|denied)\b',
                                     r.error or '', re.I)):
                    out[key] = '?'
                else:
                    out[key] = value
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
        keys = ('window_animation_scale', 'transition_animation_scale',
                'animator_duration_scale')
        numeric = r'(?:\d+(?:\.\d*)?|\.\d+)'
        previous = self.animator_scales(target, timeout=timeout)
        unknown = [key for key in keys
                   if not re.fullmatch(numeric, previous.get(key, ''))]
        if unknown:
            raise AdbError('Önceki animasyon ölçeği okunamadı: {}'.format(
                ', '.join(unknown)))

        expected = float(val)
        attempted = []
        try:
            for key in keys:
                # Include the key even when the command itself reports failure:
                # a failed settings command may still have changed its value.
                attempted.append(key)
                result = self.shell(target, 'settings', 'put', 'global', key, val,
                                    timeout=timeout)
                text = '{} {}'.format(result.output or '', result.error or '').strip()
                if result.exit_code != 0 or re.search(
                        r'\b(error|failed|exception|denied|not allowed)\b', text, re.I):
                    raise AdbError('Animasyon ölçeği yazılamadı ({}): {}'.format(
                        key, text or 'settings put başarısız'))

            # dogrula
            cur = self.animator_scales(target)
            bad = [key for key in keys
                   if not re.fullmatch(numeric, cur.get(key, ''))
                   or float(cur[key]) != expected]
            if bad:
                raise AdbError('Doğrulama başarısız: {}'.format(', '.join(bad)))
        except Exception as original:
            rollback_errors = []
            for key in reversed(attempted):
                try:
                    result = self.shell(target, 'settings', 'put', 'global', key,
                                        previous[key], timeout=timeout)
                    text = '{} {}'.format(result.output or '', result.error or '').strip()
                    if result.exit_code != 0 or re.search(
                            r'\b(error|failed|exception|denied|not allowed)\b',
                            text, re.I):
                        rollback_errors.append('{}: {}'.format(
                            key, text or 'settings put başarısız'))
                except Exception as rollback_error:
                    rollback_errors.append('{}: {}'.format(key, rollback_error))

            if attempted:
                try:
                    restored = self.animator_scales(target)
                    bad = [key for key in attempted
                           if not re.fullmatch(numeric, restored.get(key, ''))
                           or float(restored[key]) != float(previous[key])]
                    if bad:
                        rollback_errors.append(
                            'geri alma doğrulaması başarısız: {}'.format(', '.join(bad)))
                except Exception as verification_error:
                    rollback_errors.append(
                        'geri alma doğrulaması okunamadı: {}'.format(verification_error))

            message = 'Animasyon ölçeği işlemi başarısız: {}'.format(original)
            if rollback_errors:
                message += '; geri alma hataları: {}'.format('; '.join(rollback_errors))
            raise AdbError(message) from original

    def storage_top(self, target, limit=15, timeout=60):
        """En çok yer kaplayan dizinler (GB eşiği üstü du taraması)."""
        errors = []
        for base in ('/sdcard', '/data/media/0'):
            try:
                r = self.shell(target, 'du', '-sk', base + '/*', timeout=timeout)
            except AdbError as exc:
                errors.append(str(exc))
                continue
            if r.exit_code != 0 or (r.error or '').strip():
                errors.append((r.error or r.output or 'du başarısız').strip())
                continue
            out = []
            malformed = []
            for line in (r.output or '').splitlines():
                if not line.strip():
                    continue
                m = re.match(r'\s*(\d+)\s+(.+)', line)
                if m:
                    out.append({'path': m.group(2).strip(), 'kb': int(m.group(1))})
                else:
                    malformed.append(line[:160])
            if malformed:
                errors.append('du çıktısı çözümlenemedi: {}'.format(
                    '; '.join(malformed[:3])))
                continue
            out.sort(key=lambda e: e['kb'], reverse=True)
            return out[:limit]
        raise AdbError('Depolama taraması tamamlanamadı: {}'.format(
            '; '.join(errors) or 'kullanılabilir depolama yolu bulunamadı'))

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
        return self.uninstall_user(target, pkg, user_id=user_id)

    def is_uninstalled_for_user_id(self, target, pkg, user_id, timeout=10):
        return self.is_uninstalled_for_user(
            target, pkg, timeout=timeout, user_id=user_id)

    def autorun_receivers(self, target, timeout=40):
        """BOOT_COMPLETED dinleyen paketler: {pkg: [component, ...]}.

        Yöntem: 'cmd package query-receivers' önce denenir (hızlı),
        desteklenmiyorsa dumpsys package çıktısı taranır (yavaş ama evrensel).
        """
        found = {}
        try:
            r = self.shell(target, 'cmd', 'package', 'query-receivers',
                           '--brief', '-a', 'android.intent.action.BOOT_COMPLETED',
                           timeout=timeout)
            for line in (r.output or '').splitlines():
                line = line.strip()
                component = re.fullmatch(
                    r'([A-Za-z]\w*(?:\.[A-Za-z]\w*)+)/((?:\.[\w$]+)+|[A-Za-z]\w*(?:\.[\w$]+)+)', line)
                if component:
                    pkg = component.group(1)
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

    def display_details(self, target, timeout=15):
        """Ayrintili ekran bilgisi: physical/override size, physical/override density, overscan, fps, sink_name."""
        out = {
            'physical_width': 1920,
            'physical_height': 1080,
            'override_width': None,
            'override_height': None,
            'width': 1920,
            'height': 1080,
            'physical_density': 320,
            'override_density': None,
            'density': 320,
            'fps': 60.0,
            'overscan': None,
            'sink_name': '',
            'screen_str': '1920x1080 @ 60Hz',
            'read_errors': [],
        }
        try:
            result = self.shell(target, 'wm', 'size', timeout=timeout)
            if result.exit_code != 0:
                raise AdbError(result.error or result.output or 'wm size okunamadı')
            size_out = (result.output or '').strip()
            m_phys = re.search(r'Physical size:\s*(\d+)x(\d+)', size_out)
            if m_phys:
                out['physical_width'] = int(m_phys.group(1))
                out['physical_height'] = int(m_phys.group(2))
                out['width'] = out['physical_width']
                out['height'] = out['physical_height']
            else:
                m_gen = re.search(r'size:\s*(\d+)x(\d+)', size_out)
                if m_gen:
                    out['physical_width'] = int(m_gen.group(1))
                    out['physical_height'] = int(m_gen.group(2))
                    out['width'] = out['physical_width']
                    out['height'] = out['physical_height']
            m_over = re.search(r'Override size:\s*(\d+)x(\d+)', size_out)
            if m_over:
                out['override_width'] = int(m_over.group(1))
                out['override_height'] = int(m_over.group(2))
                out['width'] = out['override_width']
                out['height'] = out['override_height']
            if not m_phys and not m_gen:
                raise AdbError('wm size çıktısı çözümlenemedi')
        except AdbError:
            out['read_errors'].append('size')

        try:
            result = self.shell(target, 'wm', 'density', timeout=timeout)
            if result.exit_code != 0:
                raise AdbError(result.error or result.output or 'wm density okunamadı')
            dens_out = (result.output or '').strip()
            m_phys = re.search(r'Physical density:\s*(\d+)', dens_out)
            if m_phys:
                out['physical_density'] = int(m_phys.group(1))
                out['density'] = out['physical_density']
            else:
                m_gen = re.search(r'density:\s*(\d+)', dens_out)
                if m_gen:
                    out['physical_density'] = int(m_gen.group(1))
                    out['density'] = out['physical_density']
            m_over = re.search(r'Override density:\s*(\d+)', dens_out)
            if m_over:
                out['override_density'] = int(m_over.group(1))
                out['density'] = out['override_density']
            if not m_phys and not m_gen:
                raise AdbError('wm density çıktısı çözümlenemedi')
        except AdbError:
            out['read_errors'].append('density')

        try:
            result = self.shell(target, 'wm', 'overscan', timeout=timeout)
            if result.exit_code == 0:
                overscan_out = (result.output or '').strip()
                m_ov = re.search(r'overscan:\s*(-?\d+),(-?\d+),(-?\d+),(-?\d+)', overscan_out, re.I)
                if m_ov:
                    out['overscan'] = [int(m_ov.group(i)) for i in range(1, 5)]
        except Exception:
            pass

        try:
            disp_out = (self.shell(target, 'dumpsys', 'display', timeout=timeout).output or '')
            m = re.search(r'(?:renderFrameRate|fps[=:])\s*([\d\.]+)', disp_out)
            if m:
                out['fps'] = round(float(m.group(1)), 1)
            m_name = re.search(r'DeviceProductInfo\{name=([^,\}]+)', disp_out)
            if m_name:
                out['sink_name'] = m_name.group(1).strip()
        except AdbError:
            pass

        fps_val = int(out['fps']) if out['fps'].is_integer() else out['fps']
        screen_parts = ['{}x{} @ {}Hz ({} DPI)'.format(
            out['width'], out['height'], fps_val, out['density']
        )]
        if out['override_width'] or out['override_density']:
            screen_parts.append('(Özel Ölçek)')
        if out['sink_name']:
            screen_parts.append('· ' + out['sink_name'])
        out['screen_str'] = ' '.join(screen_parts)
        return out

    def display_info(self, target, timeout=15):
        """Ekran cozunurlugu, yenileme hizi (Hz), yogunluk (DPI) ve bagli ekran bilgisi."""
        return self.display_details(target, timeout=timeout)

    def set_display_size(self, target, width, height, timeout=15):
        """wm size <width>x<height> uygular."""
        if not (isinstance(width, int) and isinstance(height, int) and 320 <= width <= 7680 and 240 <= height <= 4320):
            raise AdbError('Geçersiz çözünürlük boyutları.')
        res = self.shell(target, 'wm', 'size', f'{width}x{height}', timeout=timeout)
        if res.exit_code != 0:
            raise AdbError('Çözünürlük uygulanamadı: ' + (res.output or ''))
        return self.display_details(target, timeout=timeout)

    def reset_display_size(self, target, timeout=15):
        """wm size reset ile fabrika cozunurlugune doner."""
        res = self.shell(target, 'wm', 'size', 'reset', timeout=timeout)
        if res.exit_code != 0:
            raise AdbError('Çözünürlük sıfırlanamadı: ' + (res.output or ''))
        return self.display_details(target, timeout=timeout)

    def set_display_density(self, target, density, timeout=15):
        """wm density <val> uygular."""
        if not (isinstance(density, int) and 72 <= density <= 1000):
            raise AdbError('Geçersiz DPI değeri (72-1000 arası olmalı).')
        res = self.shell(target, 'wm', 'density', str(density), timeout=timeout)
        if res.exit_code != 0:
            raise AdbError('DPI uygulanamadı: ' + (res.output or ''))
        return self.display_details(target, timeout=timeout)

    def reset_display_density(self, target, timeout=15):
        """wm density reset ile fabrika DPI degerine doner."""
        res = self.shell(target, 'wm', 'density', 'reset', timeout=timeout)
        if res.exit_code != 0:
            raise AdbError('DPI sıfırlanamadı: ' + (res.output or ''))
        return self.display_details(target, timeout=timeout)

    def set_display_overscan(self, target, left, top, right, bottom, timeout=15):
        """wm overscan left,top,right,bottom uygular (Android 10 ve alti)."""
        for v in (left, top, right, bottom):
            if not (isinstance(v, int) and -300 <= v <= 300):
                raise AdbError('Geçersiz overscan değeri (-300 ile +300 arası olmalı).')
        res = self.shell(target, 'wm', 'overscan', f'{left},{top},{right},{bottom}', timeout=timeout)
        if res.exit_code != 0:
            raise AdbError('Overscan uygulanamadı (cihaz desteklemiyor olabilir): ' + (res.output or ''))
        return self.display_details(target, timeout=timeout)

    def reset_display_overscan(self, target, timeout=15):
        """wm overscan reset ile kenar bosluklarini sifirlar."""
        res = self.shell(target, 'wm', 'overscan', 'reset', timeout=timeout)
        if res.exit_code != 0:
            raise AdbError('Overscan sıfırlanamadı: ' + (res.output or ''))
        return self.display_details(target, timeout=timeout)

    def network_diagnostics(self, target, timeout=15):
        """Cihazin WiFi, yerel IP, ag gecidi (gateway) ve erisim sagligini olcer."""
        diag = {
            'target': target,
            'interface': 'wlan0',
            'ip': '—',
            'gateway': '—',
            'ssid': '—',
            'rssi': None,
            'signal_pct': 0,
            'signal_label': 'Bilinmiyor',
            'link_speed': '—',
            'frequency': '—',
            'gateway_ping_ms': None,
            'packet_loss_pct': 0,
            'health_rating': 'İyi',
            'advice': 'Ağ bağlantısı normal görünüyor.',
        }
        # 1. IP ve Gateway bilgisi (ip route & ip addr)
        try:
            route_out = (self.shell(target, 'ip', 'route', timeout=timeout).output or '')
            m_gw = re.search(r'default\s+via\s+([0-9\.]+)\s+dev\s+([a-zA-Z0-9_]+)', route_out)
            if not m_gw:
                # Modern Android (Android 11-14 policy routing tables)
                route_all = (self.shell(target, 'ip', 'route', 'show', 'table', 'all', timeout=timeout).output or '')
                m_gw = re.search(r'default\s+via\s+([0-9\.]+)\s+dev\s+([a-zA-Z0-9_]+)', route_all)
            if m_gw:
                diag['gateway'] = m_gw.group(1)
                diag['interface'] = m_gw.group(2)
        except AdbError:
            pass

        try:
            addr_out = (self.shell(target, 'ip', '-o', '-4', 'addr', 'show', diag['interface'], timeout=timeout).output or '')
            m_ip = re.search(r'inet\s+([0-9\.]+)/(\d+)', addr_out)
            if m_ip:
                diag['ip'] = m_ip.group(1)
        except AdbError:
            pass

        # 2. WiFi Sinyal ve Detaylari (dumpsys wifi)
        if 'wlan' in diag['interface']:
            try:
                wifi_out = (self.shell(target, 'dumpsys', 'wifi', timeout=timeout).output or '')
                m_ssid = re.search(r'mWifiInfo\s+SSID:\s*"?([^",\r\n]+)"?', wifi_out)
                if not m_ssid:
                    m_ssid = re.search(r'SSID:\s*"?([^",\r\n]+)"?', wifi_out)
                if m_ssid:
                    diag['ssid'] = m_ssid.group(1).strip()

                m_rssi = re.search(r'RSSI:\s*(-?\d+)', wifi_out)
                if m_rssi:
                    rssi = int(m_rssi.group(1))
                    diag['rssi'] = rssi
                    pct = max(0, min(100, int(2 * (rssi + 100))))
                    diag['signal_pct'] = pct
                    if rssi >= -60:
                        diag['signal_label'] = f'Mükemmel ({rssi} dBm)'
                    elif rssi >= -70:
                        diag['signal_label'] = f'İyi ({rssi} dBm)'
                    elif rssi >= -80:
                        diag['signal_label'] = f'Orta / Zayıf ({rssi} dBm)'
                    else:
                        diag['signal_label'] = f'Çok Zayıf ({rssi} dBm)'

                m_spd = re.search(r'(?:Link speed|txLinkSpeedMbps):\s*(\d+)\s*(?:Mbps)?', wifi_out, re.I)
                if m_spd:
                    diag['link_speed'] = m_spd.group(1) + ' Mbps'

                m_freq = re.search(r'(?:Frequency|mFrequency):\s*(\d+)\s*MHz', wifi_out, re.I)
                if m_freq:
                    freq = int(m_freq.group(1))
                    band = '5 GHz' if freq >= 4900 else '2.4 GHz'
                    diag['frequency'] = f'{band} ({freq} MHz)'
            except AdbError:
                pass
        else:
            diag['ssid'] = 'Kablolu Bağlantı (Ethernet)'
            diag['signal_pct'] = 100
            diag['signal_label'] = 'Kablolu (Mükemmel)'

        # 3. TV -> Gateway Ping & Packet Loss
        if diag['gateway'] != '—':
            try:
                ping_out = (self.shell(target, 'ping', '-c', '3', '-W', '2', diag['gateway'], timeout=timeout).output or '')
                m_loss = re.search(r'(\d+)%\s+packet\s+loss', ping_out)
                if m_loss:
                    diag['packet_loss_pct'] = int(m_loss.group(1))
                m_rtt = re.search(r'rtt\s+min/avg/max/mdev\s*=\s*[\d\.]+/([\d\.]+)/', ping_out)
                if m_rtt:
                    diag['gateway_ping_ms'] = round(float(m_rtt.group(1)), 1)
            except AdbError:
                pass

        # 4. Teşhis Analizi ve Tavsiye
        if diag['packet_loss_pct'] > 0:
            diag['health_rating'] = 'Kritik / Paket Kaybı Var'
            diag['advice'] = f"TV ile modem arasında %{diag['packet_loss_pct']} paket kaybı tespit edildi! Wi-Fi paraziti veya sinyal zayıflığı video akışlarında donmaya yol açabilir."
        elif diag['rssi'] is not None and diag['rssi'] < -80:
            diag['health_rating'] = 'Zayıf Sinyal'
            diag['advice'] = f"Wi-Fi sinyali çok zayıf ({diag['rssi']} dBm). Mi Box’ı modeme yaklaştırın veya 5GHz kanalını kontrol edin."
        elif diag['gateway_ping_ms'] is not None and diag['gateway_ping_ms'] > 35:
            diag['health_rating'] = 'Yüksek Gecikme'
            diag['advice'] = f"Modeme ping gecikmesi yüksek ({diag['gateway_ping_ms']} ms). Ağ trafiği yoğun veya kablosuz kanal parazitli olabilir."
        else:
            diag['health_rating'] = 'Mükemmel'
            diag['advice'] = 'Ağ ve sinyal durumu gayet iyi. 4K HDR yayın ve akıcı oynatma için uygundur.'

        return diag

    def cpu_info(self, target, timeout=15):
        """Islemci SoC modeli, mimari (ABI), cekirdek sayisi ve sicaklik."""
        out = {
            'abi': self.getprop(target, 'ro.product.cpu.abi') or '?',
            'soc': self.getprop(target, 'ro.soc.model') or self.getprop(target, 'ro.board.platform') or '?',
            'cores': 4,
            'temp': '?',
        }
        try:
            cpu_out = self.shell(target, 'cat', '/proc/cpuinfo', timeout=timeout).output or ''
            cores = len(re.findall(r'(?m)^processor\s*:', cpu_out))
            if cores > 0:
                out['cores'] = cores
            m_hw = re.search(r'(?m)^Hardware\s*:\s*(.+)$', cpu_out)
            if m_hw and out['soc'] == '?':
                out['soc'] = m_hw.group(1).strip()
        except AdbError:
            pass

        # 1. Modern Android HAL sıcaklık tespiti (dumpsys thermalservice)
        try:
            therm_out = self.shell(target, 'dumpsys', 'thermalservice', timeout=5).output or ''
            m_t = re.search(r'mValue=([\d\.]+)', therm_out)
            if m_t:
                deg = round(float(m_t.group(1)), 1)
                if 10 <= deg <= 120:
                    out['temp'] = '{}°C'.format(deg)
        except Exception:
            pass

        # 2. Sysfs fallback
        if out['temp'] == '?':
            for zone in ('/sys/class/thermal/thermal_zone0/temp',
                         '/sys/devices/virtual/thermal/thermal_zone0/temp'):
                try:
                    r = self.shell(target, 'cat', zone, timeout=5)
                    val = (r.output or '').strip()
                    if val.isdigit():
                        num = int(val)
                        deg = round(num / 1000.0 if num > 200 else float(num), 1)
                        out['temp'] = '{}°C'.format(deg)
                        break
                except AdbError:
                    pass
        return out

    def usb_storages(self, target, timeout=15):
        """Bagli harici USB bellek veya tasinabilir diskleri listeler."""
        storages = []
        try:
            r = self.shell(target, 'ls', '-1', '/storage', timeout=timeout)
            for line in (r.output or '').splitlines():
                name = line.strip()
                if not name or name in ('emulated', 'self', 'sdcard', 'knox-emulated'):
                    continue
                full_path = '/storage/' + name
                df_r = self.shell(target, 'df', full_path, timeout=5)
                lines = [l for l in (df_r.output or '').splitlines() if full_path in l]
                total_kb, avail_kb = 0, 0
                if lines:
                    parts = lines[-1].split()
                    if len(parts) >= 4:
                        try:
                            total_kb = int(parts[1])
                            avail_kb = int(parts[3])
                        except ValueError:
                            pass
                storages.append({
                    'name': 'USB Disk ({})'.format(name),
                    'path': full_path,
                    'total_kb': total_kb,
                    'avail_kb': avail_kb,
                })
        except AdbError:
            pass
        return storages

    def private_dns_get(self, target, timeout=10):
        """Ozel DNS (Private DNS) durumunu okur."""
        try:
            mode = (self.shell(target, 'settings', 'get', 'global', 'private_dns_mode', timeout=timeout).output or '').strip()
            spec = (self.shell(target, 'settings', 'get', 'global', 'private_dns_specifier', timeout=timeout).output or '').strip()
            if mode == 'null' or not mode:
                mode = 'off'
            if spec == 'null':
                spec = ''
            return {'mode': mode, 'specifier': spec}
        except AdbError:
            return {'mode': 'off', 'specifier': ''}

    def private_dns_set(self, target, mode, specifier='', timeout=15):
        """Ozel DNS ayarini gunceller (off / opportunistic / hostname).
        AdGuard: mode='hostname', specifier='dns.adguard.com'
        Cloudflare: mode='hostname', specifier='1dot1dot1dot1.cloudflare-dns.com'
        """
        if mode not in ('off', 'opportunistic', 'hostname'):
            raise AdbError('Gecersiz DNS modu: {!r}'.format(mode))
        specifier = str(specifier or '').strip()
        if mode == 'hostname':
            label = r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
            hostname = specifier.rstrip('.')
            if (len(hostname) > 253 or len(hostname.split('.')) < 2
                    or not re.fullmatch(r'{}(?:\.{})+'.format(label, label), hostname)):
                raise AdbError('Özel DNS için geçerli bir sunucu adı girin (örn. dns.adguard.com).')
            specifier = hostname
        result = self.shell(
            target, 'settings', 'put', 'global', 'private_dns_mode', mode,
            timeout=timeout)
        if result.exit_code != 0:
            detail = (result.error or result.output or 'settings put başarısız').strip()
            raise AdbError('Özel DNS modu ayarlanamadı: {}'.format(detail[:300]))
        if mode == 'hostname':
            result = self.shell(
                target, 'settings', 'put', 'global', 'private_dns_specifier',
                specifier.strip(), timeout=timeout)
            if result.exit_code != 0:
                detail = (result.error or result.output or 'settings put başarısız').strip()
                raise AdbError('Özel DNS sunucusu ayarlanamadı: {}'.format(detail[:300]))
        elif mode == 'off':
            result = self.shell(
                target, 'settings', 'delete', 'global', 'private_dns_specifier',
                timeout=timeout)
            if result.exit_code != 0:
                detail = (result.error or result.output or 'settings delete başarısız').strip()
                raise AdbError('Özel DNS sunucusu silinemedi: {}'.format(detail[:300]))

        mode_result = self.shell(
            target, 'settings', 'get', 'global', 'private_dns_mode', timeout=timeout)
        if mode_result.exit_code != 0:
            detail = (mode_result.error or mode_result.output or 'settings get başarısız').strip()
            raise AdbError('Özel DNS modu doğrulanamadı: {}'.format(detail[:300]))
        spec_result = self.shell(
            target, 'settings', 'get', 'global', 'private_dns_specifier', timeout=timeout)
        if spec_result.exit_code != 0:
            detail = (spec_result.error or spec_result.output or 'settings get başarısız').strip()
            raise AdbError('Özel DNS sunucusu doğrulanamadı: {}'.format(detail[:300]))

        applied_mode = (mode_result.output or '').strip()
        applied_specifier = (spec_result.output or '').strip()
        if applied_mode == 'null' or not applied_mode:
            applied_mode = 'off'
        if applied_specifier == 'null':
            applied_specifier = ''
        expected_specifier = None
        if mode == 'off':
            expected_specifier = ''
        elif mode == 'hostname':
            expected_specifier = specifier
        if (applied_mode != mode
                or (expected_specifier is not None
                    and applied_specifier != expected_specifier)):
            raise AdbError(
                'Özel DNS ayarı uygulanmadı (istenen: mode={!r}, specifier={!r}; '
                'uygulanan: mode={!r}, specifier={!r}).'.format(
                    mode, expected_specifier, applied_mode, applied_specifier))
        return {'mode': applied_mode, 'specifier': applied_specifier}

    def quick_boost(self, target, timeout=40, check_cancel=None):
        """Tek tikla kapsamli sistem hizlandirma:
        1. Onbellekleri temizle (pm trim-caches)
        2. Arka plan sureclerini sonlandir (am kill-all)
        3. Animasyon olceklerini optimize et (0.5x)
        4. Bellek durumunu raporla
        """
        summary = []
        completed_steps = 0
        failed_steps = 0
        if check_cancel is not None:
            check_cancel()
        try:
            health_before = self.health(target, timeout=15)
            if not isinstance(health_before, dict):
                health_before = {}
        except Exception:
            health_before = {}

        if check_cancel is not None:
            check_cancel()
        try:
            self.trim_caches(target, timeout=20)
            summary.append('Uygulama onbellekleri temizlendi.')
            completed_steps += 1
        except Exception as e:
            summary.append('Onbellek temizleme: {}'.format(e))
            failed_steps += 1

        if check_cancel is not None:
            check_cancel()
        try:
            result = self.shell(target, 'am', 'kill-all', timeout=15)
            if not result.ok:
                error = '{} {}'.format(result.error or '', result.output or '').strip()
                raise AdbError(error or 'Arka plan süreçleri sonlandırılamadı.')
            summary.append('Arka plan bosta kalan surecler sonlandirildi.')
            completed_steps += 1
        except Exception as e:
            summary.append('Surec sonlandirma: {}'.format(e))
            failed_steps += 1

        if check_cancel is not None:
            check_cancel()
        try:
            self.set_animator_scales(target, '0.5', timeout=15)
            summary.append('Animasyon hizlari 0.5x (hizli) yapildi.')
            completed_steps += 1
        except Exception as e:
            summary.append('Animasyon olcekleri: {}'.format(e))
            failed_steps += 1

        if check_cancel is not None:
            check_cancel()
        try:
            health_after = self.health(target, timeout=15)
            if not isinstance(health_after, dict):
                health_after = {}
        except Exception:
            health_after = {}

        if check_cancel is not None:
            check_cancel()

        def valid_mem_available(health):
            total = health.get('mem_total_kb')
            available = health.get('mem_avail_kb')
            if (type(total) is int and total > 0
                    and type(available) is int and 0 <= available <= total):
                return available
            return None

        before_avail = valid_mem_available(health_before)
        after_avail = valid_mem_available(health_after)
        if before_avail is not None and after_avail is not None:
            diff_kb = after_avail - before_avail
            freed_mb = round(diff_kb / 1024.0, 1) if diff_kb > 0 else 0.0
        else:
            freed_mb = None

        return {
            'freed_mb': freed_mb,
            'summary': summary,
            'health_before': health_before,
            'health_after': health_after,
            'completed_steps': completed_steps,
            'failed_steps': failed_steps,
        }

    @staticmethod
    def _package_from_binary_manifest(data):
        """Read only the package attribute on a binary XML root manifest tag."""
        no_index = 0xFFFFFFFF
        data_size = len(data)
        max_manifest_size = 8 * 1024 * 1024
        max_string_count = 100_000
        if data_size > max_manifest_size:
            raise ValueError('Android manifest exceeds the size limit')

        def read_u16(offset, limit):
            if offset < 0 or offset + 2 > limit:
                raise ValueError('Truncated binary XML value')
            return int.from_bytes(data[offset:offset + 2], 'little')

        def read_u32(offset, limit):
            if offset < 0 or offset + 4 > limit:
                raise ValueError('Truncated binary XML value')
            return int.from_bytes(data[offset:offset + 4], 'little')

        def parse_string_pool(offset, chunk_size, header_size):
            if header_size != 28:
                raise ValueError('Unsupported binary XML string pool header')
            chunk_end = offset + chunk_size
            string_count = read_u32(offset + 8, chunk_end)
            style_count = read_u32(offset + 12, chunk_end)
            flags = read_u32(offset + 16, chunk_end)
            strings_start = read_u32(offset + 20, chunk_end)
            styles_start = read_u32(offset + 24, chunk_end)
            if flags & ~0x101:
                raise ValueError('Unsupported binary XML string pool flags')
            if string_count > max_string_count or style_count > max_string_count:
                raise ValueError('Binary XML string pool exceeds the entry limit')
            offsets_start = offset + header_size
            offsets_end = offsets_start + 4 * (string_count + style_count)
            if offsets_end > chunk_end or strings_start < offsets_end - offset:
                raise ValueError('Invalid binary XML string pool offsets')
            if strings_start > chunk_size:
                raise ValueError('Invalid binary XML string data offset')
            if style_count and not styles_start:
                raise ValueError('Missing binary XML style data')
            if styles_start and (styles_start < strings_start or styles_start > chunk_size):
                raise ValueError('Invalid binary XML style data offset')

            strings_end = offset + (styles_start or chunk_size)
            strings_base = offset + strings_start
            utf8 = bool(flags & 0x100)

            def read_length8(position):
                first = read_u16(position, strings_end) & 0xFF
                position += 1
                if first & 0x80:
                    second = read_u16(position, strings_end) & 0xFF
                    position += 1
                    return ((first & 0x7F) << 8) | second, position
                return first, position

            def read_length16(position):
                first = read_u16(position, strings_end)
                position += 2
                if first & 0x8000:
                    second = read_u16(position, strings_end)
                    position += 2
                    return ((first & 0x7FFF) << 16) | second, position
                return first, position

            strings = []
            decoded_by_offset = {}
            decoded_bytes = 0
            for index in range(string_count):
                relative = read_u32(offsets_start + index * 4, offsets_end)
                if relative in decoded_by_offset:
                    strings.append(decoded_by_offset[relative])
                    continue
                position = strings_base + relative
                if position < strings_base or position >= strings_end:
                    raise ValueError('Invalid binary XML string offset')
                if utf8:
                    utf16_length, position = read_length8(position)
                    byte_length, position = read_length8(position)
                    byte_end = position + byte_length
                    if byte_end >= strings_end or data[byte_end] != 0:
                        raise ValueError('Unterminated binary XML string')
                    decoded_bytes += byte_length
                    if decoded_bytes > max_manifest_size:
                        raise ValueError('Decoded binary XML strings exceed the size limit')
                    value = data[position:byte_end].decode('utf-8')
                    if len(value.encode('utf-16le')) // 2 != utf16_length:
                        raise ValueError('Invalid binary XML string length')
                else:
                    if position & 1:
                        raise ValueError('Misaligned binary XML UTF-16 string')
                    char_length, position = read_length16(position)
                    byte_end = position + char_length * 2
                    if byte_end + 2 > strings_end or data[byte_end:byte_end + 2] != b'\0\0':
                        raise ValueError('Unterminated binary XML string')
                    decoded_bytes += char_length * 2
                    if decoded_bytes > max_manifest_size:
                        raise ValueError('Decoded binary XML strings exceed the size limit')
                    value = data[position:byte_end].decode('utf-16le')
                if '\0' in value:
                    raise ValueError('Invalid binary XML string content')
                decoded_by_offset[relative] = value
                strings.append(value)

            if style_count:
                styles_base = offset + styles_start
                for index in range(style_count):
                    relative = read_u32(offsets_start + 4 * (string_count + index), chunk_end)
                    if relative != no_index and relative >= chunk_end - styles_base:
                        raise ValueError('Invalid binary XML style offset')

            return strings

        if data_size < 8:
            raise ValueError('Truncated binary XML document')
        if read_u16(0, data_size) != 0x0003:
            raise ValueError('Unsupported AndroidManifest.xml format')
        document_header_size = read_u16(2, data_size)
        document_size = read_u32(4, data_size)
        if document_header_size != 8 or document_size != data_size:
            raise ValueError('Invalid binary XML document bounds')

        strings = None
        resource_map_seen = False
        node_seen = False
        root_seen = False
        root_closed = False
        root_is_manifest = False
        root_package = ''
        root_package_count = 0
        element_stack = []
        namespace_stack = []
        offset = document_header_size

        def get_string(index, optional=False):
            if index == no_index and optional:
                return None
            if strings is None or index >= len(strings):
                raise ValueError('Invalid binary XML string reference')
            return strings[index]

        def check_node_header(chunk_offset, chunk_size, header_size):
            if header_size != 16 or chunk_size < 16:
                raise ValueError('Unsupported binary XML node header')
            get_string(read_u32(chunk_offset + 12, chunk_offset + chunk_size), optional=True)

        def check_namespace(uri):
            if uri is not None and uri not in (entry[1] for entry in namespace_stack):
                if uri != 'http://www.w3.org/XML/1998/namespace':
                    raise ValueError('Undeclared binary XML namespace')

        while offset < data_size:
            if offset + 8 > data_size:
                raise ValueError('Truncated binary XML chunk')
            chunk_type = read_u16(offset, data_size)
            header_size = read_u16(offset + 2, data_size)
            chunk_size = read_u32(offset + 4, data_size)
            if header_size < 8 or chunk_size < header_size or offset + chunk_size > data_size:
                raise ValueError('Invalid binary XML chunk bounds')
            chunk_end = offset + chunk_size

            if chunk_type == 0x0001:  # RES_STRING_POOL_TYPE
                if strings is not None or offset != document_header_size:
                    raise ValueError('Unexpected binary XML string pool')
                strings = parse_string_pool(offset, chunk_size, header_size)
            elif strings is None:
                raise ValueError('Binary XML string pool must be first')
            elif chunk_type == 0x0180:  # RES_XML_RESOURCE_MAP_TYPE
                if node_seen or resource_map_seen or header_size != 8 or (chunk_size - 8) % 4:
                    raise ValueError('Invalid binary XML resource map')
                resource_map_seen = True
            elif chunk_type in (0x0100, 0x0101):  # namespace start/end
                if root_closed and chunk_type == 0x0100:
                    raise ValueError('Namespace starts after the root element')
                node_seen = True
                if chunk_size != 24:
                    raise ValueError('Invalid binary XML namespace chunk')
                check_node_header(offset, chunk_size, header_size)
                prefix = get_string(read_u32(offset + 16, chunk_end), optional=True)
                uri = get_string(read_u32(offset + 20, chunk_end))
                if chunk_type == 0x0100:
                    if len(namespace_stack) >= 256:
                        raise ValueError('Binary XML namespace nesting is too deep')
                    namespace_stack.append((prefix, uri, len(element_stack)))
                elif (not namespace_stack or namespace_stack[-1] !=
                      (prefix, uri, len(element_stack))):
                    raise ValueError('Unbalanced binary XML namespace')
                else:
                    namespace_stack.pop()
            elif chunk_type == 0x0102:  # RES_XML_START_ELEMENT_TYPE
                node_seen = True
                if root_closed:
                    raise ValueError('Multiple binary XML root elements')
                check_node_header(offset, chunk_size, header_size)
                if chunk_size < 36:
                    raise ValueError('Truncated binary XML start element')
                namespace = get_string(read_u32(offset + 16, chunk_end), optional=True)
                name = get_string(read_u32(offset + 20, chunk_end))
                check_namespace(namespace)
                attribute_start = read_u16(offset + 24, chunk_end)
                attribute_size = read_u16(offset + 26, chunk_end)
                attribute_count = read_u16(offset + 28, chunk_end)
                id_index = read_u16(offset + 30, chunk_end)
                class_index = read_u16(offset + 32, chunk_end)
                style_index = read_u16(offset + 34, chunk_end)
                if (attribute_start < 20 or attribute_size < 20 or
                        attribute_start + attribute_count * attribute_size != chunk_size - 16 or
                        any(value > attribute_count for value in (id_index, class_index, style_index))):
                    raise ValueError('Invalid binary XML attributes')
                if not element_stack:
                    if root_seen:
                        raise ValueError('Multiple binary XML root elements')
                    root_seen = True
                    root_is_manifest = namespace is None and name == 'manifest'
                if len(element_stack) >= 256:
                    raise ValueError('Binary XML element nesting is too deep')
                package_candidates = []
                seen_attributes = set()
                attributes_offset = offset + 16 + attribute_start
                for index in range(attribute_count):
                    attribute_offset = attributes_offset + index * attribute_size
                    attribute_end = attribute_offset + attribute_size
                    attr_namespace = get_string(read_u32(attribute_offset, attribute_end), optional=True)
                    attr_name = get_string(read_u32(attribute_offset + 4, attribute_end))
                    attribute_key = (attr_namespace, attr_name)
                    if not attr_name or attribute_key in seen_attributes:
                        raise ValueError('Invalid or duplicate binary XML attribute')
                    seen_attributes.add(attribute_key)
                    raw_value = read_u32(attribute_offset + 8, attribute_end)
                    raw_string = get_string(raw_value, optional=True)
                    value_size = read_u16(attribute_offset + 12, attribute_end)
                    reserved = data[attribute_offset + 14]
                    value_type = data[attribute_offset + 15]
                    value_data = read_u32(attribute_offset + 16, attribute_end)
                    if value_size != 8 or reserved != 0 or value_type > 0x1F:
                        raise ValueError('Invalid binary XML attribute value')
                    if value_type == 0x03:
                        get_string(value_data)
                    check_namespace(attr_namespace)
                    if not element_stack and root_is_manifest and attr_namespace is None and attr_name == 'package':
                        root_package_count += 1
                        if value_type != 0x03:
                            raise ValueError('Manifest package attribute is not a string')
                        typed_string = get_string(value_data)
                        if raw_string is not None and raw_string != typed_string:
                            raise ValueError('Conflicting manifest package attribute values')
                        package_candidates.append(raw_string if raw_string is not None else typed_string)
                if not element_stack and root_is_manifest:
                    if root_package_count == 1 and len(package_candidates) == 1:
                        root_package = package_candidates[0]
                    else:
                        root_package = ''
                element_stack.append((namespace, name))
            elif chunk_type == 0x0103:  # RES_XML_END_ELEMENT_TYPE
                node_seen = True
                check_node_header(offset, chunk_size, header_size)
                if chunk_size != 24 or not element_stack:
                    raise ValueError('Invalid binary XML end element')
                namespace = get_string(read_u32(offset + 16, chunk_end), optional=True)
                name = get_string(read_u32(offset + 20, chunk_end))
                check_namespace(namespace)
                if element_stack.pop() != (namespace, name):
                    raise ValueError('Mismatched binary XML element')
                if not element_stack:
                    root_closed = True
            elif chunk_type == 0x0104:  # RES_XML_CDATA_TYPE
                node_seen = True
                check_node_header(offset, chunk_size, header_size)
                if chunk_size != 28 or root_closed or not element_stack:
                    raise ValueError('Invalid binary XML text node')
                get_string(read_u32(offset + 16, chunk_end))
                value_size = read_u16(offset + 20, chunk_end)
                reserved = data[offset + 22]
                value_type = data[offset + 23]
                value_data = read_u32(offset + 24, chunk_end)
                if value_size != 8 or reserved != 0 or value_type > 0x1F:
                    raise ValueError('Invalid binary XML text value')
                if value_type == 0x03:
                    get_string(value_data)
            else:
                raise ValueError('Unsupported binary XML chunk type')

            offset = chunk_end

        if (strings is None or not root_seen or not root_closed or element_stack or
                namespace_stack or not root_is_manifest or root_package_count != 1):
            return ''
        if not root_package or not PKG_RE.fullmatch(root_package):
            return ''
        return root_package

    @staticmethod
    def read_apk_metadata(local_path):
        """Yerel APK dosyasindan paket adi, surum, etiket ve min SDK okur."""
        import os
        import zipfile
        info = {
            'package': '',
            'version_name': '',
            'version_code': '',
            'app_name': '',
            'min_sdk': '',
            'target_sdk': '',
            'size_bytes': 0,
        }
        if not local_path or not os.path.isfile(local_path):
            return info
        try:
            info['size_bytes'] = os.path.getsize(local_path)
        except OSError:
            pass

        try:
            with zipfile.ZipFile(local_path, 'r') as zf:
                manifests = [entry for entry in zf.infolist()
                             if entry.filename == 'AndroidManifest.xml']
                if len(manifests) != 1 or not 0 < manifests[0].file_size <= 8 * 1024 * 1024:
                    return info
                with zf.open(manifests[0], 'r') as manifest_file:
                    data = manifest_file.read(8 * 1024 * 1024 + 1)
                if len(data) != manifests[0].file_size or len(data) > 8 * 1024 * 1024:
                    return info
                info['package'] = AdbEngine._package_from_binary_manifest(data)
        except Exception:
            return info
        if not info['package']:
            return info

        try:
            from androguard.core.apk import APK
            apk = APK(local_path)
            parsed_package = apk.get_package() or ''
            if parsed_package and parsed_package != info['package']:
                info['package'] = ''
                return info
            info['version_name'] = str(apk.get_androidversion_name() or '')
            info['version_code'] = str(apk.get_androidversion_code() or '')
            info['app_name'] = apk.get_app_name() or ''
            info['min_sdk'] = str(apk.get_min_sdk_version() or '')
            info['target_sdk'] = str(apk.get_target_sdk_version() or '')
        except Exception:
            pass
        return info

    def get_volume_info(self, target, timeout=6):
        """Cihazın medya ses seviyesi ve aralığını (cur, min, max) olarak döner."""
        # 1. En hızlı ve hafif yol: cmd media_session volume get (~15ms)
        for cmd in (
            ['cmd', 'media_session', 'volume', '--stream', '3', '--get'],
            ['media', 'volume', '--stream', '3', '--get'],
        ):
            try:
                res = self.shell(target, *cmd, timeout=timeout)
                out = res.output or ''
                m = re.search(r'volume is (\d+)', out)
                m_range = re.search(r'range\s*\[(\d+)\.\.(\d+)\]', out)
                if m:
                    cur = int(m.group(1))
                    mn = int(m_range.group(1)) if m_range else 0
                    mx = int(m_range.group(2)) if m_range else 15
                    return cur, mn, mx
            except Exception:
                continue

        # 2. Alternatif yol: dumpsys audio STREAM_MUSIC bloğu
        try:
            res = self.shell(target, 'dumpsys', 'audio', timeout=timeout)
            out = res.output or ''
            if 'STREAM_MUSIC:' in out:
                block = out.split('STREAM_MUSIC:')[1].split('- STREAM_')[0]
                m_sv = re.search(r'streamVolume:\s*(\d+)', block)
                m_min = re.search(r'Min:\s*(\d+)', block)
                m_max = re.search(r'Max:\s*(\d+)', block)
                mn = int(m_min.group(1)) if m_min else 0
                mx = int(m_max.group(1)) if m_max else 15
                if m_sv:
                    cur = int(m_sv.group(1))
                    return cur, mn, mx
                m_cur = re.search(r'Current:\s*.*?(\d+)\s*$', block, re.MULTILINE)
                if m_cur:
                    return int(m_cur.group(1)), mn, mx
        except Exception:
            pass

        raise AdbError('TV ses aralığı okunamadı; ses değişikliği uygulanmadı.')

    def get_volume(self, target, timeout=6):
        """Mevcut medya ses seviyesini yüzde (0-100) olarak döner."""
        try:
            cur, mn, mx = self.get_volume_info(target, timeout=timeout)
            if mx > mn:
                return int(round((cur - mn) / float(mx - mn) * 100))
        except Exception:
            pass
        return 50

    def _set_volume_steps(self, target, level, current, minimum, maximum, timeout):
        """Okunmuş cihaz aralığındaki tam ses kademesini uygular."""
        import time as _time
        if maximum <= minimum or not minimum <= current <= maximum:
            raise AdbError('TV ses aralığı geçersiz; ses değiştirilmedi.')
        if not minimum <= level <= maximum:
            raise AdbError('Ses seviyesi cihazın izin verdiği aralığın dışında.')
        diff = level - current
        key = '24' if diff > 0 else '25'
        for _ in range(abs(diff)):
            result = self.shell(target, 'input', 'keyevent', key, timeout=timeout)
            if result.exit_code != 0:
                raise AdbError(result.error or result.output or 'Ses tuşu başarısız oldu.')
            _time.sleep(0.05)
        return True

    def set_volume_level(self, target, level, timeout=10):
        """Medya sesini cihazın tam sayı kademesiyle ayarlar (örn. 0–15)."""
        try:
            cur_idx, mn, mx = self.get_volume_info(target, timeout=timeout)
            return self._set_volume_steps(target, int(level), cur_idx, mn, mx, timeout)
        except Exception as e:
            raise AdbError('Ses seviyesi ayarlanamadı: {}'.format(e))

    def set_volume(self, target, percent, timeout=10):
        """Yüzde kullanan çağrılar için uyumluluk: medya sesini 0–100 ile ayarlar."""
        try:
            pct = max(0, min(100, int(percent)))
            cur_idx, mn, mx = self.get_volume_info(target, timeout=timeout)
            level = int(round(mn + (pct / 100.0) * (mx - mn)))
            return self._set_volume_steps(target, level, cur_idx, mn, mx, timeout)
        except Exception as e:
            raise AdbError('Ses seviyesi ayarlanamadı: {}'.format(e))

    def set_volume_mute(self, target, timeout=10):
        """Cihaz sesini acar veya sessize alir (Mute toggle)."""
        result = self.shell(target, 'input', 'keyevent', '164', timeout=timeout)
        if result.exit_code != 0:
            raise AdbError('Sessize alma tuşu çalıştırılamadı: {}'.format(
                (result.error or result.output or 'bilinmeyen hata').strip()))
        return result

    def soft_reboot(self, target, timeout=15):
        """Zygote surecini yeniden baslatarak 3 saniyede hizli soft reboot yapar."""
        result = self.shell(target, 'setprop', 'ctl.restart', 'zygote', timeout=timeout)
        if result.exit_code != 0:
            raise AdbError('Hızlı yeniden başlatma başarısız: {}'.format(
                (result.error or result.output or 'izin reddedildi').strip()))
        return result

    def rename_file(self, target, old_path, new_path, timeout=15):
        """Cihazdaki dosya veya klasorun adini degistirir / tasir."""
        old_safe = safe_remote_path(old_path)
        new_safe = safe_remote_path(new_path)
        if self._is_protected_file_path(old_safe) or self._is_protected_file_path(new_safe):
            raise AdbError('Kok veya baglama dizinleri yeniden adlandirilamaz.')
        if old_safe == new_safe:
            raise AdbError('Kaynak ve hedef aynı; yeniden adlandırma yapılmadı.')

        def remote_exists(path):
            quoted = _quoted_remote_path(path)
            for flag in ('-e', '-L'):
                check = self.shell(target, 'test', flag, quoted, timeout=timeout)
                if check.exit_code == 0:
                    return True
                if check.exit_code != 1:
                    raise AdbError('Uzak yol doğrulanamadı; işlem güvenlik için durduruldu.')
            return False

        # Reject both existing files and directories before moving. Toybox mv -n
        # also protects against a destination file appearing between this check
        # and the rename, without overwriting its contents.
        if remote_exists(new_safe):
            raise AdbError('Bu ad zaten var; mevcut dosya veya klasör korunuyor.')

        res = self.shell(
            target, 'mv', '-n', _quoted_remote_path(old_safe),
            _quoted_remote_path(new_safe), timeout=timeout,
        )
        if res.exit_code != 0:
            raise AdbError('Yeniden adlandırılamadı: {}'.format(res.error or res.output or 'Bilinmeyen hata'))
        if remote_exists(old_safe):
            raise AdbError('Yeniden adlandırma yapılmadı; kaynak ve mevcut hedef korundu.')
        if not remote_exists(new_safe):
            raise AdbError('Yeniden adlandırma hedefi doğrulanamadı; TV dosya listesini yenileyin.')
        return True

    def open_url(self, target, url, timeout=10):
        """TV'de URL veya video bağlantısını varsayılan uygulamada (SmartTube, YouTube, Tarayıcı) açar."""
        if not target or not url:
            raise AdbError('Cihaz ve bağlantı adresi gereklidir.')
        url = str(url).strip()
        try:
            parsed = urlsplit(url)
        except ValueError:
            raise AdbError('Geçersiz bağlantı adresi.')
        if (parsed.scheme.lower() not in {'http', 'https', 'rtsp', 'magnet'}
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in url)
                or (parsed.scheme.lower() != 'magnet' and not parsed.hostname)):
            raise AdbError('Desteklenmeyen veya geçersiz bağlantı adresi.')
        _scheme, separator, remainder = url.partition(':')
        normalized_url = parsed.scheme.lower() + separator + remainder
        res = self.shell(
            target, 'am', 'start', '-a', 'android.intent.action.VIEW',
            '-d', shlex.quote(normalized_url), timeout=timeout,
        )
        explicit_error = re.search(
            r'(?im)^\s*(?:Error:|Error\s+type\s+\d+\b|Exception|java\.[^\s:]*Exception)',
            '{}\n{}'.format(res.output or '', res.error or ''),
        )
        if res.exit_code != 0 or explicit_error:
            raise AdbError('Link TV\'de açılamadı. Bağlantı adresi günlük kaydına yazılmadı.')
        return res

    def start_screensaver(self, target, timeout=10):
        """TV ekran koruyucusunu (Ambient / Backdrop) başlatır."""
        res = self.shell(target, 'cmd', 'dreams', 'start-dreaming', timeout=timeout)
        explicit_error = re.search(
            r'(?im)^\s*(?:Error:|Error\s+type\s+\d+\b|Exception|java\.[^\s:]*Exception)',
            '{}\n{}'.format(res.output or '', res.error or ''),
        )
        if res.exit_code != 0 or explicit_error:
            res = self.shell(
                target, 'am', 'start', '-n',
                'com.google.android.backdrop/.Backdrop', timeout=timeout,
            )
        explicit_error = re.search(
            r'(?im)^\s*(?:Error:|Error\s+type\s+\d+\b|Exception|java\.[^\s:]*Exception)',
            '{}\n{}'.format(res.output or '', res.error or ''),
        )
        if res.exit_code != 0 or explicit_error:
            raise AdbError('Ekran koruyucu başlatılamadı: {}'.format(
                (res.error or res.output or 'cihaz bu özelliği desteklemiyor').strip()))
        return res
