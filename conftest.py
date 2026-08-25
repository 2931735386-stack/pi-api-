# -*- coding: utf-8 -*-
"""pytest 共享配置：把项目根目录加入 sys.path，
使 `pytest` 在任何工作目录下都能直接导入项目模块
（cache_compat / vision_config / analytics ...）。"""

import sys
from pathlib import Path

ROOT = str(Path(__file__).parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
