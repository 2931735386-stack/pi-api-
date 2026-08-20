#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 kimi 审查 pi-api-switcher 的功能与界面美观度。"""
import json
import urllib.request
from pathlib import Path

# 读取 kimi 配置
models = json.loads(Path.home().joinpath(".pi/agent/models.json").read_text(encoding="utf-8"))
auth = json.loads(Path.home().joinpath(".pi/agent/auth.json").read_text(encoding="utf-8"))
k = models["providers"]["kimi-sp"]
BASE = k["baseUrl"].rstrip("/")
MODEL = k["models"][0]["id"]
KEY = auth.get("kimi-sp", {}).get("key", "")

# 读取待审查代码
app_code = Path("app.py").read_text(encoding="utf-8")

prompt = f"""你是一位资深桌面软件 UI/UX 评审专家，也是一位严谨的代码审查者。请审查下面这个 PyQt5 桌面应用「pi-api-switcher」（CC Switch 风格的 API/模型配置管理器），从【功能正确性】和【界面美观度】两个维度给出专业、具体、可执行的改进建议。

请重点审查：
1. 功能正确性：读写 models.json/auth.json/settings.json 的逻辑有无 bug；线程安全（连通性测试用了 threading + invokeMethod 是否安全）；系统托盘逻辑；数据一致性（删除 provider 后 default 是否悬空等边界情况）。
2. 界面美观度：深色主题配色是否协调；布局、间距、字体、按钮层级是否专业；有没有可提升视觉质感的细节（如空状态、loading 态、图标、动效等）。
3. 其他风险：apiKey 明文存储/显示的安全问题、异常处理缺失等。

请用中文输出，分「功能问题」「美观问题」「建议优先级（高/中/低）」三部分，每条要具体到代码位置或 UI 元素，不要空泛。

===== 代码开始 =====
{app_code}
===== 代码结束 =====
"""

payload = {
    "model": MODEL,
    "messages": [
        {"role": "user", "content": prompt}
    ],
    "temperature": 0.3,
}

req = urllib.request.Request(
    BASE + "/chat/completions",
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {KEY}",
        "User-Agent": "pi-api-switcher-review/1.0",
    },
)

print("正在请求 kimi 审查 ...")
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        # 保存到文件
        out = Path("review-kimi.md")
        out.write_text(content, encoding="utf-8")
        print(f"审查完成，结果已保存到 {out}")
        print("=" * 60)
        print(content)
except Exception as e:
    print("请求失败:", e)
