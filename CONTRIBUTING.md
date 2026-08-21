# 贡献指南

感谢你对 pi-api-switcher 的关注！欢迎提交 Issue 和 Pull Request。

## 🐛 提交 Issue

提交 Bug 报告或功能建议前，请先：

1. 搜索 [已有 Issues](https://github.com/2931735386-stack/pi-api-/issues)，避免重复。
2. 提供清晰标题，正文包含：
   - 复现步骤
   - 期望行为 vs 实际行为
   - 运行环境（Windows 版本、Python 版本、pi 版本）
   - 如有报错，附上完整错误信息

## 🔧 提交 Pull Request

1. Fork 本仓库并克隆到本地。
2. 基于最新 `main` 创建分支：
   ```bash
   git checkout -b fix/your-bugfix
   ```
3. 修改代码，保持提交信息符合 [Conventional Commits](https://www.conventionalcommits.org/) 规范：
   - `feat: 新增 xxx 功能`
   - `fix: 修复 xxx 问题`
   - `docs: 更新文档`
   - `refactor: 重构 xxx`
   - `chore: 杂项维护`
4. 如有功能变更，同步更新 `README.md`。
5. 确保代码风格一致（遵循 `.editorconfig`：4 空格缩进、UTF-8、LF 换行）。
6. 提交 PR 并描述改动内容与动机。

## 💻 本地开发

```bash
git clone https://github.com/2931735386-stack/pi-api-.git
cd pi-api-
pip install -r requirements.txt
python app.py
```

## 📝 代码规范

- Python 代码遵循 [PEP 8](https://peps.python.org/pep-0008/)，缩进 4 空格。
- 文件统一 UTF-8 编码、LF 换行（见 `.editorconfig`）。
- 新增功能尽量保持单文件 `app.py` 的结构，避免过度拆分。
- 不要提交敏感信息（如真实 apiKey）。
