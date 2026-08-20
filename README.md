# pi-api-switcher

CC Switch 风格的 pi API/模型配置桌面管理器（PyQt5）。

管理 pi 的 `~/.pi/agent/` 三个配置文件，可视化增删改中转端点（deepseek/glm/kimi/grok 等），一键切换默认模型，支持连通性测试和系统托盘常驻。

![preview](preview.png)

## 功能

- **切换激活模型**：把某个 provider/model 设为默认，写回 `settings.json`，pi 下次启动即用
- **增删改 provider**：管理 `baseUrl` / `apiKey` / 模型 ID / 显示名 / reasoning
- **连通性测试**：对各端点发 `/models` 请求，显示延迟和状态
- **系统托盘常驻**：右键菜单快速切换默认模型，无需开主窗口
- **多主题支持**：Terminal / Codex / Claude Code / DeepSeek / 青绿+靛蓝 / GitHub Night / 浅色
- **多模型管理**：每个 provider 可配置多个模型，支持批量导入

## 安装

### 方式 1：直接运行 exe（推荐）

从 [Releases](https://github.com/YOUR_USERNAME/pi-api-switcher/releases) 下载最新 exe，双击即用。

### 方式 2：从源码运行

```bash
# 克隆仓库
git clone https://github.com/YOUR_USERNAME/pi-api-switcher.git
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
| `~/.pi/agent/models.json` | providers 段（baseUrl / api / models / compat） |
| `~/.pi/agent/auth.json` | apiKey（provider 名 → {type, key}） |
| `~/.pi/agent/settings.json` | defaultProvider / defaultModel / enabledModels |

## 说明

- 修改会**立即落盘**，pi 下次启动生效；部分修改需要 pi 里 `/reload`。
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
