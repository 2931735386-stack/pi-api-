# -*- coding: utf-8 -*-
"""技能与插件管理页：浏览 ~/.pi/agent 下的 skills / extensions / npm packages。"""

import os
import re
import shutil
from pathlib import Path

from PyQt5 import QtWidgets

AGENT_DIR = Path.home() / ".pi" / "agent"
SKILLS_DIR = AGENT_DIR / "skills"
EXTENSIONS_DIR = AGENT_DIR / "extensions"


def _skill_description(skill_dir: Path) -> str:
    """从 SKILL.md 提取一行描述：优先 frontmatter 的 description，否则首个标题。"""
    md = skill_dir / "SKILL.md"
    if not md.exists():
        return ""
    try:
        text = md.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    m = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
    if m:
        return m.group(1).strip().strip("\"'")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") and len(line) > 2:
            return line.lstrip("# ").strip()
    return ""


class SkillsExtensionsTab(QtWidgets.QWidget):
    """技能(skills)/扩展(extensions)/npm包(packages) 三合一管理树。"""

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setObjectName("extTab")

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # 工具条
        bar = QtWidgets.QHBoxLayout()
        self.btn_refresh = QtWidgets.QPushButton("🔄 刷新")
        self.btn_refresh.clicked.connect(self.reload)
        self.btn_open = QtWidgets.QPushButton("📂 打开所在文件夹")
        self.btn_open.clicked.connect(self._on_open_folder)
        self.btn_delete = QtWidgets.QPushButton("🗑 删除选中项")
        self.btn_delete.clicked.connect(self._on_delete)
        for b in (self.btn_refresh, self.btn_open, self.btn_delete):
            bar.addWidget(b)
        bar.addStretch(1)
        root.addLayout(bar)

        # 主树
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["名称", "说明"])
        self.tree.setColumnWidth(0, 260)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemDoubleClicked.connect(lambda *_: self._on_open_folder())
        header = self.tree.header()
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        root.addWidget(self.tree, 1)

        # npm 包添加行
        pkg_bar = QtWidgets.QHBoxLayout()
        self.ed_pkg = QtWidgets.QLineEdit()
        self.ed_pkg.setPlaceholderText("输入 npm 包名添加到 packages，如 npm:pi-mcp-adapter ...")
        self.btn_add_pkg = QtWidgets.QPushButton("➕ 添加 npm 包")
        self.btn_add_pkg.clicked.connect(self._on_add_package)
        self.ed_pkg.returnPressed.connect(self._on_add_package)
        pkg_bar.addWidget(self.ed_pkg, 1)
        pkg_bar.addWidget(self.btn_add_pkg)
        root.addLayout(pkg_bar)

        self.reload()

    # ---- 数据 ----
    def reload(self):
        self.tree.clear()

        root_skills = QtWidgets.QTreeWidgetItem(self.tree, ["🧠 技能", f"{SKILLS_DIR}"])
        root_ext = QtWidgets.QTreeWidgetItem(self.tree, ["🔌 扩展", f"{EXTENSIONS_DIR}"])
        pkgs = self.store.settings.get("packages", []) if isinstance(self.store.settings, dict) else []
        root_pkg = QtWidgets.QTreeWidgetItem(self.tree, ["📦 npm 包", f"settings.json packages ({len(pkgs)})"])
        for r in (root_skills, root_ext, root_pkg):
            r.setFirstColumnSpanned(True)

        if SKILLS_DIR.is_dir():
            for d in sorted(SKILLS_DIR.iterdir()):
                if d.is_dir():
                    QtWidgets.QTreeWidgetItem(
                        root_skills, [d.name, _skill_description(d)])
            root_skills.setExpanded(True)

        if EXTENSIONS_DIR.is_dir():
            for p in sorted(EXTENSIONS_DIR.iterdir()):
                kind = "📁" if p.is_dir() else "📄"
                QtWidgets.QTreeWidgetItem(root_ext, [f"{kind} {p.name}", ""])
            root_ext.setExpanded(True)

        for name in pkgs:
            QtWidgets.QTreeWidgetItem(root_pkg, [name, ""])

    def _selected_entry(self):
        """返回 (类别, 路径或包名)；未选中子项时返回 (None, None)。"""
        item = self.tree.currentItem()
        parent = item.parent() if item else None
        if item is None or parent is None:
            return None, None
        cat = parent.text(0)
        raw = item.text(0)
        name = re.sub(r"^[📁📄] ", "", raw)
        if cat.startswith("🧠"):
            return "skill", SKILLS_DIR / name
        if cat.startswith("🔌"):
            return "extension", EXTENSIONS_DIR / name
        if cat.startswith("📦"):
            return "package", name
        return None, None

    # ---- 操作 ----
    def _on_open_folder(self):
        cat, target = self._selected_entry()
        path = SKILLS_DIR if cat == "package" else target
        if path and Path(path).exists():
            os.startfile(str(path))

    def _on_delete(self):
        cat, target = self._selected_entry()
        if cat is None:
            return
        if cat == "package":
            self._remove_package(target)
            return
        path = Path(target)
        if not path.exists():
            return
        tip = "该扩展由 Switcher 管理，下次启动会自动重新安装。\n" if path.name == "vision-bridge.ts" else ""
        ret = QtWidgets.QMessageBox.question(
            self, "确认删除",
            f"{tip}确定要删除 {path.name} 吗？此操作不可撤销。",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No)
        if ret != QtWidgets.QMessageBox.Yes:
            return
        try:
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "删除失败", str(exc))
            return
        self.reload()

    def _on_add_package(self):
        name = self.ed_pkg.text().strip()
        if not name:
            return
        pkgs = self.store.settings.setdefault("packages", [])
        if name not in pkgs:
            pkgs.append(name)
            from app import SETTINGS_PATH, write_json
            write_json(SETTINGS_PATH, self.store.settings)
            self.store.load()
        self.ed_pkg.clear()
        self.reload()

    def _remove_package(self, name):
        pkgs = self.store.settings.get("packages", [])
        if name not in pkgs:
            return
        pkgs.remove(name)
        from app import SETTINGS_PATH, write_json
        write_json(SETTINGS_PATH, self.store.settings)
        self.store.load()
        self.reload()
