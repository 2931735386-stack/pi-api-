# pi-api-switcher

CC Switch 风格的 pi API/模型配置桌面管理器（PyQt5）。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![PyQt5](https://img.shields.io/badge/GUI-PyQt5-green.svg)](https://riverbankcomputing.com/software/pyqt)

管理 pi 的 `~/.pi/agent/` 三个配置文件，可视化增删改中转端点（deepseek/glm/kimi/grok 等），一键切换默认模型，支持连通性测试和系统托盘常驻。

![preview](icon_preview.png)

## 功能

- **切换激活模型**：把某个 provider/model 设为默认，写回 `settings.json`，pi 下次启动即用
- **用量统计与监控看板**：全新现代微拟态卡片风格，自动分析 `~/.pi/agent/sessions/`，展示各模型 Token 占比、Prompt Cache 命中率、平滑趋势曲线、70 天 GitHub 风格活动矩阵及请求健康时间线，支持热力图悬停 Tooltip 详情
- **会话实时监听**：自动监听 sessions 目录变动，终端使用 pi 产生问答后看板自动防抖刷新，无需手动点击
- **增删改 provider 与即时搜索**：侧边栏支持按供应商名、BaseURL 及模型名称实时关键字过滤
- **并发批量测速与状态呼吸灯**：一键并发测试全部端点连通性，侧边栏直观显示延迟及状态指示点（🟢 <600ms / 🟡 >600ms / 🔴 超时）
- **操作反馈与 Toast 胶囊**：设为默认、保存配置、切换主题均带有顶部平滑淡入淡出的 Toast 胶囊提示
- **多主题支持**：Modern Light (现代微拟态) / Terminal / Codex / Claude Code / DeepSeek / 青绿+靛蓝 / GitHub Night / 浅色
- **多模型管理**：每个 provider 可配置多个模型，支持批量导入
- **上下文窗口配置**：可视化查看/编辑每个模型的 `contextWindow`（最大上下文）与 `maxTokens`（最大输出）
- **视觉模型（视觉桥接）**：纯文本模型可挂接一个支持图像的模型；安装 Vision Bridge 扩展后，图片会先被该模型转写，再交给主模型

## 安装

### 方式 1：直接运行 exe（推荐）

从 [Releases](https://github.com/2931735386-stack/pi-api-/releases) 下载最新 exe，双击即用。

### 方式 2：从源码运行

```bash
# 克隆仓库
git clone https://github.com/2931735386-stack/pi-api-.git
cd pi-api-switcher

# 安装依赖
pip install -r requirements.txt

# 运行
python app.py
```

## 打包成 exe

```bash
build.bat
# 或手动：
pip install pyinstaller
python -m PyInstaller --noconsole --onefile --name "pi-api-switcher" --icon=icon.ico app.py
```

输出：`dist/pi-api-switcher.exe`（双击即用，无需 Python 环境）

## 配置文件

| 文件 | 作用 |
|------|------|
| `~/.pi/agent/models.json` | providers 段（baseUrl / api / models / compat / contextWindow / visionModel） |
| `~/.pi/agent/auth.json` | apiKey（provider 名 → {type, key}） |
| `~/.pi/agent/settings.json` | defaultProvider / defaultModel / enabledModels |
| `~/.pi/agent/api-switcher.json` | 应用自身配置（主题 / 字体 / 字号 / 价格费率） |

## 成本估算配置

看板上的“总成本”与“平均费用”默认按输入 $1.50 / 输出 $2.00 / 缓存读 $0.30（每 1M Tokens）估算。可在 `~/.pi/agent/api-switcher.json` 中通过 `priceRates` 字段自定义费率（单位：美元 / 1M Tokens）：

```json
{
  "theme": "terminal",
  "priceRates": {
    "input": 1.50,
    "output": 2.00,
    "cacheRead": 0.30
  }
}
```

未配置时自动回退到默认费率。

## 说明

- 修改会**立即落盘**，pi 下次启动生效；部分修改需要 pi 里 `/reload`。
- **运行时要求**：`visionModel` 是 switcher 与 `vision-bridge.ts` 扩展之间的配置约定，并非 pi 内置字段。未安装扩展时，pi 不会自动转发图片。
- **最大上下文**：模型表格中的“上下文”列对应 pi 配置里的 `contextWindow`，可直接查看/编辑每个模型支持的最大上下文长度。
- **视觉桥接**：当某个模型的输入类型为纯文本（`input: ["text"]`）时，可在“视觉模型”列点击“＋ 添加视觉”，从所有支持图像输入的模型中选择桥接模型（存储为模型的 `visionModel` 字段）。安装 `~/.pi/agent/extensions/vision-bridge.ts` 后，pi 收到图片会先调用桥接模型生成图像转写，随后仅将原始文本和转写交给主模型；若主模型自身已支持图片（`input: ["text", "image"]`），则直接发送图片，不经过桥接。
- apiKey 显示为掩码，不会明文泄露（但编辑框内可查看/修改完整 key）。
- 首次运行会在目录下自动生成 `icon.ico`。

## 开发

```bash
# 安装开发依赖
pip install -r requirements.txt

# 运行
python app.py

# 打包
build.bat
```

## 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件。
