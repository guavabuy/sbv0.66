import pickle
import unittest
from pathlib import Path

from retrieval_adapter import adapt_retrieval


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "retriever_return.pkl"


class TestRetrievalAdapter(unittest.TestCase):
    def test_adapter_basic_shapes(self):
        # dict hits
        raw = {"hits": [{"text": "a", "score": 0.6}, {"text": "b", "score": 0.2}]}
        pack = adapt_retrieval(raw)
        self.assertEqual(pack.hit_count, 2)
        self.assertAlmostEqual(pack.top_score, 0.6, places=6)

        # list of (text, score)
        raw2 = [("c", 0.1), ("d", 0.9)]
        pack2 = adapt_retrieval(raw2)
        self.assertEqual(pack2.hit_count, 2)
        self.assertAlmostEqual(pack2.top_score, 0.9, places=6)

    def test_adapter_real_fixture(self):
        if not FIXTURE_PATH.exists():
            self.fail(
                "缺少真实 retriever fixture：tests/fixtures/retriever_return.pkl\n"
                "请先运行：python3 tests/make_retriever_fixture.py\n"
                "成功后再跑一次单测。"
            )

        with open(FIXTURE_PATH, "rb") as f:
            raw = pickle.load(f)

        pack = adapt_retrieval(raw)

        # 验收点：能拿到 hit_count/top_score/片段文本（至少不崩）
        self.assertIsNotNone(pack)
        self.assertTrue(hasattr(pack, "hit_count"))
        self.assertTrue(hasattr(pack, "top_score"))
        self.assertTrue(hasattr(pack, "hits"))
        self.assertGreaterEqual(pack.hit_count, 0)
        self.assertGreaterEqual(pack.top_score, 0.0)

        if pack.hit_count > 0:
            # 至少应抽到一段文本
            self.assertTrue(any(h.text and h.text.strip() for h in pack.hits))


if __name__ == "__main__":
    unittest.main()
