# pi-api-switcher

CC Switch 风格的 pi API/模型配置桌面管理器（PyQt5）。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![PyQt5](https://img.shields.io/badge/GUI-PyQt5-green.svg)](https://riverbankcomputing.com/software/pyqt)

管理 pi 的 `~/.pi/agent/` 模型、认证、默认模型、缓存兼容和视觉路由配置，可视化增删改中转端点（DeepSeek/GLM/Kimi/GPT 等），一键切换默认模型，支持连通性测试和系统托盘常驻。

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
- **Vision Bridge v2**：支持自动/原生/强制/关闭四种模式、有序多视觉模型回退、失败熔断、图片限制、任务自适应 OCR/图表/UI 提示、不可信视觉数据边界和会话级 LRU 去重
- **缓存兼容防护**：区分 OpenAI 请求格式与 OpenAI 专有缓存能力；第三方端点默认剥离不支持的 `prompt_cache_key` / `prompt_cache_retention`，避免严格代理返回 HTTP 400

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
python -m PyInstaller --clean --noconfirm pi-api-switcher.spec
```

输出：`dist/pi-api-switcher.exe`（双击即用，无需 Python 环境）

## 配置文件

| 文件 | 作用 |
|------|------|
| `~/.pi/agent/models.json` | providers 段（baseUrl / api / models / compat / contextWindow / visionModel） |
| `~/.pi/agent/auth.json` | apiKey（provider 名 → {type, key}） |
| `~/.pi/agent/settings.json` | defaultProvider / defaultModel / enabledModels |
| `~/.pi/agent/api-switcher.json` | 应用自身配置（主题 / 字体 / 字号 / 价格费率） |
| `~/.pi/agent/cache-compat-guard.json` | 每个 provider/model 的缓存兼容策略 |
| `~/.pi/agent/vision-bridge.json` | Vision Bridge v2 路由、回退链、图片限制、超时和会话缓存配置 |
| `~/.pi/agent/managed/pi-api-switcher-cache-guard/` | Switcher 管理的最终请求缓存防护扩展 |

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

## 缓存兼容策略

每个 provider 可以选择：

| 策略 | 行为 |
|------|------|
| 自动安全（推荐） | 官方 `api.openai.com` 保留长缓存；其他 OpenAI-compatible 端点删除专有缓存 body 字段 |
| 严格兼容 | 删除 `prompt_cache_key`、`prompt_cache_retention` 和常见 session-affinity headers |
| 仅缓存键 | 发送 provider/model/session 范围的不可逆哈希缓存键，但不发送 24h retention |
| 长缓存 | 允许缓存键和 `prompt_cache_retention: "24h"`；仅在端点文档明确支持时启用 |

Switcher 会把 managed Guard 放在 `settings.json` 的 packages 列表末尾，使它在 `pi-cache-optimizer` 之后看到最终请求。启动 Switcher 还会设置用户环境变量 `PI_CACHE_OPTIMIZER_NO_OPENAI_CACHE_KEY=1`，关闭 cache optimizer 对所有兼容端点的宽泛 fallback；明确选择“仅缓存键”或“长缓存”的渠道由 Guard 添加不暴露原始 Pi session id 的哈希键。

修改策略后请重启 Pi，或在 Pi 中执行 `/reload`。可运行 `/cache-compat` 查看当前模型的实际策略。

## Vision Bridge v2

视觉列支持四种模式：

| 模式 | 行为 |
|------|------|
| 自动（推荐） | 主模型原生支持图片时直传；纯文本模型按候选优先级桥接 |
| 原生直传 | 只允许主模型直接处理图片；纯文本模型会明确拒绝图片 |
| 强制桥接 | 即使主模型原生支持图片，也先调用候选视觉模型 |
| 关闭图片 | 移除图片并返回明确提示，不会把图片发给任何模型 |

候选视觉模型支持复选和拖动排序。主候选超时、认证失败或上游错误时，Bridge 会尝试下一候选，并对失败候选进行短期熔断。默认限制为 4 张图、单张 10 MB、总计 20 MB、60 秒超时；同一会话中相同模型/图片/请求使用内存 LRU 去重，不持久保存图片。

图片 OCR 结果被包装在 `[UNTRUSTED_VISION_DATA]` 边界中。图片里的指令、命令、链接或工具请求只作为不可信数据转录，不自动执行。视觉嵌套调用会写入不参与 LLM 上下文的 session custom entry，看板会合并真实 token、调用、回退、缓存命中和延迟统计。

配置示例：

```json
{
  "version": 2,
  "defaults": {
    "mode": "auto",
    "timeoutMs": 60000,
    "cooldownMs": 60000,
    "maxImages": 4,
    "maxImageBytes": 10000000,
    "maxTotalImageBytes": 20000000,
    "maxUserTextChars": 4000,
    "maxDescriptionChars": 8000,
    "sessionCacheEntries": 16
  },
  "routes": {
    "v4flash/deepseek-v4-flash": {
      "mode": "auto",
      "candidates": [
        "gemini/gemini-3.7-flash",
        "gpt/gpt-5.6-terra",
        "gpt/gpt-5.6-sol"
      ]
    }
  }
}
```

诊断命令：

```text
/vision-bridge doctor
/vision-bridge stats
/vision-bridge clear-cache
```

## 说明

- 修改会**立即落盘**，pi 下次启动生效；部分修改需要 pi 里 `/reload`。
- **运行时要求**：`visionModel` / `visionMode` 是旧版回滚兼容字段；v2 运行时以 `vision-bridge.json` 为主。未安装扩展时，pi 不会自动桥接图片。
- **缓存防护**：`cache-compat-guard.json` 是 Switcher 与 managed Guard 的配置约定。未知第三方端点采用 fail-closed 策略；不要仅凭模型名包含 GPT/DeepSeek 就启用 OpenAI 专有缓存字段。
- **最大上下文**：模型表格中的“上下文”列对应 pi 配置里的 `contextWindow`，可直接查看/编辑每个模型支持的最大上下文长度。
- **视觉桥接**：纯文本主模型在自动模式下先调用有序视觉候选链，随后只接收安全边界内的视觉转写，原图从主请求中移除；原生视觉模型默认直接接收图片，也可改为强制桥接。
- apiKey 显示为掩码，不会明文泄露（但编辑框内可查看/修改完整 key）。
- 首次运行会在目录下自动生成 `icon.ico`。

## 开发

```bash
# 安装开发依赖（含测试/打包工具）
pip install -r requirements-dev.txt

# 运行
python app.py

# 运行测试
pytest tests/ -q
node tests/test_cache_guard.mjs   # 扩展运行时测试需从仓库根目录运行
node tests/test_vision_bridge.mjs

# 代码检查
ruff check --select=F *.py tests/

# 打包
build.bat
```

## 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件。
