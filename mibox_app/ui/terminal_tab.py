# -*- coding: utf-8 -*-
"""Terminal sekmesi: ADB Shell doğrudan komut satırı ve hazır TV teşhis komutları."""
import datetime
import html
import re

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import gate
from ..workers import Worker
from . import kit

# SGR ANSI renk haritası (koyu temada yüksek kontrastlı okunabilir renkler)
_ANSI_COLORS = {
    '30': '#64748b', '31': '#f87171', '32': '#4ade80', '33': '#facc15',
    '34': '#60a5fa', '35': '#c084fc', '36': '#38bdf8', '37': '#f1f5f9',
    '90': '#94a3b8', '91': '#ef4444', '92': '#22c55e', '93': '#eab308',
    '94': '#3b82f6', '95': '#a855f7', '96': '#06b6d4', '97': '#ffffff',
}

_CURSOR_RE = re.compile(r'\x1b\[\??[0-9;]*[a-ln-zA-LN-Z]')
_SPECIAL_ESC_RE = re.compile(r'\x1b[=>()][0-9A-Za-z]?|\x1b\[\??[0-9;]*[JKHsuABCDfnp]')


class TerminalTab(QWidget):
    """Gelişmiş interaktif ADB Terminal ve hızlı sistem komutları konsolu."""

    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._history = []
        self._history_idx = -1
        self._history_draft = ''
        self._busy = False
        self._connection_generation = 0
        connection_changed = getattr(self.core, 'connection_changed', None)
        if connection_changed is not None:
            connection_changed.connect(self._on_connection_changed)
        self._build()

    def _on_connection_changed(self, *_):
        self._connection_generation += 1
        if self._busy:
            self.lbl_status.setText('Cihaz bağlantısı değişti; eski komut sonucu atlanacak.')

    def _target_is_current(self, target, generation):
        return (generation == self._connection_generation
                and getattr(self.core, 'connected', False)
                and getattr(self.core, 'target', None) == target
                and not getattr(self.window, '_connection_busy', False))

    def _build(self):
        root = kit.page(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        # 1. Hızlı Komut Butonları Kartı
        presets_card = QGroupBox('Hızlı TV Komutları ve Teşhis')
        presets_layout = QVBoxLayout(presets_card)
        presets_layout.setContentsMargins(10, 8, 10, 8)
        presets_layout.setSpacing(6)

        row1 = kit.action_bar()
        row1.setSpacing(6)
        presets = [
            ('📊 CPU / Süreçler', 'dumpsys cpuinfo'),
            ('🧠 Bellek (Meminfo)', 'dumpsys meminfo -s'),
            ('💾 Disk Kullanımı', 'df -h /data /sdcard'),
            ('🔋 Güç Durumu', 'dumpsys battery'),
            ('🖥 Ekran Boyutu', 'wm size'),
        ]
        for title, cmd in presets:
            btn = QPushButton(title)
            btn.setMinimumHeight(32)
            btn.setToolTip(cmd)
            btn.setProperty('role', 'secondary')
            btn.clicked.connect(lambda _=False, c=cmd: self._execute_preset(c))
            row1.addWidget(btn)
        presets_layout.addLayout(row1)

        row2 = kit.action_bar()
        row2.setSpacing(6)
        presets2 = [
            ('🌐 Ağ Bağlantıları', 'ip route'),
            ('📱 Android Model', 'getprop ro.product.model'),
            ('📦 Kullanıcı Paketleri', 'pm list packages -3'),
            ('⚠️ Son Hatalar (Logcat)', 'logcat -d -t 40'),
            ('📶 Wi-Fi Durumu', 'dumpsys wifi'),
        ]
        for title, cmd in presets2:
            btn = QPushButton(title)
            btn.setMinimumHeight(32)
            btn.setToolTip(cmd)
            btn.setProperty('role', 'secondary')
            btn.clicked.connect(lambda _=False, c=cmd: self._execute_preset(c))
            row2.addWidget(btn)
        presets_layout.addLayout(row2)

        root.addWidget(presets_card)

        # 2. Terminal Çıktı Konsolu
        self.txt_output = QPlainTextEdit()
        self.txt_output.setObjectName('terminalView')
        self.txt_output.setReadOnly(True)
        self.txt_output.setMaximumBlockCount(5000)
        root.addWidget(self.txt_output, 1)

        # 3. Komut Giriş Satırı
        cmd_row = QHBoxLayout()
        cmd_row.setSpacing(8)

        self.lbl_prompt = QLabel('adb shell $')
        self.lbl_prompt.setStyleSheet('font-weight: bold; color: #6366f1;')

        self.txt_cmd = QLineEdit()
        self.txt_cmd.setAccessibleName('TV shell komutu')
        self.txt_cmd.setToolTip('Enter: çalıştır · Yukarı/Aşağı: bu oturumun komut geçmişi')
        self.txt_cmd.installEventFilter(self)
        self.txt_cmd.setPlaceholderText('Bir ADB shell komutu yazın (örn: ls /sdcard, getprop, pm list packages)...')
        self.txt_cmd.returnPressed.connect(self._run_cmd)

        self.btn_run = QPushButton('Çalıştır')
        self.btn_run.setProperty('role', 'primary')
        self.btn_run.setFixedWidth(90)
        self.btn_run.clicked.connect(self._run_cmd)

        self.btn_clear = QPushButton('Temizle')
        self.btn_clear.setProperty('role', 'secondary')
        self.btn_clear.clicked.connect(self.txt_output.clear)

        self.btn_copy = QPushButton('Kopyala')
        self.btn_copy.setProperty('role', 'secondary')
        self.btn_copy.clicked.connect(self._copy_output)

        self.btn_save = QPushButton('💾 Kaydet')
        self.btn_save.setProperty('role', 'secondary')
        self.btn_save.setToolTip('Terminal konsol geçmişini bir .txt dosyasına kaydeder')
        self.btn_save.clicked.connect(self._save_output)

        cmd_row.addWidget(self.lbl_prompt)
        cmd_row.addWidget(self.txt_cmd, 1)
        cmd_row.addWidget(self.btn_run)
        root.addLayout(cmd_row)

        output_actions = kit.action_bar()
        output_actions.addWidget(self.btn_clear)
        output_actions.addWidget(self.btn_copy)
        output_actions.addWidget(self.btn_save)
        root.addLayout(output_actions)

        self.lbl_status = kit.status_label('Hazır · Okuma komutları doğrudan, değişiklik komutları onayla çalışır.')
        root.addWidget(self.lbl_status)

        self._print_welcome()

    def _print_welcome(self):
        banner = (
            '<div style="color: #6366f1; font-weight: bold; margin-bottom: 8px;">'
            '==========================================================<br>'
            ' MiBox Konsol — Gelişmiş ADB Shell Terminali<br>'
            ' TV cihazınızla doğrudan interaktif iletişim kurun.<br>'
            ' Komut geçmişi için Yukarı / Aşağı ok tuşlarını kullanabilirsiniz.<br>'
            '==========================================================</div>'
        )
        self.txt_output.appendHtml(banner)

    def _copy_output(self):
        text = self.txt_output.toPlainText()
        if text:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
            self.lbl_status.setText('Terminal çıktısı panoya kopyalandı.')

    def _save_output(self):
        text = self.txt_output.toPlainText()
        if not text.strip():
            QMessageBox.information(self, 'Boş Terminal', 'Kaydedilecek herhangi bir terminal çıktısı bulunamadı.')
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            'Terminal Çıktısını Kaydet',
            f'terminal_log_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.txt',
            'Metin Dosyaları (*.txt);;Tüm Dosyalar (*.*)'
        )
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(text)
                self.lbl_status.setText(f'Terminal günlüğü kaydedildi: {filename}')
            except Exception as e:
                QMessageBox.critical(self, 'Hata', f'Dosya kaydedilirken hata oluştu:\n{e}')

    def _execute_preset(self, cmd):
        if self._busy:
            self.lbl_status.setText('Önce çalışan komutun tamamlanmasını bekleyin.')
            return
        self.txt_cmd.setText(cmd)
        self._run_cmd()

    @staticmethod
    def _format_terminal_output(raw_text, dark=True):
        """ANSI escape kodlarını temizler ve okunabilir renkli HTML formatına dönüştürür."""
        if not raw_text:
            return ''
        # 1. Cursor / ekran temizleme / özel escape kodlarını temizle
        text = _CURSOR_RE.sub('', raw_text)
        text = _SPECIAL_ESC_RE.sub('', text)
        text = text.replace('\r\n', '\n').replace('\r', '')
        text = re.sub(r'\n{3,}', '\n\n', text)

        # 2. ANSI SGR renk kodlarını HTML span'lerine çevir
        parts = re.split(r'(\x1b\[[0-9;]*m)', text)
        out = ['<pre style="font-family: inherit; margin: 0; white-space: pre; line-height: 1.45;">']
        open_spans = 0
        text_color = '#f1f5f9' if dark else '#1e293b'

        for part in parts:
            if not part:
                continue
            if part.startswith('\x1b['):
                codes = part[2:-1].split(';')
                if not codes or codes == [''] or '0' in codes:
                    while open_spans > 0:
                        out.append('</span>')
                        open_spans -= 1
                for code in codes:
                    if code in _ANSI_COLORS:
                        color = _ANSI_COLORS[code] if dark else text_color
                        out.append(f'<span style="color: {color};">')
                        open_spans += 1
                    elif code == '1':
                        out.append(f'<span style="font-weight: bold; color: {text_color};">')
                        open_spans += 1
                    elif code == '7':
                        out.append(f'<span style="font-weight: bold; color: {text_color};">')
                        open_spans += 1
            else:
                clean_part = part.replace('\x1b', '')
                out.append(html.escape(clean_part))

        while open_spans > 0:
            out.append('</span>')
            open_spans -= 1

        out.append('</pre>')
        return ''.join(out)

    def _run_cmd(self):
        if self._busy:
            return
        if getattr(self.window, '_connection_busy', False):
            self.lbl_status.setText('Bağlantı işlemi sürüyor; tamamlanınca yeniden deneyin.')
            return
        cmd = self.txt_cmd.text().strip()
        if not cmd:
            return
        if not self.core.connected or not self.core.target:
            self.lbl_status.setText('Önce bir TV cihazına bağlanın.')
            return
        target = self.core.target
        generation = self._connection_generation

        command_class = gate.classify(cmd)
        if command_class == 'REFUSED':
            QMessageBox.warning(
                self,
                'Komut engellendi',
                f'{gate.REFUSED_MSG}\n\nKomut: {cmd}',
            )
            return
        if command_class in ('SETTING', 'CHANGE'):
            reply = QMessageBox.question(
                self,
                'Komut onayı',
                f'Bu komut TV ayarlarını veya sistem durumunu değiştirebilir. Çalıştırılsın mı?\n\n{cmd}',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                self.lbl_status.setText('Komut iptal edildi.')
                return

        if not self._target_is_current(target, generation):
            self.lbl_status.setText('Hedef veya bağlantı değişti; komut çalıştırılmadı.')
            return

        if not self._history or self._history[-1] != cmd:
            self._history.append(cmd)
        del self._history[:-100]
        self._history_idx = len(self._history)
        self._history_draft = ''
        self.txt_cmd.clear()

        ts = datetime.datetime.now().strftime('%H:%M:%S')
        text_color = kit.colors(self)['text']
        cmd_html = (
            f'<div style="margin-top: 8px; margin-bottom: 2px;">'
            f'<span style="color: #818cf8; font-weight: bold;">[{ts}] $</span> '
            f'<span style="color: {text_color}; font-weight: 600;">{html.escape(cmd)}</span>'
            f'</div>'
        )
        self.txt_output.appendHtml(cmd_html)

        engine = self.core.engine
        self._busy = True
        self.btn_run.setEnabled(False)
        self.lbl_status.setText('Komut çalıştırılıyor...')
        worker_ref = {}

        def do():
            worker = worker_ref['worker']
            worker.check_cancel()
            # ADB shell komutunu çalıştır
            try:
                res = engine.shell(
                    target, cmd, timeout=30, preserve_output_whitespace=True,
                    hide_from_trace=True,
                    cancel_check=worker.isInterruptionRequested)
            except Exception:
                worker.check_cancel()
                raise
            out = res.output or ''
            err = res.error or ''
            code = getattr(res, 'exit_code', getattr(res, 'returncode', 0))
            return out, err, code

        def done(result):
            self._busy = False
            self.btn_run.setEnabled(True)
            if not self._target_is_current(target, generation):
                self.lbl_status.setText('Hedef değişti; eski cihazın komut çıktısı gösterilmedi.')
                return
            out, err, code = result
            if out:
                formatted = self._format_terminal_output(out, dark=kit.dark_from(self))
                self.txt_output.appendHtml(formatted)
            if err:
                err_html = f'<div style="color: #ef4444; margin-top: 4px;">[HATA] {html.escape(err.strip())}</div>'
                self.txt_output.appendHtml(err_html)
            if not out and not err:
                self.txt_output.appendHtml(f'<div style="color: #64748b; font-style: italic;">(Çıktı yok — Kod: {code})</div>')

            # Son satıra kaydır
            self.txt_output.moveCursor(QTextCursor.End)
            status_text = 'Tamamlandı' if code == 0 else 'Hata kodu ile bitti'
            self.lbl_status.setText('{} (Kod: {})'.format(status_text, code))

        def failed(err):
            self._busy = False
            self.btn_run.setEnabled(True)
            if not self._target_is_current(target, generation):
                self.lbl_status.setText('Hedef değişti; eski cihazın komut hatası gösterilmedi.')
                return
            if str(err).strip().casefold() in (
                    'kullanıcı durdurdu', 'kullanici durdurdu'):
                self.lbl_status.setText('Komut durduruldu.')
                return
            fail_html = f'<div style="color: #ef4444; font-weight: bold; margin-top: 4px;">[BAŞARISIZ] {html.escape(str(err))}</div>'
            self.txt_output.appendHtml(fail_html)
            self.lbl_status.setText('Hata: ' + str(err))

        w = Worker(do)
        worker_ref['worker'] = w
        w.finished_ok.connect(done)
        w.failed.connect(failed)
        self.window._run(w)

    def eventFilter(self, watched, event):
        if (watched is self.txt_cmd and event.type() == QEvent.KeyPress
                and event.modifiers() == Qt.NoModifier
                and event.key() in (Qt.Key_Up, Qt.Key_Down)):
            if not self._history:
                return False
            if event.key() == Qt.Key_Up:
                if self._history_idx == len(self._history):
                    self._history_draft = self.txt_cmd.text()
                self._history_idx = max(0, self._history_idx - 1)
            else:
                self._history_idx = min(len(self._history), self._history_idx + 1)
            self.txt_cmd.setText(
                self._history[self._history_idx] if self._history_idx < len(self._history)
                else self._history_draft)
            self.txt_cmd.setCursorPosition(len(self.txt_cmd.text()))
            return True
        return super().eventFilter(watched, event)
