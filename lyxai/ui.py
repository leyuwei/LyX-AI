"""Desktop assistant and its separate model-configuration dialog."""
from __future__ import annotations

import copy
import json

from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QFont, QTextCursor, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter,
    QTabWidget, QVBoxLayout, QWidget,
)

from .core import (PRESETS, PROTOCOLS, Store, build_request, json_object, new_profile,
                   preview_request, render_prompt)
from .network import NetworkJob
from .selection import compose_context
from .preview import ASSETS, RichPreview
from .replacement import revised_text


STYLE = """
QWidget { font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 10pt; color: #22364a; }
QMainWindow, QDialog { background: #f2f6fa; }
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
QPushButton:disabled { color: #8c9ca9; background: #e8eef3; border-color: #dbe4eb; }
QPushButton[primary="true"] { background: #176f83; color: white; border-color: #176f83; }
QPushButton[primary="true"]:hover { background: #125b70; }
QPushButton[primary="true"]:disabled { background: #a7bcc6; border-color: #a7bcc6; }
QTabWidget::pane { border: 1px solid #d5e1e9; background: #fff; border-radius: 8px; }
QTabBar::tab { padding: 9px 16px; background: transparent; color: #607589; border-bottom: 3px solid transparent; }
QTabBar::tab:selected { color: #14697b; background: #fff; border-bottom: 3px solid #24a3a8; }
QTabBar::tab:hover { color: #14697b; background: #e7f1f5; }
QLabel[muted="true"] { color: #62788a; }
QLabel#brand { font-size: 24px; font-weight: 700; color: #174e68; }
QSplitter::handle { background: #e0e9f0; height: 5px; }
QScrollBar:vertical { width: 10px; background: #f2f6fa; }
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
        self.resize(1010, 770)
        outer = QVBoxLayout(self)
        outer.addWidget(note(self.t("每个配置档独立保存接口、模型和参数。中转站可修改地址并选择其实际协议。", "Each profile has its own endpoint, model and parameters. For a relay, select the protocol it actually serves.")))
        split = QSplitter()
        outer.addWidget(split, 1)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        self.list = QListWidget()
        self.list.setAccessibleName(self.t("模型配置档", "Model profiles"))
        ll.addWidget(self.list)
        row = QHBoxLayout()
        for label, fn in ((self.t("新增", "Add"), self.add_profile), (self.t("复制", "Duplicate"), self.duplicate), (self.t("删除", "Delete"), self.remove_profile)):
            row.addWidget(button(label, fn))
        ll.addLayout(row)
        split.addWidget(left)
        self.tabs = QTabWidget()
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
        self.refresh_list(0)

    def t(self, zh, en):
        return zh if self.lang == "zh" else en

    def form_tab(self, title):
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(11)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
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
        super().done(result)


class MainWindow(QMainWindow):
    def __init__(self, selection="", store=None):
        super().__init__()
        self.store = store or Store()
        self.config = self.store.load()
        self.lang = self.config.get("language", "zh")
        self.selection_text = selection
        self.before_text = ""
        self.after_text = ""
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
        self.build()

    def t(self, zh, en):
        return zh if self.lang == "zh" else en

    def build(self):
        self.setWindowTitle("LyX AI · " + self.t("写作助手", "Writing Assistant"))
        self.setWindowIcon(QIcon(str(ASSETS / 'logo.svg')))
        self.resize(1160, 930)
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(20, 16, 20, 16)
        top = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QIcon(str(ASSETS / 'logo.svg')).pixmap(44, 44))
        top.addWidget(logo)
        title = QLabel("LyX AI")
        title.setObjectName('brand')
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.DemiBold))
        top.addWidget(title)
        top.addWidget(note(self.t("选区问询与写作建议", "Selection review & writing advice")))
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
        self.profile.setAccessibleName(self.t("当前模型配置档", "Active model profile"))
        self.fill_profiles()
        self.profile.currentIndexChanged.connect(self.profile_changed)
        models.addWidget(self.profile, 1)
        self.endpoint_label = note("")
        models.addWidget(self.endpoint_label)
        outer.addLayout(models)
        self.update_endpoint()
        panes = QSplitter(Qt.Orientation.Vertical)
        outer.addWidget(panes, 1)
        source = QWidget()
        sl = QVBoxLayout(source)
        sl.setContentsMargins(0, 3, 0, 0)
        context_row = QHBoxLayout()
        self.auto_context = QCheckBox(self.t("自动获取正文前后文", "Automatic body context"))
        self.auto_context.setChecked(self.config.get('auto_context', True))
        self.context_radius = combo([(self.t(f"前后各 {n} 字符", f"{n} characters each side"), n) for n in (600, 1800, 4000, 8000)])
        choose(self.context_radius, self.config.get('context_radius', 1800))
        self.auto_context.toggled.connect(self.context_preferences_changed)
        self.context_radius.currentIndexChanged.connect(self.context_preferences_changed)
        context_row.addWidget(self.auto_context)
        context_row.addWidget(self.context_radius)
        self.context_btn = button(self.t("重新拉取", "Refresh context"), self.refresh_context)
        context_row.addWidget(self.context_btn)
        context_row.addStretch()
        sl.addLayout(context_row)
        self.input_tabs = QTabWidget()
        self.selection = QPlainTextEdit(self.selection_text)
        self.selection.setAccessibleName(self.t("选中文字", "Selected text"))
        self.selection.setPlaceholderText(self.t("在 LyX 中选中文字后右键“问询 AI”，或在这里粘贴。", "Select text in LyX and choose Ask AI, or paste text here."))
        self.before = QPlainTextEdit(self.before_text)
        self.after = QPlainTextEdit(self.after_text)
        for editor, zh, en in ((self.before, "前文", "Context before"), (self.after, "后文", "Context after")):
            editor.setAccessibleName(self.t(zh, en))
            editor.setPlaceholderText(self.t("回到 LyX 框选正文，再右键加入此处。可重复框选，也可编辑；手动粘贴的文字请自行排除备注脚注。", "Select body text in LyX and use its context menu to add it here. Repeat to append more. Manually pasted text must be checked for notes/footnotes."))
        self.input_tabs.addTab(self.selection, self.t("问询原文", "Target passage"))
        self.input_tabs.addTab(self.before, self.t("前文（可选）", "Before (optional)"))
        self.input_tabs.addTab(self.after, self.t("后文（可选）", "After (optional)"))
        sl.addWidget(self.input_tabs)
        template_row = QHBoxLayout()
        template_row.addWidget(QLabel(self.t("提示词模板", "Prompt template")))
        self.templates = QComboBox()
        self.templates.addItems([x["name"] for x in self.config["templates"]])
        self.templates.setCurrentIndex(min(self.config.get("template_index", 0), self.templates.count() - 1))
        self.templates.currentIndexChanged.connect(self.load_template)
        template_row.addWidget(self.templates, 1)
        template_row.addWidget(button(self.t("保存模板", "Save template"), self.save_template))
        template_row.addWidget(button(self.t("另存模板", "Save as"), self.save_template_as))
        template_row.addWidget(QLabel(self.t("回答语言", "Reply language")))
        self.reply_lang = QComboBox()
        self.reply_lang.setEditable(True)
        self.reply_lang.addItems(["中文", "English", "Follow original language", "日本語", "Deutsch", "Français"])
        self.reply_lang.setEditText(self.config.get("reply_language", "中文"))
        template_row.addWidget(self.reply_lang)
        sl.addLayout(template_row)
        self.prompt = QPlainTextEdit()
        self.prompt.setAccessibleName(self.t("提示词", "Prompt"))
        self.prompt.setMaximumHeight(115)
        sl.addWidget(self.prompt)
        self.load_template()
        sl.addWidget(note(self.t("前后文仅供理解，AI 只修改问询原文。LyX 菜单读取结构化选区并排除备注、脚注等；发送预览可核对全部内容。", "Context is reference only; AI revises the target. LyX menu imports structured body text, excluding notes/footnotes. Preview the entire request before sending.")))
        panes.addWidget(source)
        output = QWidget()
        ol = QVBoxLayout(output)
        ol.setContentsMargins(0, 0, 0, 0)
        self.output_tabs = QTabWidget()
        self.answer = QPlainTextEdit()
        self.answer.setReadOnly(True)
        self.answer.setAccessibleName(self.t("AI 回答", "AI answer"))
        self.reasoning = QPlainTextEdit()
        self.reasoning.setReadOnly(True)
        self.reasoning.setPlaceholderText(self.t("仅显示 API 实际返回的思考内容或摘要。", "Only reasoning text or summaries actually returned by the API are displayed."))
        self.conversation = QPlainTextEdit()
        self.conversation.setReadOnly(True)
        self.output_tabs.addTab(self.answer, self.t("回答", "Answer"))
        self.rich_preview = RichPreview()
        self.output_tabs.addTab(self.rich_preview, self.t("阅读预览 · Markdown / 公式", "Preview · Markdown / Math"))
        replace_page = QWidget()
        replace_layout = QVBoxLayout(replace_page)
        replace_layout.addWidget(note(self.t("仅此处正文会替换 LyX 选区。支持行内、Displayed 和 align/aligned 等多行公式；应用按钮位于窗口底部。", "Only this passage replaces the LyX selection. Inline, displayed and multiline equations are supported. Apply is in the bottom toolbar.")))
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
        self.followup.setPlaceholderText(self.t("继续追问（仅本窗口内保留上下文）", "Ask a follow-up (conversation kept only in this window)"))
        self.followup.setAccessibleName(self.t("追问内容", "Follow-up question"))
        follow = QHBoxLayout()
        follow.addWidget(self.followup, 1)
        self.follow_btn = button(self.t("追问", "Follow up"), self.send_followup)
        follow.addWidget(self.follow_btn)
        ol.addLayout(follow)
        panes.addWidget(output)
        panes.setSizes([390, 340])
        actions = QHBoxLayout()
        self.send_btn = button(self.t("发送问询", "Send request"), self.send, True)
        actions.addWidget(self.send_btn)
        self.cancel_btn = button(self.t("取消请求", "Cancel request"), self.cancel)
        self.cancel_btn.setEnabled(False)
        actions.addWidget(self.cancel_btn)
        actions.addWidget(button(self.t("预览发送内容", "Preview request"), self.preview))
        actions.addWidget(button(self.t("复制回答", "Copy answer"), self.copy_answer))
        actions.addStretch()
        self.apply_btn = button(self.t("应用到 LyX 原选区", "Apply to LyX selection"), self.apply_to_lyx, True)
        self.apply_btn.setToolTip(self.t('应用“待替换正文”中的修改稿，不包含回答解释。', 'Applies the editable Replacement passage, excluding explanations.'))
        actions.addWidget(self.apply_btn)
        outer.addLayout(actions)
        self.status = note(self.t("就绪。请先配置 API 模型。", "Ready. Configure an API model to begin."))
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self.status)
        self.follow_btn.setEnabled(bool(self.history))

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

    def settings(self):
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

    def change_language(self):
        if self.job or self.bridge_job:
            self.language.blockSignals(True)
            choose(self.language, self.lang)
            self.language.blockSignals(False)
            return
        replacement = self.replacement.toPlainText()
        self.config['auto_context'] = self.auto_context.isChecked()
        self.config['context_radius'] = self.context_radius.currentData()
        self.config["language"] = self.language.currentData()
        self.selection_text = self.selection.toPlainText()
        self.before_text = self.before.toPlainText()
        self.after_text = self.after.toPlainText()
        template_index = self.templates.currentIndex()
        self.config["templates"][template_index]["prompt"] = self.prompt.toPlainText()
        self.config["template_index"] = template_index
        self.config["reply_language"] = self.reply_lang.currentText()
        if not self.persist():
            return
        self.lang = self.config["language"]
        old = self.takeCentralWidget()
        self.build()
        old.deleteLater()
        self.answer.setPlainText(self.answer_text)
        self.replacement.setPlainText(replacement)
        self.rich_preview.set_text(self.answer_text)
        self.reasoning.setPlainText(self.reasoning_text)
        self.show_history()

    def load_template(self):
        index = self.templates.currentIndex()
        if index >= 0:
            self.prompt.setPlainText(self.config["templates"][index]["prompt"])

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
            self.run_request(self.history + [{"role": "user", "content": self.followup.text().strip()}])

    def run_request(self, messages):
        if self.job or self.bridge_job:
            return
        p = copy.deepcopy(self.active_profile())
        try:
            build_request(p, messages)
        except Exception as exc:
            self.status.setText(str(exc))
            return
        self.pending = messages
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
        for widget in (self.send_btn, self.settings_btn, self.profile, self.language, self.selection, self.before, self.after, self.prompt, self.templates, self.reply_lang):
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
        self.history = self.pending + [{"role": "assistant", "content": result["text"]}]
        self.pending = None
        self.followup.clear()
        self.job = None
        self.busy(False)
        finish = result.get("finish")
        truncated = finish in ("length", "max_tokens", "incomplete", "content_filter")
        status = self.t("回答未完整结束，请检查输出上限或过滤状态。", "Answer may be incomplete; check token limit or filtering.") if truncated else self.t("完成。", "Complete.")
        self.status.setText(status + " " + json.dumps(result.get("usage", {}), ensure_ascii=False))
        self.show_history()
        self.rich_preview.set_text(result['text'])
        self.replacement.setPlainText('' if truncated else revised_text(result['text']))

    def failed(self, error):
        self.flush_display()
        self.job = None
        self.pending = None
        self.busy(False)
        self.status.setText(error + (self.t("（已保留部分输出）", " (partial output retained)") if self.answer_text or self.reasoning_text else ""))

    def show_history(self):
        self.conversation.setPlainText("\n\n────────────\n\n".join(m["role"].upper() + "\n" + m["content"] for m in self.history))

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
            self.lyx_payload = message.copy() if message.get('native') else None
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
            self.input_tabs.setCurrentIndex(0)
            self.status.setText(self.t("问询原文已更新，前后文已清空。", "Target updated; previous context cleared."))
            if self.lyx_payload:
                self.refresh_context()
        elif kind in ("before", "after"):
            editor = self.before if kind == "before" else self.after
            existing = editor.toPlainText().strip()
            text = message["text"].strip()
            editor.setPlainText(existing + "\n\n" + text if existing else text)
            self.input_tabs.setCurrentIndex(1 if kind == "before" else 2)
            self.history = []
            self.follow_btn.setEnabled(False)
            self.conversation.clear()
            self.status.setText(self.t("已补充上下文，问询原文未变；重新发送即可使用新上下文。", "Context added; target unchanged. Send a new request to use this context."))
        if message.get("excluded") and not self.job:
            self.status.setText(self.status.text() + self.t(f" 已排除 {message['excluded']} 个非正文对象。", f" Excluded {message['excluded']} non-body objects."))
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
            self.lyx_payload.update(filename=result['filename'], document_hash=result['document_hash'])
            if enabled:
                self.before.setPlainText(result['before'])
                self.after.setPlainText(result['after'])
            self.status.setText(self.t(f"正文已读取，已排除 {result['context_excluded']} 个非正文对象。", f"Body loaded; excluded {result['context_excluded']} non-body objects."))
        self.run_bridge(lambda: load_context(payload, radius=radius, include_context=enabled), loaded)

    def context_preferences_changed(self):
        self.config.update(auto_context=self.auto_context.isChecked(), context_radius=self.context_radius.currentData())
        self.persist()

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
        if self.selection.toPlainText() != self.lyx_payload['text']:
            self.status.setText(self.t('助手中的原文被编辑过，请重新从 LyX 问询后应用。', 'Target was edited in the assistant; capture it again from LyX.'))
            return
        from .bridge import apply_replacement
        payload, text = self.lyx_payload.copy(), self.replacement.toPlainText()
        self.status.setText(self.t('正在核对原选区并应用…', 'Verifying selection and applying…'))
        def applied(result):
            self.lyx_payload = None
            self.status.setText(self.t('已应用到 LyX。可在 LyX 撤销（macOS：⌘Z；Windows：Ctrl+Z）；再次修改请重新框选问询。', 'Applied to LyX. Undo in LyX (macOS: ⌘Z; Windows: Ctrl+Z); capture a new selection for further edits.'))
        self.run_bridge(lambda: apply_replacement(payload, text), applied)
