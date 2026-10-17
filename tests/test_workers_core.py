# -*- coding: utf-8 -*-
"""Ek worker kapsami: BaseWorker/Worker, tarama, toplu islem, ozet bicimleme.

Gercek ADB kullanilmaz: motor taklit edilir. QThread.start() cagrilmaz;
worker.run() senkron kosulur ve sinyaller lambda'lara baglanarak yakalanir.
"""
import inspect

import pytest

from mibox_app.adb_engine import AdbError, check_user_id
from mibox_app.workers import (
    AppScanWorker,
    BaseWorker,
    BulkActionWorker,
    CancelledError,
    Worker,
    _call_user_method,
    _fail_text,
    _require_user_scope,
    format_action_result,
    is_system_apk,
)


def _run(worker, presence=None):
    """worker.run()'u senkron kosar; (sonuc, hata, loglar, ilerleme) doner."""
    box = {'ok': None, 'fail': None}
    logs = []
    progress = []
    worker.finished_ok.connect(lambda r: box.__setitem__('ok', r))
    worker.failed.connect(lambda e: box.__setitem__('fail', e))
    worker.log.connect(logs.append)
    worker.progress.connect(lambda i, t: progress.append((i, t)))
    if presence is not None:
        worker.presence.connect(presence.append)
    worker.run()
    return box['ok'], box['fail'], logs, progress


def _entry(pkg, enabled=True, installed_user0=True, apk=''):
    return {'package': pkg, 'enabled': enabled,
            'installed_user0': installed_user0, 'apk': apk}


# --- BaseWorker / Worker -----------------------------------------------------

class _MiniWorker(BaseWorker):
    def __init__(self):
        super().__init__()
        self.job_name = 'Mini'
        self.ran = False

    def _work(self):
        self.ran = True


def test_baseworker_basari_loglari():
    worker = _MiniWorker()
    ok, fail, logs, progress = _run(worker)
    assert ok is None and fail is None
    assert worker.ran
    assert any('Mini başladı' in line for line in logs)
    assert any('Mini bitti' in line for line in logs)


def test_baseworker_iptal_work_calismaz():
    worker = _MiniWorker()
    worker.cancel()
    ok, fail, logs, progress = _run(worker)
    assert ok is None
    assert fail == 'kullanıcı durdurdu'
    assert not worker.ran
    assert any('durduruldu' in line for line in logs)


def test_baseworker_iptal_yapiskan():
    worker = _MiniWorker()
    assert worker.isInterruptionRequested() is False
    worker.cancel()
    assert worker.isInterruptionRequested() is True
    with pytest.raises(CancelledError):
        worker.check_cancel()


def test_baseworker_work_uygulanmamis():
    with pytest.raises(NotImplementedError):
        BaseWorker()._work()


def test_cancel_request_interruption_hatasini_yutar():
    worker = _MiniWorker()

    def patla():
        raise RuntimeError('iptal edilemez')

    worker.requestInterruption = patla
    worker.cancel()

    assert worker.isInterruptionRequested() is True


def test_check_cancel_kontrol_hatasini_yutar():
    class PatlakKontrol(BaseWorker):
        def isInterruptionRequested(self):
            raise RuntimeError('kontrol yok')

    PatlakKontrol().check_cancel()  # hata sizmamali


class _PatlakSinyal:
    """Sinyal kaynagi silinmis gibi emit'i patlatan sahte sinyal."""

    def connect(self, *args):
        pass

    def emit(self, *args):
        raise RuntimeError('sinyal kaynagi silinmis')


def test_run_log_sinyali_hatasini_yutar():
    worker = _MiniWorker()
    worker.log = _PatlakSinyal()

    ok, fail, logs, progress = _run(worker)

    assert ok is None and fail is None
    assert worker.ran is True


def test_run_iptal_sinyalleri_hatasini_yutar():
    worker = _MiniWorker()
    worker.cancel()
    worker.log = _PatlakSinyal()
    worker.failed = _PatlakSinyal()

    ok, fail, logs, progress = _run(worker)

    assert ok is None and fail is None
    assert worker.ran is False


def test_run_hata_yolu_log_hatasini_yutar():
    class PatlakIs(BaseWorker):
        def _work(self):
            raise ValueError('kötü değer')

    worker = PatlakIs()
    worker.log = _PatlakSinyal()

    ok, fail, logs, progress = _run(worker)

    assert ok is None
    assert fail == 'ValueError: kötü değer'


def test_worker_sonuc_ve_log():
    worker = Worker(lambda a, b=1: a + b, 2, b=3)
    ok, fail, logs, progress = _run(worker)
    assert ok == 5 and fail is None
    assert any('Arka plan isi başladı' in line for line in logs)


def test_worker_adb_hatasi_ham_mesaj():
    def boom():
        raise AdbError('cihaz yok')
    ok, fail, logs, progress = _run(Worker(boom))
    assert ok is None
    assert fail == 'cihaz yok'
    assert any('başarısız' in line for line in logs)


def test_worker_diger_hata_tip_onekli():
    def boom():
        raise ValueError('kötü değer')
    ok, fail, logs, progress = _run(Worker(boom))
    assert fail == 'ValueError: kötü değer'


def test_worker_silent_log_yaymaz():
    worker = Worker(lambda: 1, silent=True)
    ok, fail, logs, progress = _run(worker)
    assert ok == 1 and fail is None
    assert logs == []


# --- Yardimcilar -------------------------------------------------------------

def test_is_system_apk():
    assert is_system_apk('/system/app/Foo/Foo.apk')
    assert is_system_apk('  /SYSTEM/priv-app/Bar.apk ')
    assert is_system_apk('/product/app/X.apk')
    assert is_system_apk('/apex/com.foo/base.apk')
    assert not is_system_apk('/data/app/~~x/com.foo/base.apk')
    assert not is_system_apk('')
    assert not is_system_apk(None)


def test_fail_text():
    assert _fail_text(AdbError('adbd kapalı')) == 'adbd kapalı'
    assert _fail_text(ValueError('v')) == 'ValueError: v'


def test_check_user_id_dogrulama():
    assert check_user_id(0) == 0
    assert check_user_id('7') == 7
    assert check_user_id(' 12 ') == 12
    with pytest.raises(AdbError):
        check_user_id(-1)
    with pytest.raises(AdbError):
        check_user_id(True)
    with pytest.raises(AdbError):
        check_user_id('abc')
    with pytest.raises(AdbError):
        check_user_id(3.5)


def test_require_user_scope_user0_kontrol_etmez():
    _require_user_scope(object(), ('yok_boyle_metot',), 0)


def test_require_user_scope_destek_yoksa_hata():
    class OwnerOnly:
        def disable_user(self, target, pkg):
            pass

    with pytest.raises(AdbError) as excinfo:
        _require_user_scope(OwnerOnly(), ('disable_user',), 3)
    assert 'user_id desteği sunmuyor' in str(excinfo.value)


def test_require_user_scope_kwargs_kabul_eder():
    class Esnek:
        def disable_user(self, target, pkg, **kwargs):
            pass

    _require_user_scope(Esnek(), ('disable_user',), 3)


def test_require_user_scope_eksik_metot_reddeder():
    with pytest.raises(AdbError):
        _require_user_scope(object(), ('hayali',), 3)


class _ApiMotor:
    def __init__(self):
        self.gorulen = []

    def modern(self, target, pkg, user_id=0):
        self.gorulen.append(('modern', target, pkg, user_id))

    def legacy(self, target, pkg):
        self.gorulen.append(('legacy', target, pkg))

    def esnek(self, target, pkg, **kw):
        self.gorulen.append(('esnek', target, pkg, kw.get('user_id')))


def test_call_user_method_modern_legacy_ve_esnek():
    motor = _ApiMotor()
    _call_user_method(motor, 'modern', 't', 'p', user_id=2)
    _call_user_method(motor, 'legacy', 't', 'p', user_id=0)
    _call_user_method(motor, 'esnek', 't', 'p', user_id=4)
    assert motor.gorulen == [('modern', 't', 'p', 2), ('legacy', 't', 'p'),
                             ('esnek', 't', 'p', 4)]


def test_call_user_method_legacy_user1_reddeder():
    with pytest.raises(AdbError) as excinfo:
        _call_user_method(_ApiMotor(), 'legacy', 't', 'p', user_id=5)
    assert 'user_id desteği sunmuyor' in str(excinfo.value)


def test_call_user_method_eksik_api():
    with pytest.raises(AdbError) as excinfo:
        _call_user_method(_ApiMotor(), 'hayali', 't', 'p', user_id=0)
    assert 'bulunamadı' in str(excinfo.value)


def test_call_user_method_imza_okunamazsa_user0_ile_cagirir(monkeypatch):
    motor = _ApiMotor()

    def patlak_signature(method):
        raise TypeError('imza okunamadi')

    monkeypatch.setattr(inspect, 'signature', patlak_signature)
    _call_user_method(motor, 'legacy', 't', 'p', user_id=0)

    assert motor.gorulen == [('legacy', 't', 'p')]


# --- format_action_result ----------------------------------------------------

def test_format_action_result_temel():
    res = {'ok': 1, 'fail': 1, 'action': 'disable',
           'details': [('com.a', True, 'tamam (dogrulandi)'),
                       ('com.b', False, 'koruma listesinde')]}
    text = format_action_result(res)
    assert text.startswith('1 başarılı, 1 başarısız/atlandı.')
    assert '+ com.a' in text
    assert 'X com.b: koruma listesinde' in text
    assert 'Ipucu:' in text


def test_format_action_result_user_snap_dost_ad_ve_iptal():
    res = {'ok': 1, 'fail': 0, 'action': 'disable', 'user_id': 2,
           'auto_snap': 'snap-9', 'cancelled': 1,
           'details': [('com.a', True, 'tamam (dogrulandi)')]}
    text = format_action_result(res, name_of=lambda p: 'Dost Ad')
    assert 'İşlem kullanıcısı: user 2' in text
    assert "Paket durumu snapshot'ı: snap-9" in text
    assert 'durduruldu; sonuç kısmi olabilir' in text
    assert '+ Dost Ad (com.a)' in text


def test_format_action_result_smart_mesaji_ekler():
    res = {'ok': 1, 'fail': 0, 'action': 'smart',
           'details': [('com.a', True, 'disable ile kapatildi (güvenli)')]}
    text = format_action_result(res)
    assert '+ com.a — disable ile kapatildi (güvenli)' in text


def test_format_action_result_kirpma():
    details = [('com.a{:03d}'.format(i), True, 'tamam') for i in range(65)]
    res = {'ok': 65, 'fail': 0, 'action': 'enable', 'details': details}
    text = format_action_result(res, max_items=60)
    assert text.startswith('65 başarılı, 0 başarısız/atlandı.')
    assert '+ com.a059' in text
    assert '+ com.a060' not in text
    assert '… ve 5 uygulama daha' in text


def test_format_action_result_hatali_kirpma():
    details = [('com.a{:03d}'.format(i), False, 'hata') for i in range(3)]
    res = {'ok': 0, 'fail': 3, 'action': 'disable', 'details': details}
    text = format_action_result(res, max_items=1)

    assert 'X com.a000: hata' in text
    assert '… ve 2 uygulama daha.' in text


def test_format_action_result_bos_eylem():
    res = {'ok': 0, 'fail': 0, 'action': '', 'details': []}
    assert format_action_result(res) == '0 başarılı, 0 başarısız/atlandı.'


def test_format_action_result_yeni_eylem_adini_yazar():
    res = {'ok': 1, 'fail': 0, 'action': 'weird',
           'details': [('com.a', True, 'ok')]}
    assert 'Yapilan işlem (weird):' in format_action_result(res)


def test_format_action_result_ad_hatasini_yutar():
    res = {'ok': 1, 'fail': 0, 'action': 'enable',
           'details': [('com.a', True, 'tamam')]}

    def patlak_ad(pkg):
        raise RuntimeError('ad okunamadi')

    text = format_action_result(res, name_of=patlak_ad)

    assert '+ com.a' in text


# --- AppScanWorker -----------------------------------------------------------

class ScanEngine:
    """AppScanWorker'in cagirdigi tarama API'sini taklit eder."""

    def __init__(self):
        self.calls = []
        self.detailed = []
        self.all_detailed = None
        self.all_detailed_error = None
        self.labels = {}
        self.labels_error = None
        self.running_raw = 'RAW'
        self.running_result = set()
        self.restricted = set()

    def connect(self, target, cancel_check=None):
        self.calls.append(('connect', target))

    def list_packages_detailed(self, target, include_system, use_cache=False):
        self.calls.append(('list_packages_detailed', include_system, use_cache))
        if include_system:
            if self.all_detailed_error is not None:
                raise self.all_detailed_error
            if self.all_detailed is not None:
                return self.all_detailed
        return self.detailed

    def app_labels(self, target):
        if self.labels_error is not None:
            raise self.labels_error
        return self.labels

    def running_processes(self, target):
        return self.running_raw

    def parse_running_packages(self, raw, eligible):
        self.calls.append(('parse_running', raw, set(eligible)))
        return set(self.running_result)

    def bulk_restricted(self, target):
        return self.restricted

    def app_status(self, restricted, pkg):
        return 'Kısıtlı' if pkg in restricted else 'Normal'

    def app_status_fallback(self, target, pkg):
        self.calls.append(('fallback', pkg))
        return 'Tekil'


def test_app_scan_temel_akis():
    engine = ScanEngine()
    engine.detailed = [
        _entry('com.a', apk='/data/app/com.a/base.apk'),
        _entry('com.b', enabled=False, apk='/system/app/B/B.apk'),
        _entry('com.c', installed_user0=False),
    ]
    engine.labels = {'com.a': 'A Uygulaması'}
    engine.running_result = {'com.a'}
    engine.restricted = {'com.b'}
    presence = []
    worker = AppScanWorker(engine, 'tv-1', include_system=False)
    ok, fail, logs, progress = _run(worker, presence)

    assert fail is None
    assert [a['package'] for a in ok] == ['com.a', 'com.b', 'com.c']
    by = {a['package']: a for a in ok}
    assert by['com.a'] == {'package': 'com.a', 'status': 'Normal',
                           'running': 'Evet', 'enabled': True,
                           'installed_user0': True, 'system': False,
                           'label': 'A Uygulaması'}
    assert by['com.b']['status'] == 'Kısıtlı'
    assert by['com.b']['running'] == 'Hayir'  # devre dışı: çalışıyor sayılmaz
    assert by['com.b']['system'] is True
    assert by['com.c']['running'] == 'Hayir'  # kurulu değil: aday değil
    assert by['com.c']['label'] == ''
    assert presence == [{'present': {'com.a', 'com.b'}, 'disabled': {'com.b'}}]
    assert progress[-1] == (3, 3)
    assert any('3 paket' in line for line in logs)


def test_app_scan_sistem_paketlerini_atlar_ve_fallback():
    engine = ScanEngine()
    engine.detailed = [_entry('com.android.foo'), _entry('com.other')]
    engine.all_detailed_error = AdbError('bulk yok')
    presence = []
    worker = AppScanWorker(engine, 'tv-1', include_system=False)
    ok, fail, logs, progress = _run(worker, presence)

    assert fail is None
    assert [a['package'] for a in ok] == ['com.other']
    assert progress[-1] == (2, 2)
    # include_system cagrisi hata verdi: presence yalniz detailed'dan uretilir
    assert presence == [{'present': {'com.android.foo', 'com.other'},
                         'disabled': set()}]


def test_app_scan_include_system_suzmez():
    engine = ScanEngine()
    engine.detailed = [_entry('com.android.foo')]
    engine.all_detailed = engine.detailed
    worker = AppScanWorker(engine, 'tv-1', include_system=True)
    ok, fail, logs, progress = _run(worker)
    assert [a['package'] for a in ok] == ['com.android.foo']


def test_app_scan_surec_okunamazsa_bilinmiyor():
    engine = ScanEngine()
    engine.detailed = [_entry('com.a')]
    engine.running_raw = ''
    worker = AppScanWorker(engine, 'tv-1')
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok[0]['running'] == 'Bilinmiyor'
    assert any('bilinmiyor olarak gösterilecek' in line for line in logs)


def test_app_scan_bulk_yoksa_tekil_kontrol():
    engine = ScanEngine()
    engine.detailed = [_entry('com.a'), _entry('com.b')]
    engine.restricted = None
    worker = AppScanWorker(engine, 'tv-1')
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert [a['status'] for a in ok] == ['Tekil', 'Tekil']
    assert any('tekil kontrol' in line for line in logs)
    assert ('fallback', 'com.a') in engine.calls


def test_app_scan_etiket_temizligi():
    engine = ScanEngine()
    engine.detailed = [_entry('com.a'), _entry('com.b'),
                       _entry('com.c'), _entry('com.d')]
    engine.labels = {'com.a': 'com.a',          # paket adiyla ayni
                     'com.b': 'com.other.app',  # paket gibi gorunen etiket
                     'com.c': 'com.c ',         # bosluklu ayni ad
                     'com.d': 'Dost Ad'}
    worker = AppScanWorker(engine, 'tv-1')
    ok, fail, logs, progress = _run(worker)

    labels = {a['package']: a['label'] for a in ok}
    assert labels == {'com.a': '', 'com.b': '', 'com.c': '',
                      'com.d': 'Dost Ad'}


def test_app_scan_etiket_hatasi_yutulur():
    engine = ScanEngine()
    engine.detailed = [_entry('com.a')]
    engine.labels_error = RuntimeError('dumpsys çöktü')
    worker = AppScanWorker(engine, 'tv-1')
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok[0]['label'] == ''
    assert not any('adi cihazdan okundu' in line for line in logs)


def test_app_scan_etiket_sozluk_degilse_yok_sayilir():
    engine = ScanEngine()
    engine.detailed = [_entry('com.a')]
    engine.labels = ['liste']  # sozluk beklenirken liste
    worker = AppScanWorker(engine, 'tv-1')
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok[0]['label'] == ''


def test_app_scan_dongu_ilerlemesi_25_pakette_bildirir():
    engine = ScanEngine()
    engine.detailed = [_entry('com.p{:03d}'.format(i)) for i in range(1, 26)]
    worker = AppScanWorker(engine, 'tv-1')
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert len(ok) == 25
    assert progress == [(25, 25), (25, 25)]


def test_app_scan_dongu_ortasinda_iptal():
    engine = ScanEngine()
    engine.detailed = [_entry('com.a'), _entry('com.b')]
    worker = AppScanWorker(engine, 'tv-1')
    original = engine.app_status

    def status(restricted, pkg):
        worker.cancel()
        return original(restricted, pkg)

    engine.app_status = status
    ok, fail, logs, progress = _run(worker)

    assert ok is None
    assert fail == 'kullanıcı durdurdu'
    assert any('durduruldu' in line for line in logs)


# --- BulkActionWorker --------------------------------------------------------

class BulkEngine:
    """BulkActionWorker'in cagirdigi API'yi taklit eder."""

    def __init__(self):
        self.calls = []
        self.entries = []
        self.restricted = set()
        self.fail_for = set()

    def connect(self, target, cancel_check=None):
        self.calls.append(('connect', target))

    def list_packages_detailed(self, target, include_system, use_cache=False,
                               user_id=0):
        self.calls.append(('list_packages_detailed', include_system,
                           use_cache, user_id))
        return self.entries

    def restrict(self, target, pkg, user_id=0):
        self.calls.append(('restrict', pkg, user_id))
        if pkg in self.fail_for:
            raise AdbError('kısıtlanamadı: ' + pkg)
        self.restricted.add(pkg)

    def unrestrict(self, target, pkg, user_id=0):
        self.calls.append(('unrestrict', pkg, user_id))
        if pkg in self.fail_for:
            raise AdbError('serbest bırakılamadı: ' + pkg)
        self.restricted.discard(pkg)


def test_bulk_restrict_temel():
    engine = BulkEngine()
    worker = BulkActionWorker(engine, 'tv-1', ['com.a', 'com.b'],
                              restrict=True, protected={'com.b'})
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['ok'] == 1 and ok['skip'] == 1
    assert ok['action'] == 'restrict' and ok['user_id'] == 0
    assert ok['details'] == [('com.a', True, 'tamam'),
                             ('com.b', False, 'koruma listesinde')]
    assert ok['package_states'] == {}
    assert engine.restricted == {'com.a'}
    assert progress == [(1, 2), (2, 2)]


def test_bulk_unrestrict_temel():
    engine = BulkEngine()
    engine.restricted = {'com.a'}
    worker = BulkActionWorker(engine, 'tv-1', ['com.a'],
                              restrict=False, protected=())
    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 1 and ok['action'] == 'unrestrict'
    assert engine.restricted == set()


def test_bulk_validate_paketleri_suzer():
    engine = BulkEngine()
    engine.entries = [_entry('com.a', enabled=True, installed_user0=True),
                      _entry('com.b', enabled=False, installed_user0=True)]
    worker = BulkActionWorker(engine, 'tv-1', ['com.a', 'com.b'],
                              restrict=True, protected=(),
                              validate_packages=True)
    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 1 and ok['skip'] == 1
    assert ok['details'] == [
        ('com.a', True, 'tamam'),
        ('com.b', False, 'Paket artık etkin veya kurulu değil.')]
    assert ok['package_states'] == {
        'com.a': {'enabled': True, 'installed_user0': True},
        'com.b': {'enabled': False, 'installed_user0': True}}
    assert ('list_packages_detailed', True, False, 0) in engine.calls


def test_bulk_hatali_paket_atlanir():
    engine = BulkEngine()
    engine.fail_for = {'com.b'}
    worker = BulkActionWorker(engine, 'tv-1', ['com.a', 'com.b'],
                              restrict=True, protected=())
    ok, fail, logs, progress = _run(worker)

    assert ok['ok'] == 1 and ok['skip'] == 1
    assert ok['details'][1] == ('com.b', False, 'kısıtlanamadı: com.b')
    assert any('kısıtlanamadı: com.b' in line for line in logs)


def test_bulk_iptal_kalanlari_isaretler():
    engine = BulkEngine()
    worker = BulkActionWorker(engine, 'tv-1', ['com.a', 'com.b', 'com.c'],
                              restrict=True, protected=())
    original = engine.restrict

    def restrict(target, pkg, user_id=0):
        original(target, pkg, user_id=user_id)
        worker.cancel()

    engine.restrict = restrict
    ok, fail, logs, progress = _run(worker)

    assert fail is None
    assert ok['ok'] == 1 and ok['skip'] == 2 and ok['cancelled'] == 2
    assert ok['details'][1:] == [('com.b', False, 'kullanıcı durdurdu'),
                                 ('com.c', False, 'kullanıcı durdurdu')]
    assert any('durdurdu' in line for line in logs)
    assert progress == [(1, 3), (2, 3), (3, 3)]


def test_bulk_user_scope_yoksa_reddedilir():
    class OwnerOnly:
        def restrict(self, target, pkg):
            raise AssertionError('çağrılmamalıydı')

    worker = BulkActionWorker(OwnerOnly(), 'tv-1', ['com.a'], restrict=True,
                              protected=(), user_id=3)
    ok, fail, logs, progress = _run(worker)

    assert ok is None
    assert 'user_id desteği sunmuyor' in fail


def test_bulk_gecersiz_user_id_insada_reddedilir():
    with pytest.raises(AdbError):
        BulkActionWorker(BulkEngine(), 'tv-1', ['com.a'], restrict=True,
                         protected=(), user_id=-1)
