# -*- coding: utf-8 -*-
"""Turkish, read-only landing dashboard for MiBox Konsol."""
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from . import kit
from .icons import line_icon


class OverviewTab(QWidget):
    """Quick access to device tools plus this session's recent operations."""

    _MAX_ACTIONS = 5

    def __init__(self, core, window):
        super().__init__()
        self.core = core
        self.window = window
        self._actions = []
        self._cards = []
        self._card_icons = []
        self._columns = 0
        self._connected = bool(getattr(core, 'connected', False))
        self._target = str(getattr(core, 'target', '') or '')

        self.setObjectName('overviewPage')
        root = kit.page(self)

        intro = QLabel(
            'Mi Box yönetimi, uygulama kurulumu ve bakım araçlarına tek yerden ulaşın.'
        )
        intro.setProperty('role', 'secondary')
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.connection_card = QFrame()
        self.connection_card.setObjectName('contentCard')
        connection_layout = QHBoxLayout(self.connection_card)
        connection_layout.setContentsMargins(16, 12, 16, 12)
        connection_layout.setSpacing(12)

        self.connection_dot = QLabel('●')
        self.connection_dot.setAlignment(Qt.AlignCenter)
        connection_layout.addWidget(self.connection_dot, 0, Qt.AlignTop)

        connection_copy = QVBoxLayout()
        connection_copy.setSpacing(3)
        self.connection_title = QLabel()
        self.connection_title.setObjectName('cardTitle')
        self.connection_detail = QLabel()
        self.connection_detail.setProperty('role', 'secondary')
        self.connection_detail.setWordWrap(True)
        self.connection_target = QLabel()
        self.connection_target.setProperty('role', 'secondary')
        self.connection_target.setTextFormat(Qt.PlainText)
        connection_copy.addWidget(self.connection_title)
        connection_copy.addWidget(self.connection_detail)
        connection_copy.addWidget(self.connection_target)
        connection_actions = kit.action_bar()
        self.btn_target = QPushButton('Adres gir')
        self.btn_target.clicked.connect(self._focus_target)
        self.btn_find_device = QPushButton('Cihaz bul')
        self.btn_find_device.clicked.connect(lambda: self._navigate('tab_network'))
        self.btn_connection_help = QPushButton('Bağlantı yardımı')
        self.btn_connection_help.clicked.connect(self._connection_help)
        for button in (self.btn_target, self.btn_find_device, self.btn_connection_help):
            button.setProperty('role', 'quiet')
            connection_actions.addWidget(button)
        connection_copy.addLayout(connection_actions)
        connection_layout.addLayout(connection_copy, 1)

        self.connection_badge = QLabel()
        self.connection_badge.setProperty('role', 'badge')
        self.connection_badge.setAlignment(Qt.AlignCenter)
        connection_layout.addWidget(self.connection_badge, 0, Qt.AlignVCenter)
        root.addWidget(self.connection_card)

        section_title = QLabel('Hızlı erişim')
        section_title.setObjectName('cardTitle')
        root.addWidget(section_title)

        self.cards_grid = QGridLayout()
        self.cards_grid.setContentsMargins(0, 0, 0, 0)
        self.cards_grid.setHorizontalSpacing(10)
        self.cards_grid.setVerticalSpacing(10)
        root.addLayout(self.cards_grid)

        self._add_action_card(
            'Uygulamalar', 'Yüklü TV uygulamalarını görüntüleyin ve yönetin.',
            'apps', [('Uygulamaları aç', lambda: self._navigate('tab_apps'), 'quiet')],
        )
        self._add_action_card(
            'Kumanda', 'Gezinme, ses ve oynatma kontrollerine ulaşın.',
            'remote', [('Kumandayı aç', lambda: self._navigate('tab_remote'), 'quiet')],
        )
        self._add_action_card(
            'Uygulama kurulumu', 'TV için seçilmiş uygulamalara göz atın veya APK kurun.',
            'install', [
                ('Kataloğu aç', self._open_catalog, 'primary'),
                ('Yerel APK', self._open_local_install, 'quiet'),
            ],
        )
        self._add_action_card(
            'Sağlık ve bakım', 'Cihaz durumunu ve bakım araçlarını inceleyin.',
            'health', [('Sağlığı incele', lambda: self._navigate('tab_health'), 'quiet')],
        )
        self._add_action_card(
            'Dosyalar', 'TV’deki dosyalara göz atın ve aktarım araçlarını kullanın.',
            'files', [('Dosyaları aç', lambda: self._navigate('tab_files'), 'quiet')],
        )
        self._add_action_card(
            'Ağ', 'Cihaz keşfi ve ağ araçlarını açın.',
            'network', [('Ağ araçlarını aç', lambda: self._navigate('tab_network'), 'quiet')],
        )

        self.activity_card = QFrame()
        self.activity_card.setObjectName('contentCard')
        activity_layout = QVBoxLayout(self.activity_card)
        activity_layout.setContentsMargins(16, 12, 16, 12)
        activity_layout.setSpacing(8)
        activity_header = QHBoxLayout()
        activity_title = QLabel('Son işlemler')
        activity_title.setObjectName('cardTitle')
        activity_note = QLabel('Bu oturum')
        activity_note.setProperty('role', 'secondary')
        activity_header.addWidget(activity_title)
        activity_header.addStretch(1)
        activity_header.addWidget(activity_note)
        history_button = QPushButton('Geçmişi aç')
        history_button.setProperty('role', 'quiet')
        history_button.clicked.connect(lambda: self._navigate('tab_history'))
        activity_header.addWidget(history_button)
        activity_layout.addLayout(activity_header)
        self.activity_rows = QVBoxLayout()
        self.activity_rows.setSpacing(5)
        activity_layout.addLayout(self.activity_rows)
        root.addWidget(self.activity_card)
        root.addStretch(1)

        signal = getattr(core, 'connection_changed', None)
        if signal is not None:
            try:
                signal.connect(self._on_connection_changed)
            except (AttributeError, RuntimeError, TypeError):
                pass

        self.apply_theme()
        self.refresh()
        self._render_actions()
        self._reflow_cards()

    def _add_action_card(self, title, description, icon_name, actions):
        card = QFrame()
        card.setObjectName('contentCard')
        card.setMinimumHeight(142)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)

        heading = QHBoxLayout()
        heading.setSpacing(9)
        icon = QLabel()
        icon.setFixedSize(25, 25)
        icon.setAlignment(Qt.AlignCenter)
        heading.addWidget(icon)
        title_label = QLabel(title)
        title_label.setObjectName('cardTitle')
        title_label.setWordWrap(True)
        heading.addWidget(title_label, 1)
        layout.addLayout(heading)
        self._card_icons.append((icon, icon_name))

        description_label = QLabel(description)
        description_label.setProperty('role', 'secondary')
        description_label.setWordWrap(True)
        layout.addWidget(description_label, 1)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        action_row.addStretch(1)
        for text, callback, role in actions:
            button = QPushButton(text)
            button.setProperty('role', role)
            button.clicked.connect(callback)
            action_row.addWidget(button)
        layout.addLayout(action_row)

        self._cards.append(card)

    def _navigate(self, page_name):
        tabs = getattr(self.window, 'tabs', None)
        page = getattr(self.window, page_name, None)
        if tabs is not None and page is not None:
            tabs.setCurrentWidget(page)

    def _focus_target(self):
        callback = getattr(self.window, 'focus_target', None)
        if callable(callback):
            callback()

    def _connection_help(self):
        callback = getattr(self.window, 'open_connection_help', None)
        if callable(callback):
            callback()

    def _open_catalog(self):
        callback = getattr(self.window, 'open_catalog', None)
        if callable(callback):
            callback()
        else:
            self._navigate('tab_install')

    def _open_local_install(self):
        callback = getattr(self.window, 'open_local_install', None)
        if callable(callback):
            callback()
        else:
            self._navigate('tab_install')

    def _on_connection_changed(self, connected, target):
        self._set_connection(bool(connected), str(target or ''))

    def _set_connection(self, connected, target):
        self._connected = bool(connected)
        self._target = str(target or '')
        busy = bool(getattr(self.window, '_connection_busy', False))
        self.btn_target.setEnabled(not busy)
        if busy:
            self.connection_title.setText('Bağlantı işlemi sürüyor')
            self.connection_detail.setText('İşlemin sonucu üstteki bağlantı alanında gösterilir.')
            self.connection_badge.setText('BEKLEYİN')
            self.connection_badge.setProperty('role', 'badge')
        elif self._connected:
            self.connection_title.setText('Cihaz bağlı')
            self.connection_detail.setText('TV yönetim araçları kullanıma hazır.')
            self.connection_badge.setText('BAĞLI')
            self.connection_badge.setProperty('role', 'badge-success')
        else:
            self.connection_title.setText('Cihaz bağlantısı yok')
            self.connection_detail.setText(
                'Bağlanmak için üstteki bağlantı alanından cihaz adresini seçin '
                've Bağlan düğmesine basın.'
            )
            self.connection_badge.setText('ÇEVRİMDIŞI')
            self.connection_badge.setProperty('role', 'badge')
        self.connection_target.setText(
            'Hedef: {}'.format(self._target) if self._target else ''
        )
        palette = kit.colors(self)
        dot_color = palette['success'] if self._connected else palette['faint']
        self.connection_dot.setStyleSheet('color: {};'.format(dot_color))
        # A dynamic property change needs a style polish to apply the shared badge QSS.
        self.connection_badge.style().unpolish(self.connection_badge)
        self.connection_badge.style().polish(self.connection_badge)

    def _render_actions(self):
        while self.activity_rows.count():
            item = self.activity_rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not self._actions:
            empty = QLabel('Bu oturumda henüz işlem yapılmadı.')
            empty.setProperty('role', 'secondary')
            empty.setTextFormat(Qt.PlainText)
            self.activity_rows.addWidget(empty)
            return

        for timestamp, text in self._actions:
            row = QWidget()
            row.setAttribute(Qt.WA_StyledBackground, False)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(12)
            time_label = QLabel(timestamp)
            time_label.setProperty('role', 'secondary')
            time_label.setTextFormat(Qt.PlainText)
            time_label.setMinimumWidth(58)
            text_label = QLabel(text)
            text_label.setProperty('role', 'secondary')
            text_label.setTextFormat(Qt.PlainText)
            text_label.setWordWrap(True)
            row_layout.addWidget(time_label, 0, Qt.AlignTop)
            row_layout.addWidget(text_label, 1)
            self.activity_rows.addWidget(row)

    def record_action(self, text):
        """Add a plain-text operation to the bounded, in-memory session list."""
        action = str(text or '').strip()
        if not action:
            return
        self._actions.insert(0, (datetime.now().strftime('%H:%M:%S'), action[:240]))
        del self._actions[self._MAX_ACTIONS:]
        self._render_actions()

    def refresh(self):
        """Refresh the connection summary from in-memory core state only."""
        self._set_connection(
            bool(getattr(self.core, 'connected', False)),
            str(getattr(self.core, 'target', '') or ''),
        )

    def apply_theme(self):
        palette = kit.colors(self)
        for icon_label, icon_name in self._card_icons:
            icon_label.setPixmap(line_icon(icon_name, palette['accent']).pixmap(24, 24))
        self._set_connection(self._connected, self._target)

    def _reflow_cards(self):
        width = self.width()
        columns = 3 if width >= 700 else 2 if width >= 500 else 1
        if columns == self._columns:
            return
        for card in self._cards:
            self.cards_grid.removeWidget(card)
        for column in range(max(self._columns, columns)):
            self.cards_grid.setColumnStretch(column, 0)
        for index, card in enumerate(self._cards):
            self.cards_grid.addWidget(card, index // columns, index % columns)
        for column in range(columns):
            self.cards_grid.setColumnStretch(column, 1)
        self._columns = columns

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self._reflow_cards()
