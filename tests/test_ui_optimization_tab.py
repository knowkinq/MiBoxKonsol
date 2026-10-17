# -*- coding: utf-8 -*-
"""optimization_tab: analiz, uygulama ve gorsel ayar akislari."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QPoint, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPushButton,
)

from mibox_app import optimization
from mibox_app.ui.optimization_tab import (
    OptimizationTab,
    _content_card,
    measurement,
    size_text,
)


def _bilgi(**kw):
    info = {'width': 1920, 'height': 1080, 'fps': 60, 'density': 320,
            'sink_name': None, 'overscan': None, 'override_width': None,
            'override_height': None, 'override_density': None,
            'read_errors': []}
    info.update(kw)
    return info


class _Motor:
    def __init__(self):
        self.calls = []
        self.plan = {}
        self.hooks = {}
        self.default = {
            'display_details': _bilgi(),
            'quick_boost': {'freed_mb': 512, 'summary': []},
            'reboot': SimpleNamespace(exit_code=0, error='', output=''),
        }

    def _sonraki(self, name):
        kuyruk = self.plan.get(name)
        if kuyruk:
            return kuyruk.pop(0)
        return self.default.get(name)

    def _call(self, name, *args):
        self.calls.append((name,) + args)
        deger = self._sonraki(name)
        kanca = self.hooks.get(name)
        if kanca:
            kanca()
        if isinstance(deger, Exception):
            raise deger
        return deger

    def display_details(self, target):
        return self._call('display_details', target)

    def set_display_size(self, target, width, height):
        return self._call('set_display_size', target, width, height)

    def reset_display_size(self, target):
        return self._call('reset_display_size', target)

    def set_display_density(self, target, density):
        return self._call('set_display_density', target, density)

    def reset_display_density(self, target):
        return self._call('reset_display_density', target)

    def set_display_overscan(self, target, left, top, right, bottom):
        return self._call('set_display_overscan', target, left, top, right,
                          bottom)

    def reset_display_overscan(self, target):
        return self._call('reset_display_overscan', target)

    def quick_boost(self, target, check_cancel=None):
        self.calls.append(('quick_boost', target))
        if check_cancel:
            check_cancel()
        sonuc = self._sonraki('quick_boost')
        if isinstance(sonuc, Exception):
            raise sonuc
        return sonuc

    def reboot(self, target):
        self.calls.append(('reboot', target))
        sonuc = self._sonraki('reboot')
        if isinstance(sonuc, Exception):
            raise sonuc
        return sonuc


class _Cekirdek(QObject):
    connection_changed = Signal(bool, object)

    def __init__(self):
        super().__init__()
        self.connected = True
        self.target = 'tv-1'
        self.engine_ready = True
        self._engine = _Motor()

    @property
    def engine(self):
        if not self.engine_ready:
            raise RuntimeError('motor yok')
        return self._engine


class _Sekmeler:
    def __init__(self):
        self.current = None
        self.index = None

    def setCurrentWidget(self, widget):
        self.current = widget

    def setCurrentIndex(self, index):
        self.index = index


class _SaglikTumu:
    def __init__(self):
        self.cagrilar = []
        self.scroll_bg = object()
        self.background = object()
        self.sections = _Sekmeler()

    def _open_section(self, scroll, background):
        self.cagrilar.append((scroll, background))


class _SaglikScroll:
    def __init__(self):
        self.scroll_bg = object()
        self.sections = _Sekmeler()


class _SaglikBasit:
    def __init__(self):
        self.sections = _Sekmeler()


class _UygulamaSekmesi:
    def __init__(self, calisan=True):
        self.cmb_status = QComboBox()
        self.cmb_status.addItem('Tümü', 'all')
        if calisan:
            self.cmb_status.addItem('Çalışıyor', 'running')
        self.cmb_status.addItem('Durduruldu', 'stopped')


class _Pencere:
    def __init__(self):
        self._workers = []
        self.runs = []
        self._closing = False
        self._close_pending = False
        self._connection_busy = False
        self.tabs = _Sekmeler()
        self.tab_health = object()
        self.tab_health_inner = None
        self.tab_apps = _UygulamaSekmesi()
        self.tab_files = object()

    def _run(self, worker, desc=None):
        self.runs.append((worker, desc))
        self._workers.append(worker)


@pytest.fixture
def opt(qtbot):
    core = _Cekirdek()
    win = _Pencere()
    p = OptimizationTab(core, win)
    qtbot.addWidget(p)
    return p, core, win


@pytest.fixture
def opt_embedded(qtbot):
    core = _Cekirdek()
    win = _Pencere()
    p = OptimizationTab(core, win, embedded=True)
    qtbot.addWidget(p)
    return p, core, win


def _temizle(win, isci):
    isci.finished.emit()
    if isci in win._workers:
        win._workers.remove(isci)


def _tamamla(win, isci):
    _temizle(win, isci)


def test_saf_fonksiyonlar_ve_kartlar(qapp):
    assert qapp is not None
    assert size_text(None) == 'Ölçülmedi'
    assert size_text(1048576) == '1.0 GB'
    assert size_text('2097152') == '2.0 GB'
    assert size_text(-5) == 'Ölçülmedi'
    assert size_text(float('inf')) == 'Ölçülmedi'
    assert size_text('abc') == 'Ölçülmedi'

    assert measurement('3.5') == 3.5
    assert measurement(5) == 5.0
    assert measurement(None) is None
    assert measurement('abc') is None
    assert measurement(-1) is None
    assert measurement(float('inf')) is None

    kart, _ = _content_card('Başlık')
    assert kart.objectName() == 'contentCard'
    baslik = kart.findChild(QLabel)
    assert baslik.objectName() == 'cardTitle'
    assert baslik.property('role') == 'primary'
    metrik, _ = _content_card('Değer', metric=True)
    assert metrik.objectName() == 'metricCard'
    baslik2 = metrik.findChild(QLabel)
    assert baslik2.objectName() == 'metricLabel'
    assert baslik2.property('role') == 'quiet'


def test_kurulum_ve_yerlesim(opt, opt_embedded):
    p, _core, _win = opt
    etiketler = [lbl.text() for lbl in p.findChildren(QLabel)]
    assert any('Kasma nedenlerini inceleyin' in t for t in etiketler)
    assert not any('Ekran ve çözünürlük ayarları Cihaz ayarları' in t
                   for t in etiketler)
    assert p.lbl_disk.text() == '—'
    assert p.lbl_ram.text() == '—'
    assert p.lbl_anim.text() == '—'
    assert p.lbl_disk_detail.text() == 'Henüz ölçülmedi'
    assert p.lbl_findings.text() == ('Önce cihaza bağlanın ve Analiz Et ile '
                                     'mevcut durumu okuyun.')
    assert p.lbl_status.text() == ('Analiz bekliyor. Cihaza bağlanıp Analiz '
                                   'Et’i seçin.')
    assert p.chk_cache.isChecked() is True
    assert p.chk_animation.isChecked() is False
    assert p.cmb_animation.isEnabled() is False
    assert p.cmb_animation.count() == 3
    assert p.cmb_animation.itemData(0) == '0.5'
    assert p.btn_apply.property('role') == 'primary'
    assert p.btn_boost.property('accent') is True
    assert p.lbl_disp_current.text() == 'Mevcut Ekran: Henüz sorgulanmadı'
    assert p.cmb_resolution.count() == 5
    assert p.cmb_resolution.itemData(1) == (1920, 1080)
    assert p.cmb_resolution.itemData(4) == 'reset'
    assert p.cmb_density.count() == 6
    assert p.cmb_density.itemData(3) == 320
    assert p.cmb_overscan.count() == 4
    assert p.cmb_overscan.itemData(2) == (20, 20, 20, 20)
    assert p.txt_report.isReadOnly() is True
    assert p.txt_report.maximumBlockCount() == 120
    assert p.disp_group.isHidden() is False

    pe, _ce, _we = opt_embedded
    etiketler_e = [lbl.text() for lbl in pe.findChildren(QLabel)]
    assert any('Ekran ve çözünürlük ayarları Cihaz ayarları bölümündedir.'
               in t for t in etiketler_e)
    assert pe.disp_group.isHidden() is True
    assert pe._metrics_layout.itemAt(0).widget().isHidden() is True
    assert pe._metrics_layout.itemAt(1).widget().isHidden() is True
    assert pe._metrics_layout.itemAt(2).widget().objectName() == 'metricCard'
    assert (pe._metrics_layout.itemAt(3).widget().objectName()
            == 'contentCard')

    p.show()
    p.resize(1000, 700)
    assert p._metrics_layout.direction() == QBoxLayout.LeftToRight
    assert p._display_controls_layout.direction() == QBoxLayout.LeftToRight
    p.setFixedSize(400, 700)
    assert p.width() < 760
    assert p._metrics_layout.direction() == QBoxLayout.TopToBottom
    assert p._display_controls_layout.direction() == QBoxLayout.TopToBottom

    ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0),
                     QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                     Qt.ScrollUpdate, False)
    p.cmb_animation.wheelEvent(ev)
    assert ev.isAccepted() is False
    p.cmb_resolution.showPopup()
    assert p.cmb_resolution.view().isVisible() is True
    ev2 = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0),
                      QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                      Qt.ScrollUpdate, False)
    p.cmb_resolution.wheelEvent(ev2)
    p.cmb_resolution.hidePopup()


def test_kisayollar(opt):
    p, _core, win = opt
    dugmeler = {b.text(): b for b in p.findChildren(QPushButton)}

    saglik = _SaglikTumu()
    win.tab_health_inner = saglik
    dugmeler['Arka plan yönetimi'].click()
    assert win.tabs.current is win.tab_health
    assert saglik.cagrilar == [(saglik.scroll_bg, saglik.background)]

    saglik2 = _SaglikScroll()
    win.tab_health_inner = saglik2
    dugmeler['Arka plan yönetimi'].click()
    assert saglik2.sections.current is saglik2.scroll_bg

    saglik3 = _SaglikBasit()
    win.tab_health_inner = saglik3
    dugmeler['Arka plan yönetimi'].click()
    assert saglik3.sections.index == 3

    win.tab_health_inner = None
    dugmeler['Arka plan yönetimi'].click()
    assert win.tabs.current is win.tab_apps
    assert win.tab_apps.cmb_status.currentIndex() == 1

    win.tab_apps = _UygulamaSekmesi(calisan=False)
    dugmeler['Arka plan yönetimi'].click()
    assert win.tabs.current is win.tab_apps
    assert win.tab_apps.cmb_status.currentIndex() == 0

    dugmeler['Depolamayı incele'].click()
    assert win.tabs.current is win.tab_files


def test_baglanti_degisimi_ve_hazirlik(opt):
    p, core, win = opt
    from mibox_app.workers import Worker
    isci = Worker(lambda: None)
    p._worker = isci
    p.lbl_disk.setText('50%')
    p.txt_report.setPlainText('eski')
    core.connection_changed.emit(False, None)
    assert isci.isInterruptionRequested() is True
    assert p._generation == 1
    assert p.lbl_disk.text() == '—'
    assert p.lbl_ram.text() == '—'
    assert p.lbl_anim.text() == '—'
    assert p.lbl_disk_detail.text() == 'Henüz ölçülmedi'
    assert p.lbl_ram_detail.text() == 'Henüz ölçülmedi'
    assert p.lbl_anim_detail.text() == 'Henüz ölçülmedi'
    assert p.lbl_findings.text() == ('Bağlantı değişti. Mevcut cihazı '
                                     'yeniden analiz edin.')
    assert p.lbl_status.text() == p.lbl_findings.text()
    assert p.lbl_disp_current.text() == ('Bağlantı değişti. Mevcut cihazı '
                                         'yeniden okuyun.')
    assert p.txt_report.toPlainText() == ''

    p._worker = None
    core.connection_changed.emit(True, 'tv-1')

    assert p._ready() is True
    p._busy = True
    assert p._ready() is False
    p._busy = False
    win._closing = True
    assert p._ready() is False
    win._closing = False
    win._close_pending = True
    assert p._ready() is False
    win._close_pending = False
    win._connection_busy = True
    assert p._ready() is False
    assert p.lbl_status.text() == ('Önce cihaz bağlantısının kurulmasını '
                                   'bekleyin.')
    win._connection_busy = False
    core.connected = False
    assert p._ready() is False
    core.connected = True
    core.target = ''
    assert p._ready() is False
    core.target = 'tv-1'
    assert p._ready() is True


def test_mesguliyet_durumu(opt):
    p, _core, _win = opt
    mesgul = []
    p.busy_changed.connect(mesgul.append)
    p._set_busy(True)
    assert p._busy is True
    assert mesgul[-1] is True
    for dugme in (p.btn_analyze, p.btn_apply, p.btn_reboot, p.chk_cache,
                  p.chk_animation, p.btn_boost, p.btn_apply_disp,
                  p.btn_read_disp, p.btn_reset_disp_all):
        assert dugme.isEnabled() is False
    assert p.cmb_animation.isEnabled() is False
    p.chk_animation.setChecked(True)
    p._set_busy(False)
    assert mesgul[-1] is False
    assert p.btn_analyze.isEnabled() is True
    assert p.cmb_animation.isEnabled() is True
    p.chk_animation.setChecked(False)
    p._set_busy(False)
    assert p.cmb_animation.isEnabled() is False


def test_analiz_akisi(opt, monkeypatch):
    p, core, win = opt
    cagrilar = []

    def sahte_analyze(engine, target, check_cancel=None):
        cagrilar.append(('analyze', target))
        if check_cancel:
            check_cancel()
        return {'health': {'disk_pct': '42'}, 'animations': {}}

    def sahte_plan(engine, target, trim=False, animation=None,
                   check_cancel=None, progress=None):
        cagrilar.append(('plan', trim, animation))
        if progress:
            progress(1, 3)
        if check_cancel:
            check_cancel()
        return {'steps': [{'ok': True, 'message': 'Adım tamam'}]}

    monkeypatch.setattr(optimization, 'analyze', sahte_analyze)
    monkeypatch.setattr(optimization, 'run_plan', sahte_plan)

    analizler = []
    p.analysis_ready.connect(analizler.append)
    mesgul = []
    p.busy_changed.connect(mesgul.append)

    p._busy = True
    p.refresh()
    assert win.runs == []
    p._busy = False

    core.engine_ready = False
    p.refresh()
    assert p.lbl_status.text() == 'Cihaz motoru hazır değil: motor yok'
    assert win.runs == []
    core.engine_ready = True

    p.refresh()
    isci = win.runs[-1][0]
    assert isci.job_name == 'Cihaz analizi'
    assert win.runs[-1][1] == 'Cihaz analizi'
    assert p._busy is True
    assert mesgul[-1] is True
    assert p.lbl_status.text() == 'Cihaz analiz ediliyor…'
    isci.run()
    assert cagrilar[-1] == ('analyze', 'tv-1')
    assert analizler[-1] == {'disk_pct': 42}
    assert p.lbl_status.text() == 'Analiz tamamlandı.'
    isci.finished.emit()
    assert p._busy is False
    assert mesgul[-1] is False
    win._workers.clear()

    p.refresh()
    isci = win.runs[-1][0]
    p._generation += 1
    isci.run()
    assert p.lbl_status.text() == 'Cihaz analiz ediliyor…'
    _tamamla(win, isci)

    p.chk_cache.setChecked(False)
    p._apply()
    assert p.lbl_status.text() == 'Uygulamak için en az bir adım seçin.'

    p.chk_cache.setChecked(True)
    win._workers.append(object())
    p._apply()
    assert p.lbl_status.text() == ('Diğer işlemlerin bitmesini bekleyip '
                                   'yeniden deneyin.')
    win._workers.clear()

    p.chk_animation.setChecked(True)
    p.cmb_animation.setCurrentIndex(0)
    p._apply()
    isci = win.runs[-1][0]
    assert isci.job_name == 'Cihaz optimizasyonu'
    assert p.lbl_status.text() == 'Seçilen adımlar uygulanıyor…'
    isci.run()
    assert cagrilar[-1] == ('plan', True, '0.5')
    assert p.lbl_status.text() == 'Seçilen adımlar tamamlandı.'
    assert p.txt_report.toPlainText() == 'Tamamlandı: Adım tamam'
    _tamamla(win, isci)

    def patlak_run(worker, desc=None):
        raise RuntimeError('patladi')

    monkeypatch.setattr(win, '_run', patlak_run)
    p.refresh()
    assert p.lbl_status.text() == 'İşlem başlatılamadı: patladi'
    assert p._worker is None
    assert p._busy is False


def test_analiz_sonuc_dallari(opt):
    p, _core, _win = opt
    analizler = []
    p.analysis_ready.connect(analizler.append)

    p._show_analysis({
        'health': {'disk_pct': '87', 'mem_pct': 90,
                   'disk_avail_kb': '1048576', 'mem_avail_kb': None},
        'animations': {'window_animation_scale': '0.5',
                       'transition_animation_scale': '0.5',
                       'animator_duration_scale': '0.5'},
        'warnings': ['Ek uyarı'],
    })
    assert analizler[-1]['disk_pct'] == 87
    assert analizler[-1]['mem_pct'] == 90
    assert p.lbl_disk.text() == '87%'
    assert p.lbl_ram.text() == '90%'
    assert p.lbl_disk_detail.text() == 'Boş: 1.0 GB'
    assert p.lbl_ram_detail.text() == 'Kullanılabilir: Ölçülmedi'
    assert p.lbl_anim.text() == '0.5×'
    assert p.lbl_anim_detail.text() == (
        'Pencere / geçiş / süre: 0.5 / 0.5 / 0.5')
    bulgular = p.lbl_findings.text()
    assert 'Depolama büyük ölçüde dolu.' in bulgular
    assert 'RAM kullanımı yüksek.' in bulgular
    assert 'Ek uyarı' in bulgular
    assert 'Kasma sürüyorsa yeniden başlatmayı deneyin' in bulgular
    assert p.lbl_status.text() == 'Analiz tamamlandı.'

    p._show_analysis({'health': {}, 'animations': {
        'window_animation_scale': '0.5', 'transition_animation_scale': '1',
        'animator_duration_scale': '?'}})
    assert p.lbl_disk.text() == '—'
    assert p.lbl_ram.text() == '—'
    assert p.lbl_disk_detail.text() == 'Boş: Ölçülmedi'
    assert p.lbl_anim.text() == '—'
    assert 'Cihaz ölçümleri okunamadı' in p.lbl_findings.text()

    p._show_analysis({'health': {'disk_pct': 120, 'mem_pct': 42},
                      'animations': {
                          'window_animation_scale': '1',
                          'transition_animation_scale': '1',
                          'animator_duration_scale': '1'}})
    assert p.lbl_disk.text() == '—'
    assert p.lbl_ram.text() == '42%'
    assert p.lbl_anim.text() == '1×'
    assert ('Okunan depolama ve RAM değerlerinde belirgin bir doluluk '
            'uyarısı yok.' in p.lbl_findings.text())

    p._show_analysis({'health': {'disk_pct': 'abc'}, 'animations': {}})
    assert p.lbl_disk.text() == '—'


def test_uygulama_sonuc_dallari(opt):
    p, _core, _win = opt
    p._show_result({
        'after': {'health': {'disk_avail_kb': 2097152, 'mem_pct': 60}},
        'before': {'health': {'disk_avail_kb': 1048576, 'mem_pct': 70}},
        'steps': [{'ok': True, 'message': 'Önbellek temizlendi'},
                  {'ok': False, 'message': 'Animasyon uygulanamadı'}],
    })
    rapor = p.txt_report.toPlainText()
    assert 'Tamamlandı: Önbellek temizlendi' in rapor
    assert 'Başarısız: Animasyon uygulanamadı' in rapor
    assert 'Boş depolama: 1.0 GB → 2.0 GB' in rapor
    assert 'Boş alan farkı: +1024.0 MB' in rapor
    assert 'RAM kullanımı: 70% → 60% (anlık ölçüm)' in rapor
    assert p.lbl_status.text() == ('Bazı adımlar uygulanamadı; ayrıntıları '
                                   'kontrol edin.')

    p._show_result({'cancelled': True,
                    'before': {'health': {'mem_pct': 55}},
                    'steps': [{'ok': True, 'message': 'Kısmen tamam'}]})
    assert p.lbl_status.text() == ('İşlem durduruldu. Tamamlanan adımlar '
                                   'aşağıda listeleniyor.')

    p._show_result({'steps': []})
    assert p.lbl_status.text() == 'Seçilen adımlar tamamlandı.'
    assert p.txt_report.toPlainText() == 'Seçilen adımlar tamamlandı.'


def test_yeniden_baslatma(opt, monkeypatch):
    p, core, win = opt
    sorular = []
    cevap = [QMessageBox.No]

    def soru(*args, **kwargs):
        sorular.append(args)
        return cevap[-1]

    monkeypatch.setattr(QMessageBox, 'question', soru)

    p._busy = True
    p._reboot()
    assert win.runs == []
    assert sorular == []
    p._busy = False

    win._workers.append(object())
    p._reboot()
    assert p.lbl_status.text() == ('Yeniden başlatmadan önce diğer '
                                   'işlemlerin bitmesini bekleyin.')
    win._workers.clear()

    p._reboot()
    assert sorular[-1][1] == 'Yeniden başlat'
    assert win.runs == []

    def hedef_degistir(*args, **kwargs):
        p._generation += 1
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, 'question', hedef_degistir)
    p._reboot()
    assert p.lbl_status.text() == ('Bağlantı değişti veya başka bir işlem '
                                   'çalışıyor; yeniden deneyin.')
    assert win.runs == []
    monkeypatch.setattr(QMessageBox, 'question', soru)

    cevap[0] = QMessageBox.Yes
    core.engine_ready = False
    p._reboot()
    assert p.lbl_status.text() == 'Cihaz motoru hazır değil: motor yok'
    core.engine_ready = True

    p._reboot()
    isci = win.runs[-1][0]
    assert isci.job_name == 'Cihaz yeniden başlatma'
    assert win.runs[-1][1] == 'Cihaz yeniden başlatma'
    assert p.lbl_status.text() == 'Yeniden başlatma isteniyor…'
    isci.run()
    assert core.engine.calls[-1] == ('reboot', 'tv-1')
    assert core.connected is False
    assert p.lbl_status.text() == ('Yeniden başlatma istendi. Cihaz açılınca '
                                   'yeniden bağlanın.')
    _tamamla(win, isci)
    assert p._busy is False
    core.connected = True

    core.engine.plan['reboot'] = [SimpleNamespace(exit_code=1, error='',
                                                  output='çıktı verdi')]
    p._reboot()
    win.runs[-1][0].run()
    assert p.lbl_status.text() == ('Yeniden başlatılamadı: RuntimeError: '
                                   'çıktı verdi')
    _tamamla(win, win.runs[-1][0])

    core.engine.plan['reboot'] = [SimpleNamespace(exit_code=1, error='',
                                                  output='')]
    p._reboot()
    win.runs[-1][0].run()
    assert ('Cihaz yeniden başlatma isteğini reddetti.'
            in p.lbl_status.text())
    _tamamla(win, win.runs[-1][0])

    core.engine.plan['reboot'] = [SimpleNamespace(exit_code=0, error='',
                                                  output='')]
    p._reboot()
    isci = win.runs[-1][0]
    p._generation += 1
    durum = p.lbl_status.text()
    isci.run()
    assert core.connected is True
    assert p.lbl_status.text() == durum
    _tamamla(win, isci)

    core.engine.plan['reboot'] = [SimpleNamespace(exit_code=0, error='',
                                                  output='')]
    p._reboot()
    isci = win.runs[-1][0]
    p._generation += 1
    sayi = len(win.runs)
    durum = p.lbl_status.text()
    isci.finished_ok.emit(object())
    assert len(win.runs) == sayi
    assert core.connected is True
    assert p.lbl_status.text() == durum
    _tamamla(win, isci)

    def patlak_run(worker, desc=None):
        raise RuntimeError('patladi')

    monkeypatch.setattr(win, '_run', patlak_run)
    p._reboot()
    assert p.lbl_status.text() == 'Yeniden başlatma başlatılamadı: patladi'
    assert p._busy is False
    assert p._worker is None


def test_super_hizlandirma(opt, monkeypatch):
    p, core, win = opt
    uyarilar = []
    bilgiler = []
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: uyarilar.append(a))
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgiler.append(a))
    cevap = [QMessageBox.No]
    monkeypatch.setattr(QMessageBox, 'question',
                        lambda *a, **k: cevap[-1])

    p._busy = True
    p._quick_boost()
    assert win.runs == []
    p._busy = False

    win._workers.append(object())
    p._quick_boost()
    assert p.lbl_status.text() == ('Diğer işlemlerin bitmesini bekleyip '
                                   'yeniden deneyin.')
    win._workers.clear()

    p._quick_boost()
    assert win.runs == []

    def hedef_degistir(*args, **kwargs):
        p._generation += 1
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, 'question', hedef_degistir)
    p._quick_boost()
    assert p.lbl_status.text() == ('Cihaz veya işlem durumu değişti. '
                                   'Yeniden deneyin.')
    assert win.runs == []
    monkeypatch.setattr(QMessageBox, 'question',
                        lambda *a, **k: QMessageBox.Yes)

    core.engine_ready = False
    p._quick_boost()
    assert p.lbl_status.text() == 'Cihaz motoru hazır değil: motor yok'
    core.engine_ready = True

    core.engine.plan['quick_boost'] = [
        {'freed_mb': 512, 'summary': [
            'Uygulama onbellekleri temizlendi.',
            'Arka plan bosta kalan surecler sonlandirildi.',
            'Animasyon hizlari 0.5x (hizli) yapildi.']}]
    p._quick_boost()
    isci = win.runs[-1][0]
    assert isci.job_name == 'Süper Hızlandırma'
    assert win.runs[-1][1] == 'Süper Hızlandırma'
    assert p.lbl_status.text() == 'Süper hızlandırma uygulanıyor…'
    isci.run()
    _tamamla(win, isci)
    assert bilgiler[-1][1] == 'Hızlandırma Başarılı'
    assert uyarilar == []
    assert p.lbl_status.text() == 'Süper hızlandırma tamamlandı.'
    rapor = p.txt_report.toPlainText()
    assert rapor.startswith('🚀 Süper Hızlandırma Sonucu')
    assert '• Kazanılan RAM: +512.0 MB' in rapor
    assert 'Tamamlandı: Önbellek temizleme' in rapor
    assert 'Tamamlandı: Arka plan süreçlerini sonlandırma' in rapor
    assert 'Tamamlandı: Animasyon ölçeklerini ayarlama' in rapor

    core.engine.plan['quick_boost'] = [
        {'freed_mb': None, 'summary': [
            'Onbellek temizleme: disk hatası',
            'Surec sonlandirma:',
            'Animasyon hizlari 0.5x (hizli) yapildi.']}]
    p._quick_boost()
    isci = win.runs[-1][0]
    isci.run()
    _tamamla(win, isci)
    assert uyarilar[-1][1] == 'Kısmi Hızlandırma'
    assert p.lbl_status.text() == ('Süper hızlandırma kısmen tamamlandı; '
                                   'bazı adımlar uygulanamadı.')
    rapor = p.txt_report.toPlainText()
    assert '• Kazanılan RAM: Ölçülemedi' in rapor
    assert 'Başarısız: Önbellek temizleme — disk hatası' in rapor
    assert 'Başarısız: Arka plan süreçlerini sonlandırma' in rapor
    assert 'Bazı adımlar tamamlanamadı:' in rapor

    core.engine.plan['quick_boost'] = [
        {'freed_mb': '128', 'summary': [
            42,
            'bilinmeyen metin',
            'Uygulama onbellekleri temizlendi.',
            'Uygulama onbellekleri temizlendi.']}]
    p._quick_boost()
    isci = win.runs[-1][0]
    isci.run()
    _tamamla(win, isci)
    assert uyarilar[-1][1] == 'Eksik Hızlandırma Sonucu'
    assert p.lbl_status.text() == ('Hızlandırma sonucu eksik raporlandı; '
                                   'adım durumları doğrulanamadı.')
    rapor = p.txt_report.toPlainText()
    assert 'Sonuç: 42' in rapor
    assert 'Sonuç: bilinmeyen metin' in rapor
    assert 'Tüm adımların durumu doğrulanamadı.' in rapor
    assert '• Kazanılan RAM: +128.0 MB' in rapor

    core.engine.plan['quick_boost'] = [{'summary': []}]
    p._quick_boost()
    isci = win.runs[-1][0]
    isci.run()
    _tamamla(win, isci)
    assert uyarilar[-1][1] == 'Eksik Hızlandırma Sonucu'
    assert p.txt_report.toPlainText().startswith('🚀 Süper Hızlandırma')

    core.engine.plan['quick_boost'] = [
        {'summary': 'Uygulama onbellekleri temizlendi.'}]
    p._quick_boost()
    isci = win.runs[-1][0]
    isci.run()
    _tamamla(win, isci)
    assert uyarilar[-1][1] == 'Eksik Hızlandırma Sonucu'
    assert 'Tamamlandı: Önbellek temizleme' in p.txt_report.toPlainText()

    core.engine.plan.clear()
    p._quick_boost()
    isci = win.runs[-1][0]
    isci.cancel()
    isci.run()
    _tamamla(win, isci)
    assert p.lbl_status.text() == ('Hızlandırma tamamlanamadı: kullanıcı '
                                   'durdurdu')

    p._quick_boost()
    isci = win.runs[-1][0]
    p._generation += 1
    isci.run()
    _tamamla(win, isci)
    assert p.lbl_status.text() == 'Süper hızlandırma uygulanıyor…'

    p._quick_boost()
    isci = win.runs[-1][0]
    sayi = len(win.runs)
    _tamamla(win, isci)
    assert p.lbl_status.text() == ('Hızlandırma durduruldu. Bazı adımlar '
                                   'uygulanmış olabilir.')
    assert len(win.runs) == sayi

    p._quick_boost()
    isci = win.runs[-1][0]
    p._worker = None
    durum = p.lbl_status.text()
    isci.finished.emit()
    assert p.lbl_status.text() == durum
    if isci in win._workers:
        win._workers.remove(isci)
    p._busy = False

    def patlak_run(worker, desc=None):
        raise RuntimeError('patladi')

    monkeypatch.setattr(win, '_run', patlak_run)
    p._quick_boost()
    assert p.lbl_status.text() == 'Hızlandırma başlatılamadı: patladi'
    assert p._worker is None
    assert p._busy is False


def test_ekran_okuma_ve_sifirlama(opt, monkeypatch):
    p, core, win = opt
    bilgiler = []
    hatalar = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgiler.append(a))
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: hatalar.append(a))

    p._busy = True
    p._read_display_settings()
    assert win.runs == []
    p._busy = False

    p._busy = True
    p._reset_display_all()
    assert win.runs == []
    p._busy = False

    core.engine.default['display_details'] = _bilgi(
        override_width=1280, override_height=720, override_density=240,
        sink_name='HDMI-1', overscan=(15, 15, 15, 15))
    p._read_display_settings()
    isci = win.runs[-1][0]
    assert isci.job_name == 'Ekran Bilgisi Okuma'
    assert win.runs[-1][1] == 'Ekran: mevcut çözünürlük okunuyor'
    isci.run()
    assert p.lbl_disp_current.text() == (
        'Mevcut: 1920×1080 @ 60Hz · 320 DPI · Özel ayar etkin · HDMI-1 · '
        'Overscan: (15, 15, 15, 15)')
    _tamamla(win, isci)

    core.engine.default['display_details'] = _bilgi()
    p._read_display_settings()
    isci = win.runs[-1][0]
    isci.run()
    assert p.lbl_disp_current.text() == 'Mevcut: 1920×1080 @ 60Hz · 320 DPI'
    _tamamla(win, isci)

    core.engine.plan['display_details'] = [RuntimeError('okunamadı')]
    p._read_display_settings()
    isci = win.runs[-1][0]
    isci.run()
    assert p.lbl_disp_current.text() == ('Ekran bilgisi okunamadı: '
                                         'RuntimeError: okunamadı')
    _tamamla(win, isci)

    core.engine.plan.clear()
    core.engine.default['display_details'] = _bilgi()
    core.engine.calls.clear()
    p._reset_display_all()
    isci = win.runs[-1][0]
    assert isci.job_name == 'Görüntü Sıfırlama'
    assert win.runs[-1][1] == 'Ekran: fabrika ayarlarına sıfırlanıyor'
    isci.run()
    assert ('reset_display_size', 'tv-1') in core.engine.calls
    assert ('reset_display_density', 'tv-1') in core.engine.calls
    assert ('reset_display_overscan', 'tv-1') in core.engine.calls
    assert bilgiler[-1][1] == 'Görüntü Sıfırlandı'
    assert bilgiler[-1][2] == ('Çözünürlük, DPI ölçeği ve kenar taşması '
                               'fabrika varsayılanına döndürüldü.')
    assert win.runs[-1][1] == 'Ekran: mevcut çözünürlük okunuyor'
    _tamamla(win, isci)
    _tamamla(win, win.runs[-1][0])

    core.engine.plan['display_details'] = [RuntimeError('patladı')]
    p._reset_display_all()
    isci = win.runs[-1][0]
    isci.run()
    assert hatalar[-1][1] == 'Hata'
    assert hatalar[-1][2] == ('Görüntü sıfırlanamadı: RuntimeError: '
                              'patladı')
    _tamamla(win, isci)


def test_ekran_uygulama_reddetme(opt, monkeypatch):
    p, core, win = opt
    bilgiler = []
    hatalar = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgiler.append(a))
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: hatalar.append(a))

    p._busy = True
    p._apply_display_settings()
    assert win.runs == []
    p._busy = False

    p._apply_display_settings()
    assert bilgiler[-1][1] == 'Seçim Yapılmadı'
    assert bilgiler[-1][2] == ('Uygulamak için çözünürlük, DPI veya '
                               'overscan seçeneklerinden en az birini '
                               'belirleyin.')

    p.cmb_resolution.setCurrentIndex(1)
    core.engine.plan['display_details'] = [_bilgi(read_errors=['size'])]
    p._apply_display_settings()
    isci = win.runs[-1][0]
    isci.run()
    assert hatalar[-1][1] == 'Görüntü Hatası'
    assert ('Geri alma için mevcut değerler okunamadı: size. Hiçbir ayar '
            'değiştirilmedi.') in hatalar[-1][2]
    assert win.runs[-1][1] == 'Ekran: mevcut çözünürlük okunuyor'
    _tamamla(win, isci)
    _tamamla(win, win.runs[-1][0])

    yakalanan = []

    def exec_reddet(self):
        yakalanan.append(self)
        return 0

    monkeypatch.setattr(QDialog, 'exec', exec_reddet)
    p.cmb_density.setCurrentIndex(3)
    p.cmb_overscan.setCurrentIndex(2)
    core.engine.plan['display_details'] = [
        _bilgi(), _bilgi(width=1920, height=1080, density=320)]
    p._apply_display_settings()
    isci = win.runs[-1][0]
    assert isci.job_name == 'Görüntü Ayarlama'
    assert win.runs[-1][1] == 'Ekran: yeni çözünürlük/DPI uygulanıyor'
    isci.run()
    assert ('set_display_size', 'tv-1', 1920, 1080) in core.engine.calls
    assert ('set_display_density', 'tv-1', 320) in core.engine.calls
    assert ('set_display_overscan', 'tv-1', 20, 20, 20, 20) in \
        core.engine.calls
    dlg = yakalanan[-1]
    assert dlg.windowTitle() == 'Görüntü Ayarı Onayı'
    assert dlg.minimumWidth() == 380
    mesaj = next(lbl for lbl in dlg.findChildren(QLabel)
                 if lbl.text().startswith('Yeni görüntü ayarı uygulandı!'))
    assert '• Çözünürlük: 1920×1080' in mesaj.text()
    sayac = next(lbl for lbl in dlg.findChildren(QLabel)
                 if lbl.text().startswith('Kalan süre:'))
    assert sayac.text() == 'Kalan süre: 15 saniye'
    kutular = dlg.findChild(QDialogButtonBox)
    onay = next(b for b in kutular.buttons() if b.text() == 'Ayarları Koru')
    assert onay.property('accent') is True
    assert win.runs[-1][1] == 'Ekran: ayarlar geri alınıyor'
    _tamamla(win, isci)
    _tamamla(win, win.runs[-2][0])
    _tamamla(win, win.runs[-1][0])


def test_ekran_uygulama_onay_ve_geri_alma(opt, monkeypatch):
    p, core, win = opt
    bilgiler = []
    hatalar = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgiler.append(a))
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: hatalar.append(a))

    yakalanan = []

    def exec_onay(self):
        yakalanan.append(self)
        kutular = self.findChild(QDialogButtonBox)
        onay = next(b for b in kutular.buttons()
                    if b.text() == 'Ayarları Koru')
        onay.click()
        return self.result()

    monkeypatch.setattr(QDialog, 'exec', exec_onay)
    p.cmb_resolution.setCurrentIndex(1)
    p.cmb_density.setCurrentIndex(3)
    p.cmb_overscan.setCurrentIndex(2)
    core.engine.plan['display_details'] = [_bilgi(), _bilgi()]
    p._apply_display_settings()
    isci = win.runs[-1][0]
    isci.run()
    assert win.runs[-1][1] == 'Ekran: mevcut çözünürlük okunuyor'
    _tamamla(win, isci)
    _tamamla(win, win.runs[-1][0])

    core.engine.calls.clear()
    core.engine.plan['display_details'] = [_bilgi(), _bilgi()]
    p.cmb_resolution.setCurrentIndex(4)
    p.cmb_density.setCurrentIndex(5)
    p.cmb_overscan.setCurrentIndex(1)
    p._apply_display_settings()
    isci = win.runs[-1][0]
    isci.run()
    assert ('reset_display_size', 'tv-1') in core.engine.calls
    assert ('reset_display_density', 'tv-1') in core.engine.calls
    assert ('reset_display_overscan', 'tv-1') in core.engine.calls
    _tamamla(win, isci)
    _tamamla(win, win.runs[-1][0])

    def exec_sayac(self):
        yakalanan.append(self)
        zamanlayici = self.findChild(QTimer)
        for _ in range(15):
            zamanlayici.timeout.emit()
        return self.result()

    monkeypatch.setattr(QDialog, 'exec', exec_sayac)
    core.engine.plan['display_details'] = [_bilgi(), _bilgi()]
    p._apply_display_settings()
    isci = win.runs[-1][0]
    isci.run()
    dlg = yakalanan[-1]
    sayac = next(lbl for lbl in dlg.findChildren(QLabel)
                 if lbl.text().startswith('Kalan süre:'))
    assert sayac.text() == 'Kalan süre: 1 saniye'
    assert dlg.findChild(QTimer).isActive() is False
    assert win.runs[-1][1] == 'Ekran: ayarlar geri alınıyor'
    _tamamla(win, isci)
    _tamamla(win, win.runs[-2][0])
    _tamamla(win, win.runs[-1][0])

    p.cmb_resolution.setCurrentIndex(1)
    p.cmb_density.setCurrentIndex(3)
    p.cmb_overscan.setCurrentIndex(2)
    core.engine.plan['display_details'] = [
        _bilgi(override_width=1280, override_height=720,
               override_density=240)]
    core.engine.plan['set_display_density'] = [
        RuntimeError('uygulama patladi')]
    p._apply_display_settings()
    isci = win.runs[-1][0]
    isci.run()
    assert ('set_display_density', 'tv-1', 240) in core.engine.calls
    assert 'önceki değerler geri yüklendi' in hatalar[-1][2]
    _tamamla(win, isci)
    _tamamla(win, win.runs[-1][0])

    p.cmb_resolution.setCurrentIndex(1)
    p.cmb_density.setCurrentIndex(3)
    p.cmb_overscan.setCurrentIndex(2)
    core.engine.plan['display_details'] = [
        _bilgi(override_width=1280, override_height=720,
               override_density=240)]
    core.engine.plan['set_display_density'] = [
        RuntimeError('uygulama patladi'), RuntimeError('geri de patladi')]
    p._apply_display_settings()
    isci = win.runs[-1][0]
    isci.run()
    assert 'başarısız oldu' in hatalar[-1][2]
    assert 'Geri yüklenemeyen ayarlar: DPI: geri de patladi' in \
        hatalar[-1][2]
    _tamamla(win, isci)
    _tamamla(win, win.runs[-1][0])

    p.cmb_resolution.addItem('Garip', 123)
    p.cmb_resolution.setCurrentIndex(p.cmb_resolution.count() - 1)
    p.cmb_density.addItem('Garip', [1])
    p.cmb_density.setCurrentIndex(p.cmb_density.count() - 1)
    p.cmb_overscan.setCurrentIndex(0)
    core.engine.plan['display_details'] = [
        _bilgi(), RuntimeError('son okuma patladi')]
    p._apply_display_settings()
    isci = win.runs[-1][0]
    isci.run()
    assert hatalar[-1][2] == 'RuntimeError: son okuma patladi'
    _tamamla(win, isci)
    _tamamla(win, win.runs[-1][0])


def test_geri_alma_ve_kurtarma(opt, monkeypatch):
    p, core, win = opt
    bilgiler = []
    hatalar = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: bilgiler.append(a))
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *a, **k: hatalar.append(a))

    dolu = _bilgi(override_width=1280, override_height=720,
                  override_density=240, overscan=(15, 15, 15, 15))
    p._revert_display(dolu, 'tv-1')
    isci = win.runs[-1][0]
    assert win.runs[-1][1] == 'Ekran: ayarlar geri alınıyor'
    isci.run()
    assert ('set_display_size', 'tv-1', 1280, 720) in core.engine.calls
    assert ('set_display_density', 'tv-1', 240) in core.engine.calls
    assert ('set_display_overscan', 'tv-1', 15, 15, 15, 15) in \
        core.engine.calls
    assert bilgiler[-1][1] == 'Geri Alındı'
    assert bilgiler[-1][2] == ('Görüntü ayarları önceki durumuna geri '
                               'döndürüldü.')
    assert win.runs[-1][1] == 'Ekran: mevcut çözünürlük okunuyor'
    _tamamla(win, isci)
    _tamamla(win, win.runs[-1][0])

    core.engine.plan['set_display_density'] = [RuntimeError('yoğunluk yok')]
    p._revert_display(_bilgi(override_density=240), 'tv-1')
    isci = win.runs[-1][0]
    isci.run()
    assert hatalar[-1][1] == 'Görüntü Geri Alma Hatası'
    assert hatalar[-1][2] == (
        'Önceki görüntü ayarları geri yüklenemedi: RuntimeError: '
        'Geri yüklenemeyen ayarlar: DPI: yoğunluk yok')
    _tamamla(win, isci)

    motor = core.engine
    motor.calls.clear()
    OptimizationTab._restore_display_fields(
        motor, 'tv-1', _bilgi(), ('size', 'density', 'overscan'))
    assert ('reset_display_size', 'tv-1') in motor.calls
    assert ('reset_display_density', 'tv-1') in motor.calls
    assert ('reset_display_overscan', 'tv-1') in motor.calls

    motor.calls.clear()
    OptimizationTab._restore_display_fields(
        motor, 'tv-1', dolu, ('size', 'density', 'overscan'))
    assert ('set_display_size', 'tv-1', 1280, 720) in motor.calls
    assert ('set_display_density', 'tv-1', 240) in motor.calls
    assert ('set_display_overscan', 'tv-1', 15, 15, 15, 15) in motor.calls

    motor.plan['set_display_size'] = [RuntimeError('hata')]
    with pytest.raises(RuntimeError, match='çözünürlük: hata'):
        OptimizationTab._restore_display_fields(
            motor, 'tv-1', dolu, ('size',))
