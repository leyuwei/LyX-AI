"""Desktop assistant and its separate model-configuration dialog."""
from __future__ import annotations

import copy
import json
import os

from PySide6.QtCore import Qt, QTimer, QThread, Signal, QUrl, QRect
from PySide6.QtGui import QFont, QTextCursor, QTextDocument, QIcon, QDesktopServices, QSurface
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QHBoxLayout, QGridLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter,
    QTabWidget, QVBoxLayout, QWidget, QSizePolicy,
)

from .core import (PRESETS, PROTOCOLS, Store, build_request, json_object, new_profile,
                   preview_request, render_prompt)
from .network import NetworkJob
from .selection import compose_context
from .preview import ASSETS, RichPreview
from .replacement import revised_text
from .history import HistoryStore, timestamp, transcript
from . import __version__


STYLE = """
QWidget { font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 10pt; color: #22364a; background: #ffffff; }
QMainWindow, QDialog, QScrollArea { background: #ffffff; }
QPlainTextEdit, QLineEdit, QComboBox, QListWidget, QDoubleSpinBox {
 background: white; color: #22364a; border: 1px solid #cddce5; border-radius: 8px; padding: 8px;
 selection-background-color: #c6ece9; selection-color: #16354b;
}
QPlainTextEdit:focus, QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus { border: 1px solid #168f98; background: #fcffff; }
QComboBox { padding-right: 30px; min-height: 20px; }
QComboBox::drop-down { width: 28px; border: none; border-left: 1px solid #e1e9ef; }
QComboBox::down-arrow { image: url(ARROW_ASSET); width: 12px; height: 8px; }
QComboBox QAbstractItemView { background: white; border: 1px solid #cddce5; padding: 5px; outline: 0; selection-background-color: #deefef; selection-color: #16495a; }
QAbstractItemView::item { min-height: 28px; padding: 3px; border-radius: 4px; }
QPushButton { padding: 9px 15px; border-radius: 8px; border: 1px solid #c8d9e3; background: #ffffff; color: #29465c; font-weight: 500; }
QPushButton:hover { background: #e4f2f2; border-color: #76b9bf; }
QPushButton:pressed { background: #cde7e8; }
QPushButton:focus { border: 2px solid #168f98; padding: 8px 14px; }
QPushButton:disabled { color: #758595; background: #ffffff; border-color: #e0e7ec; }
QPushButton[primary="true"] { background: #176f83; color: white; border-color: #176f83; }
QPushButton[primary="true"]:hover { background: #125b70; }
QPushButton[primary="true"]:disabled { background: #a7bcc6; border-color: #a7bcc6; }
QTabWidget::pane { border: 1px solid #d5e1e9; background: #fff; border-radius: 8px; }
QTabBar::tab { padding: 9px 16px; background: transparent; color: #607589; border-bottom: 3px solid transparent; }
QTabBar::tab:selected { color: #14697b; background: #fff; border-bottom: 3px solid #24a3a8; }
QTabBar::tab:hover { color: #14697b; background: #e7f1f5; }
QLabel[muted="true"] { color: #62788a; }
QLabel#brand { font-size: 24px; font-weight: 700; color: #174e68; }
QSplitter::handle { background: #ffffff; height: 5px; }
QSplitter::handle:hover { background: #c6ece9; }
QScrollBar:vertical { width: 10px; background: #ffffff; }
QScrollBar::handle:vertical { background: #c2d3de; border-radius: 5px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""
STYLE = STYLE.replace('ARROW_ASSET', str(ASSETS / 'chevron.svg').replace('\\', '/'))


class BridgeJob(QThread):
    result = Signal(object)
    error = Signal(str)

    def __init__(self, fn, parent):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.result.emit(self.fn())
        except Exception as exc:
            self.error.emit(str(exc))


def combo(items):
    box = QComboBox()
    for label, value in items:
        box.addItem(label, value)
    return box


def choose(box, value):
    index = box.findData(value)
    box.setCurrentIndex(max(0, index))


def note(text):
    widget = QLabel(text)
    widget.setWordWrap(True)
    widget.setProperty("muted", True)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget


class StatusLine(QLabel):
    """One visual line, with the complete message available in its tooltip."""
    def __init__(self, text=''):
        super().__init__()
        self.setProperty('muted', True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self.fontMetrics().height() + 6)
        self.setText(text)

    def setText(self, text):
        self.full_text = str(text)
        self.setToolTip(self.full_text)
        self.setAccessibleDescription(self.full_text)
        self.update_line()

    def update_line(self):
        super().setText(self.fontMetrics().elidedText(' '.join(self.full_text.split()), Qt.TextElideMode.ElideRight, max(0, self.width())))

    def resizeEvent(self, event):
        self.update_line()
        super().resizeEvent(event)


def fit_window(widget, state, preferred):
    """Restore logical screen coordinates, keeping the whole window on screen."""
    saved = state.get('geometry', [])
    screens = QApplication.screens()
    screen = widget.screen() or screens[0]
    if len(saved) == 4 and all(isinstance(n, int) for n in saved):
        rectangle = QRect(*saved)
        screen = max(screens, key=lambda s: s.availableGeometry().intersected(rectangle).width() * s.availableGeometry().intersected(rectangle).height())
        width, height = saved[2:]
    else:
        width, height = preferred
    area = screen.availableGeometry().adjusted(12, 12, -12, -40)
    width, height = min(max(480, width), area.width()), min(max(360, height), area.height())
    x, y = saved[:2] if len(saved) == 4 else (area.x() + (area.width()-width)//2, area.y() + (area.height()-height)//2)
    widget.setGeometry(max(area.left(), min(x, area.right()-width+1)), max(area.top(), min(y, area.bottom()-height+1)), width, height)
    if state.get('maximized'):
        widget.setWindowState(widget.windowState() | Qt.WindowState.WindowMaximized)


def window_state(widget):
    rect = widget.normalGeometry() if widget.isMaximized() else widget.geometry()
    return dict(geometry=[rect.x(), rect.y(), rect.width(), rect.height()], maximized=widget.isMaximized())


class PassageDialog(QDialog):
    """Edit a copy; only Save commits it to the request's text document."""
    def __init__(self, title, text, parent):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowIcon(parent.windowIcon())
        self.setMinimumSize(480, 360)
        layout = QVBoxLayout(self)
        layout.addWidget(note(parent.t('查看或修改内容，点击保存后用于下一次问询。取消不会改变内容。',
                                      'Review or edit this text. Save uses it in the next request; Cancel keeps the original.')))
        self.editor = QPlainTextEdit(text)
        self.editor.setAccessibleName(title)
        layout.addWidget(self.editor, 1)
        self.count = note('')
        self.editor.textChanged.connect(self.update_count)
        self.update_count()
        layout.addWidget(self.count)
        buttons = QDialogButtonBox()
        buttons.addButton(parent.t('保存', 'Save'), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(parent.t('取消', 'Cancel'), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        fit_window(self, parent.config.get('ui_state', {}).get('passage', {}), (800, 600))

    def update_count(self):
        size = len(self.editor.toPlainText())
        self.count.setText(self.parent().t(f'{size} 字符', f'{size} characters'))

    def done(self, result):
        self.parent().config.setdefault('ui_state', {})['passage'] = window_state(self)
        self.parent().schedule_preferences()
        super().done(result)


class HistoryDialog(QDialog):
    def __init__(self, archive, lang, parent=None):
        super().__init__(parent)
        self.archive, self.lang = archive, lang
        self.session = None
        self.limit = 100
        self.ui_state = parent.config.get('ui_state', {}).get('history', {}) if parent else {}
        t = lambda zh, en: zh if lang == 'zh' else en
        self.setWindowTitle(t('问答历史', 'Conversation history'))
        self.setWindowIcon(QIcon(str(ASSETS / 'logo.svg')))
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText(t('搜索原文、问题或回答', 'Search passages, questions or answers'))
        layout.addWidget(self.search)
        split = self.split = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(split, 1)
        self.list = QListWidget()
        split.addWidget(self.list)
        page = QWidget()
        content = QVBoxLayout(page)
        content.setContentsMargins(0, 0, 0, 0)
        self.turns = QComboBox()
        self.turns.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.turns.setAccessibleName(t('问答轮次', 'Conversation turn'))
        self.turns.currentIndexChanged.connect(self.select_turn)
        content.addWidget(self.turns)
        self.reply_status = StatusLine()
        content.addWidget(self.reply_status)
        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setMinimumWidth(0)
        for name, title in (('reply', t('AI 回复', 'AI reply')), ('question', t('用户问询', 'User question')),
                            ('thinking', t('思考 / 摘要', 'Reasoning / summary')), ('detail', t('完整对话', 'Full conversation'))):
            editor = QPlainTextEdit()
            editor.setReadOnly(True)
            editor.setAccessibleName(title)
            setattr(self, name, editor)
            self.tabs.addTab(editor, title)
        self.reply.setPlaceholderText(t('该轮尚未收到 AI 回复。', 'No AI reply was received for this turn.'))
        content.addWidget(self.tabs, 1)
        split.addWidget(page)
        split.setSizes(self.ui_state.get('splitter', [160, 360]))
        layout.addWidget(note(t('历史仅保存在本机，不含接口密钥。载入后可继续追问；写回使用当前已连接的 LyX 文档。', 'Stored locally without API credentials. Load to continue; writeback uses the currently connected LyX document.')))
        row = QHBoxLayout()
        self.load_btn = button(t('载入对话', 'Load conversation'), self.accept, True)
        self.delete_btn = button(t('删除选中记录', 'Delete selected'), self.delete_selected)
        row.addWidget(self.load_btn)
        row.addWidget(self.delete_btn)
        self.more_btn = button(t('加载更多', 'Load more'), self.more)
        row.addWidget(self.more_btn)
        row.addStretch()
        row.addWidget(button(t('关闭', 'Close'), self.reject))
        layout.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(self.search_changed)
        self.list.currentItemChanged.connect(self.select)
        self.list.itemDoubleClicked.connect(lambda _: self.accept() if self.session else None)
        fit_window(self, self.ui_state, (850, 680))
        self.refresh()

    def done(self, result):
        if self.parent():
            self.parent().config.setdefault('ui_state', {})['history'] = dict(window_state(self), splitter=self.split.sizes())
            self.parent().schedule_preferences()
        super().done(result)

    def refresh(self):
        self.list.clear()
        for identity, title, updated in self.archive.list(self.search.text(), self.limit):
            item = QListWidgetItem(updated[:19].replace('T', ' ') + '  ' + title)
            item.setData(Qt.ItemDataRole.UserRole, identity)
            self.list.addItem(item)
        self.list.setCurrentRow(0)
        if not self.list.count():
            self.select(None)
        self.more_btn.setEnabled(self.list.count() == self.limit)

    def search_changed(self):
        self.limit = 100
        self.timer.start()

    def more(self):
        self.limit += 100
        self.refresh()

    def select(self, item, previous=None):
        self.session = self.archive.get(item.data(Qt.ItemDataRole.UserRole)) if item else None
        self.detail.setPlainText(transcript(self.session) if self.session else '')
        self.turns.blockSignals(True)
        self.turns.clear()
        for index, turn in enumerate(self.session.get('turns', []) if self.session else []):
            model = turn.get('profile', {}).get('model', '')
            self.turns.addItem(f'{index + 1} · {turn.get("time", "")[:19].replace("T", " ")} · {model}', index)
        self.turns.setCurrentIndex(self.turns.count() - 1)
        self.turns.blockSignals(False)
        self.select_turn()
        self.tabs.setCurrentIndex(0)
        self.load_btn.setEnabled(bool(self.session))
        self.delete_btn.setEnabled(bool(self.session))

    def select_turn(self):
        index = self.turns.currentIndex()
        turn = self.session['turns'][index] if self.session and index >= 0 else {}
        self.reply.setPlainText(turn.get('answer', ''))
        self.question.setPlainText(turn.get('question', ''))
        self.thinking.setPlainText(turn.get('reasoning', ''))
        states = {'complete': ('已完成', 'Complete'), 'incomplete': ('回答不完整', 'Incomplete reply'),
                  'cancelled': ('已取消，显示已收到的回复', 'Cancelled; showing received reply'),
                  'error': ('请求失败，显示已收到的回复', 'Failed; showing received reply'),
                  'interrupted': ('已中断，显示已收到的回复', 'Interrupted; showing received reply'),
                  'pending': ('请求进行中', 'Request in progress')}
        state = turn.get('status', '')
        labels = states.get(state, (state, state))
        self.reply_status.setText((labels[0] if self.lang == 'zh' else labels[1]) + (' · ' + turn['error'] if turn.get('error') else ''))
        self.turns.setEnabled(bool(self.turns.count()))

    def delete_selected(self):
        if self.session:
            self.archive.delete(self.session['id'])
            self.refresh()


def button(text, callback, primary=False):
    b = QPushButton(text)
    b.setProperty("primary", primary)
    b.clicked.connect(callback)
    return b


def show_text(parent, title, text):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.resize(790, 650)
    layout = QVBoxLayout(dlg)
    editor = QPlainTextEdit(text)
    editor.setReadOnly(True)
    layout.addWidget(editor)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)
    dlg.exec()


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = copy.deepcopy(config)
        self.lang = config.get("language", "zh")
        self.profiles = self.config["profiles"]
        self.current = -1
        self.job = None
        self.setWindowTitle(self.t("AI 模型配置", "AI model configuration"))
        self.setWindowIcon(QIcon(str(ASSETS / 'logo.svg')))
        self.ui_state = self.config.get('ui_state', {}).get('settings', {})
        outer = QVBoxLayout(self)
        outer.addWidget(note(self.t("每个配置档独立保存接口、模型和参数。中转站可修改地址并选择其实际协议。", "Each profile has its own endpoint, model and parameters. For a relay, select the protocol it actually serves.")))
        split = self.split = QSplitter()
        split.setChildrenCollapsible(False)
        outer.addWidget(split, 1)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        self.list = QListWidget()
        self.list.setMinimumWidth(0)
        self.list.setAccessibleName(self.t("模型配置档", "Model profiles"))
        ll.addWidget(self.list)
        row = QHBoxLayout()
        for label, fn in ((self.t("新增", "Add"), self.add_profile), (self.t("复制", "Duplicate"), self.duplicate), (self.t("删除", "Delete"), self.remove_profile)):
            row.addWidget(button(label, fn))
        ll.addLayout(row)
        split.addWidget(left)
        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setMinimumWidth(0)
        split.addWidget(self.tabs)
        split.setSizes([225, 760])
        self.fields = {}
        connection = self.form_tab(self.t("连接", "Connection"))
        self.field(connection, "name", self.t("配置名称", "Profile name"), QLineEdit())
        self.provider = combo([(k, k) for k in PRESETS])
        self.field(connection, "provider", self.t("服务商预设", "Provider preset"), self.provider)
        self.field(connection, "protocol", self.t("接口协议", "API protocol"), combo([(v, k) for k, v in PROTOCOLS.items()]))
        self.field(connection, "url", "Base URL / " + self.t("完整端点", "full endpoint"), QLineEdit())
        key = QLineEdit()
        key.setEchoMode(QLineEdit.EchoMode.Password)
        self.field(connection, "api_key", "API Key", key)
        self.field(connection, "auth", self.t("认证方式", "Authentication"), combo([(self.t("随协议自动选择", "Protocol default"), "auto"), ("Bearer token", "bearer"), ("x-api-key", "x-api-key"), (self.t("仅使用自定义头 / 无认证", "Custom headers only / None"), "none")]))
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems([v[2] for v in PRESETS.values() if v[2]])
        self.field(connection, "model", self.t("模型 ID（可手填）", "Model ID (editable)"), self.model)
        self.system = QPlainTextEdit()
        self.system.setMaximumHeight(95)
        self.field(connection, "system", self.t("系统提示词", "System prompt"), self.system)
        self.coding_note = note("")
        connection.addRow(self.coding_note)
        connection.addRow(note(self.t("密钥和自定义请求头使用 Windows DPAPI 或 macOS 钥匙串保护。连接测试会发送一条简短请求，可能产生 API 费用。", "Keys and custom headers are protected by Windows DPAPI or macOS Keychain. Connection tests send a short request and may incur API charges.")))

        generation = self.form_tab(self.t("生成参数", "Generation"))
        self.field(generation, "stream", self.t("流式输出", "Streaming"), QCheckBox(self.t("逐步显示回答", "Show response as it arrives")))
        self.field(generation, "max_tokens", self.t("最大输出 tokens", "Maximum output tokens"), QLineEdit())
        self.field(generation, "token_field", self.t("输出上限字段", "Token limit field"), combo([(self.t("按协议自动选择", "Protocol default"), "auto"), ("max_tokens", "max_tokens"), ("max_completion_tokens", "max_completion_tokens"), ("max_output_tokens", "max_output_tokens")]))
        self.numeric = {}
        for name in ("temperature", "top_p", "top_k", "presence_penalty", "frequency_penalty", "seed"):
            edit = QLineEdit()
            edit.setPlaceholderText(self.t("留空：不发送", "Empty: omit"))
            edit.setAccessibleName(name)
            generation.addRow(name, edit)
            self.numeric[name] = edit
        self.stop_edit = QLineEdit()
        self.stop_edit.setPlaceholderText('["END", "STOP"]')
        generation.addRow("stop (JSON)", self.stop_edit)
        generation.addRow(note(self.t("参数取决于模型能力。留空不发送；不支持的参数会由服务端返回错误，可在高级 JSON 中补充或用 null 移除字段。", "Parameter support depends on the model. Blank fields are omitted. Extra JSON can add parameters; null removes a generated field.")))

        thinking = self.form_tab(self.t("思考与深度", "Reasoning"))
        self.field(thinking, "thinking", self.t("思考模式", "Thinking mode"), combo([(self.t("使用模型默认值", "Model default"), "default"), (self.t("启用", "Enabled"), "enabled"), (self.t("禁用", "Disabled"), "disabled"), (self.t("自适应（Claude）", "Adaptive (Claude)"), "adaptive")]))
        effort = QComboBox()
        effort.setEditable(True)
        effort.addItems(["", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"])
        self.field(thinking, "effort", "Reasoning effort", effort)
        self.field(thinking, "thinking_budget", self.t("思考预算（Claude tokens）", "Thinking budget (Claude tokens)"), QLineEdit())
        self.field(thinking, "verbosity", self.t("输出详略", "Verbosity"), combo([(self.t("模型默认", "Model default"), ""), ("low", "low"), ("medium", "medium"), ("high", "high")]))
        thinking.addRow(note(self.t("不同模型允许的深度值不同。Responses 使用 reasoning.effort；Chat 使用 reasoning_effort；Claude 使用 output_config.effort。Claude 手动思考预算须至少 1024 且小于最大输出；新模型可能只支持 adaptive。其他预算字段可用高级 JSON 配置。", "Allowed effort values vary by model. Responses uses reasoning.effort, Chat uses reasoning_effort, Claude uses output_config.effort. Claude manual budget must be ≥1024 and below max_tokens; some models only support adaptive. Use extra JSON for other budget formats.")))

        network = self.form_tab(self.t("超时与网络", "Timeouts & network"))
        for key, zh, en in (("first_timeout", "等待响应头（秒）", "Response headers timeout (s)"), ("idle_timeout", "读取空闲超时（秒）", "Read idle timeout (s)"), ("total_timeout", "请求总时限（秒）", "Total request deadline (s)")):
            spin = QDoubleSpinBox()
            spin.setRange(0.1, 86400)
            spin.setDecimals(1)
            self.field(network, key, self.t(zh, en), spin)
        proxy = QLineEdit()
        proxy.setPlaceholderText("http://127.0.0.1:7890 / socks5://127.0.0.1:1080")
        self.field(network, "proxy", self.t("代理（可选）", "Proxy (optional)"), proxy)
        network.addRow(note(self.t("留空使用 Qt/系统默认网络设置。请求可随时取消；不自动重试计费请求。HTTPS 证书正常校验，重定向不会自动携带密钥跳转。", "Blank uses Qt/system network defaults. Requests can be cancelled; billable requests are not automatically retried. TLS is verified and redirects are not followed with credentials.")))

        advanced = self.form_tab(self.t("高级 JSON", "Advanced JSON"))
        self.extra = QPlainTextEdit()
        self.extra.setPlaceholderText('{"response_format": {"type": "json_object"}}')
        self.extra.setMinimumHeight(145)
        advanced.addRow(self.t("额外请求体（合并）", "Extra request body (merged)"), self.extra)
        self.headers = QPlainTextEdit()
        self.headers.setMinimumHeight(100)
        self.headers.setPlaceholderText('{"anthropic-beta": "...", "X-Custom-Auth": "..."}')
        advanced.addRow(self.t("自定义请求头（加密保存）", "Custom headers (encrypted)"), self.headers)
        advanced.addRow(note(self.t("支持服务商和中转站新增参数。可覆盖生成参数；不能覆盖模型、对话或流式开关。请勿在请求体中配置需要执行的工具，本助手只处理文字回答。", "Supports provider and relay-specific parameters. Overrides generation settings; cannot replace model, conversation or streaming fields. This assistant processes text answers and does not execute tools.")))
        actions = QHBoxLayout()
        self.fetch_btn = button(self.t("获取模型列表", "Fetch models"), self.fetch_models)
        self.test_btn = button(self.t("测试连接", "Test connection"), self.test_connection)
        actions.addWidget(self.fetch_btn)
        actions.addWidget(self.test_btn)
        actions.addWidget(button(self.t("预览请求", "Preview request"), self.preview))
        actions.addStretch()
        outer.addLayout(actions)
        self.status = QPlainTextEdit()
        self.status.setReadOnly(True)
        self.status.setMaximumHeight(85)
        self.status.setPlaceholderText(self.t("测试结果会显示在这里。", "Connection test results appear here."))
        outer.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(self.t("保存", "Save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(self.t("取消", "Cancel"))
        buttons.accepted.connect(self.accept_settings)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.provider.currentIndexChanged.connect(self.change_provider)
        self.list.currentRowChanged.connect(self.switch_profile)
        active = self.ui_state.get('profile', self.config.get('active'))
        self.refresh_list(next((i for i, p in enumerate(self.profiles) if p['id'] == active), 0))
        self.tabs.setCurrentIndex(min(self.ui_state.get('tab', 0), self.tabs.count()-1))
        fit_window(self, self.ui_state, (1010, 770))
        self.adapt_layout()
        if self.ui_state.get('splitter'):
            self.split.setSizes(self.ui_state['splitter'])

    def adapt_layout(self):
        vertical = self.width() < 800
        self.split.setOrientation(Qt.Orientation.Vertical if vertical else Qt.Orientation.Horizontal)
        self.list.parentWidget().setMaximumHeight(150 if vertical else 16777215)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'split'):
            self.adapt_layout()

    def t(self, zh, en):
        return zh if self.lang == "zh" else en

    def form_tab(self, title):
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(11)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(widget)
        self.tabs.addTab(scroll, title)
        return form

    def field(self, form, name, label, widget):
        self.fields[name] = widget
        widget.setObjectName(name)
        widget.setAccessibleName(label)
        form.addRow(label, widget)

    def refresh_list(self, index):
        self.list.blockSignals(True)
        self.list.clear()
        self.list.addItems([p["name"] for p in self.profiles])
        self.list.setCurrentRow(index)
        self.list.blockSignals(False)
        self.current = index
        self.load_profile()

    def load_profile(self):
        p = self.profiles[self.current]
        for name, widget in self.fields.items():
            widget.blockSignals(True)
            value = p.get(name)
            if isinstance(widget, QLineEdit):
                widget.setText("" if value is None else str(value))
            elif isinstance(widget, QPlainTextEdit):
                widget.setPlainText(value or "")
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QDoubleSpinBox):
                widget.setValue(float(value or 120))
            elif widget.isEditable():
                widget.setEditText(value or "")
            else:
                choose(widget, value)
            widget.blockSignals(False)
        extra = copy.deepcopy(p.get("params", {}))
        for name, widget in self.numeric.items():
            value = extra.pop(name, None)
            widget.setText("" if value is None else str(value))
        stop = extra.pop("stop", None)
        self.stop_edit.setText("" if stop is None else json.dumps(stop, ensure_ascii=False))
        self.extra.setPlainText(json.dumps(extra, ensure_ascii=False, indent=2))
        self.headers.setPlainText(json.dumps(p.get("headers", {}), ensure_ascii=False, indent=2))
        self.update_coding_note()

    def collect(self):
        p = copy.deepcopy(self.profiles[self.current])
        for name, widget in self.fields.items():
            if isinstance(widget, QLineEdit):
                value = widget.text().strip() if name != "api_key" else widget.text()
                if name in ("max_tokens", "thinking_budget"):
                    value = int(value) if value else None
            elif isinstance(widget, QPlainTextEdit):
                value = widget.toPlainText()
            elif isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, QDoubleSpinBox):
                value = widget.value()
            else:
                value = widget.currentText().strip() if widget.isEditable() else widget.currentData()
            p[name] = value
        if not p["name"]:
            raise ValueError(self.t("请填写配置名称", "Profile name is required"))
        params = {}
        for name, widget in self.numeric.items():
            raw = widget.text().strip()
            if raw:
                value = json.loads(raw)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise ValueError(name + ": expected number / 需要数字")
                if name in ("top_k", "seed") and not isinstance(value, int):
                    raise ValueError(name + ": expected integer / 需要整数")
                params[name] = value
        if self.stop_edit.text().strip():
            stop = json.loads(self.stop_edit.text())
            if not (isinstance(stop, str) or isinstance(stop, list) and all(isinstance(x, str) for x in stop)):
                raise ValueError("stop: expected JSON string or array of strings")
            params["stop"] = stop
        params.update(json_object(self.extra.toPlainText(), "Extra JSON"))
        p["params"] = params
        p["headers"] = json_object(self.headers.toPlainText(), "Headers JSON")
        # Permit saving a draft without an endpoint/model/key; request-time validation
        # remains strict. JSON and numbers must always be well formed.
        json.dumps(p, allow_nan=False)
        return p

    def stash(self):
        if self.current < 0:
            return True
        try:
            self.profiles[self.current] = self.collect()
            return True
        except Exception as exc:
            self.status.setPlainText(str(exc))
            return False

    def switch_profile(self, index):
        if index < 0 or index == self.current:
            return
        if not self.stash():
            self.list.blockSignals(True)
            self.list.setCurrentRow(self.current)
            self.list.blockSignals(False)
            return
        self.current = index
        self.load_profile()

    def add_profile(self):
        if not self.stash():
            return
        provider, ok = QInputDialog.getItem(self, self.t("新增配置", "Add profile"), self.t("服务商", "Provider"), list(PRESETS), 0, False)
        if ok:
            self.profiles.append(new_profile(provider))
            self.refresh_list(len(self.profiles) - 1)

    def duplicate(self):
        if not self.stash():
            return
        p = copy.deepcopy(self.profiles[self.current])
        p["id"] = new_profile()["id"]
        p["name"] += self.t(" 副本", " copy")
        self.profiles.append(p)
        self.refresh_list(len(self.profiles) - 1)

    def remove_profile(self):
        if len(self.profiles) == 1:
            self.status.setPlainText(self.t("至少保留一个配置档。", "Keep at least one profile."))
            return
        del self.profiles[self.current]
        self.refresh_list(min(self.current, len(self.profiles) - 1))

    def change_provider(self):
        p = new_profile(self.provider.currentData())
        for name in ("url", "model", "api_key"):
            widget = self.fields[name]
            if isinstance(widget, QComboBox):
                widget.setEditText(p[name])
            else:
                widget.setText(p[name])
        choose(self.fields["protocol"], p["protocol"])
        choose(self.fields["auth"], "auto")
        self.headers.setPlainText("{}")
        self.update_coding_note()

    def update_coding_note(self):
        is_coding = self.provider.currentData() == "BigModel Coding"
        self.coding_note.setText(self.t("Coding 套餐有指定工具和用途限制；本扩展未获官方认证。请确认你的账户允许使用该端点，普通调用可选 GLM / BigModel。", "Coding subscriptions restrict supported tools and uses. This extension is not certified. Confirm endpoint eligibility; choose GLM / BigModel for general API usage.") if is_coding else "")

    def sample_messages(self):
        p = self.collect()
        messages = ([{"role": "system", "content": p["system"]}] if p.get("system") else [])
        return p, messages + [{"role": "user", "content": "Reply with only: OK"}]

    def preview(self):
        try:
            p, messages = self.sample_messages()
            show_text(self, self.t("请求预览（认证已隐藏）", "Request preview (credentials hidden)"), preview_request(p, messages))
        except Exception as exc:
            self.status.setPlainText(str(exc))

    def run_job(self, models=False):
        if self.job:
            return
        try:
            p, messages = self.sample_messages()
            if not models:
                build_request(p, messages)
            self.status.setPlainText(self.t("正在请求…", "Requesting…"))
            self.test_btn.setEnabled(False)
            self.fetch_btn.setEnabled(False)
            self.job = NetworkJob(p, self)
            self.job.completed.connect(self.job_done)
            self.job.failed.connect(self.job_failed)
            self.job.start(messages, models=models)
        except Exception as exc:
            self.job_failed(str(exc))

    def fetch_models(self):
        self.run_job(True)

    def test_connection(self):
        self.run_job(False)

    def job_done(self, result):
        if "models" in result:
            current = self.model.currentText()
            self.model.clear()
            self.model.addItems(result["models"])
            self.model.setEditText(current)
            self.status.setPlainText(self.t("已读取模型列表，可从模型框选择。", "Model list loaded. Select a model in the connection tab."))
        else:
            self.status.setPlainText(self.t("连接成功：", "Connected: ") + result["text"][:500] + "\n" + json.dumps(result.get("usage", {}), ensure_ascii=False))
        self.release_job()

    def job_failed(self, error):
        self.status.setPlainText(error)
        self.release_job()

    def release_job(self):
        self.job = None
        self.test_btn.setEnabled(True)
        self.fetch_btn.setEnabled(True)

    def accept_settings(self):
        if not self.stash():
            return
        ids = [p["id"] for p in self.profiles]
        if self.config["active"] not in ids:
            self.config["active"] = self.profiles[0]["id"]
        self.config["profiles"] = self.profiles
        self.done(QDialog.DialogCode.Accepted)

    def done(self, result):
        if self.job:
            self.job.stop()
        self.config.setdefault('ui_state', {})['settings'] = dict(window_state(self), tab=self.tabs.currentIndex(), profile=self.profiles[self.current]['id'], splitter=self.split.sizes())
        super().done(result)


class MainWindow(QMainWindow):
    def __init__(self, selection="", store=None):
        super().__init__()
        self.store = store or Store()
        # WebEngine's first composited child otherwise upgrades a visible
        # raster window, recreating its native handle on Windows (Qt 6.4+).
        platform = QApplication.platformName()
        if platform == 'cocoa':
            # Qt must create the Metal backing layer with the native window;
            # changing its surface type after winId() leaves an incompatible layer.
            os.environ.setdefault('QT_WIDGETS_RHI', '1')
        elif platform == 'windows':
            self.winId()
            backend = os.environ.get('QSG_RHI_BACKEND', 'd3d11')
            surfaces = {'d3d11': QSurface.SurfaceType.Direct3DSurface,
                        'd3d12': QSurface.SurfaceType.Direct3DSurface,
                        'metal': QSurface.SurfaceType.MetalSurface,
                        'vulkan': QSurface.SurfaceType.VulkanSurface}
            surface = surfaces.get(backend, QSurface.SurfaceType.OpenGLSurface)
            self.windowHandle().setSurfaceType(surface)
        self.config = self.store.load()
        self.lang = self.config.get("language", "zh")
        # Text lives in documents; editors are created only while a popup is open.
        self.selection = QTextDocument(self)
        self.selection.setPlainText(selection)
        self.before = QTextDocument(self)
        self.after = QTextDocument(self)
        for document in (self.selection, self.before, self.after):
            document.contentsChanged.connect(self.update_passage_buttons)
        self.history = []
        self.job = None
        self.pending = None
        self.lyx_payload = None
        self.bridge_job = None
        self.answer_text = ""
        self.reasoning_text = ""
        self.display_pending = [[], []]
        self.display_timer = QTimer(self)
        self.display_timer.setSingleShot(True)
        self.display_timer.setInterval(40)
        self.display_timer.timeout.connect(self.flush_display)
        self.preferences_timer = QTimer(self)
        self.preferences_timer.setSingleShot(True)
        self.preferences_timer.setInterval(500)
        self.preferences_timer.timeout.connect(self.save_preferences)
        self.archive = HistoryStore(self.store.folder)
        self.session = None
        self._building = False
        self.build()
        self.setMinimumSize(480, 420)
        fit_window(self, self.config.get('ui_state', {}).get('main', {}), (1160, 930))
        self.adapt_layout()
        if not selection and self.config.get('last_session'):
            saved = self.archive.get(self.config['last_session'])
            if saved:
                self.restore_session(saved, restore_profile=False)

    def t(self, zh, en):
        return zh if self.lang == "zh" else en

    def build(self):
        self._building = True
        self.setWindowTitle("LyX AI " + __version__ + " · " + self.t("写作助手", "Writing Assistant"))
        self.setWindowIcon(QIcon(str(ASSETS / 'logo.svg')))
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 10, 12, 8)
        top = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QIcon(str(ASSETS / 'logo.svg')).pixmap(44, 44))
        top.addWidget(logo)
        title = QLabel("LyX AI")
        title.setObjectName('brand')
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.DemiBold))
        top.addWidget(title)
        self.tagline = note(self.t("选区问询与写作建议", "Selection review & writing advice"))
        top.addWidget(self.tagline)
        top.addStretch()
        self.language = combo([("简体中文", "zh"), ("English", "en")])
        choose(self.language, self.lang)
        self.language.setAccessibleName("Interface language")
        self.language.currentIndexChanged.connect(self.change_language)
        top.addWidget(self.language)
        self.settings_btn = button(self.t("模型配置…", "Configure models…"), self.settings)
        top.addWidget(self.settings_btn)
        outer.addLayout(top)
        models = QHBoxLayout()
        models.addWidget(QLabel(self.t("模型配置档", "Model profile")))
        self.profile = QComboBox()
        self.profile.setMinimumContentsLength(10)
        self.profile.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.profile.setAccessibleName(self.t("当前模型配置档", "Active model profile"))
        self.fill_profiles()
        self.profile.currentIndexChanged.connect(self.profile_changed)
        models.addWidget(self.profile, 1)
        self.endpoint_label = note("")
        models.addWidget(self.endpoint_label)
        outer.addLayout(models)
        self.update_endpoint()
        panes = self.panes = QSplitter(Qt.Orientation.Vertical)
        panes.setChildrenCollapsible(False)
        outer.addWidget(panes, 1)
        source = QWidget()
        sl = QVBoxLayout(source)
        sl.setContentsMargins(0, 3, 0, 0)
        context_row = QHBoxLayout()
        self.auto_context = QCheckBox(self.t("自动获取正文前后文", "Automatic body context"))
        self.auto_context.setChecked(self.config.get('auto_context', True))
        self.context_radius = combo([(self.t(f"前后各 {n} 字符", f"{n} characters each side"), n) for n in (600, 1200, 1800, 4000, 8000)])
        choose(self.context_radius, self.config.get('context_radius', 1800))
        self.auto_context.toggled.connect(self.context_preferences_changed)
        self.context_radius.currentIndexChanged.connect(self.context_preferences_changed)
        context_row.addWidget(self.auto_context)
        context_row.addWidget(self.context_radius)
        self.context_btn = button(self.t("重新拉取", "Refresh context"), self.refresh_context)
        context_row.addWidget(self.context_btn)
        context_row.addStretch()
        sl.addLayout(context_row)
        passage_row = QHBoxLayout()
        self.passage_buttons = []
        for index in range(3):
            action = button('', lambda checked=False, i=index: self.edit_passage(i))
            passage_row.addWidget(action, 1)
            self.passage_buttons.append(action)
        self.update_passage_buttons()
        sl.addLayout(passage_row)
        template_row = QGridLayout()
        template_row.addWidget(QLabel(self.t("提示词模板", "Prompt template")), 0, 0)
        self.templates = QComboBox()
        self.templates.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.templates.setMinimumContentsLength(10)
        self.templates.addItems([x["name"] for x in self.config["templates"]])
        self.templates.setCurrentIndex(min(self.config.get("template_index", 0), self.templates.count() - 1))
        self.templates.currentIndexChanged.connect(self.load_template)
        template_row.addWidget(self.templates, 0, 1)
        template_row.setColumnStretch(1, 1)
        template_row.addWidget(button(self.t("保存模板", "Save template"), self.save_template), 0, 2)
        template_row.addWidget(button(self.t("另存模板", "Save as"), self.save_template_as), 0, 3)
        template_row.addWidget(QLabel(self.t("回答语言", "Reply language")), 1, 0)
        self.reply_lang = QComboBox()
        self.reply_lang.setEditable(True)
        self.reply_lang.addItems(["中文", "English", "Follow original language", "日本語", "Deutsch", "Français"])
        self.reply_lang.setEditText(self.config.get("reply_language", "中文"))
        template_row.addWidget(self.reply_lang, 1, 1, 1, 3)
        sl.addLayout(template_row)
        self.prompt = QPlainTextEdit()
        self.prompt.setAccessibleName(self.t("提示词", "Prompt"))
        self.prompt.setMaximumHeight(115)
        self.prompt.setMinimumHeight(65)
        sl.addWidget(self.prompt)
        self.loaded_template = -1
        self.load_template()
        sl.addWidget(note(self.t("前后文仅供理解，AI 只修改问询原文。LyX 菜单读取结构化选区并排除备注、脚注等；发送预览可核对全部内容。", "Context is reference only; AI revises the target. LyX menu imports structured body text, excluding notes/footnotes. Preview the entire request before sending.")))
        self.source_scroll = QScrollArea()
        self.source_scroll.setWidgetResizable(True)
        self.source_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.source_scroll.setMinimumSize(0, 80)
        self.source_scroll.setWidget(source)
        panes.addWidget(self.source_scroll)
        output = QWidget()
        ol = QVBoxLayout(output)
        ol.setContentsMargins(0, 0, 0, 0)
        self.output_tabs = QTabWidget()
        self.output_tabs.setUsesScrollButtons(True)
        self.output_tabs.setMinimumHeight(170)
        self.answer = QPlainTextEdit()
        self.answer.setReadOnly(True)
        self.answer.setAccessibleName(self.t("AI 回答", "AI answer"))
        self.reasoning = QPlainTextEdit()
        self.reasoning.setReadOnly(True)
        self.reasoning.setPlaceholderText(self.t("仅显示 API 实际返回的思考内容或摘要。", "Only reasoning text or summaries actually returned by the API are displayed."))
        self.conversation = QPlainTextEdit()
        self.conversation.setReadOnly(True)
        self.output_tabs.addTab(self.answer, self.t("回答", "Answer"))
        if not hasattr(self, 'rich_preview'):
            self.rich_preview = RichPreview()
            # Prepare the native browser before the top-level window is shown.
            # Rendering remains deferred; tab changes cannot recreate the HWND.
            self.rich_preview.prepare()
        self.output_tabs.addTab(self.rich_preview, self.t("阅读预览 · Markdown / 公式", "Preview · Markdown / Math"))
        replace_page = QWidget()
        replace_layout = QVBoxLayout(replace_page)
        replace_layout.addWidget(note(self.t("将此处内容应用到 LyX 当前选区或光标，支持公式、定理布局及 LaTeX 源码。应用按钮位于窗口底部。", "Apply this passage at the current LyX selection or caret. Supports equations, theorem layouts and LaTeX source. Apply is in the bottom toolbar.")))
        self.replacement = QPlainTextEdit()
        self.replacement.setPlaceholderText(self.t("从 [REVISED]…[/REVISED] 自动提取，或手动编辑待替换正文。", "Extracted from [REVISED]…[/REVISED], or edit the replacement here."))
        replace_layout.addWidget(self.replacement)
        replace_actions = QHBoxLayout()
        replace_actions.addWidget(button(self.t("从回答选区提取", "Use selected answer text"), self.stage_selected))
        replace_actions.addWidget(button(self.t("预览待替换正文", "Preview replacement"), self.preview_replacement))
        replace_layout.addLayout(replace_actions)
        self.output_tabs.addTab(replace_page, self.t("待替换正文", "Replacement"))
        self.output_tabs.addTab(self.reasoning, self.t("思考 / 摘要", "Reasoning / summary"))
        self.output_tabs.addTab(self.conversation, self.t("本次对话", "Conversation"))
        ol.addWidget(self.output_tabs)
        self.followup = QLineEdit()
        self.followup.setPlaceholderText(self.t("继续追问（对话自动保存在本机）", "Ask a follow-up (conversation saved locally)"))
        self.followup.setAccessibleName(self.t("追问内容", "Follow-up question"))
        follow = QHBoxLayout()
        follow.addWidget(self.followup, 1)
        self.follow_btn = button(self.t("追问", "Follow up"), self.send_followup)
        follow.addWidget(self.follow_btn)
        ol.addLayout(follow)
        self.output_scroll = QScrollArea()
        self.output_scroll.setWidgetResizable(True)
        self.output_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.output_scroll.setMinimumSize(0, 100)
        self.output_scroll.setWidget(output)
        panes.addWidget(self.output_scroll)
        ui = self.config.get('ui_state', {}).get('main', {})
        panes.setSizes(ui.get('splitter', [360, 400]))
        self.output_tabs.setCurrentIndex(min(ui.get('output_tab', 0), self.output_tabs.count()-1))
        actions = self.action_grid = QGridLayout()
        self.send_btn = button(self.t("发送问询", "Send request"), self.send, True)
        self.cancel_btn = button(self.t("取消请求", "Cancel request"), self.cancel)
        self.cancel_btn.setEnabled(False)
        self.preview_btn = button(self.t("预览发送内容", "Preview request"), self.preview)
        self.copy_btn = button(self.t("复制回答", "Copy answer"), self.copy_answer)
        self.history_btn = button(self.t('问答历史…', 'History…'), self.open_history)
        self.apply_btn = button(self.t("应用到 LyX 当前位置", "Apply at LyX position"), self.apply_to_lyx, True)
        self.apply_btn.setToolTip(self.t('将“待替换正文”应用到 LyX 当前选区；无选区时在当前光标插入。', 'Replaces the current LyX selection with the Replacement passage, or inserts at the current caret.'))
        outer.addLayout(actions)
        self._compact_actions = None
        self.status = StatusLine(self.t("就绪。请先配置 API 模型。", "Ready. Configure an API model to begin."))
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        footer = QHBoxLayout()
        footer.addWidget(self.status, 1)
        self.copyright_link = QLabel('<a style="color:#176f83;text-decoration:none" href="https://github.com/leyuwei/LyX-AI">© github/leyuwei</a>')
        self.copyright_link.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse | Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.copyright_link.setAccessibleName('© github/leyuwei')
        self.copyright_link.setToolTip(self.t('打开插件 GitHub 主页', 'Open the plugin homepage on GitHub'))
        self.copyright_link.linkActivated.connect(lambda _: QDesktopServices.openUrl(QUrl('https://github.com/leyuwei/LyX-AI')))
        footer.addWidget(self.copyright_link)
        outer.addLayout(footer)
        self.follow_btn.setEnabled(bool(self.history))
        self._building = False
        for signal in (self.reply_lang.currentTextChanged, self.prompt.textChanged, self.output_tabs.currentChanged, self.panes.splitterMoved):
            signal.connect(self.schedule_preferences)
        self.replacement.textChanged.connect(self.schedule_preferences)
        self.adapt_layout()

    def update_passage_buttons(self):
        if not hasattr(self, 'passage_buttons'):
            return
        names = (self.t('问询原文', 'Target passage'), self.t('前文', 'Before'), self.t('后文', 'After'))
        for action, document, name in zip(self.passage_buttons, (self.selection, self.before, self.after), names):
            size = len(document.toPlainText())
            action.setText(f'{name} · {size}')
            action.setAccessibleName(name)
            action.setToolTip(self.t(f'查看 / 编辑{name}（{size} 字符）', f'View / edit {name.lower()} ({size} characters)'))

    def edit_passage(self, index):
        if self.job or self.bridge_job:
            return
        document = (self.selection, self.before, self.after)[index]
        original = document.toPlainText()
        # The revision catches IPC updates, even when the new target has identical text.
        revision = document.revision()
        dlg = PassageDialog(self.passage_buttons[index].accessibleName(), original, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            if document.revision() != revision:
                self.status.setText(self.t('内容已由 LyX 更新，未覆盖新内容。请重新打开编辑。', 'LyX updated this text. The newer text was kept; reopen to edit.'))
            else:
                document.setPlainText(dlg.editor.toPlainText())
                self.status.setText(self.t('内容已保存，下次发送问询时使用。', 'Text saved for the next request.'))
        dlg.deleteLater()

    def adapt_layout(self):
        compact = self.width() < 1050
        self.tagline.setVisible(self.width() >= 1000)
        self.endpoint_label.setVisible(self.width() >= 1000)
        if compact == self._compact_actions:
            return
        self._compact_actions = compact
        widgets = (self.send_btn, self.cancel_btn, self.preview_btn, self.copy_btn, self.history_btn, self.apply_btn)
        for widget in widgets:
            self.action_grid.removeWidget(widget)
        for col in range(7):
            self.action_grid.setColumnStretch(col, 0)
        if compact:
            for row, group in enumerate(((self.send_btn, self.cancel_btn, self.apply_btn), (self.preview_btn, self.copy_btn, self.history_btn))):
                for col, widget in enumerate(group):
                    self.action_grid.addWidget(widget, row, col)
            self.action_grid.setColumnStretch(2, 1)
        else:
            for col, widget in enumerate(widgets):
                self.action_grid.addWidget(widget, 0, col if col < 5 else 6)
            self.action_grid.setColumnStretch(5, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'action_grid') and not self._building:
            self.adapt_layout()
            self.schedule_preferences()

    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, 'preferences_timer'):
            self.schedule_preferences()

    def schedule_preferences(self, *args):
        if not self._building:
            self.preferences_timer.start()

    def capture_preferences(self):
        self.config.update(reply_language=self.reply_lang.currentText(), template_index=self.templates.currentIndex(),
                           auto_context=self.auto_context.isChecked(), context_radius=self.context_radius.currentData(), active=self.profile.currentData())
        if self.loaded_template >= 0:
            self.config['templates'][self.loaded_template]['prompt'] = self.prompt.toPlainText()
        self.config.setdefault('ui_state', {})['main'] = dict(window_state(self), splitter=self.panes.sizes(), output_tab=self.output_tabs.currentIndex())

    def save_preferences(self):
        self.preferences_timer.stop()
        self.capture_preferences()
        self.persist()
        if self.session and not self.job:
            self.session['replacement'] = self.replacement.toPlainText()
            self.save_session()

    def fill_profiles(self):
        self.profile.clear()
        for p in self.config["profiles"]:
            self.profile.addItem(f'{p["name"]} · {p["model"]}', p["id"])
        choose(self.profile, self.config["active"])

    def active_profile(self):
        return next(p for p in self.config["profiles"] if p["id"] == self.profile.currentData())

    def update_endpoint(self):
        p = self.active_profile()
        self.endpoint_label.setText(PROTOCOLS[p["protocol"]])

    def persist(self, config=None):
        try:
            self.store.save(config or self.config)
            return True
        except Exception as exc:
            QMessageBox.warning(self, "LyX AI", str(exc))
            return False

    def profile_changed(self):
        if self.profile.currentData():
            self.config["active"] = self.profile.currentData()
            self.update_endpoint()
            self.history = []
            self.follow_btn.setEnabled(False)
            self.conversation.clear()
            self.schedule_preferences()

    def settings(self):
        self.capture_preferences()
        dlg = SettingsDialog(self.config, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and self.persist(dlg.config):
            self.config = dlg.config
            self.profile.blockSignals(True)
            self.fill_profiles()
            self.profile.blockSignals(False)
            self.update_endpoint()
            self.history = []
            self.follow_btn.setEnabled(False)
            self.conversation.clear()
            self.status.setText(self.t("模型配置已保存。", "Model configuration saved."))
        self.config.setdefault('ui_state', {})['settings'] = dlg.config.get('ui_state', {}).get('settings', {})
        self.schedule_preferences()

    def change_language(self):
        if self.job or self.bridge_job:
            self.language.blockSignals(True)
            choose(self.language, self.lang)
            self.language.blockSignals(False)
            return
        replacement = self.replacement.toPlainText()
        followup = self.followup.text()
        self.capture_preferences()
        self.config['auto_context'] = self.auto_context.isChecked()
        self.config['context_radius'] = self.context_radius.currentData()
        self.config["language"] = self.language.currentData()
        template_index = self.templates.currentIndex()
        self.config["templates"][template_index]["prompt"] = self.prompt.toPlainText()
        self.config["template_index"] = template_index
        self.config["reply_language"] = self.reply_lang.currentText()
        if not self.persist():
            return
        self.lang = self.config["language"]
        # Keep the browser's native child and page alive across translation.
        self.rich_preview.setParent(self)
        old = self.takeCentralWidget()
        self.build()
        old.deleteLater()
        self.answer.setPlainText(self.answer_text)
        self.replacement.setPlainText(replacement)
        self.rich_preview.set_text(self.answer_text)
        self.reasoning.setPlainText(self.reasoning_text)
        self.followup.setText(followup)
        self.show_history()

    def load_template(self):
        index = self.templates.currentIndex()
        if index >= 0:
            if getattr(self, 'loaded_template', -1) >= 0:
                self.config['templates'][self.loaded_template]['prompt'] = self.prompt.toPlainText()
            self.loaded_template = index
            self.prompt.setPlainText(self.config["templates"][index]["prompt"])
            self.schedule_preferences()

    def save_template(self):
        self.config["templates"][self.templates.currentIndex()]["prompt"] = self.prompt.toPlainText()
        self.config["template_index"] = self.templates.currentIndex()
        self.config["reply_language"] = self.reply_lang.currentText()
        if self.persist():
            self.status.setText(self.t("提示词模板已保存。", "Prompt template saved."))

    def save_template_as(self):
        name, ok = QInputDialog.getText(self, self.t("另存模板", "Save template as"), self.t("模板名称", "Template name"))
        if ok and name.strip():
            self.config["templates"].append(dict(name=name.strip(), prompt=self.prompt.toPlainText()))
            if self.persist():
                self.templates.addItem(name.strip())
                self.templates.setCurrentIndex(self.templates.count() - 1)

    def initial_messages(self):
        p = self.active_profile()
        selection = self.selection.toPlainText()
        if not selection.strip():
            raise ValueError(self.t("请先选择或粘贴文字。", "Select or paste text first."))
        if not self.prompt.toPlainText().strip():
            raise ValueError(self.t("请填写提示词。", "Enter a prompt."))
        selected_with_context = compose_context(selection, self.before.toPlainText(), self.after.toPlainText())
        user = render_prompt(self.prompt.toPlainText(), selected_with_context, self.reply_lang.currentText())
        user += '\n\n如需给出可直接替换的修改，请将且仅将目标正文放在 [REVISED] 与 [/REVISED] 之间，解释放在标记外。公式使用 $…$ 或 \\[ … \\]；不要重复前后文。\nFor an applicable revision, put ONLY the revised target between [REVISED] and [/REVISED]; keep explanations outside. Use $…$ or \\[ … \\] for equations.'
        return ([{"role": "system", "content": p["system"]}] if p.get("system") else []) + [{"role": "user", "content": user}]

    def preview(self):
        try:
            show_text(self, self.t("发送预览（认证已隐藏）", "Request preview (credentials hidden)"), preview_request(self.active_profile(), self.initial_messages()))
        except Exception as exc:
            self.status.setText(str(exc))

    def send(self):
        if self.bridge_job:
            self.status.setText(self.t('正在获取正文，请稍候再发送。', 'Context is loading; send when ready.'))
            return
        try:
            self.run_request(self.initial_messages())
        except Exception as exc:
            self.status.setText(str(exc))

    def send_followup(self):
        if self.history and self.followup.text().strip():
            self.run_request(self.history + [{"role": "user", "content": self.followup.text().strip()}], followup=True)

    def run_request(self, messages, followup=False):
        if self.job or self.bridge_job:
            return
        p = copy.deepcopy(self.active_profile())
        try:
            build_request(p, messages)
        except Exception as exc:
            self.status.setText(str(exc))
            return
        self.save_preferences()
        if not followup or not self.session:
            self.session = self.archive.new(
                target=self.selection.toPlainText(), before=self.before.toPlainText(),
                after=self.after.toPlainText(), prompt=self.prompt.toPlainText(),
                reply_language=self.reply_lang.currentText(),
                profile={key: p.get(key, '') for key in ('id', 'name', 'model', 'provider')})
            self.history = []
        self.session['turns'].append(dict(
            time=timestamp(), question=messages[-1]['content'], answer='', reasoning='',
            status='pending', profile={key: p.get(key, '') for key in ('id', 'name', 'model', 'provider')}))
        self.session['messages'] = copy.deepcopy(self.history if followup else [])
        self.session['replacement'] = ''
        if not self.save_session():
            return
        self.config['last_session'] = self.session['id']
        self.schedule_preferences()
        self.pending = messages
        self.show_history()
        self.display_timer.stop()
        self.display_pending = [[], []]
        self.answer_text = self.reasoning_text = ""
        self.answer.clear()
        self.reasoning.clear()
        self.replacement.clear()
        self.rich_preview.set_text('')
        self.output_tabs.setCurrentIndex(0)
        self.busy(True)
        self.status.setText(self.t("正在问询…", "Requesting…"))
        self.job = NetworkJob(p, self)
        self.job.delta.connect(self.receive)
        self.job.completed.connect(self.finished)
        self.job.failed.connect(self.failed)
        self.job.start(messages)

    def busy(self, busy):
        for widget in (self.send_btn, self.settings_btn, self.profile, self.language, *self.passage_buttons, self.prompt, self.templates, self.reply_lang, self.history_btn):
            widget.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        self.follow_btn.setEnabled(not busy and bool(self.history))
        self.apply_btn.setEnabled(not busy)

    def receive(self, text, reasoning):
        self.display_pending[0].append(text)
        self.display_pending[1].append(reasoning)
        if not self.display_timer.isActive():
            self.display_timer.start()

    def flush_display(self):
        self.display_timer.stop()
        text, reasoning = ("".join(parts) for parts in self.display_pending)
        self.display_pending = [[], []]
        self.answer_text += text
        self.reasoning_text += reasoning
        self.rich_preview.set_text(self.answer_text)
        for widget, delta in ((self.answer, text), (self.reasoning, reasoning)):
            if delta:
                cursor = widget.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.insertText(delta)
                widget.setTextCursor(cursor)

    def finished(self, result):
        self.flush_display()
        self.answer_text = result['text']
        self.reasoning_text = result.get('reasoning', self.reasoning_text)
        self.answer.setPlainText(self.answer_text)
        self.reasoning.setPlainText(self.reasoning_text)
        self.history = self.pending + [{"role": "assistant", "content": result["text"]}]
        self.pending = None
        self.followup.clear()
        self.job = None
        self.busy(False)
        finish = result.get("finish")
        truncated = finish in ("length", "max_tokens", "incomplete", "content_filter")
        status = self.t("回答未完整结束，请检查输出上限或过滤状态。", "Answer may be incomplete; check token limit or filtering.") if truncated else self.t("完成。", "Complete.")
        self.status.setText(status + " " + json.dumps(result.get("usage", {}), ensure_ascii=False))
        self.rich_preview.set_text(result['text'])
        self.replacement.setPlainText('' if truncated else revised_text(result['text']))
        if self.session:
            self.session['turns'][-1].update(answer=self.answer_text, reasoning=self.reasoning_text, status='incomplete' if truncated else 'complete', usage=result.get('usage', {}))
            self.session.update(messages=copy.deepcopy(self.history), replacement=self.replacement.toPlainText())
            self.save_session()
        self.show_history()

    def failed(self, error):
        self.flush_display()
        self.job = None
        self.pending = None
        self.busy(False)
        self.status.setText(error + (self.t("（已保留部分输出）", " (partial output retained)") if self.answer_text or self.reasoning_text else ""))
        if self.session:
            self.session['turns'][-1].update(answer=self.answer_text, reasoning=self.reasoning_text, status='cancelled' if 'Cancelled' in error else 'error', error=error)
            self.save_session()
        self.show_history()

    def show_history(self):
        self.conversation.setPlainText(transcript(self.session) if self.session else "\n\n────────────\n\n".join(m["role"].upper() + "\n" + m["content"] for m in self.history))

    def save_session(self):
        try:
            self.archive.save(self.session)
            return True
        except Exception as exc:
            self.status.setText(self.t('本地历史保存失败：', 'Could not save local history: ') + str(exc))
            return False

    def open_history(self):
        if self.job or self.bridge_job:
            return
        self.save_preferences()
        dlg = HistoryDialog(self.archive, self.lang, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.session:
            self.restore_session(dlg.session)
        elif self.session and not self.archive.get(self.session['id']):
            self.session = None
            self.config.pop('last_session', None)
        self.schedule_preferences()

    def restore_session(self, session, restore_profile=True):
        # Never restore a saved native selection/filename as a writeback target.
        self.session = session
        profile_id = (session['turns'][-1].get('profile', session.get('profile', {})) if session['turns'] else session.get('profile', {})).get('id')
        if restore_profile and self.profile.findData(profile_id) >= 0:
            self.profile.blockSignals(True)
            choose(self.profile, profile_id)
            self.profile.blockSignals(False)
            self.config['active'] = profile_id
            self.update_endpoint()
        self.history = copy.deepcopy(session.get('messages', []))
        self.selection.setPlainText(session.get('target', ''))
        self.before.setPlainText(session.get('before', ''))
        self.after.setPlainText(session.get('after', ''))
        turn = session['turns'][-1] if session['turns'] else {}
        self.answer_text, self.reasoning_text = turn.get('answer', ''), turn.get('reasoning', '')
        self.answer.setPlainText(self.answer_text)
        self.reasoning.setPlainText(self.reasoning_text)
        self.replacement.setPlainText(session.get('replacement', ''))
        self.rich_preview.set_text(self.answer_text)
        self.show_history()
        self.follow_btn.setEnabled(bool(self.history))
        self.config['last_session'] = session['id']
        self.status.setText(self.t('已载入本地历史，可查看或继续追问。', 'Local history loaded; review or continue the conversation.'))
        self.schedule_preferences()

    def cancel(self):
        if self.job:
            self.job.stop()

    def copy_answer(self):
        if self.answer_text:
            QApplication.clipboard().setText(self.answer_text)
            self.status.setText(self.t("回答已复制。", "Answer copied."))

    def accept_message(self, message):
        kind = message["kind"]
        if (self.job or self.bridge_job) and kind in ("selection", "before", "after"):
            self.status.setText(self.t("正在处理操作，未更改选区。请先取消或等待完成，再重新加入。", "An operation is running. Text was not changed; cancel or wait, then add the selection again."))
        elif kind == "selection":
            if self.bridge_job:
                self.status.setText(self.t('正在与 LyX 通信，请完成后重新问询。', 'LyX operation in progress; retry when complete.'))
                return
            self.save_preferences()
            self.lyx_payload = message.copy() if message.get('native') else None
            self.session = None
            self.display_timer.stop()
            self.display_pending = [[], []]
            self.selection.setPlainText(message["text"])
            self.before.clear()
            self.after.clear()
            self.history = []
            self.follow_btn.setEnabled(False)
            self.answer_text = self.reasoning_text = ""
            self.answer.clear()
            self.reasoning.clear()
            self.conversation.clear()
            self.replacement.clear()
            self.rich_preview.set_text('')
            self.status.setText(self.t("问询原文已更新，前后文已清空。", "Target updated; previous context cleared."))
            if self.lyx_payload:
                self.refresh_context()
        elif kind in ("before", "after"):
            editor = self.before if kind == "before" else self.after
            existing = editor.toPlainText().strip()
            text = message["text"].strip()
            editor.setPlainText(existing + "\n\n" + text if existing else text)
            self.history = []
            self.follow_btn.setEnabled(False)
            self.conversation.clear()
            self.status.setText(self.t("已补充上下文，问询原文未变；重新发送即可使用新上下文。", "Context added; target unchanged. Send a new request to use this context."))
        if message.get("excluded") and not self.job:
            self.status.setText(self.status.full_text + self.t(f" 已排除 {message['excluded']} 个非正文对象。", f" Excluded {message['excluded']} non-body objects."))
        if self.isMinimized() or not self.isVisible():
            self.showNormal()
        self.raise_()
        self.activateWindow()
        if kind == "configure":
            QTimer.singleShot(0, self.settings)

    def closeEvent(self, event):
        if self.bridge_job:
            self.status.setText(self.t('正在与 LyX 通信，请稍后关闭。', 'Waiting for LyX operation to finish.'))
            event.ignore()
            return
        self.cancel()
        self.save_preferences()
        event.accept()

    def run_bridge(self, fn, success):
        if self.bridge_job or self.job:
            return
        job = BridgeJob(fn, self)
        self.bridge_job = job
        self.context_btn.setEnabled(False)
        self.apply_btn.setEnabled(False)
        self.language.setEnabled(False)
        job.result.connect(success)
        job.error.connect(lambda text: self.status.setText(text))
        def done():
            self.bridge_job = None
            self.context_btn.setEnabled(True)
            self.apply_btn.setEnabled(True)
            self.language.setEnabled(True)
            job.deleteLater()
        job.finished.connect(done)
        job.start()

    def refresh_context(self):
        if not self.lyx_payload:
            self.status.setText(self.t('请从 LyX 正文右键启动，才能读取当前文档。', 'Open from the LyX context menu to read the current buffer.'))
            return
        from .bridge import load_context
        payload = self.lyx_payload.copy()
        radius = self.context_radius.currentData()
        enabled = self.auto_context.isChecked()
        self.config.update(auto_context=enabled, context_radius=radius)
        self.status.setText(self.t('正在读取 LyX 当前正文…', 'Reading live LyX body context…'))
        def loaded(result):
            self.lyx_payload.update(filename=result['filename'])
            if enabled:
                self.before.setPlainText(result['before'])
                self.after.setPlainText(result['after'])
            self.status.setText(self.t(f"正文已读取，已排除 {result['context_excluded']} 个非正文对象。", f"Body loaded; excluded {result['context_excluded']} non-body objects."))
        self.run_bridge(lambda: load_context(payload, radius=radius, include_context=enabled), loaded)

    def context_preferences_changed(self):
        self.config.update(auto_context=self.auto_context.isChecked(), context_radius=self.context_radius.currentData())
        self.schedule_preferences()

    def stage_selected(self):
        selected = self.answer.textCursor().selectedText().replace('\u2029', '\n')
        if selected.strip():
            self.replacement.setPlainText(selected)
        else:
            self.status.setText(self.t('请先在回答源码中选中待替换的正文。', 'Select the revised passage in the answer source first.'))

    def preview_replacement(self):
        self.rich_preview.set_text(self.replacement.toPlainText())
        self.output_tabs.setCurrentWidget(self.rich_preview)

    def apply_to_lyx(self):
        if not self.lyx_payload or not self.lyx_payload.get('filename'):
            self.status.setText(self.t('未建立 LyX 目标，请从原文右键重新问询。', 'No verified LyX target; open from its context menu again.'))
            return
        from .bridge import apply_replacement
        payload, text = self.lyx_payload.copy(), self.replacement.toPlainText()
        self.status.setText(self.t('正在应用到 LyX 当前选区或光标…', 'Applying at the current LyX selection or caret…'))
        def applied(result):
            action = self.t('已插入当前光标位置。', 'Inserted at the current caret.') if result['mode'] == 'insert' else self.t('已替换当前选区。', 'Replaced the current selection.')
            self.status.setText(action + self.t(' 可在 LyX 一次撤销（macOS：⌘Z；Windows：Ctrl+Z），也可选择其他位置继续应用。', ' Undo once in LyX (macOS: ⌘Z; Windows: Ctrl+Z), or select another position to apply again.'))
        self.run_bridge(lambda: apply_replacement(payload, text), applied)
