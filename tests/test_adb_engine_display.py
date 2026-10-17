# -*- coding: utf-8 -*-
"""AdbEngine ekran bilgisi ve ayar testleri (FakeEngine: ADB yok).

Kapsam: display_details okuma varyantlari (genel boyut/yogunluk kaliplari,
override, okuma hatalari), display_info temsilcisi ve boyut/yogunluk/overscan
uygula+sifirla metotlari (dogrulama, hata mesajlari). Cihaz kullanilmaz.
"""
import pytest

from mibox_app.adb_engine import AdbEngine, AdbError, AdbResult


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


def _ekran_handler(size_okuma='Physical size: 1920x1080\n',
                   density_okuma='Physical density: 320\n',
                   overscan_okuma='', display_okuma='',
                   yazma_yanit=None):
    """Okuma ve yazma komutlarini ayirt eden ekran sahte katmani."""

    def handler(call):
        if call == ['wm', 'size']:
            return AdbResult(0, size_okuma, '')
        if call == ['wm', 'density']:
            return AdbResult(0, density_okuma, '')
        if call == ['wm', 'overscan']:
            return AdbResult(0, overscan_okuma, '')
        if call[:2] == ['dumpsys', 'display']:
            return AdbResult(0, display_okuma, '')
        if call[:2] == ['wm', 'size'] and len(call) == 3:
            return yazma_yanit or AdbResult(0, '', '')
        if call[:2] == ['wm', 'density'] and len(call) == 3:
            return yazma_yanit or AdbResult(0, '', '')
        if call[:2] == ['wm', 'overscan'] and len(call) == 3:
            return yazma_yanit or AdbResult(0, '', '')
        return None
    return handler


# --- display_details ---------------------------------------------------------

def test_display_details_genel_kaliplar_ve_override():
    eng = ShellEngine(_ekran_handler(
        size_okuma='size: 1280x720\nOverride size: 960x540\n',
        density_okuma='density: 240\nOverride density: 213\n',
        overscan_okuma='overscan: 10,-5,10,-5\n',
        display_okuma='renderFrameRate 59.94\n'
                      'DeviceProductInfo{name=Mi TV, extra}\n'))
    out = eng.display_details('S')
    assert out['physical_width'] == 1280
    assert out['physical_height'] == 720
    assert out['override_width'] == 960
    assert out['override_height'] == 540
    assert out['width'] == 960
    assert out['height'] == 540
    assert out['physical_density'] == 240
    assert out['override_density'] == 213
    assert out['density'] == 213
    assert out['overscan'] == [10, -5, 10, -5]
    assert out['fps'] == 59.9
    assert out['sink_name'] == 'Mi TV'
    assert out['read_errors'] == []
    assert out['screen_str'] == \
        '960x540 @ 59.9Hz (213 DPI) (Özel Ölçek) · Mi TV'


def test_display_details_okuma_hatalari_kaydedilir():
    def handler(call):
        if call == ['wm', 'size']:
            return AdbResult(1, '', 'size okunamadi')
        if call == ['wm', 'density']:
            return AdbResult(1, '', 'density okunamadi')
        if call == ['wm', 'overscan']:
            raise RuntimeError('overscan patladi')
        if call[:2] == ['dumpsys', 'display']:
            raise AdbError('display kapali')
        return None

    eng = ShellEngine(handler)
    out = eng.display_details('S')
    assert out['read_errors'] == ['size', 'density']
    assert out['width'] == 1920
    assert out['density'] == 320
    assert out['fps'] == 60.0
    assert out['screen_str'] == '1920x1080 @ 60Hz (320 DPI)'


def test_display_details_fps_kalibi():
    eng = ShellEngine(_ekran_handler(display_okuma='fps=24.0\n'))
    assert eng.display_details('S')['fps'] == 24.0


def test_display_details_cozulemeyen_cikti():
    eng = ShellEngine(_ekran_handler(size_okuma='garip cikti\n',
                                     density_okuma='garip cikti\n'))
    out = eng.display_details('S')
    assert out['read_errors'] == ['size', 'density']
    assert out['physical_width'] == 1920
    assert out['physical_density'] == 320


def test_display_info_temsilci():
    class TemsilciEngine(ShellEngine):
        def __init__(self):
            super().__init__(lambda call: None)
            self.detay_calls = []

        def display_details(self, target, timeout=15):
            self.detay_calls.append((target, timeout))
            return {'ok': True}

    eng = TemsilciEngine()
    assert eng.display_info('S', timeout=7) == {'ok': True}
    assert eng.detay_calls == [('S', 7)]


# --- set/reset -----------------------------------------------------------------

def test_set_display_size_gecersiz_degerler():
    eng = ShellEngine(lambda call: None)
    for width, height in ((100, 720), (1280, 100), (9000, 720), ('1280', 720),
                          (1280, 720.5)):
        with pytest.raises(AdbError) as exc:
            eng.set_display_size('S', width, height)
        assert 'Geçersiz çözünürlük' in str(exc.value)
    assert eng.calls == []


def test_set_display_size_basarili():
    eng = ShellEngine(_ekran_handler())
    out = eng.set_display_size('S', 1280, 720)
    assert eng.calls[0] == ['wm', 'size', '1280x720']
    assert out['width'] == 1920


def test_set_display_size_hata():
    eng = ShellEngine(_ekran_handler(
        yazma_yanit=AdbResult(1, 'Error: bad size', '')))
    with pytest.raises(AdbError) as exc:
        eng.set_display_size('S', 1280, 720)
    assert 'Çözünürlük uygulanamadı' in str(exc.value)


def test_reset_display_size_basarili_ve_hata():
    eng = ShellEngine(_ekran_handler())
    eng.reset_display_size('S')
    assert eng.calls[0] == ['wm', 'size', 'reset']

    eng2 = ShellEngine(_ekran_handler(
        yazma_yanit=AdbResult(1, 'Error', '')))
    with pytest.raises(AdbError) as exc:
        eng2.reset_display_size('S')
    assert 'Çözünürlük sıfırlanamadı' in str(exc.value)


def test_set_display_density_gecersiz_degerler():
    eng = ShellEngine(lambda call: None)
    for density in (50, 1001, '320', 320.5):
        with pytest.raises(AdbError) as exc:
            eng.set_display_density('S', density)
        assert 'Geçersiz DPI' in str(exc.value)
    assert eng.calls == []


def test_set_display_density_basarili_ve_hata():
    eng = ShellEngine(_ekran_handler())
    eng.set_display_density('S', 213)
    assert eng.calls[0] == ['wm', 'density', '213']

    eng2 = ShellEngine(_ekran_handler(
        yazma_yanit=AdbResult(1, 'Error', '')))
    with pytest.raises(AdbError) as exc:
        eng2.set_display_density('S', 213)
    assert 'DPI uygulanamadı' in str(exc.value)


def test_reset_display_density_basarili_ve_hata():
    eng = ShellEngine(_ekran_handler())
    eng.reset_display_density('S')
    assert eng.calls[0] == ['wm', 'density', 'reset']

    eng2 = ShellEngine(_ekran_handler(
        yazma_yanit=AdbResult(1, 'Error', '')))
    with pytest.raises(AdbError) as exc:
        eng2.reset_display_density('S')
    assert 'DPI sıfırlanamadı' in str(exc.value)


def test_set_display_overscan_gecersiz_degerler():
    eng = ShellEngine(lambda call: None)
    for deger in ((400, 0, 0, 0), (0, -301, 0, 0), (0, 0, '5', 0)):
        with pytest.raises(AdbError) as exc:
            eng.set_display_overscan('S', *deger)
        assert 'Geçersiz overscan' in str(exc.value)
    assert eng.calls == []


def test_set_display_overscan_basarili_ve_hata():
    eng = ShellEngine(_ekran_handler())
    eng.set_display_overscan('S', 10, -5, 10, -5)
    assert eng.calls[0] == ['wm', 'overscan', '10,-5,10,-5']

    eng2 = ShellEngine(_ekran_handler(
        yazma_yanit=AdbResult(1, 'Error', '')))
    with pytest.raises(AdbError) as exc:
        eng2.set_display_overscan('S', 0, 0, 0, 0)
    assert 'Overscan uygulanamadı' in str(exc.value)


def test_reset_display_overscan_basarili_ve_hata():
    eng = ShellEngine(_ekran_handler())
    eng.reset_display_overscan('S')
    assert eng.calls[0] == ['wm', 'overscan', 'reset']

    eng2 = ShellEngine(_ekran_handler(
        yazma_yanit=AdbResult(1, 'Error', '')))
    with pytest.raises(AdbError) as exc:
        eng2.reset_display_overscan('S')
    assert 'Overscan sıfırlanamadı' in str(exc.value)
