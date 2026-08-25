# -*- coding: utf-8 -*-
"""站点管理页：统一管理部署 API 的中转/自建站点（baseUrl + apiKey）。"""

from PyQt5 import QtCore, QtWidgets


class SiteDialog(QtWidgets.QDialog):
    """添加/编辑站点的表单对话框。"""

    def __init__(self, parent=None, site=None):
        super().__init__(parent)
        self.setWindowTitle("编辑站点" if site else "添加站点")
        self.resize(480, 200)
        form = QtWidgets.QFormLayout(self)
        self.ed_name = QtWidgets.QLineEdit()
        self.ed_name.setPlaceholderText("如 my-relay")
        self.ed_url = QtWidgets.QLineEdit()
        self.ed_url.setPlaceholderText("https://api.example.com")
        self.ed_key = QtWidgets.QLineEdit()
        self.ed_key.setPlaceholderText("sk-...")
        self.ed_note = QtWidgets.QLineEdit()
        self.ed_note.setPlaceholderText("备注（可选）")
        form.addRow("名称:", self.ed_name)
        form.addRow("Base URL:", self.ed_url)
        form.addRow("API Key:", self.ed_key)
        form.addRow("备注:", self.ed_note)

        btns = QtWidgets.QHBoxLayout()
        btn_ok = QtWidgets.QPushButton("确定")
        btn_ok.setObjectName("accentBtn")
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok.clicked.connect(self._accept)
        btns.addStretch(1)
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        form.addRow(btns)

        if site:
            self.ed_name.setText(site.get("name", ""))
            self.ed_url.setText(site.get("baseUrl", ""))
            self.ed_key.setText(site.get("apiKey", ""))
            self.ed_note.setText(site.get("note", ""))

    def _accept(self):
        if not self.ed_name.text().strip() or not self.ed_url.text().strip():
            QtWidgets.QMessageBox.warning(self, "提示", "名称和 Base URL 不能为空。")
            return
        self.accept()

    def result_site(self):
        return {
            "name": self.ed_name.text().strip(),
            "baseUrl": self.ed_url.text().strip(),
            "apiKey": self.ed_key.text().strip(),
            "note": self.ed_note.text().strip(),
        }


class SitesTab(QtWidgets.QWidget):
    """站点列表 + 增删改 + 并发测速。数据存 api-switcher.json 的 sites 字段。"""

    def __init__(self, mainwin=None, parent=None):
        super().__init__(parent)
        self.mw = mainwin
        self.setObjectName("sitesTab")
        self._workers = []
        self._statuses = {}  # {索引: 状态文本}，仅内存，不落盘

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        bar = QtWidgets.QHBoxLayout()
        btn_add = QtWidgets.QPushButton("➕ 添加站点")
        btn_add.setObjectName("accentBtn")
        btn_add.clicked.connect(self._on_add)
        btn_edit = QtWidgets.QPushButton("✏️ 编辑")
        btn_edit.clicked.connect(self._on_edit)
        btn_del = QtWidgets.QPushButton("🗑 删除")
        btn_del.setObjectName("dangerBtn")
        btn_del.clicked.connect(self._on_delete)
        btn_test = QtWidgets.QPushButton("⚡ 测试全部连通性")
        btn_test.setObjectName("ghostBtn")
        btn_test.clicked.connect(self._on_test_all)
        for b in (btn_add, btn_edit, btn_del, btn_test):
            bar.addWidget(b)
        bar.addStretch(1)
        root.addLayout(bar)

        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["名称", "Base URL", "API Key", "备注", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(lambda *_: self._on_edit())
        root.addWidget(self.table, 1)

        hint = QtWidgets.QLabel(
            "提示：在「供应商与模型配置」页点击 Base URL 行的 🌐 按钮，可直接用站点信息填充供应商。")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.reload()

    # ---- 数据 ----
    def _sites(self):
        return self.mw.app_config.setdefault("sites", [])

    def reload(self):
        sites = self._sites()
        self.table.setRowCount(len(sites))
        for r, s in enumerate(sites):
            key = s.get("apiKey", "")
            masked = (key[:6] + "..." + key[-4:]) if len(key) > 12 else ("•" * len(key) if key else "")
            for c, val in enumerate((s.get("name", ""), s.get("baseUrl", ""), masked,
                                     s.get("note", ""), self._statuses.get(r, ""))):
                self.table.setItem(r, c, QtWidgets.QTableWidgetItem(str(val)))

    def _save(self):
        from app import _save_app_config
        _save_app_config(self.mw.app_config)

    # ---- 操作 ----
    def _selected_row(self):
        r = self.table.currentRow()
        return r if 0 <= r < len(self._sites()) else -1

    def _on_add(self):
        dlg = SiteDialog(self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self._sites().append(dlg.result_site())
            self._save()
            self.reload()

    def _on_edit(self):
        r = self._selected_row()
        if r < 0:
            return
        dlg = SiteDialog(self, site=self._sites()[r])
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self._sites()[r] = dlg.result_site()
            self._save()
            self.reload()

    def _on_delete(self):
        r = self._selected_row()
        if r < 0:
            return
        name = self._sites()[r].get("name", "")
        ret = QtWidgets.QMessageBox.question(
            self, "确认删除", f"确定删除站点「{name}」吗？（不影响已创建的供应商）",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No)
        if ret != QtWidgets.QMessageBox.Yes:
            return
        del self._sites()[r]
        self._statuses.clear()
        self._save()
        self.reload()

    def _on_test_all(self):
        from app import TestEndpointWorker
        sites = self._sites()
        if not sites:
            return
        self._workers.clear()
        self._statuses.clear()
        for i, s in enumerate(sites):
            url = s.get("baseUrl", "").strip()
            if not url:
                self._statuses[i] = "Base URL 为空"
                continue
            w = TestEndpointWorker(url, s.get("apiKey", ""), name=str(i), parent=self)
            w.result_ready.connect(lambda ok, lat, msg, payload, i=i: self._on_tested(i, ok, lat))
            self._workers.append(w)
            self._statuses[i] = "测试中..."
        self.reload()
        for w in self._workers:
            w.start()

    def _on_tested(self, idx, ok, latency_ms, *args):
        self._statuses[idx] = f"🟢 {latency_ms}ms" if ok else "🔴 失败"
        self.reload()

    def fill_provider_from_site(self):
        """弹出站点选择菜单，返回选中的 site dict 或 None（供供应商页调用）。"""
        menu = QtWidgets.QMenu(self)
        for s in self._sites():
            act = menu.addAction(f"{s['name']}  ({s.get('baseUrl', '')})")
            act.setData(s.get("name"))
        act = menu.exec_(self.mw.cursor().pos())
        if act is None:
            return None
        name = act.data()
        for s in self._sites():
            if s["name"] == name:
                return s
        return None
