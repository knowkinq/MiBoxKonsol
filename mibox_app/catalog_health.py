# -*- coding: utf-8 -*-
"""Katalog indirme adreslerinin saglik kontrolu (bakim/CI araci).

Her kayit icin erisilebilirlik denetlenir: HTTPS yonlendirme zinciri ve
HTTP durum kodu. 'store' turu kayitlarda APK adresi yerine store_url
yoklanir. --verify-hash verilirse sha256 kayitli (sabit surumlu) girdiler
indirilip ozet karsilastirilir; ozetsiz 'latest' kayitlari yalnizca
erisilebilirlik icin yoklanir. Ag erisimi gerektirir; birim testleri
urllib.request.urlopen'i taklit eder.

--update-hash <kayit_kimligi> kaydin guncel sha256 ozetini indirip
hesaplar ve catalog.py'ye yapistirilacak satiri yazdirir (dosyayi
degistirmez).

CLI (Qt'siz calisir; CI haftalik job kullanir):
    python -m mibox_app.catalog_health [--verify-hash]
    python -m mibox_app.catalog_health --update-hash <kayit_kimligi>
    python mibox.py --check-catalog [--verify-hash]
"""
import hashlib
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .catalog import TV_CATALOG

_TIMEOUT = 20
# catalog.download_apk ile ayni sinir.
_MAX_SIZE = 512 * 1024 * 1024
# HEAD'i reddeden sunucularda tek baytlik GET araligina dusulur.
_FALLBACK_CODES = (403, 405, 501)
_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


def _request(url, method=None, headers=None):
    merged = {'User-Agent': _UA}
    if headers:
        merged.update(headers)
    return urllib.request.Request(url, headers=merged, method=method)


def _check_final_url(resp):
    final = urlsplit(resp.geturl())
    if final.scheme != 'https' or not final.hostname:
        raise ValueError('yönlendirme güvenli bağlantıda kalmadı')


def _probe(url):
    """(ok, detay, boyut) — once HEAD; sunucu reddederse Range GET dener."""
    for attempt in ('head', 'range'):
        try:
            if attempt == 'head':
                req = _request(url, method='HEAD')
            else:
                req = _request(url, headers={'Range': 'bytes=0-0'})
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                _check_final_url(resp)
                status = getattr(resp, 'status', None) or resp.getcode()
                raw_length = resp.headers.get('content-length')
                try:
                    length = int(raw_length) if raw_length is not None else None
                except (TypeError, ValueError):
                    length = None
                if attempt == 'range':
                    return True, 'HTTP {} (HEAD reddedildi, Range yanıtı)'.format(status), None
                return True, 'HTTP {}'.format(status), length
        except urllib.error.HTTPError as exc:
            if exc.code in _FALLBACK_CODES:
                continue
            return False, 'HTTP {}'.format(exc.code), None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return False, str(exc) or exc.__class__.__name__, None
    codes = '/'.join(str(code) for code in _FALLBACK_CODES)
    return False, 'HTTP {} (HEAD ve Range reddedildi)'.format(codes), None


def _download_digest(url):
    """Indirip sha256 ozetini dondurur (dosya diske yazilmaz)."""
    digest = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(_request(url), timeout=_TIMEOUT) as resp:
        _check_final_url(resp)
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_SIZE:
                raise ValueError('boyut sınırı aşıldı')
            digest.update(chunk)
    return digest.hexdigest()


def check_entry(item, verify_hash=False):
    """Tek katalog kaydini denetle: (ok, detay).

    'store' turu kayitlarda APK adresi yoktur; store_url yalnizca
    erisilebilirlik icin yoklanir ve ozet dogrulamasi yapilmaz.
    """
    is_store = str(item.get('type') or '').strip().lower() == 'store'
    url = str(item.get('store_url' if is_store else 'url') or '').strip()
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname:
        return False, 'geçersiz adres (HTTPS değil)'
    ok, detail, length = _probe(url)
    if not ok:
        return False, detail
    if is_store:
        return True, detail + ', mağaza kaydı'
    if length is not None and length > _MAX_SIZE:
        return False, 'boyut sınırı aşıldı ({} bayt)'.format(length)
    expected = str(item.get('sha256') or '').strip().lower()
    if not expected:
        return True, detail
    if not verify_hash:
        return True, detail + ', sha256 kayıtlı (sınanmadı)'
    try:
        digest = _download_digest(url)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, 'özet doğrulaması için indirme başarısız: {}'.format(exc)
    if digest != expected:
        return False, 'sha256 uyuşmuyor: beklenen {}, gelen {}'.format(expected, digest)
    return True, detail + ', sha256 doğrulandı'


def check_catalog(entries=None, verify_hash=False):
    """Tum kayitlari denetler: [(id, ok, detay), ...] doner."""
    items = TV_CATALOG if entries is None else list(entries)
    results = []
    for item in items:
        ok, detail = check_entry(item, verify_hash=verify_hash)
        results.append((str(item.get('id') or '?'), ok, detail))
    return results


def update_hash(item_id, entries=None):
    """Kaydin guncel sha256'sini indirip hesaplar.

    Geri: (ok, detay, yapistirilacak_satir). Kaynak dosyayi degistirmez;
    kullanim: eski ozetle karsilastir, cikan satiri catalog.py'ye koy.
    """
    items = TV_CATALOG if entries is None else list(entries)
    item = next((x for x in items if str(x.get('id') or '') == item_id), None)
    if item is None:
        return False, 'kayıt bulunamadı: {}'.format(item_id), None
    if str(item.get('type') or '').strip().lower() == 'store':
        return False, 'mağaza kaydının özeti hesaplanmaz (APK adresi yok)', None
    url = str(item.get('url') or '').strip()
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname:
        return False, 'geçersiz adres (HTTPS değil)', None
    try:
        digest = _download_digest(url)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, 'indirme başarısız: {}'.format(exc), None
    current = str(item.get('sha256') or '').strip().lower()
    if current == digest:
        note = 'özet değişmedi'
    elif current:
        note = 'özet DEĞİŞTİ: eski {}, yeni {}'.format(current, digest)
    else:
        note = 'kayıtta özet yok; sabitlenebilir'
    return True, note, "'sha256': '{}',".format(digest)


def main(argv=None, stream=None):
    """CLI: --check-catalog [--verify-hash] | --update-hash <kimlik>."""
    argv = list(sys.argv if argv is None else argv)
    verify_hash = '--verify-hash' in argv
    out = stream if stream is not None else sys.stdout
    try:
        out.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError, OSError):
        pass
    if '--update-hash' in argv:
        index = argv.index('--update-hash')
        target = argv[index + 1] if index + 1 < len(argv) else ''
        if not target or target.startswith('--'):
            print('Kullanım: --update-hash <kayıt_kimliği>', file=out)
            return 2
        ok, detail, snippet = update_hash(target)
        if not ok:
            print('HATA  {}: {}'.format(target, detail), file=out)
            return 1
        print('TAMAM {}: {}'.format(target, detail), file=out)
        print(snippet, file=out)
        return 0
    results = check_catalog(verify_hash=verify_hash)
    width = max([len(item_id) for item_id, _ok, _detail in results] or [0])
    failures = 0
    for item_id, ok, detail in results:
        if not ok:
            failures += 1
        print('{:<5} {:<{width}} {}'.format(
            'TAMAM' if ok else 'HATA', item_id, detail, width=width), file=out)
    suffix = ' (--verify-hash)' if verify_hash else ''
    print('{}/{} kayıt sağlıklı{}'.format(
        len(results) - failures, len(results), suffix), file=out)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
