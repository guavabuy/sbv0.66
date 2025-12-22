from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# 兼容两种启动方式：
# 1) python3 -m apps.main（推荐）
# 2) python3 apps/main.py（直接跑脚本时需要把项目根目录加入 sys.path）
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import SecondBrain


def _special_commands(text: str) -> Optional[str]:
    """
    纯 CLI 交互层的小命令（不涉及业务数据/隐私判断/工具实现）。
    """
    t = (text or "").strip().lower()
    if t in ("q", "quit", "exit"):
        return "__quit__"
    return None


def main() -> None:
    """
    CLI 入口（固定 mode=self）。
    只负责收发与异常提示，不拼 prompt、不读数据文件、不做工具逻辑。
    """
    print(">>> Second Brain (apps/main.py) 已启动。输入 q/quit 退出。")

    # 可用环境变量控制（仅 UI 层参数）
    max_turns = int(os.getenv("CLI_MAX_TURNS", "20"))
    enable_tools = (os.getenv("CLI_ENABLE_TOOLS", "1").strip() in ("1", "true", "yes", "y", "on"))

    sb = SecondBrain(mode="self", max_turns=max_turns, enable_tools=enable_tools)

    while True:
        try:
            user_input = input("\nUser: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return

        if not user_input:
            continue

        mapped = _special_commands(user_input)
        if mapped == "__quit__":
            print("Bye.")
            return
        if isinstance(mapped, str):
            user_input = mapped

        try:
            reply = sb.answer(user_input)
        except Exception as e:
            # 入口层只做友好提示，避免崩溃
            print(f"\n[Error] {e}")
            continue

        print(f"\nSecond Brain:\n{reply}")


if __name__ == "__main__":
    main()


