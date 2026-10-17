# -*- coding: utf-8 -*-
"""Optimizasyon plani testleri: analiz, onbellek temizleme, animasyon, iptal.

Gercek ADB kullanilmaz; motor taklit edilir. Plan adimlari ve mesajlar
sozlesmeye gore dogrulanir.
"""
from types import SimpleNamespace

import pytest

from mibox_app import optimization
from mibox_app.adb_engine import AdbError
from mibox_app.workers import CancelledError


class OptEngine:
    """analyze/run_plan icin motor taklidi; her cagri kaydedilir."""

    def __init__(self):
        self.calls = []
        self.health_values = {'cpu': 20}
        self.health_error = None
        self.anim_values = {'window_animation_scale': '1'}
        self.anim_error = None
        self.trim_result = SimpleNamespace(exit_code=0, output='', error='')
        self.trim_error = None
        self.set_anim_error = None

    def health(self, target):
        self.calls.append(('health', target))
        if self.health_error is not None:
            raise self.health_error
        return dict(self.health_values)

    def animator_scales(self, target):
        self.calls.append(('animator_scales', target))
        if self.anim_error is not None:
            raise self.anim_error
        return dict(self.anim_values)

    def trim_caches(self, target):
        self.calls.append(('trim_caches', target))
        if self.trim_error is not None:
            raise self.trim_error
        return self.trim_result

    def set_animator_scales(self, target, value):
        self.calls.append(('set_animator_scales', target, value))
        if self.set_anim_error is not None:
            raise self.set_anim_error


def test_error_message_bos_mesajda_tip_adini_doner():
    assert optimization._error_message(ValueError('  ')) == 'ValueError'
    assert optimization._error_message(ValueError('x')) == 'x'


def test_analyze_verileri_toplanir():
    engine = OptEngine()
    res = optimization.analyze(engine, 'tv-1')

    assert res == {'health': {'cpu': 20},
                   'animations': {'window_animation_scale': '1'},
                   'warnings': []}
    assert ('health', 'tv-1') in engine.calls
    assert ('animator_scales', 'tv-1') in engine.calls


def test_analyze_bir_probe_hatasi_digerini_gizlemez():
    engine = OptEngine()
    engine.health_error = AdbError('health yok')
    res = optimization.analyze(engine, 'tv-1')

    assert res['health'] == {}
    assert res['animations'] == {'window_animation_scale': '1'}
    assert res['warnings'] == ['Sağlık verileri okunamadı: health yok']


def test_analyze_animasyon_hatasi_uyarir():
    engine = OptEngine()
    engine.anim_error = RuntimeError('')
    res = optimization.analyze(engine, 'tv-1')

    assert res['health'] == {'cpu': 20}
    assert res['animations'] == {}
    assert res['warnings'] == ['Animasyon ayarları okunamadı: RuntimeError']


def test_analyze_iptali_yukseltir():
    def iptal():
        raise CancelledError('kullanıcı durdurdu')

    with pytest.raises(CancelledError):
        optimization.analyze(OptEngine(), 'tv-1', iptal)


def test_analyze_okuma_iptalini_yukseltir():
    engine = OptEngine()
    engine.health_error = CancelledError('durduruldu')

    with pytest.raises(CancelledError):
        optimization.analyze(engine, 'tv-1')


def test_run_plan_animasyon_degeri_dogrulanir():
    with pytest.raises(ValueError):
        optimization.run_plan(OptEngine(), 'tv-1', animation='2')
    with pytest.raises(ValueError):
        optimization.run_plan(OptEngine(), 'tv-1', animation='1.0')


def test_run_plan_bos_plan_reddedilir():
    with pytest.raises(ValueError):
        optimization.run_plan(OptEngine(), 'tv-1')


def test_run_plan_onbellek_temizleme():
    engine = OptEngine()
    progress = []
    res = optimization.run_plan(engine, 'tv-1', trim=True,
                               progress=lambda c, t: progress.append((c, t)))

    assert res['cancelled'] is False
    assert res['before'] is not None and res['after'] is not None
    assert [s['action'] for s in res['steps']] == ['cache']
    assert res['steps'][0]['ok'] is True
    assert res['steps'][0]['message'] == 'Önbellek temizleme tamamlandı.'
    assert ('trim_caches', 'tv-1') in engine.calls
    assert progress == [(1, 1)]


def test_run_plan_animasyon():
    engine = OptEngine()
    res = optimization.run_plan(engine, 'tv-1', animation='0')

    assert res['steps'][0]['ok'] is True
    assert res['steps'][0]['message'] == \
        'Animasyon ölçekleri 0 olarak ayarlandı.'
    assert ('set_animator_scales', 'tv-1', '0') in engine.calls


def test_run_plan_ikisi_sirali():
    engine = OptEngine()
    progress = []
    res = optimization.run_plan(engine, 'tv-1', trim=True, animation='0.5',
                               progress=lambda c, t: progress.append((c, t)))

    assert [s['action'] for s in res['steps']] == ['cache', 'animation']
    assert [s['ok'] for s in res['steps']] == [True, True]
    assert progress == [(1, 2), (2, 2)]


def test_run_plan_trim_hata_mesajlari():
    engine = OptEngine()
    engine.trim_result = SimpleNamespace(exit_code=1, output='',
                                         error='pm list hatasi')
    res = optimization.run_plan(engine, 'tv-1', trim=True)
    assert res['steps'][0]['ok'] is False
    assert res['steps'][0]['message'] == \
        'Önbellek temizleme başarısız: pm list hatasi'

    engine.trim_result = SimpleNamespace(exit_code=2, output='  hata cikti  ',
                                         error='')
    res = optimization.run_plan(engine, 'tv-1', trim=True)
    assert res['steps'][0]['message'] == \
        'Önbellek temizleme başarısız: hata cikti'

    engine.trim_result = SimpleNamespace(exit_code=1, output=None, error=None)
    res = optimization.run_plan(engine, 'tv-1', trim=True)
    assert res['steps'][0]['message'] == \
        'Önbellek temizleme başarısız: çıkış kodu 1'


def test_run_plan_trim_basarili_sayilan_bicimler():
    engine = OptEngine()
    engine.trim_result = SimpleNamespace(exit_code='0', output='', error='')
    res = optimization.run_plan(engine, 'tv-1', trim=True)
    assert res['steps'][0]['ok'] is True

    engine.trim_result = object()  # exit_code alani yok: eski motor uyumu
    res = optimization.run_plan(engine, 'tv-1', trim=True)
    assert res['steps'][0]['ok'] is True
    assert res['steps'][0]['message'] == 'Önbellek temizleme tamamlandı.'


def test_run_plan_trim_istisnasi_mesaja_donusur():
    engine = OptEngine()
    engine.trim_error = AdbError('')
    res = optimization.run_plan(engine, 'tv-1', trim=True)

    assert res['steps'][0]['ok'] is False
    assert res['steps'][0]['message'] == 'Önbellek temizleme başarısız: AdbError'


def test_run_plan_animasyon_istisnasi_mesaja_donusur():
    engine = OptEngine()
    engine.set_anim_error = RuntimeError('yazma reddedildi')
    res = optimization.run_plan(engine, 'tv-1', animation='1')

    assert res['steps'][0]['ok'] is False
    assert res['steps'][0]['message'] == \
        'Animasyon ölçekleri ayarlanamadı: yazma reddedildi'


def test_run_plan_ilk_hata_ikinci_adimi_durdurmaz():
    engine = OptEngine()
    engine.trim_result = SimpleNamespace(exit_code=1, output='x', error='')
    res = optimization.run_plan(engine, 'tv-1', trim=True, animation='1')

    assert [s['ok'] for s in res['steps']] == [False, True]


def test_run_plan_analiz_oncesi_iptal():
    def iptal():
        raise CancelledError('kullanıcı durdurdu')

    engine = OptEngine()
    res = optimization.run_plan(engine, 'tv-1', trim=True, check_cancel=iptal)

    assert res['cancelled'] is True
    assert res['steps'] == []
    assert not any(c[0] == 'trim_caches' for c in engine.calls)


def test_run_plan_islem_oncesi_iptal():
    state = {'n': 0}

    def check_cancel():
        state['n'] += 1
        if state['n'] > 2:  # iki analiz probu gectikten sonra
            raise CancelledError('kullanıcı durdurdu')

    engine = OptEngine()
    res = optimization.run_plan(engine, 'tv-1', trim=True, animation='0',
                               check_cancel=check_cancel)

    assert res['cancelled'] is True
    assert res['steps'] == []
    assert res['before'] is not None and res['after'] is None
    assert not any(c[0] in ('trim_caches', 'set_animator_scales')
                   for c in engine.calls)


def test_run_plan_trim_iptalini_yukseltir():
    engine = OptEngine()
    engine.trim_error = CancelledError('durduruldu')

    res = optimization.run_plan(engine, 'tv-1', trim=True)

    assert res['cancelled'] is True
    assert res['steps'] == []
    assert ('trim_caches', 'tv-1') in engine.calls
