# -*- coding: utf-8 -*-
"""AdbEngine ses seviyesi testleri (FakeEngine: ADB yok).

Kapsam: get_volume_info (hizli yol, media yedegi, dumpsys audio yedegi ve
hatalari), get_volume yuzde hesabi, _set_volume_steps kademe dogrulamalari,
set_volume_level ve set_volume (kirpma/yuvarlama). Cihaz kullanilmaz.
"""
import pytest

from mibox_app.adb_engine import AdbEngine, AdbError, AdbResult

MEDIA_GET = ['cmd', 'media_session', 'volume', '--stream', '3', '--get']
MEDIA_YEDEK = ['media', 'volume', '--stream', '3', '--get']


class ShellEngine(AdbEngine):
    """shell()/run() yerine kaydeden ve sahte yanit ureten motor."""

    def __init__(self, handler):
        super().__init__(adb_path='fake-adb')
        self.calls = []
        self._handler = handler

    def _handle(self, call):
        self.calls.append(call)
        result = self._handler(call)
        if result is None:
            raise AssertionError('Beklenmeyen ADB cagrisi: {}'.format(call))
        return result

    def shell(self, target, *cmd, **kwargs):
        return self._handle([str(c) for c in cmd])

    def run(self, args, timeout=30, binary=False, quiet_first=False,
            preserve_output_whitespace=False, cancel_check=None,
            hide_shell_from_trace=False):
        return self._handle([str(a) for a in args])


def _ses_handler(volume='7', aralik=True, dumpsys='', keyevent_yanit=None):
    def handler(call):
        if call == MEDIA_GET:
            out = 'volume is {}'.format(volume)
            if aralik:
                out += ', range [0..15]'
            return AdbResult(0, out + '\n', '')
        if call[:2] == ['input', 'keyevent']:
            return keyevent_yanit or AdbResult(0, '', '')
        if call[:2] == ['dumpsys', 'audio']:
            return AdbResult(0, dumpsys, '')
        return None
    return handler


# --- get_volume_info ---------------------------------------------------------

def test_get_volume_info_hizli_yol():
    eng = ShellEngine(_ses_handler(volume='7'))
    assert eng.get_volume_info('S') == (7, 0, 15)
    assert eng.calls == [MEDIA_GET]


def test_get_volume_info_aralik_yoksa_varsayilan():
    eng = ShellEngine(_ses_handler(volume='3', aralik=False))
    assert eng.get_volume_info('S') == (3, 0, 15)


def test_get_volume_info_media_yedegi():
    def handler(call):
        if call == MEDIA_GET:
            raise AdbError('bilinmeyen komut')
        if call == MEDIA_YEDEK:
            return AdbResult(0, 'volume is 9, range [0..30]\n', '')
        return None

    eng = ShellEngine(handler)
    assert eng.get_volume_info('S') == (9, 0, 30)
    assert eng.calls == [MEDIA_GET, MEDIA_YEDEK]


def test_get_volume_info_dumpsys_audio_yedegi():
    def handler(call):
        if call in (MEDIA_GET, MEDIA_YEDEK):
            raise AdbError('yok')
        if call[:2] == ['dumpsys', 'audio']:
            return AdbResult(
                0,
                '- STREAM_MUSIC:\n'
                '    streamVolume: 5\n'
                '    Min: 1\n'
                '    Max: 11\n'
                '- STREAM_RING:\n', '')
        return None

    eng = ShellEngine(handler)
    assert eng.get_volume_info('S') == (5, 1, 11)


def test_get_volume_info_current_yedegi():
    def handler(call):
        if call in (MEDIA_GET, MEDIA_YEDEK):
            raise AdbError('yok')
        if call[:2] == ['dumpsys', 'audio']:
            return AdbResult(
                0,
                'STREAM_MUSIC:\n'
                '  Current: 4\n'
                '- STREAM_RING:\n', '')
        return None

    eng = ShellEngine(handler)
    assert eng.get_volume_info('S') == (4, 0, 15)


def test_get_volume_info_hicbir_yol_calisamazsa_hata():
    def handler(call):
        if call in (MEDIA_GET, MEDIA_YEDEK):
            raise AdbError('yok')
        if call[:2] == ['dumpsys', 'audio']:
            return AdbResult(0, 'STREAM_RING: 3\n', '')
        return None

    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.get_volume_info('S')
    assert 'ses aralığı okunamadı' in str(exc.value)


# --- get_volume --------------------------------------------------------------

def test_get_volume_yuzde_hesabi():
    eng = ShellEngine(_ses_handler(volume='7'))
    assert eng.get_volume('S') == 47

    eng2 = ShellEngine(_ses_handler(volume='15'))
    assert eng2.get_volume('S') == 100


def test_get_volume_gecersiz_aralikta_50():
    def handler(call):
        if call == MEDIA_GET:
            return AdbResult(0, 'volume is 5, range [5..5]\n', '')
        return None

    eng = ShellEngine(handler)
    assert eng.get_volume('S') == 50


def test_get_volume_okunamazsa_50():
    def handler(call):
        raise AdbError('yok')

    eng = ShellEngine(handler)
    assert eng.get_volume('S') == 50


# --- _set_volume_steps -------------------------------------------------------

def test_set_volume_steps_gecersiz_aralik():
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError) as exc:
        eng._set_volume_steps('S', 5, 5, 5, 5, 10)
    assert 'geçersiz' in str(exc.value)

    with pytest.raises(AdbError):
        eng._set_volume_steps('S', 5, 20, 0, 15, 10)
    assert eng.calls == []


def test_set_volume_steps_seviye_disinda():
    eng = ShellEngine(lambda call: None)
    with pytest.raises(AdbError) as exc:
        eng._set_volume_steps('S', 20, 5, 0, 15, 10)
    assert 'aralığın dışında' in str(exc.value)
    assert eng.calls == []


def test_set_volume_steps_artirir():
    eng = ShellEngine(_ses_handler())
    assert eng._set_volume_steps('S', 7, 5, 0, 15, 10) is True
    assert eng.calls == [['input', 'keyevent', '24'],
                         ['input', 'keyevent', '24']]


def test_set_volume_steps_azaltir():
    eng = ShellEngine(_ses_handler())
    assert eng._set_volume_steps('S', 5, 7, 0, 15, 10) is True
    assert eng.calls == [['input', 'keyevent', '25'],
                         ['input', 'keyevent', '25']]


def test_set_volume_steps_tus_hatasi():
    eng = ShellEngine(_ses_handler(
        keyevent_yanit=AdbResult(1, '', 'tuş çalışmadı')))
    with pytest.raises(AdbError) as exc:
        eng._set_volume_steps('S', 6, 5, 0, 15, 10)
    assert 'tuş çalışmadı' in str(exc.value)


# --- set_volume_level / set_volume ------------------------------------------

def test_set_volume_level_basarili():
    eng = ShellEngine(_ses_handler(volume='5'))
    assert eng.set_volume_level('S', 8) is True
    assert eng.calls.count(['input', 'keyevent', '24']) == 3


def test_set_volume_level_hatasi():
    def handler(call):
        raise AdbError('yok')

    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.set_volume_level('S', 8)
    assert 'Ses seviyesi ayarlanamadı' in str(exc.value)


def test_set_volume_level_cihaz_araligi_disinda():
    eng = ShellEngine(_ses_handler(volume='5'))
    with pytest.raises(AdbError) as exc:
        eng.set_volume_level('S', 99)
    assert 'Ses seviyesi ayarlanamadı' in str(exc.value)


def test_set_volume_yuzde_ile():
    eng = ShellEngine(_ses_handler(volume='5'))
    assert eng.set_volume('S', 50) is True
    assert eng.calls.count(['input', 'keyevent', '24']) == 3


def test_set_volume_kirpma_ve_sifir():
    eng = ShellEngine(_ses_handler(volume='5'))
    assert eng.set_volume('S', 250) is True
    assert eng.calls.count(['input', 'keyevent', '24']) == 10

    eng2 = ShellEngine(_ses_handler(volume='5'))
    assert eng2.set_volume('S', -20) is True
    assert eng2.calls.count(['input', 'keyevent', '25']) == 5


def test_set_volume_hatasi():
    def handler(call):
        raise AdbError('yok')

    eng = ShellEngine(handler)
    with pytest.raises(AdbError) as exc:
        eng.set_volume('S', 50)
    assert 'Ses seviyesi ayarlanamadı' in str(exc.value)
