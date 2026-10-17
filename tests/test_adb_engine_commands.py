# -*- coding: utf-8 -*-
"""AdbEngine komut uretimi testleri (FakeEngine: gercek ADB cagrilmaz).

Regresyon odagi:
- launch_resolved 'am start -n <bilesen>' argumanini cihaz shell'inde
  genisletilmeye karsi tek kelime olarak quote'lamali ('$' iceren siniflar).
- Sozdizimine uymayan resolve cikisi am start'a HIC verilmemeli; monkey
  fallback'e dusulmeli.
- set_home_activity 'cmd package set-home-activity' argumanini quote'lamali.
"""
import shlex

import pytest

from mibox_app.adb_engine import AdbEngine, AdbError, AdbResult


class FakeEngine(AdbEngine):
    """run() yerine kaydeden/sahte yanit ureten motor."""

    def __init__(self, handler):
        super().__init__(adb_path='fake-adb')
        self.calls = []
        self._handler = handler

    def run(self, args, timeout=30, binary=False, quiet_first=False,
            preserve_output_whitespace=False, cancel_check=None,
            hide_shell_from_trace=False):
        call = [str(a) for a in args]
        self.calls.append(call)
        result = self._handler(call)
        if result is None:
            raise AssertionError('Beklenmeyen ADB cagrisi: {}'.format(call))
        return result


def _fail_handler(call):
    raise AssertionError('ADB cagrisi olmamaliydi: {}'.format(call))


def _calls(engine, needle):
    return [c for c in engine.calls if needle in c]


# --- launch_resolved -------------------------------------------------------

def test_launch_resolved_bileseni_quote_ile_calistirir():
    def handler(call):
        if 'resolve-activity' in call:
            return AdbResult(0, 'com.foo/.A$B', '')
        if 'am' in call and 'start' in call:
            return AdbResult(0, 'Starting: Intent { cmp=com.foo/.A$B }', '')
        return None

    engine = FakeEngine(handler)
    result = engine.launch_resolved('tv-1', 'com.foo')

    assert result.exit_code == 0
    start_calls = [c for c in engine.calls if 'am' in c and 'start' in c]
    assert len(start_calls) == 1
    comp_arg = start_calls[0][start_calls[0].index('-n') + 1]
    # '$' cihaz shell'inde yeniden genisletilmemesi icin tek kelime olarak
    # quote'lanmis olmali; ham 'com.foo/.A$B' gonderilirse '$B' degiskene
    # donusebilir.
    assert comp_arg == shlex.quote('com.foo/.A$B') == "'com.foo/.A$B'"


def test_launch_resolved_gecersiz_bilesende_am_start_cagrilmaz():
    def handler(call):
        if 'resolve-activity' in call:
            # Bosluk iceren sinif adi shell kelimesini boler: sozdizimi gecersiz.
            return AdbResult(0, 'com.foo/.A B', '')
        if 'monkey' in call:
            return AdbResult(0, 'Events injected: 1', '')
        return None

    engine = FakeEngine(handler)
    result = engine.launch_resolved('tv-1', 'com.foo')

    assert result.exit_code == 0
    assert not any('am' in c and 'start' in c for c in engine.calls)
    assert any('monkey' in c for c in engine.calls), 'monkey fallback cagrilmaliydi'


def test_launch_resolved_basarisiz_am_start_sonrasi_fallback():
    def handler(call):
        if 'resolve-activity' in call:
            return AdbResult(0, 'com.foo/.MainActivity', '')
        if 'am' in call and 'start' in call:
            return AdbResult(1, '', 'Error: Activity not started')
        if 'monkey' in call:
            return AdbResult(0, 'Events injected: 1', '')
        return None

    engine = FakeEngine(handler)
    result = engine.launch_resolved('tv-1', 'com.foo')

    assert result.exit_code == 0
    assert any('monkey' in c for c in engine.calls)


def test_launch_resolved_gecersiz_paket_kabul_etmez():
    engine = FakeEngine(_fail_handler)
    with pytest.raises(AdbError):
        engine.launch_resolved('tv-1', 'com.foo;reboot')
    assert engine.calls == []


def test_launch_resolved_resolve_istisnasi_fallback():
    def handler(call):
        if 'resolve-activity' in call:
            raise AdbError('resolve kopuk')
        if 'monkey' in call:
            return AdbResult(0, 'Events injected: 1', '')
        return None

    engine = FakeEngine(handler)
    result = engine.launch_resolved('tv-1', 'com.foo')

    assert result.exit_code == 0
    assert not any('am' in c and 'start' in c for c in engine.calls)
    assert any('monkey' in c for c in engine.calls)


# --- set_home_activity ------------------------------------------------------

def test_set_home_activity_bileseni_quote_ile_gonderir():
    def handler(call):
        if 'set-home-activity' in call:
            return AdbResult(0, '', '')
        if 'resolve-activity' in call and 'android.intent.category.HOME' in call:
            return AdbResult(0, 'com.foo/.A$B', '')
        return None

    engine = FakeEngine(handler)
    result = engine.set_home_activity('tv-1', 'com.foo/.A$B')

    assert result.exit_code == 0
    set_calls = _calls(engine, 'set-home-activity')
    assert len(set_calls) == 1
    assert set_calls[0][-1] == "'com.foo/.A$B'"


@pytest.mark.parametrize('comp', [
    '',
    'com.foo',
    'com.foo/.A B',
    'com.foo;reboot/.X',
    None,
])
def test_set_home_activity_gecersiz_bilesen_kabul_etmez(comp):
    engine = FakeEngine(_fail_handler)
    with pytest.raises(AdbError):
        engine.set_home_activity('tv-1', comp)
    assert engine.calls == []


def test_set_home_activity_kurulum_sihirbazi_engelini_cozer():
    desired = 'com.spotify.tv.android/.MainActivity'
    wizard = 'com.google.android.tungsten.setupwraith/.SetupWraithActivity'
    state = {'set_home': 0}

    def handler(call):
        if 'set-home-activity' in call:
            state['set_home'] += 1
            return AdbResult(0, '', '')
        if 'resolve-activity' in call and 'android.intent.category.HOME' in call:
            return AdbResult(0, wizard if state['set_home'] <= 1 else desired, '')
        if 'settings' in call or 'am' in call or 'pm' in call:
            return AdbResult(0, '', '')
        return None

    engine = FakeEngine(handler)
    result = engine.set_home_activity('tv-1', desired)

    assert result.exit_code == 0
    assert state['set_home'] == 2, 'engel cozulunce set-home-activity tekrarlanmali'
    assert any('HOME dogrulandi' in note for note in engine.last_home_notes)
    assert any('Kurulum sihirbazi devre dışı bırakıldı' in note
               for note in engine.last_home_notes)
    assert any('Cihaz kurulmus isaretlendi' in note
               for note in engine.last_home_notes)


def test_set_home_activity_fix_setup_kapaliyken_hata_verir():
    wizard = 'com.google.android.tungsten.setupwraith/.SetupWraithActivity'

    def handler(call):
        if 'set-home-activity' in call:
            return AdbResult(0, '', '')
        if 'resolve-activity' in call and 'android.intent.category.HOME' in call:
            return AdbResult(0, wizard, '')
        return None

    engine = FakeEngine(handler)
    with pytest.raises(AdbError):
        engine.set_home_activity('tv-1', 'com.foo/.MainActivity', fix_setup=False)
    assert len(_calls(engine, 'set-home-activity')) == 1


def test_set_home_activity_komut_reddedilirse():
    def handler(call):
        if 'set-home-activity' in call:
            return AdbResult(1, '', 'error: denied')
        return None

    engine = FakeEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.set_home_activity('tv-1', 'com.foo/.Main')
    assert 'HOME ayarlanamadi' in str(exc.value)


def test_set_home_activity_engel_cozulemezse():
    wizard = 'com.setupwizard/.Setup'

    def handler(call):
        if 'set-home-activity' in call:
            return AdbResult(0, '', '')
        if 'resolve-activity' in call and 'android.intent.category.HOME' in call:
            return AdbResult(0, wizard, '')
        if 'settings' in call:
            return AdbResult(0, '', '')
        if 'am' in call and 'force-stop' in call:
            return AdbResult(0, '', '')
        if 'pm' in call and 'disable-user' in call:
            return AdbResult(1, '', 'error: not allowed')
        return None

    engine = FakeEngine(handler)
    with pytest.raises(AdbError) as exc:
        engine.set_home_activity('tv-1', 'com.foo/.Main')
    mesaj = str(exc.value)
    assert 'HOME hala' in mesaj
    assert 'kurulum sihirbazi' in mesaj
    assert any('birakilamadi' in note for note in engine.last_home_notes)


# --- home_activity -----------------------------------------------------------

def test_home_activity_bilesen_satirini_dondurur():
    def handler(call):
        return AdbResult(0, 'priority=0\ncom.foo/.Home\n', '')

    engine = FakeEngine(handler)
    assert engine.home_activity('tv-1') == 'com.foo/.Home'


def test_home_activity_okunamazsa_soru_isareti_dondurur():
    def handler(call):
        raise AdbError('baglanti yok')

    engine = FakeEngine(handler)
    assert engine.home_activity('tv-1') == '?'


# --- open_play_store ---------------------------------------------------------

def test_open_play_store_market_uri_gonderir():
    def handler(call):
        if 'am' in call and 'start' in call:
            return AdbResult(
                0, 'Starting: Intent { act=android.intent.action.VIEW '
                   'dat=market://details?id=com.foo }', '')
        return None

    engine = FakeEngine(handler)
    result = engine.open_play_store('tv-1', 'com.foo')

    assert result.exit_code == 0
    start_calls = [c for c in engine.calls if 'am' in c and 'start' in c]
    assert len(start_calls) == 1
    call = start_calls[0]
    assert call[call.index('-d') + 1] == 'market://details?id=com.foo'
    assert 'android.intent.action.VIEW' in call


def test_open_play_store_hata_metnini_yukseltir():
    def handler(call):
        return AdbResult(0, '', 'Error: Activity not started, unable to resolve Intent')

    engine = FakeEngine(handler)

    with pytest.raises(AdbError, match='Play Store'):
        engine.open_play_store('tv-1', 'com.foo')


def test_open_play_store_cikis_kodu_hatasini_yukseltir():
    def handler(call):
        return AdbResult(1, '', 'adb: device offline')

    engine = FakeEngine(handler)

    with pytest.raises(AdbError, match='Play Store'):
        engine.open_play_store('tv-1', 'com.foo')


@pytest.mark.parametrize('pkg', [
    'com.foo;reboot',
    'com.foo:u5',
    '',
    None,
])
def test_open_play_store_gecersiz_paketi_reddeder(pkg):
    engine = FakeEngine(_fail_handler)

    with pytest.raises(AdbError, match='Geçersiz paket'):
        engine.open_play_store('tv-1', pkg)

    assert engine.calls == [], 'geçersiz paket için ADB çağrılmamalı'
