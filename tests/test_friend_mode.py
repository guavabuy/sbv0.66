import unittest
from unittest.mock import patch

from friend_mode import (
    RetrievalPack,
    Hit,
    route_query,
    answer_telegram,
    KNOWN_PREFIX,
    UNKNOWN_PREFIX,
    UNKNOWN_SEARCH_PREFIX,
    AMBIGUOUS_PREFIX,
    AMBIGUOUS_INFER_PREFIX,
)


class TestFriendModeRoutingAndTemplates(unittest.TestCase):
    def setUp(self):
        self.thresholds = {"low": 0.25, "high": 0.55, "min_hits": 3}
        self.profile = "USER_PROFILE: demo"
        self.memory = "BRAIN_MEMORY: demo"

    def test_route_known(self):
        r = RetrievalPack(hits=[Hit(text="ctx1", score=0.70), Hit(text="ctx2", score=0.60), Hit(text="ctx3", score=0.50)])
        self.assertEqual(route_query("q", r, self.thresholds), "Known")

    def test_route_unknown(self):
        r = RetrievalPack(hit_count=0, top_score=0.10, hits=[])
        self.assertEqual(route_query("q", r, self.thresholds), "Unknown")

    def test_route_ambiguous_middle_score(self):
        r = RetrievalPack(hits=[Hit(text="maybe1", score=0.40), Hit(text="maybe2", score=0.35), Hit(text="maybe3", score=0.30)])
        self.assertEqual(route_query("q", r, self.thresholds), "Ambiguous")

    def test_route_ambiguous_insufficient_hits_even_if_high_score(self):
        r = RetrievalPack(hits=[Hit(text="maybe", score=0.80), Hit(text="maybe2", score=0.70)])
        self.assertEqual(route_query("q", r, self.thresholds), "Ambiguous")

    def test_answer_templates_unknown(self):
        r = RetrievalPack(hit_count=0, top_score=0.10, hits=[])
        with patch("friend_mode.web_search", return_value=[]) as m:
            out = answer_telegram("q", r, self.profile, self.memory, self.thresholds)
            m.assert_called_once()
        self.assertTrue(out.startswith(UNKNOWN_PREFIX))
        self.assertIn("搜不到", out)
        self.assertIn("网络不可用", out)

    def test_answer_templates_unknown_search_success(self):
        r = RetrievalPack(hit_count=0, top_score=0.10, hits=[])
        fake = [
            {"title": "中美竞争概览", "snippet": "一些摘要", "source": "news", "url": "https://example.com/a"},
            {"title": "另一个来源", "snippet": "更多摘要", "source": "blog", "url": ""},
        ]
        with patch("friend_mode.web_search", return_value=fake) as m:
            out = answer_telegram("你最近怎么看中美之争", r, self.profile, self.memory, self.thresholds)
            m.assert_called_once()
        self.assertTrue(out.startswith(UNKNOWN_PREFIX))
        self.assertIn(UNKNOWN_SEARCH_PREFIX, out)
        self.assertIn("中美竞争概览", out)

    def test_answer_templates_known(self):
        r = RetrievalPack(hits=[Hit(text="hit", score=0.70), Hit(text="hit2", score=0.66), Hit(text="hit3", score=0.60)])
        with patch("friend_mode.web_search", return_value=[]) as m:
            out = answer_telegram("我最近的编程进展如何", r, self.profile, self.memory, self.thresholds)
            # Known 且非时效词：不应触发联网
            m.assert_not_called()
        self.assertTrue(out.startswith(KNOWN_PREFIX))

    def test_answer_templates_ambiguous(self):
        r = RetrievalPack(hits=[Hit(text="maybe", score=0.40), Hit(text="maybe2", score=0.35), Hit(text="maybe3", score=0.30)])
        with patch("friend_mode.web_search", return_value=[]) as m:
            out = answer_telegram("q", r, self.profile, self.memory, self.thresholds)
            # 非“时效词”，不应触发联网
            m.assert_not_called()
        self.assertTrue(out.startswith(AMBIGUOUS_PREFIX))
        self.assertIn(AMBIGUOUS_INFER_PREFIX, out)

    def test_ambiguous_fresh_info_triggers_web_search(self):
        r = RetrievalPack(hits=[Hit(text="maybe", score=0.40), Hit(text="maybe2", score=0.35), Hit(text="maybe3", score=0.30)])
        fake = [{"title": "最新动态", "snippet": "摘要", "source": "news", "url": "https://example.com/x"}]
        with patch("friend_mode.web_search", return_value=fake) as m:
            out = answer_telegram("今天发生了什么最新消息？", r, self.profile, self.memory, self.thresholds)
            m.assert_called_once()
        # DoD：两段固定开头仍必须存在
        self.assertIn(AMBIGUOUS_PREFIX, out)
        self.assertIn(AMBIGUOUS_INFER_PREFIX, out)

    def test_mixed_question_known_and_unknown(self):
        # 第1段应该命中 Known（>=3 hits 且 top_score>=high），第2段应走 Unknown 并触发 web_search
        hits = [
            Hit(text="编程进展：Python AI Agent 开发，我在做 tg bot", score=0.9),
            Hit(text="编程进展：AI Agent 的工具调用与记忆设计", score=0.8),
            Hit(text="编程进展：Python 项目结构与测试策略", score=0.7),
            Hit(text="随便一条不相关内容", score=0.2),
        ]
        r = RetrievalPack(hits=hits)
        with patch("friend_mode.web_search", return_value=[{"title": "中美竞争概览", "snippet": "摘要", "url": "https://example.com/a"}]) as m:
            out = answer_telegram("你最近编程进展如何？另外，你怎么看中美之争？", r, self.profile, self.memory, self.thresholds)
            # Unknown 段会调用一次（Known 段不调用）
            m.assert_called_once()

        self.assertIn(KNOWN_PREFIX, out)
        self.assertIn(UNKNOWN_PREFIX, out)
        self.assertIn(UNKNOWN_SEARCH_PREFIX, out)

    def test_ambiguous_high_risk_disclaimer_invest(self):
        r = RetrievalPack(hits=[Hit(text="maybe", score=0.40), Hit(text="maybe2", score=0.35), Hit(text="maybe3", score=0.30)])
        with patch("friend_mode.web_search", return_value=[]) as m:
            out = answer_telegram("我想投资这个标的，收益怎么样？", r, self.profile, self.memory, self.thresholds)
            m.assert_not_called()
        self.assertIn(AMBIGUOUS_PREFIX, out)
        self.assertIn(AMBIGUOUS_INFER_PREFIX, out)
        self.assertIn("这只是我的推论/不构成建议。", out)

    def test_ambiguous_high_risk_disclaimer_medical(self):
        r = RetrievalPack(hits=[Hit(text="maybe", score=0.40), Hit(text="maybe2", score=0.35), Hit(text="maybe3", score=0.30)])
        # 这里避免被 Card6 分块拆成多段（否则可能触发 Unknown->web_search），只验证免责声明存在
        with patch("friend_mode.web_search", return_value=[]):
            out = answer_telegram("我这个症状需要治疗吗 能帮我诊断吗", r, self.profile, self.memory, self.thresholds)
        self.assertIn("这只是我的推论/不构成建议。", out)

    def test_ambiguous_high_risk_disclaimer_legal(self):
        r = RetrievalPack(hits=[Hit(text="maybe", score=0.40), Hit(text="maybe2", score=0.35), Hit(text="maybe3", score=0.30)])
        with patch("friend_mode.web_search", return_value=[]):
            out = answer_telegram("这个合同条款违法吗 我能起诉吗", r, self.profile, self.memory, self.thresholds)
        self.assertIn("这只是我的推论/不构成建议。", out)


if __name__ == "__main__":
    unittest.main()
