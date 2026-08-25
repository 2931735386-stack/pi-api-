"""
pi-api-switcher 多主题配色与全局样式表。

从 app.py 拆出：THEMES 配色字典、13 个 qss_* 样式片段生成函数，
以及当前主题状态（current_colors / set_current_theme）。
"""

# 当前激活主题的配色（由 set_current_theme 维护）
_CURRENT = None


THEMES = {
    # ===== Modern Light (拟物卡片微拟态风格) =====
    "modern_light": {
        "bg": "#f4f6f9", "bg_alt": "#ebf0f5", "panel": "#ffffff", "border": "#e2e8f0",
        "text": "#0f172a", "text_dim": "#64748b",
        "accent": "#3b82f6", "accent_2": "#8b5cf6", "accent_hover": "#2563eb",
        "green": "#10b981", "red": "#ef4444", "yellow": "#f59e0b", "blue": "#3b82f6",
        "btn_text": "#ffffff",
    },
    # ===== Terminal 风格：黑灰底 + 暖橙强调，极简终端感 =====
    "terminal": {
        "bg": "#0d0d0d", "bg_alt": "#080808", "panel": "#1a1a1a", "border": "#2a2a2a",
        "text": "#e8e8e8", "text_dim": "#7a7a7a",
        "accent": "#ff8c42", "accent_2": "#d4a373", "accent_hover": "#ffa05c",
        "green": "#7cb342", "red": "#ef5350", "yellow": "#ffca28", "blue": "#5c9eff",
        "btn_text": "#0d0d0d",
    },
    # ===== Codex 风格（OpenAI CLI）：白色底 + 绿色强调，简洁明亮 =====
    "codex": {
        "bg": "#ffffff", "bg_alt": "#f5f5f5", "panel": "#f0f0f0", "border": "#e0e0e0",
        "text": "#1a1a1a", "text_dim": "#666666",
        "accent": "#10a37f", "accent_2": "#0d8c6f", "accent_hover": "#0e9170",
        "green": "#10a37f", "red": "#ef4444", "yellow": "#f59e0b", "blue": "#3b82f6",
        "btn_text": "#ffffff",
    },
    # ===== Claude Code 风格：暖橙赭 + 米色终端，温润纸质调 =====
    "claude": {
        "bg": "#1c1815", "bg_alt": "#15110e", "panel": "#2a231d", "border": "#3d3429",
        "text": "#f0e6d8", "text_dim": "#a89b8a",
        "accent": "#e07a3c", "accent_2": "#c89968", "accent_hover": "#f08850",
        "green": "#8fa856", "red": "#d96552", "yellow": "#d4a83a", "blue": "#6b8cb4",
        "btn_text": "#1c1815",
    },
    # ===== DeepSeek 风格：深蓝底 + 科技青蓝，冷调未来感 =====
    "deepseek": {
        "bg": "#0a1428", "bg_alt": "#050b18", "panel": "#11203a", "border": "#1e3050",
        "text": "#dce8f5", "text_dim": "#7890b0",
        "accent": "#1ec8e8", "accent_2": "#4d8aff", "accent_hover": "#3dd9f0",
        "green": "#26d97f", "red": "#ff5c7c", "yellow": "#ffce47", "blue": "#4d8aff",
        "btn_text": "#0a1428",
    },
    # ===== 青绿+錡蓝（默认/原） =====
    "teal": {
        "bg": "#0f1117", "bg_alt": "#0a0c12", "panel": "#1a1d27", "border": "#2a2e3a",
        "text": "#e6e8ef", "text_dim": "#8b90a0",
        "accent": "#2dd4bf", "accent_2": "#6366f1", "accent_hover": "#5eead4",
        "green": "#34d399", "red": "#f87171", "yellow": "#fbbf24", "blue": "#38bdf8",
        "btn_text": "#0f1117",
    },
    # ===== GitHub Night：紫+蓝（深色高对比） =====
    "night": {
        "bg": "#0d1117", "bg_alt": "#010409", "panel": "#161b22", "border": "#30363d",
        "text": "#e6edf3", "text_dim": "#8b949e",
        "accent": "#d2a8ff", "accent_2": "#79c0ff", "accent_hover": "#bc8cff",
        "green": "#3fb950", "red": "#ff7b72", "yellow": "#e3b341", "blue": "#58a6ff",
        "btn_text": "#0d1117",
    },
    # ===== 浅色主题 =====
    "light": {
        "bg": "#fafafa", "bg_alt": "#f0f0f0", "panel": "#ffffff", "border": "#e0e0e0",
        "text": "#1a1a1a", "text_dim": "#666666",
        "accent": "#0891b2", "accent_2": "#4f46e5", "accent_hover": "#06b6d4",
        "green": "#16a34a", "red": "#dc2626", "yellow": "#ca8a04", "blue": "#2563eb",
        "btn_text": "#ffffff",
    },
}


def get_theme(name):
    """按名称取配色，未知名称回退到 terminal。"""
    return THEMES.get(name, THEMES["terminal"])


def set_current_theme(name):
    """切换当前主题并返回新配色。"""
    global _CURRENT
    _CURRENT = get_theme(name)
    return _CURRENT


def current_colors():
    """当前配色；未初始化时回退默认主题。"""
    return _CURRENT or THEMES["terminal"]


def qss_global(c):
    return f"""
        /* === 全局 === */
        QMainWindow, QWidget {{ background: {c['bg']}; color: {c['text']}; }}
        QLabel {{ color: {c['text_dim']}; font-size: 13px; }}
        QLabel#fieldHint {{ color: {c['text_dim']}; font-size: 11px; padding-left: 6px; }}
        QToolTip {{
            background-color: {c['panel']};
            color: {c['text']};
            border: 1px solid {c['accent']};
            border-radius: 6px;
            padding: 5px 8px;
            font-size: 12px;
        }}
    """



def qss_menubar(c):
    bt = c["btn_text"]
    return f"""
        /* === 菜单栏 === */
        QMenuBar {{ background: {c['bg_alt']}; color: {c['text_dim']};
                     border-bottom: 1px solid {c['border']}; padding: 3px 8px; }}
        QMenuBar::item {{ background: transparent; padding: 5px 12px; border-radius: 6px;
                           font-size: 13px; }}
        QMenuBar::item:selected {{ background: {c['panel']}; color: {c['accent']}; }}
        QMenu {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']};
                 padding: 6px; border-radius: 8px; }}
        QMenu::item {{ padding: 7px 28px 7px 20px; border-radius: 6px; font-size: 13px; }}
        QMenu::item:selected {{ background: {c['accent']}; color: {bt}; }}
        QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 10px; }}
    """



def qss_sidebar(c):
    return f"""
        /* === 侧边栏 === */
        #sidebar {{ background: {c['bg_alt']};
                     border-right: 1px solid {c['border']}; }}
        #sidebarTitle {{ font-size: 15px; font-weight: 700; color: {c['accent']};
                          padding: 6px 4px 2px 4px; letter-spacing: 0.5px; }}
        #sidebarSearch {{
            background: {c['panel']};
            border: 1px solid {c['border']};
            border-radius: 6px;
            padding: 6px 10px;
            font-size: 12px;
            color: {c['text']};
            margin-bottom: 4px;
        }}
        #sidebarSearch:focus {{
            border-color: {c['accent']};
        }}
        #sidebarFooter {{ color: {c['text_dim']}; font-size: 11px; padding: 6px 0 2px 0; opacity: 0.7; }}
        #providerList {{ background: transparent; border: none; outline: none; font-size: 13px; }}
        #providerList::item {{ padding: 11px 10px; border-radius: 8px; margin: 1px 0;
                                border-left: 3px solid transparent; }}
        #providerList::item:selected {{ background: {c['panel']}; color: {c['accent']};
                                         border-left: 3px solid {c['accent']}; font-weight: 600; }}
        #providerList::item:hover:!selected {{ background: {c['panel']}; }}
    """



def qss_content(c):
    return f"""
        /* === 右侧内容区 === */
        #content {{ background: {c['bg']}; }}
        #detailTitle {{ font-size: 24px; font-weight: 700; color: {c['text']};
                         padding: 2px 0 4px 0; letter-spacing: -0.3px; }}
        #sectionLabel {{ font-size: 13px; font-weight: 600; color: {c['text']};
                          margin-top: 10px; margin-bottom: 4px;
                          border-left: 3px solid {c['accent']}; border-bottom: none;
                          padding-left: 8px; }}
    """



def qss_empty_state(c):
    return f"""
        /* === 空状态 === */
        #emptyHint {{ background: transparent; }}
        #emptyIcon {{ font-size: 64px; color: {c['border']}; font-weight: 300;
                       padding-bottom: 8px; }}
        #emptyText {{ color: {c['text_dim']}; font-size: 16px; font-weight: 500;
                       padding: 0; }}
        #emptySubText {{ color: {c['border']}; font-size: 13px; padding-top: 4px; }}
    """



def qss_model_table(c):
    return f"""
        /* === 模型表格 === */
        #modelTable {{
            background: {c['panel']};
            border: 1px solid {c['border']};
            border-radius: 8px;
            gridline-color: {c['border']};
            color: {c['text']};
            font-size: 13px;
            selection-background-color: transparent;
            selection-color: {c['text']};
        }}
        #modelTable::item {{
            padding: 5px 8px;
        }}
        #modelTable::item:alternate {{
            background: {c['bg_alt']};
        }}
        #modelTable::item:selected {{
            background: {c['bg_alt']};
            color: {c['text']};
        }}
        #modelTable QWidget {{
            background: transparent;
        }}
        /* 原地编辑器必须不透明，否则会和底层 item 文本发生重影。 */
        #modelTable QLineEdit {{
            background: {c['panel']};
            color: {c['text']};
            border: 1px solid {c['accent']};
            border-radius: 3px;
            padding: 0 6px;
            selection-background-color: {c['accent']};
            selection-color: {c['btn_text']};
        }}
        #modelTable QComboBox {{
            background: {c['panel']};
            color: {c['text']};
            border: 1px solid {c['border']};
            border-radius: 4px;
            padding: 2px 6px;
            font-size: 12px;
        }}
        #modelTable QComboBox:hover {{
            border-color: {c['accent']};
        }}
        #modelTable QCheckBox {{
            background: transparent;
        }}
        QHeaderView::section {{
            background: {c['bg_alt']};
            color: {c['text_dim']};
            border: none;
            padding: 7px 10px;
            font-size: 12px;
            font-weight: 600;
        }}
        /* === 进度条 === */
        QProgressBar#modelProgressBar {{
            background: {c['border']};
            border-radius: 2px;
            border: none;
        }}
    """



def qss_inputs(c):
    bt = c["btn_text"]
    return f"""
        /* === 输入框 === */
        QLineEdit {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 6px;
                     padding: 9px 12px; font-size: 13px; color: {c['text']}; }}
        QLineEdit:focus {{ border: 1px solid {c['accent']}; }}
        QLineEdit:disabled {{ background: {c['bg_alt']}; color: {c['text_dim']}; }}
        QCheckBox {{ color: {c['text_dim']}; font-size: 13px; spacing: 6px; }}
        QCheckBox::indicator {{ width: 16px; height: 16px; }}
        QComboBox {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']};
                     border-radius: 6px; padding: 5px 10px; font-size: 13px; }}
        QComboBox:hover {{ border-color: {c['text_dim']}; }}
        QComboBox::drop-down {{ border: none; width: 20px; }}
        QComboBox QAbstractItemView {{ background: {c['panel']}; color: {c['text']};
                                        border: 1px solid {c['border']}; border-radius: 6px;
                                        selection-background-color: {c['accent']};
                                        selection-color: {bt}; outline: none; }}
    """



def qss_buttons(c):
    bt = c["btn_text"]
    accent2_hover = c["accent_2"]
    return f"""
        /* === 按钮 === */
        QPushButton {{ border: none; border-radius: 6px; padding: 9px 18px;
                        font-size: 13px; font-weight: 600; }}
        #accentBtn {{ background: {c['accent']}; color: {bt}; }}
        #accentBtn:hover {{ background: {c['accent_hover']}; }}
        #accentBtn:pressed {{ background: {c['panel']}; color: {c['text']}; }}
        #accentBtn:disabled {{ background: {c['border']}; color: {c['text_dim']}; }}
        #primaryBtn {{ background: {c['accent_2']}; color: #ffffff; }}
        #primaryBtn:hover {{ background: {accent2_hover}; }}
        #primaryBtn:pressed {{ background: {c['panel']}; color: {c['text']}; }}
        #primaryBtn:disabled {{ background: {c['border']}; color: {c['text_dim']}; }}
        #dangerBtn {{ background: transparent; color: {c['red']}; border: 1px solid {c['red']}; }}
        #dangerBtn:hover {{ background: {c['red']}; color: {bt}; }}
        #dangerBtn:pressed {{ background: {c['red']}; color: {bt}; }}
        #ghostBtn {{ background: transparent; color: {c['text_dim']}; border: 1px solid {c['border']}; }}
        #ghostBtn:hover {{ border-color: {c['accent']}; color: {c['accent']}; }}
        #ghostBtn:pressed {{ background: {c['panel']}; }}
        #ghostBtn:disabled {{ color: {c['border']}; }}
        #eyeBtn {{ background: transparent; color: {c['text_dim']}; border: 1px solid {c['border']};
                    border-radius: 6px; font-size: 15px; }}
        #eyeBtn:hover {{ border-color: {c['accent']}; color: {c['accent']}; }}
        #eyeBtn:checked {{ background: {c['accent']}; color: {bt}; border-color: {c['accent']}; }}
    """



def qss_status(c):
    return f"""
        /* === 默认标记 & 状态栏 === */
        #defaultBadge {{ color: {c['green']}; font-size: 13px; font-weight: 600;
                          padding: 4px 0; }}
        #statusBar {{ color: {c['text_dim']}; font-size: 12px; padding-top: 8px;
                      border-top: 1px solid {c['border']}; }}
        #loadingDots {{ color: {c['accent']}; font-size: 14px; font-weight: 700;
                         padding-top: 8px; min-width: 24px; }}
    """



def qss_tabs(c):
    return f"""
        /* === 现代主选项卡 (Tabs) === */
        QTabWidget#mainTabs::pane {{
            border: none;
            background: {c['bg']};
        }}
        QTabWidget#mainTabs QTabBar::tab {{
            background: {c['bg_alt']};
            color: {c['text_dim']};
            padding: 10px 22px;
            font-size: 13px;
            font-weight: 700;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            margin-right: 4px;
            border: 1px solid {c['border']};
            border-bottom: none;
        }}
        QTabWidget#mainTabs QTabBar::tab:selected {{
            background: {c['panel']};
            color: {c['accent']};
            border-top: 3px solid {c['accent']};
        }}
        QTabWidget#mainTabs QTabBar::tab:hover:!selected {{
            background: {c['panel']};
            color: {c['text']};
        }}
        /* === 全局 Toast 提示胶囊 === */
        #toastWidget {{
            background: {c['panel']};
            border: 1.5px solid {c['accent']};
            border-radius: 20px;
        }}
        #toastText {{
            font-size: 13px;
            font-weight: 700;
            color: {c['text']};
        }}
    """



def qss_cards(c):
    return f"""
        /* === KPI 卡片微拟态容器与文字层次 === */
        QFrame#kpiCard {{
            background-color: {c['panel']};
            border: 1px solid {c['border']};
            border-radius: 14px;
        }}
        QFrame#kpiCard:hover {{
            border: 1px solid {c['accent']};
        }}
        QFrame#modelCard {{
            background-color: {c['bg_alt']};
            border: 1px solid {c['border']};
            border-radius: 8px;
        }}
        QFrame#modelCard:hover {{
            border: 1px solid {c['accent']};
        }}
        QLabel#cardTitle {{
            font-size: 13px;
            font-weight: 700;
            color: {c['text_dim']};
        }}
        QLabel#cardBigValue {{
            font-size: 24px;
            font-weight: 800;
            color: {c['text']};
            letter-spacing: -0.5px;
        }}
        QLabel#cardSubInfo {{
            font-size: 11px;
            color: {c['text_dim']};
        }}
        QLabel#sectionHeaderTitle {{
            font-size: 16px;
            font-weight: 800;
            color: {c['text']};
        }}
        QLabel#dateRangeLabel {{
            font-size: 12px;
            font-weight: 500;
            color: {c['text_dim']};
        }}
        QLabel#rangeBadge {{
            font-size: 11px;
            font-weight: 600;
            color: {c['text_dim']};
            background: {c['bg_alt']};
            border: 1px solid {c['border']};
            border-radius: 6px;
            padding: 2px 8px;
        }}
        QLabel#rowLabel {{
            font-size: 12px;
            color: {c['text_dim']};
        }}
        QLabel#rowValue {{
            font-size: 16px;
            font-weight: 800;
            color: {c['text']};
        }}
        QLabel#subHint {{
            font-size: 10px;
            color: {c['text_dim']};
        }}
        QLabel#modelName {{
            font-size: 12px;
            font-weight: 700;
            color: {c['text']};
        }}
        QLabel#modelSub {{
            font-size: 10px;
            color: {c['text_dim']};
        }}
    """



def qss_filter_bar(c):
    return f"""
        /* === Segmented Filter Buttons === */
        QFrame#segmentedFilterBox {{
            background: {c['bg_alt']};
            border: 1px solid {c['border']};
            border-radius: 8px;
        }}
        QPushButton#filterSegmentBtn {{
            background: transparent;
            color: {c['text_dim']};
            border: none;
            border-radius: 6px;
            padding: 4px 12px;
            font-size: 12px;
            font-weight: 700;
        }}
        QPushButton#filterSegmentBtn:checked {{
            background: {c['panel']};
            color: {c['accent']};
            border: 1px solid {c['border']};
        }}
        QPushButton#filterRefreshBtn {{
            background: {c['panel']};
            color: {c['accent']};
            border: 1px solid {c['border']};
            border-radius: 8px;
            padding: 4px 12px;
            font-size: 12px;
            font-weight: 600;
        }}
        QPushButton#filterRefreshBtn:hover {{
            background: {c['bg_alt']};
            border-color: {c['accent']};
        }}
    """



def qss_scrollbar(c):
    """细条圆角滚动条，与主题协调（隐藏默认箭头按钮）。"""
    return f"""
        /* === 滚动条（细条圆角，主题化） === */
        QScrollBar:vertical {{
            background: transparent;
            width: 8px;
            margin: 2px 0;
            border: none;
        }}
        QScrollBar:horizontal {{
            background: transparent;
            height: 8px;
            margin: 0 2px;
            border: none;
        }}
        QScrollBar::handle:vertical {{
            background: {c['border']};
            border-radius: 3px;
            min-height: 24px;
        }}
        QScrollBar::handle:horizontal {{
            background: {c['border']};
            border-radius: 3px;
            min-width: 24px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {c['text_dim']};
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {c['text_dim']};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            background: none;
            border: none;
            width: 0;
            height: 0;
        }}
        QScrollBar::add-page, QScrollBar::sub-page {{
            background: transparent;
        }}
    """



QSS_PARTS = (qss_global, qss_menubar, qss_sidebar, qss_content, qss_empty_state, qss_model_table, qss_inputs, qss_buttons, qss_status, qss_tabs, qss_cards, qss_filter_bar, qss_scrollbar,)


def build_stylesheet(colors=None):
    """组装完整全局样式表；colors 缺省时用当前主题。"""
    c = colors or current_colors()
    return "\n".join(fn(c) for fn in QSS_PARTS)
