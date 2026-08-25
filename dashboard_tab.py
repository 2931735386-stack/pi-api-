# -*- coding: utf-8 -*-
"""
Modern Analytics Dashboard Tab for pi-api-switcher
1:1 Design Fidelity according to the reference UI:
- Top 3 Cards: 每日平均 (3 rows with tag), 请求总数 (Success/Fail/Rate), Token 总数 (Cache/Write/Reasoning)
- Middle 4 Cards: RPM, TPM, 缓存率, 总成本 (with smooth sparklines)
- Filter Bar: '最近活动' + Date Range + [ 日 | 周 | 月 | 年 ] Segmented Control
- Bottom Left: 各模型 Token 消耗分布 (Ranked list with progress bars & metrics)
- Bottom Right: Token 活动 (Heatmap + Input/Output summary) & 请求健康时间线 (Heatmap + Success/Fail stats)
"""

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QFileSystemWatcher
from pathlib import Path

import analytics
from dashboard_widgets import (
    DailyAvgCardWidget, StandardCardWidget, HeatmapGridWidget,
    HeatmapLegendWidget, ModelUsageListWidget
)


class DataLoadWorker(QThread):
    loaded = pyqtSignal(dict)

    def __init__(self, filter_mode="year", parent=None):
        super().__init__(parent)
        self.filter_mode = filter_mode

    def run(self):
        data = analytics.parse_session_records(filter_mode=self.filter_mode)
        self.loaded.emit(data)


class ModernDashboardTab(QtWidgets.QWidget):
    """Full-featured modern analytics dashboard view."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dashboardTab")
        self.current_filter = "year"
        self.worker = None
        self._reload_pending = False
        self._loading = False
        self._shimmer_cards = ()
        self._shimmer_timer = QtCore.QTimer(self)
        self._shimmer_timer.setInterval(33)
        self._shimmer_timer.timeout.connect(self._advance_shimmers)
        self._build_ui()
        self._setup_auto_watcher()
        self.load_data()

    def _setup_auto_watcher(self):
        """监听 ~/.pi/agent/sessions 目录变动，会话更新时自动防抖刷新看板。"""
        sessions_dir = Path.home() / ".pi" / "agent" / "sessions"
        if sessions_dir.exists():
            self._watcher = QFileSystemWatcher(self)
            self._watcher.addPath(str(sessions_dir))
            # 防抖定时器（500ms 内多次写入只触发一次刷新）
            self._debounce_timer = QtCore.QTimer(self)
            self._debounce_timer.setSingleShot(True)
            self._debounce_timer.setInterval(600)
            self._debounce_timer.timeout.connect(self.load_data)
            self._watcher.directoryChanged.connect(lambda _: self._debounce_timer.start())

    def _build_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(18, 14, 18, 14)
        main_layout.setSpacing(14)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        content_widget = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 4, 0)
        content_layout.setSpacing(14)

        # -------------------------------------------------------------
        # Row 1: Top 3 Cards
        # -------------------------------------------------------------
        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(14)

        # Card 1: 每日平均
        self.card_daily = DailyAvgCardWidget(self)
        self.card_daily.setMinimumHeight(140)
        row1.addWidget(self.card_daily, 3)

        # Card 2: 请求总数
        self.card_requests = StandardCardWidget(
            title="请求总数",
            icon_char="📞",
            accent_color="#3b82f6",
            parent=self
        )
        self.card_requests.setMinimumHeight(140)
        row1.addWidget(self.card_requests, 4)

        # Card 3: Token 总数
        self.card_tokens = StandardCardWidget(
            title="Token 总数",
            icon_char="◇",
            accent_color="#8b5cf6",
            parent=self
        )
        self.card_tokens.setMinimumHeight(140)
        row1.addWidget(self.card_tokens, 4)

        content_layout.addLayout(row1)

        # -------------------------------------------------------------
        # Row 2: Middle 4 Cards (RPM, TPM, 缓存率, 总成本)
        # -------------------------------------------------------------
        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(14)

        self.card_rpm = StandardCardWidget(title="RPM", icon_char="⏱", accent_color="#10b981", parent=self)
        self.card_tpm = StandardCardWidget(title="TPM", icon_char="📈", accent_color="#f97316", parent=self)
        self.card_cache = StandardCardWidget(title="缓存率", icon_char="%", accent_color="#06b6d4", parent=self)
        self.card_cost = StandardCardWidget(title="总成本", icon_char="$", accent_color="#f59e0b", parent=self)
        for _c in (self.card_rpm, self.card_tpm, self.card_cache, self.card_cost):
            _c.setMinimumHeight(140)

        row2.addWidget(self.card_rpm, 1)
        row2.addWidget(self.card_tpm, 1)
        row2.addWidget(self.card_cache, 1)
        row2.addWidget(self.card_cost, 1)

        content_layout.addLayout(row2)

        # -------------------------------------------------------------
        # Row 3: Section Title + Date Range + [ 日 | 周 | 月 | 年 ] Filter Buttons
        # -------------------------------------------------------------
        filter_bar = QtWidgets.QHBoxLayout()
        filter_bar.setContentsMargins(4, 8, 4, 0)
        filter_bar.setSpacing(12)

        sec_title = QtWidgets.QLabel("最近活动")
        sec_title.setObjectName("sectionHeaderTitle")
        filter_bar.addWidget(sec_title)

        filter_bar.addStretch(1)

        self.lbl_vision_summary = QtWidgets.QLabel("视觉: 0 调用 · 0 缓存")
        self.lbl_vision_summary.setObjectName("dateRangeLabel")
        self.lbl_vision_summary.setToolTip("Vision Bridge 嵌套调用、会话缓存命中与平均延迟")
        filter_bar.addWidget(self.lbl_vision_summary)

        self.lbl_date_range = QtWidgets.QLabel("00/00 00:00 - 00/00 00:00")
        self.lbl_date_range.setObjectName("dateRangeLabel")
        filter_bar.addWidget(self.lbl_date_range)

        # Filter buttons container
        btn_box = QtWidgets.QFrame()
        btn_box.setObjectName("segmentedFilterBox")
        btn_box_lay = QtWidgets.QHBoxLayout(btn_box)
        btn_box_lay.setContentsMargins(3, 3, 3, 3)
        btn_box_lay.setSpacing(2)

        self.filter_buttons = {}
        modes = [("day", "日"), ("week", "周"), ("month", "月"), ("year", "年")]
        for m_key, m_lbl in modes:
            btn = QtWidgets.QPushButton(m_lbl)
            btn.setCheckable(True)
            btn.setObjectName("filterSegmentBtn")
            btn.setCursor(Qt.PointingHandCursor)
            if m_key == self.current_filter:
                btn.setChecked(True)
            btn.clicked.connect(lambda _=False, k=m_key: self._on_filter_changed(k))
            btn_box_lay.addWidget(btn)
            self.filter_buttons[m_key] = btn

        filter_bar.addWidget(btn_box)

        self.btn_refresh = QtWidgets.QPushButton("🔄 刷新")
        self.btn_refresh.setObjectName("filterRefreshBtn")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.load_data)
        filter_bar.addWidget(self.btn_refresh)

        content_layout.addLayout(filter_bar)

        # -------------------------------------------------------------
        # Row 4: Bottom Content (Left: Models List, Right: 2 Heatmaps)
        # -------------------------------------------------------------
        bottom_box = QtWidgets.QHBoxLayout()
        bottom_box.setSpacing(14)

        # ====== LEFT BOX: Model Breakdown ======
        left_frame = QtWidgets.QFrame()
        left_frame.setObjectName("kpiCard")
        left_layout = QtWidgets.QVBoxLayout(left_frame)
        left_layout.setContentsMargins(18, 16, 18, 16)
        left_layout.setSpacing(10)

        left_title_row = QtWidgets.QHBoxLayout()
        left_title = QtWidgets.QLabel("📌 各模型 Token 消耗分布")
        left_title.setObjectName("cardTitle")
        left_title_row.addWidget(left_title)
        left_title_row.addStretch(1)

        self.lbl_model_count = QtWidgets.QLabel("0 个模型")
        self.lbl_model_count.setObjectName("cardSubInfo")
        left_title_row.addWidget(self.lbl_model_count)
        left_layout.addLayout(left_title_row)

        model_scroll = QtWidgets.QScrollArea()
        model_scroll.setWidgetResizable(True)
        model_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        model_scroll.setStyleSheet("background: transparent;")
        self.model_list_widget = ModelUsageListWidget()
        model_scroll.setWidget(self.model_list_widget)
        left_layout.addWidget(model_scroll)

        bottom_box.addWidget(left_frame, 4)

        # ====== RIGHT BOX: Activity Heatmaps ======
        right_frame = QtWidgets.QFrame()
        right_frame.setObjectName("kpiCard")
        right_layout = QtWidgets.QVBoxLayout(right_frame)
        right_layout.setContentsMargins(18, 16, 18, 16)
        right_layout.setSpacing(12)

        # Activity 1: Token 活动
        act1_header = QtWidgets.QHBoxLayout()
        act1_left_box = QtWidgets.QVBoxLayout()
        act1_left_box.setSpacing(2)
        act1_title = QtWidgets.QLabel("Token 活动")
        act1_title.setObjectName("cardTitle")
        act1_sub = QtWidgets.QLabel("展示所选活动窗口内的 Token 用量分布。")
        act1_sub.setObjectName("cardSubInfo")
        act1_left_box.addWidget(act1_title)
        act1_left_box.addWidget(act1_sub)
        act1_header.addLayout(act1_left_box)

        act1_header.addStretch(1)

        act1_right_box = QtWidgets.QVBoxLayout()
        act1_right_box.setSpacing(2)
        act1_right_box.setAlignment(Qt.AlignRight)
        self.lbl_token_badge_val = QtWidgets.QLabel("0 Tokens")
        self.lbl_token_badge_val.setStyleSheet("font-size: 15px; font-weight: 800; color: #3b82f6;")
        self.lbl_token_badge_sub = QtWidgets.QLabel("输入: 0  输出: 0")
        self.lbl_token_badge_sub.setObjectName("cardSubInfo")
        act1_right_box.addWidget(self.lbl_token_badge_val, 0, Qt.AlignRight)
        act1_right_box.addWidget(self.lbl_token_badge_sub, 0, Qt.AlignRight)
        act1_header.addLayout(act1_right_box)

        right_layout.addLayout(act1_header)

        self.heatmap_tokens = HeatmapGridWidget(mode="tokens", parent=self)
        right_layout.addWidget(self.heatmap_tokens)

        # Legend for tokens (Vector colored boxes)
        self.legend_tokens = HeatmapLegendWidget(mode="tokens", parent=self)
        right_layout.addWidget(self.legend_tokens)

        right_layout.addSpacing(8)

        # Activity 2: 请求健康时间线
        act2_header = QtWidgets.QHBoxLayout()
        act2_left_box = QtWidgets.QVBoxLayout()
        act2_left_box.setSpacing(2)
        act2_title = QtWidgets.QLabel("请求健康时间线")
        act2_title.setObjectName("cardTitle")
        act2_sub = QtWidgets.QLabel("展示所选活动窗口内的请求成功与失败分布。")
        act2_sub.setObjectName("cardSubInfo")
        act2_left_box.addWidget(act2_title)
        act2_left_box.addWidget(act2_sub)
        act2_header.addLayout(act2_left_box)

        act2_header.addStretch(1)

        act2_right_box = QtWidgets.QVBoxLayout()
        act2_right_box.setSpacing(2)
        act2_right_box.setAlignment(Qt.AlignRight)
        self.lbl_health_badge_val = QtWidgets.QLabel("100%")
        self.lbl_health_badge_val.setStyleSheet("font-size: 15px; font-weight: 800; color: #10b981;")
        self.lbl_health_badge_sub = QtWidgets.QLabel("● 0  ■ 0")
        self.lbl_health_badge_sub.setObjectName("cardSubInfo")
        act2_right_box.addWidget(self.lbl_health_badge_val, 0, Qt.AlignRight)
        act2_right_box.addWidget(self.lbl_health_badge_sub, 0, Qt.AlignRight)
        act2_header.addLayout(act2_right_box)

        right_layout.addLayout(act2_header)

        self.heatmap_health = HeatmapGridWidget(mode="health", parent=self)
        right_layout.addWidget(self.heatmap_health)

        # Legend for health (Vector colored boxes)
        self.legend_health = HeatmapLegendWidget(mode="health", parent=self)
        right_layout.addWidget(self.legend_health)

        bottom_box.addWidget(right_frame, 5)
        content_layout.addLayout(bottom_box)

        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)

    def _on_filter_changed(self, mode):
        self.current_filter = mode
        for k, btn in self.filter_buttons.items():
            btn.setChecked(k == mode)
        self.load_data()

    def load_data(self):
        # 合并刷新请求：目录监听、手动刷新和筛选切换不会堆积后台线程。
        if self.worker is not None and self.worker.isRunning():
            self._reload_pending = True
            return

        self._reload_pending = False
        self._loading = True
        self.btn_refresh.setEnabled(False)
        loading_cards = (self.card_daily, self.card_requests, self.card_tokens,
                         self.card_rpm, self.card_tpm, self.card_cache, self.card_cost)
        self._shimmer_cards = loading_cards
        self.card_daily.start_shimmer()
        self.card_daily.val_req.setText("—")
        self.card_daily.val_tok.setText("—")
        self.card_daily.val_cost.setText("—")
        for _card in loading_cards[1:]:
            _card.start_shimmer()
            _card.lbl_value.setText("—")
            _card.lbl_sub.setText("加载中...")
            _card.spark.set_data([])
        # 每次加载只保留一个动画定时器，减少多个卡片定时器同时唤醒主线程。
        for _card in loading_cards:
            timer = getattr(_card, "_shimmer_timer", None)
            if timer is not None and timer.isActive():
                timer.stop()
        if not self._shimmer_timer.isActive():
            self._shimmer_timer.start()
        self.lbl_date_range.setText("加载中...")
        self.lbl_vision_summary.setText("视觉: 加载中...")
        self.lbl_model_count.setText("—")
        self.lbl_token_badge_val.setText("—")
        self.lbl_token_badge_sub.setText("加载中...")
        self.lbl_health_badge_val.setText("—")
        self.lbl_health_badge_sub.setText("加载中...")
        worker = DataLoadWorker(filter_mode=self.current_filter, parent=self)
        self.worker = worker
        worker.loaded.connect(
            lambda data, source=worker: self._on_data_loaded(data, source)
        )
        worker.finished.connect(
            lambda source=worker: self._on_worker_finished(source)
        )
        worker.start()

    def _advance_shimmers(self):
        for card in self._shimmer_cards:
            if getattr(card, "_shimmering", False):
                card._on_shimmer_step()

    def _on_worker_finished(self, worker):
        # 旧线程的 queued finished 信号不能清理当前正在运行的新线程。
        if worker is not self.worker:
            worker.deleteLater()
            return
        self.worker = None
        self._loading = False
        self._shimmer_timer.stop()
        for card in self._shimmer_cards:
            card.stop_shimmer()
        self._shimmer_cards = ()
        if worker is not None:
            worker.deleteLater()

        if self._reload_pending:
            self._reload_pending = False
            QtCore.QTimer.singleShot(0, self.load_data)
        else:
            self.btn_refresh.setEnabled(True)

    def _apply_theme_to_children(self, c):
        """传递主题调色板至所有看板子组件。"""
        self.heatmap_tokens.set_theme_colors(c)
        self.heatmap_health.set_theme_colors(c)
        self.legend_tokens.set_theme_colors(c)
        self.legend_health.set_theme_colors(c)
        self.model_list_widget.set_theme_colors(c)

    def _on_data_loaded(self, data, worker=None):
        if worker is not None and worker is not self.worker:
            return
        # 批量更新看板控件，避免每个 QLabel/图表更新都触发一次重绘。
        self.setUpdatesEnabled(False)
        try:
            self._apply_data_loaded(data)
        finally:
            self.setUpdatesEnabled(True)
            self.update()

    def _apply_data_loaded(self, data):
        fmt = analytics.format_number_compact

        # 1. 每日平均 (Card 1)
        self.card_daily.update_data(
            days_span=data.get("active_days_span", 1),
            avg_calls=data.get("avg_calls", 0.0),
            avg_tokens_str=fmt(data.get("avg_tokens", 0.0)),
            avg_cost=data.get("avg_cost", 0.0)
        )

        # 2. 请求总数 (Card 2)
        tot_calls = data.get("total_calls", 0)
        succ_calls = data.get("success_calls", 0)
        fail_calls = data.get("failed_calls", 0)
        rate = data.get("success_rate", 100.0)
        self.card_requests.update_data(
            value_str=f"{tot_calls:,}",
            sub_info=f"● 成功: {succ_calls}  ▲ 失败: {fail_calls}  成功率: {rate:.2f}%",
            spark_data=data.get("daily_trend_calls", [])[-14:]
        )

        # 3. Token 总数 (Card 3)
        tot_tokens = data.get("total_tokens", 0)
        tot_cr = data.get("total_cache_read", 0)
        tot_cw = data.get("total_cache_write", 0)
        tot_rea = data.get("total_reasoning", 0)
        self.card_tokens.update_data(
            value_str=fmt(tot_tokens),
            sub_info=f"缓存读取: {fmt(tot_cr)}  缓存写入: {fmt(tot_cw)}  推理: {fmt(tot_rea)}",
            spark_data=data.get("daily_trend_tokens", [])[-14:]
        )

        # 4. RPM (Card 4)
        self.card_rpm.update_data(
            value_str=f"{data.get('rpm', 0.0):.2f}",
            sub_info=f"请求总数: {tot_calls:,}",
            spark_data=data.get("daily_trend_calls", [])[-14:]
        )

        # 5. TPM (Card 5)
        self.card_tpm.update_data(
            value_str=f"{data.get('tpm', 0.0):,.0f}",
            sub_info=f"Token 总数: {fmt(tot_tokens)}",
            spark_data=data.get("daily_trend_tokens", [])[-14:]
        )

        # 6. 缓存率 (Card 6)
        tot_in = data.get("total_input", 0)
        self.card_cache.update_data(
            value_str=f"{data.get('cache_rate', 0.0):.2f}%",
            sub_info=f"缓存读取: {fmt(tot_cr)}  输入: {fmt(tot_in)}",
            spark_data=data.get("daily_trend_cache", [])[-14:]
        )

        # 7. 总成本 (Card 7)
        self.card_cost.update_data(
            value_str=f"${data.get('total_cost', 0.0):.2f}",
            sub_info=f"Token 总数: {fmt(tot_tokens)}  ·  成本按 api-switcher.json 的 priceRates 估算",
            spark_data=data.get("daily_trend_tokens", [])[-14:]
        )

        # Filter Bar Date Range + Vision Bridge nested-call telemetry
        self.lbl_date_range.setText(data.get("date_range_str", ""))
        vision_calls = data.get("vision_calls", 0)
        vision_hits = data.get("vision_cache_hits", 0)
        vision_failures = data.get("vision_failures", 0)
        vision_latency = data.get("vision_avg_latency_ms", 0.0)
        self.lbl_vision_summary.setText(
            f"视觉: {vision_calls} 调用 · {vision_hits} 缓存 · {vision_latency:.0f}ms"
        )
        self.lbl_vision_summary.setToolTip(
            f"成功: {data.get('vision_success', 0)}\n"
            f"失败/回退: {vision_failures}\n"
            f"会话缓存命中: {vision_hits}\n"
            f"处理图片: {data.get('vision_image_count', 0)} 张\n"
            f"图片数据: {analytics.format_number_compact(data.get('vision_image_bytes', 0))}B"
        )

        # Bottom Left: Model List
        models_dict = data.get("models", {})
        self.lbl_model_count.setText(f"共 {len(models_dict)} 个模型")
        self.model_list_widget.update_models(models_dict, tot_tokens)

        # Bottom Right: Token Heatmap
        tot_out = data.get("total_output", 0)
        self.lbl_token_badge_val.setText(fmt(tot_tokens))
        self.lbl_token_badge_sub.setText(f"输入: {fmt(tot_in)}  输出: {fmt(tot_out)}")
        self.heatmap_tokens.set_data(data.get("heatmap_tokens", []))

        # Bottom Right: Health Heatmap
        self.lbl_health_badge_val.setText(f"{rate:.1f}%")
        self.lbl_health_badge_sub.setText(f"● 成功 {succ_calls}  ■ 失败 {fail_calls}")
        self.heatmap_health.set_data(data.get("heatmap_health", []))

    def closeEvent(self, event):
        """关闭看板前回收分析线程，避免 Qt 销毁运行中的 QThread。"""
        debounce_timer = getattr(self, "_debounce_timer", None)
        if debounce_timer is not None and debounce_timer.isActive():
            debounce_timer.stop()
        if self._shimmer_timer.isActive():
            self._shimmer_timer.stop()
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(2000)
        super().closeEvent(event)
