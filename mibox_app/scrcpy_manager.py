# -*- coding: utf-8 -*-
"""Scrcpy Entegrasyonu ve Otomatik İndirici.

Android TV ekranını yansıtmak için Scrcpy aracını tespit eder; bulunamazsa
resmî, sürümü ve SHA-256 özeti sabitlenmiş Windows paketini kurar.
"""
from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from urllib.parse import urlsplit
from pathlib import PurePosixPath
import zipfile
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Signal

from .config import BASE_DIR, LOG_DIR
from .workers import BaseWorker

SCRCPY_DEFAULT_VERSION = 'v5.0.1'
SCRCPY_RELEASES = {
    'scrcpy-win64': (
        f'https://github.com/Genymobile/scrcpy/releases/download/{SCRCPY_DEFAULT_VERSION}/scrcpy-win64-{SCRCPY_DEFAULT_VERSION}.zip',
        11264634,
        'b12a2c4ee8be317422451fc7dcf8ee20a71b5ea7ef9ad73ddd825a25316227a5',
    ),
    'scrcpy-win32': (
        f'https://github.com/Genymobile/scrcpy/releases/download/{SCRCPY_DEFAULT_VERSION}/scrcpy-win32-{SCRCPY_DEFAULT_VERSION}.zip',
        10133753,
        '0cb65ebf1bce892fa4d1502d699af0c7a1a7f24d7febcb9ef72894e3f23fc2ad',
    ),
    'scrcpy-winarm64': (
        f'https://github.com/Genymobile/scrcpy/releases/download/{SCRCPY_DEFAULT_VERSION}/scrcpy-winarm64-{SCRCPY_DEFAULT_VERSION}.zip',
        9825739,
        '16c3fc2068df64946f670e3504b4752073ebae47a416a45b46e79a5ab19c689b',
    ),
}
SCRCPY_BINARY_SHA256 = {
    'scrcpy-win64': '64bcee493d9243dab1e84093928014348738e31f3225e67558210e6b6cfb9cd6',
    'scrcpy-win32': 'c30309eed95503329a77bb600c4b60f102d939b974c370b1794bc5170d230fb3',
    'scrcpy-winarm64': 'b30c6403389101c876c4dc7981f7d3054844cbd1761dc6366af30c357ea67557',
}


def get_scrcpy_arch_prefix() -> str:
    """Sistem mimarisine göre scrcpy paket ön ekini döner."""
    machine = platform.machine().lower()
    is_64 = sys.maxsize > 2**32 or '64' in machine
    if 'arm' in machine or 'aarch64' in machine:
        return 'scrcpy-winarm64'
    elif is_64:
        return 'scrcpy-win64'
    else:
        return 'scrcpy-win32'


def _verify_scrcpy_executable(path: str) -> bool:
    """Accept only the executable from the pinned, official release archive."""
    expected = SCRCPY_BINARY_SHA256.get(get_scrcpy_arch_prefix())
    if not expected:
        return False
    try:
        digest = hashlib.sha256()
        with open(path, 'rb') as src:
            for chunk in iter(lambda: src.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest().lower() == expected
    except OSError:
        return False


def find_scrcpy(base_dir: Optional[str] = None) -> Optional[str]:
    """Sistemde veya uygulama klasöründe scrcpy.exe olup olmadığını kontrol eder.

    Öncelik Sırası:
    Yalnızca uygulamanın sabitlenmiş resmî sürüm SHA-256 özetiyle eşleşen
    dosyaları kabul eder; eşleşmeyen önbellek veya PATH dosyası çalıştırılmaz.
    """
    root = os.path.abspath(base_dir or BASE_DIR)

    # A repaired installation takes precedence over an older valid executable
    # whose neighboring libraries may be missing. Store only a relative name.
    try:
        with open(os.path.join(root, '.scrcpy-preferred'), encoding='utf-8') as marker:
            preferred = marker.read(256).strip()
        if re.fullmatch(r'scrcpy-[A-Za-z0-9._-]+', preferred):
            folder = os.path.realpath(os.path.join(root, preferred))
            if os.path.dirname(folder) == os.path.realpath(root):
                candidate = os.path.join(folder, 'scrcpy.exe')
                if os.path.isfile(candidate) and _verify_scrcpy_executable(candidate):
                    return candidate
    except (OSError, UnicodeError):
        pass

    # 1. <base_dir>/scrcpy/scrcpy.exe (Uygulama klasöründeki standart scrcpy dizini)
    primary = os.path.join(root, 'scrcpy', 'scrcpy.exe')
    if os.path.isfile(primary) and _verify_scrcpy_executable(primary):
        return primary

    # 2. Doğrudan <base_dir>/scrcpy.exe
    direct = os.path.join(root, 'scrcpy.exe')
    if os.path.isfile(direct) and _verify_scrcpy_executable(direct):
        return direct

    # 3. <base_dir>/ içindeki scrcpy-* klasörleri
    try:
        if os.path.isdir(root):
            for entry in os.listdir(root):
                if entry.lower().startswith('scrcpy') and os.path.isdir(os.path.join(root, entry)):
                    cand = os.path.join(root, entry, 'scrcpy.exe')
                    if os.path.isfile(cand) and _verify_scrcpy_executable(cand):
                        return cand
    except Exception:
        pass

    # 4. PATH üzerinde kontrol
    which_path = shutil.which('scrcpy') or shutil.which('scrcpy.exe')
    if (which_path and os.path.isfile(which_path)
            and _verify_scrcpy_executable(which_path)):
        return os.path.abspath(which_path)

    return None


def _remember_scrcpy_install(target_dir: str) -> None:
    """Atomically select a verified installation directly inside BASE_DIR."""
    root = os.path.realpath(BASE_DIR)
    folder = os.path.realpath(target_dir)
    name = os.path.basename(folder)
    if os.path.dirname(folder) != root or not re.fullmatch(r'scrcpy-[A-Za-z0-9._-]+', name):
        raise RuntimeError('Tercih edilen Scrcpy kurulum yolu doğrulanamadı.')
    descriptor, temporary = tempfile.mkstemp(prefix='.scrcpy-preferred-', suffix='.tmp', dir=root)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as marker:
            marker.write(name + '\n')
        os.replace(temporary, os.path.join(root, '.scrcpy-preferred'))
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def get_scrcpy_download_info() -> Dict[str, Any]:
    """Pinned scrcpy release details and upstream-published SHA-256 checksum."""
    prefix = get_scrcpy_arch_prefix()
    url, size, sha256 = SCRCPY_RELEASES.get(
        prefix,
        SCRCPY_RELEASES['scrcpy-win64']
    )
    return {
        'version': SCRCPY_DEFAULT_VERSION,
        'url': url,
        'size': size,
        'sha256': sha256,
        'filename': f'{prefix}-{SCRCPY_DEFAULT_VERSION}.zip',
    }


class ScrcpyDownloader(BaseWorker):
    """Scrcpy zip arşivini indirip uygulama klasörüne açan asenkron işçi."""

    finished_ok = Signal(object)
    failed = Signal(str)
    log = Signal(str)
    progress = Signal(int, int)
    status_text = Signal(str)

    job_name = 'Scrcpy İndirici'

    def __init__(self, target_dir: Optional[str] = None, force_download: bool = False):
        super().__init__()
        self.target_dir = target_dir
        self.force_download = force_download

    def _work(self):
        self.check_cancel()
        self.status_text.emit('Scrcpy sürüm bilgileri kontrol ediliyor...')
        info = get_scrcpy_download_info()
        url = info['url']
        expected_size = info['size']
        expected_sha256 = str(info.get('sha256', '')).lower()
        version = info['version']

        url_parts = urlsplit(url)
        if (url_parts.scheme != 'https' or url_parts.hostname != 'github.com'
                or not url_parts.path.startswith('/Genymobile/scrcpy/releases/download/')):
            raise RuntimeError('Scrcpy indirme adresi doğrulanamadı.')
        if not 0 < int(expected_size) <= 64 * 1024 * 1024:
            raise RuntimeError('Scrcpy arşiv boyutu beklenen sınırın dışında.')
        if not re.fullmatch(r'[a-f0-9]{64}', expected_sha256):
            raise RuntimeError('Scrcpy için güvenilir SHA-256 özeti bulunamadı.')

        safe_version = re.sub(r'[^A-Za-z0-9._-]', '_', str(version)).strip('._-') or 'latest'
        base_target = os.path.abspath(
            self.target_dir or os.path.join(BASE_DIR, 'scrcpy-' + safe_version)
        )
        cached_exe = os.path.join(base_target, 'scrcpy.exe')
        if (not self.force_download and os.path.isfile(cached_exe)
                and _verify_scrcpy_executable(cached_exe)):
            result = {'scrcpy_path': os.path.join(base_target, 'scrcpy.exe'),
                      'version': version, 'target_dir': base_target}
            self.check_cancel()
            self.finished_ok.emit(result)
            return result
        target_dir = base_target
        if os.path.exists(target_dir):
            target_dir = '{}-{}'.format(base_target, os.urandom(3).hex())
        parent_dir = os.path.dirname(target_dir)
        os.makedirs(parent_dir, exist_ok=True)

        size_mb = max(1, expected_size // (1024 * 1024))
        self.log.emit(f"Scrcpy {version} indiriliyor: {url} (~{size_mb} MB)")
        self.status_text.emit(f"Scrcpy {version} indiriliyor...")

        # İndirme işlemi
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        temp_fd, temp_zip = tempfile.mkstemp(prefix='mibox-scrcpy-', suffix='.zip')
        os.close(temp_fd)
        staging_root = None

        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                final_host = urlsplit(resp.geturl()).hostname
                if final_host not in {
                    'github.com', 'release-assets.githubusercontent.com',
                    'objects.githubusercontent.com',
                }:
                    raise RuntimeError('Scrcpy indirme kaynağı doğrulanamadı.')
                content_length = resp.headers.get('Content-Length')
                if content_length is not None:
                    content_length = int(content_length)
                total_size = content_length if content_length is not None else expected_size
                if not 0 < total_size <= 64 * 1024 * 1024:
                    raise RuntimeError('Scrcpy indirme boyutu geçersiz veya çok büyük.')
                downloaded = 0
                digest = hashlib.sha256()
                chunk_size = 64 * 1024  # 64 KB

                with open(temp_zip, 'wb') as out_f:
                    while True:
                        self.check_cancel()
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        if downloaded + len(chunk) > 64 * 1024 * 1024:
                            raise RuntimeError('Scrcpy arşivi izin verilen boyutu aşıyor.')
                        out_f.write(chunk)
                        digest.update(chunk)
                        downloaded += len(chunk)
                        self.progress.emit(downloaded, total_size)
                        if total_size > 0:
                            pct = int((downloaded / total_size) * 100)
                            cur_mb = downloaded / (1024 * 1024)
                            tot_mb = total_size / (1024 * 1024)
                            self.status_text.emit(
                                f"Scrcpy indiriliyor... {cur_mb:.1f} / {tot_mb:.1f} MB (%{pct})"
                            )
                if downloaded != total_size:
                    raise RuntimeError('Scrcpy indirmesi eksik veya bozuk (beklenen {} bayt, alınan {}).'.format(
                        total_size, downloaded))
                if downloaded != expected_size:
                    raise RuntimeError(
                        'Scrcpy indirme boyutu sabitlenmiş beklentiyle eşleşmiyor '
                        '(beklenen {} bayt, alınan {}).'.format(expected_size, downloaded)
                    )
                if digest.hexdigest().lower() != expected_sha256:
                    raise RuntimeError('Scrcpy SHA-256 doğrulaması başarısız; dosya çalıştırılmadı.')

            self.check_cancel()
            self.status_text.emit('Arşiv klasöre çıkartılıyor...')
            self.log.emit(f"Scrcpy {version} arşivi doğrulanıyor ve kuruluyor.")

            staging_root = tempfile.mkdtemp(prefix='.mibox-scrcpy-', dir=parent_dir)
            payload_dir = os.path.join(staging_root, 'payload')
            os.makedirs(payload_dir)
            extracted_size = 0
            with zipfile.ZipFile(temp_zip, 'r') as zf:
                members = zf.infolist()
                if len(members) > 10000:
                    raise RuntimeError('Scrcpy arşivinde beklenenden fazla dosya var.')
                for member in members:
                    self.check_cancel()
                    normalized = member.filename.replace('\\', '/')
                    parts = PurePosixPath(normalized).parts
                    if (not parts or normalized.startswith('/')
                            or re.match(r'^[A-Za-z]:', normalized)
                            or any(part in ('', '.', '..') for part in parts)):
                        raise RuntimeError('Scrcpy arşivinde güvenli olmayan dosya yolu var.')
                    mode = member.external_attr >> 16
                    if stat.S_ISLNK(mode) or (mode and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))):
                        raise RuntimeError('Scrcpy arşivinde desteklenmeyen dosya türü var.')
                    if len(parts) > 1 and parts[0].startswith('scrcpy-'):
                        parts = parts[1:]
                    if not parts:
                        continue
                    extracted_size += member.file_size
                    if extracted_size > 256 * 1024 * 1024:
                        raise RuntimeError('Scrcpy arşivinin açılmış boyutu izin verilen sınırı aşıyor.')
                    dest_file = os.path.abspath(os.path.join(payload_dir, *parts))
                    if os.path.commonpath((payload_dir, dest_file)) != payload_dir:
                        raise RuntimeError('Scrcpy arşiv yolu kurulum klasörünün dışına çıkıyor.')
                    if member.is_dir():
                        os.makedirs(dest_file, exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                    if os.path.exists(dest_file):
                        raise RuntimeError('Scrcpy arşivinde yinelenen dosya yolu var.')
                    with zf.open(member) as src, open(dest_file, 'xb') as dst:
                        shutil.copyfileobj(src, dst)

            scrcpy_exe = os.path.join(payload_dir, 'scrcpy.exe')
            if not os.path.isfile(scrcpy_exe):
                raise RuntimeError('Scrcpy arşivinden scrcpy.exe çıkmadı.')
            if not _verify_scrcpy_executable(scrcpy_exe):
                raise RuntimeError('Scrcpy dosyası resmî sürüm SHA-256 doğrulamasını geçemedi.')
            self.check_cancel()
            os.replace(payload_dir, target_dir)
            if self.target_dir is None:
                _remember_scrcpy_install(target_dir)

            target_exe = os.path.join(target_dir, 'scrcpy.exe')
            self.log.emit(f"Scrcpy başarıyla kuruldu: {target_exe}")
            res = {
                'scrcpy_path': target_exe,
                'version': version,
                'target_dir': target_dir,
            }
            self.check_cancel()
            self.finished_ok.emit(res)
            return res

        except Exception as exc:
            raise exc
        finally:
            for path in (temp_zip, staging_root):
                if not path:
                    continue
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                    elif os.path.exists(path):
                        os.remove(path)
                except OSError:
                    pass


def _log_scrcpy_output(output, log_path, private_values):
    """Persist Scrcpy output after removing device identifiers and local paths."""
    from .adb_engine import sanitize_log_text

    try:
        with open(log_path, 'a', encoding='utf-8', errors='replace',
                  buffering=1) as log_handle:
            for line in output:
                log_handle.write(sanitize_log_text(line, private_values))
    except OSError:
        # Keep draining the pipe if logging becomes unavailable so Scrcpy
        # cannot block on a full stdout buffer.
        try:
            for _line in output:
                pass
        except (OSError, ValueError):
            pass
    finally:
        try:
            output.close()
        except (OSError, ValueError):
            pass


def launch_scrcpy(
    scrcpy_path: str,
    target: str,
    adb_path: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
    window_title: Optional[str] = None,
) -> subprocess.Popen:
    """Scrcpy sürecini doğru dizin, ADB ortam değişkenleri ve log kaydı ile başlatır.

    Args:
        scrcpy_path: scrcpy.exe dosyasının tam yolu.
        target: Hedef Android TV cihazı (örn. '<TV-IP>:5555' veya USB seri no).
        adb_path: MiBoxKonsol'un kullandığı adb.exe yolu.
        extra_args: İlave scrcpy komut satırı argümanları.
        window_title: Başlatılacak pencerenin başlığı.
    """
    if not os.path.isfile(scrcpy_path):
        raise FileNotFoundError(f"Scrcpy çalıştırılabilir dosyası bulunamadı: {scrcpy_path}")
    if not _verify_scrcpy_executable(scrcpy_path):
        raise RuntimeError('Scrcpy dosyası resmî sürüm SHA-256 doğrulamasını geçemedi.')

    cwd = os.path.dirname(os.path.abspath(scrcpy_path))
    env = os.environ.copy()

    # ADB çakışmasını engellemek için MiBoxKonsol'un kullandığı adb yolunu aktar
    if adb_path and os.path.isfile(adb_path):
        env['ADB'] = os.path.abspath(adb_path)
        adb_dir = os.path.dirname(os.path.abspath(adb_path))
        env['PATH'] = adb_dir + os.pathsep + env.get('PATH', '')

    title = window_title or f'MiBox Canlı Ekran - {target} (Scrcpy 60 FPS)'
    cmd = [
        scrcpy_path,
        '-s', target,
        '--window-title', title,
    ]
    if extra_args:
        cmd.extend(extra_args)

    creation_flags = 0
    if os.name == 'nt':
        creation_flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)

    # Scrcpy loglarını cihaz adresi/seri no ve yerel yollar maskelenerek sakla.
    scrcpy_log_file = os.path.join(
        LOG_DIR, 'scrcpy-{}.log'.format(time.strftime('%Y%m%d')))
    log_enabled = False
    from .adb_engine import sanitize_log_text, target_private_values
    private_values = target_private_values(target)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(scrcpy_log_file, 'a', encoding='utf-8', errors='replace') as log_handle:
            log_enabled = True
            safe_command = sanitize_log_text(' '.join(cmd), private_values)
            log_handle.write(
                f"\n--- Scrcpy Başlatıldı: {time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"({safe_command}) ---\n")
    except Exception:
        log_enabled = False

    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE if log_enabled else subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        text=True if log_enabled else None,
        encoding='utf-8' if log_enabled else None,
        errors='replace' if log_enabled else None,
        bufsize=1 if log_enabled else -1,
        creationflags=creation_flags
    )
    if log_enabled and process.stdout is not None:
        output_thread = threading.Thread(
            target=_log_scrcpy_output,
            args=(process.stdout, scrcpy_log_file, private_values),
            name='mibox-scrcpy-log',
            daemon=True)
        try:
            output_thread.start()
        except RuntimeError:
            process.stdout.close()
            try:
                process.terminate()
            except OSError:
                pass
            raise
    return process
