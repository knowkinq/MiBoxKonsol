# -*- coding: utf-8 -*-
"""Stage sinifi ve run_stage yurutucu testleri (sahte motor; gercek islem yok).

Snapshot ve gecmis yazimi monkeypatch ile taklit edilir; hicbir dosya, cihaz
veya ag kullanilmaz.
"""
import pytest

from mibox_app.adb_engine import AdbError
from mibox_app.stage import Stage, run_stage
from mibox_app.workers import CancelledError


class StageEngine:
    """run_stage'in cagirdigi motor yuzeyini taklit eden kayit tutucu."""

    def __init__(self):
        self.calls = []
        self.uninstalled = set()
        self.disabled = set()
        self.dogrulama_basarisiz = False
        self.smart_sonuc = ('disable', 'sonuc')
        self.hata = {}

    def _kayit(self, ad, pkg):
        self.calls.append((ad, pkg))
        if ad in self.hata:
            raise AdbError(self.hata[ad])

    def connect(self, target, cancel_check=None):
        self.calls.append(('connect', target, cancel_check))
        if 'connect' in self.hata:
            raise AdbError(self.hata['connect'])

    def uninstall_user(self, target, pkg):
        self._kayit('uninstall_user', pkg)
        if not self.dogrulama_basarisiz:
            self.uninstalled.add(pkg)

    def is_uninstalled_for_user(self, target, pkg):
        self.calls.append(('is_uninstalled_for_user', pkg))
        return pkg in self.uninstalled

    def disable_user(self, target, pkg):
        self._kayit('disable_user', pkg)
        if not self.dogrulama_basarisiz:
            self.disabled.add(pkg)

    def is_disabled(self, target, pkg):
        self.calls.append(('is_disabled', pkg))
        return pkg in self.disabled

    def enable(self, target, pkg):
        self._kayit('enable', pkg)

    def install_existing(self, target, pkg):
        self._kayit('install_existing', pkg)

    def restrict(self, target, pkg):
        self._kayit('restrict', pkg)

    def unrestrict(self, target, pkg):
        self._kayit('unrestrict', pkg)

    def clear_data(self, target, pkg):
        self._kayit('clear_data', pkg)

    def force_stop(self, target, pkg):
        self._kayit('force_stop', pkg)

    def smart_remove(self, target, pkg):
        self._kayit('smart_remove', pkg)
        return self.smart_sonuc

    def invalidate_pkg_cache(self, target):
        self.calls.append(('invalidate_pkg_cache', target))
        if 'invalidate' in self.hata:
            raise AdbError('onbellek hatasi')


@pytest.fixture
def snap(monkeypatch):
    kayit = {'sayi': 0, 'is_cancelled': None, 'hata': None}

    def fake_take(engine, target, is_cancelled=None):
        kayit['sayi'] += 1
        kayit['is_cancelled'] = is_cancelled
        if kayit['hata'] is not None:
            raise kayit['hata']
        return ('snap-1', None)

    monkeypatch.setattr('mibox_app.snapshot.take', fake_take)
    return kayit


@pytest.fixture
def hist(monkeypatch):
    kayit = {'cagrilar': []}

    def fake_append(target, action, details, user_id=0):
        kayit['cagrilar'].append((target, action, list(details)))

    monkeypatch.setattr('mibox_app.history.append_many', fake_append)
    return kayit


class TestStageSinifi:
    def test_add_tekrar_eklenmez(self):
        s = Stage()
        assert s.add('disable', 'com.a') is True
        assert s.add('disable', 'com.a') is False
        assert s.add('disable', 'com.b') is True
        assert s.count() == 2

    def test_add_many(self):
        s = Stage()
        assert s.add_many('clear', ['com.a', 'com.b', 'com.a']) == 2
        assert s.items() == [('clear', 'com.a'), ('clear', 'com.b')]

    def test_remove(self):
        s = Stage()
        s.add('stop', 'com.a')
        assert s.remove('stop', 'com.a') is True
        assert s.remove('stop', 'com.a') is False
        assert s.items() == []

    def test_items_with_tokens_kimlik_verir(self):
        s = Stage()
        s.add('disable', 'com.a')
        s.add('disable', 'com.b')
        assert s.items_with_tokens() == [
            ('disable', 'com.a', 1), ('disable', 'com.b', 2)]

    def test_yeniden_eklenen_yeni_kimlik_alir(self):
        s = Stage()
        s.add('disable', 'com.a')
        s.add('disable', 'com.b')
        s.remove('disable', 'com.a')
        s.add('disable', 'com.a')
        assert s.items_with_tokens() == [
            ('disable', 'com.b', 2), ('disable', 'com.a', 3)]

    def test_remove_if_unchanged_bayat_token_reddedilir(self):
        s = Stage()
        s.add('clear', 'com.a')
        _, _, token = s.items_with_tokens()[0]
        assert s.remove_if_unchanged('clear', 'com.a', token + 99) is False
        assert s.count() == 1
        assert s.remove_if_unchanged('clear', 'com.a', token) is True
        assert s.count() == 0
        assert s.remove_if_unchanged('clear', 'com.a', token) is False

    def test_clear_token_sayaci_devam_eder(self):
        s = Stage()
        s.add('stop', 'com.a')
        s.clear()
        assert s.count() == 0
        assert s.items_with_tokens() == []
        s.add('stop', 'com.a')
        assert s.items_with_tokens() == [('stop', 'com.a', 2)]

    def test_items_kopya_dondurur(self):
        s = Stage()
        s.add('stop', 'com.a')
        liste = s.items()
        liste.append(('stop', 'com.b'))
        assert s.count() == 1

    def test_summary_gruplama(self):
        s = Stage()
        s.add('disable', 'com.a')
        s.add('clear', 'com.b')
        s.add('disable', 'com.c')
        assert s.summary() == {
            'disable': ['com.a', 'com.c'], 'clear': ['com.b']}

    def test_describe_bos(self):
        assert Stage().describe() == []

    def test_describe_satirlari(self):
        s = Stage()
        s.add('disable', 'com.a')
        s.add('uninstall', 'com.b')
        lines = s.describe()
        assert lines[0] == '⏸ Devre dışı bırak (1 paket):'
        assert lines[1].strip() == 'com.a'
        assert lines[2] == '🗑 Kaldır (user 0) (1 paket):'
        assert 'com.b' in lines[3]
        assert '⚠ geri dönüşü zor' in lines[3]

    def test_describe_friendly_adi(self):
        s = Stage()
        s.add('stop', 'com.a')
        assert s.describe(friendly=lambda p: 'Uygulama A')[1].strip() == \
            'com.a  (Uygulama A)'
        assert s.describe(friendly=lambda p: p)[1].strip() == 'com.a'

    def test_describe_bilinmeyen_aksiyon(self):
        s = Stage()
        s.add('weird', 'com.a')
        assert s.describe()[0] == '• weird (1 paket):'

    def test_describe_yirmi_siniri(self):
        s = Stage()
        for i in range(25):
            s.add('stop', 'com.p{}'.format(i))
        lines = s.describe()
        assert lines[-1] == '    ... ve 5 tane daha'
        madde = [ln for ln in lines if ln.startswith('    ') and 'daha' not in ln]
        assert len(madde) == 20
        cagrilan = []
        s.describe(friendly=lambda p: cagrilan.append(p) or p)
        assert len(cagrilan) == 20


@pytest.mark.usefixtures('snap', 'hist')
class TestRunStage:
    def test_tum_aksiyonlar_dagitilir(self):
        eng = StageEngine()
        s = Stage()
        for action in ('uninstall', 'disable', 'enable', 'restore',
                       'restrict', 'unrestrict', 'clear', 'stop'):
            s.add(action, 'com.' + action)
        sonuc = run_stage(eng, 'S', s)
        assert sonuc['ok'] == 8
        assert sonuc['fail'] == 0
        assert sonuc['auto_snap'] == 'snap-1'
        assert sonuc['action'] == 'stage'
        assert ('uninstall_user', 'com.uninstall') in eng.calls
        assert ('disable_user', 'com.disable') in eng.calls
        assert ('enable', 'com.enable') in eng.calls
        assert ('install_existing', 'com.restore') in eng.calls
        assert ('restrict', 'com.restrict') in eng.calls
        assert ('unrestrict', 'com.unrestrict') in eng.calls
        assert ('clear_data', 'com.clear') in eng.calls
        assert ('force_stop', 'com.stop') in eng.calls
        assert ('invalidate_pkg_cache', 'S') in eng.calls
        assert all(d[1] for d in sonuc['details'])
        assert all('(doğrulandı)' in d[2] for d in sonuc['details'])

    def test_gecmise_detaylar_yazilir(self, hist):
        eng = StageEngine()
        s = Stage()
        s.add('stop', 'com.a')
        run_stage(eng, 'S', s)
        assert len(hist['cagrilar']) == 1
        target, action, details = hist['cagrilar'][0]
        assert target == 'S'
        assert action == 'stage'
        assert details == [('stop', 'com.a', True,
                            'Force stop (doğrulandı)')]

    def test_connect_iptal_geri_cagrisi_iletilir(self, snap):
        eng = StageEngine()

        def iptal():
            return False

        run_stage(eng, 'S', [('stop', 'com.a')], is_cancelled=iptal)
        assert ('connect', 'S', iptal) in eng.calls
        assert snap['is_cancelled'] is iptal

    def test_smart_disable_yolu(self, hist):
        eng = StageEngine()
        sonuc = run_stage(eng, 'S', [('smart', 'com.a')])
        assert sonuc['ok'] == 1
        assert sonuc['details'][0][2] == \
            'Akıllı kaldırma: devre dışı bırakıldı ve doğrulandı'
        assert hist['cagrilar'][0][2][0][0] == 'disable'

    def test_smart_uninstall_yolu(self, hist):
        eng = StageEngine()
        eng.smart_sonuc = ('uninstall', 'sonuc')
        sonuc = run_stage(eng, 'S', [('smart', 'com.a')])
        assert sonuc['ok'] == 1
        assert sonuc['details'][0][2] == \
            'Akıllı kaldırma: kullanıcı için kaldırıldı ve doğrulandı'
        assert hist['cagrilar'][0][2][0][0] == 'uninstall'

    def test_smart_beklenmeyen_yontem(self):
        eng = StageEngine()
        eng.smart_sonuc = ('weird', 'sonuc')
        sonuc = run_stage(eng, 'S', [('smart', 'com.a')])
        assert sonuc['fail'] == 1
        assert 'beklenmeyen yöntem' in sonuc['details'][0][2]

    def test_uninstall_dogrulama_basarisiz(self):
        eng = StageEngine()
        eng.dogrulama_basarisiz = True
        sonuc = run_stage(eng, 'S', [('uninstall', 'com.a')])
        assert sonuc['fail'] == 1
        assert 'doğrulama başarısız: hala kurulu' in sonuc['details'][0][2]

    def test_disable_dogrulama_basarisiz(self):
        eng = StageEngine()
        eng.dogrulama_basarisiz = True
        sonuc = run_stage(eng, 'S', [('disable', 'com.a')])
        assert sonuc['fail'] == 1
        assert 'doğrulama başarısız: hala aktif' in sonuc['details'][0][2]

    def test_verify_kapali_dogrulama_yapilmaz(self):
        eng = StageEngine()
        eng.dogrulama_basarisiz = True
        sonuc = run_stage(eng, 'S', [('disable', 'com.a')], verify=False)
        assert sonuc['ok'] == 1
        assert ('is_disabled', 'com.a') not in eng.calls

    def test_bilinmeyen_aksiyon(self):
        eng = StageEngine()
        sonuc = run_stage(eng, 'S', [('weird', 'com.a')])
        assert sonuc['fail'] == 1
        assert 'bilinmeyen aksiyon' in sonuc['details'][0][2]

    def test_koruma_listesi(self):
        eng = StageEngine()
        sonuc = run_stage(eng, 'S', [('clear', 'com.a')],
                          protected={'com.a'})
        assert sonuc['fail'] == 1
        assert sonuc['details'][0][2] == 'koruma listesinde'
        assert ('clear_data', 'com.a') not in eng.calls
        assert sonuc['failed_items'] == [('clear', 'com.a')]

    def test_motor_hatasi_kaydedilir(self):
        eng = StageEngine()
        eng.hata['force_stop'] = 'durdurulamadi'
        loglar = []
        sonuc = run_stage(eng, 'S', [('stop', 'com.a')], log=loglar.append)
        assert sonuc['fail'] == 1
        assert sonuc['details'][0][2] == 'durdurulamadi'
        assert any('durdurulamadi' in ln for ln in loglar)

    def test_log_istisnasi_yutulur(self):
        eng = StageEngine()
        eng.hata['force_stop'] = 'hata'

        def bozuk_log(mesaj):
            if 'snapshot' in mesaj:
                return
            raise RuntimeError('log yok')

        sonuc = run_stage(eng, 'S', [('stop', 'com.a')], log=bozuk_log)
        assert sonuc['fail'] == 1

    def test_connect_hatasi(self, snap):
        eng = StageEngine()
        eng.hata['connect'] = 'baglanti yok'
        sonuc = run_stage(eng, 'S', [('stop', 'com.a'), ('clear', 'com.b')])
        assert sonuc == {
            'ok': 0, 'fail': 2,
            'details': [('com.a', False, 'baglanti yok'),
                        ('com.b', False, 'baglanti yok')],
            'failed_items': [('stop', 'com.a'), ('clear', 'com.b')],
            'action': 'stage', 'auto_snap': None,
        }
        assert snap['sayi'] == 0

    def test_connect_hatasi_iptal_ile_cancelled(self):
        eng = StageEngine()
        eng.hata['connect'] = 'baglanti yok'
        with pytest.raises(CancelledError):
            run_stage(eng, 'S', [('stop', 'com.a')],
                      is_cancelled=lambda: True)

    def test_snapshot_hatasi_korumali_aksiyonlari_durdurur(self, snap):
        snap['hata'] = RuntimeError('snap yok')
        eng = StageEngine()
        s = Stage()
        s.add('disable', 'com.a')
        s.add('clear', 'com.b')
        loglar = []
        sonuc = run_stage(eng, 'S', s, log=loglar.append)
        assert sonuc['fail'] == 1
        assert sonuc['ok'] == 1
        assert 'snapshot' in sonuc['details'][0][2]
        assert ('disable_user', 'com.a') not in eng.calls
        assert ('clear_data', 'com.b') in eng.calls
        assert sonuc['auto_snap'] is None
        assert any('snapshot' in ln and 'alınamadı' in ln for ln in loglar)

    def test_snapshot_cancelled_yukseltilir(self, snap):
        snap['hata'] = CancelledError('kullanici durdurdu')
        with pytest.raises(CancelledError):
            run_stage(StageEngine(), 'S', [('clear', 'com.a')])

    def test_snapshot_hatasi_iptal_ile_cancelled(self, snap):
        snap['hata'] = RuntimeError('snap yok')
        with pytest.raises(CancelledError):
            run_stage(StageEngine(), 'S', [('clear', 'com.a')],
                      is_cancelled=lambda: True)

    def test_iptal_kalanlari_durdurdu_sayar(self):
        eng = StageEngine()
        s = Stage()
        s.add('stop', 'com.a')
        s.add('stop', 'com.b')
        s.add('stop', 'com.c')
        durum = {'n': 0}

        def iptal():
            durum['n'] += 1
            return durum['n'] > 1

        sonuc = run_stage(eng, 'S', s, is_cancelled=iptal)
        assert sonuc['ok'] == 1
        assert sonuc['fail'] == 2
        assert sonuc['details'][1][2] == 'kullanıcı durdurdu'
        assert ('force_stop', 'com.b') not in eng.calls

    def test_iptal_kontrolu_istisnasi_yutulur(self):
        eng = StageEngine()

        def bozuk():
            raise RuntimeError('iptal sorgusu bozuk')

        sonuc = run_stage(eng, 'S', [('stop', 'com.a')], is_cancelled=bozuk)
        assert sonuc['ok'] == 1

    def test_progress_ilerleme_bildirimi(self):
        eng = StageEngine()
        s = Stage()
        s.add('stop', 'com.a')
        s.add('stop', 'com.b')
        bildirimler = []
        run_stage(eng, 'S', s,
                  progress=lambda i, t: bildirimler.append((i, t)))
        assert bildirimler == [(1, 2), (2, 2)]

    def test_progress_istisnasi_yutulur(self):
        eng = StageEngine()

        def bozuk(i, t):
            raise RuntimeError('x')

        assert run_stage(eng, 'S', [('stop', 'com.a')],
                         progress=bozuk)['ok'] == 1

    def test_duz_liste_kabul_edilir(self):
        eng = StageEngine()
        assert run_stage(eng, 'S', [('stop', 'com.a')])['ok'] == 1

    def test_gecmis_hatasi_yutulur(self, monkeypatch):
        def bozuk_append(target, action, details, user_id=0):
            raise RuntimeError('db yok')

        monkeypatch.setattr('mibox_app.history.append_many', bozuk_append)
        eng = StageEngine()
        assert run_stage(eng, 'S', [('stop', 'com.a')])['ok'] == 1

    def test_onbellek_temizleme_hatasi_yutulur(self):
        eng = StageEngine()
        eng.hata['invalidate'] = 'x'
        assert run_stage(eng, 'S', [('stop', 'com.a')])['ok'] == 1
