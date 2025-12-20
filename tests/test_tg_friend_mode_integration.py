import os
import unittest
from unittest.mock import MagicMock, patch

from langchain_core.messages import SystemMessage

import tg_bot


class _Resp:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class TestTgFriendModeIntegration(unittest.TestCase):
    def test_tg_friend_mode_off_keeps_old_behavior(self):
        msgs = [SystemMessage(content="SYS")]
        with patch.dict(os.environ, {"TG_FRIEND_MODE": "0"}, clear=False):
            with patch.object(tg_bot, "llm", MagicMock()) as m_llm:
                m_llm.invoke.return_value = _Resp("OLD_REPLY", tool_calls=None)
                out, meta, extra = tg_bot.generate_tg_reply("hi", msgs)
        self.assertEqual(out, "OLD_REPLY")
        self.assertEqual(meta, {})
        self.assertTrue(extra)  # 至少包含 response
        # DoD：关闭时不应出现 friend_mode 固定句式
        self.assertNotIn("我最近对这件事没有了解。", out)
        self.assertNotIn("我对这件事情的观点是：", out)

    def test_tg_friend_mode_on_uses_templates(self):
        msgs = [SystemMessage(content="SYS")]
        raw = {
            "hits": [
                {"text": "编程进展：我最近在写 tg bot", "score": 0.9},
                {"text": "编程进展：我在做 Python 项目结构优化", "score": 0.9},
                {"text": "编程进展：我在补齐测试", "score": 0.9},
            ]
        }

        with patch.dict(os.environ, {"TG_FRIEND_MODE": "1"}, clear=False):
            with patch.object(tg_bot, "_tg_friend_retrieve_raw", return_value=raw) as m_ret:
                # friend_mode 开启时不应走 llm.invoke
                with patch.object(tg_bot, "llm", MagicMock()) as m_llm:
                    with patch("builtins.print") as m_print:
                        out, meta, extra = tg_bot.generate_tg_reply("编程进展如何", msgs)
                    m_llm.invoke.assert_not_called()
                m_ret.assert_called_once()

        self.assertIn("我对这件事情的观点是：", out)
        # Card9：至少包含这些字段，并且打印了 route=
        for k in ("route", "top_score", "hit_count", "web_search", "used_chunks"):
            self.assertIn(k, meta)
        m_print.assert_called()


if __name__ == "__main__":
    unittest.main()


