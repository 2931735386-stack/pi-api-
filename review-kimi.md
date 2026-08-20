# pi-api-switcher 代码审查报告

## 一、 功能问题

### 1. 数据一致性与边界情况（高优先级）
- **问题**：`ConfigStore.remove_provider()` 方法（`App.py` 第108行）在删除 provider 时，仅移除了 `models.json` 和 `auth.json` 中的数据，但**未检查 `settings.json` 中的 `defaultProvider` 和 `enabledModels` 字段**。
- **风险**：如果被删除的 provider 是当前默认 provider，那么 `settings.json` 中的 `defaultProvider` 字段将指向一个不存在的 provider，导致下次启动 `pi` 时配置错误或行为未定义。同样，`enabledModels` 列表中可能残留属于已删除 provider 的模型 ID。
- **建议**：在 `remove_provider` 中增加逻辑：
  ```python
  def remove_provider(self, name):
      # ... 现有删除逻辑 ...
      # 清理悬空默认值
      if self.settings.get("defaultProvider") == name:
          self.settings["defaultProvider"] = ""
          self.settings["defaultModel"] = ""
      # 清理enabledModels中属于该provider的模型（需先获取其模型ID列表）
      # 注意：需要先从models字典中获取模型列表，或维护一个provider->models的映射
  ```

### 2. 文件读写原子性与异常处理（高优先级）
- **问题**：`write_json()` 函数（`App.py` 第57行）在写入失败时仅返回 `False`，且 `save()` 方法（`App.py` 第90行）直接调用它。如果写入过程中程序崩溃或磁盘已满，**可能导致 JSON 文件被清空或写入不完整**，造成数据永久丢失。
- **风险**：数据损坏。
- **建议**：实现原子写入，先写入临时文件，成功后再替换原文件：
  ```python
  def write_json(path: Path, data):
      tmp_path = path.with_suffix('.tmp')
      try:
          tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
          tmp_path.replace(path)  # 原子操作
          return True
      except Exception as e:
          # 可以考虑记录日志
          tmp_path.unlink(missing_ok=True)
          return False
  ```

### 3. 线程安全与资源管理（中优先级）
- **问题**：`MainWindow.on_test()` 方法（`App.py` 第210行）在子线程中执行 `test_endpoint`，并通过 `invokeMethod` 更新 UI。`invokeMethod` 本身是线程安全的，但**未处理窗口可能在测试期间被关闭的情况**。如果用户在测试过程中点击关闭，回调函数 `_on_test_done` 可能会尝试操作一个已不存在的窗口对象。
- **建议**：为窗口增加一个 `_is_closed` 标志，或在 `_on_test_done` 回调中先检查窗口有效性。更优雅的方式是使用 `QTimer.singleShot(0, lambda: self._on_test_done(...))` 在子线程中直接调度到主线程队列，与 `invokeMethod` 效果类似但更 Pythonic。同时，`test_endpoint` 中的 `urllib.request` 调用在异常时可能泄漏连接，建议使用 `with` 语句管理 `urllib.request.urlopen` 的响应。

### 4. 托盘菜单动态更新（低优先级）
- **问题**：`TrayApp._build_menu()` 方法（`App.py` 第246行）在每次设置默认值时被调用，但**仅更新菜单文本，未处理窗口主界面操作（如增删 provider）后菜单的同步**。如果在主窗口删除了某个 provider，托盘菜单不会立即更新，直到下一次触发构建。
- **建议**：在 `MainWindow` 的增删操作后，主动调用 `tray._build_menu()` 或通过信号通知托盘图标更新。

### 5. lambda 闭包陷阱（低优先级）
- **问题**：`TrayApp._build_menu()` 中（`App.py` 第254行），`sub.addAction(...)` 的触发器使用了 lambda。在循环中，`name` 和 `model_id` 变量会被闭包捕获，但由于它们在循环中不变，这里实际没有问题。**但这是个潜在风险**，如果循环变量名变化，可能导致所有菜单项指向最后一个 `name`。
- **建议**：明确使用默认参数来捕获当前值：`lambda checked=False, n=name, m=model_id: self._set_default(n, m)`。

## 二、 美观问题

### 1. 空状态与加载态（高优先级）
- **问题**：当没有选择任何 provider 时，右侧详情区仅显示“未选择供应商”，缺乏引导性。连通性测试时，状态栏文字变化不够醒目。
- **建议**：
  - **空状态**：在右侧内容区中心位置添加一个大号图标（如空文件夹或加号）和一行引导文字，如“← 从左侧选择或添加供应商”。
  - **加载态**：`on_test` 方法中，除了禁用按钮和更新状态文字，可考虑在状态栏旁添加一个小型 `QProgressBar`（不确定进度模式），或让状态文字旁出现一个动态的省略号动画（使用 `QTimer` 实现）。

### 2. 交互反馈细节（中优先级）
- **问题**：按钮的点击反馈不够明确。当前只有悬停变色效果。选中的列表项仅颜色变化，缺乏过渡。
- **建议**：
  - 为所有 `QPushButton` 添加 `:pressed` 状态样式，例如背景色变深 `background: {c['panel']};`。
  - 为 `QListWidget` 的选中项添加轻微的 `border-left` 或 `margin-left` 动画效果，或使用 `QPropertyAnimation` 实现平滑的颜色过渡。

### 3. 表单布局与对齐（中优先级）
- **问题**：`QGridLayout` 中的标签和输入框对齐不够精确。`QCheckBox` 的标签“支持推理”与上方输入框基线对齐不齐。
- **建议**：
  - 为所有 `QLabel` 设置固定的 `setFixedWidth`，确保标签列对齐。
  - 调整 `QCheckBox` 的 `layout` 或使用 `QHBoxLayout` 包裹，使其与输入框垂直对齐更好。可为 `QCheckBox` 设置 `margin-top` 或调整 `QGridLayout` 的行间距。

### 4. API Key 输入体验（中优先级）
- **问题**：`ed_apikey` 是一个密码框，但用户无法临时查看输入内容进行核对。
- **建议**：在密码输入框右侧添加一个“👁️”图标按钮，点击可切换 `QLineEdit.EchoMode` 在 `Password` 和 `Normal` 之间切换。这能显著提升用户体验。

### 5. 字体与层级感（低优先级）
- **问题**：当前全局字体为系统默认。标题、标签、按钮的字号差异不够大，层级感可以更强。
- **建议**：在样式表中更精细地控制字体：
  - `#sidebarTitle`: `font-size: 16px;`
  - `#detailTitle`: `font-size: 22px;`
  - 所有 `QLabel`（非标题类）: `font-size: 13px;`
  - `QPushButton`: `font-size: 14px;`
  - 状态栏: `font-size: 12px;`

## 三、 其他风险

### 1. API Key 明文存储与显示（高风险）
- **问题**：API Key 以明文形式存储在 `auth.json` 和 `models.json` 的 `apiKey` 字段中，并以明文显示在 `ed_apikey` 输入框中。这存在严重的安全隐患，一旦配置文件被泄露或截屏，密钥将暴露。
- **建议**：
  - **存储**：考虑使用操作系统提供的密钥链（如 `keyring` 库）进行安全存储。至少，在 `models.json` 中不应重复存储明文 `apiKey`（当前 `set_api_key` 方法同时写入了两个文件）。
  - **显示**：默认以密码模式显示。添加“显示/隐藏”切换按钮（见美观问题第4点）。

### 2. 输入验证缺失（中风险）
- **问题**：`on_save` 方法（`App.py` 第184行）中，对 `baseUrl`、`model_id` 等字段未做格式验证。用户可以保存一个无效的 URL（如“abc”）或空的 model_id。
- **建议**：在保存前进行基本验证：
  - `baseUrl` 应该以 `http://` 或 `https://` 开头。
  - `model_id` 不应为空。
  - 可以使用正则表达式进行更严格的校验，并给出友好的错误提示。

### 3. 异常处理过于宽泛（中风险）
- **问题**：`read_json` 和 `write_json` 函数使用了 `except Exception`，这会捕获所有异常，包括 `KeyboardInterrupt`、`SystemExit` 等不应被静默处理的异常，可能掩盖真正的 bug。
- **建议**：将 `except Exception` 改为 `except (OSError, ValueError, json.JSONDecodeError)`，只捕获文件 I/O 和 JSON 解析相关的预期异常。对于其他异常，应该让其上抛以便排查问题。

### 4. 依赖风险（低风险）
- **问题**：`generate_icon_ico` 函数（`App.py` 第120行）依赖 `Pillow` 库，但未在文档中明确声明。如果运行环境没有安装 `Pillow`，图标生成会静默失败，导致程序使用空白图标。
- **建议**：在 `requirements.txt` 或文档中明确依赖。或在 `generate_icon_ico` 中添加提示，引导用户安装依赖，或提供一个回退的纯色图标方案。

### 5. 多模型支持不完整（低风险）
- **问题**：整个 UI 设计主要围绕 **单个模型** 的 provider 进行编辑（`on_select` 只取 `models[0]`，`on_save` 也只操作 `models[0]`）。但数据模型 `models.json` 的 `providers` 中 `models` 是一个数组，支持多个模型。
- **建议**：如果计划支持多模型，需要重构 UI 为模型列表。如果当前设计就是单模型，那么 `models` 字段可以简化为一个对象，并在 `add_provider` 等方法中体现，避免逻辑混乱。