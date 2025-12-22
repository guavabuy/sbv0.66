from __future__ import annotations

from pathlib import Path
from typing import Dict, Literal


BrainMode = Literal["self", "friend"]

# 项目根目录（core/ 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = PROJECT_ROOT / "prompts"

# Card 2：Mode -> Prompt 文件映射（固定关系，改 prompt 内容不需要改代码）
MODE_TO_PROMPT_MD: Dict[BrainMode, str] = {
    "self": "self_reflect.md",
    "friend": "friend_mode.md",
}


