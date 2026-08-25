# -*- coding: utf-8 -*-
"""
Custom PyQt5 Modern UI Widgets for pi-api-switcher:
- Theme-Adaptive Colors (Dark / Light / Terminal / Codex / DeepSeek / Modern Light)
- SparklineWidget: Smooth cubic Bezier trend curve with subtle gradient fill
- DailyAvgCardWidget: 3-row layout (Daily Requests, Daily Tokens, Daily Cost) with range tag
- StandardCardWidget: Top Title + Icon, Big Value, 2-part Sub-Info, and Sparkline curve
- HeatmapGridWidget: Token Matrix & Request Health Matrix
- HeatmapLegendWidget: True colored squares legend with exact color steps
- ModelUsageListWidget: Left-bottom model breakdown cards with multi-color bars
"""

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import (
    QPainter, QColor, QPainterPath, QPen, QBrush, QLinearGradient
)


class SparklineWidget(QtWidgets.QWidget):
    """Smooth Bezier trend curve widget with soft gradient background."""

    def __init__(self, data=None, color="#3b82f6", parent=None):
        super().__init__(parent)
        self.data = data or []
        self.stroke_color = QColor(color)
        self.setFixedHeight(48)
        self.setMinimumWidth(80)

    def set_data(self, data, color=None):
        self.data = data or []
        if color:
            self.stroke_color = QColor(color)
        self.update()

    def paintEvent(self, event):
        if not self.data or len(self.data) < 2:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        pad_x = 4
        pad_y = 6

        min_val = min(self.data)
        max_val = max(self.data)
        val_range = max(max_val - min_val, 1)

        points = []
        n = len(self.data)
        for i, val in enumerate(self.data):
            x = pad_x + (w - 2 * pad_x) * (i / (n - 1))
            norm = (val - min_val) / val_range
            y = (h - pad_y) - norm * (h - 2 * pad_y)
            points.append(QPointF(x, y))

        path = QPainterPath()
        path.moveTo(points[0])

        for i in range(len(points) - 1):
            p0 = points[max(i - 1, 0)]
            p1 = points[i]
            p2 = points[i + 1]
            p3 = points[min(i + 2, len(points) - 1)]

            c1 = QPointF(p1.x() + (p2.x() - p0.x()) / 6.0, p1.y() + (p2.y() - p0.y()) / 6.0)
            c2 = QPointF(p2.x() - (p3.x() - p1.x()) / 6.0, p2.y() - (p3.y() - p1.y()) / 6.0)
            path.cubicTo(c1, c2, p2)

        # Fill under curve
        fill_path = QPainterPath(path)
        fill_path.lineTo(points[-1].x(), h)
        fill_path.lineTo(points[0].x(), h)
        fill_path.closeSubpath()

        grad = QLinearGradient(0, 0, 0, h)
        c_start = QColor(self.stroke_color)
        c_start.setAlpha(45)
        c_end = QColor(self.stroke_color)
        c_end.setAlpha(0)
        grad.setColorAt(0, c_start)
        grad.setColorAt(1, c_end)

        painter.fillPath(fill_path, QBrush(grad))

        # Stroke line
        pen = QPen(self.stroke_color, 2.0)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)

        # Draw end dot（半径增大到 5px 并加白色描边，增强端点视觉存在感）
        last_pt = points[-1]
        painter.setBrush(QBrush(self.stroke_color))
        pen = QPen(QColor(255, 255, 255), 1.5)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawEllipse(last_pt, 5.0, 5.0)


class DailyAvgCardWidget(QtWidgets.QFrame):
    """Card 1 (Top-Left): '每日平均' 3-row layout like reference image."""

    # 顶部强调色横条颜色（与各行图标色对应的混合强调色）
    _accent_strip = QColor("#3b82f6")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("kpiCard")
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        # Header: Title + Range Tag
        top_row = QtWidgets.QHBoxLayout()
        self.lbl_title = QtWidgets.QLabel("每日平均")
        self.lbl_title.setObjectName("cardTitle")
        top_row.addWidget(self.lbl_title)
        top_row.addStretch(1)

        self.lbl_range = QtWidgets.QLabel("范围 142 天")
        self.lbl_range.setObjectName("rangeBadge")
        top_row.addWidget(self.lbl_range)
        layout.addLayout(top_row)

        layout.addSpacing(2)

        # Row 1: 平均请求
        r1 = QtWidgets.QHBoxLayout()
        icon1 = QtWidgets.QLabel("⚡")
        icon1.setObjectName("rowIcon")
        icon1.setStyleSheet("color: #3b82f6;")
        lbl_r1_name = QtWidgets.QLabel("平均请求")
        lbl_r1_name.setObjectName("rowLabel")
        r1.addWidget(icon1)
        r1.addWidget(lbl_r1_name)
        r1.addStretch(1)
        self.val_req = QtWidgets.QLabel("0.0")
        self.val_req.setObjectName("rowValue")
        r1.addWidget(self.val_req)
        layout.addLayout(r1)

        # Row 2: 平均 Token 数
        r2 = QtWidgets.QHBoxLayout()
        icon2 = QtWidgets.QLabel("◇")
        icon2.setObjectName("rowIcon")
        icon2.setStyleSheet("color: #8b5cf6;")
        lbl_r2_name = QtWidgets.QLabel("平均 Token 数")
        lbl_r2_name.setObjectName("rowLabel")
        r2.addWidget(icon2)
        r2.addWidget(lbl_r2_name)
        r2.addStretch(1)
        self.val_tok = QtWidgets.QLabel("0.00M")
        self.val_tok.setObjectName("rowValue")
        r2.addWidget(self.val_tok)
        layout.addLayout(r2)

        # Row 3: 平均费用
        r3 = QtWidgets.QHBoxLayout()
        icon3 = QtWidgets.QLabel("$")
        icon3.setObjectName("rowIcon")
        icon3.setStyleSheet("color: #f59e0b; font-weight: 800;")
        lbl_r3_box = QtWidgets.QVBoxLayout()
        lbl_r3_box.setSpacing(0)
        lbl_r3_name = QtWidgets.QLabel("平均费用")
        lbl_r3_name.setObjectName("rowLabel")
        lbl_r3_sub = QtWidgets.QLabel("预估使用价格")
        lbl_r3_sub.setObjectName("subHint")
        lbl_r3_box.addWidget(lbl_r3_name)
        lbl_r3_box.addWidget(lbl_r3_sub)

        r3.addWidget(icon3)
        r3.addLayout(lbl_r3_box)
        r3.addStretch(1)
        self.val_cost = QtWidgets.QLabel("$0.0000")
        self.val_cost.setObjectName("rowValue")
        r3.addWidget(self.val_cost)
        layout.addLayout(r3)

        layout.addStretch(1)

    def start_shimmer(self):
        """开启骨架屏扫光动效。"""
        self._shimmering = True
        self._shimmer_phase = 0.0
        if not hasattr(self, "_shimmer_timer") or self._shimmer_timer is None:
            self._shimmer_timer = QtCore.QTimer(self)
            self._shimmer_timer.setInterval(33)
            self._shimmer_timer.timeout.connect(self._on_shimmer_step)
        if not self._shimmer_timer.isActive():
            self._shimmer_timer.start()
        self.update()

    def stop_shimmer(self):
        """停止骨架屏扫光动效。"""
        self._shimmering = False
        if hasattr(self, "_shimmer_timer") and self._shimmer_timer and self._shimmer_timer.isActive():
            self._shimmer_timer.stop()
        self.update()

    def _on_shimmer_step(self):
        self._shimmer_phase = (self._shimmer_phase + 0.04) % 1.0
        self.update()

    def update_data(self, days_span, avg_calls, avg_tokens_str, avg_cost):
        self.stop_shimmer()
        self.lbl_range.setText(f"范围 {days_span} 天")
        self.val_req.setText(f"{avg_calls:.1f}")
        self.val_tok.setText(avg_tokens_str)
        self.val_cost.setText(f"${avg_cost:.4f}")

    def paintEvent(self, event):
        """先绘制默认背景，再绘制 Shimmer 扫光（如果激活）及顶部 3px 强调色横条。"""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 骨架屏扫光动效
        if getattr(self, "_shimmering", False):
            w = float(self.width())
            h = float(self.height())
            band_w = w * 0.6
            center_x = (self._shimmer_phase * (w + band_w * 2)) - band_w
            grad = QLinearGradient(center_x - band_w / 2, 0, center_x + band_w / 2, 0)
            c_transparent = QColor(255, 255, 255, 0)
            c_glow = QColor(255, 255, 255, 28)
            grad.setColorAt(0.0, c_transparent)
            grad.setColorAt(0.5, c_glow)
            grad.setColorAt(1.0, c_transparent)
            painter.setBrush(QBrush(grad))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 8, 8)

        # 顶部 3px 强调色横条，与圆角对齐
        painter.setBrush(QBrush(self._accent_strip))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(0, 0, self.width(), 3), 2, 2)


class StandardCardWidget(QtWidgets.QFrame):
    """Cards 2-7: Top Title + Icon badge, Large Metric Value, Subtitle details, Sparkline."""

    def __init__(self, title, icon_char="⚡", accent_color="#3b82f6", parent=None):
        super().__init__(parent)
        self.accent_color = accent_color
        self._shimmering = False
        self._shimmer_phase = 0.0
        self.setObjectName("kpiCard")
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 12)
        layout.setSpacing(6)

        # Top row: Title + Icon Badge
        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(8)

        self.lbl_title = QtWidgets.QLabel(title)
        self.lbl_title.setObjectName("cardTitle")
        top_row.addWidget(self.lbl_title)
        top_row.addStretch(1)

        self.lbl_icon = QtWidgets.QLabel(icon_char)
        self.lbl_icon.setAlignment(Qt.AlignCenter)
        self.lbl_icon.setFixedSize(28, 28)
        self.lbl_icon.setStyleSheet(f"""
            QLabel {{
                background-color: {accent_color}22;
                color: {accent_color};
                font-weight: 800;
                font-size: 13px;
                border-radius: 8px;
            }}
        """)
        top_row.addWidget(self.lbl_icon)
        layout.addLayout(top_row)

        # Value
        self.lbl_value = QtWidgets.QLabel("0")
        self.lbl_value.setObjectName("cardBigValue")
        layout.addWidget(self.lbl_value)

        # Sub-info
        self.lbl_sub = QtWidgets.QLabel("")
        self.lbl_sub.setObjectName("cardSubInfo")
        self.lbl_sub.setWordWrap(True)
        layout.addWidget(self.lbl_sub)

        # Sparkline
        self.spark = SparklineWidget(color=accent_color, parent=self)
        layout.addWidget(self.spark)

    def start_shimmer(self):
        """开启骨架屏扫光动效。"""
        self._shimmering = True
        self._shimmer_phase = 0.0
        if not hasattr(self, "_shimmer_timer") or self._shimmer_timer is None:
            self._shimmer_timer = QtCore.QTimer(self)
            self._shimmer_timer.setInterval(33)
            self._shimmer_timer.timeout.connect(self._on_shimmer_step)
        if not self._shimmer_timer.isActive():
            self._shimmer_timer.start()
        self.update()

    def stop_shimmer(self):
        """停止骨架屏扫光动效。"""
        self._shimmering = False
        if hasattr(self, "_shimmer_timer") and self._shimmer_timer and self._shimmer_timer.isActive():
            self._shimmer_timer.stop()
        self.update()

    def _on_shimmer_step(self):
        self._shimmer_phase = (self._shimmer_phase + 0.04) % 1.0
        self.update()

    def update_data(self, value_str, sub_info="", spark_data=None):
        self.stop_shimmer()
        self.lbl_value.setText(value_str)
        self.lbl_sub.setText(sub_info)
        if spark_data is not None:
            self.spark.set_data(spark_data, self.accent_color)

    def paintEvent(self, event):
        """先绘制默认背景，再绘制 Shimmer 扫光（若激活）与顶部 3px 强调色横条。"""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 骨架屏扫光动效
        if getattr(self, "_shimmering", False):
            w = float(self.width())
            h = float(self.height())
            band_w = w * 0.6
            center_x = (self._shimmer_phase * (w + band_w * 2)) - band_w
            grad = QLinearGradient(center_x - band_w / 2, 0, center_x + band_w / 2, 0)
            c_transparent = QColor(255, 255, 255, 0)
            c_glow = QColor(255, 255, 255, 28)
            grad.setColorAt(0.0, c_transparent)
            grad.setColorAt(0.5, c_glow)
            grad.setColorAt(1.0, c_transparent)
            painter.setBrush(QBrush(grad))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 8, 8)

        # 顶部 3px 强调色横条
        painter.setBrush(QBrush(QColor(self.accent_color)))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(0, 0, self.width(), 3), 2, 2)


class HeatmapGridWidget(QtWidgets.QWidget):
    """Activity matrix heatmap for Tokens or Health status."""

    def __init__(self, mode="tokens", data=None, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.data = data or []
        self.theme_colors = None
        self.cell_gap = 5
        self.radius = 3.5
        self.setMinimumHeight(140)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        # U-2：启用鼠标追踪以显示悬停 Tooltip
        self.setMouseTracking(True)
        # 缓存网格几何信息，供 mouseMoveEvent 命中测试使用
        self._grid_rows = 7
        self._grid_cols = 0
        self._cell_size = 0
        self._step_x = 0
        self._step_y = 0
        self._offset_x = 0
        self._offset_y = 0

    def set_theme_colors(self, c):
        self.theme_colors = c
        self.update()

    def set_data(self, data):
        self.data = data or []
        self.update()

    def _get_token_color(self, val, max_val):
        c = self.theme_colors
        empty = QColor(c["border"]) if c else QColor("#e2e8f0")
        accent = QColor(c["accent"]) if c else QColor("#3b82f6")
        if val <= 0:
            return empty
        ratio = min(val / max(max_val, 1), 1.0)
        if ratio < 0.2:
            return QColor(accent.red(), accent.green(), accent.blue(), 90)
        elif ratio < 0.45:
            return QColor(accent.red(), accent.green(), accent.blue(), 150)
        elif ratio < 0.75:
            return QColor(accent.red(), accent.green(), accent.blue(), 200)
        else:
            return accent

    def _get_health_color(self, item):
        c = self.theme_colors
        empty = QColor(c["border"]) if c else QColor("#e2e8f0")
        green = QColor(c["green"]) if c else QColor("#22c55e")
        red = QColor(c["red"]) if c else QColor("#ef4444")
        yellow = QColor(c["yellow"]) if c else QColor("#eab308")

        calls = item.get("calls", 0)
        if calls <= 0:
            return empty
        rate = item.get("rate", 1.0)
        if rate >= 0.95:
            return green
        elif rate >= 0.8:
            return QColor(132, 204, 22)
        elif rate >= 0.6:
            return yellow
        elif rate >= 0.4:
            return QColor(249, 115, 22)
        else:
            return red

    def paintEvent(self, event):
        if not self.data:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rows = 7  # 7 days of week
        cols = (len(self.data) + rows - 1) // rows

        w = self.width()
        h = self.height()

        max_possible_w = (w - (cols - 1) * self.cell_gap) / max(cols, 1)
        max_possible_h = (h - (rows - 1) * self.cell_gap) / max(rows, 1)
        cell_size = max(int(min(max_possible_w, max_possible_h)), 8)

        step_x = cell_size + self.cell_gap
        step_y = cell_size + self.cell_gap
        
        total_w = cols * cell_size + (cols - 1) * self.cell_gap
        total_h = rows * cell_size + (rows - 1) * self.cell_gap
        offset_x = max(int((w - total_w) / 2), 0)
        offset_y = max(int((h - total_h) / 2), 0)

        # 缓存网格几何，供 mouseMoveEvent 命中测试
        self._grid_rows = rows
        self._grid_cols = cols
        self._cell_size = cell_size
        self._step_x = step_x
        self._step_y = step_y
        self._offset_x = offset_x
        self._offset_y = offset_y

        max_token = max([d.get("tokens", 0) for d in self.data] or [1])

        for idx, item in enumerate(self.data):
            col = idx // rows
            row = idx % rows

            x = offset_x + col * step_x
            y = offset_y + row * step_y

            if self.mode == "tokens":
                color = self._get_token_color(item.get("tokens", 0), max_token)
            else:
                color = self._get_health_color(item)

            painter.setBrush(QBrush(color))
            painter.setPen(Qt.NoPen)
            rect = QRectF(x, y, cell_size, cell_size)
            painter.drawRoundedRect(rect, self.radius, self.radius)

    def _cell_index_at(self, pos):
        """根据鼠标坐标返回命中的单元格在 self.data 中的索引，未命中返回 -1。"""
        x, y = pos.x(), pos.y()
        cs = self._cell_size
        if cs <= 0 or self._grid_cols <= 0:
            return -1
        # 反推列/行：相对偏移
        rel_x = x - self._offset_x
        rel_y = y - self._offset_y
        if rel_x < 0 or rel_y < 0:
            return -1
        col = int(rel_x / self._step_x)
        row = int(rel_y / self._step_y)
        # 落在间隔里算未命中
        if (rel_x - col * self._step_x) > cs or (rel_y - row * self._step_y) > cs:
            return -1
        if col < 0 or col >= self._grid_cols or row < 0 or row >= self._grid_rows:
            return -1
        idx = col * self._grid_rows + row
        if 0 <= idx < len(self.data):
            return idx
        return -1

    def mouseMoveEvent(self, event):
        """U-2：悬停在热力图色块上时显示 Tooltip（日期/请求数/Token 数）。"""
        idx = self._cell_index_at(event.pos())
        if idx < 0:
            QtWidgets.QToolTip.hideText()
            return
        item = self.data[idx]
        date = item.get("date", "")
        calls = item.get("calls", 0)
        if self.mode == "tokens":
            tokens = item.get("tokens", 0)
            inp = item.get("input", 0)
            out = item.get("output", 0)
            tooltip = f"{date}：{calls} 次请求，{tokens:,} Tokens\n输入 {inp:,}  输出 {out:,}"
        else:
            succ = item.get("success", 0)
            fail = item.get("fail", 0)
            rate = item.get("rate", 1.0)
            tooltip = f"{date}：{calls} 次请求，成功率 {rate*100:.1f}%\n成功 {succ}  失败 {fail}"
        if calls <= 0:
            tooltip = f"{date}：无活动"
        QtWidgets.QToolTip.showText(event.globalPos(), tooltip, self)


class HeatmapLegendWidget(QtWidgets.QWidget):
    """Accurate color-block legend widget (e.g. '较少  ■ ■ ■ ■  较多' or '不健康  ■ ■ ■ ■  健康')."""

    def __init__(self, mode="tokens", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.theme_colors = None
        self.setFixedHeight(22)
        self.setMinimumWidth(160)
        self._update_colors()

    def set_theme_colors(self, c):
        self.theme_colors = c
        self._update_colors()
        self.update()

    def _update_colors(self):
        c = self.theme_colors
        empty_bg = QColor(c["border"]) if c else QColor("#e2e8f0")
        accent = QColor(c["accent"]) if c else QColor("#3b82f6")
        green = QColor(c["green"]) if c else QColor("#22c55e")
        red = QColor(c["red"]) if c else QColor("#ef4444")
        yellow = QColor(c["yellow"]) if c else QColor("#eab308")

        if self.mode == "tokens":
            self.left_text = "较少"
            self.right_text = "较多"
            # 渐变 5 阶
            self.colors = [
                empty_bg,
                QColor(accent.red(), accent.green(), accent.blue(), 100),
                QColor(accent.red(), accent.green(), accent.blue(), 160),
                QColor(accent.red(), accent.green(), accent.blue(), 210),
                accent,
            ]
        else:
            self.left_text = "不健康"
            self.right_text = "健康"
            self.colors = [
                red,
                QColor(249, 115, 22),
                yellow,
                QColor(132, 204, 22),
                green,
            ]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)
        
        text_color = QColor(self.theme_colors["text_dim"]) if self.theme_colors else QColor("#94a3b8")
        painter.setPen(text_color)

        fm = painter.fontMetrics()
        h = self.height()
        box_size = 9
        gap = 4

        left_w = fm.horizontalAdvance(self.left_text)
        right_w = fm.horizontalAdvance(self.right_text)
        total_boxes_w = len(self.colors) * box_size + (len(self.colors) - 1) * gap
        total_w = left_w + 8 + total_boxes_w + 8 + right_w

        # Right aligned
        start_x = self.width() - total_w - 4

        # Draw left text
        text_y = int((h + fm.ascent() - fm.descent()) / 2)
        painter.drawText(int(start_x), text_y, self.left_text)

        # Draw colored boxes
        box_x = start_x + left_w + 8
        box_y = int((h - box_size) / 2)

        painter.setPen(Qt.NoPen)
        for clr in self.colors:
            painter.setBrush(QBrush(clr))
            painter.drawRoundedRect(QRectF(box_x, box_y, box_size, box_size), 2, 2)
            box_x += box_size + gap

        # Draw right text
        painter.setPen(text_color)
        painter.drawText(int(box_x + 4), text_y, self.right_text)


class ModelUsageListWidget(QtWidgets.QWidget):
    """Left-bottom widget showing model-by-model token stats & progress breakdown."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(14, 12, 14, 12)
        self.layout.setSpacing(10)
        # 复用的卡片控件列表，避免每次刷新全量重建（P-4）
        self._model_cards = []
        self._empty_label = None
        # 主题色板，由 dashboard_tab 传入
        self.theme_colors = None

    def set_theme_colors(self, c):
        self.theme_colors = c
        # 刷新已有卡片的颜色
        if self._model_cards:
            self._refresh_card_colors()

    def _palette(self):
        """从主题色派生颜色列表（U-10），缺省回退到固定色板。"""
        c = self.theme_colors
        if c:
            return [c["accent"], c["green"], c["accent_2"], c["yellow"],
                    c["blue"], c["red"], c["text_dim"]]
        return ["#3b82f6", "#10b981", "#8b5cf6", "#f59e0b",
                "#06b6d4", "#ec4899", "#64748b"]

    def _refresh_card_colors(self):
        """主题切换后更新已有卡片的颜色。"""
        palette = self._palette()
        for idx, entry in enumerate(self._model_cards):
            color = palette[idx % len(palette)]
            entry["color"] = color
            entry["val"].setStyleSheet(f"font-size: 11px; font-weight: 700; color: {color};")
            entry["pbar"].setStyleSheet(
                f"QProgressBar#modelProgressBar::chunk {{ background: {color}; border-radius: 2px; }}"
            )

    def update_models(self, models_dict, total_tokens):
        from analytics import format_number_compact

        palette = self._palette()
        sorted_models = sorted(models_dict.items(), key=lambda x: x[1]["total"], reverse=True)
        top_models = sorted_models[:8]

        has_data = bool(models_dict) and total_tokens > 0
        # 空状态：复用或创建一个占位 label
        if not has_data:
            for entry in self._model_cards:
                entry["card"].setVisible(False)
            if self._empty_label is None:
                self._empty_label = QtWidgets.QLabel("暂无调用记录")
                self._empty_label.setStyleSheet("color: #94a3b8; font-size: 12px; padding: 20px;")
                self._empty_label.setAlignment(Qt.AlignCenter)
                self.layout.addWidget(self._empty_label)
            self._empty_label.setVisible(True)
            return
        if self._empty_label is not None:
            self._empty_label.setVisible(False)

        n = len(top_models)
        # 复用已有卡片：多则隐藏多余，少则补建（P-4，避免视觉闪烁）
        for i in range(n, len(self._model_cards)):
            self._model_cards[i]["card"].setVisible(False)

        for idx, (mname, stats) in enumerate(top_models):
            tot = stats["total"]
            percent = (tot / total_tokens) * 100
            color = palette[idx % len(palette)]

            if idx < len(self._model_cards):
                entry = self._model_cards[idx]
                entry["card"].setVisible(True)
                entry["name"].setText(mname)
                tokens_str = format_number_compact(tot)
                entry["val"].setText(f"{tokens_str} Tokens ({percent:.1f}%)")
                entry["val"].setStyleSheet(f"font-size: 11px; font-weight: 700; color: {color};")
                c_read = format_number_compact(stats.get('cacheRead', 0))
                in_str = format_number_compact(stats.get('input', 0))
                out_str = format_number_compact(stats.get('output', 0))
                entry["sub"].setText(
                    f"调用: {stats['calls']} 次  ·  输入: {in_str}  ·  输出: {out_str}  ·  缓存: {c_read}"
                )
                entry["pbar"].setValue(int(percent * 10))
                entry["pbar"].setStyleSheet(
                    f"QProgressBar#modelProgressBar::chunk {{ background: {color}; border-radius: 2px; }}"
                )
                entry["color"] = color
            else:
                # 补建新卡片
                card = QtWidgets.QFrame()
                card.setObjectName("modelCard")
                clayout = QtWidgets.QVBoxLayout(card)
                clayout.setContentsMargins(12, 10, 12, 10)
                clayout.setSpacing(5)

                h_top = QtWidgets.QHBoxLayout()
                lbl_name = QtWidgets.QLabel(mname)
                lbl_name.setObjectName("modelName")
                tokens_str = format_number_compact(tot)
                lbl_val = QtWidgets.QLabel(f"{tokens_str} Tokens ({percent:.1f}%)")
                lbl_val.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {color};")
                h_top.addWidget(lbl_name)
                h_top.addStretch(1)
                h_top.addWidget(lbl_val)
                clayout.addLayout(h_top)

                h_sub = QtWidgets.QHBoxLayout()
                c_read = format_number_compact(stats.get('cacheRead', 0))
                in_str = format_number_compact(stats.get('input', 0))
                out_str = format_number_compact(stats.get('output', 0))
                sub_text = f"调用: {stats['calls']} 次  ·  输入: {in_str}  ·  输出: {out_str}  ·  缓存: {c_read}"
                lbl_sub = QtWidgets.QLabel(sub_text)
                lbl_sub.setObjectName("modelSub")
                h_sub.addWidget(lbl_sub)
                h_sub.addStretch(1)
                clayout.addLayout(h_sub)

                pbar = QtWidgets.QProgressBar()
                pbar.setFixedHeight(5)
                pbar.setTextVisible(False)
                pbar.setRange(0, 1000)
                pbar.setValue(int(percent * 10))
                pbar.setObjectName("modelProgressBar")
                pbar.setStyleSheet(
                    f"QProgressBar#modelProgressBar::chunk {{ background: {color}; border-radius: 2px; }}"
                )
                clayout.addWidget(pbar)

                self.layout.addWidget(card)
                self._model_cards.append({
                    "card": card, "name": lbl_name, "val": lbl_val,
                    "sub": lbl_sub, "pbar": pbar, "color": color,
                })

        # 确保 stretch 项存在一次
        if self.layout.count() == len(self._model_cards) + (1 if self._empty_label is not None else 0):
            self.layout.addStretch(1)
